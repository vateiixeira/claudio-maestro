"""Turn-end publishing, the single status call of the details and failure isolation."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from git_helpers import git, make_repo
from test_git_api import add_project, api, build, factory, spawn  # noqa: F401 (fixtures)
from test_git_details import commit_file, make_clone
from test_sessions_api import APP_ORIGIN, BACKEND_URL
from vibing import gitinfo


def git_events_of(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "project.git"]


# Turn end always publishes, the periodic check only on change ------------------------


def test_turn_end_publishes_without_summary_change(factory, spawn, home, data_dir):  # noqa: F811
    app = build(factory, spawn, home, data_dir)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as client:
        root = make_repo(home / "proj")
        (root / "README.md").write_text("linha 1\nmudou\n")  # already modified
        project = add_project(client, root)
        monitor = app.state.git_monitor
        client.portal.call(monitor.refresh_project, project["id"])
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]

        async def turn_ends() -> None:
            app.state.sessions._on_turn_end(project["id"])
            await asyncio.gather(*list(app.state.background))

        # Claude edits the same file again: the summary (counts) is identical.
        (root / "README.md").write_text("linha 1\nmudou\nmais\nmais\n")
        client.portal.call(turn_ends)
        assert len(git_events_of(events)) == 1
        client.portal.call(turn_ends)
        assert len(git_events_of(events)) == 2


def test_refresh_without_force_does_not_repeat(factory, spawn, home, data_dir):  # noqa: F811
    app = build(factory, spawn, home, data_dir)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as client:
        root = make_repo(home / "proj")
        project = add_project(client, root)
        monitor = app.state.git_monitor
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]
        client.portal.call(monitor.refresh_project, project["id"])
        client.portal.call(monitor.refresh_project, project["id"])
        client.portal.call(monitor.refresh_all)
        client.portal.call(monitor.refresh_all)
        assert len(git_events_of(events)) == 1
        client.portal.call(monitor.refresh_project, project["id"], True)
        assert len(git_events_of(events)) == 2
        # A forced publish keeps the last summary, so the next plain check stays quiet.
        client.portal.call(monitor.refresh_all)
        assert len(git_events_of(events)) == 2


# Details come from one status call ---------------------------------------------------


@pytest.mark.anyio
async def test_details_run_status_once(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    (repo / "solto.txt").write_text("x")
    calls: list[tuple] = []
    original = gitinfo.run_git

    async def spy(path, *args, **kwargs):
        calls.append(args)
        return await original(path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", spy)
    await gitinfo.repo_details(repo)
    assert sum(1 for args in calls if args[0] == "status") == 1


@pytest.mark.anyio
async def test_details_summary_matches_status(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    commit_file(clone, "a.txt")
    (clone / "README.md").write_text("linha 1\nmudou\n")
    (clone / "novo.txt").write_text("n\n")
    git(clone, "add", "novo.txt")
    (clone / "solto.txt").write_text("x")
    status = await gitinfo.repo_status(clone)
    detail = await gitinfo.repo_details(clone)
    assert {k: detail[k] for k in status.to_dict()} == status.to_dict()


@pytest.mark.anyio
async def test_details_summary_detached_and_no_commits(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach")
    detail = await gitinfo.repo_details(clone)
    assert detail["detached"] is True and detail["branch"] is None and detail["head"]
    empty = await gitinfo.repo_details(make_repo(tmp_path / "e", commit=False))
    assert empty["head"] is None and empty["branch"] == "main" and empty["error"] is None


@pytest.mark.anyio
async def test_details_count_untracked_by_file_status_by_folder(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "pasta").mkdir()
    (repo / "pasta" / "a.txt").write_text("a")
    (repo / "pasta" / "b.txt").write_text("b")
    assert (await gitinfo.repo_status(repo)).changed["untracked"] == 1
    detail = await gitinfo.repo_details(repo)
    assert detail["changed"]["untracked"] == 2


@pytest.mark.anyio
async def test_details_rename_counts(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "LEIAME.md")
    (repo / "LEIAME.md").write_text("linha 1\nlinha 2\nmais\n")
    status = await gitinfo.repo_status(repo)
    detail = await gitinfo.repo_details(repo)
    assert detail["changed"] == status.changed == {"staged": 1, "unstaged": 1, "untracked": 0}


# Nested repositories are not files -----------------------------------------------------


@pytest.mark.anyio
async def test_files_skip_nested_repository_folder(tmp_path: Path):
    root = make_repo(tmp_path / "proj")
    make_repo(root / "sub")
    (root / "solto.txt").write_text("x")
    files, _ = await gitinfo.repo_files(root)
    assert [f["path"] for f in files] == ["solto.txt"]
    detail = await gitinfo.repo_details(root)
    assert [f["path"] for f in detail["files"]] == ["solto.txt"]
    assert detail["changed"]["untracked"] == 1


@pytest.mark.anyio
async def test_project_details_nested_repo_listed_once(tmp_path: Path):
    root = make_repo(tmp_path / "proj")
    make_repo(root / "sub")
    repos, _ = await gitinfo.project_details_scan(root)
    by_name = {r["rel_path"]: r for r in repos}
    assert by_name["."]["files"] == []
    assert by_name["sub"]["error"] is None


# Failures after a good status stay inside the repository ----------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("target", ["repo_commits", "_repo_files"])
async def test_late_git_failure_is_isolated(tmp_path: Path, monkeypatch, target):
    root = tmp_path / "proj"
    make_repo(root / "good")
    make_repo(root / "bad")
    original = getattr(gitinfo, target)

    async def flaky(repo, *args, **kwargs):
        if repo.name == "bad":
            raise gitinfo.GitError("falhou depois do status")
        return await original(repo, *args, **kwargs)

    monkeypatch.setattr(gitinfo, target, flaky)
    repos, _ = await gitinfo.project_details_scan(root)
    by_name = {r["rel_path"]: r for r in repos}
    assert by_name["bad"]["error"] == "falhou depois do status"
    assert by_name["bad"]["files"] == [] and by_name["bad"]["commits"] == []
    assert by_name["bad"]["files_truncated"] is False
    assert by_name["good"]["error"] is None and by_name["good"]["commits"]


@pytest.mark.anyio
async def test_unexpected_exception_is_isolated(tmp_path: Path, monkeypatch, caplog):
    root = tmp_path / "proj"
    make_repo(root / "good")
    make_repo(root / "bad")
    original = gitinfo.repo_commits

    async def boom(repo, *args, **kwargs):
        if repo.name == "bad":
            raise ValueError("inesperado")
        return await original(repo, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "repo_commits", boom)
    repos, limit_reached = await gitinfo.project_details_scan(root)
    by_name = {r["rel_path"]: r for r in repos}
    assert limit_reached is False
    assert by_name["bad"]["error"] and "inesperado" not in by_name["bad"]["error"]
    assert by_name["bad"]["files"] == [] and by_name["bad"]["commits"] == []
    assert by_name["good"]["error"] is None and by_name["good"]["commits"]
    assert "inesperado" in caplog.text
