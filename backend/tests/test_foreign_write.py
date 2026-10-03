"""Escrita de outro processo numa sessão com cliente vivo e ocioso."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_sessions import Env, wait_until

from claudio_maestro.agent.fake import FakeAgentFactory, scripted, text_turn
from claudio_maestro.foreign import has_foreign_reply


def iso(ts: float, *, z: bool = True) -> str:
    text = datetime.fromtimestamp(ts, UTC).isoformat()
    return text.replace("+00:00", "Z") if z else text


def entry(type_: str, uuid: str, ts: float, *, sidechain: bool = False, z: bool = True) -> str:
    return json.dumps({
        "type": type_, "uuid": uuid, "timestamp": iso(ts, z=z), "isSidechain": sidechain,
        "message": {"role": type_, "content": [{"type": "text", "text": "x"}]},
    })


# Regra -----------------------------------------------------------------------

def test_reply_from_another_process_after_the_client_started_is_foreign():
    now = time.time()
    assert has_foreign_reply([entry("assistant", "a1", now)], set(), now - 5) is True


def test_reply_with_an_own_uuid_is_not_foreign():
    now = time.time()
    assert has_foreign_reply([entry("assistant", "a1", now)], {"a1"}, now - 5) is False


def test_reply_written_before_the_client_started_is_not_foreign():
    now = time.time()
    assert has_foreign_reply([entry("assistant", "a1", now - 60)], set(), now - 5) is False


def test_offset_timestamp_without_z_is_understood():
    now = time.time()
    assert has_foreign_reply([entry("assistant", "a1", now, z=False)], set(), now - 5) is True
    assert has_foreign_reply([entry("assistant", "a1", now - 60, z=False)], set(), now - 5) is False


def test_user_entry_alone_is_not_foreign():
    now = time.time()
    assert has_foreign_reply([entry("user", "u1", now)], set(), now - 5) is False


def test_subagent_entry_is_not_foreign():
    now = time.time()
    assert has_foreign_reply([entry("assistant", "a1", now, sidechain=True)], set(), now - 5) is False


def test_broken_or_incomplete_entries_are_ignored():
    now = time.time()
    no_ts = json.dumps({"type": "assistant", "uuid": "a1"})
    no_uuid = json.dumps({"type": "assistant", "timestamp": iso(now)})
    bad_ts = json.dumps({"type": "assistant", "uuid": "a1", "timestamp": "ontem"})
    lines = ["{nao é json", "[]", no_ts, no_uuid, bad_ts]
    assert has_foreign_reply(lines, set(), now - 5) is False


def test_without_a_client_start_nothing_is_foreign():
    assert has_foreign_reply([entry("assistant", "a1", time.time())], set(), None) is False


# Sessão ----------------------------------------------------------------------

@pytest.fixture
def env(tmp_path: Path):
    return Env(tmp_path, FakeAgentFactory(script=scripted(text_turn("x", "olá"))))


async def idle_session(env):
    session = env.new_session()
    before = time.time()
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")
    return session, before


@pytest.mark.anyio
async def test_stream_uuids_and_client_start_are_kept(env):
    session, before = await idle_session(env)
    assert session.client_since is not None and session.client_since >= before - 1
    assert session.own_uuids  # as AssistantMessage do text_turn trazem uuid
    assert session.idle_client_only is True
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_new_client_renews_uuids_and_start(env):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "de novo"))
    session, _ = await idle_session(env)
    old_uuids, old_since = set(session.own_uuids), session.client_since
    await session.close()
    await session.send("outra")
    await wait_until(lambda: session.state == "idle")
    assert session.client_since >= old_since
    assert not (old_uuids & session.own_uuids)
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_manager_releases_idle_client_on_foreign_reply(env):
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    released = await env.manager.release_if_foreign(
        session.session_id, [entry("assistant", "de-fora", time.time())]
    )
    assert released is True
    assert session.client is None and session.state == "closed"
    assert client.closed is True
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_manager_keeps_client_for_own_reply(env):
    session, _ = await idle_session(env)
    own = next(iter(session.own_uuids))
    assert await env.manager.release_if_foreign(
        session.session_id, [entry("assistant", own, time.time())]
    ) is False
    assert session.client is not None
    await env.manager.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("busy_with", ["pending", "autonomous", "followup", "prompt", "lock"])
async def test_client_is_kept_while_the_app_is_working(env, busy_with):
    session, _ = await idle_session(env)
    foreign = [entry("assistant", "de-fora", time.time())]
    if busy_with == "pending":
        session.pending_turns = 1
    elif busy_with == "autonomous":
        session._autonomous_turn = True
    elif busy_with == "followup":
        session._followup_owed = 1
    elif busy_with == "prompt":
        session.prompts["p"] = object()
    if busy_with == "lock":
        async with session._lock:
            assert await env.manager.release_if_foreign(session.session_id, foreign) is False
    else:
        assert session.idle_client_only is False
        assert await env.manager.release_if_foreign(session.session_id, foreign) is False
    assert session.client is not None
    session.pending_turns = 0
    session._autonomous_turn = False
    session._followup_owed = 0
    session.prompts.clear()
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_client_is_kept_while_a_subagent_runs(env, monkeypatch):
    session, _ = await idle_session(env)
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    assert session.idle_client_only is False
    assert await env.manager.release_if_foreign(
        session.session_id, [entry("assistant", "de-fora", time.time())]
    ) is False
    monkeypatch.undo()
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_unknown_session_or_without_client_is_not_released(env):
    assert await env.manager.release_if_foreign("nao-existe", []) is False
    session = env.new_session()
    assert await env.manager.release_if_foreign(
        session.session_id, [entry("assistant", "de-fora", time.time())]
    ) is False
    await env.manager.shutdown()
