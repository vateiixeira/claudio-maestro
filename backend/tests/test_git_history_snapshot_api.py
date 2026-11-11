"""Validation of snapshot and direction query fields at the HTTP boundary."""

import pytest
from git_helpers import commit_file, git, make_repo
from test_git_api import add_project, api, build, factory, spawn  # noqa: F401


def test_route_follows_a_frozen_snapshot(api, home):
    root = make_repo(home / "proj")
    commit_file(root, "a.txt")
    project = add_project(api, root)
    url = f"/api/projects/{project['id']}/git/log"
    first = api.get(url, params={"repo": str(root), "limit": 1}).json()
    commit_file(root, "b.txt")
    response = api.get(url, params={
        "repo": str(root), "limit": 1, "skip": first["next_skip"],
        "snapshot_head": first["head_sha"], "snapshot_upstream": "-", "direction": "all",
    })
    assert response.status_code == 200
    assert response.json()["commits"][0]["subject"] == "inicial"


@pytest.mark.parametrize("extra", [
    {"direction": "--all"}, {"snapshot_head": "HEAD", "snapshot_upstream": "-"},
    {"snapshot_head": "a" * 40}, {"snapshot_upstream": "-"},
    {"snapshot_head": "a" * 40, "snapshot_upstream": "refs/remotes/origin/main"},
])
def test_route_rejects_unsafe_or_incomplete_snapshot(api, home, extra):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    response = api.get(f"/api/projects/{project['id']}/git/log", params={"repo": str(root), **extra})
    assert response.status_code == 422


def test_snapshot_missing_commit_is_not_found(api, home):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    response = api.get(f"/api/projects/{project['id']}/git/log", params={
        "repo": str(root), "snapshot_head": "0" * 40, "snapshot_upstream": "-",
    })
    assert response.status_code == 404


def test_scm_details_does_not_query_history(api, home, monkeypatch):
    from claudio_maestro import gitinfo
    root = make_repo(home / "proj")
    project = add_project(api, root)

    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(args)
        return []

    monkeypatch.setattr(gitinfo, "repo_commits", forbidden)
    response = api.get(f"/api/projects/{project['id']}/git/details")
    assert response.status_code == 200
    assert calls == []
    assert response.json()["repos"][0]["commits"] == []
    assert git(root, "status", "--porcelain") == ""


def test_route_defers_incoming_until_requested(api, home):
    from test_git_history_snapshots import diverged
    root = make_repo(home / "proj")
    diverged(root, 1, 2)
    project = add_project(api, root)
    url = f"/api/projects/{project['id']}/git/log"
    first = api.get(url, params={"repo": str(root), "include_incoming": "false"}).json()
    assert first["incoming"] == [] and first["incoming_count"] == 2
    incoming = api.get(url, params={
        "repo": str(root), "include_incoming": "false", "direction": "incoming",
    }).json()
    assert len(incoming["commits"]) == 2
