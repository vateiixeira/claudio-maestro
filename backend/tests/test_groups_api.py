"""Group routes and the group of a session. Uses the scripted fake agent."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import api, connect_ws, factory, make_project, receive  # noqa: F401


def create_group(api: TestClient, project_id: int, name: str = "Checkout") -> dict[str, Any]:
    response = api.post(f"/api/projects/{project_id}/groups", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def new_session(api: TestClient, project_id: int, body: dict | None = None) -> dict[str, Any]:
    if body is None:
        response = api.post(f"/api/projects/{project_id}/sessions")
    else:
        response = api.post(f"/api/projects/{project_id}/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def next_of_type(ws, kind: str) -> dict[str, Any]:
    while True:
        event = receive(ws)
        if event["type"] == kind:
            return event


def test_crud_and_listing(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"], "  Checkout ")
    assert group["name"] == "Checkout"
    assert group["project_id"] == project["id"]
    assert api.get("/api/groups").json() == [group]

    renamed = api.patch(f"/api/groups/{group['id']}", json={"name": "Pagamento"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Pagamento"

    assert api.delete(f"/api/groups/{group['id']}").status_code == 204
    assert api.get("/api/groups").json() == []


@contextmanager
def without_header(api: TestClient, name: str) -> Iterator[None]:
    """Send requests without a default header of the client (not with it empty)."""
    value = api.headers[name]
    del api.headers[name]
    try:
        yield
    finally:
        api.headers[name] = value


def group_requests(project_id: int, group_id: int) -> list[tuple[str, str, dict | None]]:
    return [
        ("POST", f"/api/projects/{project_id}/groups", {"name": "Novo"}),
        ("PATCH", f"/api/groups/{group_id}", {"name": "Renomeado"}),
        ("DELETE", f"/api/groups/{group_id}", None),
    ]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_group_routes_refuse_a_request_without_the_app_header(api, home: Path, index: int):
    project = make_project(api, home)
    group = create_group(api, project["id"], "Checkout")
    method, url, body = group_requests(project["id"], group["id"])[index]

    with without_header(api, "x-vibing"):
        assert "x-vibing" not in api.headers
        response = api.request(method, url, json=body)
    assert response.status_code == 403
    assert response.json()["detail"] == "Cabeçalho do app ausente."
    # Nothing was created, renamed or removed.
    assert api.get("/api/groups").json() == [group]


@pytest.mark.parametrize("index", [0, 1, 2])
def test_group_routes_refuse_a_foreign_origin(api, home: Path, index: int):
    project = make_project(api, home)
    group = create_group(api, project["id"], "Checkout")
    method, url, body = group_requests(project["id"], group["id"])[index]

    response = api.request(method, url, json=body, headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Origem não permitida."
    assert api.get("/api/groups").json() == [group]


def test_errors(api, home: Path):
    project = make_project(api, home)
    create_group(api, project["id"], "Checkout")
    dup = api.post(f"/api/projects/{project['id']}/groups", json={"name": "checkout"})
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Já existe um agrupador com esse nome neste projeto."
    empty = api.post(f"/api/projects/{project['id']}/groups", json={"name": "  "})
    assert empty.status_code == 422
    assert empty.json()["detail"] == "Dê um nome ao agrupador."
    long = api.post(f"/api/projects/{project['id']}/groups", json={"name": "x" * 81})
    assert long.status_code == 422
    assert api.post("/api/projects/999/groups", json={"name": "x"}).status_code == 404
    assert api.patch("/api/groups/999", json={"name": "x"}).status_code == 404
    assert api.delete("/api/groups/999").status_code == 404


def test_group_routes_need_the_vibing_header(api, home: Path):
    project = make_project(api, home)
    response = api.post(
        f"/api/projects/{project['id']}/groups", json={"name": "x"}, headers={"x-vibing": ""}
    )
    assert response.status_code in (400, 403)


def test_move_change_and_release_session(api, home: Path):
    project = make_project(api, home)
    a = create_group(api, project["id"], "A")
    b = create_group(api, project["id"], "B")
    session = new_session(api, project["id"])
    assert session["group_id"] is None
    url = f"/api/sessions/{session['session_id']}"

    assert api.patch(url, json={"group_id": a["id"]}).json()["group_id"] == a["id"]
    assert api.patch(url, json={"group_id": b["id"]}).json()["group_id"] == b["id"]
    # A PATCH without group_id keeps the group.
    assert api.patch(url, json={"title": "Novo"}).json()["group_id"] == b["id"]
    assert api.patch(url, json={"group_id": None}).json()["group_id"] is None


def test_move_to_group_of_another_project_or_missing(api, home: Path):
    one = make_project(api, home, "one")
    two = make_project(api, home, "two")
    foreign = create_group(api, two["id"], "X")
    session = new_session(api, one["id"])
    url = f"/api/sessions/{session['session_id']}"
    response = api.patch(url, json={"group_id": foreign["id"]})
    assert response.status_code == 422
    assert response.json()["detail"] == "O agrupador é de outro projeto."
    assert api.patch(url, json={"group_id": 999}).status_code == 404
    assert api.get(f"/api/projects/{one['id']}/sessions").json()[0]["group_id"] is None


def test_create_session_inside_group(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"])
    session = new_session(api, project["id"], {"group_id": group["id"]})
    assert session["group_id"] == group["id"]
    # Without a body (what the frontend sent before) it still works.
    assert new_session(api, project["id"])["group_id"] is None
    other = make_project(api, home, "other")
    response = api.post(f"/api/projects/{other['id']}/sessions", json={"group_id": group["id"]})
    assert response.status_code == 422


def test_events(api, home: Path):
    project = make_project(api, home)
    with connect_ws(api) as ws:
        group = create_group(api, project["id"])
        event = next_of_type(ws, "groups.changed")
        assert event["data"] == {"project_id": project["id"]}
        assert event["session_id"] is None

        session = new_session(api, project["id"])
        api.patch(f"/api/sessions/{session['session_id']}", json={"group_id": group["id"]})
        updated = next_of_type(ws, "session.updated")
        assert updated["data"]["group_id"] == group["id"]

        api.patch(f"/api/groups/{group['id']}", json={"name": "Outro"})
        assert next_of_type(ws, "groups.changed")["data"] == {"project_id": project["id"]}

        api.delete(f"/api/groups/{group['id']}")
        released = next_of_type(ws, "session.updated")
        assert released["session_id"] == session["session_id"]
        assert released["data"]["group_id"] is None
        assert next_of_type(ws, "groups.changed")["data"] == {"project_id": project["id"]}


def test_remove_group_releases_session_not_in_memory(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"])
    session = new_session(api, project["id"], {"group_id": group["id"]})
    # Drop it from memory the way the app does after the last client leaves.
    manager = api.app.state.sessions
    manager._sessions.pop(session["session_id"], None)
    with connect_ws(api) as ws:
        api.delete(f"/api/groups/{group['id']}")
        released = next_of_type(ws, "session.updated")
        assert released["session_id"] == session["session_id"]
        assert released["data"]["group_id"] is None
    listed = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed[0]["group_id"] is None


def test_search_finds_by_group_name(api, home: Path):
    project = make_project(api, home)
    group = create_group(api, project["id"], "Integração Stripe")
    session = new_session(api, project["id"], {"group_id": group["id"]})
    new_session(api, project["id"])
    found = api.get("/api/sessions/search", params={"q": "integracao"}).json()
    assert [s["session_id"] for s in found] == [session["session_id"]]


def test_removing_project_removes_groups(api, home: Path):
    project = make_project(api, home)
    create_group(api, project["id"])
    assert api.delete(f"/api/projects/{project['id']}").status_code == 204
    assert api.get("/api/groups").json() == []
