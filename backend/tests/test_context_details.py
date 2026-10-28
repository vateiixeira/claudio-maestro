"""On-demand `full` context read: `SessionManager.context_details` and its route.

Uses the scripted fake agent; nothing here touches the real SDK.
"""

import asyncio
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultDeny, SDKSessionInfo
from fastapi.testclient import TestClient
from history_fakes import info, now_ms
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

from claudio_maestro import db
from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.fake import text_turn
from claudio_maestro.app import create_app
from claudio_maestro.contextusage import context_breakdown
from claudio_maestro.history import HistoryIndex
from claudio_maestro.sessions import DEFAULT_MODEL_VALUE, SessionNotFoundError

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
async def test_details_session_closed_during_read_without_kept_breakdown_is_failed(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup)
    session.last_breakdown, session.last_breakdown_at = None, None  # nothing kept to show
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
async def test_details_session_closed_during_read_answers_the_kept_breakdown(  # noqa: F811
    make_env, env_cleanup
):
    """The popover was open when the session closed: the last breakdown is still shown."""
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    kept_at = session.last_breakdown_at
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return other_usage(99000)

    replace_read(client, answer)
    pending = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])

    await session.close()
    release.set()
    result = await pending

    assert result["available"] is True and result["live"] is False
    assert result["measured_at"] == kept_at
    assert result["breakdown"] == context_breakdown(FULL_USAGE)  # not the dead read's
    assert result["context"] == {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}


@pytest.mark.anyio
async def test_details_client_replaced_during_read_answers_the_kept_breakdown(  # noqa: F811
    make_env, env_cleanup
):
    env, session, client = await connected(make_env, env_cleanup, usage=FULL_USAGE)
    release = asyncio.Event()

    async def answer(detail):
        await release.wait()
        return other_usage(99000)

    replace_read(client, answer)
    pending = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: client.context_usage_details == ["full"])
    session.client = object()  # type: ignore[assignment]
    release.set()
    result = await pending
    session.client = client

    assert result["available"] is True and result["live"] is False
    assert result["breakdown"] == context_breakdown(FULL_USAGE)


@pytest.mark.anyio
async def test_details_client_replaced_during_read_without_kept_breakdown_is_failed(make_env, env_cleanup):  # noqa: F811
    """The late result of a replaced client never overwrites the context of the new one."""
    env, session, client = await connected(make_env, env_cleanup)
    session.last_breakdown, session.last_breakdown_at = None, None  # nothing kept to show
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
    # Nothing kept, and the temporary process has nothing to show either: only the total.
    await session.close()
    session.last_breakdown = None
    session.last_breakdown_at = None
    env.factory.usage = None

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



# Measuring a closed conversation on demand ----------------------------------


class ProbeFactory(ContextFactory):
    """Fake factory whose clients can hold or fail `get_context_usage`, and that counts
    how many reads run at the same time."""

    def __init__(self) -> None:
        super().__init__()
        self.usage = FULL_USAGE
        self.hold: asyncio.Event | None = None
        self.read_error: Exception | None = None
        self.reading = 0
        self.max_reading = 0
        self.reading_changed = asyncio.Event()

    def __call__(self, options):
        client = super().__call__(options)
        read = client.get_context_usage

        async def gated(detail="full"):
            self.reading += 1
            self.max_reading = max(self.max_reading, self.reading)
            self.reading_changed.set()
            try:
                if self.hold is not None:
                    await self.hold.wait()
                if self.read_error is not None:
                    raise self.read_error
                return await read(detail)
            finally:
                self.reading -= 1

        client.get_context_usage = gated
        return client


def probe_env(make_env, env_cleanup, factory=None):  # noqa: F811
    factory = factory or ProbeFactory()
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    env.manager._history_exists = lambda sid, cwd: True
    return env, factory


def sessions_in_memory(env, count: int):
    return [env.new_session() for _ in range(count)]


def forget(env, session) -> None:
    env.manager.forget_closed()
    assert session.session_id not in env.manager.active_ids()


@pytest.mark.anyio
async def test_closed_session_never_measured_is_measured_on_demand(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    session.record.model = "haiku"
    before = time.time()

    result = await env.manager.context_details(session.session_id)

    after = time.time()
    assert result["available"] is True and result["live"] is False
    assert before <= result["measured_at"] <= after
    assert result["breakdown"] == context_breakdown(FULL_USAGE)
    assert result["context"] == {"used_tokens": 84800, "max_tokens": 400000, "percent": 21.2}
    (client,) = factory.clients
    assert client.context_usage_details == ["full"]
    assert client.sent == [] and client.closed
    options = client.options
    assert options.session_id == session.session_id
    assert options.resume is True and options.fork_session is True
    assert options.cwd == Path(session.record.work_dir())
    assert options.model == "haiku"
    assert options.settings == '{"disableAllHooks": true}'
    assert options.setting_sources is None
    assert options.agentd is None and options.attach is None
    denied = await options.can_use_tool("Bash", {"command": "ls"}, None)
    assert isinstance(denied, PermissionResultDeny)
    # What the probe measured is what the session keeps for the next time.
    assert session.last_breakdown == result["breakdown"]
    assert session.last_breakdown_at == result["measured_at"]


@pytest.mark.anyio
async def test_default_model_is_not_passed_to_the_probe(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    session.record.model = DEFAULT_MODEL_VALUE

    await env.manager.context_details(session.session_id)

    assert factory.clients[0].options.model is None


@pytest.mark.anyio
async def test_second_call_uses_the_kept_breakdown_without_measuring_again(  # noqa: F811
    make_env, env_cleanup
):
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()

    first = await env.manager.context_details(session.session_id)
    second = await env.manager.context_details(session.session_id)

    assert len(factory.clients) == 1
    assert second == first


@pytest.mark.anyio
async def test_forgotten_session_is_measured_and_kept_in_the_manager(  # noqa: F811
    make_env, env_cleanup
):
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    forget(env, session)

    first = await env.manager.context_details(session.session_id)

    assert first["available"] is True and first["live"] is False
    assert env.manager._kept_breakdowns[session.session_id] == (
        first["breakdown"], first["measured_at"],
    )
    assert await env.manager.context_details(session.session_id) == first
    assert len(factory.clients) == 1


@pytest.mark.anyio
async def test_simultaneous_calls_share_one_measurement(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()
    session = env.new_session()

    first = asyncio.create_task(env.manager.context_details(session.session_id))
    second = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)
    await asyncio.sleep(0.01)
    factory.hold.set()
    results = await asyncio.gather(first, second)

    assert len(factory.clients) == 1
    assert results[0] == results[1] and results[0]["available"] is True


@pytest.mark.anyio
async def test_two_sessions_are_measured_one_at_a_time(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()
    one, two = sessions_in_memory(env, 2)

    first = asyncio.create_task(env.manager.context_details(one.session_id))
    await wait_until(lambda: factory.reading == 1)
    second = asyncio.create_task(env.manager.context_details(two.session_id))
    await asyncio.sleep(0.05)
    assert len(factory.clients) == 1  # the second waits for its turn: no process yet

    factory.hold.set()
    results = await asyncio.gather(first, second)

    assert all(result["available"] is True for result in results)
    assert len(factory.clients) == 2 and factory.max_reading == 1
    assert all(client.closed for client in factory.clients)


@pytest.mark.anyio
async def test_a_queued_measurement_nobody_waits_for_is_dropped(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()
    one, two = sessions_in_memory(env, 2)
    first = asyncio.create_task(env.manager.context_details(one.session_id))
    await wait_until(lambda: factory.reading == 1)
    second = asyncio.create_task(env.manager.context_details(two.session_id))
    await asyncio.sleep(0.02)

    second.cancel()
    await asyncio.wait([second])
    factory.hold.set()
    await first

    assert len(factory.clients) == 1  # the abandoned queued one never started a process
    assert env.manager._probes == {}


@pytest.mark.anyio
async def test_caller_cancelled_while_measuring_does_not_leave_the_process_open(  # noqa: F811
    make_env, env_cleanup
):
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()
    session = env.new_session()
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)

    caller.cancel()
    await asyncio.wait([caller])
    # The measurement is not wasted: it ends on its own (here, now) and closes the process.
    factory.hold.set()
    await wait_until(lambda: env.manager._probes == {})

    assert factory.clients[0].closed
    assert session.last_breakdown == context_breakdown(FULL_USAGE)


@pytest.mark.anyio
async def test_shutdown_closes_a_measurement_in_flight(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()  # never opens
    session = env.new_session()
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)

    await env.manager.shutdown()
    await asyncio.wait([caller])

    assert factory.clients[0].closed and env.manager._probes == {}
    assert caller.result()["available"] is False


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["error", "timeout", "no_data", "unusable"])
async def test_failed_measurement_is_no_process_and_keeps_nothing(  # noqa: F811
    make_env, env_cleanup, monkeypatch, failure
):
    env, factory = probe_env(make_env, env_cleanup)
    if failure == "error":
        factory.read_error = AgentError("quebrou")
    elif failure == "timeout":
        factory.hold = asyncio.Event()  # never opens
        monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_PROBE_LIMIT", 0.05)
    elif failure == "no_data":
        factory.usage = None
    else:
        factory.usage = {"totalTokens": "x"}
    session = env.new_session()

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": None}
    assert session.last_breakdown is None and session.last_breakdown_at is None
    assert env.manager._kept_breakdowns == {}
    assert factory.clients[0].closed
    assert env.manager._probes == {}


@pytest.mark.anyio
async def test_failed_measurement_of_a_forgotten_session_keeps_nothing(  # noqa: F811
    make_env, env_cleanup
):
    env, factory = probe_env(make_env, env_cleanup)
    factory.read_error = AgentError("quebrou")
    session = env.new_session()
    forget(env, session)

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": None}
    assert env.manager._kept_breakdowns == {}


@pytest.mark.anyio
async def test_connect_failure_is_no_process(make_env, env_cleanup):  # noqa: F811
    factory = ProbeFactory()
    factory.connect_error = AgentError("não abriu")
    env, _ = probe_env(make_env, env_cleanup, factory)
    session = env.new_session()

    result = await env.manager.context_details(session.session_id)

    assert result["available"] is False and result["reason"] == "no_process"
    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_a_factory_that_refuses_is_no_process(make_env, env_cleanup):  # noqa: F811
    """The E2E server's factory raises `AgentError` for every client."""

    def refuse(options):
        raise AgentError("O servidor de E2E não inicia o agente real.")

    env, _ = probe_env(make_env, env_cleanup, refuse)
    session = env.new_session()

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": None}


@pytest.mark.anyio
async def test_session_with_a_client_is_not_measured_by_a_probe(make_env, env_cleanup):  # noqa: F811
    env, session, client = await connected(make_env, env_cleanup, usage=SDK_USAGE)

    result = await env.manager.context_details(session.session_id)

    assert result["live"] is True
    assert env.factory.clients == [client]


@pytest.mark.anyio
@pytest.mark.parametrize("busy", ["connecting", "turn", "prompt", "history_missing"])
async def test_session_in_use_or_without_history_is_not_measured(  # noqa: F811
    make_env, env_cleanup, busy
):
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    if busy == "connecting":
        session._connecting = True
    elif busy == "turn":
        session.pending_turns = 1
    elif busy == "prompt":
        session.prompts["p1"] = object()  # type: ignore[assignment]
    else:
        env.manager._history_exists = lambda sid, cwd: False

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": None}
    assert factory.clients == []


@pytest.mark.anyio
async def test_unknown_session_is_still_not_found_before_any_probe(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)

    with pytest.raises(SessionNotFoundError):
        await env.manager.context_details("não-existe")

    assert factory.clients == []


@pytest.mark.anyio
async def test_probe_result_does_not_overwrite_a_newer_live_breakdown(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    factory.hold = asyncio.Event()
    session = env.new_session()
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)

    # A live client measured the session while the probe was still running.
    live = context_breakdown(other_usage(120000))
    session.last_breakdown, session.last_breakdown_at = live, time.time()
    factory.hold.set()
    result = await caller

    assert result["available"] is True
    assert session.last_breakdown == live


@pytest.mark.anyio
async def test_a_kept_breakdown_is_never_measured_again_by_a_probe(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    env.manager._kept_breakdowns[session.session_id] = (context_breakdown(other_usage(1000)), 1.0)
    forget(env, session)
    env.manager._kept_breakdowns[session.session_id] = (context_breakdown(other_usage(1000)), 1.0)

    result = await env.manager.context_details(session.session_id)

    assert result["breakdown"]["total_tokens"] == 1000
    assert factory.clients == []


def test_route_with_a_refusing_agent_factory_stays_no_process(monkeypatch, home):
    """The E2E server refuses to start any agent: the temporary process fails the same way."""

    def refuse(options):
        raise AgentError("O servidor de E2E não inicia o agente real.")

    monkeypatch.setattr("claudio_maestro.history.sdk_read_context", lambda sid, cwd: None)
    monkeypatch.setattr("claudio_maestro.history.sdk_session_file_mtime", lambda sid, cwd: 1000.0)
    app = create_app(agent_factory=refuse, history_exists=lambda sid, cwd: True)
    headers = {"origin": APP_ORIGIN, "x-maestro": "1"}
    with TestClient(app, base_url=BACKEND_URL, headers=headers) as client:
        sid = api_session(client, home)["session_id"]

        response = client.get(f"/api/sessions/{sid}/context")

    assert response.status_code == 200
    assert response.json() == NO_PROCESS


# A conversation the agentd may still hold is never measured -------------------


@pytest.mark.anyio
async def test_a_session_the_agentd_may_hold_is_not_measured(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    env.manager._agentd_held.add(session.session_id)

    result = await env.manager.context_details(session.session_id)

    assert result == {"available": False, "reason": "no_process", "context": None}
    assert factory.clients == []

    # Once the agentd no longer holds it, the measurement is allowed again.
    env.manager._agentd_held.discard(session.session_id)
    result = await env.manager.context_details(session.session_id)
    assert result["available"] is True and len(factory.clients) == 1


# A client that leaves cancels the measurement still in line ---------------------


def asgi_scope(path: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1:6660"),
            (b"origin", APP_ORIGIN.encode()),
            (b"x-maestro", b"1"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 6660),
    }


class Call:
    """One HTTP request driven straight through the ASGI app, with a client that can hang
    up (the test client of Starlette never does)."""

    def __init__(self, app, path: str) -> None:
        self.hangup = asyncio.Event()
        self.sent: list[dict[str, Any]] = []
        self._body_sent = False
        self.task = asyncio.create_task(app(asgi_scope(path), self._receive, self._send))

    async def _receive(self) -> dict[str, Any]:
        if not self._body_sent:
            self._body_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.hangup.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    def body(self) -> dict[str, Any]:
        import json

        data = b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")
        return json.loads(data)


@pytest.mark.anyio
async def test_a_client_that_hangs_up_drops_its_queued_measurement(home):
    import httpx

    factory = ProbeFactory()
    factory.hold = asyncio.Event()
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: True)
    headers = {"origin": APP_ORIGIN, "x-maestro": "1"}
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url=BACKEND_URL, headers=headers
        ) as api:
            folder = home / "app"
            folder.mkdir()
            project = (
                await api.post("/api/projects", json={"name": "app", "path": str(folder), "color": "#ff8800"})
            ).json()
            first = (await api.post(f"/api/projects/{project['id']}/sessions")).json()
            second = (await api.post(f"/api/projects/{project['id']}/sessions")).json()
        manager = app.state.sessions

        one = Call(app, f"/api/sessions/{first['session_id']}/context")
        await wait_until(lambda: factory.reading == 1)
        two = Call(app, f"/api/sessions/{second['session_id']}/context")
        await wait_until(lambda: len(manager._probes) == 2)

        two.hangup.set()
        await asyncio.wait_for(two.task, 2)

        assert set(manager._probes) == {first["session_id"]}
        factory.hold.set()
        await asyncio.wait_for(one.task, 2)
        assert one.body()["available"] is True
        assert len(factory.clients) == 1  # the second one never opened a process
        assert manager._probes == {}


# The copy a measurement opens must never show up as a session ---------------------


def projects_folder(tmp_path: Path) -> Path:
    """The CLI's projects folder the manager uses in tests (see conftest)."""
    return tmp_path / "claude-config" / "projects"


class ForkWritingFactory(ProbeFactory):
    """Clients that write `<fork id>.jsonl` (and a folder) under the ORIGINAL cwd's history
    folder while connecting, the way the CLI does when it loads a conversation that had a
    live background subagent."""

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder

    def __call__(self, options):
        client = super().__call__(options)
        connect = client.connect

        async def writing_connect():
            await connect()
            self.folder.mkdir(parents=True, exist_ok=True)
            (self.folder / f"{options.fork_session_id}.jsonl").write_text('{"type":"x"}\n')
            (self.folder / options.fork_session_id).mkdir(exist_ok=True)

        client.connect = writing_connect
        return client


def fork_env(make_env, env_cleanup, tmp_path):  # noqa: F811
    folder = projects_folder(tmp_path) / "-home-original"
    factory = ForkWritingFactory(folder)
    env, _ = probe_env(make_env, env_cleanup, factory)
    return env, factory, folder


@pytest.mark.anyio
async def test_the_copy_gets_an_id_of_its_own(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()

    await env.manager.context_details(session.session_id)

    options = factory.clients[0].options
    assert options.resume is True and options.fork_session is True
    assert options.session_id == session.session_id
    fork_id = options.fork_session_id
    assert fork_id and fork_id != session.session_id
    assert str(uuid.UUID(fork_id)) == fork_id
    assert env.manager.is_throwaway(fork_id)
    assert not env.manager.is_throwaway(session.session_id)


@pytest.mark.anyio
async def test_each_measurement_gets_a_new_id(make_env, env_cleanup):  # noqa: F811
    env, factory = probe_env(make_env, env_cleanup)
    session = env.new_session()
    await env.manager.context_details(session.session_id)
    forget(env, session)
    env.manager._kept_breakdowns.clear()
    session = env.manager.get(session.session_id)
    session.last_breakdown = session.last_breakdown_at = None

    await env.manager.context_details(session.session_id)

    ids = [c.options.fork_session_id for c in factory.clients]
    assert len(ids) == 2 and len(set(ids)) == 2


@pytest.mark.anyio
async def test_the_copy_file_is_deleted_and_never_listed(  # noqa: F811
    make_env, env_cleanup, tmp_path
):
    env, factory, folder = fork_env(make_env, env_cleanup, tmp_path)
    session = env.new_session()
    original = folder / f"{session.session_id}.jsonl"
    folder.mkdir(parents=True)
    original.write_text("{}\n")
    index = HistoryIndex(
        env.db_path, lambda directory: listed_files(folder, env.project.path),
        folder_signature=lambda directory: None, is_throwaway=env.manager.is_throwaway,
    )
    factory.hold = asyncio.Event()
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)
    fork_id = factory.clients[0].options.fork_session_id
    assert (folder / f"{fork_id}.jsonl").is_file()  # the file exists mid-measurement

    await index.sync_all()  # the periodic sync (and the cliwatch) run now
    assert fork_id not in db_session_ids(env.db_path)

    factory.hold.set()
    result = await caller

    assert result["available"] is True
    await wait_until(lambda: not (folder / f"{fork_id}.jsonl").exists())
    assert not (folder / fork_id).exists()
    assert original.is_file()  # the real conversation is untouched
    await index.sync_all()
    assert fork_id not in db_session_ids(env.db_path)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["error", "timeout", "cancelled"])
async def test_the_copy_file_is_deleted_when_the_measurement_fails(  # noqa: F811
    make_env, env_cleanup, tmp_path, monkeypatch, failure
):
    env, factory, folder = fork_env(make_env, env_cleanup, tmp_path)
    session = env.new_session()
    if failure == "error":
        factory.read_error = AgentError("quebrou")
    else:
        factory.hold = asyncio.Event()  # never opens
    if failure == "timeout":
        monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_PROBE_LIMIT", 0.05)
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    if failure == "cancelled":
        await wait_until(lambda: factory.reading == 1)
        caller.cancel()
        await env.manager.shutdown()  # cancels the measurement itself
    await asyncio.wait([caller])

    fork_id = factory.clients[0].options.fork_session_id
    await wait_until(lambda: not (folder / f"{fork_id}.jsonl").exists())
    assert not (folder / fork_id).exists()
    assert env.manager.is_throwaway(fork_id)


@pytest.mark.anyio
async def test_the_copy_file_is_deleted_when_the_close_outlives_the_limit(  # noqa: F811
    make_env, env_cleanup, tmp_path, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.contextprobe.CLOSE_LIMIT", 0.05)
    env, factory, folder = fork_env(make_env, env_cleanup, tmp_path)
    close_gate = asyncio.Event()
    make = factory.__call__

    def slow_close_factory(options):
        client = make(options)
        close = client.close

        async def slow_close():
            await close_gate.wait()
            await close()

        client.close = slow_close
        return client

    env.manager._agent_factory = slow_close_factory
    session = env.new_session()

    await env.manager.context_details(session.session_id)

    fork_id = factory.clients[0].options.fork_session_id
    assert (folder / f"{fork_id}.jsonl").is_file()  # the process is still going away
    close_gate.set()
    await wait_until(lambda: not (folder / f"{fork_id}.jsonl").exists())


@pytest.mark.anyio
async def test_another_sessions_file_is_never_deleted(  # noqa: F811
    make_env, env_cleanup, tmp_path
):
    env, factory, folder = fork_env(make_env, env_cleanup, tmp_path)
    session = env.new_session()
    other = "11111111-2222-4333-8444-555555555555"
    folder.mkdir(parents=True)
    (folder / f"{other}.jsonl").write_text("{}\n")
    (folder / f"{session.session_id}.jsonl").write_text("{}\n")
    elsewhere = projects_folder(tmp_path) / "-home-other"
    elsewhere.mkdir(parents=True)
    (elsewhere / f"{other}.jsonl").write_text("{}\n")

    await env.manager.context_details(session.session_id)

    fork_id = factory.clients[0].options.fork_session_id
    await wait_until(lambda: not (folder / f"{fork_id}.jsonl").exists())
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [f"{other}.jsonl", f"{session.session_id}.jsonl"]
    )
    assert (elsewhere / f"{other}.jsonl").is_file()


@pytest.mark.anyio
async def test_a_row_of_the_copy_that_got_in_is_removed(  # noqa: F811
    make_env, env_cleanup, tmp_path
):
    env, factory, _folder = fork_env(make_env, env_cleanup, tmp_path)
    session = env.new_session()
    factory.hold = asyncio.Event()
    caller = asyncio.create_task(env.manager.context_details(session.session_id))
    await wait_until(lambda: factory.reading == 1)
    fork_id = factory.clients[0].options.fork_session_id
    # Some path other than the guarded ones registered the copy.
    with closing(db.connect(env.db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
            " last_activity_at, last_seen_at, finished, file_modified_at)"
            " VALUES (?, ?, ?, 'cópia', 1, 1, 1, 0, 1)",
            (fork_id, env.project.id, env.project.path),
        )
    env.recorder.envelopes.clear()

    factory.hold.set()
    await caller

    await wait_until(lambda: fork_id not in db_session_ids(env.db_path))
    assert session.session_id in db_session_ids(env.db_path)
    await wait_until(
        lambda: any(
            e["type"] == "project.synced" and e["data"] == {"project_id": env.project.id}
            for e in env.recorder.envelopes
        )
    )


def listed_files(folder: Path, cwd: str) -> list[SDKSessionInfo]:
    """What the SDK's `list_sessions` would answer: one entry per session file."""
    if not folder.is_dir():
        return []
    return [
        info(path.stem, cwd, first_prompt="mesmo título", modified_ms=now_ms())
        for path in folder.glob("*.jsonl")
    ]


def db_session_ids(db_path: Path) -> set[str]:
    with closing(db.connect(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT session_id FROM sessions")}
