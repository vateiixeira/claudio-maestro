"""Comparison routes validate repositories, refs, snapshots and paths."""

import pytest
from git_helpers import commit_file, git, make_repo
from test_git_api import add_project, api, build, factory, spawn  # noqa: F401
from test_git_comparison import diverged


def test_comparison_routes(api, home):
    repo = make_repo(home / "project")
    _, head, base = diverged(repo)
    project = add_project(api, repo)
    url = f"/api/projects/{project['id']}/git/comparison"
    response = api.get(url, params={"repo": str(repo), "base": "refs/heads/main"})
    assert response.status_code == 200
    assert response.json()["head_sha"] == head
    snapshot = {"repo": str(repo), "head_sha": head, "base_sha": base, "direction": "ahead"}
    assert api.get(url + "/commits", params=snapshot).json()["commits"][0]["subject"] == "add feature.txt"
    assert api.get(url + "/files", params=snapshot).json()["files"][0]["path"] == "feature.txt"
    diff = api.get(url + "/diff", params={**snapshot, "file": "feature.txt"})
    assert diff.status_code == 200 and "+feature" in diff.json()["diff"]
    assert api.get(url + "/diff", params={**snapshot, "file": "../outside"}).status_code == 403
    assert api.get(url, params={"repo": str(home.parent), "base": "refs/heads/main"}).status_code == 403
    assert api.get(url, params={"repo": str(repo), "base": "refs/heads/deleted"}).status_code == 404


@pytest.mark.parametrize("extra", [
    {"head_sha": "HEAD"}, {"base_sha": "--all"}, {"direction": "--all"},
    {"skip": -1}, {"limit": 301},
])
def test_snapshot_validation(api, home, extra):
    repo = make_repo(home / "project")
    _, head, base = diverged(repo)
    project = add_project(api, repo)
    response = api.get(f"/api/projects/{project['id']}/git/comparison/commits", params={
        "repo": str(repo), "head_sha": head, "base_sha": base, "direction": "ahead", **extra,
    })
    assert response.status_code == 422


def test_unrelated_files_are_recoverable_and_commits_remain_readable(api, home):
    repo = make_repo(home / "project")
    git(repo, "checkout", "--orphan", "other")
    git(repo, "rm", "-rf", ".")
    commit_file(repo, "other.txt")
    project = add_project(api, repo)
    url = f"/api/projects/{project['id']}/git/comparison"
    meta = api.get(url, params={"repo": str(repo), "base": "refs/heads/main"}).json()
    snapshot = {"repo": str(repo), "head_sha": meta["head_sha"], "base_sha": meta["base_sha"], "direction": "ahead"}
    assert api.get(url + "/commits", params=snapshot).status_code == 200
    response = api.get(url + "/files", params=snapshot)
    assert response.status_code == 409 and "ancestral" in response.json()["detail"]


def test_linked_worktree_and_escaping_file(api, home, tmp_path):
    repo = make_repo(home / "project")
    wt = tmp_path / "linked"
    git(repo, "worktree", "add", "-qb", "feature", str(wt))
    commit_file(wt, "feature.txt")
    project = add_project(api, repo)
    url = f"/api/projects/{project['id']}/git/comparison"
    response = api.get(url, params={"repo": str(wt), "base": "refs/heads/main"})
    assert response.status_code == 200
    meta = response.json()
    (wt / "outside-link").symlink_to(tmp_path)
    snapshot = {"repo": str(wt), "head_sha": meta["head_sha"], "base_sha": meta["base_sha"], "direction": "ahead"}
    assert api.get(url + "/diff", params={**snapshot, "file": "outside-link/private"}).status_code == 403
    assert api.get(url + "/diff", params={**snapshot, "file": "feature.txt"}).status_code == 200
    assert api.get(url + "/commits", params={**snapshot, "head_sha": "0" * 40}).status_code == 404
