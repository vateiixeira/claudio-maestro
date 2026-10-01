"""Plan routes: plans of a project, and the plan link of a conversation.

Uses the scripted fake agent; nothing here starts the `claude` process.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import (
    APP_ORIGIN,
    BACKEND_URL,
    MISSING,
    connect_ws,
    make_project,
    receive,
    wait_state,
)

from claudio_maestro.agent.fake import FakeAgentFactory, tool_turn
from claudio_maestro.app import create_app

PLAN_TEXT = "# P\n\n### Tarefa 1: A\n- [x] a\n\n### Tarefa 2: B\n- [ ] b\n"
NO_TASKS = "# Notas\n\nSem tarefas aqui.\n"


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory()


@pytest.fixture
def api(factory: FakeAgentFactory):
    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    app = create_app(agent_factory=factory, history_exists=history_exists)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as c:
        yield c


def write_plan(folder: Path, name: str = "p.md", text: str = PLAN_TEXT) -> Path:
    plans = folder / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / name
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def new_session(api: TestClient, home: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    project = make_project(api, home)
    response = api.post(f"/api/projects/{project['id']}/sessions")
    assert response.status_code == 201
    return project, response.json()


def plan_url(session: dict[str, Any]) -> str:
    return f"/api/sessions/{session['session_id']}/plan"


def expected_plan(path: Path, done: int = 1) -> dict[str, Any]:
    return {
        "path": str(path), "title": "P", "total": 2, "done": done,
        "current": {"number": 2, "title": "B"},
    }


TASKS = [
    {"number": 1, "title": "A", "done": True},
    {"number": 2, "title": "B", "done": False},
]


# Plans of a project ------------------------------------------------------------


def test_project_plans_root_and_repositories_newest_first(api, home):
    project = make_project(api, home)
    root = Path(project["path"])
    a = write_plan(root, "a.md")
    write_plan(root, "b.md", NO_TASKS)
    (root / "sub" / ".git").mkdir(parents=True)
    c = write_plan(root / "sub", "c.md", "# Sub\n\n### Tarefa 1: X\n- [x] x\n")
    os.utime(a, (1_000, 1_000))
    os.utime(c, (2_000, 2_000))

    response = api.get(f"/api/projects/{project['id']}/plans")

    assert response.status_code == 200
    assert response.json() == [
        {"path": str(c), "title": "Sub", "total": 1, "done": 1},
        {"path": str(a), "title": "P", "total": 2, "done": 1},
    ]


def test_project_plans_none(api, home):
    project = make_project(api, home)
    assert api.get(f"/api/projects/{project['id']}/plans").json() == []


def test_project_plans_ignores_a_symlink_leaving_the_project(api, home, tmp_path):
    project = make_project(api, home)
    outside = write_plan(tmp_path / "fora", "x.md")
    plans = Path(project["path"]) / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    (plans / "x.md").symlink_to(outside)

    assert api.get(f"/api/projects/{project['id']}/plans").json() == []


def test_project_plans_unknown_project(api):
    assert api.get("/api/projects/999/plans").status_code == 404


def test_project_plans_unavailable_project(api, home):
    project = make_project(api, home)
    shutil.rmtree(project["path"])
    response = api.get(f"/api/projects/{project['id']}/plans")
    assert response.status_code == 200
    assert response.json() == []


# GET -----------------------------------------------------------------------------


def test_get_without_link(api, home):
    _, session = new_session(api, home)
    response = api.get(plan_url(session))
    assert response.status_code == 200
    assert response.json() == {"link": "auto", "path": None, "plan": None, "tasks": []}


def test_get_with_link_lists_tasks(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    assert api.put(plan_url(session), json={"path": str(plan)}).status_code == 200

    response = api.get(plan_url(session))

    assert response.json() == {
        "link": "manual", "path": str(plan), "plan": expected_plan(plan), "tasks": TASKS,
    }


def test_get_with_the_plan_deleted_keeps_the_path(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    api.put(plan_url(session), json={"path": str(plan)})
    plan.unlink()

    response = api.get(plan_url(session))

    assert response.status_code == 200
    assert response.json() == {"link": "manual", "path": str(plan), "plan": None, "tasks": []}


def test_get_sees_an_edit_of_the_plan(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    api.put(plan_url(session), json={"path": str(plan)})
    plan.write_text(PLAN_TEXT.replace("- [ ] b", "- [x] b"), encoding="utf-8")
    later = time.time() + 5
    os.utime(plan, (later, later))

    body = api.get(plan_url(session)).json()

    assert body["plan"]["done"] == 2 and body["plan"]["current"] is None
    assert [task["done"] for task in body["tasks"]] == [True, True]


def test_get_unknown_session(api):
    assert api.get(f"/api/sessions/{MISSING}/plan").status_code == 404


# PUT ---------------------------------------------------------------------------


def test_put_path_links_manually_and_publishes_the_progress(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    with connect_ws(api) as ws:
        response = api.put(plan_url(session), json={"path": str(plan)})
        assert response.status_code == 200
        assert response.json() == {
            "link": "manual", "path": str(plan), "plan": expected_plan(plan), "tasks": TASKS,
        }
        plans = []
        while expected_plan(plan) not in plans:
            event = receive(ws)
            if event["session_id"] == session["session_id"] and event["type"] == "session.updated":
                plans.append(event["data"].get("plan"))
    listed = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed[0]["plan"] == expected_plan(plan)


def test_put_path_is_idempotent(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    first = api.put(plan_url(session), json={"path": str(plan)})
    second = api.put(plan_url(session), json={"path": str(plan)})
    assert second.status_code == 200
    assert second.json() == first.json()


def test_put_replaces_an_earlier_link(api, home):
    project, session = new_session(api, home)
    a = write_plan(Path(project["path"]), "a.md")
    b = write_plan(Path(project["path"]), "b.md")
    api.put(plan_url(session), json={"path": str(a)})
    body = api.put(plan_url(session), json={"path": str(b)}).json()
    assert (body["link"], body["path"]) == ("manual", str(b))


def test_put_auto_goes_back_to_the_automatic_link(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    api.put(plan_url(session), json={"path": str(plan)})

    response = api.put(plan_url(session), json={"auto": True})

    assert response.status_code == 200
    body = response.json()
    assert body["link"] == "auto"
    assert body["path"] == str(plan) and body["plan"] == expected_plan(plan)


def test_put_auto_after_off(api, home):
    _, session = new_session(api, home)
    assert api.delete(plan_url(session)).json()["link"] == "off"
    body = api.put(plan_url(session), json={"auto": True}).json()
    assert body == {"link": "auto", "path": None, "plan": None, "tasks": []}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"path": "/x/docs/superpowers/plans/p.md", "auto": True},
        {"auto": False},
        {"path": ""},
        {"path": 3},
        {"path": None},
        {"path": "/x/docs/superpowers/plans/p.md", "extra": 1},
        [],
        "texto",
    ],
)
def test_put_invalid_body_is_400(api, home, body):
    _, session = new_session(api, home)
    response = api.put(plan_url(session), json=body)
    assert response.status_code == 400
    assert response.json()["detail"]


def test_put_without_a_body_or_with_broken_json_is_400(api, home):
    _, session = new_session(api, home)
    assert api.put(plan_url(session)).status_code == 400
    response = api.put(
        plan_url(session), content=b"{oops", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


def test_put_a_file_that_is_not_a_plan_is_400(api, home):
    project, session = new_session(api, home)
    root = Path(project["path"])
    no_tasks = write_plan(root, "notes.md", NO_TASKS)
    elsewhere = root / "README.md"
    elsewhere.write_text(PLAN_TEXT, encoding="utf-8")
    not_md = write_plan(root, "p.txt")
    missing = root / "docs" / "superpowers" / "plans" / "missing.md"
    for path in (no_tasks, elsewhere, not_md, missing, root / "docs"):
        response = api.put(plan_url(session), json={"path": str(path)})
        assert response.status_code == 400, path
        assert "plano" in response.json()["detail"]
    assert api.get(plan_url(session)).json()["path"] is None


def test_put_relative_path_is_400(api, home):
    _, session = new_session(api, home)
    response = api.put(plan_url(session), json={"path": "docs/superpowers/plans/p.md"})
    assert response.status_code == 400


def test_put_outside_a_registered_project_is_403(api, home, tmp_path):
    _, session = new_session(api, home)
    outside = write_plan(tmp_path / "fora")
    response = api.put(plan_url(session), json={"path": str(outside)})
    assert response.status_code == 403
    assert "projeto registrado" in response.json()["detail"]
    assert api.get(plan_url(session)).json()["path"] is None


def test_put_symlink_leaving_the_project_is_403(api, home, tmp_path):
    project, session = new_session(api, home)
    outside = write_plan(tmp_path / "fora", "x.md")
    plans = Path(project["path"]) / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True)
    (plans / "x.md").symlink_to(outside)

    response = api.put(plan_url(session), json={"path": str(plans / "x.md")})

    assert response.status_code == 403
    assert api.get(plan_url(session)).json()["path"] is None


def test_put_dotdot_leaving_the_project_is_403(api, home, tmp_path):
    project, session = new_session(api, home)
    outside = write_plan(tmp_path / "fora", "x.md")
    sneaky = Path(project["path"]) / ".." / ".." / ".." / outside.relative_to("/")
    response = api.put(plan_url(session), json={"path": str(sneaky)})
    assert response.status_code == 403


def test_put_a_plan_of_another_registered_project(api, home):
    _, session = new_session(api, home)
    other = make_project(api, home, "other")
    plan = write_plan(Path(other["path"]))
    body = api.put(plan_url(session), json={"path": str(plan)}).json()
    assert (body["link"], body["path"]) == ("manual", str(plan))


def test_put_unknown_session(api):
    response = api.put(f"/api/sessions/{MISSING}/plan", json={"auto": True})
    assert response.status_code == 404


# DELETE ------------------------------------------------------------------------


def test_delete_turns_the_plan_off(api, home):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    api.put(plan_url(session), json={"path": str(plan)})

    response = api.delete(plan_url(session))

    assert response.status_code == 200
    assert response.json() == {"link": "off", "path": None, "plan": None, "tasks": []}
    assert api.get(plan_url(session)).json()["link"] == "off"
    listed = api.get(f"/api/projects/{project['id']}/sessions").json()
    assert listed[0]["plan"] is None


def test_read_after_delete_does_not_link_again(api, home, factory):
    project, session = new_session(api, home)
    plan = write_plan(Path(project["path"]))
    api.delete(plan_url(session))
    factory.script = lambda content: tool_turn(
        session["session_id"], tool_name="Read", tool_input={"file_path": str(plan)}
    )

    api.post(f"/api/sessions/{session['session_id']}/messages", json={"text": "leia"})
    wait_state(api, session["session_id"], "idle")

    body = api.get(plan_url(session)).json()
    assert (body["link"], body["path"], body["plan"]) == ("off", None, None)


def test_delete_unknown_session(api):
    assert api.delete(f"/api/sessions/{MISSING}/plan").status_code == 404


# Protection ----------------------------------------------------------------------

READS = [
    ("GET", "/api/projects/1/plans", None),
    ("GET", f"/api/sessions/{MISSING}/plan", None),
]
WRITES = [
    ("PUT", f"/api/sessions/{MISSING}/plan", {"auto": True}),
    ("DELETE", f"/api/sessions/{MISSING}/plan", None),
]
FOREIGN = "http://evil.com:6660"


@pytest.mark.parametrize(("method", "url", "body"), READS + WRITES)
@pytest.mark.parametrize(
    ("base_url", "headers", "status"),
    [
        (BACKEND_URL, {"origin": APP_ORIGIN}, 403),  # no X-Maestro
        (BACKEND_URL, {"origin": "http://evil.com", "x-maestro": "1"}, 403),  # foreign Origin
        (FOREIGN, {"origin": APP_ORIGIN, "x-maestro": "1"}, 400),  # foreign Host
    ],
)
def test_plan_routes_are_protected(method, url, body, base_url, headers, status):
    with TestClient(create_app(), base_url=base_url) as client:
        response = client.request(method, url, json=body, headers=headers)
    assert response.status_code == status


@pytest.mark.parametrize(("method", "url", "body"), WRITES)
def test_plan_writes_need_an_origin(method, url, body):
    with TestClient(create_app(), base_url=BACKEND_URL) as client:
        response = client.request(method, url, json=body, headers={"x-maestro": "1"})
    assert response.status_code == 403
