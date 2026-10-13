"""POST routes of the write actions: validation, answers and errors."""

import pytest
from git_helpers import git, git_home, make_repo, set_identity  # noqa: F401 (fixture)
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    api,
    build,
    factory,
    spawn,
)

from claudio_maestro import gitinfo, gitops


@pytest.fixture(autouse=True)
def fresh_policy():
    gitinfo.clear_policy_cache()
    yield


def project_with_repo(api, home):
    root = make_repo(home / "proj")
    set_identity(root)
    return add_project(api, root), root


def post(api, project, action, **body):
    return api.post(f"/api/projects/{project['id']}/git/{action}", json=body)


def test_stage_route_answers_with_the_repository(api, home, git_home):
    project, root = project_with_repo(api, home)
    (root / "README.md").write_text("mudou\n")
    response = post(api, project, "stage", repo=str(root), paths=["README.md"])
    assert response.status_code == 200, response.text
    files = response.json()["repo"]["files"]
    assert {(f["path"], f["status"]) for f in files} == {("README.md", "staged")}


def test_commit_route(api, home, git_home):
    project, root = project_with_repo(api, home)
    (root / "a.txt").write_text("a\n")
    response = post(api, project, "commit", repo=str(root), message="Adicionar a")
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["files"] == []
    assert git(root, "log", "-1", "--format=%s").strip() == "Adicionar a"


@pytest.mark.parametrize("path", ["../fora.txt", ".git/config", "/etc/passwd", "a\u0000b"])
def test_paths_outside_the_repository_are_refused(api, home, git_home, path):
    project, root = project_with_repo(api, home)
    response = post(api, project, "stage", repo=str(root), paths=[path])
    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert response.json()["detail"]["code"] == "invalid"


def test_link_inside_the_repository_is_staged_as_a_link(api, home, git_home):
    project, root = project_with_repo(api, home)
    (root / "docs").mkdir()
    (root / "docs" / "atalho").symlink_to("/etc")
    response = post(api, project, "stage", repo=str(root), paths=["docs/atalho"])
    assert response.status_code == 200, response.text
    assert git(root, "ls-files", "-s", "docs/atalho").startswith("120000 ")


def test_bodies_are_strict(api, home, git_home):
    project, root = project_with_repo(api, home)
    assert post(api, project, "stage", repo=str(root), paths=["a"], extra=1).status_code == 422
    assert post(api, project, "stage", repo=str(root), paths=[]).status_code == 422
    assert post(api, project, "stage", repo=str(root), paths=["a"] * (gitops.MAX_PATHS + 1)).status_code == 422
    assert post(api, project, "commit", repo=str(root), message="x" * (gitops.MAX_MESSAGE + 1)).status_code == 422
    assert post(api, project, "commit", repo=str(root), message="com\u0000nul").status_code == 422


def test_errors_carry_code_message_and_output(api, home, git_home, monkeypatch):
    project, root = project_with_repo(api, home)

    async def busy(repo, paths):
        raise gitops.RepoBusyError(gitops.BUSY_MESSAGE)

    monkeypatch.setattr(gitops, "stage", busy)
    response = post(api, project, "stage", repo=str(root), paths=["README.md"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "busy", "message": gitops.BUSY_MESSAGE, "output": ""}


def test_empty_commit_message_is_400(api, home, git_home):
    project, root = project_with_repo(api, home)
    (root / "a.txt").write_text("a\n")
    response = post(api, project, "commit", repo=str(root), message="   ")
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == gitops.EMPTY_MESSAGE


def test_action_publishes_project_git(api, home, git_home, monkeypatch):
    project, root = project_with_repo(api, home)
    calls = []
    monitor = api.app.state.git_monitor
    original = monitor.refresh_project

    async def spy(project_id, force=False):
        calls.append((project_id, force))
        await original(project_id, force=force)

    monkeypatch.setattr(monitor, "refresh_project", spy)
    (root / "README.md").write_text("mudou\n")
    assert post(api, project, "stage", repo=str(root), paths=["README.md"]).status_code == 200
    assert (project["id"], True) in calls


def test_write_route_needs_the_app_origin(api, home, git_home):
    project, root = project_with_repo(api, home)
    response = api.post(
        f"/api/projects/{project['id']}/git/stage", json={"repo": str(root), "paths": ["README.md"]},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_repo_outside_the_project_is_refused(api, home, git_home, tmp_path):
    project, _ = project_with_repo(api, home)
    outside = make_repo(tmp_path / "fora")
    assert post(api, project, "stage", repo=str(outside), paths=["README.md"]).status_code == 403
