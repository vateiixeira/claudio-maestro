"""Hooks the agents feature needs from the sessions: a turn or a session that ends in
error, and the MCP servers an init reports."""

import logging
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import SystemMessage
from test_sessions import Recorder, fake_history, make_project, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    FailStep,
    FakeAgentFactory,
    init_message,
    result_message,
    text_turn,
)
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store

pytestmark = pytest.mark.anyio


class Hooks:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.inits: list[tuple[str, list[dict[str, str]]]] = []
        self.fail = False

    def on_turn_error(self, session_id: str, error: str) -> None:
        self.errors.append((session_id, error))
        if self.fail:
            raise RuntimeError("quebrou")

    def on_init(self, session_id: str, servers: list[dict[str, str]]) -> None:
        self.inits.append((session_id, servers))
        if self.fail:
            raise RuntimeError("quebrou")


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "app")
        self.hooks = Hooks()
        self.recorder = Recorder()
        self.turn: Any = lambda sid: text_turn(sid, "oi")
        self.factory = FakeAgentFactory(
            script=lambda content: self.turn(self.factory.clients[-1].options.session_id)
        )
        self.manager = SessionManager(
            self.db_path,
            self.recorder,
            agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            on_turn_error=self.hooks.on_turn_error,
            on_init=self.hooks.on_init,
        )

    def session(self, *, agent: bool):
        specialist_id = None
        if agent:
            with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
                specialist_id = store.create_specialist(
                    conn, slug="revisor", name="Revisor", project_id=self.project.id, now=1
                ).id
        record = self.manager.create_session(self.project, specialist_id=specialist_id)
        return self.manager.get(record.session_id)


@pytest.fixture
async def world(tmp_path: Path):
    built = World(tmp_path)
    yield built
    await built.manager.shutdown()


def init_with_servers(sid: str, servers: Any) -> SystemMessage:
    message = init_message(sid)
    message.data["mcp_servers"] = servers
    return message


async def run_turn(session) -> None:
    await session.send("olá")
    await wait_until(lambda: session.state in ("idle", "error"))


async def test_error_result_calls_on_turn_error_for_an_agent_session(world):
    world.turn = lambda sid: [
        init_message(sid),
        result_message(sid, subtype="error_during_execution", is_error=True, errors=["boom"]),
    ]
    session = world.session(agent=True)

    await run_turn(session)

    [(session_id, error)] = world.hooks.errors
    assert session_id == session.session_id
    assert error == "O turno terminou com erro. boom"


async def test_successful_turn_does_not_call_on_turn_error(world):
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.errors == []


async def test_interrupted_turn_is_not_an_error(world):
    world.turn = lambda sid: [
        init_message(sid),
        result_message(
            sid, subtype="error_during_execution", is_error=True,
            terminal_reason="aborted_streaming",
        ),
    ]
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.errors == []


async def test_error_result_of_an_ordinary_session_is_not_reported(world):
    world.turn = lambda sid: [
        init_message(sid),
        result_message(sid, subtype="error_during_execution", is_error=True),
    ]
    session = world.session(agent=False)

    await run_turn(session)

    assert world.hooks.errors == []


async def test_a_failed_session_calls_on_turn_error(world):
    world.turn = lambda sid: [init_message(sid), FailStep("O processo morreu.")]
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.errors == [(session.session_id, "O processo morreu.")]


async def test_a_failed_ordinary_session_is_not_reported(world):
    world.turn = lambda sid: [init_message(sid), FailStep("O processo morreu.")]
    session = world.session(agent=False)

    await run_turn(session)

    assert world.hooks.errors == []


async def test_a_failing_hook_does_not_break_the_session(world, caplog):
    world.hooks.fail = True
    world.turn = lambda sid: [
        init_message(sid),
        result_message(sid, subtype="error_during_execution", is_error=True),
    ]
    session = world.session(agent=True)

    with caplog.at_level(logging.ERROR):
        await run_turn(session)

    assert session.state == "idle"
    assert len(world.hooks.errors) == 1
    assert "quebrou" in caplog.text


async def test_init_reports_the_mcp_servers_of_an_agent_session(world):
    servers = [
        {"name": "maestro", "status": "connected"},
        {"name": "sentry", "status": "failed", "scope": "user"},
        "ruim",
        {"status": "connected"},
    ]
    world.turn = lambda sid: [init_with_servers(sid, servers), *text_turn(sid, "oi")[1:]]
    session = world.session(agent=True)

    await run_turn(session)

    expected = [
        {"name": "maestro", "status": "connected"},
        {"name": "sentry", "status": "failed"},
    ]
    assert world.hooks.inits == [(session.session_id, expected)]
    assert session.builder.init.mcp_servers == expected


async def test_init_without_mcp_servers_reports_an_empty_list(world):
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.inits == [(session.session_id, [])]
    assert session.builder.init.mcp_servers == []


async def test_init_of_an_ordinary_session_is_not_reported(world):
    world.turn = lambda sid: [
        init_with_servers(sid, [{"name": "x", "status": "connected"}]),
        *text_turn(sid, "oi")[1:],
    ]
    session = world.session(agent=False)

    await run_turn(session)

    assert world.hooks.inits == []
    assert session.builder.init.mcp_servers == [{"name": "x", "status": "connected"}]
