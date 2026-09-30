"""Groups: related sessions of a project. Only the app knows them."""

import sqlite3
import time
import unicodedata
from dataclasses import dataclass

from vibing.db import transaction
from vibing.projects import ProjectNotFoundError

NAME_MAX = 80


@dataclass(frozen=True)
class Group:
    id: int
    project_id: int
    name: str
    created_at: int


class GroupError(Exception):
    """Base error. The message is shown to the user."""


class GroupNotFoundError(GroupError):
    pass


class InvalidGroupNameError(GroupError):
    pass


class DuplicateGroupNameError(GroupError):
    pass


class GroupProjectMismatchError(GroupError):
    pass


_COLUMNS = "id, project_id, name, created_at"


def _from_row(row: sqlite3.Row) -> Group:
    return Group(
        id=row["id"], project_id=row["project_id"], name=row["name"],
        created_at=row["created_at"],
    )


def _fold(text: str) -> str:
    """Case and accents ignored, for comparing names."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidGroupNameError("Dê um nome ao agrupador.")
    if len(cleaned) > NAME_MAX:
        raise InvalidGroupNameError(f"O nome pode ter até {NAME_MAX} caracteres.")
    return cleaned


def list_groups(conn: sqlite3.Connection, project_id: int | None = None) -> list[Group]:
    query = f"SELECT {_COLUMNS} FROM session_groups"
    params: tuple[int, ...] = ()
    if project_id is not None:
        query += " WHERE project_id = ?"
        params = (project_id,)
    query += " ORDER BY project_id, created_at, id"
    return [_from_row(row) for row in conn.execute(query, params).fetchall()]


def get_group(conn: sqlite3.Connection, group_id: int) -> Group:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM session_groups WHERE id = ?", (group_id,)
    ).fetchone()
    if row is None:
        raise GroupNotFoundError("Agrupador não encontrado.")
    return _from_row(row)


def check_group_for(conn: sqlite3.Connection, group_id: int, project_id: int) -> Group:
    """The group, if it belongs to the project."""
    group = get_group(conn, group_id)
    if group.project_id != project_id:
        raise GroupProjectMismatchError("O agrupador é de outro projeto.")
    return group


def _check_unique(
    conn: sqlite3.Connection, project_id: int, name: str, exclude_id: int | None = None
) -> None:
    folded = _fold(name)
    rows = conn.execute(
        "SELECT id, name FROM session_groups WHERE project_id = ?", (project_id,)
    ).fetchall()
    if any(row["id"] != exclude_id and _fold(row["name"]) == folded for row in rows):
        raise DuplicateGroupNameError("Já existe um agrupador com esse nome neste projeto.")


def create_group(conn: sqlite3.Connection, project_id: int, name: str) -> Group:
    cleaned = clean_name(name)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ProjectNotFoundError("Projeto não encontrado.")
        _check_unique(conn, project_id, cleaned)
        cursor = conn.execute(
            "INSERT INTO session_groups (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, cleaned, int(time.time())),
        )
    return get_group(conn, cursor.lastrowid)


def rename_group(conn: sqlite3.Connection, group_id: int, name: str) -> Group:
    cleaned = clean_name(name)
    with transaction(conn):
        group = get_group(conn, group_id)
        _check_unique(conn, group.project_id, cleaned, exclude_id=group_id)
        conn.execute("UPDATE session_groups SET name = ? WHERE id = ?", (cleaned, group_id))
    return get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int) -> tuple[Group, list[str]]:
    """Remove the group. Returns it and the sessions it released (not deleted)."""
    with transaction(conn):
        group = get_group(conn, group_id)
        released = [
            row["session_id"]
            for row in conn.execute(
                "SELECT session_id FROM sessions WHERE group_id = ?", (group_id,)
            )
        ]
        conn.execute("DELETE FROM session_groups WHERE id = ?", (group_id,))
    return group, released
