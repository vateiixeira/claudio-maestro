"""PATCH de marcações."""

import time

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings


@pytest.fixture
def api(home, data_dir):
    factory = FakeAgentFactory()
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=factory)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as c:
        yield c


def new_sid(api, home) -> str:
    project = make_project(api, home)
    return api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]


def test_patch_on_hold_with_date(api, home):
    sid = new_sid(api, home)
    until = int(time.time()) + 3600
    body = api.patch(f"/api/sessions/{sid}", json={"mark": "on_hold", "mark_until": until}).json()
    assert body["mark"] == "on_hold" and body["mark_until"] == until


def test_patch_priority(api, home):
    sid = new_sid(api, home)
    assert api.patch(f"/api/sessions/{sid}", json={"priority": True}).json()["priority"] is True


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"mark": "other"}, "Marcação inválida."),
        ({"mark": "review", "mark_note": "x"}, "A nota só vale para sessões bloqueadas."),
        ({"mark": "on_hold", "mark_until": 1}, "Escolha uma data no futuro, em até um ano."),
        ({"mark": "blocked", "mark_note": "x" * 81}, "A nota pode ter até 80 caracteres."),
        ({"mark": "blocked", "mark_note": "x" * 500}, "A nota pode ter até 80 caracteres."),
    ],
)
def test_patch_rejects_invalid_marks_in_portuguese(api, home, body, message):
    sid = new_sid(api, home)
    response = api.patch(f"/api/sessions/{sid}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"] == message


def test_patch_trims_the_note_before_the_limit(api, home):
    sid = new_sid(api, home)
    note = "  " + "x" * 80 + "  "
    body = api.patch(f"/api/sessions/{sid}", json={"mark": "blocked", "mark_note": note}).json()
    assert body["mark_note"] == "x" * 80


def test_patch_removes_mark_with_null(api, home):
    sid = new_sid(api, home)
    api.patch(f"/api/sessions/{sid}", json={"mark": "review"})
    assert api.patch(f"/api/sessions/{sid}", json={"mark": None}).json()["mark"] is None


def test_patch_discarded_then_clear(api, home):
    sid = new_sid(api, home)
    body = api.patch(f"/api/sessions/{sid}", json={"mark": "discarded"}).json()
    assert body["mark"] == "discarded" and body["mark_note"] is None and body["mark_until"] is None
    assert body["finished"] is False
    assert api.patch(f"/api/sessions/{sid}", json={"mark": None}).json()["mark"] is None


def test_discarding_a_finished_session_keeps_it_finished(api, home):
    sid = new_sid(api, home)
    assert api.patch(f"/api/sessions/{sid}", json={"finished": True}).json()["finished"] is True
    body = api.patch(f"/api/sessions/{sid}", json={"mark": "discarded"}).json()
    assert body["mark"] == "discarded" and body["finished"] is True and body["display_state"] == "finished"
    body = api.patch(f"/api/sessions/{sid}", json={"mark": None}).json()
    assert body["mark"] is None and body["finished"] is True


def test_discarded_session_is_out_of_search(api, home):
    sid = new_sid(api, home)
    api.patch(f"/api/sessions/{sid}", json={"title": "Procurada sumida"})
    assert [s["session_id"] for s in api.get("/api/sessions/search?q=sumida").json()] == [sid]
    api.patch(f"/api/sessions/{sid}", json={"mark": "discarded"})
    assert api.get("/api/sessions/search?q=sumida").json() == []
