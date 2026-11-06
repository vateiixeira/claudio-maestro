"""Projects: a registered folder with a name and a color."""

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from claudio_maestro.db import transaction
from claudio_maestro.security import PathNotAllowedError, is_within, resolve_within

REGULAR_KIND = "regular"
SCRATCH_KIND = "scratch"
SCRATCH_NAME = "Sem projeto"
SCRATCH_DIRNAME = "scratch"
_SCRATCH_COLOR = "#71717A"


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    path: str
    color: str
    position: int
    created_at: int
    available: bool
    kind: str = REGULAR_KIND


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


class ScratchProjectError(ProjectError):
    """The built-in "Sem projeto" cannot be changed or removed."""


_COLUMNS = "id, name, path, color, position, created_at, kind"


def _from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        color=row["color"],
        position=row["position"],
        created_at=row["created_at"],
        available=Path(row["path"]).is_dir(),
        kind=row["kind"],
    )


def list_projects(conn: sqlite3.Connection) -> list[Project]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM projects ORDER BY kind = 'scratch', position, id"
    ).fetchall()
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


def scratch_root(data_dir: Path) -> Path:
    """Folder of the built-in project: each conversation without a project gets a subfolder."""
    return data_dir / SCRATCH_DIRNAME


def ensure_scratch_project(conn: sqlite3.Connection, data_dir: Path) -> Project:
    """Create the built-in "Sem projeto" row, or fix its folder when the data dir moved.

    Idempotent. The folder is `<data_dir>/scratch` (mode 700), stored resolved.
    """
    root = scratch_root(data_dir)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    folder = str(root.resolve())
    with transaction(conn):
        row = conn.execute("SELECT id, path FROM projects WHERE kind = 'scratch'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at, kind)"
                " VALUES (?, ?, ?, 0, ?, 'scratch')",
                (SCRATCH_NAME, folder, _SCRATCH_COLOR, int(time.time())),
            )
        elif row["path"] != folder:
            conn.execute("UPDATE projects SET path = ? WHERE id = ?", (folder, row["id"]))
    return next(project for project in list_projects(conn) if project.kind == SCRATCH_KIND)


def create_project(
    conn: sqlite3.Connection, *, name: str, path: str, color: str, home: Path, data_dir: Path
) -> Project:
    folder = resolve_project_folder(path, home)
    if is_within(folder, data_dir.resolve()):
        raise ProjectPathNotAllowedError("Esta pasta é do próprio app e não pode virar projeto.")
    try:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM projects WHERE path = ?", (str(folder),)).fetchone():
                raise DuplicateProjectPathError("Já existe um projeto com esta pasta.")
            position = conn.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) FROM projects WHERE kind = 'regular'"
            ).fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, str(folder), color, position, int(time.time())),
            )
    except sqlite3.IntegrityError as exc:
        raise DuplicateProjectPathError("Já existe um projeto com esta pasta.") from exc
    return get_project(conn, cursor.lastrowid)


SCRATCH_IMMUTABLE_MESSAGE = 'O projeto embutido "Sem projeto" não pode ser alterado nem removido.'
SCRATCH_NO_PROJECT_FEATURES_MESSAGE = "Conversas sem projeto não têm git, agentes nem tarefas."


def refuse_scratch(project: Project, message: str = SCRATCH_IMMUTABLE_MESSAGE) -> None:
    if project.kind == SCRATCH_KIND:
        raise ScratchProjectError(message)


def require_regular(project: Project) -> Project:
    """The project, or ScratchProjectError when it is the built-in "Sem projeto"."""
    refuse_scratch(project, SCRATCH_NO_PROJECT_FEATURES_MESSAGE)
    return project


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
        refuse_scratch(get_project(conn, project_id))
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            conn.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?",
                (*changes.values(), project_id),
            )
    return get_project(conn, project_id)


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    """Remove the project record only. The folder and conversations stay."""
    refuse_scratch(get_project(conn, project_id))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
