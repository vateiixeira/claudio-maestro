"""POST routes of the write actions: validation, answers and errors."""

import subprocess

import pytest
from git_helpers import (  # noqa: F401 (fixture)
    GIT_ENV,
    git,
    git_home,
    make_repo,
    set_identity,
)
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    api,
    build,
    factory,
    spawn,
)
from test_gitinfo_fetch import LOCAL_OK, push_from_elsewhere

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


@pytest.mark.parametrize("action", ["stage", "discard"])
def test_policy_failure_is_a_409_with_a_message_not_a_500(api, home, git_home, monkeypatch, action):
    project, root = project_with_repo(api, home)
    (root / "README.md").write_text("mudou\n")

    async def broken(repo, cached=True):
        raise gitinfo.GitError("O git demorou demais para responder.")

    monkeypatch.setattr(gitinfo, "repo_policy", broken)
    response = post(api, project, action, repo=str(root), paths=["README.md"])
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "git"
    assert detail["message"] == "O git demorou demais para responder."


def test_policy_failure_message_has_no_credentials(api, home, git_home, monkeypatch):
    project, root = project_with_repo(api, home)

    async def broken(repo, cached=True):
        raise gitinfo.GitError("falhou em https://user:segredo@example.com/x.git")

    monkeypatch.setattr(gitinfo, "repo_policy", broken)
    response = post(api, project, "stage", repo=str(root), paths=["README.md"])
    assert response.status_code == 409
    assert "segredo" not in response.text


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


def conflicting(root):
    git(root, "switch", "-q", "-c", "feat")
    (root / "README.md").write_text("feat\n")
    git(root, "commit", "-q", "-am", "feat")
    git(root, "switch", "-q", "main")
    (root / "README.md").write_text("main\n")
    git(root, "commit", "-q", "-am", "main")


def test_switch_and_branch_routes(api, home, git_home):
    project, root = project_with_repo(api, home)
    git(root, "branch", "feat")
    response = post(api, project, "switch", repo=str(root), ref="refs/heads/feat")
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["branch"] == "feat"
    response = post(api, project, "branch", repo=str(root), name="fix/frete")
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["branch"] == "fix/frete"


def test_switch_route_refuses_other_refs(api, home, git_home):
    project, root = project_with_repo(api, home)
    assert post(api, project, "switch", repo=str(root), ref="main").status_code == 422
    assert post(api, project, "switch", repo=str(root), ref="refs/tags/v1").status_code == 422
    response = post(api, project, "switch", repo=str(root), ref="refs/heads/nao-existe")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_branch_route_with_space_is_400(api, home, git_home):
    project, root = project_with_repo(api, home)
    response = post(api, project, "branch", repo=str(root), name="fix carrinho")
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Nome de branch não pode ter espaço. Por exemplo: fix-carrinho."


def test_merge_flow_through_the_routes(api, home, git_home):
    project, root = project_with_repo(api, home)
    conflicting(root)
    response = post(api, project, "merge", repo=str(root), ref="refs/heads/feat")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conflicts"] is True
    assert body["repo"]["state"]["conflicts"] == ["README.md"]
    assert {(f["path"], f["status"]) for f in body["repo"]["files"]} >= {("README.md", "conflict")}
    (root / "README.md").write_text("os dois\n")
    assert post(api, project, "resolve", repo=str(root), paths=["README.md"]).status_code == 200
    response = post(api, project, "merge-continue", repo=str(root), message="Merge branch 'feat'")
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["state"]["merging"] is False


def test_merge_abort_route(api, home, git_home):
    project, root = project_with_repo(api, home)
    conflicting(root)
    post(api, project, "merge", repo=str(root), ref="refs/heads/feat")
    response = post(api, project, "merge-abort", repo=str(root))
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["state"]["merging"] is False
    response = post(api, project, "merge-abort", repo=str(root))
    assert response.status_code == 400
    assert response.json()["detail"]["message"] == gitops.NOT_MERGING


@pytest.fixture
def local_remotes(monkeypatch):
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", LOCAL_OK)


def project_with_clone(api, home, tmp_path):
    remote = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, env=GIT_ENV)
    root = make_repo(home / "proj")
    set_identity(root)
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "-q", "-u", "origin", "main")
    return add_project(api, root), root, remote


def test_network_routes(api, home, git_home, tmp_path, local_remotes):
    project, root, remote = project_with_clone(api, home, tmp_path)
    (root / "a.txt").write_text("a\n")
    git(root, "add", "a.txt")
    git(root, "commit", "-q", "-m", "A")
    response = post(api, project, "push", repo=str(root))
    assert response.status_code == 200, response.text
    assert response.json()["repo"]["ahead"] == 0
    push_from_elsewhere(tmp_path, remote)
    response = post(api, project, "pull", repo=str(root))
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] is False and response.json()["repo"]["behind"] == 0
    assert post(api, project, "sync", repo=str(root)).json()["conflicts"] is False
    assert post(api, project, "fetch-repo", repo=str(root)).status_code == 200
    git(root, "switch", "-q", "-c", "feat")
    response = post(api, project, "publish", repo=str(root))
    assert response.status_code == 200, response.text
    assert response.json()["remote"] == "origin"
    assert response.json()["repo"]["upstream"] == "origin/feat"


def test_push_rejection_is_409_with_output(api, home, git_home, tmp_path, local_remotes):
    project, root, remote = project_with_clone(api, home, tmp_path)
    push_from_elsewhere(tmp_path, remote)
    (root / "b.txt").write_text("b\n")
    git(root, "add", "b.txt")
    git(root, "commit", "-q", "-m", "B")
    response = post(api, project, "push", repo=str(root))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "git" and detail["message"].startswith("O envio não foi feito")
    assert "[rejected]" in detail["output"]
