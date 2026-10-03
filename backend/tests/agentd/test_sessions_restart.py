"""Sessions across a backend restart: the real SessionManager and SdkAgentClient over a
real agentd, with the fake CLI standing in for `claude`."""

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest
from test_sessions import Recorder, make_project

from claudio_maestro import db
from claudio_maestro.agent.agentd_client import AgentdClient
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.agent.sdk_client import SdkAgentClient
from claudio_maestro.agent.spawn import SpawnSpec
from claudio_maestro.sessions import INTERRUPTED_TEXT, SessionManager

FAKE_CLI = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]
WAIT = 10  # seconds


class RestartEnv:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.recorder = Recorder()
        self.agentd = AgentdClient(tmp_path / "data", idle_exit=5, orphan_timeout=5)
        self.managers: list[SessionManager] = []
        probe = SessionManager(self.db_path, self.recorder)
        self.session_id = probe.create_session(self.project).session_id

    def manager(self, **kw) -> SessionManager:
        manager = SessionManager(
            self.db_path,
            self.recorder,
            agentd=self.agentd,
            read_transcript=lambda sid, d: None,
            history_exists=lambda sid, d: False,
            **kw,
        )
        self.managers.append(manager)
        return manager

    async def _wait(self, predicate) -> None:
        deadline = time.monotonic() + WAIT
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError("timed out waiting for the condition")
            await asyncio.sleep(0.02)

    async def wait_state(self, manager: SessionManager, state: str) -> None:
        await self._wait(lambda: manager.get(self.session_id).state == state)

    async def wait_items(self, manager: SessionManager, predicate) -> None:
        await self._wait(lambda: predicate(manager.get(self.session_id).builder.items))

    async def _wait_no_children(self) -> None:
        # The agentd drops a killed child once its process is gone.
        deadline = time.monotonic() + WAIT
        while await self.agentd.list():
            if time.monotonic() > deadline:
                raise AssertionError("the agentd still holds children")
            await asyncio.sleep(0.05)

    async def _wait_no_children_but(self, keep: str) -> None:
        deadline = time.monotonic() + WAIT
        while [c.id for c in await self.agentd.list()] != [keep]:
            if time.monotonic() > deadline:
                raise AssertionError("the agentd still holds the other children")
            await asyncio.sleep(0.05)

    def turn_open(self, session_id: str) -> int:
        with closing(db.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT turn_open FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row["turn_open"]

    def fake_spec(self) -> SpawnSpec:
        return SpawnSpec(cmd=FAKE_CLI, cwd=str(self.project.path), env=dict(os.environ))


@pytest.fixture
async def env(tmp_path, monkeypatch):
    # The fake CLI stands in for `claude`: build_cli_spawn's command is replaced.
    monkeypatch.setattr(
        "claudio_maestro.agent.sdk_client.build_cli_spawn",
        lambda sdk_options: SpawnSpec(cmd=FAKE_CLI, cwd=str(sdk_options.cwd), env=dict(os.environ)),
    )
    # conftest blocks the real factory for every test; this one runs the real SdkAgentClient
    # (its `claude` is the fake CLI above), so put it back.
    monkeypatch.setattr(
        "claudio_maestro.sessions.default_agent_factory", lambda options: SdkAgentClient(options)
    )
    restart_env = RestartEnv(tmp_path)
    yield restart_env
    for manager in restart_env.managers:
        await manager.shutdown()
    for child in await restart_env.agentd.list():
        await restart_env.agentd.kill(child.id)
    await restart_env.agentd.aclose()


@pytest.mark.anyio
async def test_pending_permission_survives_restart(env):
    manager = env.manager()
    await manager.send(env.session_id, "ask")
    await env.wait_state(manager, "awaiting_decision")
    await manager.shutdown()  # backend goes away
    assert [c.session_id for c in await env.agentd.list()] == [env.session_id]

    manager2 = env.manager()  # backend comes back
    await manager2.reattach_all()
    session = manager2.get(env.session_id)
    assert session.state == "awaiting_decision"
    prompt_id = next(iter(session.prompts))
    session.resolve_prompt(prompt_id, "allow_once")
    await env.wait_state(manager2, "idle")
    texts = [i.text for i in session.builder.items if hasattr(i, "text")]
    assert "permitido" in texts
    assert env.turn_open(env.session_id) == 0


@pytest.mark.anyio
async def test_streaming_turn_continues_without_duplicates(env):
    manager = env.manager()
    await manager.send(env.session_id, "stream:30")
    await env.wait_items(manager, lambda items: any("w5" in getattr(i, "text", "") for i in items))
    await manager.shutdown()
    manager2 = env.manager()
    await manager2.reattach_all()
    session = manager2.get(env.session_id)
    assert session.state == "running"
    await env.wait_state(manager2, "idle")
    texts = [i.text for i in session.builder.items if type(i).__name__ == "TextItem"]
    assert texts == [" ".join(f"w{i}" for i in range(30)) + " "]


@pytest.mark.anyio
async def test_reattach_twice(env):
    manager = env.manager()
    await manager.send(env.session_id, "stream:40")
    await env.wait_items(manager, lambda items: any("w3" in getattr(i, "text", "") for i in items))
    await manager.shutdown()
    manager2 = env.manager()
    await manager2.reattach_all()
    await env.wait_items(manager2, lambda items: any("w15" in getattr(i, "text", "") for i in items))
    await manager2.shutdown()
    manager3 = env.manager()
    await manager3.reattach_all()
    await env.wait_state(manager3, "idle")
    texts = [i.text for i in manager3.get(env.session_id).builder.items
             if type(i).__name__ == "TextItem"]
    assert texts == [" ".join(f"w{i}" for i in range(40)) + " "]


@pytest.mark.anyio
async def test_reattach_with_a_running_agentd_and_no_children_does_not_raise(env):
    # The first restart after installing the agentd: it runs, but keeps no session yet.
    await env.agentd.ensure_running()
    assert await env.agentd.list() == []
    manager = env.manager()
    await manager.reattach_all()


@pytest.mark.anyio
async def test_unknown_child_is_killed(env):
    await env.agentd.spawn("no-such-session", env.fake_spec())
    manager = env.manager()
    await manager.reattach_all()
    await env._wait_no_children()


@pytest.mark.anyio
async def test_exited_child_is_cleaned_and_session_marked_interrupted(env):
    manager = env.manager()
    await manager.send(env.session_id, "ask")
    await env.wait_state(manager, "awaiting_decision")
    await manager.shutdown()
    child = (await env.agentd.list())[0]
    os.kill(child.pid, signal.SIGKILL)
    await asyncio.sleep(0.3)
    manager2 = env.manager()
    await manager2.reattach_all()
    await env._wait_no_children()
    snapshot = await manager2.open(env.session_id)
    assert snapshot["interrupted"] is True


@pytest.mark.anyio
async def test_attach_only_mode_starts_new_sessions_directly(env, monkeypatch):
    seen = []

    def factory(options):
        seen.append(options)
        return FakeAgentFactory()(options)

    # SessionManager reads default_agent_factory when it is built: patch first.
    monkeypatch.setattr("claudio_maestro.sessions.default_agent_factory", factory)
    manager = env.manager(agentd_new_sessions=False)
    await manager.send(env.session_id, "oi")
    assert seen and seen[0].agentd is None


async def hang(*_args, **_kwargs):
    await asyncio.sleep(60)


async def start_streaming_and_detach(env, text: str = "stream:30") -> SessionManager:
    manager = env.manager()
    await manager.send(env.session_id, text)
    await env.wait_items(manager, lambda items: any("w3" in getattr(i, "text", "") for i in items))
    await manager.shutdown()
    assert len(await env.agentd.list()) == 1
    return manager


@pytest.mark.anyio
async def test_reattach_timeout_kills_the_child_and_a_later_send_starts_one_process(
    env, monkeypatch
):
    await start_streaming_and_detach(env)
    manager2 = env.manager()
    with monkeypatch.context() as patch:
        patch.setattr("claudio_maestro.sessions.REATTACH_TIMEOUT", 0.3)
        patch.setattr(env.agentd, "subscribe", hang)  # the attach never completes
        await manager2.reattach_all()
    await env._wait_no_children()
    session = manager2.get(env.session_id)
    assert session.client is None
    assert not session.busy
    assert session.state != "connecting"
    # The half-attached session is usable: one new process, not a second one next to the old.
    await manager2.send(env.session_id, "oi")
    await env.wait_state(manager2, "idle")
    assert len(await env.agentd.list()) == 1


@pytest.mark.anyio
async def test_reattach_unexpected_error_kills_the_child_and_fails_the_session(env, monkeypatch):
    await start_streaming_and_detach(env)
    manager2 = env.manager()

    async def boom(self):
        raise RuntimeError("boom")

    with monkeypatch.context() as patch:
        patch.setattr(SdkAgentClient, "connect", boom)
        await manager2.reattach_all()
    await env._wait_no_children()
    session = manager2.get(env.session_id)
    assert session.client is None
    assert session.state == "error"
    assert "boom" in (session.error or "")


@pytest.mark.anyio
async def test_total_reattach_timeout_does_not_raise_out_of_reattach_all(env, monkeypatch):
    await start_streaming_and_detach(env)
    manager2 = env.manager()
    with monkeypatch.context() as patch:
        patch.setattr("claudio_maestro.sessions.REATTACH_TOTAL_TIMEOUT", 0.3)
        patch.setattr(env.agentd, "subscribe", hang)
        await manager2.reattach_all()  # must return, not raise TimeoutError
    await env._wait_no_children()
    session = manager2.get(env.session_id)
    assert session.client is None
    assert not session.busy


@pytest.mark.anyio
async def test_turn_finished_while_the_backend_was_down_shows_its_result_once(env):
    await start_streaming_and_detach(env, "stream:20")
    await asyncio.sleep(1.5)  # the fake CLI finishes the turn with nobody attached
    ends: list[int] = []
    manager2 = env.manager(on_turn_end=ends.append)
    await manager2.reattach_all()
    await env.wait_state(manager2, "idle")
    session = manager2.get(env.session_id)
    texts = [i.text for i in session.builder.items if type(i).__name__ == "TextItem"]
    assert texts == [" ".join(f"w{i}" for i in range(20)) + " "]
    assert len(ends) == 1
    assert env.turn_open(env.session_id) == 0


@pytest.mark.anyio
async def test_shutdown_while_connecting_leaves_no_untracked_child(env):
    manager = env.manager()
    session = manager.get(env.session_id)
    sending = asyncio.create_task(manager.send(env.session_id, "oi"))
    await env._wait(lambda: session.state == "connecting")
    await manager.shutdown()
    await sending
    assert session.client is None
    # Whatever the connect started is either gone or the one child still tracked.
    assert len(await env.agentd.list()) <= 1


@pytest.mark.anyio
async def test_answered_permission_is_not_asked_again_after_restart(env):
    manager = env.manager()
    await manager.send(env.session_id, "askslow")
    await env.wait_state(manager, "awaiting_decision")
    session = manager.get(env.session_id)
    session.resolve_prompt(next(iter(session.prompts)), "allow_once")
    await env.wait_state(manager, "running")
    await asyncio.sleep(0.5)  # the answer reached the CLI, which is now "running the tool"
    await manager.shutdown()
    manager2 = env.manager()
    await manager2.reattach_all()
    session2 = manager2.get(env.session_id)
    assert session2.state == "running"
    assert not session2.prompts
    await env.wait_state(manager2, "idle")
    assert not session2.prompts
    texts = [i.text for i in session2.builder.items if type(i).__name__ == "TextItem"]
    assert texts == ["permitido"]
    assert env.turn_open(env.session_id) == 0


def user_line(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text},
                       "parent_tool_use_id": None, "session_id": "s"}) + "\n"


def notices(session) -> list[str]:
    return [i.text for i in session.builder.items if type(i).__name__ == "NoticeItem"]


@pytest.mark.anyio
async def test_child_that_exited_while_the_backend_was_down_shows_why(env):
    await start_streaming_and_detach(env)
    child = (await env.agentd.list())[0]
    # The CLI dies with a message on stderr while nobody is attached.
    await env.agentd.write(child.id, user_line("exit:3"))
    for _ in range(100):
        if (await env.agentd.list())[0].exit_code is not None:
            break
        await asyncio.sleep(0.05)
    manager2 = env.manager()
    await manager2.reattach_all()
    await env._wait_no_children()
    await manager2.open(env.session_id)
    texts = notices(manager2.get(env.session_id))
    assert INTERRUPTED_TEXT in texts
    assert "O agente encerrou enquanto o app reiniciava: fake failure" in texts


@pytest.mark.anyio
async def test_two_children_of_one_session_keep_only_the_newest(env):
    older = await env.agentd.spawn(env.session_id, env.fake_spec())
    newer = await env.agentd.spawn(env.session_id, env.fake_spec())
    queue = await env.agentd.subscribe(newer, 0)
    await env.agentd.write(newer, user_line("oi"))
    while json.loads((await asyncio.wait_for(queue.get(), 5)).get("line", "{}")).get(
            "type") != "result":
        pass
    manager = env.manager()
    await manager.reattach_all()
    session = manager.get(env.session_id)
    assert session.client is not None
    await env._wait_no_children_but(newer)
    assert [c.id for c in await env.agentd.list()] == [newer]
    assert older not in [c.id for c in await env.agentd.list()]


@pytest.mark.anyio
async def test_reattach_refuses_a_session_that_already_has_a_client(env):
    await start_streaming_and_detach(env)
    manager2 = env.manager()
    await manager2.reattach_all()
    session = manager2.get(env.session_id)
    client = session.client
    assert client is not None
    child = (await env.agentd.list())[0]
    assert await session.reattach(child) is False
    assert session.client is client


@pytest.mark.anyio
async def test_error_reading_the_session_row_kills_the_child_instead_of_orphaning_it(
    env, monkeypatch
):
    await start_streaming_and_detach(env)
    manager2 = env.manager()

    def boom(session_id):
        raise RuntimeError("db is down")

    monkeypatch.setattr(manager2, "_read_row", boom)
    await manager2.reattach_all()
    await env._wait_no_children()
