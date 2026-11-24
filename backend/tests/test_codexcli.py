"""Codex settings and account metadata through the real application routes."""

from typing import Any

import pytest

from claudio_maestro import codexcli
from claudio_maestro.claudecli import CommandResult


class MetadataTransport:
    calls: list[tuple[str, dict[str, Any]]] = []
    rate_limits_fail = False

    def __init__(self, cwd, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        match method:
            case "account/read":
                return {"account": {"type": "chatgpt", "planType": "plus", "email": "private"}}
            case "account/rateLimits/read":
                if self.rate_limits_fail:
                    raise codexcli.AgentError("private account details")
                return {"rateLimitsByLimitId": {
                    "codex": {"primary": {"usedPercent": 40, "windowDurationMins": 300,
                                           "resetsAt": 2000000000},
                              "secondary": {"usedPercent": 90, "windowDurationMins": 10080}},
                    "scoped": {"limitName": "Modelo extra", "secondary": {"usedPercent": 23}},
                }}
            case "config/read":
                return {"config": {"model": "model-b", "model_reasoning_effort": "high"}}
            case "model/list":
                return {"data": [
                    {"id": "model-a", "model": "model-a", "displayName": "Modelo A", "isDefault": True},
                    {"id": "model-b", "model": "model-b", "displayName": "Modelo B",
                     "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                     "defaultReasoningEffort": "high"},
                ]}
        raise AssertionError(method)


@pytest.fixture
def codex(monkeypatch):
    MetadataTransport.calls = []
    MetadataTransport.rate_limits_fail = False
    versions = {"installed": "0.172.0", "latest": "0.173.0"}
    monkeypatch.setattr(codexcli, "codex_binary", lambda: "/absolute/bin/codex")
    monkeypatch.setattr("claudio_maestro.providers.codex_binary", lambda: "/absolute/bin/codex")
    monkeypatch.setattr(codexcli, "CodexTransport", MetadataTransport)
    monkeypatch.setattr(codexcli, "run_version_command", lambda _: f"codex-cli {versions['installed']}")
    monkeypatch.setattr(codexcli, "fetch_latest_version", lambda: versions["latest"])
    return versions


def test_cli_metadata_model_defaults_and_quota_are_cached(client, codex):
    result = client.get("/api/codex-cli")
    assert result.status_code == 200
    data = result.json()
    assert data["version"] == "0.172.0"
    assert data["update_available"] is True
    assert data["default_model"] == "model-b"
    assert data["default_effort"] == "high"
    assert data["usage"]["plan"] == "Plus"
    limits = data["usage"]["limits"]
    assert [(row["kind"], row["percent"], row["severity"]) for row in limits] == [
        ("session", 40, "normal"), ("weekly_all", 90, "critical"), ("weekly_scoped", 23, "normal")
    ]
    assert limits[0]["resets_at"] == 2000000000
    assert "private" not in result.text
    models = client.get("/api/models?provider=codex").json()
    assert [model["value"] for model in models if model["isDefault"]] == ["model-b"]
    assert models[1]["supportedEffortLevels"] == ["high"]
    assert [call for call, _ in MetadataTransport.calls].count("model/list") == 1
    assert client.post("/api/codex-cli/refresh").json()["models_refreshed"] is True
    assert [call for call, _ in MetadataTransport.calls].count("model/list") == 2


def test_cli_retains_limits_on_refresh_failure(client, codex):
    original = client.get("/api/codex-cli").json()["usage"]
    MetadataTransport.rate_limits_fail = True
    response = client.post("/api/codex-cli/refresh")
    usage = response.json()["usage"]
    assert usage["plan"] == original["plan"]
    assert usage["limits"] == original["limits"]
    assert usage["fetched_at"] == original["fetched_at"]
    assert usage["error"]
    assert "private" not in response.text


def test_cli_update_uses_the_installed_command_and_refreshes_models(client, codex, monkeypatch):
    async def run(argv, timeout):
        assert argv == ["/absolute/bin/codex", "update"]
        assert timeout > 0
        codex["installed"] = codex["latest"]
        return CommandResult(0, "texto local")

    monkeypatch.setattr(codexcli, "run_update_command", run)
    result = client.post("/api/codex-cli/update").json()
    assert result["ok"] is True
    assert result["before"] == "0.172.0"
    assert result["after"] == "0.173.0"
    assert result["models_refreshed"] is True
    assert result["update_available"] is False


def test_cli_missing_and_provider_preferences(client, home, monkeypatch):
    monkeypatch.setattr(codexcli, "codex_binary", lambda: None)
    monkeypatch.setattr("claudio_maestro.providers.codex_binary", lambda: None)
    assert client.get("/api/codex-cli").json()["installed"] is False
    assert client.post("/api/codex-cli/update").status_code == 409
    for pref, invalid in (("codex_enabled", 1), ("codex_new_session_model", " "),
                          ("codex_new_session_effort", "huge")):
        assert client.put("/api/state/preferences", json={pref: invalid}).status_code == 400
    folder = home / "codex-project"
    folder.mkdir()
    result = client.post("/api/projects", json={"name": "Codex", "path": str(folder), "color": "#3388ff"})
    assert result.status_code == 201, result.text
    route = f"/api/projects/{result.json()['id']}/sessions"
    assert client.post(route, json={"provider": "codex"}).status_code == 409
    monkeypatch.setattr("claudio_maestro.providers.codex_binary", lambda: "/absolute/bin/codex")
    preferences = {"codex_enabled": True, "codex_new_session_model": "model-b",
                   "codex_new_session_effort": "high", "new_session_model": "opus"}
    assert client.put("/api/state/preferences", json=preferences).status_code == 200
    providers = {item["id"]: item for item in client.get("/api/providers").json()}
    assert providers["codex"]["enabled"] is True and providers["codex"]["available"] is True
    response = client.post(route, json={"provider": "codex"})
    assert response.status_code == 201, response.text
    assert response.json()["provider"] == "codex"
    assert response.json()["model"] == "model-b"
    assert response.json()["effort"] == "high"

    session_route = f"/api/sessions/{response.json()['session_id']}"
    assert client.patch(session_route, json={"effort": "ultra"}).json()["effort"] == "ultra"
    assert client.patch(session_route, json={"effort": "default"}).json()["effort"] is None
    assert client.patch(session_route, json={"model": "default"}).json()["model"] == "default"


def test_codex_launch_rechecks_registered_path_after_symlink_replacement(client, codex, home, tmp_path):
    folder = home / "project"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert client.put("/api/state/preferences", json={"codex_enabled": True}).is_success
    project = client.post("/api/projects", json={"name": "Codex", "path": str(folder),
                                                  "color": "#3388ff"}).json()
    session = client.post(f"/api/projects/{project['id']}/sessions", json={"provider": "codex"}).json()
    folder.rmdir()
    folder.symlink_to(outside, target_is_directory=True)
    sent = client.post(f"/api/sessions/{session['session_id']}/messages", json={"text": "Olá"})
    assert sent.is_success
    snapshot = client.get(f"/api/sessions/{session['session_id']}").json()
    assert snapshot["error"] == "A pasta da sessão do Codex precisa pertencer ao projeto."
