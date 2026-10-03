"""Escrita de outro processo numa sessão com cliente vivo e ocioso."""

import json
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_sessions import Env, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, scripted, text_turn
from claudio_maestro.foreign import foreign_reply_uuids, has_foreign_reply
from claudio_maestro.sessions import CONTINUED_ELSEWHERE_TEXT, ContinuedElsewhereError


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


def test_foreign_reply_uuids_returns_the_matching_uuids():
    now = time.time()
    lines = [
        entry("assistant", "a1", now), entry("assistant", "a2", now),
        entry("assistant", "dono", now), entry("assistant", "velha", now - 60),
    ]
    assert foreign_reply_uuids(lines, {"dono"}, now - 5) == {"a1", "a2"}
    assert foreign_reply_uuids(lines, set(), None) == set()


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


# Resposta de fora com a sessão ocupada --------------------------------------

def foreign_lines() -> list[str]:
    return [entry("assistant", "de-fora", time.time())]


@pytest.mark.anyio
async def test_foreign_reply_while_a_subagent_runs_is_remembered(env, monkeypatch):
    session, _ = await idle_session(env)
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    assert session.foreign_pending is False
    released = await env.manager.release_if_foreign(session.session_id, foreign_lines())
    assert released is False
    assert session.client is not None
    assert session.foreign_pending is True
    monkeypatch.undo()
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_close_idle_releases_a_remembered_foreign_write_once_idle(env, monkeypatch):
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    await env.manager.release_if_foreign(session.session_id, foreign_lines())
    await env.manager.close_idle()
    assert session.client is not None  # still working in the background
    monkeypatch.undo()  # the background work ended
    await env.manager.close_idle()
    assert session.client is None and session.state == "closed"
    assert client.closed is True
    assert session.foreign_pending is False
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_is_refused_while_background_work_runs_after_a_foreign_write(env, monkeypatch):
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    await env.manager.release_if_foreign(session.session_id, foreign_lines())
    with pytest.raises(ContinuedElsewhereError) as refused:
        await env.manager.send(session.session_id, "nova")
    assert str(refused.value) == CONTINUED_ELSEWHERE_TEXT
    assert session.client is client and client.closed is False
    assert not [i for i in session.builder.items if getattr(i, "text", None) == "nova"]
    assert "nova" not in client.sent
    monkeypatch.undo()
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_after_a_foreign_write_releases_the_client_and_resumes(env):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "voltei"))
    session, _ = await idle_session(env)
    old_client = env.factory.clients[-1]
    session.foreign_candidates = {"de-fora"}
    await env.manager.send(session.session_id, "outra")
    assert old_client.closed is True
    new_client = env.factory.clients[-1]
    assert new_client is not old_client
    assert "outra" in new_client.sent
    assert session.foreign_pending is False
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_own_reply_while_busy_does_not_mark_a_foreign_write(env):
    session, _ = await idle_session(env)
    own = next(iter(session.own_uuids))
    session.pending_turns = 1
    await env.manager.release_if_foreign(
        session.session_id, [entry("assistant", own, time.time())]
    )
    assert session.foreign_pending is False
    session.pending_turns = 0
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_close_resets_the_foreign_state(env):
    session, _ = await idle_session(env)
    session.foreign_candidates = {"de-fora"}
    await session.close()
    assert session.foreign_pending is False
    assert session.foreign_candidates == set()
    assert session.own_uuids == set()
    assert session.client_since is None
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_release_keeps_the_outside_modification_notice(env):
    session, _ = await idle_session(env)
    session.save(app_modified_at=1_000)
    session._file_mtime = lambda sid, cwd: 5_000.0
    assert await env.manager.release_if_foreign(session.session_id, foreign_lines()) is True
    assert session.record.app_modified_at == 1_000
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_candidate_delivered_by_the_stream_later_is_not_foreign(env, monkeypatch):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "segue"))
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    # The file line of the app's own reply is read before the stream delivers it.
    await env.manager.release_if_foreign(session.session_id, foreign_lines())
    assert session.foreign_pending is True
    session.own_uuids.add("de-fora")  # the stream catches up
    assert session.foreign_pending is False
    await env.manager.send(session.session_id, "nova")
    assert session.client is client and "nova" in client.sent
    monkeypatch.undo()
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_a_new_client_clears_a_stale_detach_time(env):
    session = env.new_session()
    session.save(detached_at=time.time() - 86_400)  # left over from an old shutdown
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")
    assert session.record.detached_at is None
    with closing(db.connect(env.db_path)) as conn:
        row = conn.execute(
            "SELECT detached_at FROM sessions WHERE session_id = ?", (session.session_id,)
        ).fetchone()
    assert row["detached_at"] is None
    assert session.client_since is not None and session.client_since > time.time() - 60
    await env.manager.shutdown()


# Checagem no envio ------------------------------------------------------------

def locate(env, path: Path) -> None:
    env.manager._session_file = lambda session_id, directory: path


@pytest.mark.anyio
async def test_send_checks_the_file_and_releases_for_a_write_no_pass_saw(env, tmp_path):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "voltei"))
    session, _ = await idle_session(env)
    old_client = env.factory.clients[-1]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(foreign_lines()) + "\n")
    locate(env, path)
    await env.manager.send(session.session_id, "outra")
    assert old_client.closed is True
    new_client = env.factory.clients[-1]
    assert new_client is not old_client and "outra" in new_client.sent
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_checking_the_file_refuses_while_background_work_runs(env, tmp_path, monkeypatch):
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(foreign_lines()) + "\n")
    locate(env, path)
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    with pytest.raises(ContinuedElsewhereError):
        await env.manager.send(session.session_id, "nova")
    assert session.client is client and client.closed is False
    assert "nova" not in client.sent
    assert not [i for i in session.builder.items if getattr(i, "text", None) == "nova"]
    monkeypatch.undo()
    await env.manager.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["own", "old"])
async def test_send_keeps_the_client_when_the_file_has_nothing_foreign(env, tmp_path, content):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "segue"))
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    path = tmp_path / "s.jsonl"
    if content == "own":
        lines = [entry("assistant", u, time.time()) for u in session.own_uuids]
    else:
        lines = [entry("assistant", "antiga", session.client_since - 60)]
    path.write_text("\n".join(lines) + "\n")
    locate(env, path)
    await env.manager.send(session.session_id, "nova")
    assert env.factory.clients[-1] is client and "nova" in client.sent
    assert client.closed is False
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_with_a_missing_file_goes_to_the_existing_client(env, tmp_path):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "segue"))
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    locate(env, tmp_path / "nao-existe.jsonl")
    await env.manager.send(session.session_id, "nova")
    assert env.factory.clients[-1] is client and "nova" in client.sent
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_never_fails_because_the_foreign_check_failed(env, caplog):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "segue"))
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]

    def boom(session_id, directory):
        raise RuntimeError("falhou")

    env.manager._session_file = boom
    await env.manager.send(session.session_id, "nova")
    assert "nova" in client.sent
    assert "escrita de outro processo" in caplog.text
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_send_does_not_check_the_file_while_the_app_turn_runs(env, tmp_path, monkeypatch):
    env.factory.script = scripted(text_turn("x", "olá"), text_turn("x", "segue"))
    session, _ = await idle_session(env)
    client = env.factory.clients[-1]
    path = tmp_path / "s.jsonl"
    # The app's own reply may reach the file before the stream delivers its uuid.
    path.write_text("\n".join(foreign_lines()) + "\n")
    locate(env, path)
    monkeypatch.setattr(type(session), "subagents_running", property(lambda self: True))
    session.pending_turns = 1
    session._refresh_state()
    assert session.state != "idle"
    await env.manager.send(session.session_id, "nova")
    assert session.foreign_candidates == set()
    assert env.factory.clients[-1] is client and "nova" in client.sent
    session.pending_turns = 0
    monkeypatch.undo()
    await env.manager.shutdown()
