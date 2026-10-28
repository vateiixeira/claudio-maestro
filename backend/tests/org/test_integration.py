"""The organization of agents wired into the app (`create_app`): the service, the scheduler,
the comment dispatcher, the file migration at startup, and the routing of a message typed in an
agent's conversation through the queue. The real SDK is never touched: the sessions of the
agents run on a fake client that can answer by calling `concluir`."""

import json
import logging
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import make_project

from claudio_maestro import db
from claudio_maestro.agent.base import AgentOptions
from claudio_maestro.agent.fake import FakeAgentClient, text_turn
from claudio_maestro.api.org import PROJECT_BUSY_TEXT
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings
from claudio_maestro.org import store
from claudio_maestro.org.ci import CiService
from claudio_maestro.org.comments import CommentDispatcher
from claudio_maestro.org.decisions import DecisionService
from claudio_maestro.org.files import AgentFiles
from claudio_maestro.org.scheduler import Scheduler
from claudio_maestro.org.service import OrgService
from claudio_maestro.org.tasks import TaskService
from claudio_maestro.org.tools import build_tools

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
SUMMARY = "Revisei os três PRs abertos."

SKILL = """---
name: Sentry
description: "Triagem dos erros do Sentry."
---
Você acompanha os erros do Sentry e abre tarefas para os importantes.
"""


class Factory:
    """Builds fake clients. A client of a run (not of the main conversation) answers its first
    turn by calling the `concluir` tool of the agent, the way a real agent would."""

    def __init__(self) -> None:
        self.clients: list[FakeAgentClient] = []
        self.app: Any = None
        self.summary: str | None = SUMMARY
        # What an agent does in the run of a task: `(agent_id, task_id, tools)`; when set, a
        # task run calls it instead of `concluir`.
        self.on_task_run: Callable[..., Any] | None = None

    def __call__(self, options: AgentOptions) -> FakeAgentClient:
        factory = self

        class Client(FakeAgentClient):
            async def _run_steps(self, steps):
                sid = self.options.session_id
                record = factory.app.state.sessions.find_record(sid)
                task_id = None
                if factory.on_task_run is not None and record.agent_id is not None:
                    with closing(db.connect(factory.app.state.settings.db_path)) as conn:
                        run = store.run_for_session(conn, sid)
                    task_id = run.task_id if run is not None else None
                if task_id is not None:
                    tools = build_tools(
                        factory.app.state.org, agent_id=record.agent_id, session_id=sid
                    )
                    await factory.on_task_run(
                        record.agent_id, task_id, {t.name: t.handler for t in tools}
                    )
                elif factory.summary and record.agent_id is not None and not factory.app.state.org.is_main(sid):
                    tools = build_tools(
                        factory.app.state.org, agent_id=record.agent_id, session_id=sid
                    )
                    conclude = next(t for t in tools if t.name == "concluir")
                    await conclude.handler({"resumo": factory.summary})
                await super()._run_steps(steps)

        client = Client(options, script=lambda content: text_turn(options.session_id, "feito"))
        self.clients.append(client)
        return client


def until(predicate: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Poll from the test thread while the app's loop runs in the client's portal."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    pytest.fail("a condição não aconteceu a tempo")


@pytest.fixture
def factory() -> Factory:
    return Factory()


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every event published on the hub, from the routes and from the service alike."""
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "claudio_maestro.events.EventHub.publish", lambda self, e: published.append(e)
    )
    return published


@pytest.fixture
def api(factory: Factory):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    factory.app = app
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as client:
        yield client


@pytest.fixture
def project(api: TestClient, home: Path) -> dict[str, Any]:
    return make_project(api, home)


def create_agent(api: TestClient, project_id: int, slug: str = "revisor") -> dict[str, Any]:
    response = api.post(
        "/api/agents", json={"name": "Revisor", "slug": slug, "project_id": project_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def runs_of(api: TestClient, agent_id: int) -> list[dict[str, Any]]:
    return api.get(f"/api/agents/{agent_id}/runs").json()


def sent_texts(factory: Factory, session_id: str) -> list[str]:
    return [
        text if isinstance(text, str) else json.dumps(text)
        for client in factory.clients
        if client.options.session_id == session_id
        for text in client.sent
    ]


# Wiring -----------------------------------------------------------------------------


def test_the_app_builds_the_organization_and_not_the_old_service(api: TestClient):
    state = api.app.state
    assert isinstance(state.org, OrgService)
    assert isinstance(state.agent_files, AgentFiles)
    assert state.agent_files.root == state.settings.data_dir / "agents"
    assert isinstance(state.scheduler, Scheduler)
    assert state.scheduler._service is state.org
    assert isinstance(state.comments, CommentDispatcher)
    assert state.comments._service is state.org
    assert not hasattr(state, "specialists")
    assert not hasattr(state, "specialist_files")


@pytest.mark.parametrize("on", [True, False])
def test_the_routine_tasks_follow_the_scheduler_setting(home: Path, data_dir: Path, on: bool):
    settings = Settings(home_dir=home, data_dir=data_dir, routines_scheduler=on)
    app = create_app(settings=settings, agent_factory=Factory())
    with TestClient(app, base_url=BACKEND_URL, headers={"x-maestro": "1"}):
        assert (app.state.scheduler_task is not None) is on
        assert (app.state.comments_task is not None) is on
        assert (app.state.comment_poll_task is not None) is on
        assert app.state.scheduler.enabled is on


@pytest.mark.parametrize("on", [True, False])
def test_the_queue_of_the_agents_follows_the_scheduler_setting(home: Path, data_dir: Path, on: bool):
    settings = Settings(home_dir=home, data_dir=data_dir, routines_scheduler=on)
    app = create_app(settings=settings, agent_factory=Factory())
    with TestClient(app, base_url=BACKEND_URL, headers={"x-maestro": "1"}):
        assert app.state.org.serve_automatic is on


def test_shutdown_stops_the_organization(home: Path, data_dir: Path):
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=Factory()
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"x-maestro": "1"}):
        assert app.state.org._stopping is False
    assert app.state.org._stopping is True


# A wakeup, end to end ------------------------------------------------------------------


def test_wake_runs_the_agent_and_the_summary_reaches_the_main_conversation(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    agent = create_agent(api, project["id"])

    response = api.post(f"/api/agents/{agent['id']}/wake", json={"text": "Revise os PRs."})
    assert response.status_code == 202, response.text

    run = until(lambda: next((r for r in runs_of(api, agent["id"]) if r["outcome"] == "concluded"), None))
    assert run["source"] == "manual"
    assert run["session_id"] is not None
    assert sent_texts(factory, run["session_id"]) == ["Revise os PRs."]
    announcements = api.get(f"/api/agents/{agent['id']}/announcements").json()
    assert len(announcements) == 1
    assert announcements[0]["text"].endswith(f"concluída: {SUMMARY}")
    assert api.get(f"/api/agents/{agent['id']}").json()["unseen"] == 1
    # The run's session is finished once its turn is over.
    until(lambda: api.get(f"/api/sessions/{run['session_id']}").json()["finished"])

    # The announcement is shown to the person on the next message to the main conversation.
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    sent = api.post(f"/api/sessions/{main}/messages", json={"text": "Como foi?"})
    assert sent.status_code == 202, sent.text
    texts = until(lambda: sent_texts(factory, main))
    assert SUMMARY in texts[0] and texts[0].endswith("Como foi?")
    assert api.get(f"/api/agents/{agent['id']}").json()["unseen"] == 0


# A message typed in the conversation of an agent ----------------------------------------


def test_a_message_in_the_main_conversation_goes_through_the_queue(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    agent = create_agent(api, project["id"])
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]

    response = api.post(f"/api/sessions/{main}/messages", json={"text": "Olá, agente."})

    assert response.status_code == 202, response.text
    assert response.json()["queued"] is True
    assert sent_texts(factory, main) == ["Olá, agente."]  # delivered before the answer
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        [wakeup] = store.pending_wakeups(conn, agent["id"]) or [None]
        rows = conn.execute(
            "SELECT source, state, run_id FROM wakeups WHERE agent_id = ?", (agent["id"],)
        ).fetchall()
    assert wakeup is None
    assert [tuple(row) for row in rows] == [("message", "taken", None)]
    assert runs_of(api, agent["id"]) == []  # a conversation has no run


def test_a_message_to_a_disabled_agent_is_refused_and_stays_pending(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    agent = create_agent(api, project["id"])
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    assert api.patch(f"/api/agents/{agent['id']}", json={"enabled": False}).status_code == 200

    response = api.post(f"/api/sessions/{main}/messages", json={"text": "Alguém aí?"})

    assert response.status_code == 409
    assert response.json()["detail"] == "O agente está desligado."
    assert sent_texts(factory, main) == []
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        pending = store.pending_wakeups(conn, agent["id"])
    assert [w.source for w in pending] == ["message"]


def test_an_empty_message_to_an_agent_is_refused(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    agent = create_agent(api, project["id"])
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]

    response = api.post(f"/api/sessions/{main}/messages", json={"text": "   "})

    assert response.status_code in (400, 422)
    assert sent_texts(factory, main) == []


def test_an_ordinary_session_does_not_touch_the_queue(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    session = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]

    response = api.post(f"/api/sessions/{session}/messages", json={"text": "Oi"})

    assert response.status_code == 202
    until(lambda: sent_texts(factory, session) == ["Oi"])
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wakeups").fetchone()[0] == 0


# The file migration at startup ----------------------------------------------------------


def seed_old_agent(settings: Settings) -> int:
    """An agent row as migration 31 leaves it, and the old folder `specialists/sentry`."""
    db.init_db(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn, db.transaction(conn):
        project_path = settings.home_dir / "app"
        project_path.mkdir(parents=True)
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'app', ?, '#fff', 0, 0)",
            (str(project_path),),
        )
        legacy = {"model": "sonnet", "effort": "high", "denied_tools": [], "extra_project_ids": []}
        agent_id = conn.execute(
            "INSERT INTO agents (slug, name, project_id, enabled, legacy_json, created_at, updated_at)"
            " VALUES ('sentry', 'Sentry', 1, 1, ?, 5, 5)",
            (json.dumps(legacy),),
        ).lastrowid
    folder = settings.data_dir / "specialists" / "sentry"
    folder.mkdir(parents=True, mode=0o700)
    (folder / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (folder / "aprendizados.md").write_text("- O alerta X é ruído.\n", encoding="utf-8")
    return agent_id


def test_startup_migrates_the_old_folders_and_logs_the_report(
    home: Path, data_dir: Path, caplog: pytest.LogCaptureFixture
):
    settings = Settings(home_dir=home, data_dir=data_dir)
    agent_id = seed_old_agent(settings)
    app = create_app(settings=settings, agent_factory=Factory())

    with caplog.at_level(logging.INFO, logger="claudio_maestro"):
        with TestClient(
            app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
        ) as client:
            listed = client.get("/api/agents").json()

    assert [(a["id"], a["slug"], a["description"]) for a in listed] == [
        (agent_id, "sentry", "Triagem dos erros do Sentry.")
    ]
    folder = data_dir / "agents" / "sentry"
    assert (folder / "AGENT.md").is_file()
    assert (folder / "memoria.md").read_text(encoding="utf-8") == "- O alerta X é ruído.\n"
    assert (data_dir / "specialists" / "sentry.migrado").is_dir()
    assert not (data_dir / "specialists" / "sentry").exists()
    [report] = list((data_dir / "agents").glob("migracao-*.md"))
    assert "sentry" in report.read_text(encoding="utf-8")
    assert any("migra" in record.getMessage().lower() for record in caplog.records)
    with closing(db.connect(settings.db_path)) as conn:
        assert store.get_agent(conn, agent_id).legacy is None


def test_a_second_startup_does_not_migrate_again(home: Path, data_dir: Path):
    settings = Settings(home_dir=home, data_dir=data_dir)
    seed_old_agent(settings)
    for _ in range(2):
        app = create_app(settings=settings, agent_factory=Factory())
        with TestClient(app, base_url=BACKEND_URL, headers={"x-maestro": "1"}):
            pass

    assert sorted(p.name for p in (data_dir / "specialists").iterdir()) == ["sentry.migrado"]
    assert len(list((data_dir / "agents").glob("migracao-*.md"))) == 1
    with closing(db.connect(settings.db_path)) as conn:
        assert [a.slug for a in store.list_agents(conn)] == ["sentry"]


def test_a_failing_file_migration_does_not_stop_the_app(
    home: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def explode(*args: Any, **kwargs: Any):
        raise RuntimeError("falha de teste")

    monkeypatch.setattr("claudio_maestro.app.migrate_files", explode)
    settings = Settings(home_dir=home, data_dir=data_dir)
    app = create_app(settings=settings, agent_factory=Factory())

    with caplog.at_level(logging.ERROR, logger="claudio_maestro"):
        with TestClient(
            app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
        ) as client:
            assert client.get("/api/agents").status_code == 200

    assert any("falha de teste" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


# The migration of the old work system at startup -----------------------------------------


def test_startup_migrates_the_old_work_after_the_folders(
    home: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    from claudio_maestro.org import migration

    order: list[str] = []
    real_files, real_work = migration.migrate_files, migration.migrate_work

    def files(*args: Any, **kwargs: Any):
        order.append("files")
        return real_files(*args, **kwargs)

    def work(data: Path, conn: Any, *, files: AgentFiles, **kwargs: Any):
        order.append("work")
        assert data == data_dir and files.root == data_dir / "agents"
        return real_work(data, conn, files=files, **kwargs)

    monkeypatch.setattr("claudio_maestro.app.migrate_files", files)
    monkeypatch.setattr("claudio_maestro.app.migrate_work", work)
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=Factory())

    with TestClient(app, base_url=BACKEND_URL, headers={"x-maestro": "1"}):
        assert order == ["files", "work"]


def test_a_failing_work_migration_does_not_stop_the_app(
    home: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def explode(*args: Any, **kwargs: Any):
        raise RuntimeError("falha do trabalho")

    monkeypatch.setattr("claudio_maestro.app.migrate_work", explode)
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=Factory())

    with caplog.at_level(logging.ERROR, logger="claudio_maestro"):
        with TestClient(
            app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
        ) as client:
            assert client.get("/api/agents").status_code == 200

    assert any("falha do trabalho" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)


# Tasks, decisions and CI wired into the app ---------------------------------------------


def test_the_app_wires_the_task_board_and_drops_the_old_work_system(api: TestClient):
    state = api.app.state
    assert isinstance(state.tasks, TaskService)
    assert isinstance(state.decisions, DecisionService)
    assert state.org.tasks is state.tasks
    assert state.org.decisions is state.decisions
    assert isinstance(state.org.ci, CiService)
    assert state.scheduler._tasks is state.tasks
    assert state.scheduler._decisions is state.decisions
    for gone in ("work", "work_prs", "work_pr_task"):
        assert not hasattr(state, gone)
    assert api.get("/api/work-items").status_code == 404
    assert api.get("/api/work/decisions").status_code == 404


def create_team(api: TestClient, project_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    cto = api.post(
        "/api/agents",
        json={"name": "CTO", "slug": "cto", "project_id": project_id, "kind": "cto"},
    )
    assert cto.status_code == 201, cto.text
    worker = api.post(
        "/api/agents",
        json={
            "name": "Trabalhador", "slug": "trabalhador", "project_id": project_id,
            "kind": "worker", "reports_to": cto.json()["id"],
        },
    )
    assert worker.status_code == 201, worker.text
    return cto.json(), worker.json()


def task_wakeups(api: TestClient, agent_id: int) -> list[dict[str, Any]]:
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        rows = conn.execute(
            "SELECT source, task_id, payload FROM wakeups WHERE agent_id = ? AND task_id IS NOT NULL"
            " ORDER BY id",
            (agent_id,),
        ).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]


def test_a_task_from_the_api_runs_in_the_worker_and_is_closed_by_it(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    cto, worker = create_team(api, project["id"])
    calls: list[tuple[int, int]] = []

    async def on_task_run(agent_id: int, task_id: int, tools: dict[str, Any]) -> None:
        calls.append((agent_id, task_id))
        if agent_id == worker["id"]:
            for status, text in (("in_progress", "Comecei."), ("done", "Corrigi o botão.")):
                result = await tools["tarefa_atualizar"](
                    {"id": task_id, "status": status, "comentario": text}
                )
                assert not result.get("is_error"), result

    factory.on_task_run = on_task_run

    response = api.post(
        "/api/tasks",
        json={
            "project_id": project["id"], "title": "Ajustar login", "description": "Corrigir o botão.",
            "assignee_agent_id": worker["id"],
        },
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]

    task = until(
        lambda: (t := api.get(f"/api/tasks/{task_id}").json())["task"]["status"] == "done"
        and [r["outcome"] for r in t["runs"]] == ["concluded"]
        and t
    )
    assert calls == [(worker["id"], task_id)]
    assert [(c["author_kind"], c["text"]) for c in task["comments"]][-1] == (
        "agent", "Corrigi o botão."
    )
    # The person created it, so nobody else is told when it closes.
    assert task_wakeups(api, cto["id"]) == []


def test_the_cto_that_created_the_task_is_woken_with_a_comment_when_it_is_done(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    cto, worker = create_team(api, project["id"])

    async def on_task_run(agent_id: int, task_id: int, tools: dict[str, Any]) -> None:
        if agent_id == worker["id"]:
            for status, text in (("in_progress", "Comecei."), ("done", "Corrigi o botão.")):
                result = await tools["tarefa_atualizar"](
                    {"id": task_id, "status": status, "comentario": text}
                )
                assert not result.get("is_error"), result
        else:
            await tools["tarefa_comentar"]({"id": task_id, "texto": "Recebi o resultado."})

    factory.on_task_run = on_task_run
    main = api.post(f"/api/agents/{cto['id']}/main").json()["session_id"]
    create = next(
        t.handler
        for t in build_tools(api.app.state.org, agent_id=cto["id"], session_id=main)
        if t.name == "tarefa_criar"
    )

    result = api.portal.call(
        create,
        {"titulo": "Ajustar login", "descricao": "Corrigir o botão.", "responsavel": "trabalhador"},
    )
    assert not result.get("is_error"), result
    task_id = json.loads(result["content"][0]["text"])["tarefa"]["id"]

    until(lambda: api.get(f"/api/tasks/{task_id}").json()["task"]["status"] == "done")
    woken = until(
        lambda: [w for w in task_wakeups(api, cto["id"]) if w["source"] == "comment"]
    )
    assert woken[0]["task_id"] == task_id
    assert woken[0]["payload"]["reason"] == "closed"
    run = until(
        lambda: next((r for r in runs_of(api, cto["id"]) if r["outcome"] == "concluded"), None)
    )
    assert run["source"] == "comment"


# Deleting a project ----------------------------------------------------------------------


def test_deleting_a_project_removes_its_agents_and_their_folders(
    api: TestClient, home: Path, events: list[dict[str, Any]]
):
    other = make_project(api, home, "outro")
    agent = create_agent(api, other["id"], "do-outro")
    folder = api.app.state.agent_files.root / "do-outro"
    assert (folder / "AGENT.md").is_file()
    events.clear()

    assert api.delete(f"/api/projects/{other['id']}").status_code == 204

    assert api.get("/api/agents").json() == []
    assert not folder.exists()
    assert [e["data"]["id"] for e in events if e["type"] == "agent.changed"] == [agent["id"]]


@pytest.mark.parametrize("sub", [False, True])
def test_deleting_a_project_closes_the_live_process_of_an_agent_that_holds_its_folder(
    api: TestClient, home: Path, project: dict[str, Any], factory: Factory, sub: bool
):
    other = make_project(api, home, "outro")
    held = Path(other["path"]) / "docs" if sub else Path(other["path"])
    held.mkdir(exist_ok=True)
    agent = create_agent(api, project["id"], "leitor")
    text = f'---\nname: Leitor\naddDirs: [{json.dumps(str(held))}]\n---\nLeia a outra pasta.\n'
    assert api.put(f"/api/agents/{agent['id']}/definition", json={"text": text}).status_code == 200
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    assert api.post(f"/api/sessions/{main}/messages", json={"text": "Oi"}).status_code == 202
    client = until(lambda: next((c for c in factory.clients if c.options.session_id == main), None))
    assert held in [Path(p) for p in client.options.add_dirs]
    assert not client.closed

    assert api.delete(f"/api/projects/{other['id']}").status_code == 204

    until(lambda: client.closed)
    assert api.get("/api/agents").json()[0]["id"] == agent["id"]  # the agent itself stays


def test_deleting_a_project_leaves_alone_an_agent_that_holds_another_folder(
    api: TestClient, home: Path, project: dict[str, Any], factory: Factory
):
    other = make_project(api, home, "outro")
    third = make_project(api, home, "terceiro")
    agent = create_agent(api, project["id"], "leitor")
    text = f'---\nname: Leitor\naddDirs: [{json.dumps(third["path"])}]\n---\nLeia.\n'
    assert api.put(f"/api/agents/{agent['id']}/definition", json={"text": text}).status_code == 200
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    assert api.post(f"/api/sessions/{main}/messages", json={"text": "Oi"}).status_code == 202
    client = until(lambda: next((c for c in factory.clients if c.options.session_id == main), None))

    assert api.delete(f"/api/projects/{other['id']}").status_code == 204

    assert not client.closed


def test_deleting_a_project_is_refused_while_one_of_its_agents_is_busy(
    api: TestClient, home: Path, factory: Factory
):
    factory.summary = None  # the run never concludes: the agent stays busy
    other = make_project(api, home, "outro")
    agent = create_agent(api, other["id"], "ocupado")
    assert api.post(f"/api/agents/{agent['id']}/wake", json={"text": "Trabalhe."}).status_code == 202
    until(lambda: any(r["outcome"] == "running" for r in runs_of(api, agent["id"])))

    response = api.delete(f"/api/projects/{other['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == PROJECT_BUSY_TEXT
    assert [p["id"] for p in api.get("/api/projects").json()].count(other["id"]) == 1
    assert (api.app.state.agent_files.root / "ocupado").is_dir()
    assert [r["outcome"] for r in runs_of(api, agent["id"])] == ["running"]


def test_the_terminal_does_not_queue_a_message_for_a_disabled_agent(
    api: TestClient, project: dict[str, Any], factory: Factory
):
    agent = create_agent(api, project["id"])
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    send = api.app.state.terminals._send_message

    assert api.portal.call(lambda: send(main, "Saída do terminal")) is True
    until(lambda: sent_texts(factory, main) == ["Saída do terminal"])

    assert api.patch(f"/api/agents/{agent['id']}", json={"enabled": False}).status_code == 200
    assert api.portal.call(lambda: send(main, "Outra saída")) is False
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        assert store.pending_wakeups(conn, agent["id"]) == []
    assert sent_texts(factory, main) == ["Saída do terminal"]
