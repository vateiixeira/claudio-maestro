"""`delete_fork_files`: removes only the files of one exact session id, under the CLI's
projects folder, without following symlinks."""

import os
from pathlib import Path

import pytest

from claudio_maestro.contextprobe import delete_fork_files

FORK = "0b7e5c52-6f3a-4d0e-8a64-2f9d1c3b7a10"
OTHER = "0b7e5c52-6f3a-4d0e-8a64-2f9d1c3b7a11"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "projects"
    path.mkdir()
    return path


def test_removes_the_file_and_the_folder_in_any_project_folder(root):
    a, b = root / "-home-a", root / "-home-b"
    (a / FORK / "subagents").mkdir(parents=True)
    (a / FORK / "subagents" / "agent-1.jsonl").write_text("{}\n")
    (a / f"{FORK}.jsonl").write_text("{}\n")
    b.mkdir()
    (b / f"{FORK}.jsonl").write_text("{}\n")

    delete_fork_files(root, FORK)

    assert list(a.iterdir()) == [] and list(b.iterdir()) == []


def test_never_touches_another_session(root):
    folder = root / "-home-a"
    folder.mkdir()
    (folder / f"{OTHER}.jsonl").write_text("{}\n")
    (folder / OTHER).mkdir()
    (folder / f"{FORK}-x.jsonl").write_text("{}\n")
    (folder / f"x{FORK}.jsonl").write_text("{}\n")
    (folder / f"{FORK}.jsonl").write_text("{}\n")

    delete_fork_files(root, FORK)

    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [f"{OTHER}.jsonl", OTHER, f"{FORK}-x.jsonl", f"x{FORK}.jsonl"]
    )


@pytest.mark.parametrize("bad", ["", "*", "../x", f"{FORK}/..", FORK.upper(), "not-a-uuid"])
def test_refuses_an_id_that_is_not_a_canonical_uuid(root, bad):
    folder = root / "-home-a"
    folder.mkdir()
    (folder / "keep.jsonl").write_text("{}\n")

    delete_fork_files(root, bad)

    assert [p.name for p in folder.iterdir()] == ["keep.jsonl"]


def test_does_not_follow_symlinks(root, tmp_path):
    outside = tmp_path / "outside"
    (outside / FORK).mkdir(parents=True)
    (outside / FORK / "precious.txt").write_text("x")
    (outside / f"{FORK}.jsonl").write_text("{}\n")
    # A project folder that is a symlink out of the root is skipped entirely.
    os.symlink(outside, root / "-linked")
    # Inside a real folder, a symlinked file or folder named like the fork is only unlinked.
    folder = root / "-home-a"
    folder.mkdir()
    os.symlink(outside / f"{FORK}.jsonl", folder / f"{FORK}.jsonl")
    os.symlink(outside / FORK, folder / FORK)

    delete_fork_files(root, FORK)

    assert (outside / FORK / "precious.txt").is_file()
    assert (outside / f"{FORK}.jsonl").is_file()
    assert not (folder / f"{FORK}.jsonl").is_symlink()
    assert not (folder / FORK).is_symlink()


def test_a_missing_root_is_fine(tmp_path):
    delete_fork_files(tmp_path / "nope", FORK)
