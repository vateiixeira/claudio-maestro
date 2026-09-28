from pathlib import Path

import pytest

from vibing import db


def table_names(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_migrate_creates_tables(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.migrate(conn)
    assert {"projects", "sessions", "app_state"} <= table_names(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_migrate_twice_is_harmless(tmp_path: Path):
    path = tmp_path / "test.db"
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES ('layout', '{}')"
    )
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert conn.execute("SELECT value FROM app_state WHERE key = 'layout'").fetchone()[0] == "{}"


def test_init_db_creates_data_dir(tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "vibing.db"
    db.init_db(path)
    assert path.exists()
    conn = db.connect(path)
    assert {"projects", "sessions", "app_state"} <= table_names(conn)


def test_foreign_keys_enabled(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.migrate(conn)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_session_requires_existing_project(tmp_path: Path):
    import sqlite3

    conn = db.connect(tmp_path / "test.db")
    db.migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            " VALUES ('s1', 999, '/x', 't', 0, 0)"
        )


def test_app_startup_runs_migrations(client, data_dir: Path):
    conn = db.connect(data_dir / "vibing.db")
    assert {"projects", "sessions", "app_state"} <= table_names(conn)
