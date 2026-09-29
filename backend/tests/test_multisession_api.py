"""Marco 2 routes: project removal, session listing and PATCH, seen, app state."""

import pytest
from fastapi.testclient import TestClient

from test_sessions_api import (
    APP_ORIGIN,
    BACKEND_URL,
    make_project,
    receive,
    wait_state,
)
from vibing.agent.fake import FakeAgentFactory, text_turn, tool_turn
from vibing.app import create_app
from vibing.config import Settings


class RenameSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, session_id: str, title: str, directory: str) -> None:
        self.calls.append((session_id, title, directory))


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory()


@pytest.fixture
def rename() -> RenameSpy:
    return RenameSpy()


@pytest.fixture
def api(factory, rename, home, data_dir):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir),
        agent_factory=factory,
        history_exists=history_exists,
        rename_session=rename,
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as c:
        yield c


def new_session(api: TestClient, project: dict) -> dict:
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return response.json()


# Project removal -----------------------------------------------------------


def test_delete_project_with_pending_permission(api, home, factory):
    factory.script = lambda content: tool_turn("x", ask_permission=True)
    project = make_project(api, home)
    session = new_session(api, project)
    sid = session["session_id"]
    api.post(f"/api/sessions/{sid}/messages", json={"text": "escreva"})
    wait_state(api, sid, "awaiting_decision")

    assert api.delete(f"/api/projects/{project['id']}").status_code == 204

    assert factory.clients[0].closed
    assert api.get(f"/api/sessions/{sid}").status_code == 404
    assert api.get("/api/sessions").json() == []


def test_delete_unknown_project(api):
    assert api.delete("/api/projects/999").status_code == 404


# Session fields and listing ------------------------------------------------


def test_created_session_has_new_fields(api, home):
    project = make_project(api, home)
    body = new_session(api, project)
    assert body["seq"] == 0
    assert body["finished"] is False
    assert body["unread"] is False
    assert body["awaiting_decision"] is False
    assert body["display_state"] == "waiting"
    assert "last_seen_at" in body


def test_project_listing_has_seq(api, home, factory):
    factory.script = lambda content: text_turn("x", "ok")
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
    snapshot = wait_state(api, sid, "idle")

    [listed] = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed["seq"] == snapshot["seq"] > 0
    assert snapshot["display_state"] == "waiting"


def test_list_all_sessions_with_filters(api, home):
    one = make_project(api, home, "one")
    two = make_project(api, home, "two")
    a = new_session(api, one)["session_id"]
    b = new_session(api, two)["session_id"]
    api.patch(f"/api/sessions/{b}", json={"finished": True})

    ids = lambda r: sorted(s["session_id"] for s in r.json())  # noqa: E731
    assert ids(api.get("/api/sessions")) == sorted([a, b])
    assert ids(api.get("/api/sessions", params={"project_id": one["id"]})) == [a]
    assert ids(api.get("/api/sessions", params={"state": "finished"})) == [b]
    assert ids(api.get("/api/sessions", params={"state": "waiting"})) == [a]
    assert ids(api.get("/api/sessions", params={"state": "running"})) == []
    assert api.get("/api/sessions", params={"state": "bogus"}).status_code == 422


# PATCH and seen ------------------------------------------------------------


def test_patch_finish_emits_session_updated(api, home):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    with api.websocket_connect("ws://127.0.0.1:6660/ws", headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as ws:
        response = api.patch(f"/api/sessions/{sid}", json={"finished": True})
        event = receive(ws)

    assert response.status_code == 200
    assert response.json()["display_state"] == "finished"
    assert event["type"] == "session.updated"
    assert event["session_id"] == sid
    assert event["data"] == response.json()


def test_patch_title(api, home, rename):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]

    response = api.patch(f"/api/sessions/{sid}", json={"title": "  Refatorar  "})

    assert response.json()["title"] == "Refatorar"
    assert rename.calls == []  # no history on disk yet
    [listed] = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed["title"] == "Refatorar"


def test_patch_title_with_history_calls_sdk(api, home, factory, rename):
    factory.script = lambda content: text_turn("x", "ok")
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
    wait_state(api, sid, "idle")

    api.patch(f"/api/sessions/{sid}", json={"title": "Novo"})

    assert rename.calls == [(sid, "Novo", project["path"])]


@pytest.mark.parametrize(
    "body", [{"title": ""}, {"title": "   "}, {"title": "x" * 201}, {"other": 1}]
)
def test_patch_invalid(api, home, body):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    assert api.patch(f"/api/sessions/{sid}", json=body).status_code == 422


def test_patch_unknown_session(api):
    missing = "00000000-0000-0000-0000-000000000000"
    assert api.patch(f"/api/sessions/{missing}", json={"finished": True}).status_code == 404
    assert api.post(f"/api/sessions/{missing}/seen").status_code == 404


def test_seen(api, home):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]

    response = api.post(f"/api/sessions/{sid}/seen")

    assert response.status_code == 200
    assert response.json()["unread"] is False
    assert response.json()["last_seen_at"] > 0


# App state -----------------------------------------------------------------


def test_app_state_roundtrip(api):
    assert api.get("/api/state").json() == {}
    layout = {"columns": [{"session_id": "a", "width": 480}]}

    assert api.put("/api/state/layout", json=layout).status_code == 200
    assert api.put("/api/state/preferences", json={"finished_after_days": 5}).status_code == 200

    assert api.get("/api/state").json() == {
        "layout": layout,
        "preferences": {"finished_after_days": 5},
    }


def test_app_state_rejects_unknown_key(api):
    assert api.put("/api/state/secret", json={}).status_code == 404


def test_app_state_rejects_large_body(api):
    big = {"x": "a" * (64 * 1024)}
    assert api.put("/api/state/layout", json=big).status_code == 413
    assert api.get("/api/state").json() == {}


def test_app_state_rejects_invalid_json(api):
    response = api.put(
        "/api/state/layout", content=b"{nope", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


def test_preferences_change_finished_after_days(api, home, data_dir):
    import time
    from contextlib import closing

    from vibing import db

    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    two_days_ago = int(time.time()) - 2 * 86_400
    with closing(db.connect(data_dir / "vibing.db")) as conn:
        conn.execute(
            "UPDATE sessions SET last_activity_at = ?, last_seen_at = ? WHERE session_id = ?",
            (two_days_ago, two_days_ago, sid),
        )
    assert api.get("/api/sessions").json()[0]["display_state"] == "waiting"

    api.put("/api/state/preferences", json={"finished_after_days": 1})

    assert api.get("/api/sessions").json()[0]["display_state"] == "finished"



# Idle sweep in the lifespan ------------------------------------------------


def test_lifespan_sweep_closes_idle_session(factory, home, data_dir):
    import time

    settings = Settings(
        home_dir=home, data_dir=data_dir,
        idle_timeout_seconds=0.05, idle_sweep_interval_seconds=0.01,
    )
    factory.script = lambda content: text_turn("x", "ok")
    app = create_app(settings=settings, agent_factory=factory, history_exists=lambda s, c: False)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as api:
        project = make_project(api, home)
        sid = new_session(api, project)["session_id"]
        api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
        wait_state(api, sid, "closed")
        assert factory.clients[0].closed

        api.post(f"/api/sessions/{sid}/messages", json={"text": "de novo"})
        deadline = time.monotonic() + 2
        while len(factory.clients) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert factory.clients[1].options.resume is True
