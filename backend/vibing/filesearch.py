"""File and folder suggestions for `@` mentions, like the VS Code extension:
the file name (or, with `/` in the term, the path) contains the term, at most
`RESULT_LIMIT` files, plus the folders of those files whose path contains it.

The listing comes from `git ls-files` (tracked plus untracked not ignored). A folder
that is not a repository lists each repository inside it with git and walks the rest,
so ignored heavy folders (`.venv`, caches) never fill the walk limit.
"""

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vibing.gitinfo import GitError, discover, run_git

logger = logging.getLogger(__name__)

LIST_SECONDS = 30.0
WALK_LIMIT = 20_000
RESULT_LIMIT = 100
GIT_LIST_TIMEOUT = 10.0
EXCLUDED_DIRS = frozenset({"node_modules", ".git", "dist", "build", ".next", ".nuxt"})
# Skipped only by the walk (outside git): caches and tool folders that can be huge.
WALK_SKIPPED_DIRS = frozenset({
    "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".cache", "target", "coverage", ".gradle", ".idea",
})
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", ".env", "yarn-error.log"})


class FileSearchError(Exception):
    """Failure with a message ready to show (pt-BR)."""


@dataclass(frozen=True)
class FileMatch:
    path: str
    name: str
    type: Literal["file", "directory"]


def is_excluded(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    name = parts[-1]
    return (
        name in EXCLUDED_NAMES
        or name.endswith(".log")
        or name.startswith(".env.")
        or name.startswith("npm-debug.log")
    )


def match_files(paths: list[str], query: str) -> list[FileMatch]:
    """`paths` sorted. Same rule as the extension's `**/*<term>*` glob, ignoring case:
    the match starts at a folder boundary and the `*` never crosses `/`."""
    term = query.lower()
    pattern = re.compile(r"(?:^|/)[^/]*" + re.escape(term) + r"[^/]*$", re.IGNORECASE)
    files = [p for p in paths if pattern.search(p)][:RESULT_LIMIT]
    folders: set[str] = set()
    for path in files:
        parts = path.split("/")[:-1]
        for end in range(1, len(parts) + 1):
            folder = "/".join(parts[:end])
            if term in folder.lower():
                folders.add(folder)
    found = [FileMatch(p, p.rsplit("/", 1)[-1], "file") for p in files]
    found += [FileMatch(f + "/", f.rsplit("/", 1)[-1], "directory") for f in folders]
    found.sort(key=lambda m: m.path)
    return found


async def _ls_files(repo: Path, prefix: str) -> list[str]:
    try:
        code, out, err = await run_git(
            repo, "ls-files", "-co", "--exclude-standard", "-z", timeout=GIT_LIST_TIMEOUT
        )
    except GitError as exc:
        raise FileSearchError(f"Falha ao listar os arquivos: {exc}") from exc
    if code != 0:
        raise FileSearchError(f"Falha ao listar os arquivos: {err.strip() or code}")
    # A nested repository that is not a submodule comes as `inner/`: not a file.
    return [prefix + p for p in out.split("\0") if p and not p.endswith("/")]


async def _inside_work_tree(folder: Path) -> bool:
    try:
        code, out, _ = await run_git(folder, "rev-parse", "--is-inside-work-tree", timeout=GIT_LIST_TIMEOUT)
    except GitError:
        return False
    return code == 0 and out.strip() == "true"


def _walk(folder: Path, skip: set[Path]) -> list[str]:
    found: list[str] = []
    for root, dirs, names in os.walk(folder):  # does not follow links
        base = Path(root)
        dirs[:] = sorted(
            d for d in dirs
            if d not in EXCLUDED_DIRS and d not in WALK_SKIPPED_DIRS
            and not d.startswith(".") and base / d not in skip
        )
        for name in sorted(names):
            rel = (base / name).relative_to(folder).as_posix()
            if is_excluded(rel):
                continue
            found.append(rel)
            if len(found) >= WALK_LIMIT:
                return found
    return found


async def _list(folder: Path) -> list[str]:
    if await _inside_work_tree(folder):
        paths = await _ls_files(folder, "")
    else:
        repos = [r for r in await asyncio.to_thread(discover, folder) if r != folder]
        paths = []
        for repo in repos:
            prefix = repo.relative_to(folder).as_posix() + "/"
            try:
                paths += await _ls_files(repo, prefix)
            except FileSearchError:
                logger.warning("Repositório %s ficou fora da busca de arquivos", repo, exc_info=True)
        paths += await asyncio.to_thread(_walk, folder, set(repos))
    return sorted({p for p in paths if not is_excluded(p)})


class FileIndex:
    """Listing per folder, cached for `LIST_SECONDS`; the search runs on it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lists: dict[Path, tuple[float, list[str]]] = {}
        self._locks: dict[Path, asyncio.Lock] = {}

    async def search(self, folder: Path, query: str) -> list[FileMatch]:
        paths = await self._listing(folder.resolve())
        return await asyncio.to_thread(match_files, paths, query)

    async def _listing(self, key: Path) -> list[str]:
        async with self._locks.setdefault(key, asyncio.Lock()):
            entry = self._lists.get(key)
            if entry is not None and self._clock() - entry[0] < LIST_SECONDS:
                return entry[1]
            paths = await _list(key)
            self._lists[key] = (self._clock(), paths)
            return paths
