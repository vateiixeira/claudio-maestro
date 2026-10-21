"""Remote Control across process changes: restarts, idleness, another process taking the
conversation, finishing, the phone reopening a session and the startup reconnect.

Only the scripted fake agent is used.
"""

import asyncio
import json
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_controls import connected, options_events
from test_controls_refused import notice_texts, refused
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
    FailStep,
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
    return SimpleNamespace(id=agentd_id, pid=0, ack=0, init=None)


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
    await wait_until(lambda: session.remote_state == "on")  # same bridge, answered at once
    assert session.remote_url == URL
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_reattach_with_the_same_bridge_is_on_without_a_bridge_state(make_env, env_cleanup):
    """The CLI answers at once with the live bridge and sends no `bridge_state` again."""
    env, session = await marked(make_env, env_cleanup, spawn_version=1)

    await session.reattach(child())
    await wait_until(lambda: session.remote_state == "on")

    assert session.remote_url == URL
    assert session.remote_error is None
    assert session.record.remote_control_bridge == "cse_1"
    assert options_events(env, session)[-1]["remote_control_state"] == "on"


@pytest.mark.anyio
async def test_reattach_with_another_bridge_stays_connecting(make_env, env_cleanup):
    env, session = await marked(make_env, env_cleanup, spawn_version=1)
    original = env.factory.__call__

    def factory(options):
        made = original(options)
        made.set_remote_control_error_once = refused("bridge session expired")
        return made

    session._agent_factory = factory

    await session.reattach(child())
    await wait_until(lambda: len(calls(env.factory.clients[0])) == 2)

    assert [c["reattach_session_id"] for c in calls(env.factory.clients[0])] == ["cse_1", None]
    assert session.record.remote_control_bridge == "cse_fake"
    assert session.remote_state == "connecting"


@pytest.mark.anyio
async def test_failed_bridge_state_after_a_reattach_still_drops_to_failed(make_env, env_cleanup):
    env, session = await marked(make_env, env_cleanup, spawn_version=1)
    await session.reattach(child())
    await wait_until(lambda: session.remote_state == "on")

    env.factory.clients[0].push([bridge_state_message("failed", detail="queda")])

    await wait_until(lambda: session.remote_state == "failed")
    assert session.remote_error == "queda"


@pytest.mark.anyio
async def test_new_process_with_the_saved_bridge_waits_for_the_bridge_state(
    make_env, env_cleanup
):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de novo")
    )
    session.save(remote_control=True, remote_control_bridge="cse_1")
    await session.close()

    await session.send("outra")
    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    await wait_until(lambda: session.state == "idle")

    assert calls(env.factory.clients[1])[0]["reattach_session_id"] == "cse_1"
    assert session.remote_state == "connecting"


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


def entry(type_: str, at: float, uuid: str, **extra) -> str:
    stamp = datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": type_, "uuid": uuid, "timestamp": stamp, **extra})


def boot_with_file(env, tmp_path, lines: list[str] | None, app_modified_at: int | None):
    """A marked session with `app_modified_at` and a conversation file of `lines` (None:
    no file), and a fresh manager that reads it."""
    session = env.new_session()
    session.save(remote_control=True, remote_control_bridge="cse_1")
    if app_modified_at is not None:
        session.save(app_modified_at=app_modified_at)
    path = tmp_path / "conversation.jsonl"
    if lines is not None:
        path.write_text("\n".join(lines) + "\n")
    boot = SessionManager(
        env.db_path,
        env.recorder,
        agent_factory=env.factory,
        history_exists=lambda *a: True,
        session_file=lambda sid, directory: path if lines is not None else None,
        file_mtime=lambda sid, directory: 9_999_999.0,  # never the criterion
    )
    return session, boot


# What the CLI appends after the last turn: not a reply.
CLI_METADATA = [
    ("bridge-session", 40),
    ("cost-state", 45),
    ("last-prompt", 46),
    ("ai-title", 47),
    ("atis-latch", 48),
]


@pytest.mark.anyio
async def test_startup_does_not_connect_a_conversation_written_elsewhere(
    make_env, env_cleanup, tmp_path
):
    env = make_env()
    env_cleanup.append(env.manager)
    lines = [
        entry("assistant", 5_000, "a-app"),
        entry("assistant", 5_100, "a-terminal"),
        *[entry(kind, 5_000 + at, f"m-{kind}") for kind, at in CLI_METADATA],
    ]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=5_000)
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
async def test_startup_connects_when_only_cli_metadata_follows_the_last_turn(
    make_env, env_cleanup, tmp_path
):
    """The CLI writes `bridge-session` when Remote Control turns on and `cost-state`,
    `last-prompt`, `ai-title` and `atis-latch` when it exits; the file's mtime moves, but
    nobody else talked in the conversation."""
    env = make_env()
    env_cleanup.append(env.manager)
    lines = [
        entry("assistant", 4_990, "a-app"),
        *[entry(kind, 5_000 + at, f"m-{kind}") for kind, at in CLI_METADATA],
    ]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert [c.options.session_id for c in env.factory.clients] == [session.session_id]
    assert calls(env.factory.clients[0])[0]["enabled"] is True
    assert boot.get(session.session_id).remote_state == "connecting"


@pytest.mark.anyio
async def test_startup_ignores_a_reply_within_the_app_write_tolerance(
    make_env, env_cleanup, tmp_path
):
    env = make_env()
    env_cleanup.append(env.manager)
    lines = [entry("assistant", 5_001, "a-app")]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_startup_ignores_replies_of_subagents(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    lines = [entry("assistant", 5_100, "a-side", isSidechain=True)]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_startup_without_a_saved_app_write_date_connects(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    lines = [entry("assistant", 5_100, "a-terminal")]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=None)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_startup_without_a_conversation_file_connects(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    session, boot = boot_with_file(env, tmp_path, None, app_modified_at=5_000)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions()

    assert len(env.factory.clients) == 1


# A marked session whose process dies ---------------------------------------------------------


async def killed(make_env, env_cleanup, *, delays=(0.1,), message="Limite de uso atingido."):
    """A marked session with Remote Control on whose process then dies."""
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de novo"), lambda sid: text_turn(sid, "3")
    )
    await session.set_remote_control(True)
    session.remote_retry_delays = delays
    env.factory.clients[0].push([FailStep(message)])
    await wait_until(lambda: session.client is None)
    return env, session


@pytest.mark.anyio
async def test_failed_session_shows_failed_with_the_reason_and_reconnects(make_env, env_cleanup):
    env, session = await killed(make_env, env_cleanup)

    assert session.remote_state == "failed"
    assert session.remote_error == session.error == "Limite de uso atingido."
    assert session.record.remote_control is True
    assert session.summary()["remote_control_state"] == "failed"
    assert options_events(env, session)[-1]["remote_control_error"] == "Limite de uso atingido."

    await wait_until(lambda: len(env.factory.clients) == 2 and calls(env.factory.clients[1]))
    new = env.factory.clients[1]
    assert new.options.resume is True
    assert calls(new)[0]["enabled"] is True
    assert calls(new)[0]["reattach_session_id"] == "cse_fake"
    assert session.client is new
    assert session.remote_state == "connecting"
    assert session.remote_error is None


@pytest.mark.anyio
async def test_reconnect_after_a_failure_backs_off_and_goes_on_until_it_works(
    make_env, env_cleanup
):
    from claudio_maestro.agent import AgentError

    env, session = await killed(make_env, env_cleanup, delays=(0.05, 0.05))
    env.factory.connect_error = AgentError("sem claude")

    await wait_until(lambda: len(env.factory.clients) >= 3)
    assert session.remote_state == "failed"
    assert session.remote_error == "sem claude"
    assert session._remote_attempts >= 2

    env.factory.connect_error = None
    await wait_until(lambda: session.client is not None and session.remote_state == "connecting")
    assert calls(session.client)[0]["enabled"] is True


@pytest.mark.anyio
async def test_no_reconnect_when_the_session_leaves_the_terminal_behind(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, lambda sid: text_turn(sid, "x"))
    await session.set_remote_control(True)
    session.remote_retry_delays = (0.05,)

    assert await session.release_for_external() is True
    await asyncio.sleep(0.3)

    assert len(env.factory.clients) == 1
    assert session.remote_state == "elsewhere"


@pytest.mark.anyio
@pytest.mark.parametrize("how", ["close", "turn_off", "finish", "detach"])
async def test_no_reconnect_after_the_user_or_the_app_ends_it(make_env, env_cleanup, how):
    env, session = await killed(make_env, env_cleanup, delays=(0.2,))

    if how == "close":
        await session.close()
    elif how == "turn_off":
        await session.set_remote_control(False)
    elif how == "finish":
        await env.manager.update(session.session_id, finished=True)
    else:
        await session.detach()
    await asyncio.sleep(0.5)

    assert len(env.factory.clients) == 1
    assert session._remote_retry_task is None or session._remote_retry_task.done()


@pytest.mark.anyio
async def test_unmarked_session_failure_stays_off(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, lambda sid: text_turn(sid, "x"))
    session.remote_retry_delays = (0.05,)
    env.factory.clients[0].push([FailStep("caiu")])
    await wait_until(lambda: session.client is None)
    await asyncio.sleep(0.2)

    assert session.remote_state == "off"
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_enable_again_with_the_mark_on_and_failed_tries_at_once(make_env, env_cleanup):
    env, session = await killed(make_env, env_cleanup, delays=(60,))
    assert session.remote_state == "failed"

    summary = await env.manager.update(session.session_id, remote_control=True)

    assert len(env.factory.clients) == 2
    assert calls(env.factory.clients[1])[0]["enabled"] is True
    assert summary["remote_control_state"] == "connecting"
    assert session._remote_retry_task is None or session._remote_retry_task.done()


@pytest.mark.anyio
async def test_enable_again_with_the_mark_on_and_failed_bridge_calls_the_agent(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (60,)
    client.set_remote_control_error_once = refused("sem rede")
    await session.set_remote_control(True)
    assert session.remote_state == "failed" and len(calls(client)) == 1

    await env.manager.update(session.session_id, remote_control=True)

    assert len(calls(client)) == 2
    assert session.remote_state == "connecting"


@pytest.mark.anyio
async def test_enable_again_with_the_mark_on_and_state_off_connects(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, lambda sid: text_turn(sid, "x"))
    await session.set_remote_control(True)
    await session.close()
    assert session.remote_state == "off" and session.record.remote_control is True

    await env.manager.update(session.session_id, remote_control=True)

    assert len(env.factory.clients) == 2
    assert calls(env.factory.clients[1])[0]["enabled"] is True
    assert session.remote_state == "connecting"


@pytest.mark.anyio
async def test_enable_again_while_connecting_or_on_does_nothing(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    assert session.remote_state == "connecting"

    assert await session.set_remote_control(True) is False
    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")
    assert await session.set_remote_control(True) is False

    assert len(calls(client)) == 1


# The startup reconnect and what the reattach could not release ---------------------------------


@pytest.mark.anyio
async def test_startup_reconnect_skips_sessions_the_agentd_still_holds(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    held = env.new_session()
    held.save(remote_control=True, remote_control_bridge="cse_1")
    free = env.new_session()
    free.save(remote_control=True, remote_control_bridge="cse_2")
    boot = second_manager(env)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions({held.session_id})

    assert [c.options.session_id for c in env.factory.clients] == [free.session_id]


@pytest.mark.anyio
async def test_startup_reconnect_does_not_run_when_the_listing_failed(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(remote_control=True)
    boot = second_manager(env)
    env_cleanup.append(boot)

    await boot.reconnect_remote_sessions(None)

    assert env.factory.clients == []
    assert boot.get(session.session_id).client is None


# The automatic reconnect is quiet and does not collide with other processes -----------------------


@pytest.mark.anyio
async def test_auto_reconnect_failures_do_not_pile_up_notices_or_flip_to_error(
    make_env, env_cleanup
):
    from claudio_maestro.agent import AgentError

    env, session = await killed(make_env, env_cleanup, delays=(0.05,))
    env.factory.connect_error = AgentError("claude não encontrado")
    start = len(env.recorder.states(session.session_id))
    clients_before = len(env.factory.clients)

    await wait_until(lambda: len(env.factory.clients) >= clients_before + 3)
    states = env.recorder.states(session.session_id)[start:]

    flips = sum(1 for a, b in zip(states, states[1:]) if a != "error" and b == "error")
    errors = [i for i in session.builder.items if getattr(i, "level", None) == "error"]
    assert flips == 0 and "connecting" not in states
    assert [e.text for e in errors] == ["Limite de uso atingido."]  # the first failure only
    assert session.state == "error"
    assert session.remote_state == "failed" and session.remote_error == "claude não encontrado"


@pytest.mark.anyio
async def test_auto_reconnect_that_works_clears_the_error(make_env, env_cleanup):
    env, session = await killed(make_env, env_cleanup, delays=(0.05,))

    await wait_until(lambda: session.client is not None)

    assert session.error is None
    assert session.state != "error"


@pytest.mark.anyio
async def test_auto_reconnect_stops_when_the_project_folder_is_gone(make_env, env_cleanup):
    import shutil

    env, session = await killed(make_env, env_cleanup, delays=(0.2,))
    shutil.rmtree(session.record.work_dir())

    await asyncio.sleep(0.6)

    assert len(env.factory.clients) == 1
    assert session.remote_state == "failed"
    assert "A pasta do projeto não existe mais" in session.remote_error
    assert session._remote_retry_task is None or session._remote_retry_task.done()
    assert session._remote_attempts == 1  # the one that found the folder gone


@pytest.mark.anyio
async def test_a_dead_session_whose_folder_is_already_gone_is_not_retried(make_env, env_cleanup):
    import shutil

    env, session = await connected(make_env, env_cleanup, lambda sid: text_turn(sid, "x"))
    await session.set_remote_control(True)
    session.remote_retry_delays = (0.05,)
    shutil.rmtree(session.record.work_dir())
    env.factory.clients[0].push([FailStep("caiu")])
    await wait_until(lambda: session.client is None)

    await asyncio.sleep(0.3)

    assert len(env.factory.clients) == 1
    assert session.remote_state == "failed"
    assert "A pasta do projeto não existe mais" in session.remote_error
    assert session._remote_attempts == 0


@pytest.mark.anyio
async def test_auto_reconnect_waits_while_the_cli_signal_is_up_and_goes_on_after(
    make_env, env_cleanup
):
    import time

    env, session = await killed(make_env, env_cleanup, delays=(0.1,))
    env.manager.note_cli_turn(session.session_id, open=True, activity_at=time.time())

    await asyncio.sleep(0.5)

    # Not `elsewhere` (the signal alone may be the app's own dead process): it waits and
    # asks again with the growing interval.
    assert len(env.factory.clients) == 1
    assert session.remote_state == "failed"
    assert session._remote_attempts >= 2
    assert session._remote_retry_task is not None and not session._remote_retry_task.done()

    env.manager.note_cli_turn(session.session_id, open=False, activity_at=0.0)
    await wait_until(lambda: session.client is not None and session.remote_state == "connecting")
    assert calls(session.client)[0]["enabled"] is True


@pytest.mark.anyio
async def test_auto_reconnect_goes_elsewhere_on_a_reply_of_another_process(
    make_env, env_cleanup, tmp_path
):
    import time

    env = make_env()
    env_cleanup.append(env.manager)
    lines = [entry("assistant", 5_000, "a-app"), entry("assistant", 5_100, "a-terminal")]
    session, boot = boot_with_file(env, tmp_path, lines, app_modified_at=5_000)
    env_cleanup.append(boot)
    reopened = boot.get(session.session_id)
    reopened.remote_retry_delays = (0.05,)
    boot.note_cli_turn(session.session_id, open=True, activity_at=time.time())

    await reopened._remote_reconnect(0)

    assert reopened.remote_state == "elsewhere"
    assert env.factory.clients == []


@pytest.mark.anyio
async def test_auto_reconnect_respects_what_the_agentd_still_holds(make_env, env_cleanup):
    env, session = await killed(make_env, env_cleanup, delays=(0.2,))
    await env.manager.reconnect_remote_sessions({session.session_id})

    await asyncio.sleep(0.5)

    assert len(env.factory.clients) == 1
    assert session.client is None
    assert session.remote_state == "failed"
    assert session._remote_retry_task is None or session._remote_retry_task.done()
