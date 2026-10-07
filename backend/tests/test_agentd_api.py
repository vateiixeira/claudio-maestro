from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.agent.agentd_client import AgentdChild
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}


class FakeAgentd:
    def __init__(self, children):
        self.children = children
        self.shutdowns = 0

    async def live_children(self):
        return self.children

    async def shutdown_server(self):
        self.shutdowns += 1

    async def aclose(self):
        pass


def child(exit_code):
    return AgentdChild(id="c", session_id="s", pid=1, next_pos=0, ack=0, exit_code=exit_code, init=None)


def client_with(home, data_dir, agentd):
    with TestClient(create_app(settings=Settings(home_dir=home, data_dir=data_dir)),
                    base_url=BACKEND_URL, headers=HEADERS) as client:
        client.app.state.agentd = agentd
        yield client


def test_restart_refused_without_agentd(home, data_dir):
    for client in client_with(home, data_dir, None):
        response = client.post("/api/agentd/restart")
    assert response.status_code == 409
    assert response.json()["detail"] == "o agentd está desligado"


def test_restart_refused_with_live_children(home, data_dir):
    agentd = FakeAgentd([child(None), child(0)])
    for client in client_with(home, data_dir, agentd):
        response = client.post("/api/agentd/restart")
    assert response.status_code == 409
    assert response.json()["detail"] == "há 1 sessão rodando no agentd"
    assert agentd.shutdowns == 0


def test_restart_with_only_exited_children(home, data_dir):
    agentd = FakeAgentd([child(0)])
    for client in client_with(home, data_dir, agentd):
        response = client.post("/api/agentd/restart")
    assert response.json() == {"restarted": True}
    assert agentd.shutdowns == 1


def test_restart_when_agentd_is_not_running(home, data_dir):
    agentd = FakeAgentd(None)
    for client in client_with(home, data_dir, agentd):
        response = client.post("/api/agentd/restart")
    assert response.json() == {"restarted": False}
    assert agentd.shutdowns == 0


def test_restart_refused_while_the_app_has_live_sessions(home, data_dir, monkeypatch):
    # A session still connecting could spawn between the check and the shutdown.
    agentd = FakeAgentd([])
    for client in client_with(home, data_dir, agentd):
        monkeypatch.setattr(client.app.state.sessions, "live_count", lambda: 1)
        response = client.post("/api/agentd/restart")
    assert response.status_code == 409
    assert response.json()["detail"] == "há sessões abertas no app"
    assert agentd.shutdowns == 0


def test_restart_requires_origin_and_maestro_header(home, data_dir):
    agentd = FakeAgentd([])
    for client in client_with(home, data_dir, agentd):
        bad_origin = client.post("/api/agentd/restart", headers={"origin": "https://evil.example"})
        no_header = client.post("/api/agentd/restart", headers={"x-maestro": "0"})
    assert bad_origin.status_code == 403
    assert no_header.status_code == 403
    assert agentd.shutdowns == 0
