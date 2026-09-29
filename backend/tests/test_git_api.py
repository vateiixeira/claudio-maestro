"""Git routes: repositories, diff, session changes, open in editor, events."""

import os
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from git_helpers import git, make_repo
from test_sessions_api import APP_ORIGIN, BACKEND_URL, WS_URL, receive, wait_state
from vibing.agent.fake import FakeAgentFactory, text_turn
from vibing.app import create_app
from vibing.config import Settings


class SpawnSpy:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.error = error

    async def __call__(self, argv: list[str]) -> None:
        if self.error:
            raise self.error
        self.calls.append(argv)


@pytest.fixture
def factory() -> FakeAgentFactory:
    return FakeAgentFactory()


@pytest.fixture
def spawn() -> SpawnSpy:
    return SpawnSpy()


def build(factory, spawn, home, data_dir, **settings):
    return create_app(
        settings=Settings(home_dir=home, data_dir=data_dir, **settings),
        agent_factory=factory,
        history_exists=lambda s, c: False,
        spawn_editor=spawn,
    )


@pytest.fixture
def api(factory, spawn, home, data_dir):
    with TestClient(
        build(factory, spawn, home, data_dir), base_url=BACKEND_URL,
        headers={"origin": APP_ORIGIN, "x-vibing": "1"},
    ) as c:
        yield c


def add_project(api: TestClient, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    response = api.post(
        "/api/projects", json={"name": folder.name, "path": str(folder), "color": "#ff8800"}
    )
    assert response.status_code == 201, response.text
    return response.json()


# Repositories --------------------------------------------------------------


def test_project_git(api, home):
    root = make_repo(home / "proj")
    make_repo(root / "api", branch="dev")
    git(root / "api", "checkout", "-q", "--detach")
    (root / "novo.txt").write_text("x")
    project = add_project(api, root)
    body = api.get(f"/api/projects/{project['id']}/git").json()
    repos = body["repos"]
    assert [r["rel_path"] for r in repos] == [".", "api"]
    assert repos[0] == {
        "path": str(root), "rel_path": ".", "branch": "main", "detached": False,
        "head": repos[0]["head"], "changed": {"staged": 0, "unstaged": 0, "untracked": 2},  # novo.txt + api/ (nested)
        "error": None,
    }
    assert repos[1]["detached"] is True and repos[1]["branch"] is None
    assert repos[1]["head"]


def test_project_git_without_repo(api, home):
    project = add_project(api, home / "plain")
    assert api.get(f"/api/projects/{project['id']}/git").json() == {"repos": []}


def test_project_git_unknown(api):
    assert api.get("/api/projects/999/git").status_code == 404


def test_fs_dirs_branch(api, home):
    make_repo(home / "a", branch="dev")
    (home / "b").mkdir()
    entries = {e["name"]: e for e in api.get("/api/fs/dirs").json()["entries"]}
    assert entries["a"]["git"] is True and entries["a"]["branch"] == "dev"
    assert entries["b"]["branch"] is None


# Diff ----------------------------------------------------------------------


def diff(api, project, repo, file):
    return api.get(f"/api/projects/{project['id']}/diff", params={"repo": repo, "file": file})


def test_diff_routes(api, home):
    root = home / "proj"
    make_repo(root / "api")
    (root / "api" / "README.md").write_text("linha 1\ntrocada\n")
    (root / "api" / "novo.txt").write_text("oi\n")
    project = add_project(api, root)

    body = diff(api, project, "api", "README.md").json()
    assert "+trocada" in body["diff"] and body["truncated"] is False
    assert "+oi" in diff(api, project, "api", "novo.txt").json()["diff"]
    git(root / "api", "checkout", "README.md")
    assert diff(api, project, "api", "README.md").json()["diff"] == ""


@pytest.mark.parametrize(
    ("repo", "file"),
    [("..", "x"), ("api", "../../fora.txt"), ("api", "/etc/passwd"), ("/tmp", "x")],
)
def test_diff_escape_rejected(api, home, repo, file):
    root = home / "proj"
    make_repo(root / "api")
    project = add_project(api, root)
    assert diff(api, project, repo, file).status_code == 403


def test_diff_symlink_escape_rejected(api, home, tmp_path):
    root = home / "proj"
    make_repo(root / "api")
    outside = tmp_path / "fora"
    make_repo(outside)
    os.symlink(outside, root / "link")
    os.symlink(outside / "README.md", root / "api" / "segredo.md")
    project = add_project(api, root)
    assert diff(api, project, "link", "README.md").status_code == 403
    assert diff(api, project, "api", "segredo.md").status_code == 403


def test_diff_repo_not_git(api, home):
    root = home / "proj"
    (root / "sem").mkdir(parents=True)
    project = add_project(api, root)
    assert diff(api, project, "sem", "a.txt").status_code == 400


# Session changes -----------------------------------------------------------


def test_session_changes(api, home, factory, monkeypatch):
    root = home / "proj"
    make_repo(root / "api", branch="dev")
    (root / "api" / "README.md").write_text("linha 1\nmudou\n")
    (root / "api" / "novo.py").write_text("x\n")
    git(root / "api", "add", "novo.py")
    git(root / "api", "commit", "-q", "-m", "novo")
    (root / "solto.txt").write_text("s")
    project = add_project(api, root)
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]

    items = [
        {"type": "tool", "name": "Edit", "input": {"file_path": str(root / "api" / "README.md")},
         "result": {"details": {"structuredPatch": [
             {"lines": [" linha 1", "-linha 2", "+mudou"]}]}}},
        {"type": "tool", "name": "Write", "input": {"file_path": str(root / "api" / "novo.py")},
         "result": {"details": {"structuredPatch": [{"lines": ["+x"]}]}}},
        {"type": "tool", "name": "MultiEdit",
         "input": {"file_path": str(root / "api" / "README.md")},
         "result": {"details": {"structuredPatch": [{"lines": ["+a", "+b"]}]}}},
        {"type": "tool", "name": "Read", "input": {"file_path": str(root / "api" / "x")},
         "result": None},
        {"type": "tool", "name": "Write", "input": {"file_path": str(root / "solto.txt")},
         "result": None},
    ]

    async def fake_open(session_id):
        return {"items": items}

    monkeypatch.setattr(api.app.state.sessions, "open", fake_open)
    body = api.get(f"/api/sessions/{sid}/changes").json()
    groups = {g["rel_path"]: g for g in body["repos"]}
    assert groups["api"]["branch"] == "dev"
    files = {f["rel_path"]: f for f in groups["api"]["files"]}
    assert files["README.md"] == {
        "path": str(root / "api" / "README.md"), "rel_path": "README.md",
        "added": 3, "removed": 1, "uncommitted": True,
    }
    assert files["novo.py"]["uncommitted"] is False
    assert files["novo.py"]["added"] == 1
    assert groups[None]["branch"] is None
    assert groups[None]["files"][0]["rel_path"] == "solto.txt"
    assert groups[None]["files"][0]["added"] is None


def test_session_changes_unknown(api):
    assert api.get("/api/sessions/nao-existe/changes").status_code == 404


# Open in editor ------------------------------------------------------------


def test_open_in_editor(api, home, spawn):
    root = home / "proj"
    project = add_project(api, root)
    (root / "a.txt").write_text("a")
    response = api.post("/api/open-in-editor", json={"path": str(root / "a.txt")})
    assert response.status_code == 204
    assert spawn.calls == [["code", str(root / "a.txt")]]

    api.put("/api/state/preferences", json={"editor_command": ["zed", "--new"]})
    api.post("/api/open-in-editor", json={"path": str(root)})
    assert spawn.calls[-1] == ["zed", "--new", str(root)]


def test_open_in_editor_outside_rejected(api, home, spawn, tmp_path):
    add_project(api, home / "proj")
    (home / "outro").mkdir()
    for path in [str(home / "outro"), str(home / "proj" / ".." / "outro"), "/etc"]:
        assert api.post("/api/open-in-editor", json={"path": path}).status_code == 403
    assert spawn.calls == []


def test_open_in_editor_missing_command(factory, home, data_dir):
    from vibing.api.editor import spawn_detached

    app = build(factory, spawn_detached, home, data_dir)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as api:
        root = home / "proj"
        add_project(api, root)
        api.put("/api/state/preferences",
                json={"editor_command": ["comando-que-nao-existe-vibing"]})
        response = api.post("/api/open-in-editor", json={"path": str(root)})
        assert response.status_code == 400
        assert "não encontrado" in response.json()["detail"]


def test_open_in_editor_invalid_command(api, home):
    root = home / "proj"
    add_project(api, root)
    from vibing import db as dbmod

    with closing(dbmod.connect(api.app.state.settings.db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value)"
            " VALUES ('preferences', '{\"editor_command\": \"code; rm\"}')"
        )
    assert api.post("/api/open-in-editor", json={"path": str(root)}).status_code == 400


# project.git events ----------------------------------------------------------


def git_events(ws, count: int, limit: int = 50) -> list[dict]:
    found = []
    for _ in range(limit):
        event = receive(ws)
        if event["type"] == "project.git":
            found.append(event)
            if len(found) == count:
                break
    return found


def test_project_git_event_after_turn(api, home, factory):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    factory.script = lambda content: text_turn(sid, "ok")
    with api.websocket_connect(WS_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as ws:
        api.post(f"/api/sessions/{sid}/messages", json={"text": "oi"})
        (event,) = git_events(ws, 1)
        assert event["data"]["project_id"] == project["id"]
        assert event["data"]["repos"][0]["branch"] == "main"


def test_project_git_not_repeated(factory, spawn, home, data_dir):
    app = build(factory, spawn, home, data_dir)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as api:
        root = make_repo(home / "proj")
        project = add_project(api, root)
        monitor = app.state.git_monitor
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]

        def git_only() -> list[dict]:
            return [e for e in events if e["type"] == "project.git"]

        api.portal.call(monitor.refresh_project, project["id"])
        api.portal.call(monitor.refresh_project, project["id"])
        assert len(git_only()) == 1
        (root / "x").write_text("x")
        api.portal.call(monitor.refresh_project, project["id"])
        assert len(git_only()) == 2
        assert git_only()[1]["data"]["repos"][0]["changed"]["untracked"] == 1


def test_project_git_periodic(factory, spawn, home, data_dir):
    app = build(factory, spawn, home, data_dir, git_refresh_interval_seconds=0.05)
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as api:
        root = make_repo(home / "proj")
        project = add_project(api, root)
        with api.websocket_connect(WS_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}) as ws:
            (first,) = git_events(ws, 1)
            assert first["data"]["project_id"] == project["id"]
            (root / "y").write_text("y")
            (second,) = git_events(ws, 1)
            assert second["data"]["repos"][0]["changed"]["untracked"] == 1


def test_fs_dirs_does_not_run_repo_config(api, home, tmp_path):
    marker = tmp_path / "executou"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    repo = make_repo(home / "evil")
    git(repo, "config", "core.fsmonitor", str(script))
    (repo / "README.md").write_text("x\n")
    entries = api.get("/api/fs/dirs").json()["entries"]
    assert entries[0]["branch"] == "main"
    assert not marker.exists()


def test_diff_pathspec_literal(api, home):
    root = home / "proj"
    make_repo(root / "api")
    (root / "api" / "README.md").write_text("mudou\n")
    project = add_project(api, root)
    for spec in ("*", ":(top)README.md"):
        response = diff(api, project, "api", spec)
        assert response.status_code == 200 and response.json()["diff"] == ""


def test_editor_corrupted_preferences(api, home):
    root = home / "proj"
    add_project(api, root)
    from vibing import db as dbmod

    with closing(dbmod.connect(api.app.state.settings.db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_state (key, value) VALUES ('preferences', '{corrompido')"
        )
    response = api.post("/api/open-in-editor", json={"path": str(root)})
    assert response.status_code == 400


@pytest.mark.parametrize("command", ["code", [], [""], ["code", 1], {"a": 1}])
def test_preferences_reject_invalid_editor_command(api, command):
    response = api.put("/api/state/preferences", json={"editor_command": command})
    assert response.status_code == 400
    assert api.put(
        "/api/state/preferences", json={"editor_command": ["zed"]}
    ).status_code == 200


def test_session_changes_through_symlink(api, home, monkeypatch):
    root = home / "proj"
    make_repo(root)
    (root / "README.md").write_text("mudou\n")
    project = add_project(api, root)
    os.symlink(root, home / "atalho")
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    items = [{"type": "tool", "name": "Edit",
              "input": {"file_path": str(home / "atalho" / "sub" / ".." / "README.md")},
              "result": None}]

    async def fake_open(session_id):
        return {"items": items}

    monkeypatch.setattr(api.app.state.sessions, "open", fake_open)
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    assert group["rel_path"] == "."
    assert group["files"][0]["rel_path"] == "README.md"
    assert group["files"][0]["uncommitted"] is True


def test_fs_dirs_does_not_run_repo_filters(api, home, tmp_path):
    marker = tmp_path / "filtro"
    script = tmp_path / "f.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    repo = make_repo(home / "f")
    (repo / ".gitattributes").write_text("*.md filter=x\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "a")
    git(repo, "config", "filter.x.clean", str(script))
    (repo / "README.md").write_text("mudou\n")
    assert api.get("/api/fs/dirs").json()["entries"][0]["branch"] == "main"
    assert not marker.exists()
