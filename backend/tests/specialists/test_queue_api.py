"""Queue controls use the normal protected agent API; no real SDK."""

import pytest

from .test_api import agent, api, events, factory, project  # noqa: F401


def test_pause_queue_enqueue_reload_and_cancel(api, agent, factory):
    agent_id = agent["id"]
    assert agent["queue_paused"] is False
    response = api.patch(f"/api/specialists/{agent_id}", json={"queue_paused": True})
    assert response.status_code == 200 and response.json()["queue_paused"] is True
    run = api.post(f"/api/specialists/{agent_id}/run", json={"text": "Pedido guardado"}).json()
    assert run["outcome"] == "queued" and run["session_id"] is None
    assert factory.clients == []
    assert api.get(f"/api/specialists/{agent_id}/runs").json() == [run]
    cancelled = api.post(f"/api/specialists/{agent_id}/runs/{run['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["outcome"] == "cancelled"
    assert api.post(f"/api/specialists/{agent_id}/runs/{run['id']}/cancel").json() == cancelled.json()
    api.patch(f"/api/specialists/{agent_id}", json={"queue_paused": False})
    assert factory.clients == []


def test_resume_dispatches_the_existing_run(api, agent):
    agent_id = agent["id"]
    api.patch(f"/api/specialists/{agent_id}", json={"queue_paused": True})
    run = api.post(f"/api/specialists/{agent_id}/run").json()
    response = api.patch(f"/api/specialists/{agent_id}", json={"queue_paused": False})
    assert response.status_code == 200
    [saved] = api.get(f"/api/specialists/{agent_id}/runs").json()
    assert saved["id"] == run["id"] and saved["session_id"] and saved["outcome"] == "running"


def test_cancel_refuses_running_and_unknown_runs(api, agent):
    agent_id = agent["id"]
    run = api.post(f"/api/specialists/{agent_id}/run").json()
    assert api.post(f"/api/specialists/{agent_id}/runs/{run['id']}/cancel").status_code == 409
    assert api.post(f"/api/specialists/{agent_id}/runs/99999/cancel").status_code == 404


@pytest.mark.parametrize("value", [None, "maybe"])
def test_queue_pause_refuses_invalid_values(api, agent, value):
    assert api.patch(f"/api/specialists/{agent['id']}", json={"queue_paused": value}).status_code == 422


def test_queue_cancel_requires_the_maestro_header(api, agent):
    agent_id = agent["id"]
    api.patch(f"/api/specialists/{agent_id}", json={"queue_paused": True})
    run = api.post(f"/api/specialists/{agent_id}/run").json()
    api.headers.pop("x-maestro")
    assert api.post(f"/api/specialists/{agent_id}/runs/{run['id']}/cancel").status_code == 403


def test_failed_queue_storage_returns_an_actionable_error_without_echoing_the_exception(api, agent, monkeypatch):
    def fail(*args):
        raise OSError("SEGREDO_NO_ERRO")

    monkeypatch.setattr(api.app.state.specialist_files, "write_run_text", fail)
    response = api.post(f"/api/specialists/{agent['id']}/run")
    assert response.status_code == 503
    assert "guardar a execução" in response.json()["detail"]
    assert "SEGREDO_NO_ERRO" not in response.text
    assert api.get(f"/api/specialists/{agent['id']}/runs").json() == []
