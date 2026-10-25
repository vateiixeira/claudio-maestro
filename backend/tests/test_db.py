import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from claudio_maestro import db


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


@pytest.mark.parametrize("keep_run", [True, False])
def test_queue_migration_preserves_runs_foreign_keys_and_deleted_id_sequence(tmp_path, keep_run):
    with open_db(tmp_path / "old-queue.db") as conn:
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("queue_paused" in str(statement) for statement in statements)
        )
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute("INSERT INTO projects VALUES (1, 'p', '/p', '#fff', 0, 0)")
        conn.execute("INSERT INTO specialists (id, slug, name, project_id, created_at, updated_at) VALUES (1, 'rev', 'Rev', 1, 0, 0)")
        conn.execute("INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at, specialist_id) VALUES ('s', 1, '/p', 't', 0, 0, 1)")
        conn.execute("INSERT INTO specialist_runs VALUES (7, 1, 's', 'manual', NULL, 10, 11, 'concluded', 'feito')")
        conn.execute("INSERT INTO specialist_runs VALUES (99, 1, NULL, 'schedule', 5, 10, 11, 'skipped', 'sem uso')")
        conn.execute("DELETE FROM specialist_runs WHERE id = 99")
        if not keep_run:
            conn.execute("DELETE FROM specialist_runs WHERE id = 7")

        db.migrate(conn)

        if keep_run:
            assert dict(conn.execute("SELECT * FROM specialist_runs WHERE id = 7").fetchone()) == {
                "id": 7, "specialist_id": 1, "session_id": "s", "trigger": "manual", "scheduled_for": None,
                "started_at": 10, "ended_at": 11, "outcome": "concluded", "reason": "feito", "message": 0,
            }
        assert conn.execute("SELECT queue_paused FROM specialists").fetchone()[0] == 0
        for outcome in ("queued", "starting", "cancelled"):
            cursor = conn.execute("INSERT INTO specialist_runs (specialist_id, trigger, started_at, outcome) VALUES (1, 'manual', 20, ?)", (outcome,))
            assert cursor.lastrowid > 99
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        indexes = {r["name"] for r in conn.execute("PRAGMA index_list(specialist_runs)")}
        assert {"specialist_runs_specialist_started", "specialist_runs_session"} <= indexes
        conn.execute("DELETE FROM sessions WHERE session_id = 's'")
        if keep_run:
            assert conn.execute("SELECT session_id FROM specialist_runs WHERE id = 7").fetchone()[0] is None
        conn.execute("DELETE FROM specialists WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM specialist_runs").fetchone()[0] == 0


def test_sessions_have_worktree_columns(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"history_dir", "worktree_name", "worktree_path", "git_branch"} <= cols


def test_sessions_have_mark_columns(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"mark", "mark_note", "mark_until", "priority"} <= cols.keys()
    assert cols["priority"]["dflt_value"] == "0"


def test_mark_migration_keeps_existing_sessions_unmarked(tmp_path: Path):
    # A database from before the marks, with a session in it.
    with open_db(tmp_path / "old.db") as conn:
        # The migration that adds the marks (later ones may follow it).
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("mark_until" in str(statement) for statement in statements)
        )
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                if callable(statement):
                    statement(conn)
                else:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/p', '#fff', 0, 0)"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            " VALUES ('old', 1, '/p', 't', 0, 0)"
        )
        assert "mark" not in {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}

        db.migrate(conn)

        row = conn.execute("SELECT * FROM sessions WHERE session_id = 'old'").fetchone()
    assert row["mark"] is None and row["mark_note"] is None and row["mark_until"] is None
    assert row["priority"] == 0
    assert row["detached_at"] is None


def test_specialist_migration_adds_empty_denied_tools(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        # The migration that adds the blocked tools (later ones may follow it).
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("denied_tools" in str(statement) for statement in statements)
        )
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                if callable(statement):
                    statement(conn)
                else:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/p', '#fff', 0, 0)"
        )
        conn.execute(
            "INSERT INTO specialists (slug, name, project_id, created_at, updated_at)"
            " VALUES ('rev', 'Rev', 1, 0, 0)"
        )
        assert "denied_tools" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(specialists)")
        }

        db.migrate(conn)

        row = conn.execute("SELECT denied_tools FROM specialists WHERE slug = 'rev'").fetchone()
    assert row["denied_tools"] == "[]"


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
    path = tmp_path / "nested" / "dir" / "maestro.db"
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
    with open_db(data_dir / "maestro.db") as conn:
        assert {"projects", "sessions", "app_state"} <= table_names(conn)


def insert_project(conn, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, path, color, position, created_at)"
        " VALUES (?, 'p', ?, '#fff', 0, 0)",
        (project_id, f"/tmp/p{project_id}"),
    )


def insert_session(conn, session_id: str, project_id: int = 1, group_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, group_id) VALUES (?, ?, '/tmp', 't', 0, 0, ?)",
        (session_id, project_id, group_id),
    )


def test_migration_creates_session_groups(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert "session_groups" in table_names(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert "group_id" in columns


def test_removing_group_releases_sessions(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        insert_project(conn)
        conn.execute(
            "INSERT INTO session_groups (id, project_id, name, created_at) VALUES (7, 1, 'g', 0)"
        )
        insert_session(conn, "a", group_id=7)
        conn.execute("DELETE FROM session_groups WHERE id = 7")
        row = conn.execute("SELECT group_id FROM sessions WHERE session_id = 'a'").fetchone()
        assert row["group_id"] is None


def test_removing_project_removes_its_groups(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        insert_project(conn)
        conn.execute(
            "INSERT INTO session_groups (project_id, name, created_at) VALUES (1, 'g', 0)"
        )
        conn.execute("DELETE FROM projects WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM session_groups").fetchone()[0] == 0


def test_migration_creates_labels_tables(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert {"labels", "session_labels"} <= table_names(conn)


def test_removing_session_or_label_removes_the_link(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        insert_project(conn)
        insert_session(conn, "a")
        insert_session(conn, "b")
        conn.execute("INSERT INTO labels (id, slug, color, created_at) VALUES (1, 'x', '#000000', 0)")
        conn.execute("INSERT INTO session_labels (session_id, label_id) VALUES ('a', 1), ('b', 1)")
        conn.execute("DELETE FROM sessions WHERE session_id = 'a'")
        assert conn.execute("SELECT COUNT(*) FROM session_labels").fetchone()[0] == 1
        conn.execute("DELETE FROM labels WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM session_labels").fetchone()[0] == 0


def test_label_ids_are_never_reused(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        conn.execute("INSERT INTO labels (slug, color, created_at) VALUES ('a', '#000000', 0)")
        conn.execute("INSERT INTO labels (slug, color, created_at) VALUES ('b', '#000000', 0)")
        highest = conn.execute("SELECT MAX(id) FROM labels").fetchone()[0]
        conn.execute("DELETE FROM labels WHERE id = ?", (highest,))
        conn.execute("INSERT INTO labels (slug, color, created_at) VALUES ('c', '#000000', 0)")
        new_id = conn.execute("SELECT id FROM labels WHERE slug = 'c'").fetchone()[0]
        assert new_id > highest


def test_label_slug_is_unique(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        conn.execute("INSERT INTO labels (slug, color, created_at) VALUES ('x', '#000000', 0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO labels (slug, color, created_at) VALUES ('x', '#000000', 0)")


def test_sessions_have_remote_control_columns(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"remote_control", "remote_control_bridge", "spawn_version"} <= cols.keys()
    assert cols["remote_control"]["dflt_value"] == "0" and cols["remote_control"]["notnull"]
    assert cols["spawn_version"]["dflt_value"] == "0" and cols["spawn_version"]["notnull"]
    assert cols["remote_control_bridge"]["dflt_value"] is None


def test_remote_control_migration_keeps_existing_sessions_off(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("remote_control_bridge" in str(statement) for statement in statements)
        )
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                if callable(statement):
                    statement(conn)
                else:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/p', '#fff', 0, 0)"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            " VALUES ('old', 1, '/p', 't', 0, 0)"
        )

        db.migrate(conn)

        row = conn.execute("SELECT * FROM sessions WHERE session_id = 'old'").fetchone()
    assert row["remote_control"] == 0
    assert row["remote_control_bridge"] is None
    assert row["spawn_version"] == 0


def test_migration_creates_specialist_tables(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        db.migrate(conn)
        assert {
            "specialists", "specialist_schedules", "specialist_runs",
            "specialist_items", "specialist_notices",
        } <= table_names(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "specialist_id" in cols and cols["specialist_id"]["dflt_value"] is None


def test_specialists_migration_keeps_existing_sessions(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("CREATE TABLE specialists" in str(statement) for statement in statements)
        )
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                if callable(statement):
                    statement(conn)
                else:
                    conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/p', '#fff', 0, 0)"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            " VALUES ('old', 1, '/p', 't', 0, 0)"
        )
        assert "specialist_id" not in {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}

        db.migrate(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
        row = conn.execute("SELECT * FROM sessions WHERE session_id = 'old'").fetchone()
    assert row["title"] == "t" and row["specialist_id"] is None
