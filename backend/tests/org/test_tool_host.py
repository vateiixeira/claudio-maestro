"""The task tools of `OrgService` (`ToolHost`): names to agents, the revision retry, the run of the
session, reading, decisions and CI. The tools themselves are in `test_tools.py`. Scripted fake
agent only; nothing here starts a turn."""

import json
from contextlib import closing
from types import SimpleNamespace

import pytest

from claudio_maestro import db, projects
from claudio_maestro.org import store
from claudio_maestro.org.decisions import DecisionService
from claudio_maestro.org.service import UNAVAILABLE_TOOL
from claudio_maestro.org.tasks import TaskAuthorityError
from claudio_maestro.org.tools import build_tools

from .test_service import fresh, world  # noqa: F401
from .test_task_runs import board, get_task, new_task  # noqa: F401

pytestmark = pytest.mark.anyio


class Team:
    """A boss with two workers and a reviewer, each with a session of its own."""

    def __init__(self, board) -> None:  # noqa: F811
        self.board = board
        self.cto = board.add_agent("cto", name="CTO")
        self.dev = board.add_agent("dev", name="Desenvolvedora", reports_to=self.cto)
        self.qa = board.add_agent("qa", name="Qualidade", reports_to=self.cto)
        self.sessions = {
            agent: board.manager.create_session(board.project, agent_id=agent).session_id
            for agent in (self.cto, self.dev, self.qa)
        }

    def host(self):
        return self.board.service

    def tools(self, agent: int):
        tools = build_tools(self.board.service, agent_id=agent, session_id=self.sessions[agent])
        return {t.name: t.handler for t in tools}


@pytest.fixture
def team(board):  # noqa: F811
    return Team(board)


def text(result: dict) -> str:
    return result["content"][0]["text"]


def run_for(board, agent: int, session_id: str, task_id: int, outcome: str = "running") -> int:  # noqa: F811
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        return store.insert_run(
            conn, agent_id=agent, session_id=session_id, source="assignment", routine_id=None,
            scheduled_for=None, started_at=1, task_id=task_id, outcome=outcome,
        ).id


# Wiring ------------------------------------------------------------------------------------


async def test_tools_without_service_answer_with_portuguese_error(world):  # noqa: F811
    agent = world.add_agent()
    session = world.manager.create_session(world.project, agent_id=agent).session_id
    tools = {
        t.name: t.handler for t in build_tools(world.service, agent_id=agent, session_id=session)
    }

    calls = {
        "tarefas_listar": {},
        "tarefa_ler": {"id": 1},
        "tarefa_criar": {"titulo": "T", "descricao": "D"},
        "tarefa_atualizar": {"id": 1, "comentario": "x"},
        "tarefa_comentar": {"id": 1, "texto": "x"},
        "decidir": {"pergunta": "P"},
        "verificar_ci": {"url": "https://github.com/o/r/actions/runs/1"},
    }
    for name, args in calls.items():
        result = await tools[name](args)
        assert result["is_error"] is True, name
        assert text(result) == UNAVAILABLE_TOOL, name
    assert UNAVAILABLE_TOOL == "Esta ferramenta não está disponível agora."


# Creating ----------------------------------------------------------------------------------


async def test_tarefa_criar_resolves_assignee_by_name_and_slug(team, board):  # noqa: F811
    for ref in ("Desenvolvedora", "desenvolvedora", "dev", "DEV"):
        result = await team.tools(team.cto)["tarefa_criar"](
            {"titulo": f"Para {ref}", "descricao": "Fazer.", "responsavel": ref}
        )
        assert not result.get("is_error"), text(result)
        task = json.loads(text(result))["tarefa"]
        assert task["responsavel"] == "Desenvolvedora"
        assert get_task(board, task["id"]).assignee_agent_id == team.dev


async def test_tarefa_criar_sets_reviewer_priority_and_parent(team, board):  # noqa: F811
    parent = await new_task(board, team.dev)

    result = await team.tools(team.cto)["tarefa_criar"](
        {
            "titulo": "Filha", "descricao": "Fazer.", "responsavel": "dev", "revisor": "Qualidade",
            "prioridade": "high", "pai": parent.id,
        }
    )

    created = get_task(board, json.loads(text(result))["tarefa"]["id"])
    assert (created.assignee_agent_id, created.reviewer_agent_id) == (team.dev, team.qa)
    assert (created.priority, created.parent_task_id) == ("high", parent.id)
    assert (created.created_by, created.created_by_agent_id) == ("agent", team.cto)


async def test_tarefa_criar_ambiguous_name_asks_for_slug(team, board):  # noqa: F811
    other = board.add_agent("dev2", name="Desenvolvedora", reports_to=team.cto)

    result = await team.tools(team.cto)["tarefa_criar"](
        {"titulo": "T", "descricao": "D", "responsavel": "Desenvolvedora"}
    )

    assert result["is_error"] is True
    assert "dev" in text(result) and "dev2" in text(result)
    assert "identificador" in text(result)
    # The slug settles it.
    ok = await team.tools(team.cto)["tarefa_criar"](
        {"titulo": "T", "descricao": "D", "responsavel": "dev2"}
    )
    assert get_task(board, json.loads(text(ok))["tarefa"]["id"]).assignee_agent_id == other


async def test_tarefa_criar_unknown_or_foreign_agent_is_refused(team, board):  # noqa: F811
    foreign_project = board.add_project("estrangeiro")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.create_agent(
            conn, slug="fora", name="Fora", project_id=projects_id(foreign_project, board),
            reports_to=None, now=1,
        )
    board.files.create("fora", "---\nname: Fora\n---\nx\n")

    for ref in ("ninguem", "fora", "Fora"):
        result = await team.tools(team.cto)["tarefa_criar"](
            {"titulo": "T", "descricao": "D", "responsavel": ref}
        )
        assert result["is_error"] is True, ref
        assert "organizacao" in text(result), ref
    with closing(db.connect(board.db_path)) as conn:
        assert store.list_tasks(conn) == []


def projects_id(path, board) -> int:  # noqa: F811
    with closing(db.connect(board.db_path)) as conn:
        return conn.execute(
            "SELECT id FROM projects WHERE name = 'outro' AND path = ?", (str(path),)
        ).fetchone()["id"]


async def test_tarefa_criar_by_worker_cannot_assign_to_peer(team, board):  # noqa: F811
    result = await team.tools(team.dev)["tarefa_criar"](
        {"titulo": "T", "descricao": "D", "responsavel": "qa"}
    )

    assert result["is_error"] is True
    assert "subordinado" in text(result)
    with closing(db.connect(board.db_path)) as conn:
        assert store.list_tasks(conn) == []


# Updating ----------------------------------------------------------------------------------


async def test_tarefa_atualizar_changes_status_with_comment_and_run(team, board):  # noqa: F811
    task = await new_task(board, team.dev)
    run_id = run_for(board, team.dev, team.sessions[team.dev], task.id)

    result = await team.tools(team.dev)["tarefa_atualizar"](
        {"id": task.id, "status": "in_progress", "comentario": "Peguei."}
    )

    assert not result.get("is_error"), text(result)
    assert json.loads(text(result))["tarefa"]["status"] == "in_progress"
    assert get_task(board, task.id).status == "in_progress"
    with closing(db.connect(board.db_path)) as conn:
        agent_comments = [
            c for c in store.list_comments(conn, task.id) if c.author_kind == "agent"
        ]
        assert [(c.text, c.run_id) for c in agent_comments] == [("Peguei.", run_id)]
        assert store.get_run(conn, run_id).commented is True


async def test_run_of_another_session_or_ended_run_is_not_the_comment_run(team, board):  # noqa: F811
    task = await new_task(board, team.dev)
    run_for(board, team.dev, team.sessions[team.dev], task.id, outcome="concluded")

    await team.tools(team.dev)["tarefa_comentar"]({"id": task.id, "texto": "Depois."})
    # The run of the other agent's session never counts for this one.
    run_for(board, team.cto, team.sessions[team.cto], task.id)
    await team.tools(team.dev)["tarefa_comentar"]({"id": task.id, "texto": "De novo."})

    with closing(db.connect(board.db_path)) as conn:
        runs = [c.run_id for c in store.list_comments(conn, task.id) if c.author_kind == "agent"]
    assert runs == [None, None]


async def test_tarefa_atualizar_authority_error_changes_nothing(team, board):  # noqa: F811
    task = await new_task(board, team.dev)

    result = await team.tools(team.qa)["tarefa_atualizar"](
        {"id": task.id, "status": "cancelled", "comentario": "Não precisa."}
    )

    assert result["is_error"] is True
    assert text(result) == str(TaskAuthorityError())
    assert get_task(board, task.id).status == task.status
    with closing(db.connect(board.db_path)) as conn:
        assert [c for c in store.list_comments(conn, task.id) if c.author_kind == "agent"] == []


async def test_tarefa_atualizar_reassigns_to_subordinate_by_name(team, board):  # noqa: F811
    task = await new_task(board, team.dev)

    result = await team.tools(team.cto)["tarefa_atualizar"](
        {"id": task.id, "responsavel": "Qualidade", "comentario": "Passa para a QA."}
    )

    assert not result.get("is_error"), text(result)
    assert get_task(board, task.id).assignee_agent_id == team.qa


async def test_task_update_retries_once_on_stale_revision(team, board):  # noqa: F811
    task = await new_task(board, team.dev)
    real = board.tasks.update_task
    calls: list[int] = []

    async def racing(task_id, **kwargs):
        calls.append(kwargs["expected_revision"])
        if len(calls) == 1:  # somebody changes the task between the read and the update
            with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
                store.update_task(
                    conn, task_id, expected_revision=kwargs["expected_revision"], now=1,
                    priority="low",
                )
        return await real(task_id, **kwargs)

    board.tasks.update_task = racing  # type: ignore[method-assign]

    result = await team.tools(team.dev)["tarefa_atualizar"](
        {"id": task.id, "status": "in_progress", "comentario": "Peguei."}
    )

    assert not result.get("is_error"), text(result)
    assert calls == [task.revision, task.revision + 1]
    assert get_task(board, task.id).status == "in_progress"
    assert get_task(board, task.id).priority == "low"


async def test_task_update_gives_up_after_two_stale_revisions(team, board):  # noqa: F811
    task = await new_task(board, team.dev)

    async def always_stale(task_id, **kwargs):
        raise store.TaskRevisionError()

    board.tasks.update_task = always_stale  # type: ignore[method-assign]

    result = await team.tools(team.dev)["tarefa_atualizar"](
        {"id": task.id, "status": "in_progress", "comentario": "Peguei."}
    )

    assert result["is_error"] is True
    assert "tarefa_ler" in text(result)
    assert get_task(board, task.id).status == task.status


async def test_tarefa_comentar_leaves_comment_and_wakes(team, board):  # noqa: F811
    task = await new_task(board, team.dev)

    result = await team.tools(team.cto)["tarefa_comentar"]({"id": task.id, "texto": "Capricha."})

    assert not result.get("is_error"), text(result)
    with closing(db.connect(board.db_path)) as conn:
        assert [(c.author_kind, c.author_agent_id, c.text) for c in store.list_comments(conn, task.id)
                if c.author_kind == "agent"] == [("agent", team.cto, "Capricha.")]


async def test_tarefa_comentar_outside_authority_is_refused(team, board):  # noqa: F811
    task = await new_task(board, team.dev)

    result = await team.tools(team.qa)["tarefa_comentar"]({"id": task.id, "texto": "Oi"})

    assert result["is_error"] is True
    assert text(result) == str(TaskAuthorityError())


# Reading -----------------------------------------------------------------------------------


async def test_tarefas_listar_mine_means_assignee_or_reviewer_and_open(team, board):  # noqa: F811
    mine = await new_task(board, team.dev, "Minha")
    reviewing = await new_task(board, team.cto, "Revisão", reviewer_agent_id=team.dev)
    await new_task(board, team.qa, "Da QA")
    done = await new_task(board, team.dev, "Pronta")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.update_task(conn, done.id, expected_revision=done.revision, now=1, status="done")

    result = await team.tools(team.dev)["tarefas_listar"]({})

    ids = [t["id"] for t in json.loads(text(result))["tarefas"]]
    assert ids == [mine.id, reviewing.id]

    everyone = await team.tools(team.dev)["tarefas_listar"]({"minhas": False})
    assert len(json.loads(text(everyone))["tarefas"]) == 3
    closed = await team.tools(team.dev)["tarefas_listar"]({"status": ["done"]})
    assert [t["id"] for t in json.loads(text(closed))["tarefas"]] == [done.id]


async def test_tarefas_listar_stays_in_the_project(team, board):  # noqa: F811
    other_path = board.add_project("estrangeiro")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        pid = projects_id(other_path, board)
        store.create_task(
            conn, project_id=pid, title="De outro projeto", description="", assignee_agent_id=None,
            reviewer_agent_id=None, parent_task_id=None, priority="normal", created_by="human",
            created_by_agent_id=None, routine_id=None, now=1,
        )

    result = await team.tools(team.cto)["tarefas_listar"]({"minhas": False})

    assert json.loads(text(result)) == {"tarefas": []}


async def test_tarefa_ler_returns_latest_comments_and_authority(team, board):  # noqa: F811
    task = await new_task(board, team.dev)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        for index in range(60):
            store.add_comment(
                conn, task_id=task.id, author_kind="human", author_agent_id=None, run_id=None,
                text=f"c{index}", now=index,
            )

    mine = json.loads(text(await team.tools(team.dev)["tarefa_ler"]({"id": task.id})))["tarefa"]
    other = json.loads(text(await team.tools(team.qa)["tarefa_ler"]({"id": task.id})))["tarefa"]

    assert mine["pode_alterar"] is True
    assert other["pode_alterar"] is False
    assert mine["responsavel"] == "Desenvolvedora"
    assert mine["criador"] == "Pessoa"
    comments = mine["comentarios"]
    assert len(comments) == 50
    assert comments[-1]["texto"] == "c59"
    assert comments[-1]["autor"] == "Pessoa"
    assert comments[0]["id"] < comments[-1]["id"]


async def test_tarefa_ler_other_project_or_unknown_is_not_found(team, board):  # noqa: F811
    other_path = board.add_project("estrangeiro")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        foreign = store.create_task(
            conn, project_id=projects_id(other_path, board), title="Segredo", description="",
            assignee_agent_id=None, reviewer_agent_id=None, parent_task_id=None,
            priority="normal", created_by="human", created_by_agent_id=None, routine_id=None,
            now=1,
        )

    for task_id in (foreign.id, 9999):
        result = await team.tools(team.cto)["tarefa_ler"]({"id": task_id})
        assert result["is_error"] is True
        assert text(result) == "Tarefa não encontrada."


# Decisions and CI --------------------------------------------------------------------------


async def test_decidir_opens_decision_bound_to_task_of_active_run(team, board):  # noqa: F811
    board.service.decisions = DecisionService(
        board.db_path, org=board.service, tasks=board.tasks,
        publish=lambda type_, data: board.events.append((type_, data)), clock=lambda: board.now,
    )
    task = await new_task(board, team.dev)
    run_for(board, team.dev, team.sessions[team.dev], task.id)

    result = await team.tools(team.dev)["decidir"]({"pergunta": "Usar Redis?", "opcoes": ["sim", "não"]})

    assert not result.get("is_error"), text(result)
    with closing(db.connect(board.db_path)) as conn:
        [decision] = store.list_decisions(conn, task_id=task.id, pending_only=True)
    assert (decision.question, decision.options, decision.agent_id) == (
        "Usar Redis?", ["sim", "não"], team.dev,
    )
    # A second, different question while one is pending is a domain error, in Portuguese.
    again = await team.tools(team.dev)["decidir"]({"pergunta": "Outra coisa?"})
    assert again["is_error"] is True
    assert "pendente" in text(again)


async def test_verificar_ci_goes_to_ci_service_with_session_and_url(team, board):  # noqa: F811
    seen: list[tuple[str, str]] = []

    async def verify(session_id: str, *, run_url: str) -> dict:
        seen.append((session_id, run_url))
        return {
            "receipt": "ci-1", "conclusion": "success", "head_sha": "b" * 40, "run_url": run_url,
            "repository": "o/r", "jobs": [{"name": "backend", "conclusion": "success"}],
        }

    board.service.ci = SimpleNamespace(verify=verify)  # type: ignore[assignment]
    url = "https://github.com/o/r/actions/runs/9"

    result = await team.tools(team.dev)["verificar_ci"]({"url": url})

    assert seen == [(team.sessions[team.dev], url)]
    payload = json.loads(text(result))
    assert (payload["conclusao"], payload["recibo"]) == ("success", "ci-1")


async def test_verificar_ci_project_not_found_becomes_portuguese_domain_error(team, board):  # noqa: F811
    async def verify(session_id: str, *, run_url: str) -> dict:
        raise projects.ProjectNotFoundError("Projeto não encontrado.")

    board.service.ci = SimpleNamespace(verify=verify)  # type: ignore[assignment]

    result = await team.tools(team.dev)["verificar_ci"](
        {"url": "https://github.com/o/r/actions/runs/9"}
    )

    assert result["is_error"] is True
    assert text(result) == "Projeto não encontrado."
