"""Folder browser limited to the user's home folder."""

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from vibing.security import PathNotAllowedError, resolve_within


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    git: bool


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


def list_dirs(path: str | None, home: Path) -> DirListing:
    """List direct subfolders of `path` (default: home). Never lists files."""
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

    try:
        with os.scandir(folder) as items:
            entries = [entry for item in items if (entry := _entry(item, home))]
    except PermissionError as exc:
        raise BrowseNotAllowedError("Sem permissão para ler esta pasta.") from exc

    entries.sort(key=lambda e: (e.name.casefold(), e.name))
    parent = None if folder == home else str(folder.parent)
    return DirListing(path=str(folder), parent=parent, entries=entries)
