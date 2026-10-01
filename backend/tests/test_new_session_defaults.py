"""Preferences for new sessions: model, effort and mode."""

from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibing import db
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"


@contextmanager
def client(monkeypatch: pytest.MonkeyPatch, cli_mode: str | None):
    # `SessionManager.__init__` reads `user_default_permission_mode` at construction,
    # so the patch has to come before `create_app`.
    monkeypatch.setattr("vibing.sessions.user_default_permission_mode", lambda: cli_mode)
    app = create_app(agent_factory=FakeAgentFactory(), history_exists=lambda sid, cwd: False)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as c:
        yield c


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):
    with client(monkeypatch, None) as c:
        yield c


def project(api: TestClient, home: Path) -> int:
    (home / "app").mkdir()
    r = api.post("/api/projects", json={"name": "app", "path": str(home / "app"), "color": "#ff8800"})
    return r.json()["id"]


def create(api: TestClient, pid: int) -> dict:
    r = api.post(f"/api/projects/{pid}/sessions")
    assert r.status_code == 201
    return r.json()


def write_raw_preferences(api: TestClient, raw: str) -> None:
    """Writes the row behind the validation, as an old or damaged database could hold it."""
    with closing(db.connect(api.app.state.settings.db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES ('preferences', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (raw,),
        )


def test_new_sessions_use_the_saved_defaults(api, home):
    pid = project(api, home)
    r = api.put("/api/state/preferences", json={
        "new_session_model": "opus", "new_session_effort": "high", "new_session_mode": "acceptEdits",
    })
    assert r.status_code == 200
    s = create(api, pid)
    assert (s["model"], s["effort"], s["permission_mode"]) == ("opus", "high", "acceptEdits")
    # Kept on the record, not only in the reply.
    again = api.get(f"/api/sessions/{s['session_id']}").json()
    assert (again["model"], again["effort"], again["permission_mode"]) == ("opus", "high", "acceptEdits")


def test_without_defaults_sessions_start_as_before(monkeypatch, home):
    with client(monkeypatch, "plan") as api:
        s = create(api, project(api, home))
    assert (s["model"], s["effort"], s["permission_mode"]) == (None, None, "plan")


def test_saved_mode_wins_over_the_cli_default(monkeypatch, home):
    with client(monkeypatch, "plan") as api:
        pid = project(api, home)
        api.put("/api/state/preferences", json={"new_session_mode": "acceptEdits"})
        assert create(api, pid)["permission_mode"] == "acceptEdits"


def test_null_mode_falls_back_to_the_cli_default(monkeypatch, home):
    with client(monkeypatch, "plan") as api:
        pid = project(api, home)
        api.put("/api/state/preferences", json={"new_session_mode": None})
        assert create(api, pid)["permission_mode"] == "plan"


@pytest.mark.parametrize("raw", [
    "{not json",
    "[]",
    '{"new_session_model": 7, "new_session_effort": ["high"], "new_session_mode": {}}',
    '{"new_session_model": "", "new_session_effort": "turbo", "new_session_mode": "bypassPermissions"}',
])
def test_unreadable_preferences_are_ignored(monkeypatch, home, raw):
    with client(monkeypatch, "plan") as api:
        pid = project(api, home)
        write_raw_preferences(api, raw)
        s = create(api, pid)
    assert (s["model"], s["effort"], s["permission_mode"]) == (None, None, "plan")


def test_valid_keys_survive_invalid_neighbours(api, home):
    pid = project(api, home)
    write_raw_preferences(api, '{"new_session_model": "opus", "new_session_effort": "turbo"}')
    s = create(api, pid)
    assert (s["model"], s["effort"]) == ("opus", None)


@pytest.mark.parametrize("body", [
    {"new_session_model": ""},
    {"new_session_model": "   "},
    {"new_session_model": "x" * 101},
    {"new_session_model": 7},
    {"new_session_effort": "turbo"},
    {"new_session_effort": 3},
    {"new_session_mode": "bypassPermissions"},
    {"new_session_mode": "qualquer"},
])
def test_invalid_defaults_are_refused(api, body):
    assert api.put("/api/state/preferences", json=body).status_code == 400


def test_null_defaults_are_accepted(api):
    body = {"new_session_model": None, "new_session_effort": None, "new_session_mode": None}
    assert api.put("/api/state/preferences", json=body).status_code == 200
