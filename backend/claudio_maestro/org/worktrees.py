"""A git worktree per task, for agents whose `AGENT.md` says `worktree: true`.

Creating and removing worktrees runs git, so this module is deliberately narrow:

- Every git command goes through `gitinfo.run_git` (arguments in a list, no shell).
- Worktrees live only at `<project>/.claude/worktrees/tarefa-<id>`. The folder of the project must
  be the root of a git repository (a `.git` folder, not a link, not a file). The path is compared
  by `realpath`, so a symlink for `.claude`, `worktrees` or `tarefa-<id>` is refused.
- A folder is only treated as the task's worktree after `gitinfo.project_worktree` proves it:
  pointers that agree in both directions, the main repository inside the project, and the folder
  listed by `git worktree list`. A folder that is not proven is never touched.
- Nothing is deleted by this code: removal is `git worktree remove` (which itself refuses a
  worktree with uncommitted changes, so no `--force`) and `git branch -d`/`-D`. There is no
  `shutil.rmtree`.

Removing needs a proof that the work is safe elsewhere. "Merged" means the task branch is an
ancestor of the default branch. The default branch is, in order: the branch `origin/HEAD` points
to (`refs/remotes/origin/<name>`, plus the local branch of that name if it exists); without
`origin/HEAD`, the branch currently checked out in the project folder; with a detached HEAD there,
`main` or `master` if they exist. "Pushed" means `refs/remotes/origin/<branch>` equals the branch.
That reads the remote-tracking ref as the last fetch or push left it; it never touches the network.
"""

import asyncio
import os
import re
import unicodedata
from pathlib import Path

from claudio_maestro import gitinfo
from claudio_maestro.gitinfo import STATUS_SUBMODULES, GitError, run_git

WORKTREES_DIR = ".claude/worktrees"
BRANCH_PREFIX = "tarefa/"
FOLDER_PREFIX = "tarefa-"
MAX_BRANCH_LENGTH = 60
# `worktree add` checks out the whole tree and `remove` deletes it: far longer than a status.
ADD_TIMEOUT = 300.0
REMOVE_TIMEOUT = 120.0
GRACE = 5.0  # SIGTERM first, so git can clean up its lock files

NOT_A_REPO = "A pasta do projeto não é a raiz de um repositório git."

# One creation at a time per folder: the second caller finds the finished worktree.
_locks: dict[str, asyncio.Lock] = {}


class WorktreeError(Exception):
    """Message in Portuguese, shown as the reason a run could not start or a worktree stayed."""


def task_branch(task_id: int, title: str) -> str:
    """`tarefa/<id>-<slug of the title>`, at most 60 characters, only `a-z 0-9 - /`."""
    prefix = f"{BRANCH_PREFIX}{task_id}"
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    room = MAX_BRANCH_LENGTH - len(prefix) - 1
    slug = slug[:room].strip("-") if room > 0 else ""
    return f"{prefix}-{slug}" if slug else prefix


async def ensure_task_worktree(project_path: Path, task_id: int, title: str) -> tuple[Path, str]:
    """The worktree of the task, created if needed: (folder, branch).

    An existing `tarefa-<id>` folder is reused only when it is a proven worktree. Anything else
    in that place is an error and stays untouched.
    """
    repo = Path(project_path)
    _require_repo_root(repo)
    path = repo / WORKTREES_DIR / f"{FOLDER_PREFIX}{task_id}"
    expected = _expected_path(repo, path.name)
    if _real(path.parent) != expected.parent:
        raise WorktreeError(
            "A pasta .claude/worktrees do projeto aponta para fora dele; nada foi criado."
        )
    lock = _locks.setdefault(str(expected), asyncio.Lock())
    async with lock:
        if os.path.lexists(path):
            return path, await _existing_branch(repo, path, expected)
        branch = task_branch(task_id, title)
        code, _, _ = await _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        add = (
            ("worktree", "add", str(path), branch) if code == 0
            else ("worktree", "add", "-b", branch, str(path), "HEAD")
        )
        code, _, err = await _git(repo, *add, timeout=ADD_TIMEOUT, grace=GRACE)
        if code != 0:
            raise WorktreeError(f"Não foi possível criar a worktree da tarefa: {_short(err)}")
        return path, await _existing_branch(repo, path, expected)


async def remove_task_worktree(project_path: Path, path: Path, branch: str) -> tuple[bool, str]:
    """Remove the worktree and its branch when the work is merged or pushed.

    Returns (True, "") when done, and (False, reason) when the worktree stays. A folder that is
    already gone counts as done. (True, note) means the worktree is gone but the branch could not
    be deleted. Nothing is removed unless: the folder is exactly `<project>/.claude/worktrees/<name>`
    (no links), it is a proven worktree of this project, it is on `branch` (a `tarefa/...` name),
    it has no uncommitted changes, and the branch is merged into the default branch or pushed.
    """
    try:
        return await _remove(Path(project_path), Path(path), branch)
    except WorktreeError as exc:
        return False, str(exc)


async def _remove(repo: Path, path: Path, branch: str) -> tuple[bool, str]:
    _require_repo_root(repo)
    parent = _expected_path(repo, "x").parent
    if (
        path.name in ("", ".", "..")
        or not path.name.startswith(FOLDER_PREFIX)
        or path.is_symlink()
        or _real(path.parent) != parent
        or _real(path) != parent / path.name
    ):
        raise WorktreeError(
            f"A pasta {path} não está em {repo / WORKTREES_DIR} e não será removida."
        )
    # The same lock `ensure_task_worktree` takes: a removal never runs in the middle of a creation.
    async with _locks.setdefault(str(_expected_path(repo, path.name)), asyncio.Lock()):
        return await _remove_locked(repo, path, branch)


async def _remove_locked(repo: Path, path: Path, branch: str) -> tuple[bool, str]:
    if not os.path.lexists(path):
        return True, ""
    found = await gitinfo.project_worktree(path, [repo])
    if found is None or found.path != _real(path) or found.main_repo != _real(repo):
        raise WorktreeError(f"A pasta {path} não é uma worktree deste projeto e não será removida.")
    await _require_task_branch(repo, path, branch)
    code, out, err = await _git(
        path, "status", STATUS_SUBMODULES, "--porcelain", "--untracked-files=all"
    )
    if code != 0:
        raise WorktreeError(f"Não foi possível ler o estado da worktree: {_short(err)}")
    if out.strip():
        raise WorktreeError(
            "A worktree tem alterações não salvas (ou arquivos novos) e foi mantida."
        )

    sha = await _rev(repo, f"refs/heads/{branch}")
    if sha is None:
        raise WorktreeError(f"A branch {branch} não existe mais; a worktree foi mantida.")
    refs = await _default_refs(repo)
    merged = False
    for ref in refs:
        code, _, _ = await _git(repo, "merge-base", "--is-ancestor", sha, ref)
        if code == 0:
            merged = True
            break
    pushed = await _rev(repo, f"refs/remotes/origin/{branch}") == sha
    if not merged and not pushed:
        target = ", ".join(ref.removeprefix("refs/heads/").removeprefix("refs/remotes/") for ref in refs)
        raise WorktreeError(
            f"A branch {branch} ainda não foi mesclada na branch padrão"
            f"{f' ({target})' if target else ''} nem enviada ao remoto (origin/{branch}); "
            "a worktree foi mantida."
        )

    code, _, err = await _git(repo, "worktree", "remove", str(path), timeout=REMOVE_TIMEOUT, grace=GRACE)
    if code != 0:
        raise WorktreeError(f"Não foi possível remover a worktree: {_short(err)}")
    code, _, err = await _git(repo, "branch", "-d", "--", branch)
    if code != 0:
        # `-d` judges by the upstream or HEAD of the project folder, which says nothing about
        # the proof above (merged into the default branch, or equal to origin/<branch>).
        code, _, err = await _git(repo, "branch", "-D", "--", branch)
    if code != 0:
        return True, f"A worktree foi removida, mas a branch {branch} ficou: {_short(err)}"
    return True, ""


# Helpers -------------------------------------------------------------------


async def _git(
    repo: Path, *args: str, timeout: float = gitinfo.GIT_TIMEOUT, grace: float = 0.0
) -> tuple[int, str, str]:
    try:
        return await run_git(repo, *args, timeout=timeout, grace=grace)
    except GitError as exc:
        raise WorktreeError(str(exc)) from exc


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _expected_path(repo: Path, name: str) -> Path:
    return _real(repo) / WORKTREES_DIR / name


def _require_repo_root(repo: Path) -> None:
    marker = repo / ".git"
    if not repo.is_dir() or marker.is_symlink() or not marker.is_dir():
        raise WorktreeError(NOT_A_REPO)


def _short(text: str) -> str:
    """The useful tail of git's message: one line, bounded."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines[-2:])[:300] or "sem detalhes."


async def _rev(repo: Path, ref: str) -> str | None:
    code, out, _ = await _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.strip() if code == 0 and out.strip() else None


async def _current_branch(repo: Path) -> str:
    code, out, _ = await _git(repo, "branch", "--show-current")
    return out.strip() if code == 0 else ""


async def _existing_branch(repo: Path, path: Path, expected: Path) -> str:
    """Branch of a proven worktree at `path`; WorktreeError for anything else."""
    found = None
    if not path.is_symlink() and _real(path) == expected:
        found = await gitinfo.project_worktree(path, [repo])
    if found is None or found.path != expected or found.main_repo != _real(repo):
        raise WorktreeError(
            f"Já existe uma pasta {path} que não é uma worktree deste projeto; "
            "ela não foi alterada."
        )
    branch = await _current_branch(path)
    if not branch:
        raise WorktreeError(f"A worktree {path} está sem branch (HEAD solto); ela não foi alterada.")
    return branch


async def _require_task_branch(repo: Path, path: Path, branch: str) -> None:
    code, _, _ = await _git(repo, "check-ref-format", f"refs/heads/{branch}")
    if not branch.startswith(BRANCH_PREFIX) or code != 0:
        raise WorktreeError(f"A branch {branch!r} não é de uma tarefa; a worktree foi mantida.")
    if await _current_branch(path) != branch:
        raise WorktreeError(f"A worktree não está na branch {branch}; ela foi mantida.")


async def _default_refs(repo: Path) -> list[str]:
    """Refs that count as "the default branch" (see the module docstring)."""
    code, out, _ = await _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    target = out.strip()
    if code == 0 and target.startswith("refs/remotes/origin/"):
        name = target.removeprefix("refs/remotes/origin/")
        refs = [target]
        if await _rev(repo, f"refs/heads/{name}"):
            refs.append(f"refs/heads/{name}")
        return refs
    current = await _current_branch(repo)
    if current:
        return [f"refs/heads/{current}"]
    refs = []
    for name in ("main", "master"):
        if await _rev(repo, f"refs/heads/{name}"):
            refs.append(f"refs/heads/{name}")
    return refs
