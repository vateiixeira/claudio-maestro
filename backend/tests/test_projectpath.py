"""Paths inside a registered project or a proven linked worktree."""

from pathlib import Path

import pytest
from git_helpers import git, make_repo

from claudio_maestro.projectpath import resolve_project_path
from claudio_maestro.security import PathNotAllowedError

pytestmark = pytest.mark.anyio


async def test_absolute_inside_a_project(tmp_path: Path):
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    assert await resolve_project_path(str(root / "docs" / "a.md"), [root]) == (root / "docs" / "a.md").resolve()


async def test_relative_needs_a_base(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathNotAllowedError):
        await resolve_project_path("a.md", [root])
    assert await resolve_project_path("docs/a.md", [root], base=root) == (root / "docs" / "a.md").resolve()


async def test_escape_with_dotdot_is_refused(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    with pytest.raises(PathNotAllowedError):
        await resolve_project_path("../fora.md", [root], base=root)


async def test_symlink_out_of_the_project_is_refused(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "segredo.md").write_text("x")
    (root / "link.md").symlink_to(tmp_path / "segredo.md")
    with pytest.raises(PathNotAllowedError):
        await resolve_project_path(str(root / "link.md"), [root])


async def test_proven_worktree_outside_the_project(tmp_path: Path):
    root = make_repo(tmp_path / "proj")
    wt = tmp_path / "fora" / "w"
    git(root, "worktree", "add", "-q", "-b", "feat", str(wt))
    (wt / "plano.md").write_text("# p\n")
    assert await resolve_project_path(str(wt / "plano.md"), [root]) == (wt / "plano.md").resolve()
    # Relative to a base inside the worktree too.
    assert await resolve_project_path("plano.md", [root], base=wt) == (wt / "plano.md").resolve()


async def test_folder_that_only_looks_like_a_worktree(tmp_path: Path):
    root = make_repo(tmp_path / "proj")
    wt = tmp_path / "fora" / "w"
    git(root, "worktree", "add", "-q", "-b", "feat", str(wt))
    forged = tmp_path / "forged"
    forged.mkdir()
    admin = (wt / ".git").read_text().split("gitdir:", 1)[1].strip()
    (forged / ".git").write_text(f"gitdir: {admin}\n")
    (forged / "a.md").write_text("x")
    with pytest.raises(PathNotAllowedError):
        await resolve_project_path(str(forged / "a.md"), [root])


async def test_null_byte_is_refused(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        await resolve_project_path("a\x00.md", [tmp_path], base=tmp_path)
