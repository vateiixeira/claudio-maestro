"""Routes of the closure check."""

from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.digest.closure_store import Closure, save_closure
from claudio_maestro.digest.model import FakeDigestModel

MESSAGE = "O item precisa ter de 1 a 200 caracteres."


@pytest.fixture
def api():
    app = create_app(agent_factory=FakeAgentFactory(), digest_model=FakeDigestModel())
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        yield client


@pytest.fixture
def sid(api: TestClient, home: Path) -> str:
    project = make_project(api, home)
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def seed(api: TestClient, sid: str, **fields) -> None:
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        last = conn.execute("SELECT last_activity_at FROM sessions WHERE session_id = ?",
                            (sid,)).fetchone()[0]
        save_closure(conn, Closure(sid, checked_at=last + 10, **fields))


def test_get_closure(api: TestClient, sid: str) -> None:
    assert api.get(f"/api/sessions/{sid}/closure").json() is None
    seed(api, sid, verdict="user_action", user_actions=["Reiniciar"])
    body = api.get(f"/api/sessions/{sid}/closure").json()
    assert (body["verdict"], body["user_actions"]) == ("user_action", ["Reiniciar"])
    assert api.get("/api/sessions/nope/closure").status_code == 404


def test_resolve(api: TestClient, sid: str) -> None:
    seed(api, sid, verdict="user_action", user_actions=["Reiniciar"])
    response = api.post(f"/api/sessions/{sid}/closure/resolve", json={"item": "Reiniciar"})
    assert response.status_code == 200
    assert response.json()["verdict"] == "can_close"
    again = api.post(f"/api/sessions/{sid}/closure/resolve", json={"item": "Reiniciar"})
    assert again.status_code == 404
    assert again.json()["detail"] == "Item não encontrado; a verificação foi atualizada."


def test_resolve_unknown_session(api: TestClient) -> None:
    response = api.post("/api/sessions/nope/closure/resolve", json={"item": "x"})
    assert response.status_code == 404


def test_resolve_validation(api: TestClient, sid: str) -> None:
    url = f"/api/sessions/{sid}/closure/resolve"
    bodies = ({"item": ""}, {"item": "   "}, {"item": "x" * 201}, {"item": 3}, {"item": None},
              {}, [], ["item"], "item", 7)
    for body in bodies:
        response = api.post(url, json=body)
        assert response.status_code == 422, body
        assert response.json()["detail"] == MESSAGE, body
    assert api.post(url, json={"item": "x" * 200}).status_code == 404  # valid, just unknown


def test_resolve_invalid_json(api: TestClient, sid: str) -> None:
    response = api.post(f"/api/sessions/{sid}/closure/resolve", content=b"{nope",
                        headers={"content-type": "application/json"})
    assert response.status_code == 400
    assert response.json()["detail"] == "JSON inválido."


def test_routes_need_the_app_header(api: TestClient, sid: str) -> None:
    assert api.get(f"/api/sessions/{sid}/closure", headers={"x-maestro": ""}).status_code == 403
    response = api.post(f"/api/sessions/{sid}/closure/resolve", json={"item": "x"},
                        headers={"x-maestro": ""})
    assert response.status_code == 403


def test_resolve_needs_the_app_origin(api: TestClient, sid: str) -> None:
    response = api.post(f"/api/sessions/{sid}/closure/resolve", json={"item": "x"},
                        headers={"origin": "https://evil.example"})
    assert response.status_code == 403
