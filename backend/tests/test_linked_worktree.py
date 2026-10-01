"""Proof that a folder is a linked git worktree of a repository inside a project."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from git_helpers import GIT_ENV, git, make_repo

from claudio_maestro import gitinfo
from claudio_maestro.worktree import LinkedWorktree, linked_worktree


def add_worktree(repo: Path, where: Path, branch: str = "feat") -> Path:
    where.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", branch, str(where))
    return where.resolve()


def admin_of(wt: Path) -> Path:
    text = (wt / ".git").read_text()
    return Path(text.split("gitdir:", 1)[1].strip())


# linked_worktree (pure, no git) ----------------------------------------------


def test_inside_the_project_and_in_a_subfolder(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, repo / ".claude" / "worktrees" / "x")
    (wt / "sub").mkdir()
    expected = LinkedWorktree(name="x", path=wt, main_repo=repo.resolve())
    assert linked_worktree(wt) == expected
    assert linked_worktree(wt / "sub" / "novo.py") == expected  # file that does not exist yet
    assert linked_worktree(wt / "README.md") == expected


def test_outside_the_project(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "fora" / "w")
    assert linked_worktree(wt / "README.md") == LinkedWorktree("w", wt, repo.resolve())


def test_main_checkout_is_not_a_worktree(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    assert linked_worktree(repo / "README.md") is None
    assert linked_worktree(repo) is None
    assert linked_worktree(tmp_path / "nada" / "x") is None


def test_inside_the_git_dir_is_not_a_worktree(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    assert linked_worktree(repo / ".git" / "worktrees" / "w" / "gitdir") is None
    assert linked_worktree(admin_of(wt)) is None


def test_submodule_is_not_a_worktree(tmp_path: Path):
    inner = make_repo(tmp_path / "inner")
    repo = make_repo(tmp_path / "proj")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "protocol.file.allow=always", "submodule", "add", "-q",
         str(inner), "mod"],
        check=True, capture_output=True, env=GIT_ENV,
    )
    assert (repo / "mod" / ".git").is_file()
    assert linked_worktree(repo / "mod" / "README.md") is None


def test_forged_git_file_with_wrong_back_pointer(tmp_path: Path):
    """`.git` points to a real admin dir whose `gitdir` names another place."""
    repo = make_repo(tmp_path / "proj")
    real = add_worktree(repo, tmp_path / "real")
    forged = tmp_path / "forged"
    forged.mkdir()
    (forged / ".git").write_text(f"gitdir: {admin_of(real)}\n")
    assert linked_worktree(forged / "a.txt") is None
    assert linked_worktree(real / "README.md") is not None


def test_back_pointer_to_w_but_git_file_points_elsewhere(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    w1 = add_worktree(repo, tmp_path / "w1", "b1")
    w2 = add_worktree(repo, tmp_path / "w2", "b2")
    # w1's `.git` now claims w2's admin dir, whose back pointer is w2/.git.
    (w1 / ".git").write_text(f"gitdir: {admin_of(w2)}\n")
    assert linked_worktree(w1 / "README.md") is None
    assert linked_worktree(w2 / "README.md") is not None


def test_admin_dir_outside_a_worktrees_folder(tmp_path: Path):
    fake_admin = tmp_path / "admin"
    fake_admin.mkdir()
    wt = tmp_path / "w"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {fake_admin}\n")
    (fake_admin / "gitdir").write_text(f"{wt}/.git\n")
    assert linked_worktree(wt / "a") is None


def test_admin_not_inside_a_dot_git_dir(tmp_path: Path):
    """`worktrees/<id>` under a folder not named `.git` (bare layouts) is refused."""
    admin = tmp_path / "bare" / "worktrees" / "w"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    wt = tmp_path / "w"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {admin}\n")
    (admin / "gitdir").write_text(f"{wt}/.git\n")
    assert linked_worktree(wt / "a") is None


def test_commondir_pointing_elsewhere(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    other = make_repo(tmp_path / "other")
    wt = add_worktree(repo, tmp_path / "w")
    (admin_of(wt) / "commondir").write_text(f"{other / '.git'}\n")
    assert linked_worktree(wt / "README.md") is None


def test_relative_gitdir(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    admin = admin_of(wt)
    (wt / ".git").write_text(f"gitdir: {os.path.relpath(admin, wt)}\n")
    (admin / "gitdir").write_text(f"{os.path.relpath(wt / '.git', admin)}\n")
    assert linked_worktree(wt / "README.md") == LinkedWorktree("w", wt, repo.resolve())


def test_symlinked_path_is_resolved(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    os.symlink(wt, tmp_path / "atalho")
    found = linked_worktree(tmp_path / "atalho" / "README.md")
    assert found is not None and found.path == wt


def test_git_file_that_is_a_symlink_to_a_real_worktree_marker(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    real = add_worktree(repo, tmp_path / "real")
    forged = tmp_path / "forged"
    forged.mkdir()
    os.symlink(real / ".git", forged / ".git")
    assert linked_worktree(forged / "a") is None


def test_garbage_git_file(tmp_path: Path):
    wt = tmp_path / "w"
    wt.mkdir()
    (wt / ".git").write_bytes(b"\xff\x00lixo")
    assert linked_worktree(wt / "a") is None
    (wt / ".git").write_text("gitdir:\n")
    assert linked_worktree(wt / "a") is None


# project_worktree (adds the project and `git worktree list` checks) ---------


@pytest.mark.anyio
async def test_project_worktree_accepts_inside_and_outside(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    inside = add_worktree(repo, repo / ".claude" / "worktrees" / "x")
    outside = add_worktree(repo, tmp_path / "fora" / "w", "b2")
    roots = [repo]
    found = await gitinfo.project_worktree(inside / "README.md", roots)
    assert found is not None and found.path == inside
    found = await gitinfo.project_worktree(outside, roots)
    assert found is not None and found.path == outside and found.name == "w"


@pytest.mark.anyio
async def test_project_worktree_main_repo_must_be_in_a_project(tmp_path: Path):
    repo = make_repo(tmp_path / "unregistered")
    wt = add_worktree(repo, tmp_path / "w")
    (tmp_path / "proj").mkdir()
    assert await gitinfo.project_worktree(wt, [tmp_path / "proj"]) is None


@pytest.mark.anyio
async def test_project_worktree_repo_inside_a_project_subfolder(tmp_path: Path):
    repo = make_repo(tmp_path / "proj" / "api")
    wt = add_worktree(repo, tmp_path / "fora" / "w")
    assert await gitinfo.project_worktree(wt, [tmp_path / "proj"]) is not None


@pytest.mark.anyio
async def test_project_worktree_requires_git_to_list_it(tmp_path: Path, monkeypatch):
    """`git worktree list` is the second proof: consistent pointers alone do not pass."""
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    assert linked_worktree(wt / "a") is not None

    async def listing_without_it(directory, *args, **kwargs):
        assert args == ("worktree", "list", "--porcelain")
        return 0, f"worktree {repo}\nHEAD abc\nbranch refs/heads/main\n\n", ""

    monkeypatch.setattr(gitinfo, "run_git", listing_without_it)
    assert await gitinfo.project_worktree(wt / "a", [repo]) is None

    async def failing(directory, *args, **kwargs):
        return 128, "", "fatal"

    monkeypatch.setattr(gitinfo, "run_git", failing)
    assert await gitinfo.project_worktree(wt / "a", [repo]) is None


@pytest.mark.anyio
async def test_project_worktree_after_remove_and_move(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    assert await gitinfo.project_worktree(wt, [repo]) is not None  # fills the cache
    moved = tmp_path / "moved"
    git(repo, "worktree", "move", str(wt), str(moved))
    assert await gitinfo.project_worktree(wt, [repo]) is None
    found = await gitinfo.project_worktree(moved, [repo])
    assert found is not None and found.path == moved.resolve()
    git(repo, "worktree", "remove", "--force", str(moved))
    assert await gitinfo.project_worktree(moved, [repo]) is None


@pytest.mark.anyio
async def test_project_worktree_cache_never_trusts_a_changed_back_pointer(tmp_path: Path):
    repo = make_repo(tmp_path / "proj")
    wt = add_worktree(repo, tmp_path / "w")
    assert await gitinfo.project_worktree(wt, [repo]) is not None
    # The folder is replaced by a copy that claims the same admin dir.
    clone = tmp_path / "clone"
    shutil.copytree(wt, clone, symlinks=True)
    assert await gitinfo.project_worktree(clone / "README.md", [repo]) is None
