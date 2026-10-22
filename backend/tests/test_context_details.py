"""On-demand `full` context read: `SessionManager.context_details` and its route.

Uses the scripted fake agent; nothing here touches the real SDK.
"""

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_context_breakdown import FULL_USAGE
from test_context_permission import (
    APP_ORIGIN,
    BACKEND_URL,
    SDK_USAGE,
    ContextFactory,
    api_session,
    env_cleanup,  # noqa: F401  (fixture)
    make_env,  # noqa: F401  (fixture)
)
from test_sessions import by_session, wait_until

from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.fake import text_turn
from claudio_maestro.app import create_app
from claudio_maestro.contextusage import context_breakdown
from claudio_maestro.sessions import SessionNotFoundError

NO_PROCESS = {"available": False, "reason": "no_process", "context": None}


async def connected(make_env, env_cleanup, *, usage=SDK_USAGE):  # noqa: F811
    """Session with one finished turn; its client answers `usage` to the summary read."""
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = ContextFactory(script)
    factory.usage = usage
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)
    return env, session, env.factory.clients[0]


def replace_read(client, answer):
    """Replace `get_context_usage` by `answer(detail)`, counting the calls per detail."""
    client.context_usage_details.clear()
    original = client.get_context_usage

    async def read(detail="full"):
        client.context_usage_details.append(detail)
        return await answer(detail)

    client.get_context_usage = read
    return original


@pytest.mark.anyio
async def test_details_unknown_session_raises(make_env, env_cleanup):  # noqa: F811
    env = make_env()
    env_cleanup.append(env.manager)
    with pytest.raises(SessionNotFoundError):
        await env.manager.context_details("não-existe")


@pytest.mark.anyio
async def test_details_without_client_is_no_process(make_env, env_cleanup):  # noqa: F811
    env = make_env()
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    # Not in memory yet: nothing is loaded just to answer.
    assert await env.manager.context_details(record.session_id) == NO_PROCESS
    assert record.session_id not in env.manager.active_ids()

    # In memory without a client (history): the last known context goes along.
    session = env.manager.get(record.session_id)
    session.context = {"used_tokens": 1000, "max_tokens": 200000, "percent": 0.5}
    assert await env.manager.context_details(record.session_id) == {
        "available": False,
        "reason": "no_process",
        "context": session.context,
    }


@pytest.mark.anyio
async def test_details_with_client_reads_full_and_normalizes(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    client.context_usage = FULL_USAGE
    before = time.time()

    result = await env.manager.context_details(session.session_id)

    assert result["available"] is True
    assert result["context"] == {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}
    assert result["breakdown"]["categories"][0]["name"] == "Messages"
    assert result["breakdown"]["model"] == "claude-opus-5-5"
    assert client.context_usage_details[-1] == "full"
    assert set(result) == {"available", "live", "measured_at", "context", "breakdown"}
    assert result["live"] is True
    assert before <= result["measured_at"] <= time.time()


@pytest.mark.anyio
async def test_details_updates_session_context_and_emits(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    assert session.context["used_tokens"] == 50_000
    before = len(env.recorder.of(session.session_id, "session.updated"))
    client.context_usage = FULL_USAGE

    await env.manager.context_details(session.session_id)

    expected = {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}
    assert session.context == expected
    updates = env.recorder.of(session.session_id, "session.updated")
    assert len(updates) == before + 1
    assert updates[-1]["data"]["context"] == expected
    assert "breakdown" not in updates[-1]["data"]["context"]

    # Same total again: nothing changed, nothing announced.
    await env.manager.context_details(session.session_id)
    assert len(env.recorder.of(session.session_id, "session.updated")) == before + 1


@pytest.mark.anyio
async def test_details_concurrent_calls_share_one_read(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return FULL_USAGE

    replace_read(client, answer)
    first = asyncio.create_task(env.manager.context_details(session.session_id))
    second = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    await asyncio.sleep(0.01)
    release.set()
    r1, r2 = await asyncio.gather(first, second)

    assert client.context_usage_details.count("full") == 1
    assert r1 == r2 and r1["available"] is True
    # Done: the next request reads again.
    release.set()
    await env.manager.context_details(session.session_id)
    assert client.context_usage_details.count("full") == 2


@pytest.mark.anyio
async def test_details_caller_cancelled_does_not_cancel_the_read(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()
    stats = {"cancelled": 0}

    async def answer(detail):
        try:
            await release.wait()
        except asyncio.CancelledError:
            stats["cancelled"] += 1
            raise
        return FULL_USAGE

    replace_read(client, answer)
    first = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert stats["cancelled"] == 0

    second = asyncio.create_task(env.manager.context_details(session.session_id))
    await asyncio.sleep(0.01)
    release.set()
    assert (await second)["available"] is True
    assert client.context_usage_details == ["full"]


@pytest.mark.anyio
async def test_details_timeout_answers_and_keeps_call_tracked(  # noqa: F811
    make_env, env_cleanup, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_READ_LIMIT", 0.05)
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()
    stats = {"cancelled": 0}

    async def answer(detail):
        try:
            await release.wait()
        except asyncio.CancelledError:
            stats["cancelled"] += 1
            raise
        return FULL_USAGE

    replace_read(client, answer)
    result = await env.manager.context_details(session.session_id)

    assert result["reason"] == "timeout"
    assert result["available"] is False
    assert result["context"] == session.context  # the last known value
    assert stats["cancelled"] == 0
    assert len(session._context_calls) == 1  # abandoned, not cancelled, still tracked

    # The late answer is discarded.
    release.set()
    await asyncio.sleep(0.02)
    assert session.context["used_tokens"] == 50_000

    await session.close()
    assert session._context_calls == set()


@pytest.mark.anyio
async def test_details_timeout_call_is_cancelled_on_close(  # noqa: F811
    make_env, env_cleanup, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_READ_LIMIT", 0.05)
    env, session, client = await connected(make_env, env_cleanup)
    stats = {"cancelled": 0}

    async def answer(detail):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stats["cancelled"] += 1
            raise

    replace_read(client, answer)
    assert (await env.manager.context_details(session.session_id))["reason"] == "timeout"
    await session.close()
    await wait_until(lambda: stats["cancelled"] == 1)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (AgentError("unsupported control request subtype: get_context_usage"), "unsupported"),
        (AgentError("Unknown control request"), "unsupported"),
        (AgentError("unrecognized subtype 'x'"), "unsupported"),
        (RuntimeError("quebrou"), "failed"),
        (AgentError("sem dados"), "failed"),
    ],
)
async def test_details_errors_are_classified(make_env, env_cleanup, error, reason):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)

    async def answer(detail):
        raise error

    replace_read(client, answer)
    result = await env.manager.context_details(session.session_id)

    assert result["available"] is False and result["reason"] == reason
    assert session.context["used_tokens"] == 50_000


@pytest.mark.anyio
@pytest.mark.parametrize("usage", [None, {"totalTokens": "muito", "maxTokens": 0}, [1]])
async def test_details_unusable_response_is_failed(make_env, env_cleanup, usage):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    client.context_usage = usage

    result = await env.manager.context_details(session.session_id)

    assert result["available"] is False and result["reason"] == "failed"
    assert session.context["used_tokens"] == 50_000


@pytest.mark.anyio
async def test_details_session_closed_during_read_is_failed(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return FULL_USAGE

    replace_read(client, answer)
    pending = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])

    await session.close()
    release.set()
    result = await pending

    assert result["available"] is False
    assert result["reason"] in {"failed", "no_process"}
    assert session.context["used_tokens"] == 50_000  # untouched by the dead read
    assert session._context_calls == set()


@pytest.mark.anyio
async def test_details_client_replaced_during_read_is_failed(make_env, env_cleanup):  # noqa: F811
    """The late result of a replaced client never overwrites the context of the new one."""
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return FULL_USAGE

    replace_read(client, answer)
    pending = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    # Replace the client without the normal teardown (which would cancel the read).
    session.client = object()  # type: ignore[assignment]
    release.set()
    result = await pending
    session.client = client

    assert result["available"] is False and result["reason"] == "failed"
    assert session.context["used_tokens"] == 50_000


@pytest.mark.anyio
async def test_details_do_not_hold_the_turn_or_other_reads(make_env, env_cleanup):  # noqa: F811
    """A `full` read pending does not stop the per-turn summary read from running."""
    env, session, client = await connected(make_env, env_cleanup)
    release = asyncio.Event()

    async def answer(detail):
        if detail == "full":
            await release.wait()
        return FULL_USAGE

    replace_read(client, answer)
    pending = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    session._request_context(client)
    await wait_until(lambda: client.context_usage_details == ["full", "summary"])
    release.set()
    assert (await pending)["available"] is True


# Last measured breakdown kept in memory ------------------------------------


def other_usage(total: int) -> dict[str, Any]:
    return {**FULL_USAGE, "totalTokens": total}


@pytest.mark.anyio
async def test_closed_session_answers_the_last_summary_breakdown(make_env, env_cleanup):  # noqa: F811
    before = time.time()
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    after = time.time()
    assert session.last_breakdown == context_breakdown(FULL_USAGE)
    assert before <= session.last_breakdown_at <= after

    await session.close()
    result = await env.manager.context_details(session.session_id)

    assert result == {
        "available": True,
        "live": False,
        "measured_at": session.last_breakdown_at,
        "context": {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2},
        "breakdown": context_breakdown(FULL_USAGE),
    }
    assert client.context_usage_details == ["summary"]  # nothing was read to answer


@pytest.mark.anyio
async def test_full_read_updates_the_kept_breakdown(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    summary_at = session.last_breakdown_at
    await asyncio.sleep(0.01)
    client.context_usage = other_usage(90000)

    live = await env.manager.context_details(session.session_id)

    assert live["live"] is True and live["breakdown"]["total_tokens"] == 90000
    assert live["measured_at"] > summary_at
    assert session.last_breakdown == live["breakdown"]
    assert session.last_breakdown_at == live["measured_at"]

    await session.close()
    closed = await env.manager.context_details(session.session_id)
    assert closed["live"] is False
    assert closed["breakdown"]["total_tokens"] == 90000
    assert closed["measured_at"] == live["measured_at"]


@pytest.mark.anyio
async def test_a_newer_summary_replaces_the_kept_full(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    client.context_usage = other_usage(90000)
    await env.manager.context_details(session.session_id)
    full_at = session.last_breakdown_at
    await asyncio.sleep(0.01)

    client.context_usage = other_usage(95000)
    session._request_context(client)
    await wait_until(lambda: session.last_breakdown["total_tokens"] == 95000)

    assert session.last_breakdown_at > full_at


@pytest.mark.anyio
async def test_unusable_summary_keeps_the_last_breakdown(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    kept, kept_at = session.last_breakdown, session.last_breakdown_at
    client.context_usage = None
    session._request_context(client)
    await wait_until(lambda: client.context_usage_details == ["summary", "summary"])
    await asyncio.sleep(0.01)

    assert (session.last_breakdown, session.last_breakdown_at) == (kept, kept_at)


@pytest.mark.anyio
async def test_failed_full_read_keeps_the_last_breakdown(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    kept, kept_at = session.last_breakdown, session.last_breakdown_at

    async def answer(detail):
        raise RuntimeError("quebrou")

    replace_read(client, answer)
    result = await env.manager.context_details(session.session_id)

    assert result["available"] is False and result["reason"] == "failed"
    assert (session.last_breakdown, session.last_breakdown_at) == (kept, kept_at)


@pytest.mark.anyio
async def test_replaced_client_result_does_not_write_the_kept_breakdown(  # noqa: F811
    make_env, env_cleanup
):
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    kept, kept_at = session.last_breakdown, session.last_breakdown_at
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return other_usage(99000)

    replace_read(client, answer)
    full = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    session._request_context(client)
    await wait_until(lambda: client.context_usage_details == ["full", "summary"])
    session.client = object()  # type: ignore[assignment]
    release.set()
    await full
    await asyncio.sleep(0.02)
    session.client = client

    assert (session.last_breakdown, session.last_breakdown_at) == (kept, kept_at)


@pytest.mark.anyio
async def test_forgotten_session_keeps_the_last_breakdown(make_env, env_cleanup):  # noqa: F811
    env, session, _client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    sid, measured_at = session.session_id, session.last_breakdown_at
    await session.close()

    env.manager.forget_closed()
    assert sid not in env.manager.active_ids()
    result = await env.manager.context_details(sid)

    assert result == {
        "available": True,
        "live": False,
        "measured_at": measured_at,
        "context": {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2},
        "breakdown": context_breakdown(FULL_USAGE),
    }
    assert sid not in env.manager.active_ids()  # answering does not load the session

    # Back in memory, the session has it again.
    restored = env.manager.get(sid)
    assert restored.last_breakdown == context_breakdown(FULL_USAGE)
    assert restored.last_breakdown_at == measured_at
    again = await env.manager.context_details(sid)
    assert again["live"] is False and again["measured_at"] == measured_at


@pytest.mark.anyio
async def test_kept_breakdowns_are_limited_to_the_most_recent(  # noqa: F811
    make_env, env_cleanup, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.sessions.KEPT_BREAKDOWN_LIMIT", 2)
    env = make_env()
    env_cleanup.append(env.manager)
    ids = []
    for total in (1000, 2000, 3000):
        record = env.manager.create_session(env.project)
        session = env.manager.get(record.session_id)
        session.last_breakdown = context_breakdown(other_usage(total))
        session.last_breakdown_at = float(total)
        ids.append(record.session_id)
    env.manager.forget_closed()

    assert list(env.manager._kept_breakdowns) == ids[1:]
    assert (await env.manager.context_details(ids[0])) == NO_PROCESS
    assert (await env.manager.context_details(ids[2]))["breakdown"]["total_tokens"] == 3000


@pytest.mark.anyio
async def test_session_that_never_measured_stays_no_process(make_env, env_cleanup):  # noqa: F811
    env, session, _client = await connected(make_env, env_cleanup, usage=SDK_USAGE)
    # The summary came without categories: nothing to show, but the total still counts.
    await session.close()
    session.last_breakdown = None
    session.last_breakdown_at = None

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": session.context}


# Route ---------------------------------------------------------------------


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch):
    factory = ContextFactory()
    factory.usage = FULL_USAGE
    monkeypatch.setattr("claudio_maestro.history.sdk_read_context", lambda sid, cwd: None)
    monkeypatch.setattr("claudio_maestro.history.sdk_session_file_mtime", lambda sid, cwd: 1000.0)
    app = create_app(
        agent_factory=factory,
        history_exists=lambda sid, cwd: any(c.options.session_id == sid and c.sent for c in factory.clients),
    )
    headers = {"origin": APP_ORIGIN, "x-maestro": "1"}
    with TestClient(app, base_url=BACKEND_URL, headers=headers) as client:
        client.factory = factory  # type: ignore[attr-defined]
        yield client


def test_route_returns_details_and_404(api_client, home):
    sid = api_session(api_client, home)["session_id"]

    # No process yet.
    response = api_client.get(f"/api/sessions/{sid}/context")
    assert response.status_code == 200
    assert response.json() == NO_PROCESS

    assert api_client.get("/api/sessions/nao-existe/context").status_code == 404

    # Without the header the API refuses, like every other route.
    bare = TestClient(api_client.app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN})
    assert bare.get(f"/api/sessions/{sid}/context").status_code in {400, 403}


def test_route_reads_full_with_a_connected_client(api_client, home):
    sid = api_session(api_client, home)["session_id"]
    factory: ContextFactory = api_client.factory  # type: ignore[attr-defined]
    factory.script = lambda content: text_turn(sid, "oi")
    api_client.post(f"/api/sessions/{sid}/messages", json={"text": "olá"})
    deadline = time.monotonic() + 2
    while api_client.get(f"/api/sessions/{sid}").json()["state"] != "idle":
        assert time.monotonic() < deadline
        time.sleep(0.01)

    body: dict[str, Any] = api_client.get(f"/api/sessions/{sid}/context").json()

    assert body["available"] is True
    assert body["context"] == {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}
    assert body["breakdown"]["categories"][0]["name"] == "Messages"
    assert body["live"] is True and isinstance(body["measured_at"], float)
    assert factory.clients[0].context_usage_details[-1] == "full"

