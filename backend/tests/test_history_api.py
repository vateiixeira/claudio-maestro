"""History routes: sync, search, hidden sessions per project, old session snapshot."""

import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from history_fakes import FakeHistory, assistant_entry, info, user_entry

from vibing import db
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app
from vibing.config import Settings

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"


@pytest.fixture
def fake() -> FakeHistory:
    return FakeHistory()


@pytest.fixture
def api(fake: FakeHistory, home: Path, data_dir: Path):
    settings = Settings(home_dir=home, data_dir=data_dir, history_sync_interval_seconds=3600)
    app = create_app(
        settings=settings,
        agent_factory=FakeAgentFactory(),
        history_exists=lambda sid, cwd: sid in fake.messages,
        rename_session=fake.rename_session,
        list_sessions=fake.list_sessions,
        get_session_messages=fake.get_session_messages,
        read_tool_results=fake.read_tool_results,
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as c:
        yield c


def make_project(api: TestClient, home: Path, name: str = "app") -> dict[str, Any]:
    folder = home / name
    folder.mkdir(exist_ok=True)
    response = api.post(
        "/api/projects", json={"name": name, "path": str(folder), "color": "#ff8800"}
    )
    assert response.status_code == 201
    return response.json()


def test_creating_project_syncs_its_history(api, fake, home):
    folder = home / "app"
    folder.mkdir()
    fake.add(str(folder), info("s1", str(folder), summary="Do CLI"))

    with api.websocket_connect("ws://127.0.0.1:6660/ws", headers={"origin": APP_ORIGIN}) as ws:
        project = make_project(api, home)
        event = ws.receive_json()
        while event["type"] != "project.synced":
            event = ws.receive_json()
        assert event["data"] == {"project_id": project["id"]}

    sessions = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert [s["title"] for s in sessions] == ["Do CLI"]
    assert sessions[0]["unread"] is False


def test_sync_route(api, fake, home):
    project = make_project(api, home)
    fake.add(project["path"], info("s1", project["path"], summary="Nova"))

    response = api.post(f"/api/projects/{project['id']}/sync")

    assert response.status_code == 200
    assert [s["session_id"] for s in response.json()] == ["s1"]
    assert api.post("/api/projects/999/sync").status_code == 404


def test_sync_runs_at_startup(fake, home, data_dir):
    folder = home / "app"
    folder.mkdir()
    db.init_db(data_dir / "vibing.db")
    with closing(db.connect(data_dir / "vibing.db")) as conn:
        conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES ('app', ?, '#ff8800', 0, 0)",
            (str(folder),),
        )
    fake.add(str(folder), info("s1", str(folder), summary="x"))
    settings = Settings(home_dir=home, data_dir=data_dir, history_sync_interval_seconds=3600)
    app = create_app(settings=settings, list_sessions=fake.list_sessions,
                     get_session_messages=fake.get_session_messages)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as c:
        deadline = time.monotonic() + 2
        while not c.get("/api/sessions").json():
            assert time.monotonic() < deadline
            time.sleep(0.01)


def test_old_session_snapshot(api, fake, home):
    project = make_project(api, home)
    fake.add(project["path"], info("s1", project["path"], summary="Antiga"))
    fake.messages["s1"] = [
        user_entry("oi"),
        assistant_entry({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}, "m1"),
    ]
    api.post(f"/api/projects/{project['id']}/sync")

    snapshot = api.get("/api/sessions/s1").json()

    assert [i["type"] for i in snapshot["items"]] == ["user", "tool"]
    assert snapshot["items"][1]["streaming"] is False
    assert snapshot["history_truncated"] is False
    assert snapshot["external_activity"] is False


def test_search_ignores_case_and_accents(api, fake, home):
    project = make_project(api, home)
    path = project["path"]
    fake.add(
        path,
        info("s1", path, summary="Configuração do banco", modified_ms=1_000_000_000_000),
        info("s2", path, summary="Outra", first_prompt="ajustar AÇÃO do botão",
             modified_ms=2_000_000_000_000),
        info("s3", path, summary="Nada a ver"),
    )
    api.post(f"/api/projects/{project['id']}/sync")
    with closing(db.connect(home.parent / "data" / "vibing.db")) as conn:
        conn.execute("UPDATE sessions SET finished = 1 WHERE session_id = 's1'")

    found = api.get("/api/sessions/search", params={"q": "CONFIGURACAO"}).json()
    assert [s["session_id"] for s in found] == ["s1"]

    found = api.get("/api/sessions/search", params={"q": "BOTAO"}).json()
    assert [s["session_id"] for s in found] == ["s2"]

    found = api.get("/api/sessions/search", params={"q": "o", "limit": 1}).json()
    assert [s["session_id"] for s in found] == ["s2"]  # newest first

    assert api.get("/api/sessions/search", params={"q": " "}).json() == []


def test_projects_count_hidden_sessions(api, fake, home):
    project = make_project(api, home)
    path = project["path"]
    old = int((time.time() - 10 * 86_400) * 1000)
    fake.add(
        path,
        info("old", path, summary="velha", modified_ms=old),
        info("old-marked", path, summary="marcada", modified_ms=old),
        info("new", path, summary="nova", modified_ms=int(time.time() * 1000)),
    )
    api.post(f"/api/projects/{project['id']}/sync")
    api.patch("/api/sessions/old-marked", json={"finished": True})

    listed = api.get("/api/projects").json()

    assert listed[0]["hidden_sessions"] == 1
