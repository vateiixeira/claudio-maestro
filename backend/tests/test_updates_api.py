from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.app import create_app
from claudio_maestro.config import Settings, load_settings
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
