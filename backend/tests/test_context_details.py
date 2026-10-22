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

    result = await env.manager.context_details(session.session_id)

    assert result["available"] is True
    assert result["context"] == {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}
    assert result["breakdown"]["categories"][0]["name"] == "Messages"
    assert result["breakdown"]["model"] == "claude-opus-5-5"
    assert client.context_usage_details[-1] == "full"
    assert set(result) == {"available", "context", "breakdown"}


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
    assert factory.clients[0].context_usage_details[-1] == "full"

