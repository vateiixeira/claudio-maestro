"""Sessions of an agent (specialist): the extras reach the agent options and the
permission callback uses the agent's policy. Uses the scripted fake agent."""

import asyncio
import json
import logging
import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from claude_agent_sdk import PermissionResultAllow, ToolPermissionContext
from test_sessions import Env, by_session, fake_history, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, init_message, text_turn
from claudio_maestro.sessions import (
    InvalidDecisionError,
    SessionExtras,
    SessionManager,
)
from claudio_maestro.specialists import store

SETTINGS = '{"permissions": {"ask": ["Bash(git push:*)"]}}'


class Setup:
    """Stub `session_setup`: records the records it saw and the tool calls `decide` got."""

    def __init__(self, decision: Any = "ask", setup_error: Exception | None = None) -> None:
        self.decision = decision
        self.setup_error = setup_error
        self.records: list[Any] = []
        self.decided: list[tuple[str, dict[str, Any]]] = []
        self.server = object()

    async def decide(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self.decided.append((tool_name, tool_input))
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision

    def __call__(self, record: Any) -> SessionExtras:
        self.records.append(record)
        if self.setup_error is not None:
            raise self.setup_error
        return SessionExtras(
            system_prompt_append="Você é o revisor.",
            add_dirs=[Path("/opt/outra-pasta")],
            env={"MAESTRO_X": "1"},
            mcp_servers={"maestro": self.server},
            settings=SETTINGS,
            decide=self.decide,
        )


@pytest.fixture
def make_env(tmp_path: Path):
    def build(setup: Setup | None, script=None) -> Env:
        factory = FakeAgentFactory(script=script)
        env = Env(tmp_path, factory)
        env.manager = SessionManager(
            env.db_path, env.recorder, agent_factory=factory,
            history_exists=fake_history(factory), session_setup=setup,
        )
        return env

    return build


@pytest.fixture
async def env_cleanup():
    managers: list[SessionManager] = []
    yield managers
    for manager in managers:
        await manager.shutdown()


def add_specialist(env: Env) -> int:
    with closing(db.connect(env.db_path)) as conn, db.transaction(conn):
        return store.create_specialist(
            conn, slug="revisor", name="Revisor", project_id=env.project.id, now=1
        ).id


def specialist_session(env: Env, **kwargs: Any):
    record = env.manager.create_session(env.project, specialist_id=add_specialist(env), **kwargs)
    return env.manager.get(record.session_id)


def ask_context() -> ToolPermissionContext:
    return ToolPermissionContext(tool_use_id="toolu_1")


# Options -------------------------------------------------------------------


@pytest.mark.anyio
async def test_session_setup_reaches_agent_options(make_env, env_cleanup):
    setup = Setup()
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(setup, script)
    env_cleanup.append(env.manager)
    session = specialist_session(env)
    ids.append(session.session_id)

    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    [options] = [c.options for c in env.factory.clients]
    assert options.system_prompt_append == "Você é o revisor."
    assert options.add_dirs == [Path("/opt/outra-pasta")]
    assert options.env == {"MAESTRO_X": "1"}
    assert options.mcp_servers == {"maestro": setup.server}
    assert options.settings == SETTINGS
    assert [r.session_id for r in setup.records] == [session.session_id]
    assert setup.records[0].specialist_id == session.record.specialist_id


def child():
    """What the agentd lists for a process it kept."""
    return SimpleNamespace(id="child-1", pid=os.getpid(), ack=0, init=None)


@pytest.mark.anyio
async def test_setup_runs_again_and_extras_reach_the_options_when_the_session_reattaches(
    make_env, env_cleanup
):
    setup = Setup()
    env = make_env(setup)
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    assert await session.reattach(child()) is True

    [options] = [c.options for c in env.factory.clients]
    assert options.attach is not None and options.attach.agentd_id == "child-1"
    assert options.resume is True
    assert options.system_prompt_append == "Você é o revisor."
    assert options.mcp_servers == {"maestro": setup.server}
    assert options.settings == SETTINGS
    assert len(setup.records) == 1


@pytest.mark.anyio
async def test_session_without_specialist_gets_todays_defaults(make_env, env_cleanup):
    setup = Setup()
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(setup, script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    [options] = [c.options for c in env.factory.clients]
    assert options.system_prompt_append is None
    assert options.add_dirs == [] and options.env == {}
    assert options.mcp_servers is None and options.settings is None
    assert setup.records == []


@pytest.mark.anyio
async def test_manager_without_setup_builds_plain_options(make_env, env_cleanup):
    env = make_env(None)
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    client = session._new_client(resume=False)

    assert client.options.system_prompt_append is None
    assert client.options.settings is None


# Permissions ---------------------------------------------------------------


async def connected_specialist_session(make_env, env_cleanup, setup: Setup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(setup, script)
    env_cleanup.append(env.manager)
    session = specialist_session(env)
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    return env, session, env.factory.clients[0].options.can_use_tool


@pytest.mark.anyio
async def test_specialist_session_allow_does_not_create_prompt(make_env, env_cleanup):
    setup = Setup("allow")
    env, session, can_use_tool = await connected_specialist_session(make_env, env_cleanup, setup)

    result = await can_use_tool("Read", {"file_path": "a.txt"}, ask_context())

    assert isinstance(result, PermissionResultAllow)
    assert setup.decided == [("Read", {"file_path": "a.txt"})]
    assert session.prompts == {}
    assert env.recorder.of(session.session_id, "prompt.request") == []


@pytest.mark.anyio
async def test_specialist_session_ask_creates_pending_prompt(make_env, env_cleanup):
    setup = Setup("ask")
    env, session, can_use_tool = await connected_specialist_session(make_env, env_cleanup, setup)

    task = asyncio.ensure_future(
        can_use_tool("Bash", {"command": "git push origin main"}, ask_context())
    )
    await wait_until(lambda: len(session.prompts) == 1)

    [request] = env.recorder.of(session.session_id, "prompt.request")
    [prompt] = session.prompts.values()
    assert prompt.tool_name == "Bash"
    assert request["data"]["tool_name"] == "Bash"
    assert not task.done()

    session.resolve_prompt(prompt.prompt_id, "allow_once")
    assert isinstance(await task, PermissionResultAllow)


@pytest.mark.anyio
async def test_failing_decide_falls_back_to_asking(make_env, env_cleanup):
    setup = Setup(RuntimeError("quebrou"))
    env, session, can_use_tool = await connected_specialist_session(make_env, env_cleanup, setup)

    task = asyncio.ensure_future(can_use_tool("Bash", {"command": "ls"}, ask_context()))
    await wait_until(lambda: len(session.prompts) == 1)

    assert len(env.recorder.of(session.session_id, "prompt.request")) == 1
    task.cancel()


@pytest.mark.anyio
async def test_session_without_extras_always_asks(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(Setup("allow"), script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    task = asyncio.ensure_future(
        env.factory.clients[0].options.can_use_tool("Read", {"file_path": "a"}, ask_context())
    )
    await wait_until(lambda: len(session.prompts) == 1)
    task.cancel()


# Creation ------------------------------------------------------------------


def save_preferences(env: Env, **preferences: str) -> None:
    with closing(db.connect(env.db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES ('preferences', ?)",
            (json.dumps(preferences),),
        )


@pytest.mark.anyio
async def test_create_session_for_specialist_forces_default_mode(make_env, env_cleanup):
    env = make_env(None)
    env_cleanup.append(env.manager)
    save_preferences(
        env, new_session_mode="bypassPermissions", new_session_model="opus",
        new_session_effort="low",
    )
    specialist_id = add_specialist(env)

    record = env.manager.create_session(
        env.project, specialist_id=specialist_id, model="haiku", effort="high"
    )

    assert record.permission_mode == "default"
    assert (record.model, record.effort) == ("haiku", "high")
    assert record.specialist_id == specialist_id
    with closing(db.connect(env.db_path)) as conn:
        row = conn.execute(
            "SELECT specialist_id, permission_mode, model, effort FROM sessions"
            " WHERE session_id = ?", (record.session_id,),
        ).fetchone()
    assert tuple(row) == (specialist_id, "default", "haiku", "high")


@pytest.mark.anyio
async def test_create_session_for_specialist_keeps_preferences_without_overrides(
    make_env, env_cleanup
):
    env = make_env(None)
    env_cleanup.append(env.manager)
    save_preferences(env, new_session_mode="bypassPermissions", new_session_model="opus")

    record = env.manager.create_session(env.project, specialist_id=add_specialist(env))

    assert record.permission_mode == "default"
    assert record.model == "opus"


@pytest.mark.anyio
async def test_create_session_without_specialist_keeps_the_preferred_mode(make_env, env_cleanup):
    env = make_env(None)
    env_cleanup.append(env.manager)
    save_preferences(env, new_session_mode="bypassPermissions")

    record = env.manager.create_session(env.project)

    assert record.permission_mode == "bypassPermissions"
    assert record.specialist_id is None


# Always the default permission mode -------------------------------------------


async def set_saved_mode(session, mode: str) -> None:
    session.save(permission_mode=mode)


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits", "plan", "auto", "dontAsk"])
async def test_update_refuses_other_modes_for_a_specialist_session(make_env, env_cleanup, mode):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    with pytest.raises(InvalidDecisionError) as info:
        await env.manager.update(
            session.session_id, permission_mode=mode, confirm_bypass=True
        )

    assert "agente" in str(info.value)
    assert session.record.permission_mode == "default"


@pytest.mark.anyio
async def test_set_options_refuses_other_modes_for_a_specialist_session(make_env, env_cleanup):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    with pytest.raises(InvalidDecisionError):
        await session.set_options(permission_mode="bypassPermissions")

    assert session.record.permission_mode == "default"
    assert await session.set_options(permission_mode="default") is False


@pytest.mark.anyio
async def test_update_still_changes_the_mode_of_an_ordinary_session(make_env, env_cleanup):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = env.new_session()

    summary = await env.manager.update(session.session_id, permission_mode="acceptEdits")

    assert summary["permission_mode"] == "acceptEdits"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["fresh", "resume", "attach"])
async def test_specialist_client_always_starts_in_default_mode_without_bypass(
    make_env, env_cleanup, kind
):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = specialist_session(env)
    # Whatever got into the record (an old row, a bug), the client never gets it.
    session.save(permission_mode="bypassPermissions")
    attach = SimpleNamespace(agentd_id="c", from_pos=0, init_response=None)

    client = session._new_client(
        resume=kind != "fresh", attach=attach if kind == "attach" else None
    )

    assert client.options.permission_mode == "default"
    assert client.options.allow_bypass is False


@pytest.mark.anyio
async def test_ordinary_client_keeps_the_saved_mode_and_bypass_switch(make_env, env_cleanup):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(permission_mode="bypassPermissions")

    client = session._new_client(resume=False)

    assert client.options.permission_mode == "bypassPermissions"
    assert client.options.allow_bypass is True


async def push_init(env, session, mode: str) -> None:
    env.factory.clients[0].push([init_message(session.session_id, permission_mode=mode)])
    await wait_until(
        lambda: session.builder.init is not None and session.builder.init.permission_mode == mode
    )


@pytest.mark.anyio
async def test_init_cannot_move_a_specialist_session_out_of_default(make_env, env_cleanup):
    env, session, _ = await connected_specialist_session(make_env, env_cleanup, Setup())

    await push_init(env, session, "bypassPermissions")

    assert session.record.permission_mode == "default"


@pytest.mark.anyio
async def test_init_may_put_a_specialist_session_in_plan_mode(make_env, env_cleanup):
    env, session, _ = await connected_specialist_session(make_env, env_cleanup, Setup())

    await push_init(env, session, "plan")

    assert session.record.permission_mode == "plan"


@pytest.mark.anyio
async def test_init_still_sets_the_mode_of_an_ordinary_session(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(Setup(), script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    await push_init(env, session, "acceptEdits")

    assert session.record.permission_mode == "acceptEdits"


# Failures of the setup --------------------------------------------------------

SECRET = "SEGREDO-DO-SECRETS-ENV"
FIXED_TEXT = "Não foi possível preparar o agente desta sessão."


@pytest.mark.anyio
async def test_setup_failure_on_connect_shows_a_fixed_text(make_env, env_cleanup, caplog):
    setup = Setup(setup_error=RuntimeError(f"linha inválida: {SECRET}"))
    env = make_env(setup)
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    with caplog.at_level(logging.ERROR):
        await session.send("olá")
        await wait_until(lambda: session.error is not None)

    assert session.error == FIXED_TEXT
    shown = json.dumps(env.recorder.of(session.session_id), default=str, ensure_ascii=False)
    assert FIXED_TEXT in shown and SECRET not in shown
    assert SECRET in caplog.text  # the full error goes to the log only
    assert env.factory.clients == []


@pytest.mark.anyio
async def test_setup_failure_on_reattach_fails_the_session_with_a_fixed_text(
    make_env, env_cleanup, caplog
):
    setup = Setup(setup_error=RuntimeError(f"linha inválida: {SECRET}"))
    env = make_env(setup)
    env_cleanup.append(env.manager)
    session = specialist_session(env)

    with caplog.at_level(logging.ERROR):
        assert await session.reattach(child()) is False

    assert session.error == FIXED_TEXT
    assert session.client is None
    shown = json.dumps(env.recorder.of(session.session_id), default=str, ensure_ascii=False)
    assert FIXED_TEXT in shown and SECRET not in shown
    assert SECRET in caplog.text


# Creation: validation ---------------------------------------------------------


@pytest.mark.anyio
async def test_create_session_validates_model_and_effort(make_env, env_cleanup):
    env = make_env(None)
    env_cleanup.append(env.manager)
    specialist_id = add_specialist(env)

    with pytest.raises(InvalidDecisionError):
        env.manager.create_session(env.project, specialist_id=specialist_id, model="ruim; rm -rf")
    with pytest.raises(InvalidDecisionError):
        env.manager.create_session(env.project, specialist_id=specialist_id, effort="enorme")


# Policy timeout ---------------------------------------------------------------


@pytest.mark.anyio
async def test_slow_decide_times_out_into_asking(make_env, env_cleanup, monkeypatch, caplog):
    monkeypatch.setattr("claudio_maestro.sessions.POLICY_TIMEOUT", 0.05)

    class Slow(Setup):
        async def decide(self, tool_name, tool_input):
            await asyncio.sleep(5)
            return "allow"

    env, session, can_use_tool = await connected_specialist_session(make_env, env_cleanup, Slow())

    with caplog.at_level(logging.WARNING):
        task = asyncio.ensure_future(can_use_tool("Bash", {"command": "ls"}, ask_context()))
        await wait_until(lambda: len(session.prompts) == 1)

    assert len(env.recorder.of(session.session_id, "prompt.request")) == 1
    assert "política" in caplog.text
    task.cancel()
