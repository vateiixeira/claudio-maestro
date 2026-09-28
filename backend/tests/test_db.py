import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from vibing import db


def table_names(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


@contextmanager
def open_db(path: Path) -> Iterator[sqlite3.Connection]:
    """Connection closed at the end of the block, so no ResourceWarning leaks."""
    with closing(db.connect(path)) as conn:
        yield conn


def test_migrate_creates_tables(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert {"projects", "sessions", "app_state"} <= table_names(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_migrate_twice_is_harmless(tmp_path: Path):
    path = tmp_path / "test.db"
    with open_db(path) as conn:
        db.migrate(conn)
        conn.execute("INSERT INTO app_state (key, value) VALUES ('layout', '{}')")

    with open_db(path) as conn:
        db.migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert (
            conn.execute("SELECT value FROM app_state WHERE key = 'layout'").fetchone()[0]
            == "{}"
        )


def test_init_db_creates_data_dir(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "vibing.db"
    db.init_db(path)
    assert path.exists()
    with open_db(path) as conn:
        assert {"projects", "sessions", "app_state"} <= table_names(conn)


def test_foreign_keys_enabled(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_session_requires_existing_project(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sessions"
                " (session_id, project_id, cwd, title, created_at, last_activity_at)"
                " VALUES ('s1', 999, '/x', 't', 0, 0)"
            )


def test_app_startup_runs_migrations(client, data_dir: Path):
    with open_db(data_dir / "vibing.db") as conn:
        assert {"projects", "sessions", "app_state"} <= table_names(conn)
