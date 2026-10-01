"""Routes of the digest agent."""

import time
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.digest import store
from claudio_maestro.digest.model import FakeDigestModel
from claudio_maestro.digest.store import Digest


@pytest.fixture
def model() -> FakeDigestModel:
    return FakeDigestModel()


@pytest.fixture
def api(model: FakeDigestModel):
    app = create_app(agent_factory=FakeAgentFactory(), digest_model=model)
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        yield client


def new_session(api: TestClient, home: Path) -> str:
    project = make_project(api, home)
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def test_config_defaults(api: TestClient) -> None:
    body = api.get("/api/digest/config").json()
    assert body["config"]["enabled"] is False and body["config"]["model"] == "sonnet"
    assert body["status"] == {"enabled": False, "running": False, "next_run_at": None,
                              "paused_until": None}


def test_put_config(api: TestClient) -> None:
    config = api.get("/api/digest/config").json()["config"]
    response = api.put("/api/digest/config", json={**config, "enabled": True, "window_days": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["window_days"] == 5 and body["status"]["enabled"] is True
    assert body["status"]["next_run_at"] is not None
    assert api.get("/api/digest/config").json()["config"]["window_days"] == 5


def test_put_config_rejects_bad_fields(api: TestClient) -> None:
    response = api.put("/api/digest/config", json={"window_days": 0})
    assert response.status_code == 422
    assert response.json()["detail"] == "A janela precisa ser um número inteiro de 1 a 30 dias."


def test_run_and_runs(api: TestClient) -> None:
    assert api.post("/api/digest/run").status_code == 202
    deadline = time.time() + 2
    while not api.get("/api/digest/runs").json() and time.time() < deadline:
        time.sleep(0.01)
    runs = api.get("/api/digest/runs").json()
    assert runs and runs[0]["trigger"] == "manual_all"


def test_session_digest_routes(api: TestClient, home: Path) -> None:
    sid = new_session(api, home)
    assert api.get(f"/api/sessions/{sid}/digest").json() is None
    settings = api.app.state.settings
    with closing(db.connect(settings.db_path)) as conn:
        store.save_digest(conn, Digest(sid, short="Faz X", cursor="u1"))
    body = api.get(f"/api/sessions/{sid}/digest").json()
    assert body["short"] == "Faz X" and "cursor" not in body
    assert api.post(f"/api/sessions/{sid}/digest").json() == {"queued": True}
    assert api.get("/api/sessions/nope/digest").status_code == 404
    assert api.post("/api/sessions/nope/digest").status_code == 404


def test_routes_need_the_app_header(api: TestClient) -> None:
    response = api.get("/api/digest/config", headers={"x-maestro": ""})
    assert response.status_code == 403


def test_put_needs_the_app_origin(api: TestClient) -> None:
    response = api.put("/api/digest/config", json={}, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
