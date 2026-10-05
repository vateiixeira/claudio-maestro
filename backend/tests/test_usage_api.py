import asyncio

from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.app import create_app
from claudio_maestro.config import Settings, load_settings
from claudio_maestro.usage import UsageLimit, UsageReport

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}
LIMIT = UsageLimit("session", "Sessão", 14, "normal", 1791333000.0)


def _client(home, data_dir, *, enabled, fetch):
    settings = Settings(
        home_dir=home, data_dir=data_dir, usage_check=enabled, usage_check_delay_seconds=3600
    )
    return TestClient(
        create_app(settings=settings, fetch_usage=fetch), base_url=BACKEND_URL, headers=HEADERS
    )


def test_usage_endpoint_returns_snapshot(home, data_dir):
    async def fetch():
        return UsageReport([LIMIT], "Max 20x")

    with _client(home, data_dir, enabled=True, fetch=fetch) as client:
        client.portal.call(client.app.state.usage.refresh)
        body = client.get("/api/usage").json()

    assert body["enabled"] is True
    assert body["error"] is None
    assert body["plan"] == "Max 20x"
    assert isinstance(body["fetched_at"], float)
    assert body["limits"] == [
        {"kind": "session", "label": "Sessão", "percent": 14, "severity": "normal",
         "resets_at": 1791333000.0}
    ]


def test_usage_endpoint_when_disabled(home, data_dir):
    async def fetch():
        raise AssertionError("não deveria consultar")

    with _client(home, data_dir, enabled=False, fetch=fetch) as client:
        client.portal.call(client.app.state.usage.refresh)
        body = client.get("/api/usage").json()

    assert body == {"enabled": False, "limits": [], "fetched_at": None, "error": None, "plan": None}


def test_usage_endpoint_requires_maestro_header(client):
    assert client.get("/api/usage", headers={"x-maestro": "0"}).status_code == 403


def test_turn_end_refreshes_usage(home, data_dir):
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        return UsageReport([LIMIT], "Max 20x")

    (home / "app").mkdir()
    with _client(home, data_dir, enabled=True, fetch=fetch) as client:
        project = client.post(
            "/api/projects", json={"name": "app", "path": str(home / "app"), "color": "#ff8800"}
        ).json()

        async def end_turn():
            client.app.state.sessions._on_turn_end(project["id"])
            for _ in range(100):
                if calls:
                    return
                await asyncio.sleep(0.01)

        client.portal.call(end_turn)
        assert calls == [1]
        # A second turn within a minute does not check again.
        client.portal.call(end_turn)
        assert calls == [1]


def test_load_settings_reads_usage_check(monkeypatch):
    monkeypatch.setenv("MAESTRO_USAGE_CHECK", "0")
    assert load_settings().usage_check is False
    monkeypatch.setenv("MAESTRO_USAGE_CHECK", "1")
    assert load_settings().usage_check is True
    monkeypatch.delenv("MAESTRO_USAGE_CHECK")
    assert load_settings().usage_check is True
