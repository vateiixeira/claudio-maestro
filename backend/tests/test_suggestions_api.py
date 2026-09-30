"""Suggestion routes: commands and files of a session or project."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vibing.agent.base import AgentError
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
MISSING = "00000000-0000-0000-0000-000000000000"
RAW = [
    {"name": "hello", "description": "Diz olá (project)", "argumentHint": "<nome>"},
    {"name": "clear", "description": "Limpa", "builtin": True},
]


def make_api(factory: FakeAgentFactory):
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: False)
    return TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"})


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
        f"/api/projects/{project['id']}/commands", headers={"x-vibing": ""}
    )
    assert response.status_code == 403
