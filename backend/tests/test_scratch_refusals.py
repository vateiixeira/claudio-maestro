"""The built-in "Sem projeto" has no git, plans, agents or tasks, and no file suggestions."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claudio_maestro import gitinfo
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
REFUSAL = "Conversas sem projeto não têm git, agentes nem tarefas."


@pytest.fixture
def api(home: Path, data_dir: Path):
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir),
        agent_factory=FakeAgentFactory(),
        history_exists=lambda sid, cwd: False,
    )
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as client:
        yield client


@pytest.fixture
def scratch(api: TestClient) -> dict:
    found = [p for p in api.get("/api/projects").json() if p["kind"] == "scratch"]
    assert len(found) == 1
    return found[0]


@pytest.fixture
def no_git(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args, **kwargs):
        raise AssertionError("git must not run for the scratch project")

    monkeypatch.setattr(gitinfo, "run_git", fail)


@pytest.mark.parametrize(
    "path",
    ["git", "git/details", "git/log", "git/branches", "git/commit", "git/compare"],
)
def test_git_get_routes_refuse_scratch(api, scratch, no_git, path):
    response = api.get(
        f"/api/projects/{scratch['id']}/{path}",
        params={"repo": scratch["path"], "ref": "main", "sha": "a" * 40},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == REFUSAL


def test_diff_refuses_scratch(api, scratch, no_git):
    response = api.get(
        f"/api/projects/{scratch['id']}/diff", params={"repo": scratch["path"], "file": "a.txt"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("git/fetch", None),
        ("git/stage", {"paths": ["a.txt"]}),
        ("git/commit", {"message": "x"}),
        ("git/fetch-repo", {}),
    ],
)
def test_git_post_routes_refuse_scratch(api, scratch, no_git, path, extra):
    body = None if extra is None else {"repo": scratch["path"], **extra}
    response = api.post(f"/api/projects/{scratch['id']}/{path}", json=body)
    assert response.status_code == 403
    assert response.json()["detail"] == REFUSAL


def test_session_changes_of_scratch_runs_no_git(api, scratch, no_git):
    session = api.post(f"/api/projects/{scratch['id']}/sessions").json()
    response = api.get(f"/api/sessions/{session['session_id']}/changes")
    assert response.status_code == 200


def test_plans_refuse_scratch(api, scratch):
    response = api.get(f"/api/projects/{scratch['id']}/plans")
    assert response.status_code == 403
    assert response.json()["detail"] == REFUSAL


def test_org_refuses_scratch(api, scratch):
    agent = api.post(
        "/api/agents", json={"name": "X", "slug": "x", "project_id": scratch["id"]}
    )
    assert agent.status_code == 403
    assert agent.json()["detail"] == REFUSAL
    assert api.get("/api/agents").json() == []
    task = api.post("/api/tasks", json={"project_id": scratch["id"], "title": "Tarefa"})
    assert task.status_code == 403
    assert task.json()["detail"] == REFUSAL


def test_org_still_works_for_regular_project(api, home):
    folder = home / "app"
    folder.mkdir()
    project = api.post(
        "/api/projects", json={"name": "app", "path": str(folder), "color": "#ff8800"}
    ).json()
    response = api.post("/api/tasks", json={"project_id": project["id"], "title": "Tarefa"})
    assert response.status_code == 201


def test_suggestion_files_empty_for_scratch(api, scratch, data_dir):
    folder = data_dir / "scratch" / "scratch-x"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "arquivo.txt").write_text("x")
    response = api.get(f"/api/projects/{scratch['id']}/files", params={"q": "arq"})
    assert response.status_code == 200
    assert response.json() == []


def test_suggestion_commands_still_work_for_scratch(api, scratch):
    response = api.get(f"/api/projects/{scratch['id']}/commands")
    assert response.status_code == 200
