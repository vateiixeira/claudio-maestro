"""Worktree per task: creation, reuse, refusals and the removal proofs (real git in tmp_path)."""

import os
from pathlib import Path

import pytest
from git_helpers import (  # noqa: F401
    commit_file,
    git,
    git_home,
    make_repo,
    set_identity,
)

from claudio_maestro import gitinfo
from claudio_maestro.org import worktrees
from claudio_maestro.org.worktrees import (
    WORKTREES_DIR,
    WorktreeError,
    ensure_task_worktree,
    remove_task_worktree,
    task_branch,
)


@pytest.fixture
def project(tmp_path: Path, git_home) -> Path:  # noqa: F811
    root = make_repo(tmp_path / "proj")
    set_identity(root)
    return root.resolve()


def branches(repo: Path) -> list[str]:
    return git(repo, "branch", "--format=%(refname:short)").split()


def attach_remote(repo: Path, tmp_path: Path, *, head: bool = True) -> Path:
    """A bare `origin` with the current branch pushed; `origin/HEAD` points to it."""
    remote = tmp_path / "origin.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    if head:
        git(repo, "remote", "set-head", "origin", "main")
    return remote


# task_branch ---------------------------------------------------------------


def test_task_branch_slug_and_length():
    assert task_branch(7, "Corrigir Ação do Botão: Salvar!") == "tarefa/7-corrigir-acao-do-botao-salvar"
    assert task_branch(12, "  --Já   é  ÇÃO--  ") == "tarefa/12-ja-e-cao"
    # Nothing usable in the title: only the id.
    assert task_branch(3, "!!! ???") == "tarefa/3"
    assert task_branch(3, "") == "tarefa/3"
    long = task_branch(9, "a" * 200)
    assert len(long) <= 60
    assert long.startswith("tarefa/9-a") and not long.endswith("-")
    # The cut never leaves a trailing dash.
    cut = task_branch(1, "aaaa bbbb " * 20)
    assert len(cut) <= 60 and not cut.endswith("-")
    for title in ("../../etc", "a b\x00c", "x.lock", "-rf", "emoji 🎉 test", "ß~^:?*[\\"):
        name = task_branch(5, title)
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-/" for c in name), name
        assert name.startswith("tarefa/5") and "//" not in name and not name.endswith("-")


# ensure_task_worktree ------------------------------------------------------


@pytest.mark.anyio
async def test_ensure_creates_worktree_and_branch(project: Path):
    path, branch = await ensure_task_worktree(project, 3, "Ajustar login")

    assert path == project / WORKTREES_DIR / "tarefa-3"
    assert branch == "tarefa/3-ajustar-login"
    assert path.is_dir() and (path / "README.md").is_file()
    assert git(path, "branch", "--show-current").strip() == branch
    assert branch in branches(project)
    found = await gitinfo.project_worktree(path, [project])
    assert found is not None and found.path == path


@pytest.mark.anyio
async def test_ensure_reuses_existing_worktree(project: Path):
    path, branch = await ensure_task_worktree(project, 3, "Ajustar login")
    (path / "work.txt").write_text("em andamento\n")

    again, again_branch = await ensure_task_worktree(project, 3, "Outro título")

    assert (again, again_branch) == (path, branch)
    assert (path / "work.txt").read_text() == "em andamento\n"


@pytest.mark.anyio
async def test_ensure_uses_existing_branch(project: Path):
    git(project, "branch", "tarefa/4-x")
    commit_file(project, "later.txt")  # HEAD moves; the old branch must stay where it was
    old = git(project, "rev-parse", "tarefa/4-x").strip()

    path, branch = await ensure_task_worktree(project, 4, "x")

    assert branch == "tarefa/4-x"
    assert git(path, "rev-parse", "HEAD").strip() == old
    assert not (path / "later.txt").exists()


@pytest.mark.anyio
async def test_ensure_refuses_non_repo(tmp_path: Path, git_home):  # noqa: F811
    folder = tmp_path / "plain"
    folder.mkdir()

    with pytest.raises(WorktreeError, match="não é a raiz de um repositório git"):
        await ensure_task_worktree(folder, 1, "x")

    assert list(folder.iterdir()) == []  # nothing created


@pytest.mark.anyio
async def test_ensure_refuses_project_that_is_itself_a_worktree(project: Path, tmp_path: Path):
    git(project, "worktree", "add", "-q", "-b", "other", str(tmp_path / "linked"))

    with pytest.raises(WorktreeError, match="não é a raiz de um repositório git"):
        await ensure_task_worktree((tmp_path / "linked").resolve(), 1, "x")


@pytest.mark.anyio
async def test_ensure_refuses_foreign_folder(project: Path):
    foreign = project / WORKTREES_DIR / "tarefa-3"
    foreign.mkdir(parents=True)
    (foreign / "mine.txt").write_text("não apague\n")

    with pytest.raises(WorktreeError, match="não é uma worktree"):
        await ensure_task_worktree(project, 3, "x")

    assert (foreign / "mine.txt").read_text() == "não apague\n"
    assert not any(b.startswith("tarefa/") for b in branches(project))


@pytest.mark.anyio
async def test_ensure_refuses_symlink_in_place_of_worktree(project: Path, tmp_path: Path):
    real, _ = await ensure_task_worktree(project, 9, "real")
    link = project / WORKTREES_DIR / "tarefa-3"
    os.symlink(real, link)

    with pytest.raises(WorktreeError, match="não é uma worktree"):
        await ensure_task_worktree(project, 3, "x")

    assert link.is_symlink() and real.is_dir()


@pytest.mark.anyio
async def test_ensure_refuses_worktrees_dir_that_is_a_symlink(project: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".claude").mkdir()
    os.symlink(outside, project / WORKTREES_DIR)

    with pytest.raises(WorktreeError):
        await ensure_task_worktree(project, 3, "x")

    assert list(outside.iterdir()) == []
    assert not any(b.startswith("tarefa/") for b in branches(project))


@pytest.mark.anyio
async def test_ensure_reports_git_failure_in_portuguese(tmp_path: Path, git_home):  # noqa: F811
    root = make_repo(tmp_path / "empty", commit=False)  # no commit: HEAD is not valid

    with pytest.raises(WorktreeError, match="Não foi possível criar a worktree"):
        await ensure_task_worktree(root.resolve(), 1, "x")

    assert not (root / WORKTREES_DIR / "tarefa-1").exists()


@pytest.mark.anyio
async def test_ensure_refuses_branch_checked_out_elsewhere(project: Path, tmp_path: Path):
    git(project, "worktree", "add", "-q", "-b", "tarefa/5-x", str(tmp_path / "elsewhere"))

    with pytest.raises(WorktreeError, match="Não foi possível criar a worktree"):
        await ensure_task_worktree(project, 5, "x")

    assert not (project / WORKTREES_DIR / "tarefa-5").exists()


@pytest.mark.anyio
async def test_ensure_runs_git_only_through_run_git(project: Path, monkeypatch):
    calls: list[tuple[str, ...]] = []
    real = gitinfo.run_git

    async def spy(repo, *args, **kwargs):
        calls.append(args)
        return await real(repo, *args, **kwargs)

    monkeypatch.setattr(worktrees, "run_git", spy)
    await ensure_task_worktree(project, 3, "x")

    assert any(call[:2] == ("worktree", "add") for call in calls)


# remove_task_worktree ------------------------------------------------------


@pytest.mark.anyio
async def test_remove_only_when_merged_or_pushed(project: Path, tmp_path: Path):
    # Merged into the default branch (no remote: the project's current branch).
    path, branch = await ensure_task_worktree(project, 1, "mesclada")
    commit_file(path, "a.txt")
    git(project, "merge", "-q", "--no-ff", "-m", "merge", branch)

    assert await remove_task_worktree(project, path, branch) == (True, "")
    assert not path.exists() and branch not in branches(project)

    # Pushed: origin/<branch> equals the branch; there is no upstream and it is not merged.
    attach_remote(project, tmp_path)
    path, branch = await ensure_task_worktree(project, 2, "enviada")
    commit_file(path, "b.txt")
    git(path, "push", "-q", "origin", branch)
    git(project, "fetch", "-q", "origin")

    assert await remove_task_worktree(project, path, branch) == (True, "")
    assert not path.exists() and branch not in branches(project)

    # Neither merged nor pushed: the folder stays, with the reason.
    path, branch = await ensure_task_worktree(project, 3, "solta")
    commit_file(path, "c.txt")

    ok, reason = await remove_task_worktree(project, path, branch)

    assert ok is False and "mesclada" in reason and "enviada" in reason
    assert (path / "c.txt").is_file() and branch in branches(project)


@pytest.mark.anyio
async def test_remove_refuses_pushed_branch_that_moved_on(project: Path, tmp_path: Path):
    attach_remote(project, tmp_path)
    path, branch = await ensure_task_worktree(project, 2, "enviada")
    commit_file(path, "b.txt")
    git(path, "push", "-q", "origin", branch)
    git(project, "fetch", "-q", "origin")
    commit_file(path, "c.txt")  # local branch is ahead of origin/<branch>

    ok, _ = await remove_task_worktree(project, path, branch)

    assert ok is False and (path / "c.txt").is_file() and branch in branches(project)


@pytest.mark.anyio
async def test_remove_uses_origin_head_as_default_branch(project: Path, tmp_path: Path):
    attach_remote(project, tmp_path)
    path, branch = await ensure_task_worktree(project, 1, "x")
    commit_file(path, "a.txt")
    # The remote default gets the work (the PR was merged there); the checkout sits elsewhere.
    git(project, "merge", "-q", "--ff-only", branch)
    git(project, "push", "-q", "origin", "main")
    git(project, "fetch", "-q", "origin")
    git(project, "checkout", "-q", "-b", "elsewhere", "HEAD~1")

    assert await remove_task_worktree(project, path, branch) == (True, "")
    assert not path.exists() and branch not in branches(project)


@pytest.mark.anyio
async def test_remove_refuses_worktree_with_uncommitted_work(project: Path):
    path, branch = await ensure_task_worktree(project, 1, "x")  # nothing to merge: same commit
    (path / "draft.txt").write_text("não salvo\n")

    ok, reason = await remove_task_worktree(project, path, branch)

    assert ok is False and "alterações" in reason
    assert (path / "draft.txt").read_text() == "não salvo\n"
    assert branch in branches(project)


@pytest.mark.anyio
async def test_remove_refuses_folder_that_is_not_a_proven_worktree(project: Path):
    foreign = project / WORKTREES_DIR / "tarefa-3"
    foreign.mkdir(parents=True)
    (foreign / "mine.txt").write_text("x")

    ok, reason = await remove_task_worktree(project, foreign, "tarefa/3-x")

    assert ok is False and reason
    assert (foreign / "mine.txt").is_file()


@pytest.mark.anyio
async def test_remove_refuses_path_outside_worktrees_dir(project: Path, tmp_path: Path):
    # A real, merged worktree, but not under <project>/.claude/worktrees.
    other = tmp_path / "elsewhere"
    git(project, "worktree", "add", "-q", "-b", "tarefa/8-x", str(other))

    ok, reason = await remove_task_worktree(project, other.resolve(), "tarefa/8-x")

    assert ok is False and ".claude/worktrees" in reason
    assert other.is_dir() and "tarefa/8-x" in branches(project)
    # The project itself and the worktrees folder are never removable either.
    assert (await remove_task_worktree(project, project, "main"))[0] is False
    assert (await remove_task_worktree(project, project / WORKTREES_DIR, "main"))[0] is False
    assert project.is_dir() and "main" in branches(project)


@pytest.mark.anyio
async def test_remove_refuses_when_worktree_is_on_another_branch(project: Path):
    path, _ = await ensure_task_worktree(project, 1, "x")

    # `main` is merged into itself, but it is not the branch of this worktree.
    ok, reason = await remove_task_worktree(project, path, "main")

    assert ok is False and reason
    assert path.is_dir() and "main" in branches(project)


@pytest.mark.anyio
async def test_remove_refuses_branch_name_outside_task_namespace(project: Path):
    path, _ = await ensure_task_worktree(project, 1, "x")
    git(path, "checkout", "-q", "-b", "feature/y")

    ok, reason = await remove_task_worktree(project, path, "feature/y")

    assert ok is False and reason and path.is_dir()


@pytest.mark.anyio
async def test_remove_refuses_symlink_to_a_worktree(project: Path, tmp_path: Path):
    real, branch = await ensure_task_worktree(project, 1, "x")
    link = project / WORKTREES_DIR / "tarefa-2"
    os.symlink(real, link)

    ok, _ = await remove_task_worktree(project, link, branch)

    assert ok is False and link.is_symlink() and real.is_dir()


@pytest.mark.anyio
async def test_remove_of_missing_folder_is_done(project: Path):
    assert await remove_task_worktree(project, project / WORKTREES_DIR / "tarefa-7", "tarefa/7-x") == (
        True,
        "",
    )


@pytest.mark.anyio
async def test_remove_never_uses_rmtree(project: Path, monkeypatch):
    import shutil

    def boom(*args, **kwargs):
        raise AssertionError("rmtree must not be used")

    monkeypatch.setattr(shutil, "rmtree", boom)
    path, branch = await ensure_task_worktree(project, 1, "x")

    assert await remove_task_worktree(project, path, branch) == (True, "")
    assert not path.exists()


@pytest.mark.anyio
async def test_remove_waits_for_the_lock_of_the_task_worktree(project: Path):
    import asyncio

    path, branch = await ensure_task_worktree(project, 3, "Ajustar login")
    key = str(worktrees._expected_path(project, path.name))
    lock = worktrees._locks.setdefault(key, asyncio.Lock())
    async with lock:
        removal = asyncio.ensure_future(remove_task_worktree(project, path, branch))
        await asyncio.sleep(0.2)
        assert not removal.done() and path.is_dir()  # an `ensure` in flight would be waited for
    assert await removal == (True, "")
    assert not path.exists()
