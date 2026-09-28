"""Projects: a registered folder with a name and a color."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from vibing.db import transaction
from vibing.security import PathNotAllowedError, resolve_within


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    path: str
    color: str
    position: int
    created_at: int
    available: bool


class ProjectError(Exception):
    """Base error. The message is shown to the user."""


class ProjectNotFoundError(ProjectError):
    pass


class DuplicateProjectPathError(ProjectError):
    pass


class InvalidProjectPathError(ProjectError):
    pass


class ProjectPathNotAllowedError(ProjectError):
    pass


_COLUMNS = "id, name, path, color, position, created_at"


def _from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        color=row["color"],
        position=row["position"],
        created_at=row["created_at"],
        available=Path(row["path"]).is_dir(),
    )


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM projects ORDER BY position, id").fetchall()
    return [_from_row(row) for row in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> Project:
    row = conn.execute(f"SELECT {_COLUMNS} FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError("Projeto não encontrado.")
    return _from_row(row)


def project_roots(conn: sqlite3.Connection) -> list[Path]:
    """Folders of every registered project, for `security.resolve_within`."""
    return [Path(row["path"]) for row in conn.execute("SELECT path FROM projects")]


def resolve_project_folder(path: str, home: Path) -> Path:
    """Resolve a folder chosen for a new project and check it is usable."""
    try:
        resolved = resolve_within(path, [home])
    except PathNotAllowedError as exc:
        raise ProjectPathNotAllowedError("A pasta precisa estar dentro da pasta pessoal.") from exc
    if not resolved.exists():
        raise InvalidProjectPathError("A pasta não existe.")
    if not resolved.is_dir():
        raise InvalidProjectPathError("O caminho não é uma pasta.")
    return resolved


def create_project(
    conn: sqlite3.Connection, *, name: str, path: str, color: str, home: Path
) -> Project:
    folder = resolve_project_folder(path, home)
    try:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM projects WHERE path = ?", (str(folder),)).fetchone():
                raise DuplicateProjectPathError("Já existe um projeto com esta pasta.")
            position = conn.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) FROM projects"
            ).fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, str(folder), color, position, int(time.time())),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateProjectPathError("Já existe um projeto com esta pasta.") from exc
    return get_project(conn, cursor.lastrowid)


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    name: str | None = None,
    color: str | None = None,
    position: int | None = None,
) -> Project:
    changes = {
        key: value
        for key, value in (("name", name), ("color", color), ("position", position))
        if value is not None
    }
    with transaction(conn):
        get_project(conn, project_id)
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            conn.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?",
                (*changes.values(), project_id),
            )
    return get_project(conn, project_id)


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Remove the project record only. The folder and conversations stay."""
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if cursor.rowcount == 0:
        raise ProjectNotFoundError("Projeto não encontrado.")
