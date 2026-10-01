"""Context usage and pending tool permission in the session summary.

Uses the scripted fake agent and injected history readers; nothing here starts
the `claude` process or reads the real SDK history.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ToolPermissionContext
from fastapi.testclient import TestClient
from test_agent_sdk_client import StubSdkClient, make_options
from test_sessions import Env, by_session, fake_history, wait_until

from claudio_maestro import history as history_module
from claudio_maestro.agent.base import AgentClient, AgentError
from claudio_maestro.agent.fake import (
    FakeAgentClient,
    FakeAgentFactory,
    text_turn,
    tool_turn,
)
from claudio_maestro.agent.sdk_client import SdkAgentClient
from claudio_maestro.app import create_app
from claudio_maestro.sessions import SessionManager

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"

SDK_USAGE = {
    "categories": [],
    "totalTokens": 50_000,
    "maxTokens": 167_000,
    "rawMaxTokens": 200_000,
    "percentage": 29.9,  # over maxTokens: not the base of the maximum shown
    "model": "claude-opus-5-5",
}


@pytest.fixture
def make_env(tmp_path: Path):
    def build(script=None, factory=None, **manager_kwargs) -> Env:
        factory = factory or FakeAgentFactory(script=script)
        env = Env(tmp_path, factory)
        if manager_kwargs:
            env.manager = SessionManager(
                env.db_path, env.recorder, agent_factory=factory,
                history_exists=fake_history(factory), **manager_kwargs,
            )
        return env

    return build


@pytest.fixture
async def env_cleanup():
    managers: list[SessionManager] = []
    yield managers
    for manager in managers:
        await manager.shutdown()


# Agent interface -----------------------------------------------------------


def test_fake_client_satisfies_protocol_with_context_usage(tmp_path):
    client = FakeAgentClient(make_options(tmp_path))
    assert isinstance(client, AgentClient)


@pytest.mark.anyio
async def test_fake_get_context_usage_returns_configured_value(tmp_path):
    client = FakeAgentClient(make_options(tmp_path))
    assert await client.get_context_usage() is None
    client.context_usage = SDK_USAGE
    assert await client.get_context_usage() == SDK_USAGE
    assert client.context_usage_calls == 2


@pytest.mark.anyio
async def test_sdk_client_forwards_get_context_usage(tmp_path):
    class Stub(StubSdkClient):
        async def get_context_usage(self):
            return SDK_USAGE

    client = SdkAgentClient(make_options(tmp_path), sdk_client=Stub())
    assert await client.get_context_usage() == SDK_USAGE


@pytest.mark.anyio
async def test_sdk_client_maps_get_context_usage_errors(tmp_path):
    class Stub(StubSdkClient):
        async def get_context_usage(self):
            raise RuntimeError("quebrou")

    client = SdkAgentClient(make_options(tmp_path), sdk_client=Stub())
    with pytest.raises(AgentError):
        await client.get_context_usage()


# Context with a connected client -------------------------------------------


class ContextFactory(FakeAgentFactory):
    """Fake factory whose clients answer `get_context_usage` with `usage`."""

    def __init__(self, script=None) -> None:
        super().__init__(script=script)
        self.usage: Any = None

    def __call__(self, options):
        client = super().__call__(options)
        client.context_usage = self.usage
        return client


@pytest.mark.anyio
async def test_context_is_null_before_any_turn(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    assert session.summary()["context"] is None
    assert session.summary()["pending_permission"] is None


@pytest.mark.anyio
async def test_context_updated_at_end_of_turn(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = ContextFactory(script)
    factory.usage = SDK_USAGE
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)

    expected = {"used_tokens": 50_000, "max_tokens": 200_000, "percent": 25.0}
    assert session.summary()["context"] == expected
    assert env.manager.list_sessions()[0]["context"] == expected
    # The same event that already updates the summary carries it.
    updates = env.recorder.of(session.session_id, "session.updated")
    assert updates[-1]["data"]["context"] == expected
    assert session.snapshot()["context"] == expected
    assert env.factory.clients[0].context_usage_calls == 1


@pytest.mark.anyio
async def test_context_failure_keeps_last_value_and_turn_finishes(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "um"), lambda sid: text_turn(sid, "dois"))
    factory = ContextFactory(script)
    factory.usage = SDK_USAGE
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("a")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)
    first = session.summary()["context"]
    assert first is not None

    client = env.factory.clients[0]

    async def failing():
        raise AgentError("sem dados")

    async def counted_failure():
        client.context_failures += 1
        await failing()

    client.context_failures = 0
    client.get_context_usage = counted_failure
    await session.send("b")
    await wait_until(lambda: len(env.recorder.of(session.session_id, "turn.result")) == 2)
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: client.context_failures == 1)

    assert session.error is None
    assert session.summary()["context"] == first


@pytest.mark.anyio
async def test_context_ignores_malformed_response(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = ContextFactory(script)
    factory.usage = {"totalTokens": "muito", "maxTokens": 0}
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    assert session.summary()["context"] is None
    assert session.state == "idle"


async def hanging_context_env(make_env, env_cleanup):
    """Session with a first turn done whose `get_context_usage` waits for `release`."""
    script, ids = by_session(
        lambda sid: text_turn(sid, "oi"), lambda sid: text_turn(sid, "dois"),
        lambda sid: text_turn(sid, "três"),
    )
    factory = ContextFactory(script)
    factory.usage = SDK_USAGE
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)
    client = env.factory.clients[0]
    release = asyncio.Event()
    stats = {"calls": 0, "cancelled": 0}

    async def hang():
        stats["calls"] += 1
        try:
            await release.wait()
        except asyncio.CancelledError:
            stats["cancelled"] += 1
            raise
        return {**SDK_USAGE, "totalTokens": 80_000}

    client.get_context_usage = hang
    return env, session, client, release, stats


def turn_results(env, session) -> int:
    return len(env.recorder.of(session.session_id, "turn.result"))


@pytest.mark.anyio
async def test_context_hanging_response_does_not_hold_the_turn(make_env, env_cleanup):
    env, session, _client, release, stats = await hanging_context_env(make_env, env_cleanup)
    before = len(env.recorder.of(session.session_id, "session.updated"))

    await session.send("de novo")
    await wait_until(lambda: turn_results(env, session) == 2)
    await wait_until(lambda: session.state == "idle")

    # The turn ended (state and update) while the read still hangs, and the SDK
    # call was not cancelled from our side.
    assert session.error is None
    assert stats == {"calls": 1, "cancelled": 0}
    updates = env.recorder.of(session.session_id, "session.updated")
    assert len(updates) > before
    assert updates[-1]["data"]["context"]["used_tokens"] == 50_000

    release.set()
    await wait_until(lambda: session.context["used_tokens"] == 80_000)
    updates = env.recorder.of(session.session_id, "session.updated")
    assert updates[-1]["data"]["context"]["used_tokens"] == 80_000
    assert stats["cancelled"] == 0


@pytest.mark.anyio
async def test_context_reads_one_at_a_time_and_again_after_a_turn_meanwhile(
    make_env, env_cleanup
):
    env, session, _client, release, stats = await hanging_context_env(make_env, env_cleanup)

    await session.send("dois")
    await wait_until(lambda: turn_results(env, session) == 2)
    await session.send("três")
    await wait_until(lambda: turn_results(env, session) == 3)
    await wait_until(lambda: session.state == "idle")
    assert stats["calls"] == 1  # not one call per turn while the first one hangs

    release.set()
    await wait_until(lambda: stats["calls"] == 2)  # reads again for the later turn
    await wait_until(lambda: session.context["used_tokens"] == 80_000)


@pytest.mark.anyio
async def test_context_read_is_cancelled_when_the_session_closes(make_env, env_cleanup):
    env, session, _client, _release, stats = await hanging_context_env(make_env, env_cleanup)
    await session.send("dois")
    await wait_until(lambda: stats["calls"] == 1)

    await session.close()
    await wait_until(lambda: stats["cancelled"] == 1)

    assert session._context_task is None
    assert session.context["used_tokens"] == 50_000  # not touched by the dead read


@pytest.mark.anyio
async def test_context_late_result_of_replaced_client_is_ignored(make_env, env_cleanup):
    env, session, _client, release, stats = await hanging_context_env(make_env, env_cleanup)
    await session.send("dois")
    await wait_until(lambda: stats["calls"] == 1)

    await session.close()
    release.set()
    await asyncio.sleep(0.01)

    assert session.context["used_tokens"] == 50_000


@pytest.mark.anyio
async def test_context_read_slot_is_freed_after_the_limit(make_env, env_cleanup, monkeypatch):
    monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_READ_LIMIT", 0.05)
    env, session, client, release, stats = await hanging_context_env(make_env, env_cleanup)

    await session.send("dois")
    await wait_until(lambda: turn_results(env, session) == 2)
    await wait_until(lambda: stats["calls"] == 1)
    # The first call never returns: the slot is freed anyway, without cancelling it.
    await wait_until(lambda: session._context_task is None or session._context_task.done())
    assert stats["cancelled"] == 0

    async def answer():
        stats["calls"] += 1
        return {**SDK_USAGE, "totalTokens": 90_000}

    client.get_context_usage = answer
    await session.send("três")
    await wait_until(lambda: turn_results(env, session) == 3)
    await wait_until(lambda: session.context["used_tokens"] == 90_000)
    assert stats["calls"] == 2
    assert stats["cancelled"] == 0

    # The abandoned call ends later: its stale result is discarded.
    release.set()
    await asyncio.sleep(0.02)
    assert session.context["used_tokens"] == 90_000


@pytest.mark.anyio
async def test_dispose_cancels_pending_and_abandoned_context_calls(
    make_env, env_cleanup, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_READ_LIMIT", 0.05)
    env, session, client, _release, stats = await hanging_context_env(make_env, env_cleanup)
    await session.send("dois")
    await wait_until(lambda: stats["calls"] == 1)
    await wait_until(lambda: session._context_task is None or session._context_task.done())
    await session.send("três")
    await wait_until(lambda: stats["calls"] == 2)  # a second call, the first abandoned

    await session.close()

    await wait_until(lambda: stats["cancelled"] == 2)


# Context conversion ----------------------------------------------------------


def test_context_percent_uses_the_base_of_the_maximum_shown():
    from claudio_maestro.sessions import context_from_sdk

    context = context_from_sdk(SDK_USAGE)

    assert context == {"used_tokens": 50_000, "max_tokens": 200_000, "percent": 25.0}


def test_context_percent_falls_back_to_max_tokens_and_ignores_percentage():
    from claudio_maestro.sessions import context_from_sdk

    context = context_from_sdk({"totalTokens": 50_000, "maxTokens": 100_000, "percentage": 7.0})

    assert context == {"used_tokens": 50_000, "max_tokens": 100_000, "percent": 50.0}


# Context without a client (history) ----------------------------------------
#
# Listings, search, sync and `hidden_counts` never read history files: only the
# snapshot does, off the event loop.


def history_reader(values: dict[str, dict[str, Any] | None] | None = None):
    calls: list[str] = []

    def read(session_id: str, cwd: str):
        calls.append(session_id)
        return (values or {}).get(session_id)

    read.calls = calls  # type: ignore[attr-defined]
    return read


def usage_reader(used: int, model: str | None = None):
    def read(session_id: str, cwd: str):
        return {"used_tokens": used, "model": model}

    return read


@pytest.mark.anyio
async def test_snapshot_of_history_session_has_context(make_env, env_cleanup):
    env = make_env(read_context=usage_reader(40_000, "claude-opus-5-5"))
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    snapshot = await env.manager.open(record.session_id)

    assert snapshot["context"] == {"used_tokens": 40_000, "max_tokens": 200_000, "percent": 20.0}


@pytest.mark.anyio
async def test_snapshot_context_null_without_data(make_env, env_cleanup):
    env = make_env(read_context=lambda sid, cwd: None)
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    assert (await env.manager.open(record.session_id))["context"] is None


@pytest.mark.anyio
async def test_snapshot_context_reader_failure_gives_null(make_env, env_cleanup):
    def boom(sid, cwd):
        raise OSError("disco")

    env = make_env(read_context=boom)
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    assert (await env.manager.open(record.session_id))["context"] is None


@pytest.mark.anyio
async def test_snapshot_context_uses_one_million_window_for_1m_model(make_env, env_cleanup):
    env = make_env(read_context=usage_reader(250_000, "claude-opus-5-5"))
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)
    env.manager.get(record.session_id).save(model="opus[1m]")

    snapshot = await env.manager.open(record.session_id)

    assert snapshot["context"] == {
        "used_tokens": 250_000, "max_tokens": 1_000_000, "percent": 25.0
    }


@pytest.mark.anyio
async def test_snapshot_context_above_200k_implies_large_window(make_env, env_cleanup):
    env = make_env(read_context=usage_reader(300_000))
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    context = (await env.manager.open(record.session_id))["context"]

    assert context["max_tokens"] == 1_000_000
    assert context["percent"] == 30.0


@pytest.mark.anyio
async def test_snapshot_context_is_read_off_the_event_loop(make_env, env_cleanup):
    import threading

    threads: list[int] = []

    def read(session_id: str, cwd: str):
        threads.append(threading.get_ident())
        return {"used_tokens": 1000, "model": None}

    env = make_env(read_context=read)
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)

    await env.manager.open(record.session_id)

    assert threads and threads[0] != threading.get_ident()


@pytest.mark.anyio
async def test_snapshot_context_is_cached_by_file_modification(make_env, env_cleanup):
    read = history_reader({})
    env = make_env(read_context=read)
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)
    session = env.manager.get(record.session_id)
    session.record.file_modified_at = 1000

    await env.manager.open(record.session_id)
    await env.manager.open(record.session_id)
    assert len(read.calls) == 1  # type: ignore[attr-defined]

    session.record.file_modified_at = 2000
    await env.manager.open(record.session_id)
    assert len(read.calls) == 2  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_history_context_cache_is_bounded(make_env, env_cleanup, monkeypatch):
    monkeypatch.setattr("claudio_maestro.sessions.CONTEXT_CACHE_SIZE", 2)
    read = history_reader({})
    env = make_env(read_context=read)
    env_cleanup.append(env.manager)
    ids = []
    for index in range(3):
        session = env.new_session()
        session.record.file_modified_at = 1000 + index
        ids.append(session.session_id)
        await env.manager.open(session.session_id)

    assert len(env.manager._history_contexts) == 2
    assert ids[0] not in env.manager._history_contexts


@pytest.mark.anyio
async def test_listings_search_and_summaries_do_not_read_history(make_env, env_cleanup):
    read = history_reader({})
    env = make_env(read_context=read)
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)
    env.manager.get(record.session_id).record.file_modified_at = 1000

    env.manager.list_sessions()
    env.manager.list_sessions(project_id=env.project.id)
    env.manager.search("nova")
    env.manager.hidden_counts()
    env.manager.list_for_project(env.project.id)
    item = env.manager.describe_record(record)
    await env.manager.apply_external_change(record.session_id, reload=False)

    assert read.calls == []  # type: ignore[attr-defined]
    assert item["context"] is None
    assert env.manager.list_sessions()[0]["context"] is None


@pytest.mark.anyio
async def test_active_session_events_and_lists_carry_in_memory_context(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = ContextFactory(script)
    factory.usage = SDK_USAGE
    read = history_reader({})
    env = make_env(factory=factory, read_context=read)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)

    assert env.manager.list_sessions()[0]["context"]["used_tokens"] == 50_000
    assert read.calls == []  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_connected_context_is_kept_and_snapshot_reads_history_after_close(
    make_env, env_cleanup
):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = ContextFactory(script)
    factory.usage = SDK_USAGE
    env = make_env(factory=factory, read_context=usage_reader(1000))
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: session.context is not None)

    # Connected: the in-memory value, no file read.
    assert (await env.manager.open(session.session_id))["context"]["used_tokens"] == 50_000

    await session.close()

    # Without a client the snapshot reads the history again.
    assert (await env.manager.open(session.session_id))["context"]["used_tokens"] == 1000


@pytest.mark.anyio
async def test_snapshot_history_read_does_not_overwrite_a_newer_value(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.project)
    session = env.manager.get(record.session_id)
    newer = {"used_tokens": 50_000, "max_tokens": 200_000, "percent": 25.0}

    def read(session_id: str, cwd: str):
        # A turn ends while the file is being read.
        session.context = newer
        return {"used_tokens": 1000, "model": None}

    env.manager._read_context = read

    snapshot = await env.manager.open(record.session_id)

    assert session.context == newer
    assert snapshot["context"] == newer


# read_context_file ---------------------------------------------------------


def assistant_line(
    usage: dict[str, int] | None, *, model: str = "claude-opus-5-5", sidechain: bool = False
) -> str:
    entry: dict[str, Any] = {
        "type": "assistant",
        "uuid": "u",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "model": model, "content": []},
    }
    if usage is not None:
        entry["message"]["usage"] = usage
    return json.dumps(entry)


USAGE = {
    "input_tokens": 3,
    "cache_creation_input_tokens": 1000,
    "cache_read_input_tokens": 20_000,
    "output_tokens": 500,
}


def test_read_context_file_uses_last_assistant_usage(tmp_path):
    path = tmp_path / "s.jsonl"
    older = {**USAGE, "cache_read_input_tokens": 5}
    path.write_text(
        "\n".join([
            assistant_line(older),
            json.dumps({"type": "user", "message": {"content": "oi"}}),
            assistant_line(USAGE),
            json.dumps({"type": "user", "message": {"content": "tchau"}}),
        ]) + "\n"
    )

    assert history_module.read_context_file(path) == {
        "used_tokens": 3 + 1000 + 20_000, "model": "claude-opus-5-5"
    }


def test_read_context_file_skips_synthetic_sidechain_and_usage_less(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join([
            assistant_line(USAGE),
            assistant_line({"input_tokens": 0, "output_tokens": 0}, model="<synthetic>"),
            assistant_line({**USAGE, "input_tokens": 999_000}, sidechain=True),
            assistant_line(None),
            "not json {",
        ]) + "\n"
    )

    assert history_module.read_context_file(path)["used_tokens"] == 21_003


def test_read_context_file_without_assistant_usage(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({"type": "user", "message": {"content": "oi"}}) + "\n")
    assert history_module.read_context_file(path) is None
    assert history_module.read_context_file(tmp_path / "missing.jsonl") is None


def test_read_context_file_finds_usage_before_a_huge_tail(tmp_path):
    path = tmp_path / "s.jsonl"
    huge = json.dumps({"type": "user", "message": {"content": "x" * 300_000}})
    path.write_text("\n".join([assistant_line(USAGE), huge, huge]) + "\n")

    assert history_module.read_context_file(path)["used_tokens"] == 21_003


def test_read_context_file_handles_partial_last_line(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(assistant_line(USAGE) + "\n" + '{"type": "assistant", "mess')
    assert history_module.read_context_file(path)["used_tokens"] == 21_003


# Pending permission --------------------------------------------------------


async def start_tool_permission(make_env, env_cleanup, tool_name="Bash", tool_input=None,
                                suggestions=None):
    script, ids = by_session(
        lambda sid: tool_turn(
            sid, tool_name=tool_name, tool_input=tool_input or {"command": "ls -la"},
            tool_use_id="toolu_1", ask_permission=True, suggestions=suggestions,
        ),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("rode")
    await wait_until(lambda: session.state == "awaiting_decision")
    return env, session


@pytest.mark.anyio
async def test_pending_permission_in_summary(make_env, env_cleanup):
    env, session = await start_tool_permission(make_env, env_cleanup)
    [request] = env.recorder.of(session.session_id, "prompt.request")

    expected = {
        "prompt_id": request["data"]["prompt_id"],
        "tool_name": "Bash",
        "summary": "ls -la",
        "can_allow_always": False,
    }
    assert session.summary()["pending_permission"] == expected
    assert env.manager.list_sessions()[0]["pending_permission"] == expected
    assert session.snapshot()["pending_permission"] == expected


@pytest.mark.anyio
async def test_pending_permission_can_allow_always(make_env, env_cleanup):
    from claude_agent_sdk import PermissionUpdate

    suggestion = PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")
    env, session = await start_tool_permission(
        make_env, env_cleanup, tool_name="Write", tool_input={"file_path": "/tmp/a.txt"},
        suggestions=[suggestion],
    )

    pending = session.summary()["pending_permission"]

    assert pending["summary"] == "/tmp/a.txt"
    assert pending["can_allow_always"] is True


@pytest.mark.anyio
async def test_pending_permission_event_when_it_appears_and_is_resolved(make_env, env_cleanup):
    env, session = await start_tool_permission(make_env, env_cleanup)
    sid = session.session_id
    [request] = env.recorder.of(sid, "prompt.request")
    prompt_id = request["data"]["prompt_id"]

    appeared = [
        e for e in env.recorder.of(sid, "session.updated")
        if e["data"]["pending_permission"] is not None
    ]
    assert len(appeared) == 1
    assert appeared[0]["data"]["pending_permission"]["prompt_id"] == prompt_id
    assert appeared[0]["data"]["awaiting_decision"] is True
    assert appeared[0]["seq"] == appeared[0]["data"]["seq"]

    session.resolve_prompt(prompt_id, "allow_once")

    last = env.recorder.of(sid, "session.updated")[-1]
    assert last["data"]["pending_permission"] is None
    assert session.summary()["pending_permission"] is None


@pytest.mark.anyio
async def test_pending_permission_cleared_when_interrupted(make_env, env_cleanup):
    env, session = await start_tool_permission(make_env, env_cleanup)
    sid = session.session_id

    await session.interrupt()
    await wait_until(lambda: not session.prompts)

    assert session.summary()["pending_permission"] is None
    last = env.recorder.of(sid, "session.updated")[-1]
    assert last["data"]["pending_permission"] is None


@pytest.mark.anyio
async def test_pending_permission_cleared_when_session_closes(make_env, env_cleanup):
    env, session = await start_tool_permission(make_env, env_cleanup)

    await session.close()

    assert session.summary()["pending_permission"] is None
    assert env.recorder.of(session.session_id, "session.updated")[-1]["data"][
        "pending_permission"
    ] is None


def long_summary_input() -> dict[str, Any]:
    return {"command": "echo   um\n  dois\t" + "x" * 500}


@pytest.mark.anyio
async def test_pending_permission_summary_is_one_short_line(make_env, env_cleanup):
    env, session = await start_tool_permission(
        make_env, env_cleanup, tool_input=long_summary_input()
    )

    summary = session.summary()["pending_permission"]["summary"]

    assert len(summary) == 200
    assert "\n" not in summary and "\t" not in summary
    assert summary.startswith("echo um dois xxx")
    assert summary.endswith("…")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "tool_input", "expected"),
    [
        ("WebFetch", {"url": "https://a.dev/x"}, "https://a.dev/x"),
        ("Read", {"path": "/tmp/p"}, "/tmp/p"),
        ("Mcp", {"a": 1}, '{"a": 1}'),
    ],
)
async def test_pending_permission_summary_fallbacks(
    make_env, env_cleanup, tool_name, tool_input, expected
):
    env, session = await start_tool_permission(
        make_env, env_cleanup, tool_name=tool_name, tool_input=tool_input
    )
    assert session.summary()["pending_permission"]["summary"] == expected


def ask(session, tool_name: str, tool_input: dict[str, Any]) -> asyncio.Task:
    return asyncio.create_task(
        session._can_use_tool(tool_name, tool_input, ToolPermissionContext(tool_use_id="t"))
    )


@pytest.mark.anyio
async def test_pending_permission_is_the_oldest_tool_prompt(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.client = FakeAgentClient(make_options_for(env, session))

    question = ask(session, "AskUserQuestion", {"questions": []})
    await wait_until(lambda: len(session.prompts) == 1)
    assert session.summary()["pending_permission"] is None  # questions stay null

    plan = ask(session, "ExitPlanMode", {"plan": "p"})
    await wait_until(lambda: len(session.prompts) == 2)
    assert session.summary()["pending_permission"] is None  # plans too

    first = ask(session, "Bash", {"command": "primeiro"})
    await wait_until(lambda: len(session.prompts) == 3)
    second = ask(session, "Bash", {"command": "segundo"})
    await wait_until(lambda: len(session.prompts) == 4)
    assert session.summary()["pending_permission"]["summary"] == "primeiro"

    first_id = session.summary()["pending_permission"]["prompt_id"]
    session.resolve_prompt(first_id, "deny")
    await first
    assert session.summary()["pending_permission"]["summary"] == "segundo"
    # The event of the first answer already shows the next request.
    last = env.recorder.of(session.session_id, "session.updated")[-1]
    assert last["data"]["pending_permission"]["summary"] == "segundo"

    for task in (question, plan, second):
        task.cancel()
    await asyncio.gather(question, plan, second, return_exceptions=True)


def make_options_for(env: Env, session):
    from claudio_maestro.agent.base import AgentOptions

    async def allow(name, tool_input, context):
        raise AssertionError("not used")

    return AgentOptions(
        cwd=Path(session.record.cwd), session_id=session.session_id, resume=False,
        can_use_tool=allow,
    )


# API -----------------------------------------------------------------------


@pytest.fixture
def factory() -> ContextFactory:
    return ContextFactory()


@pytest.fixture
def api(factory: ContextFactory, monkeypatch: pytest.MonkeyPatch):
    read_calls: list[str] = []

    def read_context(sid: str, cwd: str):
        read_calls.append(sid)
        return {"used_tokens": 10_000, "model": None}

    monkeypatch.setattr("claudio_maestro.history.sdk_read_context", read_context)
    monkeypatch.setattr("claudio_maestro.history.sdk_session_file_mtime", lambda sid, cwd: 1000.0)

    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    headers = {"origin": APP_ORIGIN, "x-maestro": "1"}
    with TestClient(app, base_url=BACKEND_URL, headers=headers) as client:
        client.read_calls = read_calls  # type: ignore[attr-defined]
        yield client


def api_session(api: TestClient, home: Path) -> dict[str, Any]:
    folder = home / "app"
    folder.mkdir()
    project = api.post(
        "/api/projects", json={"name": "app", "path": str(folder), "color": "#ff8800"}
    ).json()
    return api.post(f"/api/projects/{project['id']}/sessions").json()


def wait_api_state(api: TestClient, sid: str, state: str) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 2
    while True:
        snapshot = api.get(f"/api/sessions/{sid}").json()
        if snapshot["state"] == state:
            return snapshot
        assert time.monotonic() < deadline, snapshot["state"]
        time.sleep(0.01)


def test_api_lists_and_search_do_not_read_history(api, home):
    created = api_session(api, home)
    project_id = created["project_id"]

    assert created["context"] is None
    assert created["pending_permission"] is None
    [listed] = api.get("/api/sessions").json()
    assert listed["context"] is None and listed["pending_permission"] is None
    api.get(f"/api/projects/{project_id}/sessions")
    api.get("/api/sessions/search", params={"q": "nova"})
    api.post(f"/api/projects/{project_id}/sync")

    assert api.read_calls == []  # type: ignore[attr-defined]


def test_api_snapshot_has_history_context_and_uses_cache(api, home):
    created = api_session(api, home)
    sid = created["session_id"]

    first = api.get(f"/api/sessions/{sid}").json()
    second = api.get(f"/api/sessions/{sid}").json()

    expected = {"used_tokens": 10_000, "max_tokens": 200_000, "percent": 5.0}
    assert first["context"] == expected and second["context"] == expected
    assert api.read_calls == [sid]  # type: ignore[attr-defined]


def test_api_answer_permission_from_summary(api, home, factory):
    created = api_session(api, home)
    sid = created["session_id"]
    factory.script = lambda content: tool_turn(
        sid, tool_name="Bash", tool_input={"command": "ls"}, ask_permission=True
    )
    api.post(f"/api/sessions/{sid}/messages", json={"text": "rode"})
    wait_api_state(api, sid, "awaiting_decision")

    [listed] = api.get("/api/sessions").json()
    pending = listed["pending_permission"]
    assert pending["summary"] == "ls" and pending["tool_name"] == "Bash"
    assert listed["display_state"] == "waiting"

    url = f"/api/sessions/{sid}/prompts/{pending['prompt_id']}"
    first = api.post(url, json={"decision": "allow_once"})
    second = api.post(url, json={"decision": "deny"})

    assert first.status_code == 200
    assert second.status_code == 409
    wait_api_state(api, sid, "idle")
    [after] = api.get("/api/sessions").json()
    assert after["pending_permission"] is None
    [record] = factory.clients[0].permission_results
    assert record.result.__class__.__name__ == "PermissionResultAllow"


def test_api_context_after_turn(api, home, factory):
    created = api_session(api, home)
    sid = created["session_id"]
    factory.usage = SDK_USAGE
    factory.script = lambda content: text_turn(sid, "oi")
    api.post(f"/api/sessions/{sid}/messages", json={"text": "olá"})
    wait_api_state(api, sid, "idle")
    deadline = time.monotonic() + 2
    while api.get("/api/sessions").json()[0]["context"] is None:
        assert time.monotonic() < deadline
        time.sleep(0.005)

    [listed] = api.get("/api/sessions").json()

    assert listed["context"] == {"used_tokens": 50_000, "max_tokens": 200_000, "percent": 25.0}
