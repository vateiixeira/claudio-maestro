"""Session routes and the event WebSocket, with the scripted fake agent."""

import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import PermissionUpdate
from fastapi.testclient import TestClient

from vibing.agent.fake import FakeAgentFactory, text_turn, tool_turn
from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
WS_URL = "ws://127.0.0.1:6660/ws"
WAIT = 2  # seconds; every wait fails instead of hanging the suite
MISSING = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory()


@pytest.fixture
def api(factory: FakeAgentFactory):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as c:
        yield c


def make_project(api: TestClient, home: Path, name: str = "app") -> dict[str, Any]:
    folder = home / name
    folder.mkdir()
    response = api.post(
        "/api/projects", json={"name": name, "path": str(folder), "color": "#ff8800"}
    )
    assert response.status_code == 201
    return response.json()


def new_session(api: TestClient, home: Path) -> dict[str, Any]:
    project = make_project(api, home)
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return response.json()


def wait_state(api: TestClient, session_id: str, state: str) -> dict[str, Any]:
    deadline = time.monotonic() + WAIT
    while True:
        snapshot = api.get(f"/api/sessions/{session_id}").json()
        if snapshot["state"] == state:
            return snapshot
        if time.monotonic() > deadline:
            raise AssertionError(f"estado {snapshot['state']!r}, esperado {state!r}")
        time.sleep(0.005)


def connect_ws(api: TestClient, origin: str = APP_ORIGIN):
    return api.websocket_connect(WS_URL, headers={"origin": origin})


def receive(ws) -> dict[str, Any]:
    """Next event from a test WebSocket, failing after WAIT seconds instead of hanging.

    `receive_json` blocks with no timeout, so it runs in a worker thread.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(ws.receive_json).result(timeout=WAIT)
    except FutureTimeout:
        raise AssertionError(f"nenhum evento em {WAIT}s") from None
    finally:
        executor.shutdown(wait=False)


def receive_until_idle(ws, session_id: str) -> list[dict[str, Any]]:
    events = []
    while True:
        event = receive(ws)
        events.append(event)
        if (
            event["session_id"] == session_id
            and event["type"] == "session.state"
            and event["data"]["state"] == "idle"
        ):
            return events


# Creation and listing ------------------------------------------------------


def test_create_session(api, home, factory):
    project = make_project(api, home)

    response = api.post(f"/api/projects/{project['id']}/sessions")

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["cwd"] == project["path"]
    assert body["title"] == "Nova sessão"
    assert body["state"] == "closed"
    assert body["error"] is None
    assert body["created_at"] > 0 and body["last_activity_at"] > 0
    assert len(body["session_id"]) == 36
    assert factory.clients == []


def test_create_session_unknown_project(api):
    assert api.post("/api/projects/999/sessions").status_code == 404


def test_create_session_unavailable_project(api, home):
    project = make_project(api, home)
    shutil.rmtree(project["path"])

    response = api.post(f"/api/projects/{project['id']}/sessions")

    assert response.status_code == 409
    assert response.json()["detail"]


def test_list_sessions_with_state(api, home, factory):
    factory.script = lambda content: text_turn("x", "ok")
    project = make_project(api, home)
    first = api.post(f"/api/projects/{project['id']}/sessions").json()
    second = api.post(f"/api/projects/{project['id']}/sessions").json()
    api.post(f"/api/sessions/{second['session_id']}/messages", json={"text": "oi"})
    wait_state(api, second["session_id"], "idle")

    response = api.get(f"/api/projects/{project['id']}/sessions")

    assert response.status_code == 200
    listed = {s["session_id"]: s for s in response.json()}
    assert listed[first["session_id"]]["state"] == "closed"
    assert listed[second["session_id"]]["state"] == "idle"
    assert listed[second["session_id"]]["title"] == "oi"


def test_list_sessions_unknown_project(api):
    assert api.get("/api/projects/999/sessions").status_code == 404


# Snapshot and messages -----------------------------------------------------


def test_snapshot_of_new_session(api, home):
    session = new_session(api, home)

    response = api.get(f"/api/sessions/{session['session_id']}")

    assert response.status_code == 200
    assert response.json() == {
        **session,
        "items": [],
        "prompts": [],
        "init": None,
        "history_truncated": False,
        "external_activity": False,
    }


def test_send_message_runs_turn(api, home, factory):
    session = new_session(api, home)
    sid = session["session_id"]
    factory.script = lambda content: text_turn(sid, "Olá!")

    response = api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})

    assert response.status_code == 202
    snapshot = wait_state(api, sid, "idle")
    assert [i["type"] for i in snapshot["items"]] == ["user", "text"]
    assert snapshot["items"][1]["text"] == "Olá!"
    assert snapshot["init"]["session_id"] == sid
    assert factory.clients[0].options.resume is False


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}])
def test_send_empty_message(api, home, body):
    session = new_session(api, home)

    response = api.post(f"/api/sessions/{session['session_id']}/messages", json=body)

    assert response.status_code == 400
    assert response.json()["detail"] == "A mensagem está vazia."


def test_interrupt_is_accepted(api, home):
    session = new_session(api, home)
    assert api.post(f"/api/sessions/{session['session_id']}/interrupt").status_code == 202


# Prompts -------------------------------------------------------------------


def start_prompt(api, home, factory, suggestions=None) -> tuple[str, dict[str, Any]]:
    session = new_session(api, home)
    sid = session["session_id"]
    factory.script = lambda content: tool_turn(
        sid, tool_name="Write", ask_permission=True, suggestions=suggestions
    )
    api.post(f"/api/sessions/{sid}/messages", json={"text": "escreva"})
    snapshot = wait_state(api, sid, "awaiting_decision")
    [prompt] = snapshot["prompts"]
    return sid, prompt


def test_answer_prompt_twice(api, home, factory):
    sid, prompt = start_prompt(api, home, factory)
    url = f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}"

    first = api.post(url, json={"decision": "allow_once"})
    second = api.post(url, json={"decision": "deny"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]
    wait_state(api, sid, "idle")


def test_allow_always_with_suggestions(api, home, factory):
    suggestion = PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")
    sid, prompt = start_prompt(api, home, factory, suggestions=[suggestion])
    assert prompt["can_always"] is True
    assert prompt["suggestions"] == [suggestion.to_dict()]

    response = api.post(
        f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}", json={"decision": "allow_always"}
    )

    assert response.status_code == 200
    wait_state(api, sid, "idle")
    [record] = factory.clients[0].permission_results
    assert record.result.updated_permissions == [suggestion]


def test_allow_always_without_suggestions(api, home, factory):
    sid, prompt = start_prompt(api, home, factory)

    response = api.post(
        f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}", json={"decision": "allow_always"}
    )

    assert response.status_code == 400
    assert api.get(f"/api/sessions/{sid}").json()["state"] == "awaiting_decision"


def test_invalid_decision(api, home, factory):
    sid, prompt = start_prompt(api, home, factory)

    response = api.post(
        f"/api/sessions/{sid}/prompts/{prompt['prompt_id']}", json={"decision": "talvez"}
    )

    assert response.status_code == 422


def test_unknown_prompt(api, home):
    session = new_session(api, home)
    response = api.post(
        f"/api/sessions/{session['session_id']}/prompts/nada", json={"decision": "deny"}
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "", None),
        ("post", "/messages", {"text": "oi"}),
        ("post", "/interrupt", None),
        ("post", "/prompts/p1", {"decision": "deny"}),
    ],
)
def test_unknown_session_is_404(api, method, path, body):
    response = api.request(method, f"/api/sessions/{MISSING}{path}", json=body)
    assert response.status_code == 404
    assert response.json()["detail"] == "Sessão não encontrada."


# WebSocket -----------------------------------------------------------------


def test_websocket_fans_out_events_with_growing_seq(api, home, factory):
    session = new_session(api, home)
    sid = session["session_id"]
    factory.script = lambda content: text_turn(sid, "Olá!")

    with connect_ws(api) as one, connect_ws(api) as two:
        api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
        from_one = receive_until_idle(one, sid)
        from_two = receive_until_idle(two, sid)

    assert from_one == from_two
    assert [e["seq"] for e in from_one] == list(range(1, len(from_one) + 1))
    assert set(from_one[0]) == {"session_id", "seq", "type", "data"}
    assert from_one[0]["type"] == "item.upsert"
    assert from_one[0]["data"]["text"] == "oi"


def test_websocket_disconnect_does_not_affect_others(api, home, factory):
    session = new_session(api, home)
    sid = session["session_id"]
    factory.script = lambda content: text_turn(sid, "Olá!")

    with connect_ws(api) as staying:
        with connect_ws(api) as leaving:
            api.post(f"/api/sessions/{sid}/messages", json={"text": "um"})
            first = receive_until_idle(staying, sid)
            receive_until_idle(leaving, sid)

        hub = api.app.state.hub
        deadline = time.monotonic() + WAIT
        while hub.connection_count != 1:
            assert time.monotonic() < deadline, "a conexão que saiu continua registrada"
            time.sleep(0.005)
        api.post(f"/api/sessions/{sid}/messages", json={"text": "dois"})
        # Project-wide events (e.g. project.git after a turn) have no session.
        second = [e for e in receive_until_idle(staying, sid) if e["session_id"] == sid]

    assert second[0]["seq"] == first[-1]["seq"] + 1
    assert second[0]["data"]["text"] == "dois"
    assert api.get(f"/api/sessions/{sid}").json()["state"] == "idle"


def test_websocket_requires_origin(api):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with connect_ws(api, origin="http://evil.example"):
            pass


# Lifespan ------------------------------------------------------------------


def test_shutdown_closes_clients(home, factory):
    app = create_app(agent_factory=factory, history_exists=lambda sid, cwd: False)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as api:
        session = new_session(api, home)
        sid = session["session_id"]
        factory.script = lambda content: text_turn(sid, "ok")
        api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
        wait_state(api, sid, "idle")
        assert factory.clients[0].closed is False

    assert factory.clients[0].closed is True
