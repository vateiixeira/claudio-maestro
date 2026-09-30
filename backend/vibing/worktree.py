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


def parse_worktree_list(output: str) -> list[str]:
    """Paths in `git worktree list --porcelain` output, main checkout first."""
    return [line[len("worktree "):] for line in output.splitlines() if line.startswith("worktree ")]
