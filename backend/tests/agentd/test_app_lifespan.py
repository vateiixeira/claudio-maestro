"""The agentd wiring in the app's lifespan. No agentd process is ever started here."""

from fastapi.testclient import TestClient

from claudio_maestro.agent.agentd_client import AgentdClient
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.agentd.paths import socket_path
from claudio_maestro.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}


def test_agentd_is_off_with_an_injected_agent(data_dir):
    app = create_app(agent_factory=FakeAgentFactory())
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        assert app.state.agentd is None
    assert not socket_path(data_dir).exists()


def test_real_agent_turns_the_agentd_on_without_starting_it_when_disabled(data_dir, monkeypatch):
    monkeypatch.setenv("MAESTRO_AGENTD", "0")
    app = create_app()
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        assert isinstance(app.state.agentd, AgentdClient)
        # Attach-only: reattaching at startup must not launch an agentd.
        assert not socket_path(data_dir).exists()


def test_explicit_flag_overrides_the_default(data_dir, monkeypatch):
    monkeypatch.setenv("MAESTRO_AGENTD", "0")
    on = create_app(agent_factory=FakeAgentFactory(), agentd=True)
    with TestClient(on, base_url=BACKEND_URL, headers=HEADERS):
        assert isinstance(on.state.agentd, AgentdClient)
    off = create_app(agentd=False)
    with TestClient(off, base_url=BACKEND_URL, headers=HEADERS):
        assert off.state.agentd is None


def test_agentd_may_spawn_when_not_disabled(data_dir, monkeypatch):
    async def no_reattach(self):
        return None

    # No process of any kind: the startup reattach would launch an agentd.
    monkeypatch.setattr("claudio_maestro.sessions.SessionManager.reattach_all", no_reattach)
    monkeypatch.delenv("MAESTRO_AGENTD", raising=False)
    app = create_app(agent_factory=FakeAgentFactory(), agentd=True)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        assert app.state.agentd.spawn_allowed is True
    assert not socket_path(data_dir).exists()


def test_a_failing_reattach_does_not_stop_the_backend_from_starting(data_dir, monkeypatch):
    async def broken_reattach(self):
        raise RuntimeError("boom")

    monkeypatch.setattr("claudio_maestro.sessions.SessionManager.reattach_all", broken_reattach)
    app = create_app(agent_factory=FakeAgentFactory(), agentd=True)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as client:
        assert client.get("/api/health").status_code == 200
