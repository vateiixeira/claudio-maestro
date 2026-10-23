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
    tool_turn,
)
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store

pytestmark = pytest.mark.anyio


class Hooks:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []
        self.inits: list[tuple[str, list[dict[str, str]]]] = []
        self.fail = False
        self.prs: list[tuple[str, str]] = []
        self.prepared: list[tuple[str, str]] = []
        self.committed = 0
        self.prefix: str | None = None
        self.prepare_fails = False
        self.commit_fails = False

    def prepare_message(self, record: Any, text: str):
        self.prepared.append((record.session_id, text))
        if self.prepare_fails:
            raise RuntimeError("anuncio quebrou")

        def commit() -> None:
            self.committed += 1
            if self.commit_fails:
                raise RuntimeError("commit quebrou")

        if self.prefix is None:
            return text, commit
        return f"{self.prefix}\n\n{text}", commit

    def on_pr_created(self, session_id: str, url: str) -> None:
        self.prs.append((session_id, url))
        if self.fail:
            raise RuntimeError("quebrou")

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
            on_pr_created=self.hooks.on_pr_created,
            prepare_message=self.hooks.prepare_message,
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


# on_pr_created -----------------------------------------------------------------------

PR_URL = "https://github.com/angular-ecommerce/ecommerce/pull/9"


def bash_turn(sid: str, command: str, output: str, *, is_error: bool = False) -> list:
    return tool_turn(
        sid, tool_name="Bash", tool_input={"command": command},
        result_content=output, is_error=is_error,
    )


async def test_pr_url_captured_from_gh_pr_create_result(world):
    world.turn = lambda sid: bash_turn(
        sid, "cd w && gh pr create --base develop --title x --body y", f"{PR_URL}\n"
    )
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.prs == [(session.session_id, PR_URL)]


async def test_pr_url_is_the_first_one_in_a_list_result(world):
    world.turn = lambda sid: tool_turn(
        sid, tool_name="Bash", tool_input={"command": "gh pr create --fill"},
        result_content=[
            {"type": "text", "text": f"Creating pull request\n{PR_URL}\n"},
            {"type": "text", "text": "https://github.com/a/b/pull/1"},
        ],
    )
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.prs == [(session.session_id, PR_URL)]


async def test_pr_url_ignored_on_error_result(world):
    world.turn = lambda sid: bash_turn(sid, "gh pr create --fill", PR_URL, is_error=True)
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.prs == []


async def test_other_commands_ignored(world):
    world.turn = lambda sid: bash_turn(sid, "gh pr view 9", PR_URL)
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.prs == []


async def test_result_without_a_pr_url_is_ignored(world):
    world.turn = lambda sid: bash_turn(sid, "gh pr create --fill", "falhou sem url")
    session = world.session(agent=True)

    await run_turn(session)

    assert world.hooks.prs == []


async def test_pr_of_an_ordinary_session_is_not_reported(world):
    world.turn = lambda sid: bash_turn(sid, "gh pr create --fill", PR_URL)
    session = world.session(agent=False)

    await run_turn(session)

    assert world.hooks.prs == []


async def test_on_pr_created_failure_does_not_break_the_session(world, caplog):
    world.hooks.fail = True
    world.turn = lambda sid: bash_turn(sid, "gh pr create --fill", PR_URL)
    session = world.session(agent=True)

    with caplog.at_level(logging.ERROR):
        await run_turn(session)

    assert session.state == "idle"
    assert world.hooks.prs == [(session.session_id, PR_URL)]
    assert "PR" in caplog.text


# prepare_message ---------------------------------------------------------------------

ANNOUNCEMENTS = "<maestro-anuncios>\n[23/10 10:00] Execução das 09:00 concluída: ok (sessão x)\n</maestro-anuncios>"


def user_items(session) -> list[Any]:
    return [item for item in session.builder.items if getattr(item, "type", None) == "user"]


async def test_send_records_prepared_text(world):
    world.hooks.prefix = ANNOUNCEMENTS
    session = world.session(agent=True)

    await run_turn(session)

    [(_, original)] = world.hooks.prepared
    assert original == "olá"
    [user] = user_items(session)
    assert user.text == f"{ANNOUNCEMENTS}\n\nolá"
    assert world.factory.clients[-1].sent[0] == f"{ANNOUNCEMENTS}\n\nolá"
    assert world.hooks.committed == 1
    # The title still comes from what the person wrote.
    assert session.record.title == "olá"


async def test_send_commits_only_after_the_message_is_recorded(world):
    world.hooks.prefix = ANNOUNCEMENTS
    session = world.session(agent=True)
    seen: list[int] = []
    original = world.hooks.prepare_message

    def prepare(record, text):
        result, commit = original(record, text)

        def checked() -> None:
            seen.append(len(user_items(session)))
            commit()

        return result, checked

    session._prepare_message = prepare

    await run_turn(session)

    assert seen == [1]


async def test_send_of_an_ordinary_session_does_not_prepare(world):
    session = world.session(agent=False)

    await run_turn(session)

    assert world.hooks.prepared == []


async def test_a_failing_prepare_sends_the_original_text(world, caplog):
    world.hooks.prepare_fails = True
    session = world.session(agent=True)

    with caplog.at_level(logging.ERROR):
        await run_turn(session)

    assert world.factory.clients[-1].sent[0] == "olá"
    assert user_items(session)[0].text == "olá"
    assert world.hooks.committed == 0
    assert "anuncio quebrou" in caplog.text


async def test_a_failing_commit_does_not_lose_the_message(world, caplog):
    world.hooks.prefix = ANNOUNCEMENTS
    world.hooks.commit_fails = True
    session = world.session(agent=True)

    with caplog.at_level(logging.ERROR):
        await run_turn(session)

    assert world.factory.clients[-1].sent[0].startswith("<maestro-anuncios>")
    assert "commit quebrou" in caplog.text
