"""Label routes, label_ids of a session, events and search. Uses the scripted fake agent."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_groups_api import new_session, next_of_type, without_header
from test_sessions_api import (  # noqa: F401
    api,
    connect_ws,
    factory,
    make_project,
    receive,
)

from claudio_maestro import labels


def create_label(api: TestClient, slug: str = "urgente", color: str = "#ff0000") -> dict[str, Any]:
    response = api.post("/api/labels", json={"slug": slug, "color": color})
    assert response.status_code == 201, response.text
    return response.json()


def put_labels(api: TestClient, session_id: str, ids: list[int]):
    return api.put(f"/api/sessions/{session_id}/labels", json={"label_ids": ids})


def test_crud_and_listing(api):
    label = create_label(api, "  Urgente ", "#F00")
    assert label["slug"] == "urgente"
    assert label["color"] == "#ff0000"
    assert api.get("/api/labels").json() == [label]

    recolored = api.patch(f"/api/labels/{label['id']}", json={"color": "#00ff00"})
    assert recolored.status_code == 200
    assert recolored.json()["color"] == "#00ff00"
    assert recolored.json()["slug"] == "urgente"

    renamed = api.patch(f"/api/labels/{label['id']}", json={"slug": "importante"})
    assert renamed.json()["slug"] == "importante"

    assert api.delete(f"/api/labels/{label['id']}").status_code == 204
    assert api.get("/api/labels").json() == []


def test_errors(api):
    create_label(api, "urgente")
    dup = api.post("/api/labels", json={"slug": "URGENTE", "color": "#000000"})
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Já existe uma etiqueta com esse slug."
    bad_slug = api.post("/api/labels", json={"slug": "a b", "color": "#000000"})
    assert bad_slug.status_code == 422
    bad_color = api.post("/api/labels", json={"slug": "ok", "color": "red"})
    assert bad_color.status_code == 422
    assert bad_color.json()["detail"] == "A cor deve ser um hexadecimal como #1a2b3c."
    assert api.post("/api/labels", json={"slug": "ok"}).status_code == 422
    assert api.post("/api/labels", json={"slug": "ok", "color": "#000000", "x": 1}).status_code == 422
    assert api.patch("/api/labels/999", json={"color": "#000000"}).status_code == 404
    assert api.delete("/api/labels/999").status_code == 404
    assert len(api.get("/api/labels").json()) == 1


def label_requests(label_id: int, session_id: str) -> list[tuple[str, str, dict | None]]:
    return [
        ("POST", "/api/labels", {"slug": "novo", "color": "#000000"}),
        ("PATCH", f"/api/labels/{label_id}", {"color": "#111111"}),
        ("DELETE", f"/api/labels/{label_id}", None),
        ("PUT", f"/api/sessions/{session_id}/labels", {"label_ids": []}),
    ]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_label_routes_refuse_a_request_without_the_app_header(api, home: Path, index: int):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    label = create_label(api)
    put_labels(api, session["session_id"], [label["id"]])
    method, url, body = label_requests(label["id"], session["session_id"])[index]

    with without_header(api, "x-maestro"):
        response = api.request(method, url, json=body)
    assert response.status_code == 403
    assert api.get("/api/labels").json() == [label]
    assert api.get(f"/api/sessions/{session['session_id']}").json()["label_ids"] == [label["id"]]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_label_routes_refuse_a_foreign_origin(api, home: Path, index: int):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    label = create_label(api)
    method, url, body = label_requests(label["id"], session["session_id"])[index]

    response = api.request(method, url, json=body, headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert api.get("/api/labels").json() == [label]


def test_session_starts_without_labels_and_put_sets_them(api, home: Path):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    assert session["label_ids"] == []
    a = create_label(api, "a", "#111111")
    b = create_label(api, "b", "#222222")

    response = put_labels(api, session["session_id"], [b["id"], a["id"], b["id"]])
    assert response.status_code == 200
    assert response.json()["label_ids"] == [a["id"], b["id"]]
    listed = api.get("/api/sessions").json()
    assert [item["label_ids"] for item in listed if item["session_id"] == session["session_id"]] == [
        [a["id"], b["id"]]
    ]
    # A PATCH of something else keeps the labels.
    patched = api.patch(f"/api/sessions/{session['session_id']}", json={"title": "Novo"})
    assert patched.json()["label_ids"] == [a["id"], b["id"]]
    assert put_labels(api, session["session_id"], []).json()["label_ids"] == []


def test_put_with_an_unknown_id_applies_nothing(api, home: Path):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    a = create_label(api, "a", "#111111")
    put_labels(api, session["session_id"], [a["id"]])
    response = put_labels(api, session["session_id"], [a["id"], 999])
    assert response.status_code == 404
    assert api.get(f"/api/sessions/{session['session_id']}").json()["label_ids"] == [a["id"]]


def test_put_for_an_unknown_session_is_404(api):
    a = create_label(api, "a", "#111111")
    assert put_labels(api, "00000000-0000-0000-0000-000000000000", [a["id"]]).status_code == 404


def test_put_body_is_validated(api, home: Path):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    url = f"/api/sessions/{session['session_id']}/labels"
    assert api.put(url, json={}).status_code == 422
    assert api.put(url, json={"label_ids": ["x"]}).status_code == 422
    assert api.put(url, json={"label_ids": [], "x": 1}).status_code == 422


def test_events_for_catalog_and_for_session(api, home: Path):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    with connect_ws(api) as ws:
        label = create_label(api)
        assert next_of_type(ws, "labels.changed")["session_id"] is None
        put_labels(api, session["session_id"], [label["id"]])
        updated = next_of_type(ws, "session.updated")
        assert updated["data"]["label_ids"] == [label["id"]]
        api.patch(f"/api/labels/{label['id']}", json={"color": "#00ff00"})
        next_of_type(ws, "labels.changed")
        assert api.delete(f"/api/labels/{label['id']}").status_code == 204
        next_of_type(ws, "labels.changed")


def test_deleting_a_label_unlinks_sessions_and_announces_each(api, home: Path):
    project = make_project(api, home)
    a_session = new_session(api, project["id"])
    b_session = new_session(api, project["id"])
    keep = create_label(api, "keep", "#111111")
    gone = create_label(api, "gone", "#222222")
    put_labels(api, a_session["session_id"], [keep["id"], gone["id"]])
    put_labels(api, b_session["session_id"], [gone["id"]])

    with connect_ws(api) as ws:
        assert api.delete(f"/api/labels/{gone['id']}").status_code == 204
        seen = {}
        while len(seen) < 2:
            event = next_of_type(ws, "session.updated")
            seen[event["data"]["session_id"]] = event["data"]["label_ids"]
    assert seen == {a_session["session_id"]: [keep["id"]], b_session["session_id"]: []}
    assert api.get(f"/api/sessions/{b_session['session_id']}").json()["label_ids"] == []


def test_deleting_a_label_announces_a_session_that_is_not_in_memory(api, home: Path):
    project = make_project(api, home)
    live = new_session(api, project["id"])
    stored = new_session(api, project["id"])
    gone = create_label(api, "gone", "#222222")
    put_labels(api, live["session_id"], [gone["id"]])
    put_labels(api, stored["session_id"], [gone["id"]])
    # Only the database row is left: this is the `outside` branch of remove_label.
    assert api.app.state.sessions._sessions.pop(stored["session_id"]) is not None

    with connect_ws(api) as ws:
        assert api.delete(f"/api/labels/{gone['id']}").status_code == 204
        seen = {}
        while len(seen) < 2:
            event = next_of_type(ws, "session.updated")
            seen[event["data"]["session_id"]] = event["data"]["label_ids"]
    assert seen == {live["session_id"]: [], stored["session_id"]: []}
    listed = {item["session_id"]: item["label_ids"] for item in api.get("/api/sessions").json()}
    assert listed[stored["session_id"]] == []
    assert listed[live["session_id"]] == []


def test_search_finds_a_session_by_the_slug_of_its_label(api, home: Path):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    other = new_session(api, project["id"])
    label = create_label(api, "revisao-final")
    put_labels(api, session["session_id"], [label["id"]])
    found = api.get("/api/sessions/search", params={"q": "revisao"}).json()
    assert [item["session_id"] for item in found] == [session["session_id"]]
    assert other["session_id"] not in [item["session_id"] for item in found]


def test_put_converts_an_integrity_error_from_the_write_into_404(api, home: Path, monkeypatch):
    project = make_project(api, home)
    session = new_session(api, project["id"])
    label = create_label(api)

    def vanished(conn, session_id, label_ids):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(labels, "set_session_labels", vanished)
    response = put_labels(api, session["session_id"], [label["id"]])
    assert response.status_code == 404
    assert response.json()["detail"] == "Sessão não encontrada."
