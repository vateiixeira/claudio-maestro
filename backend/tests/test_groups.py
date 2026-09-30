"""Groups module: name rules and CRUD over SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from vibing import db, groups
from vibing.projects import ProjectNotFoundError


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "t.db")) as c:
        db.migrate(c)
        for pid in (1, 2):
            c.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (?, 'p', ?, '#fff', 0, 0)",
                (pid, f"/tmp/p{pid}"),
            )
        yield c


def add_session(conn, session_id: str, project_id: int = 1, group_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, group_id) VALUES (?, ?, '/tmp', 't', 0, 0, ?)",
        (session_id, project_id, group_id),
    )


def test_create_trims_and_lists(conn):
    created = groups.create_group(conn, 1, "  Checkout  ")
    assert created.name == "Checkout"
    assert created.project_id == 1
    assert groups.list_groups(conn) == [created]
    assert groups.list_groups(conn, 2) == []


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_name_is_refused(conn, name):
    with pytest.raises(groups.InvalidGroupNameError, match="Dê um nome ao agrupador."):
        groups.create_group(conn, 1, name)


def test_name_limit(conn):
    assert groups.create_group(conn, 1, "a" * 80).name == "a" * 80
    with pytest.raises(groups.InvalidGroupNameError, match="até 80 caracteres"):
        groups.create_group(conn, 1, "b" * 81)


def test_duplicate_ignores_case_and_accents(conn):
    groups.create_group(conn, 1, "Refatoração")
    with pytest.raises(groups.DuplicateGroupNameError, match="Já existe um agrupador"):
        groups.create_group(conn, 1, "refatoracao")
    # Another project may use the same name.
    assert groups.create_group(conn, 2, "Refatoração").project_id == 2


def test_create_in_unknown_project(conn):
    with pytest.raises(ProjectNotFoundError):
        groups.create_group(conn, 99, "x")


def test_rename(conn):
    g = groups.create_group(conn, 1, "a")
    other = groups.create_group(conn, 1, "b")
    assert groups.rename_group(conn, g.id, "A").name == "A"  # own name, other case: allowed
    with pytest.raises(groups.DuplicateGroupNameError):
        groups.rename_group(conn, g.id, "B")
    with pytest.raises(groups.GroupNotFoundError, match="Agrupador não encontrado."):
        groups.rename_group(conn, 999, "x")
    assert groups.get_group(conn, other.id).name == "b"


def test_delete_returns_released_sessions(conn):
    g = groups.create_group(conn, 1, "a")
    add_session(conn, "s1", group_id=g.id)
    add_session(conn, "s2", group_id=g.id)
    add_session(conn, "s3")
    removed, released = groups.delete_group(conn, g.id)
    assert removed == g
    assert sorted(released) == ["s1", "s2"]
    rows = conn.execute("SELECT group_id FROM sessions").fetchall()
    assert all(row["group_id"] is None for row in rows)
    with pytest.raises(groups.GroupNotFoundError):
        groups.delete_group(conn, g.id)


def test_check_group_for(conn):
    g = groups.create_group(conn, 1, "a")
    assert groups.check_group_for(conn, g.id, 1) == g
    with pytest.raises(groups.GroupProjectMismatchError, match="outro projeto"):
        groups.check_group_for(conn, g.id, 2)
    with pytest.raises(groups.GroupNotFoundError):
        groups.check_group_for(conn, 999, 1)
