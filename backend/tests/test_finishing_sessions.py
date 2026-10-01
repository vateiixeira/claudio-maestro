"""Marco 6 (finishing): robustness of active sessions.

Default permission mode, project removal, disposal on cancel, external activity
after restart, history retry, snapshot size, background subagent interrupt,
readable failures and the subscription limit. Only fakes; no real SDK.
"""

import asyncio
import json
import logging
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    RateLimitInfo,
    TextBlock,
)
from history_fakes import FakeHistory, user_entry

from test_controls_review import with_background_agent
from test_sessions import env_cleanup, make_env, session_row, wait_until  # noqa: F401
from claudio_maestro import db
from claudio_maestro.agent.fake import (
    FailStep,
    FakeAgentFactory,
    PauseStep,
    _Closed,
    init_message,
    result_message,
    text_turn,
)
from claudio_maestro.history import Transcript
from claudio_maestro.sessions import SessionManager, user_default_permission_mode

WAIT = 2


# Helpers -------------------------------------------------------------------


def write_settings(tmp_path: Path, content: Any) -> None:
    folder = tmp_path / "claude-config"
    folder.mkdir(exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content)
    (folder / "settings.json").write_text(text)


class SlowConnectFactory(FakeAgentFactory):
    """Clients whose connect() waits until the test opens the gate."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.gate = asyncio.Event()
        self.connecting = asyncio.Event()

    def __call__(self, options):
        client = super().__call__(options)
        original = client.connect

        async def connect() -> None:
            self.connecting.set()
            await self.gate.wait()
            await original()

        client.connect = connect  # type: ignore[method-assign]
        return client


class HistoryEnv:
    """Manager over fake history functions and a fake file mtime."""

    def __init__(self, tmp_path: Path, script=None, **manager_kwargs: Any) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.folder = tmp_path / "home" / "app"
        self.folder.mkdir(parents=True, exist_ok=True)
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute("SELECT id FROM projects WHERE path = ?", (str(self.folder),))
            existing = row.fetchone()
            if existing is None:
                self.project_id = conn.execute(
                    "INSERT INTO projects (name, path, color, position, created_at)"
                    " VALUES ('app', ?, '#ff8800', 0, 0)",
                    (str(self.folder),),
                ).lastrowid
            else:
                self.project_id = existing["id"]
        self.fake = FakeHistory()
        self.factory = FakeAgentFactory(script=script)
        self.events: list[dict[str, Any]] = []
        self.mtimes: dict[str, float] = {}
        kwargs: dict[str, Any] = {
            "agent_factory": self.factory,
            "history_exists": lambda sid, cwd: sid in self.fake.messages,
            "rename_session": self.fake.rename_session,
            "list_sessions": self.fake.list_sessions,
            "get_session_messages": self.fake.get_session_messages,
            "read_tool_results": self.fake.read_tool_results,
            "file_mtime": lambda sid, cwd: self.mtimes.get(sid),
        }
        kwargs.update(manager_kwargs)
        self.manager = SessionManager(self.db_path, self.events.append, **kwargs)

    def add_old_session(self, session_id: str = "old-1") -> str:
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, last_seen_at, finished) VALUES (?, ?, ?, 'Antiga', 1, 2, 2, 0)",
                (session_id, self.project_id, str(self.folder)),
            )
        self.fake.messages[session_id] = [user_entry("oi", session_id)]
        return session_id


@pytest.fixture
async def history_env(tmp_path: Path):
    envs: list[HistoryEnv] = []

    def build(**kwargs: Any) -> HistoryEnv:
        env = HistoryEnv(tmp_path, **kwargs)
        envs.append(env)
        return env

    yield build
    for env in envs:
        await env.manager.shutdown()


# 1. Default permission mode -------------------------------------------------


def test_default_mode_read_from_user_settings(tmp_path):
    write_settings(tmp_path, {"permissions": {"defaultMode": "acceptEdits"}})
    assert user_default_permission_mode() == "acceptEdits"


@pytest.mark.parametrize("content", [None, "{nao é json", {"permissions": "x"}, [],
                                     {"permissions": {"defaultMode": "inventado"}},
                                     {"permissions": {"defaultMode": 3}}])
def test_default_mode_tolerates_missing_or_invalid_settings(tmp_path, content):
    if content is not None:
        write_settings(tmp_path, content)
    assert user_default_permission_mode() is None


def test_default_mode_ignores_bypass_and_logs(tmp_path, caplog):
    write_settings(tmp_path, {"permissions": {"defaultMode": "bypassPermissions"}})
    with caplog.at_level(logging.WARNING):
        assert user_default_permission_mode() is None
    assert "bypassPermissions" in caplog.text


@pytest.mark.anyio
async def test_new_session_starts_in_user_default_mode(make_env, env_cleanup, tmp_path):
    write_settings(tmp_path, {"permissions": {"defaultMode": "auto"}})
    env = make_env(script=lambda content: [])
    env_cleanup.append(env.manager)

    session = env.new_session()

    assert session.record.permission_mode == "auto"
    assert session_row(env.db_path, session.session_id)["permission_mode"] == "auto"
    await session.send("oi")
    assert env.factory.clients[0].options.permission_mode == "auto"


@pytest.mark.anyio
async def test_session_with_mode_keeps_it_when_settings_change(make_env, env_cleanup, tmp_path):
    write_settings(tmp_path, {"permissions": {"defaultMode": "acceptEdits"}})
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    write_settings(tmp_path, {"permissions": {"defaultMode": "plan"}})

    other = SessionManager(env.db_path, lambda e: None, agent_factory=env.factory)
    env_cleanup.append(other)

    assert other.get(session.session_id).record.permission_mode == "acceptEdits"


@pytest.mark.anyio
async def test_new_session_without_settings_has_no_mode(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    assert env.new_session().record.permission_mode is None


# 2. Removing a project waits for connects -----------------------------------


@pytest.mark.anyio
async def test_close_project_waits_for_connect_in_progress(make_env, env_cleanup):
    factory = SlowConnectFactory()
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()

    send = asyncio.create_task(session.send("oi"))
    await asyncio.wait_for(factory.connecting.wait(), WAIT)
    closing_task = asyncio.create_task(env.manager.close_project(env.project.id))
    await asyncio.sleep(0.05)

    assert not closing_task.done()
    factory.gate.set()
    await asyncio.wait_for(closing_task, WAIT)
    assert send.done()
    assert factory.clients[0].closed
    assert session.session_id not in env.manager.active_ids()


# 3. Cancel during connect goes through the disposal control -----------------


@pytest.mark.anyio
async def test_close_after_cancelled_connect_is_tracked_as_disposal(make_env, env_cleanup):
    factory = SlowConnectFactory()
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    session = env.new_session()

    send = asyncio.create_task(session.send("oi"))
    await asyncio.wait_for(factory.connecting.wait(), WAIT)
    client = factory.clients[0]
    client.close_pause = PauseStep()
    send.cancel()
    await asyncio.wait_for(client.close_pause.reached.wait(), WAIT)
    send.cancel()  # a second cancel no longer waits for the close
    await asyncio.wait([send], timeout=WAIT)
    assert send.done()

    assert not session.forgettable  # the close is still running
    client.close_pause.release.set()
    await wait_until(lambda: session.forgettable)
    assert client.closed


# 4. External activity without false positives --------------------------------


@pytest.mark.anyio
async def test_app_records_file_mtime_at_turn_end(history_env, tmp_path):
    ids: list[str] = []
    env = history_env(script=lambda content: text_turn(ids[0], "ok"))
    sid = env.add_old_session()
    ids.append(sid)
    mtime = time.time() - 5
    env.mtimes[sid] = mtime

    await env.manager.send(sid, "oi")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")

    await wait_until(lambda: session_row(env.db_path, sid)["app_modified_at"] == int(mtime))


@pytest.mark.anyio
async def test_no_external_activity_after_backend_restart(history_env, tmp_path):
    ids: list[str] = []
    env = history_env(script=lambda content: text_turn(ids[0], "ok"))
    sid = env.add_old_session()
    ids.append(sid)
    env.mtimes[sid] = time.time() - 5
    await env.manager.send(sid, "oi")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")
    await env.manager.shutdown()

    restarted = history_env()
    restarted.fake.messages = env.fake.messages
    restarted.mtimes = env.mtimes

    snapshot = await restarted.manager.open(sid)
    assert snapshot["external_activity"] is False

    # Someone else writes the file afterwards: now it counts.
    restarted.mtimes[sid] = time.time()
    restarted.manager.forget_closed()
    snapshot = await restarted.manager.open(sid)
    assert snapshot["external_activity"] is True


@pytest.mark.anyio
async def test_no_external_activity_after_process_failure(history_env):
    ids: list[str] = []
    env = history_env(script=lambda content: [init_message(ids[0]), FailStep()])
    sid = env.add_old_session()
    ids.append(sid)
    mtime = time.time() - 3
    env.mtimes[sid] = mtime

    await env.manager.send(sid, "oi")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "error")
    await wait_until(lambda: session_row(env.db_path, sid)["app_modified_at"] == int(mtime))

    await env.manager.shutdown()
    restarted = history_env()
    restarted.fake.messages = env.fake.messages
    restarted.mtimes = env.mtimes
    assert (await restarted.manager.open(sid))["external_activity"] is False


# 6. File info by stat -------------------------------------------------------


@pytest.mark.anyio
async def test_file_info_comes_from_stat_not_listing(history_env):
    env = history_env()
    sid = env.add_old_session()
    env.mtimes[sid] = time.time() - 10

    snapshot = await env.manager.open(sid)

    assert env.fake.list_calls == []
    assert session_row(env.db_path, sid)["file_modified_at"] == int(env.mtimes[sid])
    assert snapshot["external_activity"] is True


# 7. Corrupt transcript and compaction ----------------------------------------


@pytest.mark.anyio
async def test_skipped_lines_show_a_warning(history_env):
    def read_transcript(session_id, directory):
        return Transcript(messages=[user_entry("oi", session_id)], tool_results={},
                          skipped_lines=2)

    env = history_env(read_transcript=read_transcript)
    sid = env.add_old_session()

    items = (await env.manager.open(sid))["items"]

    assert [i["type"] for i in items] == ["user", "notice"]
    assert items[1]["level"] == "warning"
    assert items[1]["text"] == "Parte do histórico não pôde ser lida."


@pytest.mark.anyio
async def test_compact_summary_becomes_info_notice(history_env):
    summary = user_entry("Resumo do que aconteceu antes", "old-1", uuid="c1")

    def read_transcript(session_id, directory):
        return Transcript(messages=[summary, user_entry("depois", session_id, uuid="u2")],
                          tool_results={}, compact_uuids={"c1"})

    env = history_env(read_transcript=read_transcript)
    sid = env.add_old_session()

    items = (await env.manager.open(sid))["items"]

    assert [(i["type"], i.get("level"), i["text"]) for i in items] == [
        ("notice", "info", "Conversa compactada"), ("user", None, "depois"),
    ]


@pytest.mark.anyio
async def test_compact_summary_text_is_recognised_without_flag(history_env):
    env = history_env()
    sid = env.add_old_session()
    env.fake.messages[sid] = [user_entry(
        "This session is being continued from a previous conversation that ran out of"
        " context. The conversation is summarized below: ...", sid)]

    items = (await env.manager.open(sid))["items"]

    assert [(i["type"], i["text"]) for i in items] == [("notice", "Conversa compactada")]


# 8. Retry after a failed load -----------------------------------------------


@pytest.mark.anyio
async def test_history_load_is_retried_after_failure(history_env):
    env = history_env()
    sid = env.add_old_session()
    working = env.fake.get_session_messages
    calls = {"n": 0}

    def flaky(session_id, directory):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("quebrou")
        return working(session_id, directory)

    env.manager._get_session_messages = flaky
    first = await env.manager.open(sid)
    assert [i["type"] for i in first["items"]] == ["notice"]

    second = await env.manager.open(sid)
    assert [(i["type"], i["text"]) for i in second["items"]] == [("user", "oi")]
    assert calls["n"] == 2


# 5. Snapshot size -----------------------------------------------------------


@pytest.mark.anyio
async def test_snapshot_is_capped_dropping_oldest_items(history_env, monkeypatch):
    monkeypatch.setattr("claudio_maestro.sessions.SNAPSHOT_MAX_BYTES", 3_000)
    env = history_env()
    sid = env.add_old_session()
    env.fake.messages[sid] = [user_entry(f"m{n} " + "x" * 200, sid) for n in range(40)]

    snapshot = await env.manager.open(sid)

    assert snapshot["history_truncated"] is True
    assert len(json.dumps(snapshot["items"])) <= 3_000
    assert snapshot["items"][-1]["text"].startswith("m39 ")
    assert 0 < len(snapshot["items"]) < 40


# 13. Interrupting background subagents ---------------------------------------


@pytest.mark.anyio
async def test_interrupt_stops_background_subagents(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]

    await session.interrupt()

    assert client.stopped_tasks == ["task-1"]
    assert client.interrupts == 0


@pytest.mark.anyio
async def test_interrupt_without_turn_or_subagent_does_nothing(make_env, env_cleanup):
    ids: list[str] = []
    env = make_env(script=lambda content: text_turn(ids[0], "ok"))
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    await session.interrupt()

    assert env.factory.clients[0].stopped_tasks == []
    assert env.factory.clients[0].interrupts == 0


# 14. Readable failures --------------------------------------------------------


@pytest.mark.anyio
async def test_process_gone_puts_session_in_readable_error(make_env, env_cleanup):
    ids: list[str] = []
    env = make_env(script=lambda content: [init_message(ids[0])])
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("oi")
    await wait_until(lambda: session.client is not None)

    env.factory.clients[0]._out.put_nowait(_Closed())  # the stream ends by itself
    await wait_until(lambda: session.state == "error")

    assert session.error == "O agente encerrou a conexão."


@pytest.mark.anyio
async def test_authentication_failed_shows_login_message(make_env, env_cleanup):
    ids: list[str] = []

    def script(content):
        sid = ids[0]
        return [
            init_message(sid),
            AssistantMessage(content=[TextBlock(text="Please run /login")], model="haiku",
                             error="authentication_failed", message_id="msg_e"),
            result_message(sid, subtype="success", is_error=True),
        ]

    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    notices = [i for i in session.snapshot()["items"] if i["type"] == "notice"]
    assert [n["text"] for n in notices] == [
        "Falha de autenticação. Rode `claude` no terminal e faça /login."
    ]


# 15. Subscription limit -------------------------------------------------------


@pytest.mark.anyio
async def test_rejected_rate_limit_puts_session_in_error_with_release_time(
    make_env, env_cleanup
):
    ids: list[str] = []
    resets_at = int(time.time()) + 3600

    def script(content):
        return [
            init_message(ids[0]),
            RateLimitEvent(
                rate_limit_info=RateLimitInfo(status="rejected", resets_at=resets_at,
                                              rate_limit_type="five_hour"),
                uuid="r", session_id=ids[0],
            ),
        ]

    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("oi")
    await wait_until(lambda: session.state == "error")

    when = datetime.fromtimestamp(resets_at).astimezone()
    expected = "Limite da assinatura atingido. Libera às " + when.strftime("%H:%M")
    assert session.error.startswith(expected)
    errors = [i for i in session.snapshot()["items"]
              if i["type"] == "notice" and i["level"] == "error"]
    assert len(errors) == 1 and errors[0]["text"] == session.error


# SDK client: stop_task and login ------------------------------------------------


@pytest.mark.anyio
async def test_sdk_client_forwards_stop_task(tmp_path):
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.sdk_client import SdkAgentClient

    stub = StubSdkClient()
    stopped: list[str] = []

    async def stop_task(task_id):
        stopped.append(task_id)

    stub.stop_task = stop_task
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()
    await client.stop_task("task-9")

    assert stopped == ["task-9"]


@pytest.mark.anyio
@pytest.mark.parametrize("stderr", ["Invalid API key · Please run /login",
                                    "OAuth token has expired. Please run /login"])
async def test_expired_login_on_connect_is_readable(tmp_path, stderr):
    from claude_agent_sdk import ProcessError
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.sdk_client import LOGIN_MESSAGE, SdkAgentClient

    stub = StubSdkClient(connect_error=ProcessError("Command failed", exit_code=1))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    client.sdk_options.stderr(stderr)

    with pytest.raises(AgentError) as error:
        await client.connect()

    assert error.value.message_pt == LOGIN_MESSAGE
    assert "/login" in LOGIN_MESSAGE


@pytest.mark.anyio
@pytest.mark.parametrize("stderr", ["Not logged in · Please run /login", "OAuth token revoked · Please run /login",
                                    "Login expired · Please run /login",
                                    "Failed to authenticate: OAuth session expired and could not be refreshed"])
async def test_specific_cli_login_phrases_are_recognised(tmp_path, stderr):
    from claude_agent_sdk import ProcessError
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.sdk_client import LOGIN_MESSAGE, SdkAgentClient

    stub = StubSdkClient(connect_error=ProcessError("Command failed", exit_code=1))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    client.sdk_options.stderr(stderr)

    with pytest.raises(AgentError) as error:
        await client.connect()

    assert error.value.message_pt == LOGIN_MESSAGE


@pytest.mark.anyio
async def test_stray_login_mention_does_not_turn_process_death_into_expired_login(tmp_path):
    from claude_agent_sdk import ProcessError
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.sdk_client import LOGIN_MESSAGE, SdkAgentClient

    stub = StubSdkClient(receive_error=ProcessError("Command failed", exit_code=137))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()
    client.sdk_options.stderr("hook output: see the docs about /login for details")
    client.sdk_options.stderr("Killed")

    with pytest.raises(AgentError) as error:
        async for _ in client.messages():
            pass

    assert error.value.message_pt != LOGIN_MESSAGE
    assert "encerrou inesperadamente" in error.value.message_pt


@pytest.mark.anyio
async def test_stray_login_mention_on_connect_is_not_expired_login(tmp_path):
    from claude_agent_sdk import ProcessError
    from test_agent_sdk_client import StubSdkClient, make_options

    from claudio_maestro.agent.base import AgentError
    from claudio_maestro.agent.sdk_client import LOGIN_MESSAGE, SdkAgentClient

    stub = StubSdkClient(connect_error=ProcessError("Command failed", exit_code=1))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    client.sdk_options.stderr("Run /login to sign in with your claude.ai account")

    with pytest.raises(AgentError) as error:
        await client.connect()

    assert error.value.message_pt != LOGIN_MESSAGE


def test_cli_not_found_message_is_readable():
    from claude_agent_sdk import CLINotFoundError

    from claudio_maestro.agent.sdk_client import to_agent_error

    assert to_agent_error(CLINotFoundError()).message_pt == (
        "O comando `claude` não foi encontrado nesta máquina."
    )


# Review fixes --------------------------------------------------------------------


@pytest.mark.anyio
async def test_stop_task_failure_is_logged_and_others_still_stop(make_env, env_cleanup, caplog):
    from claudio_maestro.agent.base import AgentError

    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.builder._subagents["extra"] = {**session.builder._subagents["toolu_agent"],
                                           "task_id": "task-2", "status": "running"}
    calls: list[str] = []

    async def stop_task(task_id):
        calls.append(task_id)
        if task_id == "task-1":
            raise AgentError("já terminou")

    client.stop_task = stop_task
    with caplog.at_level(logging.ERROR):
        await session.interrupt()

    assert calls == ["task-1", "task-2"]
    assert session.client is client and session.error is None
    assert "task-1" in caplog.text


@pytest.mark.anyio
async def test_close_project_waits_for_sessions_in_parallel_under_one_deadline(
    make_env, env_cleanup, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.sessions.PROJECT_CLOSE_WAIT", 0.3)
    factory = SlowConnectFactory()
    env = make_env(factory=factory)
    env_cleanup.append(env.manager)
    sessions = [env.new_session() for _ in range(3)]
    sends = [asyncio.create_task(s.send("oi")) for s in sessions]
    await wait_until(lambda: len(factory.clients) == 3)

    started = time.monotonic()
    await env.manager.close_project(env.project.id)
    elapsed = time.monotonic() - started

    assert 0.25 <= elapsed < 0.6  # one deadline, not 0.3 s per session
    assert env.manager.active_ids() == set()
    factory.gate.set()
    await asyncio.wait(sends, timeout=WAIT)
    assert all(c.closed for c in factory.clients)
