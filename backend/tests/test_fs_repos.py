"""GET /api/fs/repos, `detached` in /api/fs/dirs and `limit_reached` in the project git route."""

import asyncio
import os
import time
from pathlib import Path

import pytest
from conftest import APP_ORIGIN
from git_helpers import git, make_repo

from claudio_maestro import history
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings


def repos(client, path) -> dict:
    response = client.get("/api/fs/repos", params={"path": str(path)})
    assert response.status_code == 200, response.text
    return response.json()


def fake_repo(path: Path) -> None:
    (path / ".git").mkdir(parents=True)


# /api/fs/dirs: detached ----------------------------------------------------


def test_dirs_detached_flag(client, home: Path):
    make_repo(home / "a", branch="dev")
    make_repo(home / "b")
    git(home / "b", "checkout", "-q", "--detach")
    (home / "c").mkdir()
    entries = {e["name"]: e for e in client.get("/api/fs/dirs").json()["entries"]}
    assert entries["a"]["detached"] is False and entries["a"]["branch"] == "dev"
    assert entries["b"]["detached"] is True
    assert entries["b"]["branch"] == git(home / "b", "rev-parse", "--short=7", "HEAD").strip()
    assert entries["c"]["detached"] is False and entries["c"]["branch"] is None


# /api/fs/repos -------------------------------------------------------------


def test_repos_of_a_folder(client, home: Path):
    root = home / "proj"
    make_repo(root / "api", branch="dev")
    make_repo(root / "web")
    git(root / "web", "checkout", "-q", "--detach")
    (root / "docs").mkdir()
    body = repos(client, root)
    assert body["limit_reached"] is False
    assert [r["rel_path"] for r in body["repos"]] == ["api", "web"]
    api, web = body["repos"]
    assert api == {
        "name": "api", "rel_path": "api", "path": str(root / "api"),
        "branch": "dev", "detached": False,
    }
    assert web["detached"] is True and web["branch"]


def test_repos_includes_the_folder_itself(client, home: Path):
    root = make_repo(home / "proj")
    make_repo(root / "sub")
    body = repos(client, root)
    assert [(r["name"], r["rel_path"]) for r in body["repos"]] == [("proj", "."), ("sub", "sub")]
    assert body["repos"][0]["path"] == str(root)


def test_repos_empty(client, home: Path):
    (home / "plain").mkdir()
    assert repos(client, home / "plain") == {"repos": [], "limit_reached": False}


def test_repos_three_levels_and_ignored_folders(client, home: Path):
    root = home / "proj"
    make_repo(root / "a" / "b" / "c")  # 3 levels: found
    make_repo(root / "a" / "b" / "c" / "d")  # 4 levels: not found
    make_repo(root / "node_modules" / "pkg")  # ignored
    make_repo(root / ".hidden" / "r")  # hidden
    body = repos(client, root)
    assert [r["rel_path"] for r in body["repos"]] == ["a/b/c"]


def test_repos_match_project_discovery(client, home: Path):
    """Same function as the project's repositories."""
    root = make_repo(home / "proj")
    make_repo(root / "x" / "y")
    make_repo(root / "vendor" / "z")
    expected = [str(p) for p in history.find_repositories(root)]
    assert [r["path"] for r in repos(client, root)["repos"][1:]] == expected


def test_repos_limit_reached(client, home: Path):
    root = home / "proj"
    for index in range(history.REPO_MAX_COUNT + 1):
        fake_repo(root / f"r{index:02d}")
    body = repos(client, root)
    assert body["limit_reached"] is True
    assert len(body["repos"]) == history.REPO_MAX_COUNT


def test_repos_exactly_at_limit_is_not_reached(client, home: Path):
    root = home / "proj"
    for index in range(history.REPO_MAX_COUNT):
        fake_repo(root / f"r{index:02d}")
    body = repos(client, root)
    assert body["limit_reached"] is False
    assert len(body["repos"]) == history.REPO_MAX_COUNT


def test_repos_broken_repository_has_no_branch(client, home: Path):
    fake_repo(home / "proj" / "quebrado")
    body = repos(client, home / "proj")
    assert body["repos"][0]["branch"] is None and body["repos"][0]["detached"] is False


def test_repos_spaces_and_accents(client, home: Path):
    root = home / "Área de trabalho" / "meu projeto"
    make_repo(root / "repositório ção", branch="ramo")
    body = repos(client, root)
    assert body["repos"] == [{
        "name": "repositório ção", "rel_path": "repositório ção",
        "path": str(root / "repositório ção"), "branch": "ramo", "detached": False,
    }]


def test_repos_outside_home_rejected(client, tmp_path: Path):
    assert client.get("/api/fs/repos", params={"path": str(tmp_path)}).status_code == 403
    assert client.get("/api/fs/repos", params={"path": "/"}).status_code == 403


def test_repos_dotdot_and_relative_rejected(client, home: Path):
    (home / "dev").mkdir()
    assert client.get("/api/fs/repos", params={"path": f"{home}/.."}).status_code == 403
    assert client.get("/api/fs/repos", params={"path": "dev"}).status_code == 403


def test_repos_missing_and_file(client, home: Path):
    (home / "file.txt").write_text("x")
    assert client.get("/api/fs/repos", params={"path": str(home / "nope")}).status_code == 404
    assert client.get("/api/fs/repos", params={"path": str(home / "file.txt")}).status_code == 400


def test_repos_requires_path(client):
    assert client.get("/api/fs/repos").status_code == 422


def test_repos_symlink_to_outside_rejected(client, home: Path, tmp_path: Path):
    outside = tmp_path / "fora"
    make_repo(outside / "segredo")
    os.symlink(outside, home / "atalho")
    assert client.get("/api/fs/repos", params={"path": str(home / "atalho")}).status_code == 403


def test_repos_symlink_inside_home_resolved(client, home: Path):
    make_repo(home / "real" / "r")
    os.symlink(home / "real", home / "alias")
    body = repos(client, home / "alias")
    assert [r["path"] for r in body["repos"]] == [str(home / "real" / "r")]


def test_repos_does_not_follow_links_inside_the_folder(client, home: Path, tmp_path: Path):
    outside = tmp_path / "fora"
    make_repo(outside / "segredo")
    root = home / "proj"
    root.mkdir()
    os.symlink(outside, root / "atalho")
    assert repos(client, root)["repos"] == []


def test_repos_needs_the_api_header(home: Path):
    from fastapi.testclient import TestClient

    from claudio_maestro.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:6660") as anon:
        response = anon.get("/api/fs/repos", params={"path": str(home)})
        assert response.status_code == 403


# Client gone -----------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.anyio
async def test_full_app_disconnect_stops_the_git_processes(
    home: Path, data_dir: Path, tmp_path: Path, monkeypatch
):
    """Whole ASGI app: `http.disconnect` while the preview runs kills its git
    processes instead of letting them run to the end (Starlette keeps the route)."""
    from claudio_maestro import gitinfo
    from claudio_maestro.api import fs as fs_api

    monkeypatch.setattr(fs_api, "DISCONNECT_POLL", 0.02)
    pids = tmp_path / "pids"
    fake = tmp_path / "hanginggit"
    fake.write_text(f"#!/bin/sh\necho $$ >> {pids}\nexec sleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    root = home / "proj"
    fake_repo(root / "a")
    fake_repo(root / "b")

    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "path": "/api/fs/repos", "raw_path": b"/api/fs/repos",
        "query_string": f"path={root}".encode(),
        "headers": [
            (b"host", b"localhost:6660"),
            (b"origin", APP_ORIGIN.encode()),
            (b"x-maestro", b"1"),
        ],
        "server": ("127.0.0.1", 6660), "client": ("127.0.0.1", 1),
        "scheme": "http", "root_path": "",
    }
    incoming: asyncio.Queue = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        return await incoming.get()

    async def send(message):
        pass

    async with app.router.lifespan_context(app):
        request = asyncio.create_task(app(scope, receive, send))
        for _ in range(250):
            await asyncio.sleep(0.02)
            if pids.exists() and len(pids.read_text().split()) >= 2:
                break
        started = [int(p) for p in pids.read_text().split()]
        assert len(started) == 2
        assert all(_pid_alive(p) for p in started)
        await incoming.put({"type": "http.disconnect"})
        # Well under GIT_TIMEOUT (5 s): the git limit must not be what ends it.
        await asyncio.wait_for(request, 2)
        # Nothing more is started after the client left.
        assert [int(p) for p in pids.read_text().split()] == started
        # The started ones die. What the route guarantees is that every git process was
        # sent SIGKILL by the time it answers: `asyncio.gather` finishes as soon as the
        # first child is cancelled, while a sibling may still be waiting for its own
        # process to be reaped. So wait for the condition with a deadline (far below the
        # 30 s of the fake git and the 5 s git limit) instead of reading it at once.
        deadline = time.monotonic() + 3
        while any(_pid_alive(p) for p in started) and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        assert not any(_pid_alive(p) for p in started)
