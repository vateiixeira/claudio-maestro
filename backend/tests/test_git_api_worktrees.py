"""Changes panel, diff and editor for files edited in git worktrees."""

import os
from pathlib import Path

from git_helpers import git, make_repo
from test_git_api import add_project, api, diff, factory, spawn  # noqa: F401 (fixtures)


def worktree_session(api, project, monkeypatch, *edited: Path) -> str:  # noqa: F811
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    items = [
        {"type": "tool", "name": "Edit", "input": {"file_path": str(path)}, "result": None}
        for path in edited
    ]

    async def fake_open(session_id):
        return {"items": items}

    monkeypatch.setattr(api.app.state.sessions, "open", fake_open)
    return sid


def project_with_worktree(api, home: Path, where: Path) -> tuple[Path, Path, dict]:  # noqa: F811
    root = home / "proj"
    make_repo(root)
    git(root, "worktree", "add", "-q", "-b", "feat", str(where))
    (where / "README.md").write_text("linha 1\nmudou\n")
    return root, where.resolve(), add_project(api, root)


def forge(tmp_path: Path, wt: Path) -> Path:
    """A folder whose `.git` file claims the admin dir of the real worktree `wt`."""
    forged = tmp_path / "forged"
    forged.mkdir()
    admin = (wt / ".git").read_text().split("gitdir:", 1)[1].strip()
    (forged / ".git").write_text(f"gitdir: {admin}\n")
    (forged / "a.txt").write_text("x")
    return forged


def test_changes_groups_a_worktree_inside_the_project(api, home, monkeypatch):  # noqa: F811
    root, wt, project = project_with_worktree(
        api, home, home / "proj" / ".claude" / "worktrees" / "x"
    )
    (root / "README.md").write_text("principal\n")
    sid = worktree_session(api, project, monkeypatch, wt / "README.md")
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    assert group["rel_path"] == ".claude/worktrees/x"
    assert group["path"] == str(wt)
    assert group["branch"] == "feat"
    assert group["worktree"] == "x"
    (file,) = group["files"]
    assert file["rel_path"] == "README.md"
    assert file["uncommitted"] is True
    body = diff(api, project, group["rel_path"], "README.md").json()
    assert "-linha 2" in body["diff"] and "+mudou" in body["diff"]


def test_changes_groups_a_worktree_outside_the_project(api, home, monkeypatch, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    sid = worktree_session(api, project, monkeypatch, wt / "README.md")
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    assert group["path"] == group["rel_path"] == str(wt)
    assert group["branch"] == "feat"
    assert group["worktree"] == "w"
    assert group["files"][0]["uncommitted"] is True
    body = diff(api, project, str(wt), "README.md").json()
    assert "-linha 2" in body["diff"] and "+mudou" in body["diff"]


def test_open_in_editor_in_a_worktree_outside_the_project(api, home, spawn, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    (wt / "novo.txt").write_text("a")
    response = api.post("/api/open-in-editor", json={"path": str(wt / "novo.txt")})
    assert response.status_code == 204
    assert spawn.calls == [["code", str(wt / "novo.txt")]]


def test_changes_main_and_worktree_edits_make_two_groups(api, home, monkeypatch, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    (root / "README.md").write_text("principal\n")
    sid = worktree_session(api, project, monkeypatch, root / "README.md", wt / "README.md")
    groups = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    by_worktree = {g["worktree"]: g for g in groups}
    assert set(by_worktree) == {None, "w"}
    assert by_worktree[None]["rel_path"] == "." and by_worktree[None]["branch"] == "main"
    assert by_worktree["w"]["branch"] == "feat"


def test_changes_ignores_a_forged_worktree(api, home, monkeypatch, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    forged = forge(tmp_path, wt)
    sid = worktree_session(api, project, monkeypatch, forged / "a.txt")
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    assert group["path"] is None and group["worktree"] is None
    assert group["files"][0]["path"] == str(forged / "a.txt")


def test_changes_without_worktrees_has_no_worktree_name(api, home, monkeypatch):  # noqa: F811
    root = home / "proj"
    make_repo(root)
    (root / "README.md").write_text("x\n")
    project = add_project(api, root)
    sid = worktree_session(api, project, monkeypatch, root / "README.md")
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    assert group["worktree"] is None


def test_diff_and_editor_refuse_a_plain_repo_outside_the_project(api, home, spawn, tmp_path):  # noqa: F811
    root = home / "proj"
    make_repo(root)
    project = add_project(api, root)
    outside = make_repo(tmp_path / "fora")
    assert diff(api, project, str(outside), "README.md").status_code == 403
    response = api.post("/api/open-in-editor", json={"path": str(outside / "README.md")})
    assert response.status_code == 403
    assert spawn.calls == []


def test_diff_and_editor_refuse_a_worktree_of_an_unregistered_repo(api, home, spawn, tmp_path):  # noqa: F811
    project = add_project(api, home / "proj")
    other = make_repo(tmp_path / "outro")
    wt = tmp_path / "w"
    git(other, "worktree", "add", "-q", "-b", "feat", str(wt))
    assert diff(api, project, str(wt), "README.md").status_code == 403
    response = api.post("/api/open-in-editor", json={"path": str(wt / "README.md")})
    assert response.status_code == 403
    assert spawn.calls == []


def test_diff_and_editor_refuse_a_forged_back_pointer(api, home, spawn, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    forged = forge(tmp_path, wt)
    assert diff(api, project, str(forged), "a.txt").status_code == 403
    assert api.post("/api/open-in-editor", json={"path": str(forged / "a.txt")}).status_code == 403
    assert spawn.calls == []


def test_diff_and_editor_refuse_a_symlink_out_of_the_worktree(api, home, spawn, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    (tmp_path / "segredo.txt").write_text("s")
    os.symlink(tmp_path / "segredo.txt", wt / "link.txt")
    os.symlink(tmp_path, wt / "pasta")
    assert diff(api, project, str(wt), "link.txt").status_code == 403
    assert api.post("/api/open-in-editor", json={"path": str(wt / "link.txt")}).status_code == 403
    assert api.post(
        "/api/open-in-editor", json={"path": str(wt / "pasta" / "segredo.txt")}
    ).status_code == 403
    assert diff(api, project, str(wt / "pasta"), "segredo.txt").status_code == 403
    assert spawn.calls == []


def test_diff_refuses_a_subfolder_of_a_worktree_as_repo(api, home, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    (wt / "sub").mkdir()
    assert diff(api, project, str(wt / "sub"), "x").status_code == 403


def test_editor_refuses_a_removed_worktree(api, home, spawn, tmp_path):  # noqa: F811
    root, wt, project = project_with_worktree(api, home, tmp_path / "fora" / "w")
    path = wt / "README.md"
    assert api.post("/api/open-in-editor", json={"path": str(path)}).status_code == 204
    git(root, "worktree", "remove", "--force", str(wt))
    assert api.post("/api/open-in-editor", json={"path": str(path)}).status_code == 403
    assert spawn.calls == [["code", str(path)]]
