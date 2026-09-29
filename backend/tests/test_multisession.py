"""Marco 2 at the manager level: parallel sessions, project removal, idleness,
display state, finishing, renaming and seen marks. Fake agent only."""

import asyncio
import time
from pathlib import Path

import pytest

from test_sessions import (
    Env,
    env_cleanup,  # noqa: F401  (fixture)
    fake_history,
    make_project,
    session_row,
    wait_until,
)
from vibing.agent.fake import FailStep, FakeAgentFactory, PauseStep, text_turn, tool_turn
from vibing.sessions import SessionManager, SessionNotFoundError, display_state

DAY = 86_400


class RenameSpy:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.error = error

    def __call__(self, session_id: str, title: str, directory: str) -> None:
        self.calls.append((session_id, title, directory))
        if self.error is not None:
            raise self.error


def build_manager(env: Env, **kwargs) -> SessionManager:
    return SessionManager(
        env.db_path,
        env.recorder,
        agent_factory=env.factory,
        history_exists=fake_history(env.factory),
        **kwargs,
    )


@pytest.fixture
def env(tmp_path: Path, env_cleanup):
    env = Env(tmp_path, FakeAgentFactory())
    env_cleanup.append(env.manager)
    return env


# 1. Parallel sessions ------------------------------------------------------


@pytest.mark.anyio
async def test_two_projects_run_at_the_same_time_isolated(env, tmp_path):
    other = make_project(env.db_path, tmp_path / "home" / "other")
    pause = PauseStep()

    def script(content):
        if content == "a":
            return [PauseStep(release=pause.release, reached=pause.reached),
                    *tool_turn("x", ask_permission=True)]
        if content == "b":
            return [FailStep("caiu")]
        return text_turn("x", "ok")

    env.factory.script = script
    one = env.new_session()
    two = env.manager.get(env.manager.create_session(other).session_id)

    await asyncio.gather(one.send("a"), two.send("b"))
    await pause.reached.wait()
    await wait_until(lambda: two.state == "error")

    # The failure of `two` does not touch `one`, which is still mid-turn.
    assert one.state == "running"
    assert one.error is None
    clients = {c.options.session_id: c for c in env.factory.clients}
    assert clients[one.session_id] is not clients[two.session_id]
    assert clients[one.session_id].options.cwd != clients[two.session_id].options.cwd

    pause.release.set()
    await wait_until(lambda: one.state == "awaiting_decision")
    assert two.prompts == {}
    # Events are tagged by session and each has its own sequence.
    one_events = env.recorder.of(one.session_id)
    assert [e["seq"] for e in one_events] == list(range(1, len(one_events) + 1))
    assert not env.recorder.of(two.session_id, "prompt.request")

    [prompt_id] = one.prompts
    one.resolve_prompt(prompt_id, "allow_once")
    await wait_until(lambda: one.state == "idle")
    assert two.state == "error"


# 2. Closing a project's sessions ------------------------------------------


@pytest.mark.anyio
async def test_close_project_resolves_prompts_and_forgets_sessions(env, tmp_path):
    other = make_project(env.db_path, tmp_path / "home" / "other")
    env.factory.script = lambda content: tool_turn("x", ask_permission=True)
    session = env.new_session()
    keep = env.manager.get(env.manager.create_session(other).session_id)
    await session.send("escreva")
    await wait_until(lambda: session.state == "awaiting_decision")
    [prompt] = session.prompts.values()

    await env.manager.close_project(env.project.id)

    assert prompt.future.done()
    resolved = env.recorder.of(session.session_id, "prompt.resolved")
    assert resolved[-1]["data"]["decision"] == "cancelled"
    assert env.factory.clients[0].closed
    assert session.state == "closed"
    assert session.session_id not in env.manager.active_ids()
    assert keep.session_id in env.manager.active_ids()


# 3. seq in listings --------------------------------------------------------


@pytest.mark.anyio
async def test_listing_includes_current_seq(env):
    env.factory.script = lambda content: text_turn("x", "ok")
    quiet = env.new_session()
    busy = env.new_session()
    await busy.send("oi")
    await wait_until(lambda: busy.state == "idle")

    listed = {s["session_id"]: s for s in env.manager.list_sessions(project_id=env.project.id)}

    assert listed[busy.session_id]["seq"] == busy.seq > 0
    assert listed[quiet.session_id]["seq"] == 0


# 4. Idleness ---------------------------------------------------------------


@pytest.mark.anyio
async def test_idle_session_is_closed_and_resumes_on_next_message(env, env_cleanup):
    manager = build_manager(env, idle_timeout=0.05)
    env_cleanup.append(manager)
    env.factory.script = lambda content: text_turn("x", "ok")
    session = manager.get(manager.create_session(env.project).session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    await manager.close_idle()
    assert session.state == "idle"  # not idle long enough yet

    await asyncio.sleep(0.06)
    await manager.close_idle()
    assert session.state == "closed"
    assert env.factory.clients[0].closed
    assert session.error is None

    await session.send("de novo")
    await wait_until(lambda: session.state == "idle")
    assert [c.options.resume for c in env.factory.clients] == [False, True]


@pytest.mark.anyio
async def test_idle_sweep_never_closes_busy_sessions(env, env_cleanup):
    manager = build_manager(env, idle_timeout=0)
    env_cleanup.append(manager)
    pause = PauseStep()

    def script(content):
        if content == "pausa":
            return [pause, *text_turn("x", "ok")]
        return tool_turn("x", ask_permission=True)

    env.factory.script = script
    running = manager.get(manager.create_session(env.project).session_id)
    waiting = manager.get(manager.create_session(env.project).session_id)
    await running.send("pausa")
    await waiting.send("escreva")
    await pause.reached.wait()
    await wait_until(lambda: waiting.state == "awaiting_decision")

    await asyncio.sleep(0.01)
    await manager.close_idle()

    assert running.state == "running"
    assert waiting.state == "awaiting_decision"
    pause.release.set()
    await wait_until(lambda: running.state == "idle")


@pytest.mark.anyio
async def test_idle_sweep_skips_connecting_session(env, env_cleanup):
    manager = build_manager(env, idle_timeout=0)
    env_cleanup.append(manager)
    gate = asyncio.Event()
    make_client = env.factory.__class__.__call__

    def slow_factory(options):
        client = make_client(env.factory, options)
        connect = client.connect

        async def slow_connect():
            await gate.wait()
            await connect()

        client.connect = slow_connect
        return client

    manager._agent_factory = slow_factory
    session = manager.get(manager.create_session(env.project).session_id)
    task = asyncio.create_task(session.send("oi"))
    await wait_until(lambda: session.state == "connecting")

    await manager.close_idle()

    assert session.state == "connecting"
    gate.set()
    await task


# 5. display_state ----------------------------------------------------------


def row(**overrides):
    base = {"finished": False, "last_activity_at": 1_000, "last_seen_at": 1_000}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("state", "fields", "expected"),
    [
        ("connecting", row(), "running"),
        ("running", row(finished=True), "running"),
        ("awaiting_decision", row(), "waiting"),
        ("error", row(), "waiting"),
        ("idle", row(), "waiting"),
        ("closed", row(last_activity_at=2_000), "waiting"),  # unread answer
        ("closed", row(), "waiting"),  # recent, not finished
        ("closed", row(finished=True), "finished"),
        ("idle", row(finished=True), "finished"),
        ("closed", row(last_activity_at=1_000, last_seen_at=None), "waiting"),
    ],
)
def test_display_state(state, fields, expected):
    assert display_state(state, now=1_000 + 60, finished_after=3 * DAY, **fields) == expected


def test_display_state_old_inactivity_is_finished():
    fields = row(last_activity_at=0, last_seen_at=0)
    assert display_state("closed", now=3 * DAY + 1, finished_after=3 * DAY, **fields) == "finished"
    assert display_state("closed", now=3 * DAY, finished_after=3 * DAY, **fields) == "waiting"


@pytest.mark.anyio
async def test_summary_flags(env):
    env.factory.script = lambda content: tool_turn("x", ask_permission=True)
    session = env.new_session()
    fresh = env.manager.summary(session.session_id)
    assert fresh["unread"] is False
    assert fresh["awaiting_decision"] is False
    assert fresh["display_state"] == "waiting"
    assert fresh["finished"] is False

    await session.send("escreva")
    await wait_until(lambda: session.state == "awaiting_decision")
    summary = env.manager.summary(session.session_id)
    assert summary["awaiting_decision"] is True
    assert summary["display_state"] == "waiting"


@pytest.mark.anyio
async def test_old_session_listed_as_finished(env, env_cleanup):
    manager = build_manager(env, finished_after_days=3)
    env_cleanup.append(manager)
    record = manager.create_session(env.project)
    from contextlib import closing

    from vibing import db

    with closing(db.connect(env.db_path)) as conn:
        conn.execute(
            "UPDATE sessions SET last_activity_at = ?, last_seen_at = ? WHERE session_id = ?",
            (int(time.time()) - 4 * DAY, int(time.time()) - 4 * DAY, record.session_id),
        )
    [listed] = manager.list_sessions()
    assert listed["display_state"] == "finished"


# 6. Finish and reopen ------------------------------------------------------


@pytest.mark.anyio
async def test_finish_and_reopen(env):
    session = env.new_session()

    summary = await env.manager.update(session.session_id, finished=True)

    assert summary["finished"] is True
    assert summary["display_state"] == "finished"
    assert session_row(env.db_path, session.session_id)["finished"] == 1
    [event] = env.recorder.of(session.session_id, "session.updated")
    assert event["data"] == summary

    reopened = await env.manager.update(session.session_id, finished=False)
    assert reopened["display_state"] == "waiting"
    assert len(env.recorder.of(session.session_id, "session.updated")) == 2


@pytest.mark.anyio
async def test_update_without_change_emits_nothing(env):
    session = env.new_session()
    await env.manager.update(session.session_id, finished=False)
    assert env.recorder.of(session.session_id, "session.updated") == []


@pytest.mark.anyio
async def test_message_reopens_finished_session(env):
    env.factory.script = lambda content: text_turn("x", "ok")
    session = env.new_session()
    await env.manager.update(session.session_id, finished=True)

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    assert session.record.finished is False
    assert session_row(env.db_path, session.session_id)["finished"] == 0
    updates = env.recorder.of(session.session_id, "session.updated")
    assert updates[-1]["data"]["finished"] is False


@pytest.mark.anyio
async def test_update_unknown_session(env):
    with pytest.raises(SessionNotFoundError):
        await env.manager.update("00000000-0000-0000-0000-000000000000", finished=True)


# 7. Rename -----------------------------------------------------------------


@pytest.mark.anyio
async def test_rename_without_history_only_writes_database(env, env_cleanup):
    spy = RenameSpy()
    manager = build_manager(env, rename_session=spy)
    env_cleanup.append(manager)
    record = manager.create_session(env.project)

    summary = await manager.update(record.session_id, title="  Novo nome  ")

    assert summary["title"] == "Novo nome"
    assert session_row(env.db_path, record.session_id)["title"] == "Novo nome"
    assert spy.calls == []
    [event] = env.recorder.of(record.session_id, "session.updated")
    assert event["data"]["title"] == "Novo nome"


@pytest.mark.anyio
async def test_rename_with_history_calls_sdk(env, env_cleanup):
    spy = RenameSpy()
    manager = build_manager(env, rename_session=spy)
    env_cleanup.append(manager)
    env.factory.script = lambda content: text_turn("x", "ok")
    session = manager.get(manager.create_session(env.project).session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    await manager.update(session.session_id, title="Outro")

    assert spy.calls == [(session.session_id, "Outro", env.project.path)]


@pytest.mark.anyio
async def test_rename_survives_sdk_failure(env, env_cleanup):
    spy = RenameSpy(error=RuntimeError("disco"))
    manager = build_manager(env, rename_session=spy)
    env_cleanup.append(manager)
    env.factory.script = lambda content: text_turn("x", "ok")
    session = manager.get(manager.create_session(env.project).session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    summary = await manager.update(session.session_id, title="Outro")

    assert spy.calls
    assert summary["title"] == "Outro"
    assert session_row(env.db_path, session.session_id)["title"] == "Outro"


@pytest.mark.anyio
async def test_renamed_session_keeps_title_on_first_message(env):
    env.factory.script = lambda content: text_turn("x", "ok")
    session = env.new_session()
    await env.manager.update(session.session_id, title="Meu nome")
    await session.send("primeira mensagem")
    assert session.record.title == "Meu nome"


# 8. Seen -------------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_seen_clears_unread(env):
    env.factory.script = lambda content: text_turn("x", "ok")
    session = env.new_session()
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")
    session.record.last_activity_at += 5  # the answer came after the last look
    assert env.manager.summary(session.session_id)["unread"] is True

    summary = await env.manager.mark_seen(session.session_id)

    assert summary["unread"] is False
    assert session_row(env.db_path, session.session_id)["last_seen_at"] >= session.record.last_activity_at


def _make_sessions(env, tmp_path, count):
    ids = [env.new_session().session_id for _ in range(count)]
    return ids


def _reset_seen(env, ids, value=0):
    from contextlib import closing

    from vibing import db

    with closing(db.connect(env.db_path)) as conn:
        conn.execute(
            f"UPDATE sessions SET last_seen_at = ? WHERE session_id IN ({','.join('?' * len(ids))})",
            (value, *ids),
        )
    for sid in ids:
        env.manager.get(sid).record.last_seen_at = value


@pytest.mark.anyio
async def test_mark_seen_many_writes_in_one_transaction_off_the_event_loop(env, tmp_path, monkeypatch):
    import threading

    from vibing import db
    from vibing import sessions as sessions_module

    ids = _make_sessions(env, tmp_path, 3)
    _reset_seen(env, ids)
    env.recorder.envelopes.clear()
    calls: list[int] = []
    real = db.transaction

    def spy(conn):
        calls.append(threading.get_ident())
        return real(conn)

    monkeypatch.setattr(sessions_module.db, "transaction", spy)

    updated = await env.manager.mark_seen_many([ids[0], "desconhecida", ids[1], ids[0], ids[2]])

    assert updated == 3
    assert len(calls) == 1
    assert calls[0] != threading.get_ident()
    for sid in ids:
        assert session_row(env.db_path, sid)["last_seen_at"] > 0
        assert env.manager.get(sid).record.last_seen_at > 0
    updates = [e for e in env.recorder.envelopes if e["type"] == "session.updated"]
    assert sorted(e["session_id"] for e in updates) == sorted(ids)


@pytest.mark.anyio
async def test_mark_seen_many_failure_writes_nothing_and_emits_nothing(env, tmp_path):
    from contextlib import closing

    from vibing import db

    ids = _make_sessions(env, tmp_path, 3)
    _reset_seen(env, ids)
    env.recorder.envelopes.clear()
    with closing(db.connect(env.db_path)) as conn:
        conn.execute(
            "CREATE TRIGGER fail_seen BEFORE UPDATE OF last_seen_at ON sessions"
            f" WHEN NEW.session_id = '{ids[2]}' BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )

    with pytest.raises(Exception, match="boom"):
        await env.manager.mark_seen_many(ids)

    for sid in ids:
        assert session_row(env.db_path, sid)["last_seen_at"] == 0
        assert env.manager.get(sid).record.last_seen_at == 0
    assert [e for e in env.recorder.envelopes if e["type"] == "session.updated"] == []


@pytest.mark.anyio
async def test_mark_seen_many_never_goes_before_last_activity(env, tmp_path):
    ids = _make_sessions(env, tmp_path, 2)
    future = int(time.time()) + 1000
    env.manager.get(ids[0]).record.last_activity_at = future  # only in memory, like mark_seen's test
    env.manager.get(ids[1]).save(last_activity_at=future)

    await env.manager.mark_seen_many(ids)

    assert env.manager.get(ids[0]).record.last_seen_at >= future
    assert env.manager.get(ids[1]).record.last_seen_at >= future
    assert session_row(env.db_path, ids[1])["last_seen_at"] >= future


@pytest.mark.anyio
async def test_mark_seen_many_memory_matches_database_when_touch_runs_during_write(
    env, tmp_path, monkeypatch
):
    import threading

    ids = _make_sessions(env, tmp_path, 2)
    _reset_seen(env, ids)
    loop = asyncio.get_running_loop()
    future = int(time.time()) + 5000
    real = env.manager._write_seen

    def write_then_touch(marks):
        result = real(marks)
        # A message arrives on the event loop right after the commit, before the
        # coroutine resumes: it must not leak into the read mark held in memory.
        done = threading.Event()

        def touch():
            env.manager.get(ids[0]).save(last_activity_at=future)
            done.set()

        loop.call_soon_threadsafe(touch)
        assert done.wait(5)
        return result

    monkeypatch.setattr(env.manager, "_write_seen", write_then_touch)

    await env.manager.mark_seen_many(ids)

    for sid in ids:
        assert env.manager.get(sid).record.last_seen_at == session_row(env.db_path, sid)["last_seen_at"]
    assert env.manager.get(ids[0]).record.last_activity_at == future
    assert env.manager.get(ids[0]).record.last_seen_at < future  # still unread


@pytest.mark.anyio
async def test_mark_seen_many_applies_memory_and_events_when_cancelled_during_write(
    env, tmp_path, monkeypatch
):
    import threading

    ids = _make_sessions(env, tmp_path, 2)
    _reset_seen(env, ids)
    env.recorder.envelopes.clear()
    real = env.manager._write_seen
    committed = threading.Event()
    release = threading.Event()

    def write_then_wait(marks):
        result = real(marks)
        committed.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(env.manager, "_write_seen", write_then_wait)

    task = asyncio.create_task(env.manager.mark_seen_many(ids))
    while not committed.is_set():
        await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):  # cancellation is not held back by the thread
        await task
    assert env.manager.get(ids[0]).record.last_seen_at == 0

    release.set()
    for _ in range(400):
        if all(env.manager.get(sid).record.last_seen_at > 0 for sid in ids):
            break
        await asyncio.sleep(0.005)

    for sid in ids:
        assert session_row(env.db_path, sid)["last_seen_at"] > 0
        assert env.manager.get(sid).record.last_seen_at == session_row(env.db_path, sid)["last_seen_at"]
    updates = [e for e in env.recorder.envelopes if e["type"] == "session.updated"]
    assert sorted(e["session_id"] for e in updates) == sorted(ids)


@pytest.mark.anyio
async def test_mark_seen_many_handles_a_large_list(env, tmp_path):
    ids = _make_sessions(env, tmp_path, 40)
    _reset_seen(env, ids)
    env.recorder.envelopes.clear()

    updated = await env.manager.mark_seen_many(ids + [f"x{i}" for i in range(460)])

    assert updated == 40
    assert len([e for e in env.recorder.envelopes if e["type"] == "session.updated"]) == 40


# 9. Listing all sessions ---------------------------------------------------


@pytest.mark.anyio
async def test_list_sessions_filters(env, tmp_path):
    other = make_project(env.db_path, tmp_path / "home" / "other")
    a = env.new_session()
    b = env.manager.get(env.manager.create_session(other).session_id)
    await env.manager.update(b.session_id, finished=True)

    all_ids = {s["session_id"] for s in env.manager.list_sessions()}
    assert all_ids == {a.session_id, b.session_id}
    assert [s["session_id"] for s in env.manager.list_sessions(project_id=other.id)] == [
        b.session_id
    ]
    assert [s["session_id"] for s in env.manager.list_sessions(display_state="finished")] == [
        b.session_id
    ]
    assert [s["session_id"] for s in env.manager.list_sessions(display_state="waiting")] == [
        a.session_id
    ]
    assert env.manager.list_sessions(project_id=other.id, display_state="waiting") == []



# Review fixes ----------------------------------------------------------------


@pytest.mark.anyio
async def test_reopen_session_finished_by_inactivity(env, env_cleanup):
    manager = build_manager(env, finished_after_days=3)
    env_cleanup.append(manager)
    session = manager.get(manager.create_session(env.project).session_id)
    session.save(last_activity_at=int(time.time()) - 4 * DAY)
    assert manager.summary(session.session_id)["display_state"] == "finished"

    summary = await manager.update(session.session_id, finished=False)

    assert summary["display_state"] != "finished"
    assert session_row(env.db_path, session.session_id)["last_activity_at"] >= int(time.time()) - 1
    [event] = env.recorder.of(session.session_id, "session.updated")
    assert event["data"]["display_state"] != "finished"


@pytest.mark.anyio
async def test_turn_end_emits_updated_with_unread(env):
    env.factory.script = lambda content: text_turn("x", "ok")
    session = env.new_session()
    session.save(last_seen_at=0)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: any(
        e["data"]["unread"] for e in env.recorder.of(session.session_id, "session.updated")
    ))
    last = env.recorder.of(session.session_id, "session.updated")[-1]
    assert last["data"]["unread"] is True
    assert last["data"]["last_activity_at"] == session.record.last_activity_at


@pytest.mark.anyio
async def test_send_emits_updated(env):
    env.factory.script = lambda content: [PauseStep()]
    session = env.new_session()
    await session.send("oi")
    assert env.recorder.of(session.session_id, "session.updated")
    await session.close()


@pytest.mark.anyio
async def test_send_waits_pending_close_before_connecting(env, env_cleanup):
    manager = build_manager(env, idle_timeout=0)
    env_cleanup.append(manager)
    env.factory.script = lambda content: text_turn("x", "ok")
    session = manager.get(manager.create_session(env.project).session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    gate = asyncio.Event()
    first = env.factory.clients[0]
    original_close = first.close

    async def slow_close():
        await gate.wait()
        await original_close()

    first.close = slow_close
    await asyncio.sleep(0.01)
    sweep = asyncio.create_task(manager.close_idle())
    await wait_until(lambda: session.state == "closed")
    send = asyncio.create_task(session.send("de novo"))
    await asyncio.sleep(0.02)
    assert len(env.factory.clients) == 1  # no second process while the first closes

    gate.set()
    await sweep
    await send
    await wait_until(lambda: session.state == "idle")
    assert len(env.factory.clients) == 2
    assert first.closed
