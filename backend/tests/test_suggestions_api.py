"""Suggestion routes: commands and files of a session or project."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
MISSING = "00000000-0000-0000-0000-000000000000"
RAW = [
    {"name": "hello", "description": "Diz olá (project)", "argumentHint": "<nome>"},
    {"name": "clear", "description": "Limpa", "builtin": True},
]


def make_api(factory: FakeAgentFactory):
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: False)
    return TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"})


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory(server_info={"commands": RAW})


@pytest.fixture
def api(factory: FakeAgentFactory):
    with make_api(factory) as client:
        yield client


def make_project(api: TestClient, home: Path, name: str = "app") -> dict[str, Any]:
    folder = home / name
    folder.mkdir()
    response = api.post("/api/projects", json={"name": name, "path": str(folder), "color": "#ff8800"})
    assert response.status_code == 201
    return response.json()


def new_session(api: TestClient, project: dict[str, Any]) -> dict[str, Any]:
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return response.json()


EXPECTED = [{"name": "hello", "description": "Diz olá", "argument_hint": "<nome>"}]


def test_project_commands(api, home, factory):
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 200
    assert response.json() == EXPECTED
    assert factory.clients[-1].options.cwd == Path(project["path"]).resolve()


def test_session_commands_use_the_session_folder_without_opening_it(api, home, factory):
    project = make_project(api, home)
    session = new_session(api, project)
    before = len(factory.clients)
    response = api.get(f"/api/sessions/{session['session_id']}/commands")
    assert response.status_code == 200
    assert response.json() == EXPECTED
    # Only the throwaway catalog client was created, not a session client.
    assert len(factory.clients) == before + 1
    assert factory.clients[-1].options.session_id != session["session_id"]


def test_unknown_ids_are_404(api):
    assert api.get(f"/api/sessions/{MISSING}/commands").status_code == 404
    assert api.get("/api/projects/9999/commands").status_code == 404


def test_missing_folder_is_409(api, home):
    project = make_project(api, home)
    shutil.rmtree(project["path"])
    response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 409
    assert response.json()["detail"] == f"A pasta do projeto não existe mais: {project['path']}"


def test_catalog_failure_is_502_with_the_message(home):
    factory = FakeAgentFactory(connect_error=AgentError("CLI não encontrado."))
    with make_api(factory) as api:
        project = make_project(api, home)
        response = api.get(f"/api/projects/{project['id']}/commands")
    assert response.status_code == 502
    assert response.json()["detail"] == "CLI não encontrado."


def test_requests_without_the_app_header_are_refused(api, home):
    project = make_project(api, home)
    response = api.get(
        f"/api/projects/{project['id']}/commands", headers={"x-maestro": ""}
    )
    assert response.status_code == 403


def test_project_files(api, home):
    project = make_project(api, home)
    (Path(project["path"]) / "backend").mkdir()
    (Path(project["path"]) / "backend" / "fs.py").write_text("x")
    response = api.get(f"/api/projects/{project['id']}/files", params={"q": "fs"})
    assert response.status_code == 200
    assert response.json() == [{"path": "backend/fs.py", "name": "fs.py", "type": "file"}]


def test_session_files(api, home):
    project = make_project(api, home)
    (Path(project["path"]) / "a.py").write_text("x")
    session = new_session(api, project)
    response = api.get(f"/api/sessions/{session['session_id']}/files", params={"q": ""})
    assert response.status_code == 200
    assert [m["path"] for m in response.json()] == ["a.py"]


def test_files_query_longer_than_200_is_refused(api, home):
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/files", params={"q": "x" * 201})
    assert response.status_code == 422


def test_files_unknown_ids_and_missing_folder(api, home):
    assert api.get(f"/api/sessions/{MISSING}/files").status_code == 404
    project = make_project(api, home)
    shutil.rmtree(project["path"])
    assert api.get(f"/api/projects/{project['id']}/files").status_code == 409


def test_files_search_failure_is_502(api, home, monkeypatch):
    from claudio_maestro.filesearch import FileSearchError

    async def boom(self, folder, query):
        raise FileSearchError("Falha ao listar os arquivos: x")

    monkeypatch.setattr("claudio_maestro.filesearch.FileIndex.search", boom)
    project = make_project(api, home)
    response = api.get(f"/api/projects/{project['id']}/files")
    assert response.status_code == 502
    assert response.json()["detail"] == "Falha ao listar os arquivos: x"
