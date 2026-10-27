"""OrgService, part A: the session of an agent (prompt, folders, secrets, MCP, permission
mode), the main conversation, the announcements and the PRs. Scripted fake agent only."""

import asyncio
import json
import logging
import shutil
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from test_sessions import Recorder, fake_history, make_project, wait_until

from claudio_maestro import db, projects
from claudio_maestro.agent.fake import (
    FakeAgentFactory,
    PermissionStep,
    init_message,
    text_turn,
)
from claudio_maestro.org import store
from claudio_maestro.org.files import MEMORY_MAX_CHARS, AgentFiles
from claudio_maestro.org.service import (
    PROJECT_MISSING,
    PROJECT_UNAVAILABLE,
    AddDirOutsideProjectsError,
    OrgService,
)
from claudio_maestro.sessions import (
    AGENT_SETUP_FAILED_TEXT,
    ProjectUnavailableError,
    SessionManager,
)

pytestmark = pytest.mark.anyio

NOW = 1_700_000_000
SECRET = "SEGREDO-DO-SECRETS-ENV"


def definition(name: str = "Revisor", body: str = "Você revisa o código.", **fields: Any) -> str:
    lines = [f"name: {name}"]
    for key, value in fields.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return "---\n" + "\n".join(lines) + f"\n---\n{body}\n"


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.now = NOW
        self.recorder = Recorder()
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.files = AgentFiles(tmp_path / "agents")
        self.factory = FakeAgentFactory(
            script=lambda content: text_turn(self.factory.clients[-1].options.session_id, "feito")
        )
        self.manager = SessionManager(
            self.db_path,
            self.recorder,
            agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            session_setup=lambda record: self.service.session_setup(record),
            on_pr_created=lambda sid, url: self.service.on_pr_created(sid, url),
            prepare_message=lambda record, text: self.service.prepare_message(record, text),
        )
        self.source = self.manager.create_session(self.project).session_id
        self.service = OrgService(
            self.db_path,
            sessions=self.manager,
            files=self.files,
            publish=lambda type_, data: self.events.append((type_, data)),
            clock=lambda: self.now,
        )

    def add_project(self, folder: str, name: str = "outro") -> Path:
        path = self.tmp_path / "home" / folder
        project = make_project(self.db_path, path)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project.id))
        return path

    def add_agent(
        self, slug: str = "revisor", text: str | None = None, reports_to: int | None = None,
        **fields: Any,
    ) -> int:
        text = text or definition(**fields)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            agent = store.create_agent(
                conn, slug=slug, name=slug.title(), project_id=self.project.id,
                reports_to=reports_to, now=1,
            )
        self.files.create(slug, text)
        return agent.id

    def agent(self, agent_id: int) -> store.Agent:
        with closing(db.connect(self.db_path)) as conn:
            return store.get_agent(conn, agent_id)

    def session_of(self, agent_id: int, *, main: bool = False):
        if main:
            raise AssertionError("use ensure_main")
        record = self.manager.create_session(self.project, agent_id=agent_id)
        return self.manager.get(record.session_id)

    async def send(self, session_id: str, text: str = "olá") -> None:
        await self.manager.send(session_id, text)
        await wait_until(lambda: self.manager.get(session_id).state == "idle")

    def record(self, session_id: str):
        return self.manager.find_record(session_id)

    def published(self, type_: str) -> list[dict[str, Any]]:
        return [data for t, data in self.events if t == type_]


@pytest.fixture
async def world(tmp_path: Path):
    built = World(tmp_path)
    yield built
    await built.manager.shutdown()


# The session of an agent ---------------------------------------------------------


async def test_session_extras_use_definition_permission_mode_and_disallowed_tools(world):
    agent = world.add_agent(permissionMode="bypassPermissions", disallowedTools=["WebFetch"])
    session = world.session_of(agent)

    await world.send(session.session_id)

    [options] = [c.options for c in world.factory.clients]
    assert options.permission_mode == "bypassPermissions"
    assert options.disallowed_tools == ["WebFetch"]
    assert options.allow_bypass is True


async def test_default_definition_means_bypass_permissions(world):
    session = world.session_of(world.add_agent())

    await world.send(session.session_id)

    assert world.factory.clients[0].options.permission_mode == "bypassPermissions"


async def test_definition_mode_default_is_kept(world):
    session = world.session_of(world.add_agent(permissionMode="default"))

    await world.send(session.session_id)

    assert world.factory.clients[0].options.permission_mode == "default"


async def test_session_extras_add_agent_folder_and_valid_add_dirs(world):
    other = world.add_project("outro")
    (other / "lib").mkdir()
    agent = world.add_agent(addDirs=[str(other / "lib"), "../outro"])
    session = world.session_of(agent)

    await world.send(session.session_id)

    [options] = [c.options for c in world.factory.clients]
    assert options.add_dirs == [world.files.folder("revisor"), other / "lib", other.resolve()]
    assert options.cwd == Path(world.project.path)


async def test_add_dir_that_does_not_exist_inside_a_project_is_left_out(world):
    other = world.add_project("outro")
    agent = world.add_agent(addDirs=[str(other / "sumiu")])
    session = world.session_of(agent)

    await world.send(session.session_id)

    assert world.factory.clients[0].options.add_dirs == [world.files.folder("revisor")]


@pytest.mark.parametrize("kind", ["absolute", "dotdot", "symlink", "sibling-prefix"])
async def test_session_setup_refuses_add_dir_outside_projects(world, caplog, kind):
    outside = world.tmp_path / "home" / "fora-secreta"
    outside.mkdir(parents=True)
    project = Path(world.project.path)
    entry = {
        "absolute": str(outside),
        "dotdot": f"{project}/../fora-secreta",
        "symlink": str(project / "atalho"),
        "sibling-prefix": f"{project}-irmao",
    }[kind]
    if kind == "symlink":
        (project / "atalho").symlink_to(outside)
    if kind == "sibling-prefix":
        Path(entry).mkdir()
    agent = world.add_agent(addDirs=[entry])
    session = world.session_of(agent)

    with pytest.raises(AddDirOutsideProjectsError):
        world.service.session_setup(session.record)
    with caplog.at_level(logging.ERROR):
        await world.manager.send(session.session_id, "olá")
        await wait_until(lambda: session.error is not None)

    assert session.error == AGENT_SETUP_FAILED_TEXT
    shown = json.dumps(world.recorder.of(session.session_id), default=str, ensure_ascii=False)
    assert "fora-secreta" not in shown and "irmao" not in shown
    assert world.factory.clients == []


async def test_prompt_has_body_and_memory_but_no_secret(world):
    agent = world.add_agent(body="Você revisa PRs do app com cuidado.")
    world.files.write_memory("revisor", "Sempre rodar o linter antes.")
    world.files.write_secrets("revisor", {"TOKEN": SECRET})
    session = world.session_of(agent)

    await world.send(session.session_id)

    [options] = [c.options for c in world.factory.clients]
    assert "Você revisa PRs do app com cuidado." in options.system_prompt_append
    assert "Sempre rodar o linter antes." in options.system_prompt_append
    assert str(world.files.folder("revisor") / "memoria.md") in options.system_prompt_append
    assert SECRET not in options.system_prompt_append
    assert options.env["TOKEN"] == SECRET
    assert SECRET not in json.dumps(options.mcp_servers, default=str)


async def test_memory_past_the_limit_is_cut_with_a_note(world):
    agent = world.add_agent()
    big = "a" * (MEMORY_MAX_CHARS - 1) + "FIM-" + "b" * 500
    folder = world.files.folder("revisor")
    (folder / "memoria.md").write_text(big, encoding="utf-8")  # the agent edits it directly
    session = world.session_of(agent)

    extras = world.service.session_setup(session.record)

    assert "FIM-" not in extras.system_prompt_append
    assert "b" * 10 not in extras.system_prompt_append
    assert "a" * (MEMORY_MAX_CHARS - 1) in extras.system_prompt_append
    assert "passou do limite" in extras.system_prompt_append


async def test_prompt_names_the_boss_and_the_reports(world):
    boss = world.add_agent("cto", definition("CTO", description="Coordena a engenharia."))
    agent = world.add_agent(
        "revisor", definition("Revisor", description="Revisa PRs."), reports_to=boss
    )
    world.add_agent(
        "dev", definition("Dev", description="Escreve código."), reports_to=agent
    )
    session = world.session_of(agent)

    prompt = world.service.session_setup(session.record).system_prompt_append

    assert "- CTO: Coordena a engenharia." in prompt
    assert "- Dev: Escreve código." in prompt
    assert f"({world.project.path})" in prompt


async def test_session_setup_is_none_for_an_ordinary_session(world):
    assert world.service.session_setup(world.record(world.source)) is None


async def test_extras_wire_the_maestro_server_without_settings(world):
    session = world.session_of(world.add_agent())

    extras = world.service.session_setup(session.record)

    assert set(extras.mcp_servers) == {"maestro"}
    assert extras.settings is None and extras.deny_message is None


async def test_agent_that_no_longer_exists_fails_with_the_fixed_text(world, caplog):
    agent = world.add_agent()
    session = world.session_of(agent)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM agents WHERE id = ?", (agent,))

    with caplog.at_level(logging.ERROR):
        await world.manager.send(session.session_id, "olá")
        await wait_until(lambda: session.error is not None)

    assert session.error == AGENT_SETUP_FAILED_TEXT
    assert world.factory.clients == []


@pytest.mark.parametrize("break_how", ["missing", "invalid"])
async def test_unreadable_agent_md_fails_with_the_fixed_text(world, caplog, break_how):
    agent = world.add_agent()
    session = world.session_of(agent)
    path = world.files.folder("revisor") / "AGENT.md"
    if break_how == "missing":
        path.unlink()
    else:
        path.write_text("sem cabeçalho nenhum", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        await world.manager.send(session.session_id, "olá")
        await wait_until(lambda: session.error is not None)

    assert session.error == AGENT_SETUP_FAILED_TEXT
    shown = json.dumps(world.recorder.of(session.session_id), default=str, ensure_ascii=False)
    assert str(world.files.root) not in shown and "AGENT.md" not in shown


# The decider ---------------------------------------------------------------------


async def test_decider_allows_only_maestro_tools_denies_blocked_and_asks_for_the_rest(world):
    agent = world.add_agent(
        disallowedTools=["WebFetch", "Bash(git push --force*)", "mcp__perigo", "Edit(*.lock)"]
    )
    decide = world.service.session_setup(world.session_of(agent).record).decide

    # Only the Maestro tools are approved here; the CLI calls the decider when it already
    # decided to ask, so anything else is left to the person (the mode of the .md rules).
    assert await decide("mcp__maestro__avisar", {"texto": "x"}) == "allow"
    assert await decide("Bash", {"command": "git push origin main"}) == "ask"
    assert await decide("Read", {"file_path": "/etc/hosts"}) == "ask"
    assert await decide("mcp__outro__qualquer", {}) == "ask"
    assert await decide("AskUserQuestion", {"questions": []}) == "ask"
    assert await decide("ExitPlanMode", {"plan": "x"}) == "ask"
    assert await decide("WebFetch", {"url": "https://x.dev"}) == "deny"
    assert await decide("Bash", {"command": "git push --force origin main"}) == "deny"
    assert await decide("mcp__perigo__apagar", {}) == "deny"
    assert await decide("Edit", {"file_path": "uv.lock"}) == "deny"
    assert await decide("Edit", {"file_path": "app.py"}) == "ask"


async def test_decider_reaches_the_user_for_ask_through_the_session(world):
    agent = world.add_agent()
    session = world.session_of(agent)
    await world.send(session.session_id)
    can_use_tool = world.factory.clients[0].options.can_use_tool

    from claude_agent_sdk import PermissionResultAllow, ToolPermissionContext

    context = ToolPermissionContext(tool_use_id="toolu_1")
    allowed = await can_use_tool(
        "mcp__maestro__registro_consultar", {"chaves": []}, context
    )
    assert isinstance(allowed, PermissionResultAllow) and session.prompts == {}

    bash = asyncio.ensure_future(can_use_tool("Bash", {"command": "ls"}, context))
    await wait_until(lambda: len(session.prompts) == 1)
    assert [p.tool_name for p in session.prompts.values()] == ["Bash"]
    bash.cancel()
    await wait_until(lambda: session.prompts == {})

    task = asyncio.ensure_future(
        can_use_tool("AskUserQuestion", {"questions": [{"question": "Qual?", "options": []}]}, context)
    )
    await wait_until(lambda: len(session.prompts) == 1)
    assert [p.tool_name for p in session.prompts.values()] == ["AskUserQuestion"]
    task.cancel()


# Main conversation -----------------------------------------------------------------


async def test_ensure_main_creates_once_and_announcement_enters_next_turn(world):
    agent = world.add_agent(model="haiku", effort="low")

    first, second = await asyncio.gather(
        world.service.ensure_main(agent), world.service.ensure_main(agent)
    )

    assert first == second
    assert world.agent(agent).main_session_id == first
    record = world.record(first)
    assert (record.agent_id, record.title) == (agent, "Revisor · conversa")
    assert (record.model, record.effort) == ("haiku", "low")
    assert world.service.is_main(first) is True and world.service.is_conversation(first)
    assert {"id": agent} in world.published("agent.changed")
    assert await world.service.ensure_main(agent) == first

    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.add_announcement(
            conn, agent_id=agent, run_id=None, session_id=world.source,
            text="Execução das 09:00 concluída: A.", created_at=NOW,
        )
    stamp = f"{datetime.fromtimestamp(NOW):%d/%m %H:%M}"
    assert world.service.unseen(agent) == 1

    await world.send(first, "e então?")

    assert world.factory.clients[0].sent[0] == (
        "<maestro-anuncios>\n"
        f"[{stamp}] Execução das 09:00 concluída: A. (sessão {world.source})\n"
        "</maestro-anuncios>\n\ne então?"
    )
    with closing(db.connect(world.db_path)) as conn:
        assert store.pending_announcements(conn, agent) == []
    assert world.service.unseen(agent) == 0
    await world.send(first, "outra")
    assert world.factory.clients[0].sent[1] == "outra"


async def test_ensure_main_holds_the_lock_while_it_creates_the_conversation(world):
    """Nothing yields between reading the agent and saving the main session today, so two
    callers cannot be told apart by their result; what the lock guarantees is observable
    while the title is set (the only await): the agent's lock is held."""
    agent = world.add_agent()
    held: list[bool] = []
    real_update = world.manager.update

    async def update(session_id, **fields):
        lock = world.service._main_locks.get(agent)
        held.append(lock is not None and lock.locked())
        await asyncio.sleep(0)
        return await real_update(session_id, **fields)

    world.manager.update = update
    first, second = await asyncio.gather(
        world.service.ensure_main(agent), world.service.ensure_main(agent)
    )

    assert first == second
    assert held == [True]  # the second caller found the conversation and never created one


async def test_prepare_message_leaves_other_sessions_untouched(world):
    agent = world.add_agent()
    await world.service.ensure_main(agent)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.add_announcement(
            conn, agent_id=agent, run_id=None, session_id=None, text="Solta.", created_at=NOW
        )
    other = world.session_of(agent)

    text, commit = world.service.prepare_message(other.record, "oi")
    ordinary, _ = world.service.prepare_message(world.record(world.source), "oi")

    assert text == ordinary == "oi"
    commit()
    with closing(db.connect(world.db_path)) as conn:
        assert len(store.pending_announcements(conn, agent)) == 1


async def test_ensure_main_recreates_when_deleted_and_keeps_a_finished_one(world):
    agent = world.add_agent()
    first = await world.service.ensure_main(agent)
    await world.manager.update(first, finished=True)
    assert await world.service.ensure_main(agent) == first

    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (first,))
    second = await world.service.ensure_main(agent)

    assert second != first
    assert world.agent(agent).main_session_id == second
    assert world.service.is_main(first) is False


async def test_ensure_main_with_a_missing_or_unavailable_project(world, monkeypatch):
    agent = world.add_agent()
    shutil.rmtree(world.project.path)
    with pytest.raises(ProjectUnavailableError, match=PROJECT_UNAVAILABLE):
        await world.service.ensure_main(agent)

    def gone(conn, project_id):
        raise projects.ProjectNotFoundError("sumiu")

    monkeypatch.setattr(projects, "get_project", gone)
    with pytest.raises(ProjectUnavailableError, match=PROJECT_MISSING):
        await world.service.ensure_main(agent)
    assert world.agent(agent).main_session_id is None


async def test_main_prompt_has_the_main_section_and_no_concluir(world):
    agent = world.add_agent()
    main = await world.service.ensure_main(agent)
    isolated = world.session_of(agent)

    main_prompt = world.service.session_setup(world.record(main)).system_prompt_append
    other_prompt = world.service.session_setup(isolated.record).system_prompt_append

    assert "## Esta é a conversa principal" in main_prompt
    assert "`concluir`" not in main_prompt
    assert "## Esta é a conversa principal" not in other_prompt
    assert "`concluir`" in other_prompt


async def test_main_with_a_broken_definition_is_created_and_fails_on_send(world):
    agent = world.add_agent()
    (world.files.folder("revisor") / "AGENT.md").unlink()

    main = await world.service.ensure_main(agent)
    await world.manager.send(main, "oi")
    await wait_until(lambda: world.manager.get(main).error is not None)

    assert world.manager.get(main).error == AGENT_SETUP_FAILED_TEXT


async def test_unseen_counts_a_pending_question_of_the_main_conversation(world):
    agent = world.add_agent()
    world.factory.script = lambda content: [
        init_message(world.factory.clients[-1].options.session_id),
        PermissionStep("AskUserQuestion", {"questions": []}),
        *text_turn(world.factory.clients[-1].options.session_id, "ok")[1:],
    ]
    main = await world.service.ensure_main(agent)
    await world.manager.send(main, "oi")
    await wait_until(lambda: world.manager.get(main).state == "awaiting_decision")

    assert world.service.unseen(agent) == 1


# Conversations ---------------------------------------------------------------------


async def test_open_conversation_reuses_main_and_new_starts_another_chat(world):
    agent = world.add_agent()
    first = await world.service.open_conversation(agent)
    assert (await world.service.open_conversation(agent)).session_id == first.session_id
    other = await world.service.open_conversation(agent, new=True, title="Revisão do PR 7")

    assert other.session_id != first.session_id
    assert world.record(other.session_id).title == "Revisão do PR 7"
    assert world.service.is_conversation(other.session_id)
    assert world.service.is_main(other.session_id) is False
    assert {c["session_id"] for c in world.service.conversations(agent)} == {
        first.session_id, other.session_id,
    }
    assert world.factory.clients == []


async def test_cannot_open_a_session_of_another_agent(world):
    agent = world.add_agent()
    other = world.add_agent("outro")
    chat = await world.service.open_conversation(other)

    with pytest.raises(store.NotFoundError):
        await world.service.open_conversation(agent, session_id=chat.session_id)
    with pytest.raises(store.NotFoundError):
        await world.service.open_conversation(agent, session_id="desconhecida")


# PRs, registry and organization ----------------------------------------------------


async def test_pr_created_by_an_agent_session_is_remembered(world):
    agent = world.add_agent()
    session = world.session_of(agent)

    world.service.on_pr_created(session.session_id, "https://github.com/o/r/pull/7/?x=1")
    world.service.on_pr_created(world.source, "https://github.com/o/r/pull/8")  # not an agent

    assert world.service.is_agent_pr("https://github.com/o/r/pull/7") == agent
    assert world.service.is_agent_pr("https://github.com/o/r/pull/8") is None
    with closing(db.connect(world.db_path)) as conn:
        pr = store.get_pr(conn, "https://github.com/o/r/pull/7")
    assert pr is not None and pr.session_id == session.session_id
    assert {"id": agent} in world.published("agent.changed")


async def test_pr_linked_in_the_registry_belongs_to_the_agent(world):
    agent = world.add_agent()

    world.service.record(agent, "PR-9", "feito", "https://github.com/o/r/pull/9/", None)

    assert world.service.is_agent_pr("https://github.com/o/r/pull/9") == agent


async def test_lookup_and_record_go_through_the_registry(world):
    agent = world.add_agent()

    world.service.record(agent, "SENTRY-1", "feito", "https://x/1", "ok")

    [item] = world.service.lookup(agent, ["SENTRY-1", "SENTRY-2"])
    assert (item.key, item.status, item.link, item.note) == ("SENTRY-1", "feito", "https://x/1", "ok")
    assert (item.created_at, item.updated_at) == (NOW, NOW)


async def test_organization_lists_the_project_agents_with_the_boss_name(world):
    boss = world.add_agent("cto", definition("CTO", description="Coordena."))
    me = world.add_agent("dev", definition("Dev", description="Escreve."), reports_to=boss)
    off = world.add_agent("qa", definition("QA"), reports_to=boss)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_agent(conn, off, now=2, enabled=False)

    listed = world.service.organization(me)

    assert listed == [
        {"name": "CTO", "description": "Coordena.", "reports_to": None, "is_me": False, "enabled": True},
        {"name": "Dev", "description": "Escreve.", "reports_to": "CTO", "is_me": True, "enabled": True},
        {"name": "QA", "description": "", "reports_to": "CTO", "is_me": False, "enabled": False},
    ]


async def test_organization_survives_an_unreadable_definition(world):
    boss = world.add_agent("cto", definition("CTO"))
    me = world.add_agent("dev", reports_to=boss)
    (world.files.folder("cto") / "AGENT.md").unlink()

    names = [a["name"] for a in world.service.organization(me)]

    assert names == ["Cto", "Revisor"]  # the cached name stands in for the unreadable file
