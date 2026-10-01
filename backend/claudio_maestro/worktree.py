"""Which git worktree a session is working in, read from its transcript.

A linked worktree has a `.git` *file* whose `gitdir:` points into
`<main repo>/.git/worktrees/<id>`. Submodules also use a `.git` file, but it
points into `.git/modules/`, so they do not count. No git process is started.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

TAIL_BYTES = 64 * 1024
_CWD = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Worktree:
    name: str
    path: str


def last_cwd(path: Path, tail_bytes: int = TAIL_BYTES) -> str | None:
    """Last `cwd` value in the last `tail_bytes` of a `.jsonl` transcript."""
    try:
        with open(path, "rb") as file:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(max(0, size - tail_bytes))
            data = file.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    matches = _CWD.findall(data)
    if not matches:
        return None
    try:
        return json.loads(f'"{matches[-1]}"')
    except ValueError:
        return None


def worktree_of(cwd: str) -> Worktree | None:
    """The linked worktree containing `cwd`, or None (main checkout, submodule, no git)."""
    folder = Path(cwd)
    for candidate in (folder, *folder.parents):
        marker = candidate / ".git"
        try:
            if marker.is_dir():
                return None
            if not marker.is_file():
                continue
            text = marker.read_text(errors="replace")[:4096]
        except OSError:
            return None
        for line in text.splitlines():
            if line.startswith("gitdir:"):
                parts = Path(line[len("gitdir:"):].strip()).parts
                if len(parts) >= 2 and parts[-2] == "worktrees":
                    return Worktree(name=candidate.name, path=str(candidate))
                return None
        return None
    return None


def current_worktree(transcript: Path) -> tuple[bool, Worktree | None]:
    """(decided, worktree) for the session's latest folder.

    Not decided when the last `cwd` is unknown or its folder is gone (a removed
    worktree): the caller keeps what it had.
    """
    cwd = last_cwd(transcript)
    if cwd is None or not Path(cwd).is_dir():
        return False, None
    return True, worktree_of(cwd)


@dataclass(frozen=True)
class LinkedWorktree:
    """A folder proven (by pointers on disk) to be a linked worktree of `main_repo`."""

    name: str
    path: Path
    main_repo: Path


def _gitdir_pointer(file: Path, base: Path) -> Path | None:
    """The `gitdir:` target of a `.git` file, resolved against `base` (symlinks followed)."""
    try:
        with open(file, "rb") as handle:
            text = handle.read(4096).decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("gitdir:"):
            value = line[len("gitdir:"):].strip()
            return _real(base / value) if value and "\x00" not in value else None
    return None


def _real(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except (OSError, ValueError):
        return None


def _first_line(file: Path) -> str | None:
    try:
        with open(file, "rb") as handle:
            lines = handle.read(4096).decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    value = lines[0].strip() if lines else ""
    return value if value and "\x00" not in value else None


def linked_worktree(path: str | os.PathLike[str]) -> LinkedWorktree | None:
    """The linked worktree that contains `path`, proven in both directions. No git process.

    The first `.git` found above the (resolved) path must be a file, never a link
    or a folder. Its `gitdir:` must lead to `<repo>/.git/worktrees/<id>`, whose
    `commondir` must lead back to `<repo>/.git` and whose `gitdir` file must name
    this very `.git` file. A submodule (`.git/modules/...`), a bare repository, a
    forged pointer or one that only matches in one direction gives None.
    """
    real = _real(Path(path))
    if real is None:
        return None
    root = None
    for candidate in (real, *real.parents):
        marker = candidate / ".git"
        try:
            if marker.is_symlink():
                return None
            if marker.is_dir():
                return None
            if marker.is_file():
                root = candidate
                break
        except OSError:
            return None
    if root is None:
        return None
    admin = _gitdir_pointer(root / ".git", root)
    if admin is None or admin.parent.name != "worktrees":
        return None
    common_text = _first_line(admin / "commondir")
    common = _real(admin / common_text) if common_text else None
    if common is None or common != admin.parent.parent or common.name != ".git":
        return None
    try:
        if not common.is_dir():
            return None
    except OSError:
        return None
    # The way back: the admin folder must name this exact `.git` file (not a link to one).
    back = _first_line(admin / "gitdir")
    if back is None or _real(admin / back) != root / ".git":
        return None
    return LinkedWorktree(name=root.name, path=root, main_repo=common.parent)


def parse_worktree_list(output: str) -> list[str]:
    """Paths in `git worktree list --porcelain` output, main checkout first."""
    return [line[len("worktree "):] for line in output.splitlines() if line.startswith("worktree ")]
