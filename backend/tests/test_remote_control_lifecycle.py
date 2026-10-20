"""Remote Control across process changes: restarts, idleness, another process taking the
conversation, finishing, the phone reopening a session and the startup reconnect.

Only the scripted fake agent is used.
"""

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_controls import connected, options_events
from test_controls_refused import notice_texts
from test_sessions import (  # noqa: F401
    by_session,
    env_cleanup,
    make_env,
    make_project,
    session_row,
    wait_until,
)

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    PauseStep,
    bridge_state_message,
    remote_user_message,
    result_message,
    text_turn,
    tool_turn,
)
from claudio_maestro.sessions import SPAWN_VERSION, SessionManager

URL = "https://claude.ai/code/session_fake"


def calls(client) -> list[dict]:
    return client.remote_control_calls


def child(agentd_id: str = "child-1"):
    """What the agentd lists for a process it kept."""
    return SimpleNamespace(id=agentd_id, ack=0, init=None)


async def marked(make_env, env_cleanup, *, spawn_version: int, **kwargs):
    """A session with the mark on, a bridge saved and no client, in a fresh env."""
    env = make_env(**kwargs)
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(
        remote_control=True, remote_control_bridge="cse_1", spawn_version=spawn_version
    )
    return env, session


# Spawn version ---------------------------------------------------------------


def test_spawn_version_is_one():
    assert SPAWN_VERSION == 1


@pytest.mark.anyio
async def test_new_process_records_the_spawn_version(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    assert session.record.spawn_version == SPAWN_VERSION
    assert session_row(env.db_path, session.session_id)["spawn_version"] == SPAWN_VERSION


# New process for a marked session ----------------------------------------------


@pytest.mark.anyio
async def test_new_client_reenables_with_saved_bridge(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de novo")
    )
    session.save(remote_control=True, remote_control_bridge="cse_1")
    await session.close()
    assert session.remote_state == "off"

    await session.send("outra")
    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))

    fresh = env.factory.clients[1]
    assert fresh.options.resume is True
    assert calls(fresh) == [
        {"enabled": True, "name": session.record.title, "reattach_session_id": "cse_1"}
    ]
    await wait_until(lambda: session.state == "idle")
    assert session.remote_state == "connecting"
    assert session.remote_url == URL


@pytest.mark.anyio
async def test_unmarked_session_never_asks_for_remote_control(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de novo")
    )
    await session.close()

    await session.send("outra")
    await wait_until(lambda: session.state == "idle")

    assert calls(env.factory.clients[1]) == []


@pytest.mark.anyio
async def test_connect_does_not_wait_for_remote_control(make_env, env_cleanup):
    """A slow bridge must not hold back the message that reconnected the session."""
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de novo")
    )
    session.save(remote_control=True)
    await session.close()
    pause = PauseStep()
    factory = session._agent_factory

    def slow(options):
        client = factory(options)
        client.remote_control_pause = pause
        return client

    session._agent_factory = slow

    await session.send("outra")

    await asyncio.wait_for(pause.reached.wait(), 1)
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)
    assert env.factory.clients[1].sent == ["outra"]
    pause.release.set()
    await wait_until(lambda: session.remote_state == "connecting")


# Same process after a backend restart ------------------------------------------


@pytest.mark.anyio
async def test_reattach_reenables_on_same_process(make_env, env_cleanup):
    env, session = await marked(make_env, env_cleanup, spawn_version=1)

    assert await session.reattach(child()) is True

    assert len(env.factory.clients) == 1
    client = env.factory.clients[0]
    assert client.options.attach is not None
    await wait_until(lambda: len(calls(client)) == 1)
    assert calls(client)[0]["enabled"] is True
    assert calls(client)[0]["reattach_session_id"] == "cse_1"
    assert session.remote_state == "connecting"

    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")
    assert session.remote_url == URL
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_reattach_without_the_mark_asks_nothing(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.reattach(child())
    await asyncio.sleep(0.02)

    assert calls(env.factory.clients[0]) == []
    assert session.remote_state == "off"


@pytest.mark.anyio
async def test_reattach_old_process_respawns_between_turns(make_env, env_cleanup):
    env, session = await marked(make_env, env_cleanup, spawn_version=0)

    assert await session.reattach(child()) is True

    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    old, fresh = env.factory.clients
    assert old.options.attach is not None and old.closed is True
    assert fresh.options.attach is None and fresh.options.resume is True
    assert calls(old) == []
    assert calls(fresh)[0]["enabled"] is True
    assert calls(fresh)[0]["reattach_session_id"] == "cse_1"
    assert session.effort_pending is False
    assert session.respawn_pending is False
    assert session.record.spawn_version == SPAWN_VERSION
    assert options_events(env, session)[-1]["effort_pending"] is False
    assert "vale a partir do próximo turno" not in " ".join(
        text for _level, text in notice_texts(session)
    )


@pytest.mark.anyio
async def test_old_process_waits_for_the_open_turn_before_respawning(make_env, env_cleanup):
    env, session = await marked(make_env, env_cleanup, spawn_version=0)
    session.save(turn_open=True)

    await session.reattach(child())
    await asyncio.sleep(0.05)

    # The turn the backend left behind is still open: the process stays.
    assert len(env.factory.clients) == 1
    assert session.respawn_pending is True
    assert session.effort_pending is False
    assert session.remote_state == "connecting"

    env.factory.clients[0].push([result_message(session.session_id)])
    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    assert session.respawn_pending is False


# Turning it on in a process that came from before ------------------------------------


@pytest.mark.anyio
async def test_enable_on_old_process_respawns_first(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    session.save(spawn_version=0)
    old = env.factory.clients[0]

    await session.set_remote_control(True)

    assert len(env.factory.clients) == 2
    fresh = env.factory.clients[1]
    assert old.closed is True and calls(old) == []
    assert fresh.options.resume is True
    assert calls(fresh)[-1]["enabled"] is True
    assert session.client is fresh
    assert session.remote_state == "connecting"
    assert session.remote_url == URL
    assert session.effort_pending is False
    assert session.respawn_pending is False


@pytest.mark.anyio
async def test_enable_on_old_process_waits_for_the_running_turn(make_env, env_cleanup):
    pause = PauseStep()

    def slow(sid):
        turn = text_turn(sid, "devagar")
        return [*turn[:3], pause, *turn[3:]]

    env, session = await connected(make_env, env_cleanup, slow)
    session.save(spawn_version=0)
    await session.send("lento")
    await asyncio.wait_for(pause.reached.wait(), 1)

    await session.set_remote_control(True)

    assert session.record.remote_control is True
    assert session.remote_state == "connecting"
    assert len(env.factory.clients) == 1
    assert calls(env.factory.clients[0]) == []

    pause.release.set()
    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    assert calls(env.factory.clients[1])[-1]["enabled"] is True
    assert calls(env.factory.clients[0]) == []


# Idleness ------------------------------------------------------------------------


@pytest.mark.anyio
async def test_idle_close_skips_remote_sessions(make_env, env_cleanup):
    env = make_env(script=lambda content: text_turn("x", "oi"))
    env_cleanup.append(env.manager)
    marked_session, plain = env.new_session(), env.new_session()
    for session in (marked_session, plain):
        await session.send("oi")
        await wait_until(lambda session=session: session.state == "idle")
    await marked_session.set_remote_control(True)
    env.manager._idle_timeout = 0

    await env.manager.close_idle()

    assert marked_session.client is not None
    assert not env.factory.clients[0].closed
    assert plain.client is None
    assert env.factory.clients[1].closed is True


@pytest.mark.anyio
async def test_close_project_closes_and_keeps_the_mark(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)
    env.factory.clients[0].push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")

    await env.manager.close_project(env.project.id)

    assert env.factory.clients[0].closed is True
    assert session.remote_state == "off"
    assert session.record.remote_control is True


# Another process takes the conversation ------------------------------------------------


@pytest.mark.anyio
async def test_external_write_pauses_remote(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "voltei")
    )
    await session.set_remote_control(True)
    old = env.factory.clients[0]

    assert await session.release_for_external() is True

    assert old.closed is True and session.client is None
    assert session.remote_state == "elsewhere"
    assert session.record.remote_control is True
    assert options_events(env, session)[-1]["remote_control_state"] == "elsewhere"
    assert session.summary()["remote_control_state"] == "elsewhere"

    # The state survives the sweep that forgets closed sessions.
    env.manager.forget_closed()
    assert env.manager.get(session.session_id) is session

    await session.send("volto")
    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    assert calls(env.factory.clients[1])[-1]["enabled"] is True
    assert session.remote_state != "elsewhere"


@pytest.mark.anyio
async def test_external_write_without_the_mark_leaves_the_state_off(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    assert await session.release_for_external() is True

    assert session.remote_state == "off"


# Finishing and discarding ---------------------------------------------------------------


@pytest.mark.anyio
async def test_finish_disables_remote(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, finished=True)

    assert calls(client)[-1]["enabled"] is False
    assert session.record.remote_control is False
    assert session.record.remote_control_bridge is None
    assert session.remote_state == "off"
    row = session_row(env.db_path, session.session_id)
    assert row["remote_control"] == 0 and row["remote_control_bridge"] is None


@pytest.mark.anyio
async def test_discard_mark_disables_remote(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="discarded")

    assert calls(client)[-1]["enabled"] is False
    assert session.record.remote_control is False
    assert session.record.remote_control_bridge is None
    assert session.remote_state == "off"


@pytest.mark.anyio
async def test_other_marks_keep_remote(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)

    await env.manager.update(session.session_id, mark="on_hold", mark_until=None)

    assert session.record.remote_control is True
    assert [c["enabled"] for c in calls(env.factory.clients[0])] == [True]


# The phone ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_phone_message_reopens_finished_session(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.save(finished=True, finished_at=123, mark="on_hold")
    sid = session.session_id

    client.push([remote_user_message("oi do celular"), *text_turn(sid, "oi")])
    await wait_until(lambda: session.record.finished is False)

    assert session.record.finished_at is None
    assert session.record.mark is None
    assert session_row(env.db_path, sid)["finished"] == 0
    updated = env.recorder.of(sid, "session.updated")
    assert updated[-1]["data"]["finished"] is False


@pytest.mark.anyio
async def test_agent_message_does_not_reopen(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.save(finished=True, finished_at=123)

    client.push(text_turn(session.session_id, "autônomo"))
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)
    await asyncio.sleep(0.02)

    assert session.record.finished is True


@pytest.mark.anyio
async def test_phone_message_during_maestro_turn_keeps_turn_count(make_env, env_cleanup):
    pause = PauseStep()

    def maestro_turn(sid):
        turn = text_turn(sid, "do maestro")
        return [*turn[:3], pause, *turn[3:]]

    env, session = await connected(make_env, env_cleanup, maestro_turn)
    client = env.factory.clients[0]
    sid = session.session_id
    await session.send("pergunta")
    await asyncio.wait_for(pause.reached.wait(), 1)
    assert session.pending_turns == 1

    client.push([remote_user_message("e esta, do celular"), *text_turn(sid, "do celular")])
    pause.release.set()
    await wait_until(
        lambda: [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
        == ["oi", "do maestro", "do celular"]
    )
    await wait_until(lambda: session.state == "idle")

    assert session.pending_turns == 0
    assert session.state == "idle"
    users = [i for i in session.snapshot()["items"] if i["type"] == "user"]
    assert [(u["text"], u.get("remote", False)) for u in users] == [
        ("olá", False), ("pergunta", False), ("e esta, do celular", True)
    ]


@pytest.mark.anyio
async def test_prompt_answered_on_phone_removes_card(make_env, env_cleanup):
    script, ids = by_session(lambda sid: tool_turn(sid, tool_name="Bash", ask_permission=True))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("rode")
    await wait_until(lambda: bool(session.prompts))
    [prompt_id] = list(session.prompts)

    env.factory.clients[0].cancel_permission_request()

    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)
    resolved = env.recorder.of(session.session_id, "prompt.resolved")
    assert [(e["data"]["prompt_id"], e["data"]["decision"]) for e in resolved] == [
        (prompt_id, "cancelled")
    ]
    assert session.prompts == {}
    assert session.error is None
    assert not [text for level, text in notice_texts(session) if level == "error"]
    assert session.client is env.factory.clients[0]


# Startup ------------------------------------------------------------------------------------------


def second_manager(env) -> SessionManager:
    """A new process of the backend over the same database and agent."""
    return SessionManager(
        env.db_path, env.recorder, agent_factory=env.factory, history_exists=lambda *a: True
    )


@pytest.mark.anyio
async def test_startup_reconnects_marked_sessions(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    live = env.new_session()
    live.save(remote_control=True, remote_control_bridge="cse_1")
    done = env.new_session()
    done.save(remote_control=True, finished=True)
    plain = env.new_session()
    gone_project = make_project(env.db_path, tmp_path / "home" / "other")
    gone = env.manager.create_session(gone_project)
    env.manager.get(gone.session_id).save(remote_control=True)
    with closing(db.connect(env.db_path)) as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (gone_project.id,))
    boot = second_manager(env)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert [c.options.session_id for c in env.factory.clients] == [live.session_id]
    client = env.factory.clients[0]
    assert client.options.resume is True
    assert calls(client)[0]["enabled"] is True
    assert calls(client)[0]["reattach_session_id"] == "cse_1"
    reopened = boot.get(live.session_id)
    assert reopened.client is client
    assert reopened.remote_state == "connecting"
    assert plain.client is None and done.client is None


@pytest.mark.anyio
async def test_startup_skips_a_session_the_agentd_gave_back(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(remote_control=True, spawn_version=1)
    boot = second_manager(env)
    env_cleanup.append(boot)
    attached = boot.get(session.session_id)
    assert await attached.reattach(child()) is True
    await wait_until(lambda: len(calls(env.factory.clients[0])) == 1)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_startup_connect_failure_leaves_the_mark_and_does_not_raise(
    make_env, env_cleanup
):
    from claudio_maestro.agent import AgentError

    env = make_env(connect_error=AgentError("sem claude"))
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(remote_control=True)
    boot = second_manager(env)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    reopened = boot.get(session.session_id)
    assert reopened.record.remote_control is True
    assert reopened.remote_state == "failed"
    assert reopened.remote_error == "sem claude"


@pytest.mark.anyio
async def test_startup_does_nothing_without_marked_sessions(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    env.new_session()

    await env.manager.reconnect_remote_sessions()

    assert env.factory.clients == []


# The app's lifespan -----------------------------------------------------------------------------


def test_app_startup_reconnects_marked_sessions_in_the_background(data_dir, tmp_path):
    import time

    from fastapi.testclient import TestClient

    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.app import create_app
    from claudio_maestro.config import DB_FILENAME

    db_path = data_dir / DB_FILENAME
    db.init_db(db_path)
    project = make_project(db_path, tmp_path / "home" / "app")
    factory = FakeAgentFactory()
    seed = SessionManager(db_path, lambda envelope: None, agent_factory=factory)
    record = seed.create_session(project)
    seed.get(record.session_id).save(remote_control=True, remote_control_bridge="cse_1")
    headers = {"origin": "http://localhost:6600", "x-maestro": "1"}

    app = create_app(agent_factory=factory)
    with TestClient(app, base_url="http://127.0.0.1:6660", headers=headers):
        deadline = time.monotonic() + 5
        while not (factory.clients and factory.clients[0].remote_control_calls):
            assert time.monotonic() < deadline, "the marked session was not reconnected"
            time.sleep(0.01)

    client = factory.clients[0]
    assert client.options.session_id == record.session_id
    assert client.remote_control_calls[0]["enabled"] is True
    assert client.remote_control_calls[0]["reattach_session_id"] == "cse_1"


# Startup does not take a conversation another process is using -----------------------------------


def boot_with_file_dates(env, mtime: float, app_modified_at: int):
    session = env.new_session()
    session.save(remote_control=True, remote_control_bridge="cse_1", app_modified_at=app_modified_at)
    boot = SessionManager(
        env.db_path,
        env.recorder,
        agent_factory=env.factory,
        history_exists=lambda *a: True,
        file_mtime=lambda sid, directory: mtime,
    )
    return session, boot


@pytest.mark.anyio
async def test_startup_does_not_connect_a_conversation_written_elsewhere(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session, boot = boot_with_file_dates(env, mtime=5_100.0, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert env.factory.clients == []
    reopened = boot.get(session.session_id)
    assert reopened.client is None
    assert reopened.remote_state == "elsewhere"
    assert reopened.record.remote_control is True
    assert reopened.record.remote_control_bridge == "cse_1"
    assert reopened.summary()["remote_control_state"] == "elsewhere"
    # The sweep that forgets closed sessions keeps what only memory knows.
    boot.forget_closed()
    assert boot.get(session.session_id) is reopened


@pytest.mark.anyio
async def test_startup_connects_a_conversation_the_app_left_untouched(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    # Within the tolerance of the app's own last write.
    session, boot = boot_with_file_dates(env, mtime=5_001.0, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert [c.options.session_id for c in env.factory.clients] == [session.session_id]
    assert calls(env.factory.clients[0])[0]["enabled"] is True
    assert boot.get(session.session_id).remote_state == "connecting"


@pytest.mark.anyio
async def test_startup_without_a_saved_app_write_date_connects(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(remote_control=True)
    boot = SessionManager(
        env.db_path, env.recorder, agent_factory=env.factory, history_exists=lambda *a: True,
        file_mtime=lambda sid, directory: 9_999.0,
    )
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1
