import os
from pathlib import Path

import pytest


def names(body) -> list[str]:
    return [entry["name"] for entry in body["entries"]]


def test_lists_home_by_default(client, home: Path):
    (home / "dev").mkdir()
    (home / "Documents").mkdir()
    response = client.get("/api/fs/dirs")
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(home)
    assert body["parent"] is None
    assert names(body) == ["dev", "Documents"]


def test_lists_given_path(client, home: Path):
    (home / "dev" / "alpha").mkdir(parents=True)
    (home / "dev" / "beta").mkdir()
    body = client.get("/api/fs/dirs", params={"path": str(home / "dev")}).json()
    assert body["path"] == str(home / "dev")
    assert body["parent"] == str(home)
    assert names(body) == ["alpha", "beta"]
    assert body["entries"][0]["path"] == str(home / "dev" / "alpha")


def test_only_directories_listed(client, home: Path):
    (home / "folder").mkdir()
    (home / "file.txt").write_text("x")
    assert names(client.get("/api/fs/dirs").json()) == ["folder"]


def test_hidden_directories_omitted(client, home: Path):
    (home / ".config").mkdir()
    (home / ".git").mkdir()
    (home / "visible").mkdir()
    assert names(client.get("/api/fs/dirs").json()) == ["visible"]


def test_git_flag(client, home: Path):
    (home / "repo" / ".git").mkdir(parents=True)
    (home / "worktree").mkdir()
    (home / "worktree" / ".git").write_text("gitdir: /somewhere")
    (home / "plain" / "sub" / ".git").mkdir(parents=True)
    body = client.get("/api/fs/dirs").json()
    flags = {e["name"]: e["git"] for e in body["entries"]}
    assert flags == {"repo": True, "worktree": True, "plain": False}


def test_spaces_and_accents(client, home: Path):
    folder = home / "Área de trabalho"
    (folder / "projeto ção").mkdir(parents=True)
    response = client.get("/api/fs/dirs", params={"path": str(folder)})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(folder)
    assert names(body) == ["projeto ção"]
    assert body["entries"][0]["path"] == str(folder / "projeto ção")


def test_path_outside_home_rejected(client, tmp_path: Path):
    response = client.get("/api/fs/dirs", params={"path": str(tmp_path)})
    assert response.status_code == 403


def test_root_rejected(client):
    assert client.get("/api/fs/dirs", params={"path": "/"}).status_code == 403


def test_dotdot_escape_rejected(client, home: Path):
    response = client.get("/api/fs/dirs", params={"path": str(home) + "/.."})
    assert response.status_code == 403


def test_symlink_pointing_outside_rejected(client, home: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    (outside / "secret").mkdir(parents=True)
    os.symlink(outside, home / "escape")
    response = client.get("/api/fs/dirs", params={"path": str(home / "escape")})
    assert response.status_code == 403


def test_symlink_pointing_outside_not_listed(client, home: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, home / "escape")
    (home / "real").mkdir()
    assert names(client.get("/api/fs/dirs").json()) == ["real"]


def test_symlink_inside_home_listed_with_resolved_path(client, home: Path):
    (home / "real").mkdir()
    os.symlink(home / "real", home / "alias")
    body = client.get("/api/fs/dirs").json()
    entries = {e["name"]: e["path"] for e in body["entries"]}
    assert entries == {"alias": str(home / "real"), "real": str(home / "real")}


def test_broken_symlink_ignored(client, home: Path):
    os.symlink(home / "missing", home / "broken")
    (home / "real").mkdir()
    assert names(client.get("/api/fs/dirs").json()) == ["real"]


def test_nonexistent_path(client, home: Path):
    response = client.get("/api/fs/dirs", params={"path": str(home / "nope")})
    assert response.status_code == 404


def test_file_path(client, home: Path):
    (home / "file.txt").write_text("x")
    response = client.get("/api/fs/dirs", params={"path": str(home / "file.txt")})
    assert response.status_code == 400


def test_relative_path_rejected(client, home: Path):
    (home / "dev").mkdir()
    assert client.get("/api/fs/dirs", params={"path": "dev"}).status_code == 403


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_subfolder_does_not_break_listing(client, home: Path):
    locked = home / "locked"
    (locked / "inner").mkdir(parents=True)
    (home / "open").mkdir()
    locked.chmod(0)
    try:
        response = client.get("/api/fs/dirs")
        assert response.status_code == 200
        body = response.json()
        assert names(body) == ["locked", "open"]
        assert body["entries"][0]["git"] is False
    finally:
        locked.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unreadable_folder_itself_returns_403(client, home: Path):
    locked = home / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        response = client.get("/api/fs/dirs", params={"path": str(locked)})
        assert response.status_code == 403
    finally:
        locked.chmod(0o755)
