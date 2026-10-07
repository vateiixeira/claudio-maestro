"""Routes of "Entregas"."""

import time
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from claudio_maestro import db, deliveries
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.digest.model import FakeDigestModel


@pytest.fixture
def api():
    app = create_app(agent_factory=FakeAgentFactory(), digest_model=FakeDigestModel([]))
    with TestClient(app, base_url=BACKEND_URL,
                    headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        yield client


def new_session(api: TestClient, project: dict) -> str:
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def seed(api, *, session_id, project_id, name, title, when, status="title_only"):
    with closing(db.connect(api.app.state.settings.db_path)) as conn:
        return deliveries.record_finish(conn, session_id=session_id, project_id=project_id,
                                        project_name=name, title=title, finished_at=when,
                                        to_cursor=None, status=status)


def test_get_day(api, home: Path, monkeypatch) -> None:
    project = make_project(api, home)
    sid = new_session(api, project)
    now = int(time.time())
    d = seed(api, session_id=sid, project_id=project["id"], name=project["name"],
             title="Feita", when=now)
    open_sid = new_session(api, project)
    monkeypatch.setattr(api.app.state.activity, "sessions_on", lambda day: {sid, open_sid})
    body = api.get(f"/api/deliveries?date={date.today().isoformat()}").json()
    assert body["date"] == date.today().isoformat() and body["agent_enabled"] is False
    assert [x["id"] for x in body["deliveries"]] == [d.id]
    # a session delivered that day is not "in progress"
    assert [x["session_id"] for x in body["in_progress"]] == [open_sid]
    assert set(body["in_progress"][0]) == {"session_id", "project_id", "project_name", "title", "short"}


def test_get_defaults_to_today(api) -> None:
    assert api.get("/api/deliveries").json()["date"] == date.today().isoformat()


@pytest.mark.parametrize("bad", ["2026-13-01", "ontem", "2026-1-1", "20261007"])
def test_get_rejects_bad_dates(api, bad) -> None:
    assert api.get(f"/api/deliveries?date={bad}").status_code == 422


def test_summarize_errors(api, home: Path) -> None:
    assert api.post("/api/deliveries/999/summarize").status_code == 404
    project = make_project(api, home)
    sid = new_session(api, project)
    d = seed(api, session_id=sid, project_id=project["id"], name="p", title="t",
             when=int(time.time()))
    response = api.post(f"/api/deliveries/{d.id}/summarize")
    assert response.status_code == 409
    assert response.json()["detail"] == "O agente de resumos está desligado."


def test_requires_the_maestro_header(api) -> None:
    assert api.get("/api/deliveries", headers={"x-maestro": ""}).status_code == 403
    assert api.post("/api/deliveries/1/summarize", headers={"x-maestro": ""}).status_code == 403
