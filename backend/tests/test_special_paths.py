"""Paths with spaces, accents and symbolic links; project git limit; preferences."""

import os
from pathlib import Path

import pytest
from git_helpers import git, make_repo
from test_git_api import add_project, api, diff, factory, spawn  # noqa: F401

from claudio_maestro import history

ACCENTED = "Área de trabalho"
REPO_NAME = "repositório ção"
FILE_NAME = "arquivo com espaço é.txt"


# Spaces and accents --------------------------------------------------------


def test_create_project_with_spaces_and_accents(api, home):  # noqa: F811
    folder = home / ACCENTED / "meu projeto ç"
    project = add_project(api, folder)
    assert project["path"] == str(folder)
    assert api.get("/api/projects").json()[0]["path"] == str(folder)
    assert api.get(f"/api/projects/{project['id']}/git").status_code == 200


def test_diff_with_spaces_and_accents(api, home):  # noqa: F811
    root = home / ACCENTED / "proj"
    repo = make_repo(root / REPO_NAME)
    (repo / FILE_NAME).write_text("um\n")
    git(repo, "add", FILE_NAME)
    git(repo, "commit", "-q", "-m", "arquivo")
    (repo / FILE_NAME).write_text("um\ndois\n")
    (repo / "novo ção.txt").write_text("novo\n")
    project = add_project(api, root)

    tracked = diff(api, project, REPO_NAME, FILE_NAME)
    assert tracked.status_code == 200, tracked.text
    assert "+dois" in tracked.json()["diff"]
    untracked = diff(api, project, REPO_NAME, "novo ção.txt")
    assert untracked.status_code == 200, untracked.text
    assert "+novo" in untracked.json()["diff"]
    absolute = diff(api, project, str(repo), str(repo / FILE_NAME))
    assert "+dois" in absolute.json()["diff"]


def test_project_git_with_spaces_and_accents(api, home):  # noqa: F811
    root = home / ACCENTED / "proj"
    repo = make_repo(root / REPO_NAME, branch="ramo")
    (repo / FILE_NAME).write_text("x")
    project = add_project(api, root)
    repos = api.get(f"/api/projects/{project['id']}/git").json()["repos"]
    assert [r["rel_path"] for r in repos] == [REPO_NAME]
    assert repos[0]["branch"] == "ramo" and repos[0]["changed"]["untracked"] == 1


def test_open_in_editor_with_spaces_and_accents(api, home, spawn):  # noqa: F811
    root = home / ACCENTED / "proj ç"
    add_project(api, root)
    file = root / FILE_NAME
    file.write_text("a")
    folder = root / "sub pasta é"
    folder.mkdir()
    for target in (file, folder, root):
        assert api.post("/api/open-in-editor", json={"path": str(target)}).status_code == 204
    assert spawn.calls == [["code", str(file)], ["code", str(folder)], ["code", str(root)]]


# Symbolic links ------------------------------------------------------------


def test_open_in_editor_link_to_outside_project_rejected(api, home, spawn, tmp_path):  # noqa: F811
    root = home / "proj"
    add_project(api, root)
    outside = home / "outro"
    outside.mkdir()
    (outside / "a.txt").write_text("a")
    os.symlink(outside, root / "atalho")
    os.symlink(outside / "a.txt", root / "a-link.txt")
    for path in (root / "atalho", root / "a-link.txt"):
        assert api.post("/api/open-in-editor", json={"path": str(path)}).status_code == 403
    assert spawn.calls == []


def test_diff_link_to_outside_home_rejected(api, home, tmp_path):  # noqa: F811
    root = home / "proj"
    make_repo(root / "api")
    outside = tmp_path / "fora"
    make_repo(outside)
    (outside / "segredo.txt").write_text("s")
    os.symlink(outside, root / "link")
    os.symlink(outside / "segredo.txt", root / "api" / "segredo.txt")
    project = add_project(api, root)
    assert diff(api, project, "link", "README.md").status_code == 403
    assert diff(api, project, "api", "segredo.txt").status_code == 403


def test_diff_link_inside_project_allowed_and_resolved(api, home):  # noqa: F811
    root = home / "proj"
    make_repo(root / "api")
    (root / "api" / "README.md").write_text("mudou\n")
    os.symlink(root / "api", root / "atalho")
    project = add_project(api, root)
    response = diff(api, project, "atalho", "README.md")
    assert response.status_code == 200 and "+mudou" in response.json()["diff"]


def test_create_project_link_to_outside_home_rejected(api, home, tmp_path):  # noqa: F811
    outside = tmp_path / "fora"
    outside.mkdir()
    os.symlink(outside, home / "atalho")
    response = api.post(
        "/api/projects", json={"name": "x", "path": str(home / "atalho"), "color": "#ff8800"}
    )
    assert response.status_code == 403
    assert api.get("/api/projects").json() == []


def test_project_git_does_not_follow_links_out_of_the_project(api, home, tmp_path):  # noqa: F811
    root = home / "proj"
    root.mkdir()
    outside = tmp_path / "fora"
    make_repo(outside)
    os.symlink(outside, root / "atalho")
    project = add_project(api, root)
    assert api.get(f"/api/projects/{project['id']}/git").json()["repos"] == []


# limit_reached -------------------------------------------------------------


def test_project_git_limit_reached(api, home):  # noqa: F811
    root = home / "proj"
    for index in range(history.REPO_MAX_COUNT + 1):
        (root / f"r{index:02d}" / ".git").mkdir(parents=True)
    project = add_project(api, root)
    body = api.get(f"/api/projects/{project['id']}/git").json()
    assert body["limit_reached"] is True
    assert len(body["repos"]) == history.REPO_MAX_COUNT


def test_project_git_under_limit(api, home):  # noqa: F811
    root = make_repo(home / "proj")
    make_repo(root / "api")
    project = add_project(api, root)
    assert api.get(f"/api/projects/{project['id']}/git").json()["limit_reached"] is False


def test_project_git_unreadable_folder_is_not_the_limit(api, home, monkeypatch):  # noqa: F811
    root = home / "proj"
    (root / "a").mkdir(parents=True)
    project = add_project(api, root)
    real = os.scandir

    def failing(path):
        if Path(path).name == "a":
            raise PermissionError("no")
        return real(path)

    monkeypatch.setattr("claudio_maestro.history.os.scandir", failing)
    body = api.get(f"/api/projects/{project['id']}/git").json()
    assert body["limit_reached"] is False


def test_project_git_unavailable_has_no_limit(api, home):  # noqa: F811
    root = home / "proj"
    project = add_project(api, root)
    root.rmdir()
    assert api.get(f"/api/projects/{project['id']}/git").json() == {
        "repos": [], "limit_reached": False,
    }


def test_project_git_without_repo_has_no_limit(api, home):  # noqa: F811
    project = add_project(api, home / "plain")
    assert api.get(f"/api/projects/{project['id']}/git").json() == {
        "repos": [], "limit_reached": False,
    }


# Preferences ---------------------------------------------------------------


@pytest.mark.parametrize("days", [1, 3, 30, 365])
def test_finished_after_days_accepted(api, days):  # noqa: F811
    response = api.put("/api/state/preferences", json={"finished_after_days": days})
    assert response.status_code == 200
    assert api.get("/api/state").json()["preferences"] == {"finished_after_days": days}


@pytest.mark.parametrize("days", [0, -1, 366, 1000, 1.5, "3", None, True, [3], {"a": 1}])
def test_finished_after_days_rejected(api, days):  # noqa: F811
    response = api.put("/api/state/preferences", json={"finished_after_days": days})
    assert response.status_code == 400
    assert "dias" in response.json()["detail"]
    assert api.get("/api/state").json() == {}


def test_preferences_without_finished_after_days_still_accepted(api):  # noqa: F811
    assert api.put("/api/state/preferences", json={"editor_command": ["zed"]}).status_code == 200


def test_preferences_validate_both_fields(api):  # noqa: F811
    response = api.put(
        "/api/state/preferences", json={"editor_command": ["zed"], "finished_after_days": 0}
    )
    assert response.status_code == 400
    response = api.put(
        "/api/state/preferences", json={"editor_command": [], "finished_after_days": 5}
    )
    assert response.status_code == 400
    ok = api.put(
        "/api/state/preferences", json={"editor_command": ["zed"], "finished_after_days": 5}
    )
    assert ok.status_code == 200
