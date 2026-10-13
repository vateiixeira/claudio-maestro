"""GET routes of the history, commit, branches and compare."""


from git_helpers import commit_file, git, make_repo
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    api,
    build,
    factory,
    spawn,
)


def test_log_route(api, home):
    root = make_repo(home / "proj")
    sha = commit_file(root, "a.txt")
    project = add_project(api, root)
    body = api.get(f"/api/projects/{project['id']}/git/log", params={"repo": str(root)}).json()
    assert body["commits"][0]["full_hash"] == sha and body["branch"] == "main"


def test_log_route_with_ref_and_skip(api, home):
    root = make_repo(home / "proj")
    git(root, "switch", "-q", "-c", "feat")
    commit_file(root, "a.txt")
    project = add_project(api, root)
    url = f"/api/projects/{project['id']}/git/log"
    body = api.get(url, params={"repo": str(root), "ref": "refs/heads/feat", "skip": 1}).json()
    assert [c["subject"] for c in body["commits"]] == ["inicial"]
    assert api.get(url, params={"repo": str(root), "ref": "refs/heads/nada"}).status_code == 404
    assert api.get(url, params={"repo": str(root), "skip": -1}).status_code == 422
    assert api.get(url, params={"repo": str(root), "limit": 301}).status_code == 422


def test_repo_must_be_a_repository_of_the_project(api, home, tmp_path):
    root = make_repo(home / "proj")
    (root / "pasta").mkdir()
    outside = make_repo(tmp_path / "fora")
    project = add_project(api, root)
    url = f"/api/projects/{project['id']}/git/log"
    assert api.get(url, params={"repo": str(outside)}).status_code == 403
    assert api.get(url, params={"repo": str(root / "pasta")}).status_code == 400
    assert api.get(url, params={"repo": "../fora"}).status_code == 403


def test_nested_repository_is_accepted(api, home):
    root = home / "proj"
    make_repo(root / "api")
    project = add_project(api, root)
    response = api.get(f"/api/projects/{project['id']}/git/log", params={"repo": str(root / "api")})
    assert response.status_code == 200


def test_commit_routes(api, home):
    root = make_repo(home / "proj")
    sha = commit_file(root, "a.txt", "oi\n")
    project = add_project(api, root)
    base = f"/api/projects/{project['id']}/git/commit"
    detail = api.get(base, params={"repo": str(root), "sha": sha}).json()
    assert [f["path"] for f in detail["files"]] == ["a.txt"]
    diff = api.get(f"{base}/diff", params={"repo": str(root), "sha": sha, "file": "a.txt"}).json()
    assert "+oi" in diff["diff"] and diff["truncated"] is False
    assert api.get(f"{base}/diff", params={"repo": str(root), "sha": sha, "file": "README.md"}).status_code == 404
    assert api.get(base, params={"repo": str(root), "sha": "HEAD"}).status_code == 400
    assert api.get(base, params={"repo": str(root), "sha": "0" * 40}).status_code == 404


def test_branches_and_compare_routes(api, home):
    root = make_repo(home / "proj")
    git(root, "switch", "-q", "-c", "feat")
    commit_file(root, "a.txt")
    git(root, "switch", "-q", "main")
    project = add_project(api, root)
    branches = api.get(f"/api/projects/{project['id']}/git/branches", params={"repo": str(root)}).json()
    assert {b["name"] for b in branches["local"]} == {"main", "feat"}
    compare = api.get(
        f"/api/projects/{project['id']}/git/compare", params={"repo": str(root), "ref": "refs/heads/feat"}
    ).json()
    assert compare == {"incoming": 1}


def test_details_carry_state(api, home):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    repo = api.get(f"/api/projects/{project['id']}/git/details").json()["repos"][0]
    assert repo["state"]["merging"] is False and repo["head_sha"]


def test_get_routes_need_the_maestro_header(api, home):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    response = api.get(
        f"/api/projects/{project['id']}/git/log", params={"repo": str(root)}, headers={"x-maestro": ""}
    )
    assert response.status_code == 403
