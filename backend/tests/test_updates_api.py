import pytest
from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.app import create_app
from claudio_maestro.config import Settings, load_settings
from claudio_maestro.runmode import RunMode
from claudio_maestro.selfupdate import Eligibility, UpdateBusy, UpdateNotAllowed
from claudio_maestro.updates import RELEASES_URL, ReleaseInfo

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}


def _client(home, data_dir, *, enabled, fetch):
    settings = Settings(
        home_dir=home, data_dir=data_dir, update_check=enabled, update_check_delay_seconds=3600
    )
    return TestClient(
        create_app(settings=settings, fetch_release=fetch), base_url=BACKEND_URL, headers=HEADERS
    )


def test_updates_endpoint_reports_new_release(home, data_dir):
    release = ReleaseInfo("999.0.0", f"{RELEASES_URL}/tag/v999.0.0", "notas", 1791288000.0)

    async def fetch():
        return release

    with _client(home, data_dir, enabled=True, fetch=fetch) as client:
        client.portal.call(client.app.state.updates.check)
        body = client.get("/api/updates").json()

    assert body["enabled"] is True
    assert body["available"] is True
    assert body["latest"] == {
        "version": "999.0.0",
        "url": f"{RELEASES_URL}/tag/v999.0.0",
        "notes": "notas",
        "published_at": 1791288000.0,
    }
    assert isinstance(body["checked_at"], float)
    assert body["releases_url"] == RELEASES_URL
    assert isinstance(body["current"], str) and body["current"]


def test_updates_endpoint_when_disabled(home, data_dir):
    async def fetch():
        raise AssertionError("não deveria consultar")

    with _client(home, data_dir, enabled=False, fetch=fetch) as client:
        client.portal.call(client.app.state.updates.check)
        body = client.get("/api/updates").json()

    assert body["enabled"] is False
    assert body["latest"] is None
    assert body["available"] is False


def test_updates_endpoint_requires_maestro_header(client):
    assert client.get("/api/updates", headers={"x-maestro": "0"}).status_code == 403


def test_load_settings_reads_update_check(monkeypatch):
    monkeypatch.setenv("MAESTRO_UPDATE_CHECK", "0")
    assert load_settings().update_check is False
    monkeypatch.setenv("MAESTRO_UPDATE_CHECK", "1")
    assert load_settings().update_check is True
    monkeypatch.delenv("MAESTRO_UPDATE_CHECK")
    assert load_settings().update_check is True


def test_settings_defaults():
    from pathlib import Path

    settings = Settings(home_dir=Path("/h"), data_dir=Path("/d"))
    assert settings.update_check is True
    assert settings.update_check_delay_seconds == 60
    assert settings.update_check_interval_seconds == 24 * 3600


class FakeAgentd:
    async def live_children(self):
        return []

    async def aclose(self):
        pass


class FakeUpdater:
    def __init__(self, eligibility=Eligibility(True, mode="pull", remote="origin"), error=None):
        self.eligibility = eligibility
        self.error = error
        self.applied: list[str] = []
        self.job = None

    async def check(self):
        return self.eligibility

    def job_state(self):
        return self.job

    async def apply(self, version):
        if self.error:
            raise self.error
        self.applied.append(version)
        self.job = {"state": "running", "step": "check", "rolling_back": False, "lines": [],
                    "error": None, "log_path": "/d/update.log"}


def _client_with(home, data_dir, updater, *, run_mode=RunMode("terminal"), release="999.0.0", agentd=False):
    settings = Settings(home_dir=home, data_dir=data_dir, update_check=True, update_check_delay_seconds=3600)

    async def fetch():
        return ReleaseInfo(release, f"{RELEASES_URL}/tag/v{release}", "notas", None)

    app = create_app(settings=settings, fetch_release=fetch, run_mode=run_mode,
                     agentd=agentd, refresh_models=False, self_updater=lambda **kw: updater)
    return TestClient(app, base_url=BACKEND_URL, headers=HEADERS)


def test_get_updates_reports_run_mode_and_self_update(home, data_dir):
    with _client_with(home, data_dir, FakeUpdater()) as client:
        body = client.get("/api/updates").json()
    assert body["run_mode"] == {"kind": "terminal", "unit": None, "kill_mode": None}
    assert body["self_update"] == {"can": True, "reason": None, "mode": "pull"}
    assert body["job"] is None
    assert body["last_result"] is None
    assert body["agentd"] == {"enabled": False, "live_children": None}
    assert body["live_sessions"] == 0


def test_get_updates_reports_last_result_once_per_process(home, data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "update-result.json").write_text('{"from": "0.1.0", "to": "0.2.0", "agentd_changed": true, "at": 1}')
    with _client_with(home, data_dir, FakeUpdater()) as client:
        first = client.get("/api/updates").json()["last_result"]
        second = client.get("/api/updates").json()["last_result"]
    assert first == second == {"from": "0.1.0", "to": "0.2.0", "agentd_changed": True, "at": 1.0}
    assert not (data_dir / "update-result.json").exists()


def test_apply_starts_the_announced_version(home, data_dir):
    updater = FakeUpdater()
    with _client_with(home, data_dir, updater) as client:
        client.portal.call(client.app.state.updates.check)
        response = client.post("/api/updates/apply", json={"version": "999.0.0"})
    assert response.status_code == 202
    assert response.json()["job"]["state"] == "running"
    assert updater.applied == ["999.0.0"]


def test_apply_refuses_a_version_not_announced(home, data_dir):
    updater = FakeUpdater()
    with _client_with(home, data_dir, updater) as client:
        client.portal.call(client.app.state.updates.check)
        response = client.post("/api/updates/apply", json={"version": "998.0.0"})
    assert response.status_code == 400
    assert updater.applied == []


def test_apply_refuses_before_any_check(home, data_dir):
    with _client_with(home, data_dir, FakeUpdater()) as client:
        assert client.post("/api/updates/apply", json={"version": "999.0.0"}).status_code == 400


@pytest.mark.parametrize("error", [UpdateNotAllowed("há arquivos alterados no clone"), UpdateBusy("já há")])
def test_apply_conflicts(home, data_dir, error):
    with _client_with(home, data_dir, FakeUpdater(error=error)) as client:
        client.portal.call(client.app.state.updates.check)
        response = client.post("/api/updates/apply", json={"version": "999.0.0"})
    assert response.status_code == 409
    assert response.json()["detail"] == str(error)


def test_apply_without_agentd_asks_to_confirm_live_sessions(home, data_dir, monkeypatch):
    updater = FakeUpdater()
    with _client_with(home, data_dir, updater) as client:
        client.portal.call(client.app.state.updates.check)
        monkeypatch.setattr(client.app.state.sessions, "live_count", lambda: 2)
        refused = client.post("/api/updates/apply", json={"version": "999.0.0"})
        accepted = client.post("/api/updates/apply", json={"version": "999.0.0", "confirm_sessions_drop": True})
    assert refused.status_code == 409 and "2 sessões" in refused.json()["detail"]
    assert accepted.status_code == 202


def test_apply_requires_origin(home, data_dir):
    with _client_with(home, data_dir, FakeUpdater()) as client:
        response = client.post("/api/updates/apply", json={"version": "999.0.0"},
                               headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_apply_asks_to_confirm_when_new_sessions_skip_the_agentd(home, data_dir, monkeypatch):
    # MAESTRO_AGENTD=0 (set by conftest): the client exists but no new session goes through it.
    with _client_with(home, data_dir, FakeUpdater(), agentd=True) as client:
        client.portal.call(client.app.state.updates.check)
        monkeypatch.setattr(client.app.state.sessions, "live_count", lambda: 2)
        assert client.app.state.agentd is not None
        body = client.get("/api/updates").json()
        refused = client.post("/api/updates/apply", json={"version": "999.0.0"})
    assert body["agentd"] == {"enabled": False, "live_children": None}
    assert refused.status_code == 409 and "2 sessões" in refused.json()["detail"]


def test_apply_does_not_ask_when_sessions_survive_the_restart(home, data_dir, monkeypatch):
    updater = FakeUpdater()
    with _client_with(home, data_dir, updater) as client:
        client.portal.call(client.app.state.updates.check)
        # A fake agentd (starting a real one would spawn a process): new sessions go through it.
        client.app.state.agentd = FakeAgentd()
        client.app.state.agentd_new_sessions = True
        monkeypatch.setattr(client.app.state.sessions, "live_count", lambda: 2)
        body = client.get("/api/updates").json()
        accepted = client.post("/api/updates/apply", json={"version": "999.0.0"})
    assert body["agentd"]["enabled"] is True
    assert accepted.status_code == 202
    assert updater.applied == ["999.0.0"]
