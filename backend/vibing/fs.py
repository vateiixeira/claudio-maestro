"""Folder browser limited to the user's home folder."""

import asyncio
import os
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

from vibing import gitinfo
from vibing.security import PathNotAllowedError, resolve_within


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    git: bool
    # Filled by `with_branches` for folders with git.
    branch: str | None = None
    # HEAD detached: `branch` then holds the short hash.
    detached: bool = False


@dataclass(frozen=True)
class RepoPreview:
    name: str
    rel_path: str
    path: str
    branch: str | None
    detached: bool


@dataclass(frozen=True)
class DirListing:
    path: str
    parent: str | None
    entries: list[DirEntry] = field(default_factory=list)


class BrowseError(Exception):
    """Base error. The message is shown to the user."""


class BrowseNotAllowedError(BrowseError):
    pass


class BrowseNotFoundError(BrowseError):
    pass


class BrowseNotADirectoryError(BrowseError):
    pass


def _has_git(folder: Path) -> bool:
    try:
        return (folder / ".git").exists()
    except OSError:
        return False


def _entry(item: os.DirEntry[str], home: Path) -> DirEntry | None:
    """Build an entry for a visible subfolder, or None to skip it."""
    if item.name.startswith("."):
        return None
    try:
        if not item.is_dir():
            return None
        target = resolve_within(item.path, [home])
    except (OSError, PathNotAllowedError):
        # Unreadable, broken link, or link pointing outside home.
        return None
    return DirEntry(name=item.name, path=str(target), git=_has_git(target))


def resolve_folder(path: str | None, home: Path) -> Path:
    """The folder a browsing request points at: inside home and readable."""
    home = home.resolve()
    try:
        folder = resolve_within(path, [home]) if path else home
    except PathNotAllowedError as exc:
        raise BrowseNotAllowedError("Só é possível navegar dentro da pasta pessoal.") from exc

    try:
        is_dir = stat.S_ISDIR(folder.stat().st_mode)
    except PermissionError as exc:
        raise BrowseNotAllowedError("Sem permissão para ler esta pasta.") from exc
    except OSError as exc:
        raise BrowseNotFoundError("Pasta não encontrada.") from exc
    if not is_dir:
        raise BrowseNotADirectoryError("O caminho não é uma pasta.")
    return folder


def list_dirs(path: str | None, home: Path) -> DirListing:
    """List direct subfolders of `path` (default: home). Never lists files."""
    home = home.resolve()
    folder = resolve_folder(path, home)

    try:
        with os.scandir(folder) as items:
            entries = [entry for item in items if (entry := _entry(item, home))]
    except PermissionError as exc:
        raise BrowseNotAllowedError("Sem permissão para ler esta pasta.") from exc

    entries.sort(key=lambda e: (e.name.casefold(), e.name))
    parent = None if folder == home else str(folder.parent)
    return DirListing(path=str(folder), parent=parent, entries=entries)


async def with_branches(listing: DirListing) -> DirListing:
    """Fill `branch` and `detached` of every git entry, in parallel (each with the git time limit)."""
    git_entries = [entry for entry in listing.entries if entry.git]
    statuses = await asyncio.gather(
        *(gitinfo.repo_status(Path(entry.path)) for entry in git_entries)
    )
    found = {
        entry.path: (None, False) if status.error
        else (status.head if status.detached else status.branch, status.detached)
        for entry, status in zip(git_entries, statuses, strict=True)
    }
    entries = [
        replace(entry, branch=found[entry.path][0], detached=found[entry.path][1])
        if entry.path in found else entry
        for entry in listing.entries
    ]
    return replace(listing, entries=entries)


async def preview_repos(path: str, home: Path) -> tuple[list[RepoPreview], bool]:
    """Repositories a project on `path` would have, and whether the limit was reached.

    Uses the project's own discovery (`gitinfo.project_repos_scan`).
    """
    if not path:
        raise BrowseNotADirectoryError("Informe uma pasta.")
    folder = await asyncio.to_thread(resolve_folder, path, home)
    repos, limit_reached = await gitinfo.project_repos_scan(folder)
    previews = [
        RepoPreview(
            name=folder.name if repo.rel_path == "." else Path(repo.path).name,
            rel_path=repo.rel_path,
            path=repo.path,
            branch=None if repo.error else (repo.head if repo.detached else repo.branch),
            detached=repo.detached and not repo.error,
        )
        for repo in repos
    ]
    return previews, limit_reached
