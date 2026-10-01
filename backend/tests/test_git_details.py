"""Upstream/ahead/behind, changed files and recent commits, plus /git/details."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git_helpers import GIT_ENV, git, make_repo
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    api,
    build,
    factory,
    spawn,
)
from test_sessions_api import APP_ORIGIN, BACKEND_URL

from claudio_maestro import gitinfo


def init_bare(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)], check=True, env=GIT_ENV)


def clone_to(remote: Path, path: Path) -> None:
    subprocess.run(["git", "clone", "-q", str(remote), str(path)], check=True, env=GIT_ENV)


def make_clone(tmp_path: Path) -> tuple[Path, Path]:
    """A bare "remote" and a repository tracking it with one pushed commit."""
    remote = tmp_path / "remote.git"
    init_bare(remote)
    clone = make_repo(tmp_path / "clone")
    git(clone, "remote", "add", "origin", str(remote))
    git(clone, "push", "-q", "-u", "origin", "main")
    return remote, clone


def commit_file(repo: Path, name: str, text: str = "x\n") -> None:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


def by_key(files: list[dict]) -> dict[tuple[str, str], dict]:
    return {(f["path"], f["status"]): f for f in files}


# Upstream ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_upstream_in_sync(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    status = await gitinfo.repo_status(clone)
    assert (status.upstream, status.ahead, status.behind) == ("origin/main", 0, 0)
    assert status.to_dict()["upstream"] == "origin/main"


@pytest.mark.anyio
async def test_upstream_ahead_and_behind(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    other = tmp_path / "other"
    clone_to(remote, other)
    commit_file(other, "remoto.txt")
    commit_file(other, "remoto2.txt")
    git(other, "push", "-q")
    commit_file(clone, "local.txt")
    git(clone, "fetch", "-q")
    status = await gitinfo.repo_status(clone)
    assert (status.upstream, status.ahead, status.behind) == ("origin/main", 1, 2)


@pytest.mark.anyio
async def test_no_upstream(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    status = await gitinfo.repo_status(repo)
    assert (status.upstream, status.ahead, status.behind) == (None, None, None)


@pytest.mark.anyio
async def test_upstream_gone(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    git(clone, "config", "branch.main.merge", "refs/heads/sumiu")
    status = await gitinfo.repo_status(clone)
    assert status.error is None
    assert status.ahead is None and status.behind is None


@pytest.mark.anyio
async def test_detached_has_no_upstream(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach")
    status = await gitinfo.repo_status(clone)
    assert (status.upstream, status.ahead, status.behind) == (None, None, None)


# Changed files -----------------------------------------------------------------


@pytest.mark.anyio
async def test_files_clean(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    assert await gitinfo.repo_files(repo) == ([], False)


@pytest.mark.anyio
async def test_files_statuses_and_counts(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("linha 1\nnova\nmais\n")  # unstaged: +2 -1
    (repo / "novo.txt").write_text("a\nb\nc\n")
    git(repo, "add", "novo.txt")  # staged: +3
    (repo / "solto.txt").write_text("x\n")  # untracked
    files, truncated = await gitinfo.repo_files(repo)
    assert truncated is False
    assert by_key(files) == {
        ("README.md", "unstaged"): {"path": "README.md", "status": "unstaged", "added": 2, "removed": 1},
        ("novo.txt", "staged"): {"path": "novo.txt", "status": "staged", "added": 3, "removed": 0},
        ("solto.txt", "untracked"): {"path": "solto.txt", "status": "untracked", "added": None, "removed": None},
    }


@pytest.mark.anyio
async def test_file_staged_and_unstaged_listed_twice(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("linha 1\nlinha 2\nstaged\n")
    git(repo, "add", "README.md")
    (repo / "README.md").write_text("linha 1\nlinha 2\nstaged\nmais\nmais2\n")
    files, _ = await gitinfo.repo_files(repo)
    found = by_key(files)
    assert found[("README.md", "staged")]["added"] == 1
    assert found[("README.md", "unstaged")]["added"] == 2
    assert len(files) == 2


@pytest.mark.anyio
async def test_file_deleted(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").unlink()
    files, _ = await gitinfo.repo_files(repo)
    assert files == [{"path": "README.md", "status": "unstaged", "added": 0, "removed": 2}]


@pytest.mark.anyio
async def test_file_renamed_uses_new_path(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "LEIAME.md")
    files, _ = await gitinfo.repo_files(repo)
    assert files == [{"path": "LEIAME.md", "status": "staged", "added": 0, "removed": 0}]


@pytest.mark.anyio
async def test_file_renamed_and_edited(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("linha 1\nlinha 2\nlinha 3\n")
    git(repo, "commit", "-q", "-am", "mais")
    git(repo, "mv", "README.md", "LEIAME.md")
    (repo / "LEIAME.md").write_text("linha 1\nlinha 2\nlinha 3\nlinha 4\n")
    files, _ = await gitinfo.repo_files(repo)
    found = by_key(files)
    assert ("LEIAME.md", "staged") in found and ("LEIAME.md", "unstaged") in found
    assert found[("LEIAME.md", "unstaged")]["added"] == 1
    assert not any(f["path"] == "README.md" for f in files)


@pytest.mark.anyio
async def test_file_binary_has_no_counts(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "img.bin").write_bytes(b"\x00\x01\x02\x00")
    git(repo, "add", "img.bin")
    git(repo, "commit", "-q", "-m", "bin")
    (repo / "img.bin").write_bytes(b"\x00\x09\x09\x00\x00")
    (repo / "novo.bin").write_bytes(b"\x00\x01")
    git(repo, "add", "novo.bin")
    files, _ = await gitinfo.repo_files(repo)
    found = by_key(files)
    assert found[("img.bin", "unstaged")]["added"] is None
    assert found[("img.bin", "unstaged")]["removed"] is None
    assert found[("novo.bin", "staged")]["added"] is None


@pytest.mark.anyio
async def test_file_names_with_spaces_and_unicode(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "dir com espaço").mkdir()
    (repo / "dir com espaço" / "ação é.txt").write_text("a\n")
    git(repo, "add", "-A")
    (repo / "dir com espaço" / "ação é.txt").write_text("a\nb\n")
    (repo / "outro ñ.txt").write_text("x")
    files, _ = await gitinfo.repo_files(repo)
    found = by_key(files)
    assert found[("dir com espaço/ação é.txt", "staged")]["added"] == 1
    assert found[("dir com espaço/ação é.txt", "unstaged")]["added"] == 1
    assert ("outro ñ.txt", "untracked") in found


@pytest.mark.anyio
async def test_files_untracked_listed_one_by_one(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "pasta").mkdir()
    (repo / "pasta" / "a.txt").write_text("a")
    (repo / "pasta" / "b.txt").write_text("b")
    files, _ = await gitinfo.repo_files(repo)
    assert [f["path"] for f in files] == ["pasta/a.txt", "pasta/b.txt"]


@pytest.mark.anyio
async def test_files_without_commits(tmp_path: Path):
    repo = make_repo(tmp_path / "r", commit=False)
    (repo / "a.txt").write_text("1\n2\n")
    git(repo, "add", "a.txt")
    (repo / "b.txt").write_text("x")
    files, _ = await gitinfo.repo_files(repo)
    found = by_key(files)
    assert found[("a.txt", "staged")]["added"] == 2
    assert ("b.txt", "untracked") in found


@pytest.mark.anyio
async def test_files_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gitinfo, "MAX_FILES", 5)
    repo = make_repo(tmp_path / "r")
    for index in range(8):
        (repo / f"f{index}.txt").write_text("x")
    files, truncated = await gitinfo.repo_files(repo)
    assert truncated is True and len(files) == 5
    assert [f["path"] for f in files] == [f"f{i}.txt" for i in range(5)]


@pytest.mark.anyio
async def test_files_exactly_at_limit_not_truncated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gitinfo, "MAX_FILES", 5)
    repo = make_repo(tmp_path / "r")
    for index in range(5):
        (repo / f"f{index}.txt").write_text("x")
    files, truncated = await gitinfo.repo_files(repo)
    assert truncated is False and len(files) == 5


def test_files_default_limit_is_200():
    assert gitinfo.MAX_FILES == 200


@pytest.mark.anyio
async def test_files_not_a_repo(tmp_path: Path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.repo_files(tmp_path / "plain")


# Commits -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_commits_without_upstream(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    commit_file(repo, "a.txt")
    commits = await gitinfo.repo_commits(repo, has_upstream=False)
    assert [c["subject"] for c in commits] == ["add a.txt", "inicial"]
    newest = commits[0]
    assert newest["full_hash"] == git(repo, "rev-parse", "HEAD").strip()
    assert newest["hash"] == newest["full_hash"][:7]
    assert newest["author"] == "Teste"
    assert "T" in newest["date"] and newest["date"][:2] == "20"
    assert all(c["pushed"] is None for c in commits)


@pytest.mark.anyio
async def test_commits_pushed_flags(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    commit_file(clone, "a.txt")
    commit_file(clone, "b.txt")
    commits = await gitinfo.repo_commits(clone, has_upstream=True)
    assert [(c["subject"], c["pushed"]) for c in commits] == [
        ("add b.txt", False), ("add a.txt", False), ("inicial", True),
    ]


@pytest.mark.anyio
async def test_commits_limit_ten(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    for index in range(12):
        commit_file(repo, f"f{index}.txt")
    commits = await gitinfo.repo_commits(repo, has_upstream=False)
    assert len(commits) == 10 and commits[0]["subject"] == "add f11.txt"


@pytest.mark.anyio
async def test_commits_subject_with_punctuation_and_body(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "título | com; vírgula \"e\" ação\n\ncorpo\ncorpo 2")
    commits = await gitinfo.repo_commits(repo, has_upstream=False)
    assert commits[0]["subject"] == "título | com; vírgula \"e\" ação"
    assert len(commits) == 2


@pytest.mark.anyio
async def test_commits_upstream_unresolvable_gives_none(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    commits = await gitinfo.repo_commits(repo, has_upstream=True)
    assert [c["pushed"] for c in commits] == [None]


@pytest.mark.anyio
async def test_commits_empty_repo(tmp_path: Path):
    repo = make_repo(tmp_path / "r", commit=False)
    assert await gitinfo.repo_commits(repo, has_upstream=False) == []


# repo_details ------------------------------------------------------------------


@pytest.mark.anyio
async def test_repo_details_combines(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    commit_file(clone, "a.txt")
    (clone / "solto.txt").write_text("x")
    detail = await gitinfo.repo_details(clone)
    assert detail["branch"] == "main" and detail["ahead"] == 1
    assert detail["files"] == [
        {"path": "solto.txt", "status": "untracked", "added": None, "removed": None}
    ]
    assert detail["files_truncated"] is False
    assert [c["pushed"] for c in detail["commits"]] == [False, True]


@pytest.mark.anyio
async def test_repo_details_error_is_isolated(tmp_path: Path):
    root = tmp_path / "proj"
    make_repo(root / "good")
    broken = root / "broken"
    broken.mkdir()
    (broken / ".git").write_text("gitdir: /nao/existe\n")
    repos, limit_reached = await gitinfo.project_details_scan(root)
    by_name = {r["rel_path"]: r for r in repos}
    assert limit_reached is False
    assert by_name["broken"]["error"]
    assert by_name["broken"]["files"] == [] and by_name["broken"]["commits"] == []
    assert by_name["broken"]["files_truncated"] is False
    assert by_name["good"]["error"] is None
    assert by_name["good"]["commits"][0]["subject"] == "inicial"


# Routes ------------------------------------------------------------------------


def test_details_route_shape(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    make_repo(root / "api", branch="dev")
    (root / "api" / "README.md").write_text("linha 1\nmudou\n")
    project = add_project(api, root)
    response = api.get(f"/api/projects/{project['id']}/git/details")
    assert response.status_code == 200
    body = response.json()
    assert body["limit_reached"] is False
    assert [r["rel_path"] for r in body["repos"]] == [".", "api"]
    api_repo = body["repos"][1]
    assert set(api_repo) == {
        "path", "rel_path", "branch", "detached", "head", "changed", "upstream",
        "ahead", "behind", "error", "files", "files_truncated", "commits",
    }
    assert api_repo["branch"] == "dev" and api_repo["upstream"] is None
    assert api_repo["files"] == [
        {"path": "README.md", "status": "unstaged", "added": 1, "removed": 1}
    ]
    assert set(api_repo["commits"][0]) == {
        "hash", "full_hash", "subject", "author", "date", "pushed",
    }


def test_details_route_unknown_project(api):  # noqa: F811
    assert api.get("/api/projects/999/git/details").status_code == 404


def test_details_route_requires_header(api, home):  # noqa: F811
    project = add_project(api, make_repo(home / "proj"))
    response = api.get(
        f"/api/projects/{project['id']}/git/details", headers={"x-maestro": ""}
    )
    assert response.status_code in (400, 403)
    assert api.get(f"/api/projects/{project['id']}/git/details").status_code == 200


def test_details_route_unavailable_folder(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    project = add_project(api, root)
    shutil.rmtree(root)
    assert api.get(f"/api/projects/{project['id']}/git/details").json() == {
        "repos": [], "limit_reached": False,
    }


def test_details_route_without_repo(api, home):  # noqa: F811
    project = add_project(api, home / "plain")
    assert api.get(f"/api/projects/{project['id']}/git/details").json() == {
        "repos": [], "limit_reached": False,
    }


def test_details_route_error_in_one_repo(api, home):  # noqa: F811
    root = home / "proj"
    make_repo(root / "good")
    (root / "broken").mkdir(parents=True)
    (root / "broken" / ".git").write_text("gitdir: /nao/existe\n")
    project = add_project(api, root)
    body = api.get(f"/api/projects/{project['id']}/git/details").json()
    repos = {r["rel_path"]: r for r in body["repos"]}
    assert repos["broken"]["error"] and repos["broken"]["files"] == []
    assert repos["good"]["error"] is None and repos["good"]["commits"]


def test_git_route_includes_upstream_fields(api, home):  # noqa: F811
    project = add_project(api, make_repo(home / "proj"))
    (repo,) = api.get(f"/api/projects/{project['id']}/git").json()["repos"]
    assert (repo["upstream"], repo["ahead"], repo["behind"]) == (None, None, None)


# Diff route for staged / untracked files ------------------------------------------


def diff(api, project, repo, file):
    return api.get(f"/api/projects/{project['id']}/diff", params={"repo": repo, "file": file})


def test_diff_route_untracked_staged_and_spaces(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    (root / "novo arquivo.txt").write_text("um\ndois\n")
    (root / "staged.txt").write_text("s1\n")
    git(root, "add", "staged.txt")
    (root / "README.md").write_text("linha 1\nlinha 2\nextra\n")
    git(root, "add", "README.md")
    project = add_project(api, root)
    assert "+dois" in diff(api, project, ".", "novo arquivo.txt").json()["diff"]
    assert "+s1" in diff(api, project, ".", "staged.txt").json()["diff"]
    assert "+extra" in diff(api, project, ".", "README.md").json()["diff"]


def test_diff_route_staged_deletion(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    git(root, "rm", "-q", "README.md")
    project = add_project(api, root)
    assert "-linha 1" in diff(api, project, ".", "README.md").json()["diff"]


def test_diff_route_untracked_truncated(api, home, monkeypatch):  # noqa: F811
    monkeypatch.setattr(gitinfo, "DIFF_LIMIT", 40)
    root = make_repo(home / "proj")
    (root / "grande.txt").write_text("y" * 500 + "\n")
    project = add_project(api, root)
    body = diff(api, project, ".", "grande.txt").json()
    assert body["truncated"] is True and len(body["diff"]) == 40


# project.git event considers the new fields -----------------------------------------


def test_monitor_publishes_when_only_behind_changes(factory, spawn, home, data_dir):  # noqa: F811
    app = build(factory, spawn, home, data_dir)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as client:
        remote = home / "remote.git"
        init_bare(remote)
        root = make_repo(home / "proj")
        git(root, "remote", "add", "origin", str(remote))
        git(root, "push", "-q", "-u", "origin", "main")
        project = add_project(client, root)
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]
        monitor = app.state.git_monitor
        client.portal.call(monitor.refresh_project, project["id"])
        other = home / "other"
        clone_to(remote, other)
        commit_file(other, "remoto.txt")
        git(other, "push", "-q")
        git(root, "fetch", "-q")
        client.portal.call(monitor.refresh_project, project["id"])
        sent = [e for e in events if e["type"] == "project.git"]
        assert len(sent) == 2
        assert sent[0]["data"]["repos"][0]["behind"] == 0
        assert sent[1]["data"]["repos"][0]["behind"] == 1
        assert sent[1]["data"]["repos"][0]["upstream"] == "origin/main"
