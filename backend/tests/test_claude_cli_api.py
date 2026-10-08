"""GET /api/claude-cli and POST /api/claude-cli/update."""

from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.claudecli import ClaudeCliBusy, ClaudeCliResolver, CommandResult
from claudio_maestro.config import Settings

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}
SYSTEM = "/opt/bin/claude"


class Machine:
    def __init__(self, version: str | None = "2.1.292", path: str | None = SYSTEM) -> None:
        self.version, self.path = version, path
        self.new_version: str | None = None
        self.result = CommandResult(0, "ok")

    def which(self, name):
        return self.path

    def run_version(self, path):
        return None if self.version is None else f"{self.version} (Claude Code)"

    async def run_update(self, argv, timeout):
        if self.new_version:
            self.version = self.new_version
        return self.result


def client_for(home, data_dir, machine: Machine, env=None) -> TestClient:
    resolver = ClaudeCliResolver(
        env=env or {}, which=machine.which, run_version=machine.run_version,
        run_update=machine.run_update, bundled_version="2.1.284",
    )
    settings = Settings(home_dir=home, data_dir=data_dir, update_check=False, usage_check=False)
    app = create_app(settings=settings, agent_factory=FakeAgentFactory(), claude_cli=resolver)
    return TestClient(app, base_url=BACKEND_URL, headers=HEADERS)


def test_get_reports_system_cli(home, data_dir):
    with client_for(home, data_dir, Machine()) as client:
        body = client.get("/api/claude-cli").json()
    assert body == {
        "in_use": {"source": "system", "version": "2.1.292"},
        "system": {"path": SYSTEM, "version": "2.1.292"},
        "bundled": {"version": "2.1.284"},
        "forced_bundled": False,
        "can_update": True,
        "job": None,
    }


def test_get_without_system_cli(home, data_dir):
    with client_for(home, data_dir, Machine(path=None)) as client:
        body = client.get("/api/claude-cli").json()
    assert body["in_use"] == {"source": "bundled", "version": "2.1.284"}
    assert body["system"] is None and body["can_update"] is False


def test_get_forced_bundled(home, data_dir):
    with client_for(home, data_dir, Machine(), env={"MAESTRO_CLAUDE_CLI": "bundled"}) as client:
        body = client.get("/api/claude-cli").json()
    assert body["forced_bundled"] is True and body["can_update"] is False
    assert body["in_use"]["source"] == "bundled"


def test_update_to_new_version_refreshes_models(home, data_dir):
    machine = Machine()
    machine.new_version = "2.1.295"
    with client_for(home, data_dir, machine) as client:
        factory = client.app.state.sessions.agent_factory
        response = client.post("/api/claude-cli/update")
        after = client.get("/api/claude-cli").json()
    assert response.status_code == 200
    body = response.json()
    assert (body["ok"], body["before"], body["after"]) == (True, "2.1.292", "2.1.295")
    assert body["models_refreshed"] is True
    assert body["message"] == "Claude atualizado de 2.1.292 para 2.1.295. A lista de modelos foi renovada."
    assert sum(c.server_info_calls for c in factory.clients) == 1
    assert after["in_use"]["version"] == "2.1.295"
    assert after["job"]["state"] == "done"


def test_update_already_latest(home, data_dir):
    with client_for(home, data_dir, Machine()) as client:
        body = client.post("/api/claude-cli/update").json()
    assert body["message"] == "O Claude já está na versão mais nova (2.1.292)."


def test_update_failure_is_200_with_ok_false(home, data_dir):
    machine = Machine()
    machine.result = CommandResult(1, "Erro: sem permissão")
    with client_for(home, data_dir, machine) as client:
        response = client.post("/api/claude-cli/update")
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["message"] == "Não foi possível atualizar o Claude. Erro: sem permissão"


def test_update_without_system_cli_is_409(home, data_dir):
    with client_for(home, data_dir, Machine(path=None)) as client:
        response = client.post("/api/claude-cli/update")
    assert response.status_code == 409
    assert response.json()["detail"] == "Não há Claude instalado no sistema para atualizar."


def test_update_forced_bundled_is_409(home, data_dir):
    with client_for(home, data_dir, Machine(), env={"MAESTRO_CLAUDE_CLI": "bundled"}) as client:
        response = client.post("/api/claude-cli/update")
    assert response.status_code == 409


def test_update_busy_is_409(home, data_dir, monkeypatch):
    with client_for(home, data_dir, Machine()) as client:
        async def busy(refresh_models):
            raise ClaudeCliBusy("Já há uma atualização do Claude em andamento.")

        monkeypatch.setattr(client.app.state.claude_cli, "update", busy)
        response = client.post("/api/claude-cli/update")
    assert response.status_code == 409
    assert response.json()["detail"] == "Já há uma atualização do Claude em andamento."


def test_update_requires_maestro_header_and_origin(home, data_dir):
    with client_for(home, data_dir, Machine()) as client:
        assert client.post("/api/claude-cli/update", headers={"x-maestro": "0"}).status_code == 403
        assert client.post(
            "/api/claude-cli/update", headers={"origin": "https://evil.example"}
        ).status_code == 403
        assert client.get("/api/claude-cli", headers={"x-maestro": "0"}).status_code == 403
