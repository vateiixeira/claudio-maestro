"""What an agent session takes from `SessionExtras`: the permission mode and the blocked tools of
its definition reach the client options. Uses the scripted fake agent; no real SDK."""

import json
import logging
import os
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_sessions import Env, by_session, fake_history, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, init_message, text_turn
from claudio_maestro.org import store
from claudio_maestro.sessions import (
    AGENT_SETUP_FAILED_TEXT,
    SessionExtras,
    SessionManager,
)

pytestmark = pytest.mark.anyio

SECRET = "SEGREDO-DO-SECRETS-ENV"


class Setup:
    """Stub `session_setup`: hands out the same extras for every session of an agent."""

    def __init__(self, *, setup_error: Exception | None = None, **extras: Any) -> None:
        self.setup_error = setup_error
        self.extras = extras
        self.records: list[Any] = []

    async def decide(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        return "allow"

    def __call__(self, record: Any) -> SessionExtras:
        self.records.append(record)
        if self.setup_error is not None:
            raise self.setup_error
        return SessionExtras(
            system_prompt_append="Você é o revisor.",
            add_dirs=[Path("/opt/outra-pasta")],
            env={"TOKEN": "x"},
            mcp_servers={"maestro": object()},
            decide=self.decide,
            **self.extras,
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


def agent_session(env: Env):
    with closing(db.connect(env.db_path)) as conn, db.transaction(conn):
        agent_id = store.create_agent(
            conn, slug="revisor", name="Revisor", project_id=env.project.id,
            reports_to=None, now=1,
        ).id
    record = env.manager.create_session(env.project, agent_id=agent_id)
    return env.manager.get(record.session_id)


async def connected(make_env, env_cleanup, setup: Setup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(setup, script)
    env_cleanup.append(env.manager)
    session = agent_session(env)
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")
    return env, session


async def push_init(env, session, mode: str) -> None:
    env.factory.clients[0].push([init_message(session.session_id, permission_mode=mode)])
    await wait_until(
        lambda: session.builder.init is not None and session.builder.init.permission_mode == mode
    )


async def test_options_use_the_mode_and_blocked_tools_of_the_extras(make_env, env_cleanup):
    setup = Setup(permission_mode="bypassPermissions", disallowed_tools=["WebFetch"])
    env, session = await connected(make_env, env_cleanup, setup)

    [options] = [c.options for c in env.factory.clients]

    assert options.permission_mode == "bypassPermissions"
    assert options.allow_bypass is True
    assert options.disallowed_tools == ["WebFetch"]
    assert options.settings is None  # `settings` is optional now


@pytest.mark.parametrize("kind", ["fresh", "resume", "attach"])
async def test_client_starts_in_the_extras_mode_whatever_the_record_says(
    make_env, env_cleanup, kind
):
    env = make_env(Setup(permission_mode="acceptEdits", disallowed_tools=["Bash(rm*)"]))
    env_cleanup.append(env.manager)
    session = agent_session(env)
    session.save(permission_mode="plan")
    attach = SimpleNamespace(agentd_id="c", from_pos=0, init_response=None)

    client = session._new_client(
        resume=kind != "fresh", attach=attach if kind == "attach" else None
    )

    assert client.options.permission_mode == "acceptEdits"
    assert client.options.disallowed_tools == ["Bash(rm*)"]
    assert client.options.allow_bypass is False


@pytest.mark.parametrize(
    ("mode", "bypass"),
    [("default", False), ("acceptEdits", False), ("plan", False), ("bypassPermissions", True)],
)
async def test_process_may_bypass_only_when_the_definition_asks_for_it(
    make_env, env_cleanup, mode, bypass
):
    env = make_env(Setup(permission_mode=mode))
    env_cleanup.append(env.manager)
    session = agent_session(env)

    client = session._new_client(resume=False)

    assert client.options.permission_mode == mode
    assert client.options.allow_bypass is bypass


async def test_extras_default_to_the_default_mode_and_nothing_blocked(make_env, env_cleanup):
    env = make_env(Setup())
    env_cleanup.append(env.manager)
    session = agent_session(env)

    client = session._new_client(resume=False)

    assert client.options.permission_mode == "default"
    assert client.options.disallowed_tools == []


async def test_agent_session_without_extras_stays_in_default_without_bypass(
    make_env, env_cleanup
):
    env = make_env(None)
    env_cleanup.append(env.manager)
    session = agent_session(env)

    client = session._new_client(resume=False)

    assert client.options.permission_mode == "default"
    assert client.options.allow_bypass is False
    assert client.options.disallowed_tools == []


async def test_ordinary_session_is_not_changed(make_env, env_cleanup):
    env = make_env(Setup(permission_mode="bypassPermissions"))
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(permission_mode="acceptEdits")

    client = session._new_client(resume=False)

    assert client.options.permission_mode == "acceptEdits"
    assert client.options.allow_bypass is True
    assert client.options.disallowed_tools == []


async def test_init_records_the_mode_the_definition_asked_for(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, Setup(permission_mode="bypassPermissions")
    )

    await push_init(env, session, "bypassPermissions")

    assert session.record.permission_mode == "bypassPermissions"


async def test_init_cannot_move_the_session_to_a_mode_the_definition_did_not_ask(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup, Setup(permission_mode="acceptEdits"))

    await push_init(env, session, "bypassPermissions")

    assert session.record.permission_mode == "default"


async def test_setup_failure_shows_a_fixed_text_without_the_detail(
    make_env, env_cleanup, caplog
):
    setup = Setup(setup_error=RuntimeError(f"pasta extra inválida: /home/x/{SECRET}"))
    env = make_env(setup)
    env_cleanup.append(env.manager)
    session = agent_session(env)

    with caplog.at_level(logging.ERROR):
        await session.send("olá")
        await wait_until(lambda: session.error is not None)

    assert session.error == AGENT_SETUP_FAILED_TEXT
    assert AGENT_SETUP_FAILED_TEXT == "Não foi possível preparar a sessão do agente."
    shown = json.dumps(env.recorder.of(session.session_id), default=str, ensure_ascii=False)
    assert AGENT_SETUP_FAILED_TEXT in shown and SECRET not in shown
    assert SECRET in caplog.text  # the detail goes to the log only
    assert env.factory.clients == []


def child():
    return SimpleNamespace(id="child-1", pid=os.getpid(), ack=0, init=None)


async def test_setup_failure_on_reattach_fails_the_session_with_the_fixed_text(
    make_env, env_cleanup
):
    env = make_env(Setup(setup_error=RuntimeError(SECRET)))
    env_cleanup.append(env.manager)
    session = agent_session(env)

    assert await session.reattach(child()) is False

    assert session.error == AGENT_SETUP_FAILED_TEXT
    assert session.client is None
