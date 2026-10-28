"""API of the organization of agents: agents, `AGENT.md`, memory, secrets, registry,
conversations, wakeups, runs, routines, notices and the GitHub settings.

The app still wires the old `SpecialistService`; the fixture below puts the `OrgService` and
the `AgentFiles` in `app.state` the way the final wiring will (`app.state.org`,
`app.state.agent_files`). `OrgService.kick` is silenced so no drainer opens real sessions: the
queue is checked by what stays pending. The real SDK is never touched."""

import json
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_groups_api import without_header
from test_sessions_api import make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app
from claudio_maestro.org import store
from claudio_maestro.org.definition import definition_hash
from claudio_maestro.org.files import AgentFiles
from claudio_maestro.org.service import OrgService

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
SECRET = "SEGREDO-QUE-NAO-PODE-VAZAR"


def definition(name: str = "Revisor", body: str = "Você revisa o código.", **fields: Any) -> str:
    lines = [f"name: {name}"]
    for key, value in fields.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return "---\n" + "\n".join(lines) + f"\n---\n{body}\n"


@pytest.fixture
def factory() -> FakeAgentFactory:
    scripted: FakeAgentFactory = FakeAgentFactory(
        script=lambda content: text_turn(scripted.clients[-1].options.session_id, "feito")
    )
    return scripted


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every event published on the hub, from the routes and from the service alike."""
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "claudio_maestro.events.EventHub.publish", lambda self, e: published.append(e)
    )
    return published


@pytest.fixture
def api(factory: FakeAgentFactory, events):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as c:
        state = c.app.state
        state.agent_files = AgentFiles(state.settings.data_dir / "agents")
        state.org = OrgService(
            state.settings.db_path,
            sessions=state.sessions,
            files=state.agent_files,
            publish=lambda kind, data: state.hub.publish(
                {"session_id": None, "seq": 0, "type": kind, "data": data}
            ),
        )
        kicks: list[int | None] = []
        state.org.kick = lambda agent_id=None: kicks.append(agent_id)
        c.kicks = kicks
        yield c


def conn_of(api: TestClient):
    return closing(db.connect(api.app.state.settings.db_path))


def agents_dir(api: TestClient) -> Path:
    return api.app.state.settings.data_dir / "agents"


def create_agent(
    api: TestClient, project_id: int, slug: str = "revisor", name: str = "Revisor", **extra: Any
) -> dict[str, Any]:
    response = api.post(
        "/api/agents", json={"name": name, "slug": slug, "project_id": project_id, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def put_definition(api: TestClient, agent_id: int, text: str, **extra: Any):
    return api.put(f"/api/agents/{agent_id}/definition", json={"text": text, **extra})


@pytest.fixture
def project(api: TestClient, home: Path) -> dict[str, Any]:
    return make_project(api, home)


@pytest.fixture
def agent(api: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    return create_agent(api, project["id"])


# Create and list ----------------------------------------------------------------


def test_create_agent_writes_template(api, project):
    agent = create_agent(api, project["id"], "revisor-de-pr", "  Revisor de PR ", kind="cto")

    assert agent["slug"] == "revisor-de-pr"
    assert agent["name"] == "Revisor de PR"
    assert agent["project_id"] == project["id"]
    assert agent["reports_to"] is None
    assert agent["enabled"] is True
    assert agent["busy"] is False
    assert agent["unseen"] == 0
    assert agent["last_run"] is None
    assert agent["main_session_id"] is None
    assert agent["definition_error"] is None
    assert agent["description"].startswith("Coordena")  # the "cto" template
    text = (agents_dir(api) / "revisor-de-pr" / "AGENT.md").read_text()
    assert text.startswith("---\n") and "name: Revisor de PR" in text
    # The hash of the file is kept in the table.
    with conn_of(api) as conn:
        saved = store.get_agent(conn, agent["id"])
    assert saved.definition_hash == definition_hash(text)
    assert api.get("/api/agents").json() == [agent]
    assert api.get(f"/api/agents/{agent['id']}").json() == agent


def test_create_defaults_to_the_worker_template(api, project):
    agent = create_agent(api, project["id"])
    assert agent["description"].startswith("Executa")


def test_list_is_empty_at_first(api):
    assert api.get("/api/agents").json() == []


@pytest.mark.parametrize(
    "slug",
    ["../fora", "a/b", "A", "a b", "a_b", "", "-a", "a-", "a--b", "x" * 41, "a.b", "..", "a\n"],
)
def test_create_rejects_bad_slug(api, project, slug):
    response = api.post(
        "/api/agents", json={"name": "X", "slug": slug, "project_id": project["id"]}
    )
    assert response.status_code == 422
    assert api.get("/api/agents").json() == []
    root = agents_dir(api)
    assert not root.exists() or list(root.iterdir()) == []
    assert not (root.parent / "fora").exists()
    assert not (root.parent.parent / "fora").exists()


def test_create_bad_slug_is_one_sentence_in_portuguese(api, project):
    response = api.post(
        "/api/agents", json={"name": "X", "slug": "A b", "project_id": project["id"]}
    )
    assert "identificador" in response.json()["detail"]


def test_create_accepts_the_longest_slug(api, project):
    create_agent(api, project["id"], "a" + "b" * 39)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "slug": "ok"},
        {"name": "   ", "slug": "ok"},
        {"name": "A", "slug": "ok", "kind": "gerente"},
        {"name": "A", "slug": "ok", "enabled": False},
        {"name": "A"},
    ],
)
def test_create_refuses_invalid_bodies(api, project, body):
    response = api.post("/api/agents", json={"project_id": project["id"], **body})
    assert response.status_code == 422
    assert api.get("/api/agents").json() == []


def test_create_with_an_unknown_project_is_404(api):
    response = api.post("/api/agents", json={"name": "A", "slug": "ok", "project_id": 999})
    assert response.status_code == 404
    assert api.get("/api/agents").json() == []
    assert not (agents_dir(api) / "ok").exists()


def test_create_with_a_repeated_slug_is_409(api, project, agent):
    response = api.post(
        "/api/agents", json={"name": "Outro", "slug": "revisor", "project_id": project["id"]}
    )
    assert response.status_code == 409
    assert len(api.get("/api/agents").json()) == 1


def test_create_with_a_leftover_folder_is_409_and_leaves_no_row(api, project):
    (agents_dir(api) / "sobra").mkdir(parents=True)
    response = api.post(
        "/api/agents", json={"name": "A", "slug": "sobra", "project_id": project["id"]}
    )
    assert response.status_code == 409
    assert api.get("/api/agents").json() == []
    # The folder that was not ours stays.
    assert (agents_dir(api) / "sobra").is_dir()


def test_create_failing_on_disk_rolls_the_row_back(api, project, monkeypatch):
    def broken(self, slug, text):
        raise OSError("disco cheio /segredo/caminho")

    monkeypatch.setattr(AgentFiles, "create", broken)
    response = api.post(
        "/api/agents", json={"name": "A", "slug": "ok", "project_id": project["id"]}
    )
    assert response.status_code == 503
    assert "/segredo/caminho" not in response.text
    assert api.get("/api/agents").json() == []


def test_create_with_a_boss_of_another_project_is_422(api, project, home):
    other = make_project(api, home, "outro")
    boss = create_agent(api, other["id"], "chefe", "Chefe")
    response = api.post(
        "/api/agents",
        json={"name": "A", "slug": "ok", "project_id": project["id"], "reports_to": boss["id"]},
    )
    assert response.status_code == 422
    assert [a["slug"] for a in api.get("/api/agents").json()] == ["chefe"]
    assert not (agents_dir(api) / "ok").exists()


def test_create_with_a_missing_boss_is_422(api, project):
    response = api.post(
        "/api/agents",
        json={"name": "A", "slug": "ok", "project_id": project["id"], "reports_to": 999},
    )
    assert response.status_code == 422
    assert api.get("/api/agents").json() == []


def test_list_filters_by_project(api, project, home):
    other = make_project(api, home, "outro")
    create_agent(api, project["id"], "um", "Um")
    create_agent(api, other["id"], "dois", "Dois")
    assert [a["slug"] for a in api.get(f"/api/agents?project_id={other['id']}").json()] == ["dois"]
    assert len(api.get("/api/agents").json()) == 2


def test_list_agents_has_description_from_definition(api, agent):
    text = definition(
        "Revisor", "Você revisa.", description="Revisa PRs do app", model="opus", effort="high"
    )
    assert put_definition(api, agent["id"], text).status_code == 200

    [listed] = api.get("/api/agents").json()
    assert listed["description"] == "Revisa PRs do app"
    assert listed["model"] == "opus"
    assert listed["effort"] == "high"
    assert listed["definition_error"] is None


def test_list_survives_a_missing_or_broken_definition(api, project):
    first = create_agent(api, project["id"], "sumiu", "Sumiu")
    second = create_agent(api, project["id"], "quebrado", "Quebrado")
    third = create_agent(api, project["id"], "ok", "Ok")
    (agents_dir(api) / "sumiu" / "AGENT.md").unlink()
    (agents_dir(api) / "quebrado" / "AGENT.md").write_text("sem cabeçalho\n")

    listed = {a["id"]: a for a in api.get("/api/agents").json()}

    assert listed[first["id"]]["description"] == ""
    assert "não foi encontrado" in listed[first["id"]]["definition_error"]
    assert listed[second["id"]]["description"] == ""
    assert "---" in listed[second["id"]]["definition_error"]
    assert listed[third["id"]]["definition_error"] is None
    # A folder that is gone altogether does not break the list either.
    import shutil

    shutil.rmtree(agents_dir(api) / "ok")
    ok = {a["id"]: a for a in api.get("/api/agents").json()}[third["id"]]
    assert ok["description"] == "" and ok["definition_error"]
    assert str(agents_dir(api)) not in json.dumps(api.get("/api/agents").json())


def test_get_unknown_agent_is_404(api):
    assert api.get("/api/agents/999").status_code == 404


# Edit -----------------------------------------------------------------------------


def patch(api: TestClient, agent_id: int, **body: Any):
    return api.patch(f"/api/agents/{agent_id}", json=body)


def test_patch_updates_boss_and_enabled(api, project, agent):
    boss = create_agent(api, project["id"], "chefe", "Chefe")
    response = patch(api, agent["id"], reports_to=boss["id"], enabled=False)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Revisor"
    assert body["reports_to"] == boss["id"]
    assert body["enabled"] is False
    # Back to a top agent.
    assert patch(api, agent["id"], reports_to=None).json()["reports_to"] is None


@pytest.mark.parametrize("name", ["Novo nome", None, "   ", ""])
def test_patch_name_is_refused_the_file_rules(api, agent, name):
    response = patch(api, agent["id"], name=name, enabled=False)
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "O nome do agente vem do AGENT.md; altere o campo name: na definição."
    )
    # Nothing else in the same request was applied either.
    assert api.get(f"/api/agents/{agent['id']}").json() == agent


def test_name_changes_only_through_the_definition(api, agent):
    assert put_definition(api, agent["id"], definition("Outro Nome")).status_code == 200
    assert api.get(f"/api/agents/{agent['id']}").json()["name"] == "Outro Nome"


def test_patch_without_fields_changes_nothing(api, agent):
    response = api.patch(f"/api/agents/{agent['id']}", json={})
    assert response.status_code == 200
    assert response.json() == agent


@pytest.mark.parametrize(
    "body",
    [{"enabled": None}, {"enabled": "talvez"}, {"slug": "x"},
     {"project_id": 2}, {"unknown": 1}],
)
def test_patch_refuses_invalid_fields(api, agent, body):
    assert api.patch(f"/api/agents/{agent['id']}", json=body).status_code == 422
    assert api.get("/api/agents").json() == [agent]


def test_patch_unknown_agent_is_404(api):
    assert patch(api, 999, enabled=False).status_code == 404


def test_patch_reports_to_cycle_422(api, project):
    top = create_agent(api, project["id"], "topo", "Topo")
    middle = create_agent(api, project["id"], "meio", "Meio", reports_to=top["id"])
    leaf = create_agent(api, project["id"], "folha", "Folha", reports_to=middle["id"])

    for agent_id, boss_id in ((top["id"], leaf["id"]), (top["id"], top["id"]), (middle["id"], leaf["id"])):
        response = patch(api, agent_id, reports_to=boss_id)
        assert response.status_code == 422, response.text
        assert "reportar" in response.json()["detail"]
    assert api.get(f"/api/agents/{top['id']}").json()["reports_to"] is None


def test_patch_reports_to_other_project_422(api, project, home, agent):
    other = make_project(api, home, "outro")
    boss = create_agent(api, other["id"], "chefe", "Chefe")
    response = patch(api, agent["id"], reports_to=boss["id"])
    assert response.status_code == 422
    assert "mesmo projeto" in response.json()["detail"]


def test_patch_is_all_or_nothing(api, project):
    top = create_agent(api, project["id"], "topo", "Topo")
    leaf = create_agent(api, project["id"], "folha", "Folha", reports_to=top["id"])
    # `enabled` is valid, the boss closes a cycle: nothing is written.
    response = patch(api, top["id"], enabled=False, reports_to=leaf["id"])
    assert response.status_code == 422
    unchanged = api.get(f"/api/agents/{top['id']}").json()
    assert unchanged["reports_to"] is None and unchanged["enabled"] is True


def test_turning_the_agent_on_calls_the_drainer(api, agent):
    patch(api, agent["id"], enabled=False)
    assert api.kicks == []
    patch(api, agent["id"], enabled=True)
    assert api.kicks == [agent["id"]]
    # Turning it off does not wake the queue.
    patch(api, agent["id"], enabled=False)
    assert api.kicks == [agent["id"]]


def test_agent_events_are_published(api, agent, events):
    events.clear()
    patch(api, agent["id"], enabled=False)
    assert {"session_id": None, "seq": 0, "type": "agent.changed", "data": {"id": agent["id"]}} in events


def test_patch_requires_the_maestro_header(api, agent):
    with without_header(api, "x-maestro"):
        assert patch(api, agent["id"], enabled=False).status_code == 403
        assert api.get("/api/agents").status_code == 403


# Delete -----------------------------------------------------------------------------


def test_delete_removes_row_and_folder_and_keeps_sessions(api, agent):
    main = api.post(f"/api/agents/{agent['id']}/main").json()["session_id"]
    response = api.delete(f"/api/agents/{agent['id']}")
    assert response.status_code == 204
    assert api.get("/api/agents").json() == []
    assert not (agents_dir(api) / "revisor").exists()
    with conn_of(api) as conn:
        row = conn.execute(
            "SELECT agent_id FROM sessions WHERE session_id = ?", (main,)
        ).fetchone()
    assert row is not None and row["agent_id"] is None
    assert api.delete(f"/api/agents/{agent['id']}").status_code == 404


def test_delete_promotes_the_reports_to_top_agents(api, project):
    boss = create_agent(api, project["id"], "chefe", "Chefe")
    report = create_agent(api, project["id"], "sub", "Sub", reports_to=boss["id"])
    assert api.delete(f"/api/agents/{boss['id']}").status_code == 204
    assert api.get(f"/api/agents/{report['id']}").json()["reports_to"] is None


def test_delete_is_refused_while_a_run_is_active(api, agent):
    with conn_of(api) as conn, db.transaction(conn):
        store.insert_run(
            conn, agent_id=agent["id"], source="manual", started_at=1, outcome="running"
        )
    response = api.delete(f"/api/agents/{agent['id']}")
    assert response.status_code == 409
    assert (agents_dir(api) / "revisor").is_dir()
    assert api.get(f"/api/agents/{agent['id']}").json()["busy"] is True


def test_delete_rechecks_busy_inside_the_transaction(api, agent):
    """A run that starts while the sessions are being closed stops the deletion: nothing is
    removed, neither the row, nor its run, nor the folder."""
    sid = api.post(f"/api/agents/{agent['id']}/conversations").json()["session_id"]
    session = api.app.state.sessions.get(sid)

    async def close_and_start_a_run(final: bool = False) -> None:
        session.client = None
        with conn_of(api) as conn, db.transaction(conn):
            store.insert_run(
                conn, agent_id=agent["id"], source="routine", started_at=1, outcome="starting"
            )

    session.client = object()
    session.close = close_and_start_a_run

    response = api.delete(f"/api/agents/{agent['id']}")

    assert response.status_code == 409
    assert "executando" in response.json()["detail"]
    assert (agents_dir(api) / "revisor" / "AGENT.md").is_file()
    assert api.get(f"/api/agents/{agent['id']}").status_code == 200
    [run] = api.get(f"/api/agents/{agent['id']}/runs").json()
    assert run["outcome"] == "starting"


def test_delete_closes_the_open_sessions_of_the_agent(api, agent, factory):
    sid = api.post(f"/api/agents/{agent['id']}/conversations").json()["session_id"]
    session = api.app.state.sessions.get(sid)
    closed = []

    async def fake_close(final: bool = False) -> None:
        closed.append(sid)
        session.client = None

    session.client = object()
    session.close = fake_close
    assert api.delete(f"/api/agents/{agent['id']}").status_code == 204
    assert closed == [sid]


# Duplicate -----------------------------------------------------------------------------


def test_duplicate_copies_definition_only(api, project, home):
    (project_dir := home / "app" / "extra").mkdir()
    boss = create_agent(api, project["id"], "chefe", "Chefe")
    source = create_agent(api, project["id"], "origem", "Origem", reports_to=boss["id"])
    text = definition(
        "Origem", "Faça tudo.", description="D", model="haiku", addDirs=[str(project_dir)],
        worktree=True, disallowedTools=["WebFetch"],
    )
    assert put_definition(api, source["id"], text).status_code == 200
    assert api.put(
        f"/api/agents/{source['id']}/memory", json={"text": "memória da origem"}
    ).status_code == 200
    assert api.put(
        f"/api/agents/{source['id']}/secrets", json={"values": {"TOKEN": SECRET}}
    ).status_code == 200
    other = make_project(api, home, "outro")

    response = api.post(
        f"/api/agents/{source['id']}/duplicate", json={"project_id": other["id"], "slug": "copia"}
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["slug"] == "copia" and copy["project_id"] == other["id"]
    assert copy["reports_to"] is None
    assert copy["description"] == "D" and copy["model"] == "haiku"
    folder = agents_dir(api) / "copia"
    assert sorted(p.name for p in folder.iterdir()) == ["AGENT.md"]
    copied = (folder / "AGENT.md").read_text()
    assert "addDirs" not in copied
    assert "worktree: true" in copied and "WebFetch" in copied and "Faça tudo." in copied
    assert api.get(f"/api/agents/{copy['id']}/memory").json() == {"text": ""}
    assert api.get(f"/api/agents/{copy['id']}/secrets").json() == {"names": []}
    # The origin is untouched.
    assert str(project_dir) in (agents_dir(api) / "origem" / "AGENT.md").read_text()
    assert api.get(f"/api/agents/{source['id']}").json()["reports_to"] == boss["id"]


def test_duplicate_refuses_a_bad_slug_a_repeated_one_and_an_unknown_project(api, project, agent):
    url = f"/api/agents/{agent['id']}/duplicate"
    assert api.post(url, json={"project_id": project["id"], "slug": "../x"}).status_code == 422
    assert api.post(url, json={"project_id": project["id"], "slug": "revisor"}).status_code == 409
    assert api.post(url, json={"project_id": 999, "slug": "novo"}).status_code == 404
    assert len(api.get("/api/agents").json()) == 1
    assert api.post("/api/agents/999/duplicate", json={"project_id": 1, "slug": "x"}).status_code == 404


def test_duplicate_of_an_unreadable_definition_is_422(api, project, agent):
    (agents_dir(api) / "revisor" / "AGENT.md").unlink()
    response = api.post(
        f"/api/agents/{agent['id']}/duplicate", json={"project_id": project["id"], "slug": "copia"}
    )
    assert response.status_code == 422
    assert len(api.get("/api/agents").json()) == 1


# AGENT.md -----------------------------------------------------------------------------


def test_get_definition_returns_text_and_hash(api, agent):
    body = api.get(f"/api/agents/{agent['id']}/definition").json()
    on_disk = (agents_dir(api) / "revisor" / "AGENT.md").read_text()
    assert body == {"text": on_disk, "hash": definition_hash(on_disk)}


def test_get_definition_of_a_missing_file_is_404(api, agent):
    (agents_dir(api) / "revisor" / "AGENT.md").unlink()
    response = api.get(f"/api/agents/{agent['id']}/definition")
    assert response.status_code == 404
    assert str(agents_dir(api)) not in response.text


def test_put_definition_saves_and_updates_name_and_hash(api, agent):
    text = definition("Novo Nome", "Outro prompt.", description="Nova")
    response = put_definition(api, agent["id"], text)
    assert response.status_code == 200, response.text
    assert response.json() == {"text": text, "hash": definition_hash(text)}
    assert (agents_dir(api) / "revisor" / "AGENT.md").read_text() == text
    with conn_of(api) as conn:
        saved = store.get_agent(conn, agent["id"])
    assert saved.name == "Novo Nome" and saved.definition_hash == definition_hash(text)
    assert api.get(f"/api/agents/{agent['id']}/definition").json()["text"] == text


def test_put_definition_invalid_keeps_file(api, agent):
    before = api.get(f"/api/agents/{agent['id']}/definition").json()
    invalid = "---\nname: X\ncampo_estranho: 1\n---\nprompt\n"

    response = put_definition(api, agent["id"], invalid)

    assert response.status_code == 422
    body = response.json()
    assert "campo_estranho" in body["detail"]
    assert body["field"] == "campo_estranho"
    assert body["line"] == 3
    assert api.get(f"/api/agents/{agent['id']}/definition").json() == before


@pytest.mark.parametrize(
    "text",
    ["", "sem cabeçalho", "---\nname: X\n", "---\nname: [\n---\nx\n", "---\n---\nx\n",
     "---\nname: X\n---\n", "---\nname: X\neffort: demais\n---\nx\n"],
)
def test_put_definition_refuses_every_invalid_text_without_touching_the_file(api, agent, text):
    before = api.get(f"/api/agents/{agent['id']}/definition").json()
    response = put_definition(api, agent["id"], text)
    assert response.status_code == 422
    assert set(response.json()) == {"detail", "field", "line"}
    assert api.get(f"/api/agents/{agent['id']}/definition").json() == before


def test_put_definition_hash_mismatch_409(api, agent):
    opened = api.get(f"/api/agents/{agent['id']}/definition").json()
    # Someone else saves in the meantime.
    assert put_definition(api, agent["id"], definition("Revisor", "Versão B.")).status_code == 200

    response = put_definition(
        api, agent["id"], definition("Revisor", "Versão C."), hash=opened["hash"]
    )

    assert response.status_code == 409
    assert "Versão B." in api.get(f"/api/agents/{agent['id']}/definition").json()["text"]
    # With the current hash it goes through.
    current = api.get(f"/api/agents/{agent['id']}/definition").json()["hash"]
    assert put_definition(
        api, agent["id"], definition("Revisor", "Versão C."), hash=current
    ).status_code == 200


def test_put_definition_hash_with_an_unreadable_file_is_409(api, agent):
    path = agents_dir(api) / "revisor" / "AGENT.md"
    path.write_bytes(b"---\nname: \xff\xfe\n---\nx\n")
    response = put_definition(api, agent["id"], definition(), hash="a" * 64)
    assert response.status_code == 409
    assert path.read_bytes().startswith(b"---\nname: \xff")
    # Without a hash the broken file is simply replaced.
    assert put_definition(api, agent["id"], definition()).status_code == 200


def test_put_definition_hash_with_a_missing_file_is_404_like_without_hash(api, agent):
    (agents_dir(api) / "revisor" / "AGENT.md").unlink()
    response = put_definition(api, agent["id"], definition(), hash="a" * 64)
    assert response.status_code == 404
    assert str(agents_dir(api)) not in response.text
    assert not (agents_dir(api) / "revisor" / "AGENT.md").exists()


def test_definition_row_is_written_under_the_lock_of_the_agent(api, agent, monkeypatch):
    """File and hash/name in the table are written under one lock, so two saves never leave
    the file of one and the hash of the other."""
    from claudio_maestro.api import org as api_org

    original = store.update_agent
    held: list[bool] = []

    def spy(conn, agent_id, **fields):
        if "definition_hash" in fields:
            held.append(api_org._slug_lock("revisor").locked())
        return original(conn, agent_id, **fields)

    monkeypatch.setattr(store, "update_agent", spy)

    assert put_definition(api, agent["id"], definition("Nome A", "Versão A.")).status_code == 200

    assert held == [True]


def test_concurrent_definition_saves_leave_file_and_hash_of_the_same_save(api, agent):
    texts = {
        key: definition(f"Nome {key}", f"Versão {key}.") for key in "ABCDEF"
    }
    codes: dict[str, int] = {}

    def send(key: str) -> None:
        codes[key] = put_definition(api, agent["id"], texts[key]).status_code

    threads = [threading.Thread(target=send, args=(key,)) for key in texts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert set(codes.values()) == {200}
    on_disk = (agents_dir(api) / "revisor" / "AGENT.md").read_text()
    with conn_of(api) as conn:
        saved = store.get_agent(conn, agent["id"])
    assert saved.definition_hash == definition_hash(on_disk)
    assert saved.name == on_disk.splitlines()[1].removeprefix("name: ")


def test_put_definition_add_dir_inside_a_project_is_accepted(api, agent, home):
    (home / "app" / "sub").mkdir()
    text = definition(addDirs=["sub", str(home / "app" / "sub")])
    assert put_definition(api, agent["id"], text).status_code == 200


def test_put_definition_add_dir_outside_projects_422(api, agent, home):
    before = api.get(f"/api/agents/{agent['id']}/definition").json()
    (home / "fora").mkdir()
    (home / "app" / "atalho").symlink_to(home / "fora", target_is_directory=True)
    entries = ["../fora", "atalho", "atalho/../../fora", str(home / "fora"), "/etc"]

    for entry in entries:
        response = put_definition(api, agent["id"], definition(addDirs=[entry]))
        assert response.status_code == 422, entry
        body = response.json()
        assert body["field"] == "addDirs" and body["line"] == 3
        assert "projeto cadastrado" in body["detail"]
        # The resolved path of the target is never quoted back.
        assert str(home) not in body["detail"] or entry == str(home / "fora")
    assert api.get(f"/api/agents/{agent['id']}/definition").json() == before


def test_put_definition_add_dir_in_a_sibling_with_the_same_prefix_is_422(api, agent, home):
    (home / "app2").mkdir()  # not a registered project: `/x/app` is a prefix of `/x/app2`
    for entry in ("../app2", str(home / "app2"), "../app2/x"):
        response = put_definition(api, agent["id"], definition(addDirs=[entry]))
        assert response.status_code == 422, entry
        assert response.json()["field"] == "addDirs"


def test_put_definition_requires_the_maestro_header(api, agent):
    with without_header(api, "x-maestro"):
        assert put_definition(api, agent["id"], definition()).status_code == 403


# Memory -----------------------------------------------------------------------------


def test_memory_roundtrip_and_limit(api, agent):
    url = f"/api/agents/{agent['id']}/memory"
    assert api.get(url).json() == {"text": ""}
    assert api.put(url, json={"text": "Aprendi isto."}).json() == {"text": "Aprendi isto."}
    assert api.get(url).json() == {"text": "Aprendi isto."}
    assert (agents_dir(api) / "revisor" / "memoria.md").read_text() == "Aprendi isto."
    assert api.put(url, json={"text": "x" * 4000}).status_code == 200
    too_long = api.put(url, json={"text": "x" * 4001})
    assert too_long.status_code == 422 and "4.000" in too_long.json()["detail"]
    assert api.get(url).json()["text"] == "x" * 4000
    assert api.get("/api/agents/999/memory").status_code == 404


# Secrets -----------------------------------------------------------------------------


def test_secrets_never_echo_values(api, agent, events):
    url = f"/api/agents/{agent['id']}/secrets"
    assert api.get(url).json() == {"names": []}
    events.clear()

    response = api.put(url, json={"values": {"GH_TOKEN": SECRET, "OUTRO": "x"}})

    assert response.status_code == 200
    assert response.json() == {"names": ["GH_TOKEN", "OUTRO"]}
    assert SECRET not in response.text
    assert SECRET not in api.get(url).text
    assert SECRET not in json.dumps(events)
    assert SECRET not in api.get("/api/agents").text
    # Only the file holds it, with mode 600.
    path = agents_dir(api) / "revisor" / "secrets.env"
    assert SECRET in path.read_text() and path.stat().st_mode & 0o777 == 0o600
    # `null` deletes a name.
    assert api.put(url, json={"values": {"OUTRO": None}}).json() == {"names": ["GH_TOKEN"]}


@pytest.mark.parametrize(
    "body",
    [
        {"values": {"PATH": SECRET}},
        {"values": {"CLAUDE_X": SECRET}},
        {"values": {"minuscula": SECRET}},
        {"values": {SECRET: "x"}},
        {"values": {"OK": 5}},
        {"values": {"OK": SECRET + "\x00"}},
        {"values": "nao"},
        {"values": {"OK": "x" * 20_001}},
        {"valores": {"OK": SECRET}},
        {"values": {"OK": SECRET}, "extra": SECRET},
        [SECRET],
    ],
)
def test_secrets_refuse_bad_bodies_without_echoing_anything(api, agent, body):
    response = api.put(f"/api/agents/{agent['id']}/secrets", json=body)
    assert response.status_code == 422
    assert SECRET not in response.text
    assert api.get(f"/api/agents/{agent['id']}/secrets").json() == {"names": []}


def test_secrets_refuse_a_body_that_is_not_json(api, agent):
    response = api.put(
        f"/api/agents/{agent['id']}/secrets", content=SECRET, headers={"content-type": "text/plain"}
    )
    assert response.status_code == 422 and SECRET not in response.text


def test_secrets_refuse_a_corrupted_file_without_quoting_it(api, agent):
    (agents_dir(api) / "revisor" / "secrets.env").write_bytes(b"A=\xff\xfe\n")
    response = api.put(f"/api/agents/{agent['id']}/secrets", json={"values": {"B": "x"}})
    assert response.status_code == 422
    assert (agents_dir(api) / "revisor" / "secrets.env").read_bytes() == b"A=\xff\xfe\n"


def test_secret_writes_of_one_agent_are_serialized(api, agent, monkeypatch):
    """`write_secrets` reads, merges and writes: two of the same agent never overlap, so no
    name is lost."""
    original = AgentFiles.write_secrets
    state = {"active": 0, "peak": 0}
    guard = threading.Lock()

    def slow(self, slug, values):
        with guard:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        try:
            return original(self, slug, values)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(AgentFiles, "write_secrets", slow)
    url = f"/api/agents/{agent['id']}/secrets"
    results: list[int] = []

    def send(name: str) -> None:
        results.append(api.put(url, json={"values": {name: "valor"}}).status_code)

    threads = [threading.Thread(target=send, args=(name,)) for name in ("UM", "DOIS", "TRES")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200, 200, 200]
    assert state["peak"] == 1
    assert api.get(url).json() == {"names": ["DOIS", "TRES", "UM"]}


def test_secrets_of_an_unknown_agent_are_404(api):
    assert api.get("/api/agents/999/secrets").status_code == 404
    assert api.put("/api/agents/999/secrets", json={"values": {}}).status_code == 404


# Registry -----------------------------------------------------------------------------


def test_registry_lists_and_deletes_by_query_key(api, agent):
    with conn_of(api) as conn, db.transaction(conn):
        store.upsert_item(
            conn, agent["id"], key="SENTRY-1/../x", status="done", link=None, note="n", now=5
        )
        store.upsert_item(
            conn, agent["id"], key="SENTRY-2", status="open", link=None, note=None, now=6
        )
    url = f"/api/agents/{agent['id']}/registry"
    assert {i["key"] for i in api.get(url).json()} == {"SENTRY-1/../x", "SENTRY-2"}

    assert api.delete(url, params={"key": "SENTRY-1/../x"}).status_code == 204
    assert [i["key"] for i in api.get(url).json()] == ["SENTRY-2"]
    assert api.delete(url).status_code == 422
    assert api.get("/api/agents/999/registry").status_code == 404


# Conversations -----------------------------------------------------------------------


def test_main_conversation_is_created_once(api, agent):
    first = api.post(f"/api/agents/{agent['id']}/main")
    assert first.status_code == 200
    sid = first.json()["session_id"]
    assert api.post(f"/api/agents/{agent['id']}/main").json() == {"session_id": sid}
    assert api.get(f"/api/agents/{agent['id']}").json()["main_session_id"] == sid
    assert api.post("/api/agents/999/main").status_code == 404


def test_open_list_and_reopen_conversations(api, agent):
    url = f"/api/agents/{agent['id']}/conversations"
    opened = api.post(url)
    assert opened.status_code == 201, opened.text
    sid = opened.json()["session_id"]
    assert api.post(url).json()["session_id"] == sid
    other = api.post(url, json={"new": True}).json()["session_id"]
    assert other != sid
    listed = {c["session_id"] for c in api.get(url).json()}
    assert listed == {sid, other}
    assert api.post(url, json={"session_id": other}).json()["session_id"] == other


def test_conversation_requires_header_and_rejects_foreign_session(api, agent, project):
    url = f"/api/agents/{agent['id']}/conversations"
    assert api.post(url, json={"session_id": "missing"}).status_code == 404
    foreign = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    assert api.post(url, json={"session_id": foreign}).status_code == 404
    assert api.post("/api/agents/999/conversations").status_code == 404
    with without_header(api, "x-maestro"):
        assert api.post(url).status_code == 403
        assert api.get(url).status_code == 403


def test_conversation_with_an_unavailable_project_is_409(api, agent, home):
    import shutil

    shutil.rmtree(home / "app")
    response = api.post(f"/api/agents/{agent['id']}/conversations", json={"new": True})
    assert response.status_code == 409


def test_pending_message_preview_is_scoped_to_its_agent_and_session(api, project, agent):
    org = api.app.state.org
    sid = api.post(f"/api/agents/{agent['id']}/conversations", json={"new": True}).json()["session_id"]
    other = create_agent(api, project["id"], "outro", "Outro")
    api.portal.call(
        lambda: org.wake(agent["id"], source="message", text="Distinguir esta mensagem",
                         payload={"session_id": sid})
    )
    api.portal.call(lambda: org.wake(agent["id"], source="message", text="Para a principal"))

    response = api.get(f"/api/agents/{agent['id']}/messages", params={"session_id": sid})
    assert response.status_code == 200
    assert [m["text"] for m in response.json()] == ["Distinguir esta mensagem"]
    main = api.get(f"/api/agents/{agent['id']}").json()["main_session_id"]
    assert [m["text"] for m in api.get(
        f"/api/agents/{agent['id']}/messages", params={"session_id": main}
    ).json()] == ["Para a principal"]
    # Another agent's conversation, or none at all, is not found.
    assert api.get(f"/api/agents/{other['id']}/messages", params={"session_id": sid}).status_code == 404
    assert api.get(f"/api/agents/{agent['id']}/messages", params={"session_id": "x"}).status_code == 404
    assert api.get(f"/api/agents/{agent['id']}/messages").status_code == 422


def test_announcements_list_and_pending_filter(api, agent):
    with conn_of(api) as conn, db.transaction(conn):
        old = store.add_announcement(
            conn, agent_id=agent["id"], run_id=None, session_id=None, text="velho", created_at=1
        )
        store.add_announcement(
            conn, agent_id=agent["id"], run_id=None, session_id=None, text="novo", created_at=2
        )
        store.mark_announcements_delivered(conn, [old.id], 3)
    url = f"/api/agents/{agent['id']}/announcements"
    assert [a["text"] for a in api.get(url).json()] == ["novo", "velho"]
    assert [a["text"] for a in api.get(url, params={"pending": True}).json()] == ["novo"]
    assert "agent_id" not in api.get(url).json()[0]
    assert api.get(url, params={"limit": 0}).status_code == 422
    assert api.get("/api/agents/999/announcements").status_code == 404
    assert api.get(f"/api/agents/{agent['id']}").json()["unseen"] == 1


# Wakeups and runs -----------------------------------------------------------------------


def test_wake_returns_202_and_lists_wakeup(api, agent):
    response = api.post(f"/api/agents/{agent['id']}/wake", json={"text": "Faça isto agora"})

    assert response.status_code == 202, response.text
    wakeup = response.json()
    assert wakeup["source"] == "manual" and wakeup["state"] == "pending"
    [listed] = api.get(f"/api/agents/{agent['id']}/wakeups").json()
    assert listed["id"] == wakeup["id"] and listed["text"] == "Faça isto agora"
    assert listed["source"] == "manual"


def test_wake_without_a_body_uses_the_standard_text(api, agent):
    assert api.post(f"/api/agents/{agent['id']}/wake").status_code == 202
    [listed] = api.get(f"/api/agents/{agent['id']}/wakeups").json()
    assert "concluir" in listed["text"]


def test_wake_refuses_a_text_over_the_limit_and_unknown_agents(api, agent):
    assert api.post(f"/api/agents/{agent['id']}/wake", json={"text": "x" * 5001}).status_code == 422
    assert api.post("/api/agents/999/wake").status_code == 404
    assert api.get(f"/api/agents/{agent['id']}/wakeups").json() == []


def test_wake_of_a_disabled_agent_is_409_and_stays_pending(api, agent):
    patch(api, agent["id"], enabled=False)

    response = api.post(f"/api/agents/{agent['id']}/wake", json={"text": "Quando ligar"})

    assert response.status_code == 409
    assert response.json()["detail"] == "O agente está desligado."
    [pending] = api.get(f"/api/agents/{agent['id']}/wakeups").json()
    assert pending["text"] == "Quando ligar"


def test_wake_queue_is_bounded(api, agent):
    for _ in range(50):
        assert api.post(f"/api/agents/{agent['id']}/wake").status_code == 202
    response = api.post(f"/api/agents/{agent['id']}/wake")
    assert response.status_code == 409 and "50" in response.json()["detail"]


def test_wake_storage_failure_returns_a_sentence_without_the_exception(api, agent, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("SEGREDO_NO_ERRO")

    monkeypatch.setattr(api.app.state.agent_files, "write_wake_text", fail)
    response = api.post(f"/api/agents/{agent['id']}/wake")
    assert response.status_code == 422
    assert "SEGREDO_NO_ERRO" not in response.text
    assert api.get(f"/api/agents/{agent['id']}/wakeups").json() == []


def test_cancel_wakeup(api, agent):
    wakeup = api.post(f"/api/agents/{agent['id']}/wake").json()
    url = f"/api/agents/{agent['id']}/wakeups/{wakeup['id']}/cancel"

    assert api.post(url).status_code == 200
    assert api.get(f"/api/agents/{agent['id']}/wakeups").json() == []
    assert api.post(url).status_code == 200  # idempotent
    assert api.post(f"/api/agents/{agent['id']}/wakeups/999/cancel").status_code == 404


def test_cancel_wakeup_already_served_is_409(api, agent):
    wakeup = api.post(f"/api/agents/{agent['id']}/wake").json()
    with conn_of(api) as conn, db.transaction(conn):
        store.take_wakeup(conn, wakeup["id"], None, 5)
    assert api.post(f"/api/agents/{agent['id']}/wakeups/{wakeup['id']}/cancel").status_code == 409


def test_cancel_wakeup_of_another_agent_is_404(api, project, agent):
    other = create_agent(api, project["id"], "outro", "Outro")
    wakeup = api.post(f"/api/agents/{agent['id']}/wake").json()
    assert api.post(f"/api/agents/{other['id']}/wakeups/{wakeup['id']}/cancel").status_code == 404


def test_runs_list_and_cancel(api, agent, project):
    other = create_agent(api, project["id"], "outro", "Outro")
    with conn_of(api) as conn, db.transaction(conn):
        run = store.insert_run(
            conn, agent_id=agent["id"], source="manual", started_at=10, outcome="running"
        )
        done = store.insert_run(
            conn, agent_id=agent["id"], source="routine", started_at=5, outcome="concluded",
            ended_at=6,
        )
    listed = api.get(f"/api/agents/{agent['id']}/runs").json()
    assert [r["id"] for r in listed] == [run.id, done.id]
    assert api.get(f"/api/agents/{agent['id']}").json()["last_run"]["id"] == run.id

    cancelled = api.post(f"/api/agents/{agent['id']}/runs/{run.id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["outcome"] == "cancelled"
    assert api.post(f"/api/agents/{agent['id']}/runs/{run.id}/cancel").json() == cancelled.json()
    assert api.post(f"/api/agents/{agent['id']}/runs/{done.id}/cancel").status_code == 409
    assert api.post(f"/api/agents/{agent['id']}/runs/999/cancel").status_code == 404
    assert api.post(f"/api/agents/{other['id']}/runs/{run.id}/cancel").status_code == 404
    assert api.get(f"/api/agents/{agent['id']}/runs", params={"limit": 1}).json()[0]["id"] == run.id
    assert api.get(f"/api/agents/{agent['id']}/runs", params={"limit": 0}).status_code == 422


def test_cancel_requires_the_maestro_header(api, agent):
    wakeup = api.post(f"/api/agents/{agent['id']}/wake").json()
    with without_header(api, "x-maestro"):
        assert api.post(f"/api/agents/{agent['id']}/wakeups/{wakeup['id']}/cancel").status_code == 403
        assert api.post(f"/api/agents/{agent['id']}/wake").status_code == 403


# Routines -----------------------------------------------------------------------------


def create_routine(api: TestClient, agent: dict[str, Any], **extra: Any):
    body = {
        "agent_id": agent["id"],
        "name": "Manhã",
        "instruction": "Veja o Sentry.",
        "schedules": [{"days": "12345", "time": "08:30"}],
        **extra,
    }
    return api.post("/api/routines", json=body)


def test_routine_crud_and_run_now(api, project, agent):
    created = create_routine(api, agent, project_id=project["id"])
    assert created.status_code == 201, created.text
    routine = created.json()
    assert routine["name"] == "Manhã" and routine["enabled"] is True
    assert routine["project_id"] == project["id"] and routine["agent_id"] == agent["id"]
    assert [(s["days"], s["time"]) for s in routine["schedules"]] == [("12345", "08:30")]
    assert api.get("/api/routines").json() == [routine]
    assert api.get(f"/api/routines?project_id={project['id']}").json() == [routine]
    assert api.get("/api/routines?project_id=999").json() == []

    updated = api.patch(
        f"/api/routines/{routine['id']}",
        json={"name": "Tarde", "instruction": "Outra", "enabled": False,
              "schedules": [{"days": "71", "time": "17:00"}, {"days": "1", "time": "09:00"}]},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "Tarde" and body["instruction"] == "Outra" and body["enabled"] is False
    assert [(s["days"], s["time"]) for s in body["schedules"]] == [("17", "17:00"), ("1", "09:00")]

    run = api.post(f"/api/routines/{routine['id']}/run")
    assert run.status_code == 202, run.text
    assert run.json()["source"] == "manual" and run.json()["routine_id"] == routine["id"]
    [pending] = api.get(f"/api/agents/{agent['id']}/wakeups").json()
    assert "Outra" in pending["text"] and "Tarde" in pending["text"]

    assert api.delete(f"/api/routines/{routine['id']}").status_code == 204
    assert api.get("/api/routines").json() == []
    assert api.delete(f"/api/routines/{routine['id']}").status_code == 404
    assert api.post(f"/api/routines/{routine['id']}/run").status_code == 404


def test_routine_without_project_id_takes_the_one_of_the_agent(api, project, agent):
    assert create_routine(api, agent).json()["project_id"] == project["id"]


def test_routine_of_another_project_is_422(api, project, agent, home):
    other = make_project(api, home, "outro")
    response = create_routine(api, agent, project_id=other["id"])
    assert response.status_code == 422
    assert "mesmo" in response.json()["detail"]
    assert api.get("/api/routines").json() == []


def test_routine_of_an_unknown_agent_is_404(api):
    assert api.post(
        "/api/routines", json={"agent_id": 999, "name": "x", "instruction": "y"}
    ).status_code == 404


@pytest.mark.parametrize(
    "extra",
    [
        {"name": ""},
        {"name": "x" * 81},
        {"instruction": ""},
        {"instruction": "x" * 5001},
        {"schedules": [{"days": "8", "time": "08:00"}]},
        {"schedules": [{"days": "", "time": "08:00"}]},
        {"schedules": [{"days": "1", "time": "25:00"}]},
        {"schedules": [{"days": "1", "time": "8:00"}]},
        {"schedules": [{"days": "12", "time": "08:00"}, {"days": "2", "time": "08:00"}]},
        {"schedules": [{"days": "1", "time": "08:00"}] * 51},
        {"enabled": "talvez"},
        {"extra": 1},
    ],
)
def test_routine_refuses_invalid_bodies(api, agent, extra):
    assert create_routine(api, agent, **extra).status_code == 422
    assert api.get("/api/routines").json() == []


def test_routine_patch_is_all_or_nothing_and_checks_fields(api, agent):
    routine = create_routine(api, agent).json()
    url = f"/api/routines/{routine['id']}"
    bad = api.patch(url, json={"name": "Novo", "schedules": [{"days": "9", "time": "08:00"}]})
    assert bad.status_code == 422
    assert api.patch(url, json={"instruction": ""}).status_code == 422
    assert api.patch(url, json={"name": None}).status_code == 422
    assert api.patch(url, json={"agent_id": 2}).status_code == 422
    assert api.patch("/api/routines/999", json={"name": "x"}).status_code == 404
    assert api.get("/api/routines").json() == [routine]


def test_routine_patch_empty_keeps_the_schedules(api, agent):
    routine = create_routine(api, agent).json()
    assert api.patch(f"/api/routines/{routine['id']}", json={}).json() == routine


def test_routine_run_of_a_disabled_agent_is_409(api, agent):
    routine = create_routine(api, agent).json()
    patch(api, agent["id"], enabled=False)
    response = api.post(f"/api/routines/{routine['id']}/run")
    assert response.status_code == 409 and response.json()["detail"] == "O agente está desligado."


def test_routines_follow_the_agent_when_it_is_deleted(api, agent):
    create_routine(api, agent)
    api.delete(f"/api/agents/{agent['id']}")
    assert api.get("/api/routines").json() == []


# Notices -----------------------------------------------------------------------------


def test_notices_list_and_mark_read(api, agent, events):
    with conn_of(api) as conn, db.transaction(conn):
        first = store.add_notice(
            conn, agent_id=agent["id"], run_id=None, kind="alert", text="a", now=1
        )
        second = store.add_notice(
            conn, agent_id=agent["id"], run_id=None, kind="summary", text="b", now=2
        )
    assert [n["id"] for n in api.get("/api/agent-notices").json()] == [second.id, first.id]
    events.clear()

    response = api.post("/api/agent-notices/read", json={"ids": [first.id, first.id, 999]})

    assert response.json() == {"updated": 1}
    assert [n["id"] for n in api.get("/api/agent-notices", params={"unread": True}).json()] == [
        second.id
    ]
    assert any(
        e["type"] == "agent.notice" and e["data"] == {"read_ids": [first.id]} for e in events
    )
    events.clear()
    assert api.post("/api/agent-notices/read", json={"ids": [first.id]}).json() == {"updated": 0}
    assert events == []
    assert api.post("/api/agent-notices/read", json={"ids": ["a"]}).status_code == 422
    assert api.post("/api/agent-notices/read", json={"ids": [1] * 501}).status_code == 422


# GitHub -----------------------------------------------------------------------------


def test_github_settings_never_return_the_secret(api):
    secret = "segredo-do-webhook-1234"
    assert api.get("/api/agents-github").json() == {
        "login": None, "secret_set": False, "hooks_port": None, "queued": 0,
    }

    response = api.put("/api/agents-github", json={"login": "vini7", "secret": secret})

    assert response.status_code == 200
    assert response.json()["login"] == "vini7" and response.json()["secret_set"] is True
    assert secret not in response.text and secret not in api.get("/api/agents-github").text
    path = api.app.state.settings.data_dir / "github-webhook.secret"
    assert path.read_text() == secret and path.stat().st_mode & 0o777 == 0o600
    # One field at a time.
    assert api.put("/api/agents-github", json={"login": "outro"}).json()["login"] == "outro"
    assert path.read_text() == secret


@pytest.mark.parametrize(
    "body",
    [{}, {"login": ""}, {"login": "a b"}, {"login": "x" * 40}, {"secret": "curto"},
     {"secret": " " + "x" * 20}, {"secret": "x" * 257}, {"outro": "x"}, ["x"]],
)
def test_github_settings_refuse_bad_bodies(api, body):
    response = api.put("/api/agents-github", json=body)
    assert response.status_code == 422
    assert api.get("/api/agents-github").json()["login"] is None
    assert not (api.app.state.settings.data_dir / "github-webhook.secret").exists()


def test_github_counts_the_queued_comments(api, agent):
    with conn_of(api) as conn, db.transaction(conn):
        for number, status in ((1, "queued"), (2, "queued"), (3, "delivered")):
            store.insert_comment(
                conn,
                store.PrComment(
                    comment_id=f"issue:{number}", pr_url="https://github.com/o/r/pull/1",
                    agent_id=agent["id"], author="vini7", body="ajuste", path=None, line=None,
                    html_url="https://github.com/o/r/pull/1#x", created_at=number,
                    received_at=number, status=status, batch_at=None,
                ),
            )
    assert api.get("/api/agents-github").json()["queued"] == 2


# Wiring ---------------------------------------------------------------------------------


def test_every_route_needs_the_maestro_header(api, agent):
    routes = [
        ("get", "/api/agents"),
        ("get", f"/api/agents/{agent['id']}/definition"),
        ("get", f"/api/agents/{agent['id']}/secrets"),
        ("get", "/api/routines"),
        ("get", "/api/agent-notices"),
        ("get", "/api/agents-github"),
    ]
    with without_header(api, "x-maestro"):
        for method, url in routes:
            assert getattr(api, method)(url).status_code == 403, url


def test_routes_refuse_a_foreign_origin(api, agent):
    response = api.post(
        f"/api/agents/{agent['id']}/wake", headers={"origin": "http://evil.example"}
    )
    assert response.status_code == 403

