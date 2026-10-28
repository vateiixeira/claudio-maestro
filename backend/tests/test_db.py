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


def migrate_before_drop(conn) -> None:
    """`db.migrate` stopped at version 31: the old `specialist_*` tables still exist.

    Tests of what migrations 1 to 31 did to those tables use this; migration 32 drops them.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:31])
        patch.setattr(db, "SCHEMA_VERSION", 31)
        db.migrate(conn)


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

        migrate_before_drop(conn)

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

        migrate_before_drop(conn)

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
        migrate_before_drop(conn)
        assert {
            "specialists", "specialist_schedules", "specialist_runs",
            "specialist_items", "specialist_notices",
        } <= table_names(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        cols = {row["name"]: row for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "agent_id" in cols and cols["agent_id"]["dflt_value"] is None


def test_specialists_migration_keeps_existing_sessions(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("CREATE TABLE specialists" in str(statement) for statement in statements)
        )
        assert before < len(db.MIGRATIONS)
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
    assert row["title"] == "t" and row["agent_id"] is None


def test_migration_keeps_runs_and_accepts_comment_trigger(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        before = next(
            index for index, statements in enumerate(db.MIGRATIONS)
            if any("main_session_id" in str(statement) for statement in statements)
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
            " VALUES ('s1', 1, '/p', 't', 0, 0)"
        )
        conn.execute(
            "INSERT INTO specialists (slug, name, project_id, created_at, updated_at)"
            " VALUES ('a', 'A', 1, 1, 1)"
        )
        agent_id = conn.execute("SELECT id FROM specialists").fetchone()[0]
        conn.execute(
            "INSERT INTO specialist_runs (specialist_id, session_id, trigger, started_at, outcome)"
            " VALUES (?, 's1', 'schedule', 10, 'concluded')",
            (agent_id,),
        )
        conn.execute(
            "INSERT INTO specialist_runs (specialist_id, session_id, trigger, scheduled_for,"
            " started_at, ended_at, outcome, reason) VALUES (?, NULL, 'manual', 5, 20, 30,"
            " 'failed', 'x')",
            (agent_id,),
        )

        migrate_before_drop(conn)

        runs = conn.execute("SELECT * FROM specialist_runs ORDER BY id").fetchall()
        assert [(r["trigger"], r["session_id"], r["started_at"]) for r in runs] == [
            ("schedule", "s1", 10), ("manual", None, 20),
        ]
        assert (runs[1]["scheduled_for"], runs[1]["ended_at"], runs[1]["reason"]) == (5, 30, "x")
        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(specialist_runs)")
        }
        assert {"specialist_runs_specialist_started", "specialist_runs_session"} <= indexes
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        comment_id = conn.execute(
            "INSERT INTO specialist_runs (specialist_id, trigger, started_at, outcome)"
            " VALUES (?, 'comment', 40, 'running')",
            (agent_id,),
        ).lastrowid
        assert conn.execute(
            "SELECT trigger FROM specialist_runs WHERE id = ?", (comment_id,)
        ).fetchone()[0] == "comment"
        # The foreign keys survived the rebuild: deleting the session unlinks the run.
        conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
        assert conn.execute(
            "SELECT session_id FROM specialist_runs WHERE id = ?", (runs[0]["id"],)
        ).fetchone()[0] is None
        # And so do the cascades: deleting the agent removes its runs.
        conn.execute("DELETE FROM specialists WHERE id = ?", (agent_id,))
        assert conn.execute("SELECT COUNT(*) FROM specialist_runs").fetchone()[0] == 0


def test_migration_creates_conversation_tables(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        migrate_before_drop(conn)
        assert {
            "specialist_announcements", "specialist_prs", "specialist_pr_comments",
        } <= table_names(conn)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(specialists)")}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(specialist_pr_comments)")}
    assert "main_session_id" in cols
    assert "specialist_pr_comments_status_pr" in indexes


def test_comment_dispatch_migration_preserves_queued_comments(tmp_path: Path):
    with open_db(tmp_path / "test.db") as conn:
        before = next(i + 1 for i, statements in enumerate(db.MIGRATIONS)
                      if any("CREATE TABLE specialist_pr_comments (" in str(sql) for sql in statements))
        for statements in db.MIGRATIONS[:before]:
            for sql in statements:
                if callable(sql):
                    sql(conn)
                else:
                    conn.execute(sql)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute("INSERT INTO projects (name, path, color, position, created_at) VALUES ('p','/p','x',0,0)")
        conn.execute("INSERT INTO specialists (slug, name, project_id, created_at, updated_at) VALUES ('a','A',1,0,0)")
        conn.execute("INSERT INTO specialist_pr_comments (comment_id, pr_url, specialist_id, author, body, html_url, created_at, received_at) VALUES ('issue:1','https://github.com/o/r/pull/1',1,'vini','ajuste','url',1,2)")
        migrate_before_drop(conn)
        conn.execute("UPDATE specialist_pr_comments SET status = 'dispatching' WHERE comment_id = 'issue:1'")
        row = conn.execute("SELECT body, status FROM specialist_pr_comments").fetchone()
        assert (row['body'], row['status']) == ('ajuste', 'dispatching')
        conn.execute("UPDATE specialist_pr_comments SET status = 'uncertain'")
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_migration_30_renames_specialist_id(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        before = 29
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {before}")
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at) VALUES (1, 'p', '/p', '#fff', 0, 0)")
        conn.execute("INSERT INTO specialists (id, slug, name, project_id, created_at, updated_at) VALUES (7, 'rev', 'Rev', 1, 0, 0)")
        conn.execute("INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at, specialist_id) VALUES ('s', 1, '/p', 't', 0, 0, 7)")
        assert len(db.MIGRATIONS) >= 30

        db.migrate(conn)

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        assert "agent_id" in columns and "specialist_id" not in columns
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 's'").fetchone()[0] == 7
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # The foreign key survives the rename; migration 31 moved it from specialists to agents.
        conn.execute("DELETE FROM agents WHERE id = 7")
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 's'").fetchone()[0] is None


def _build_v30_with_specialist(conn) -> None:
    """A database at version 30 with one specialist and everything that hangs from it."""
    for statements in db.MIGRATIONS[:30]:
        for statement in statements:
            statement(conn) if callable(statement) else conn.execute(statement)
    conn.execute("PRAGMA user_version = 30")
    for pid in (1, 2):
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            f" VALUES ({pid}, 'p', '/p{pid}', '#fff', 0, 0)"
        )
    for sid in ("main", "s-run", "s-msg"):
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            f" VALUES ('{sid}', 1, '/p1', 't', 0, 0)"
        )
    conn.execute(
        "INSERT INTO specialists (id, slug, name, project_id, extra_project_ids, model, effort,"
        " run_text, denied_tools, enabled, main_session_id, created_at, updated_at)"
        " VALUES (7, 'sentry', 'Sentry', 1, '[2]', 'opus', 'high', 'Execute a rotina.',"
        " '[\"WebFetch\"]', 1, 'main', 11, 12)"
    )
    conn.execute("UPDATE sessions SET agent_id = 7 WHERE session_id IN ('main', 's-run', 's-msg')")
    conn.execute("INSERT INTO specialist_schedules (id, specialist_id, days, time, last_fired_at) VALUES (4, 7, '12345', '09:00', 100)")
    conn.execute("INSERT INTO specialist_schedules (id, specialist_id, days, time) VALUES (5, 7, '67', '10:30')")
    conn.execute("INSERT INTO specialist_items VALUES (7, 'SENTRY-1', 'handled', 'http://x', 'nota', 1, 2)")

    def run(rid, session, trigger, started, outcome, message=0, reason=None, ended=None):
        conn.execute(
            "INSERT INTO specialist_runs (id, specialist_id, session_id, trigger, scheduled_for,"
            " started_at, ended_at, outcome, reason, message) VALUES (?, 7, ?, ?, NULL, ?, ?, ?, ?, ?)",
            (rid, session, trigger, started, ended, outcome, reason, message),
        )

    run(1, "s-run", "schedule", 10, "concluded", ended=20, reason="feito")
    run(2, "s-run", "comment", 30, "running")  # same session as run 1: the latest keeps it
    run(3, None, "manual", 40, "queued")
    run(4, "s-msg", "manual", 50, "concluded", message=1, ended=60)
    run(5, None, "schedule", 70, "missed", reason="atrasou")
    conn.execute("INSERT INTO specialist_notices (id, specialist_id, session_id, kind, text, created_at) VALUES (1, 7, 's-run', 'summary', 'resumo', 25)")
    conn.execute("INSERT INTO specialist_notices (id, specialist_id, session_id, kind, text, created_at, read_at) VALUES (2, 7, 's-msg', 'notice', 'da conversa', 55, 56)")
    conn.execute("INSERT INTO specialist_notices (id, specialist_id, session_id, kind, text, created_at) VALUES (3, 7, NULL, 'alert', 'sem sessão', 57)")
    conn.execute("INSERT INTO specialist_announcements (id, specialist_id, run_id, session_id, text, created_at) VALUES (1, 7, 1, 's-run', 'anuncio', 21)")
    conn.execute("INSERT INTO specialist_announcements (id, specialist_id, run_id, session_id, text, created_at) VALUES (2, 7, 4, 's-msg', 'da mensagem', 61)")
    conn.execute("INSERT INTO specialist_chats VALUES ('s-msg', 7)")
    conn.execute("INSERT INTO specialist_prs VALUES ('https://github.com/o/r/pull/1', 7, 's-run', 1, 2, 0)")
    conn.execute(
        "INSERT INTO specialist_pr_comments VALUES ('issue:1', 'https://github.com/o/r/pull/1', 7,"
        " 'vi', 'ajuste', NULL, NULL, 'u', 1, 2, 'uncertain', 3)"
    )


def test_migration_31_copies_specialists_into_agents(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)

        migrate_before_drop(conn)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 31
        agents = conn.execute("SELECT * FROM agents").fetchall()
        assert len(agents) == 1
        agent = agents[0]
        assert (agent["id"], agent["slug"], agent["name"], agent["project_id"]) == (7, "sentry", "Sentry", 1)
        assert (agent["enabled"], agent["main_session_id"], agent["reports_to"]) == (1, "main", None)
        assert (agent["created_at"], agent["updated_at"], agent["definition_hash"]) == (11, 12, None)
        import json
        assert json.loads(agent["legacy_json"]) == {
            "model": "opus", "effort": "high", "denied_tools": ["WebFetch"],
            "extra_project_ids": [2],
        }

        routine = conn.execute("SELECT * FROM routines").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM routines").fetchone()[0] == 1
        assert (routine["agent_id"], routine["project_id"], routine["name"]) == (7, 1, "Sentry")
        assert (routine["instruction"], routine["enabled"]) == ("Execute a rotina.", 1)
        schedules = conn.execute("SELECT id, routine_id, days, time, last_fired_at FROM routine_schedules ORDER BY id").fetchall()
        assert [tuple(row) for row in schedules] == [
            (4, routine["id"], "12345", "09:00", 100), (5, routine["id"], "67", "10:30", None),
        ]
        item = conn.execute("SELECT * FROM registry").fetchone()
        assert (item["agent_id"], item["key"], item["status"], item["link"], item["note"]) == (
            7, "SENTRY-1", "handled", "http://x", "nota",
        )

        # Runs keep their ids; message runs are gone; the queued one is cancelled; `schedule`
        # becomes `routine` (linked to the routine); runs may share a session.
        runs = {row["id"]: row for row in conn.execute("SELECT * FROM runs")}
        assert sorted(runs) == [1, 2, 3, 5]
        assert (runs[1]["source"], runs[1]["routine_id"], runs[1]["outcome"], runs[1]["session_id"]) == ("routine", 7, "concluded", "s-run")
        assert (runs[2]["source"], runs[2]["routine_id"], runs[2]["outcome"], runs[2]["session_id"]) == ("comment", None, "running", "s-run")
        assert (runs[3]["outcome"], runs[3]["reason"], runs[3]["source"], runs[3]["ended_at"]) == ("cancelled", "Fila migrada", "manual", 40)
        assert (runs[5]["outcome"], runs[5]["reason"]) == ("missed", "atrasou")
        assert conn.execute("SELECT COUNT(*) FROM wakeups").fetchone()[0] == 0

        # Notices point at the latest copied run of their session; announcements of dropped runs unlink.
        notices = {row["id"]: row["run_id"] for row in conn.execute("SELECT id, run_id FROM notices")}
        assert notices == {1: 2, 2: None, 3: None}
        assert conn.execute("SELECT read_at FROM notices WHERE id = 2").fetchone()[0] == 56
        announcements = {row["id"]: row["run_id"] for row in conn.execute("SELECT id, run_id FROM announcements")}
        assert announcements == {1: 1, 2: None}
        assert conn.execute("SELECT session_id, agent_id FROM agent_chats").fetchone()[:] == ("s-msg", 7)
        pr = conn.execute("SELECT * FROM agent_prs").fetchone()
        assert (pr["agent_id"], pr["session_id"], pr["polled_at"], pr["closed"]) == (7, "s-run", 2, 0)
        comment = conn.execute("SELECT * FROM agent_pr_comments").fetchone()
        assert (comment["agent_id"], comment["status"], comment["batch_at"]) == (7, "uncertain", 3)

        # The old tables stay (the end of the milestone removes them) and the sessions still point at the agent id.
        assert "specialists" in table_names(conn) and "specialist_runs" in table_names(conn)
        assert conn.execute("SELECT COUNT(*) FROM specialists").fetchone()[0] == 1
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 'main'").fetchone()[0] == 7
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        # New ids continue after the old ones (no reuse of ids deleted before the copy).
        new = conn.execute(
            "INSERT INTO runs (agent_id, source, started_at, outcome) VALUES (7, 'manual', 1, 'skipped')"
        )
        assert new.lastrowid > 5


SPECIALIST_TABLES = (
    "specialists", "specialist_schedules", "specialist_runs", "specialist_items",
    "specialist_notices", "specialist_announcements", "specialist_prs",
    "specialist_pr_comments", "specialist_chats",
)


def test_migration_32_drops_specialist_tables(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)
        with db.transaction(conn):  # migration 31 only; the drop (32) stays pending
            for statement in db.MIGRATIONS[30]:
                statement(conn) if callable(statement) else conn.execute(statement)
            conn.execute("PRAGMA user_version = 31")
        assert set(SPECIALIST_TABLES) <= table_names(conn)
        copied = ("agents", "routines", "routine_schedules", "runs", "registry", "notices",
                  "announcements", "agent_chats", "agent_prs", "agent_pr_comments")
        # Later migrations add columns to some of these; compare only what existed at version 31.
        columns = {
            table: ", ".join(row["name"] for row in conn.execute(f"PRAGMA table_info({table})"))
            for table in copied
        }
        before = {
            table: [tuple(row) for row in conn.execute(f"SELECT {columns[table]} FROM {table} ORDER BY 1, 2")]
            for table in copied
        }
        sessions_before = [
            tuple(row) for row in conn.execute("SELECT session_id, agent_id FROM sessions ORDER BY 1")
        ]
        assert len(db.MIGRATIONS) >= 32

        db.migrate(conn)

        assert db.schema_version(conn) == db.SCHEMA_VERSION
        assert not set(SPECIALIST_TABLES) & table_names(conn)
        leftovers = [
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'specialist%' OR sql LIKE '%specialist%'"
            )
        ]
        assert leftovers == []
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_sequence WHERE name LIKE 'specialist%'"
        ).fetchone()[0] == 0
        # What was copied stays exactly as it was.
        for table, rows in before.items():
            now = [tuple(row) for row in conn.execute(f"SELECT {columns[table]} FROM {table} ORDER BY 1, 2")]
            assert now == rows, table
        assert [
            tuple(row) for row in conn.execute("SELECT session_id, agent_id FROM sessions ORDER BY 1")
        ] == sessions_before
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sessions'").fetchone()[0]
        assert "agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL" in sql
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        # The foreign key still works after the old parent table is gone.
        conn.execute("DELETE FROM agents WHERE id = 7")
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 'main'").fetchone()[0] is None


def test_migration_32_can_run_twice(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)
        db.migrate(conn)
        # A crash between the statements and the version stamp must not make a rerun fail.
        with db.transaction(conn):
            for statement in db.MIGRATIONS[31]:
                statement(conn) if callable(statement) else conn.execute(statement)
        assert not set(SPECIALIST_TABLES) & table_names(conn)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migration_32_on_a_database_without_specialists(tmp_path: Path):
    with open_db(tmp_path / "t.db") as conn:
        db.migrate(conn)
        assert not set(SPECIALIST_TABLES) & table_names(conn)
        assert db.SCHEMA_VERSION == 34


def test_migration_31_keeps_autoincrement_watermark(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)
        conn.execute("INSERT INTO specialist_runs (id, specialist_id, trigger, started_at, outcome) VALUES (90, 7, 'manual', 1, 'skipped')")
        conn.execute("DELETE FROM specialist_runs WHERE id = 90")

        db.migrate(conn)

        cursor = conn.execute(
            "INSERT INTO runs (agent_id, source, started_at, outcome) VALUES (7, 'manual', 1, 'skipped')"
        )
        assert cursor.lastrowid == 91


def test_migration_31_clamps_text_to_the_new_checks(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)
        conn.execute("UPDATE specialists SET run_text = '  ', name = ?", ("n" * 120,))

        db.migrate(conn)

        row = conn.execute("SELECT name, instruction FROM routines").fetchone()
        assert (len(row["name"]), row["instruction"]) == (80, "Execute a rotina agendada.")


def test_migration_31_runs_on_a_database_without_specialists(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        for statements in db.MIGRATIONS[:30]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute("PRAGMA user_version = 30")

        db.migrate(conn)

        for table in ("agents", "routines", "runs", "notices", "registry"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_migration_is_idempotent_on_rows(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)

        db.migrate(conn)
        before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("agents", "routines", "routine_schedules", "runs", "registry",
                          "notices", "announcements", "agent_chats", "agent_prs", "agent_pr_comments")
        }
        db.migrate(conn)
        after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}

        assert before == after
        assert before["agents"] == 1 and before["routines"] == 1 and before["runs"] == 4


def test_agent_tables_cascade_from_project(tmp_path: Path):
    with open_db(tmp_path / "t.db") as conn:
        db.migrate(conn)
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at) VALUES (1, 'p', '/p', '#fff', 0, 0)")
        conn.execute("INSERT INTO agents (id, slug, name, project_id, created_at, updated_at) VALUES (1, 'a', 'A', 1, 0, 0)")
        conn.execute("INSERT INTO routines (project_id, agent_id, name, instruction, created_at, updated_at) VALUES (1, 1, 'r', 'i', 0, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO routines (project_id, agent_id, name, instruction, created_at, updated_at) VALUES (1, 1, '', 'i', 0, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO wakeups (agent_id, source, priority, payload, created_at) VALUES (1, 'manual', 0, ?, 0)", ("x" * 20001,))
        conn.execute("DELETE FROM projects WHERE id = 1")
        for table in ("agents", "routines"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def _agent_sessions_db(conn) -> None:
    _build_v30_with_specialist(conn)
    migrate_before_drop(conn)


def test_sessions_agent_fk_points_at_agents_after_migration_31(tmp_path: Path):
    from claudio_maestro.org import store

    with open_db(tmp_path / "old.db") as conn:
        _agent_sessions_db(conn)
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sessions'").fetchone()[0]
        assert "agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL" in sql
        assert "REFERENCES specialists" not in sql
        # (a) an agent created now (no specialist with that id) can own a session.
        fresh = store.create_agent(conn, slug="novo", name="Novo", project_id=1, reports_to=None, now=1)
        assert fresh.id not in {row[0] for row in conn.execute("SELECT id FROM specialists")}
        conn.execute("UPDATE sessions SET agent_id = ? WHERE session_id = 's-run'", (fresh.id,))
        # a made-up id is still refused.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE sessions SET agent_id = 999 WHERE session_id = 's-run'")
        # (b) deleting the agent leaves the session without owner, through the FK.
        store.delete_agent(conn, fresh.id)
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 's-run'").fetchone()[0] is None
        # (c) the old table no longer matters to sessions: dropping it (what the end of the
        # milestone does) leaves `sessions.agent_id` and the agents alone.
        conn.execute("DROP TABLE specialists")
        assert conn.execute("SELECT COUNT(*) FROM agents WHERE id = 7").fetchone()[0] == 1
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 'main'").fetchone()[0] == 7
        # (d) the file is sound and the rewritten schema is seen by every new statement.
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sessions_agent_fk_is_seen_by_other_connections(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _agent_sessions_db(conn)
        with open_db(tmp_path / "old.db") as other:
            other.execute("PRAGMA foreign_keys = ON")
            sql = other.execute("SELECT sql FROM sqlite_master WHERE name = 'sessions'").fetchone()[0]
            assert "REFERENCES agents(id)" in sql
            other.execute("DELETE FROM agents WHERE id = 7")
            assert other.execute("SELECT agent_id FROM sessions WHERE session_id = 'main'").fetchone()[0] is None


def test_rebind_sessions_agent_fk_refuses_unknown_schema(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _agent_sessions_db(conn)
        # Already rewritten: the snippet is gone, so a second run must fail loudly, not guess.
        with pytest.raises(RuntimeError, match="tabela de sessões"):
            with db.transaction(conn):
                db.rebind_sessions_agent_fk(conn)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_rebind_sessions_agent_fk_rejects_orphan_agent_ids(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v30_with_specialist(conn)
        # A session owned by an id the copy did not carry over cannot satisfy the new FK.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE sessions SET agent_id = 55 WHERE session_id = 's-run'")
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.migrate(conn)
        assert db.schema_version(conn) == 30


def test_legacy_specialists_are_mirrored_into_agents_until_the_old_tables_go(tmp_path: Path):
    """The old specialist service still runs: its sessions need a row in `agents` too."""
    with open_db(tmp_path / "old.db") as conn:
        _agent_sessions_db(conn)
        conn.execute(
            "INSERT INTO specialists (id, slug, name, project_id, enabled, created_at, updated_at)"
            " VALUES (20, 'novo', 'Novo', 2, 1, 5, 6)"
        )
        agent = conn.execute("SELECT * FROM agents WHERE id = 20").fetchone()
        assert (agent["slug"], agent["name"], agent["project_id"], agent["enabled"]) == ("novo", "Novo", 2, 1)
        assert (agent["created_at"], agent["updated_at"]) == (5, 6)
        conn.execute("UPDATE sessions SET agent_id = 20 WHERE session_id = 's-run'")

        conn.execute(
            "UPDATE specialists SET slug = 'outro', name = 'Outro', enabled = 0, main_session_id = 's-msg',"
            " updated_at = 9 WHERE id = 20"
        )
        agent = conn.execute("SELECT * FROM agents WHERE id = 20").fetchone()
        assert (agent["slug"], agent["name"], agent["enabled"], agent["main_session_id"], agent["updated_at"]) == (
            "outro", "Outro", 0, "s-msg", 9,
        )

        conn.execute("DELETE FROM specialists WHERE id = 20")
        assert conn.execute("SELECT COUNT(*) FROM agents WHERE id = 20").fetchone()[0] == 0
        assert conn.execute("SELECT agent_id FROM sessions WHERE session_id = 's-run'").fetchone()[0] is None

        # Dropping the table drops its triggers; the agents stay.
        conn.execute("DROP TABLE specialists")
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        assert not {name for name in names if name.startswith("specialists_mirror")}
        assert conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 1


def _build_v32_with_work(conn) -> None:
    """A database at version 32 with work items, attempts, a coordinator, a pending decision and a PR."""
    for statements in db.MIGRATIONS[:32]:
        for statement in statements:
            statement(conn) if callable(statement) else conn.execute(statement)
    conn.execute("PRAGMA user_version = 32")
    conn.execute("INSERT INTO projects (id, name, path, color, position, created_at) VALUES (1, 'p', '/p1', '#fff', 0, 0)")
    for sid in ("coord", "s-a1", "s-a2", "s-a3"):
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at)"
            f" VALUES ('{sid}', 1, '/p1', 't', 0, 0)"
        )

    def item(item_id, status, *, parent=None, priority="normal", source="manual", external="e"):
        conn.execute(
            "INSERT INTO work_items (id, project_id, parent_id, source, source_instance, source_project,"
            " external_id, title, priority, status, phase, revision, created_at, updated_at)"
            " VALUES (?, 1, ?, ?, 'i', 'sp', ?, ?, ?, ?, 'implementation', 3, 100, 200)",
            (item_id, parent, source, f"{external}{item_id}", f"Item {item_id}", priority, status),
        )

    item(1, "review", priority="high", source="github", external="gh")
    item(2, "active", parent=1)
    conn.execute("INSERT INTO work_specs (work_item_id, dossier_ref, role) VALUES (2, 'dossier-2.json', 'implementer')")

    def attempt(attempt_id, item_id, session, role, state, created):
        conn.execute(
            "INSERT INTO work_attempts (id, work_item_id, session_id, role, state, work_revision, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (attempt_id, item_id, session, role, state, created, created),
        )

    attempt(10, 2, "s-a1", "implementer", "failed", 110)
    attempt(11, 2, "s-a2", "reviewer", "succeeded", 120)
    attempt(12, 2, None, "implementer", "running", 130)
    attempt(13, 1, "s-a3", "investigator", "cancelled", 140)
    conn.execute("INSERT INTO work_coordinators (project_id, session_id, created_at) VALUES (1, 'coord', 50)")
    conn.execute(
        "INSERT INTO work_decision_requests (id, work_item_id, attempt_id, work_revision, dossier_ref, target_ref,"
        " request_ref, status, created_at) VALUES (1, 2, 12, 1, 'd', 't', 'request-1.json', 'pending', 150)"
    )
    conn.execute(
        "INSERT INTO work_decision_requests (id, work_item_id, attempt_id, work_revision, dossier_ref, target_ref,"
        " request_ref, status, created_at, answered_at) VALUES (2, 2, 11, 1, 'd', 't', 'request-2.json', 'answered',"
        " 151, 160)"
    )
    conn.execute(
        "INSERT INTO work_prs (url, project_id, work_item_id, origin_attempt_id, last_attempt_id, origin_session_id,"
        " last_session_id, workspace, target_ref, created_at, polled_at, closed)"
        " VALUES ('https://github.com/o/r/pull/9', 1, 2, 10, 12, 's-a1', 's-a2', '/p1', 't', 170, 180, 1)"
    )


def test_migration_33_copies_work_items_into_tasks(tmp_path: Path):
    import json

    with open_db(tmp_path / "old.db") as conn:
        _build_v32_with_work(conn)

        db.migrate(conn)

        assert db.schema_version(conn) == db.SCHEMA_VERSION
        tasks = {row["id"]: row for row in conn.execute("SELECT * FROM tasks")}
        assert sorted(tasks) == [1, 2]
        assert (tasks[1]["status"], tasks[1]["priority"], tasks[1]["parent_task_id"]) == ("in_review", "high", None)
        assert (tasks[2]["status"], tasks[2]["priority"], tasks[2]["parent_task_id"]) == ("in_progress", "normal", 1)
        for task in tasks.values():
            assert (task["project_id"], task["created_by"], task["description"]) == (1, "human", "")
            assert (task["assignee_agent_id"], task["reviewer_agent_id"], task["routine_id"]) == (None, None, None)
            assert (task["revision"], task["run_count"], task["max_runs"]) == (1, 0, 20)
            assert (task["created_at"], task["updated_at"], task["blocked_reason"]) == (100, 200, None)
        assert tasks[1]["title"] == "Item 1" and tasks[1]["closed_at"] is None
        assert json.loads(tasks[2]["legacy_json"]) == {
            "dossier_ref": "dossier-2.json", "source": "manual", "external_id": "e2",
            "coordinator_session_id": "coord",
        }
        assert json.loads(tasks[1]["legacy_json"])["dossier_ref"] is None
        assert json.loads(tasks[1]["legacy_json"])["source"] == "github"

        # One `app` comment per attempt, numbered in order inside each task.
        comments = [
            (row["task_id"], row["author_kind"], row["text"], row["created_at"])
            for row in conn.execute("SELECT * FROM task_comments ORDER BY id")
        ]
        assert comments == [
            (1, "app", "Tentativa 1 (investigador): cancelada, sessão s-a3", 140),
            (2, "app", "Tentativa 1 (implementador): falhou, sessão s-a1", 110),
            (2, "app", "Tentativa 2 (revisor): concluída, sessão s-a2", 120),
            (2, "app", "Tentativa 3 (implementador): em andamento, sem sessão", 130),
        ]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # New tasks continue after the old ids.
        new = conn.execute(
            "INSERT INTO tasks (project_id, title, created_at, updated_at) VALUES (1, 'n', 1, 1)"
        )
        assert new.lastrowid == 3


def test_migration_33_maps_every_work_status(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        for statements in db.MIGRATIONS[:32]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute("PRAGMA user_version = 32")
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at) VALUES (1, 'p', '/p1', '#fff', 0, 0)")
        statuses = ("backlog", "ready", "active", "waiting", "blocked", "review", "done", "cancelled")
        for index, status in enumerate(statuses, start=1):
            conn.execute(
                "INSERT INTO work_items (id, project_id, source, source_instance, source_project, external_id,"
                " title, priority, status, phase, created_at, updated_at)"
                " VALUES (?, 1, 's', 'i', 'p', ?, 't', 'low', ?, 'review', 10, 20)",
                (index, f"x{index}", status),
            )

        db.migrate(conn)

        rows = {
            row["id"]: (row["status"], row["blocked_reason"], row["closed_at"])
            for row in conn.execute("SELECT id, status, blocked_reason, closed_at FROM tasks")
        }
        assert rows == {
            1: ("todo", None, None), 2: ("todo", None, None), 3: ("in_progress", None, None),
            4: ("blocked", "Aguardava decisão no sistema anterior.", None),
            5: ("blocked", None, None), 6: ("in_review", None, None),
            7: ("done", None, 20), 8: ("cancelled", None, 20),
        }
        assert conn.execute("SELECT priority FROM tasks WHERE id = 1").fetchone()[0] == "low"
        assert conn.execute("SELECT COUNT(*) FROM task_comments").fetchone()[0] == 0


def test_migration_33_keeps_legacy_work_for_the_file_migration(tmp_path: Path):
    import json

    with open_db(tmp_path / "old.db") as conn:
        _build_v32_with_work(conn)

        db.migrate(conn)

        rows = [
            (row["kind"], row["project_id"], row["task_id"], json.loads(row["data"]))
            for row in conn.execute("SELECT * FROM org_legacy_work ORDER BY id")
        ]
        assert rows == [
            ("coordinator", 1, None, {"session_id": "coord", "created_at": 50}),
            ("decision", 1, 2, {"request_ref": "request-1.json", "created_at": 150}),
            ("pr", 1, 2, {
                "url": "https://github.com/o/r/pull/9", "last_session_id": "s-a2",
                "created_at": 170, "polled_at": 180, "closed": 1,
            }),
        ]
        # Only pending decisions are carried; the answered one is history.
        assert conn.execute("SELECT COUNT(*) FROM org_legacy_work WHERE kind = 'decision'").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO org_legacy_work (kind, data) VALUES ('other', '{}')")


def test_migration_33_creates_the_new_tables_and_columns(tmp_path: Path):
    with open_db(tmp_path / "t.db") as conn:
        db.migrate(conn)

        assert {"tasks", "task_comments", "task_sessions", "decisions", "ci_receipts",
                "org_legacy_work"} <= table_names(conn)
        for table, column in (
            ("runs", "task_id"), ("runs", "commented"), ("runs", "rewoken"), ("wakeups", "task_id"),
            ("routines", "create_task"), ("agent_prs", "task_id"), ("decisions", "session_id"),
        ):
            assert column in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}, (table, column)
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at) VALUES (1, 'p', '/p', '#fff', 0, 0)")
        for title in ("", "x" * 161):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO tasks (project_id, title, created_at, updated_at) VALUES (1, ?, 0, 0)", (title,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (project_id, title, status, created_at, updated_at) VALUES (1, 't', 'backlog', 0, 0)")
        conn.execute("INSERT INTO tasks (id, project_id, title, created_at, updated_at) VALUES (1, 1, 't', 0, 0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO task_comments (task_id, author_kind, text, created_at) VALUES (1, 'human', '', 0)")
        conn.execute("DELETE FROM projects WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def migrate_to(conn, version: int) -> None:
    """`db.migrate` stopped at `version`, so the tables the later migrations drop still exist."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(db, "MIGRATIONS", db.MIGRATIONS[:version])
        patch.setattr(db, "SCHEMA_VERSION", version)
        db.migrate(conn)


def _fill_work_tables(conn) -> None:
    """A row in each `work_*` table of a version 33 database that `_build_v32_with_work` filled."""
    execute = conn.execute
    execute("INSERT INTO work_events (id, work_item_id, attempt_id, kind, actor, revision, data, created_at)"
            " VALUES (1, 2, 12, 'k', 'a', 1, '{}', 100)")
    execute("INSERT INTO work_notifications (event_id, project_id, coordinator_session_id, work_item_id,"
            " attempt_id, kind, summary, dispatch_state, created_at)"
            " VALUES (1, 1, 'coord', 2, 12, 'k', 's', 'queued', 100)")
    execute("INSERT INTO work_dependencies (work_item_id, depends_on_id, created_at) VALUES (2, 1, 100)")
    execute("INSERT INTO work_resource_claims (resource, attempt_id, created_at) VALUES ('r', 12, 100)")
    execute("INSERT INTO work_collections (id, work_item_id, source, source_instance, source_project, created_at)"
            " VALUES ('c1', 1, 's', 'i', 'p', 100)")
    execute("INSERT INTO work_collection_pages VALUES ('c1', 'cur', 'dig', 'ref')")
    execute("INSERT INTO work_collection_items VALUES ('c1', 2, NULL)")
    execute("INSERT INTO work_collection_inputs VALUES ('c1', 2, 1)")
    execute("INSERT INTO work_input_history VALUES (2, 1, 'd')")
    execute("INSERT INTO work_attempt_inputs VALUES (12, 'd', NULL)")
    execute("INSERT INTO work_attempt_workspaces VALUES (12, 'p')")
    execute("INSERT INTO work_attempt_signals (attempt_id, updated_at) VALUES (12, 100)")
    execute("INSERT INTO work_process_closures (attempt_id, status, updated_at) VALUES (12, 'closed', 100)")
    execute("INSERT INTO work_capacity_suspensions VALUES (12, 'human_decision_quiescent', 100)")
    execute("INSERT INTO work_review_bindings (work_item_id, author_attempt_id, input_revision, item_revision,"
            " dossier_ref, target_ref, status, created_at, updated_at)"
            " VALUES (2, 10, 1, 1, 'd', 't', 'queued', 100, 100)")
    execute("INSERT INTO work_pr_batches VALUES ('b1', 'https://github.com/o/r/pull/9', 'delivered', 100, NULL)")
    execute("INSERT INTO work_pr_comments VALUES ('https://github.com/o/r/pull/9', 'c1', 'u', 'ref', 100, 100,"
            " 'queued', 'b1')")
    execute("INSERT INTO work_pr_inbox VALUES ('b1', 2, 12, 'rcpt', 'd', 100)")
    execute("INSERT INTO work_pr_registrations (session_id, url, attempt_id, state)"
            " VALUES ('s-a1', 'https://github.com/o/r/pull/9', 10, 'pending')")
    execute("INSERT INTO work_ci_receipts VALUES ('ev', 12, 's-a1', 1, 1, NULL, 'd', 't', 'dg', 'dg', 100)")
    execute("INSERT INTO work_project_pool_limits VALUES (1, 2)")
    execute("INSERT INTO work_project_resources VALUES (1, 'port')")
    execute("INSERT INTO work_project_modes VALUES (1, 1, 0, 100)")
    execute("INSERT INTO work_project_fences VALUES (1, 'f', 'r', 100)")


def test_migration_34_drops_work_tables(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v32_with_work(conn)
        migrate_to(conn, 33)
        _fill_work_tables(conn)
        legacy = [tuple(row) for row in conn.execute("SELECT * FROM org_legacy_work ORDER BY id")]
        tasks = [tuple(row) for row in conn.execute("SELECT * FROM tasks ORDER BY id")]
        work_tables = {name for name in table_names(conn) if name.startswith("work_")}
        assert len(work_tables) == 31
        for table in sorted(work_tables):  # every one holds rows, so the drop has data to cascade over
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
        assert db.schema_version(conn) == 33
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # The list the migration drops is the real one, not a guess.
        assert set(db.LEGACY_WORK_TABLES) == work_tables

        db.migrate(conn)

        assert db.schema_version(conn) == 34 == db.SCHEMA_VERSION
        assert not [name for name in table_names(conn) if name.startswith("work_")]
        leftovers = [
            tuple(row) for row in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE name LIKE 'work\\_%' ESCAPE '\\'"
                " OR tbl_name LIKE 'work\\_%' ESCAPE '\\'"
            )
        ]
        assert leftovers == []
        assert conn.execute("SELECT COUNT(*) FROM sqlite_sequence WHERE name LIKE 'work\\_%' ESCAPE '\\'"
                            ).fetchone()[0] == 0
        # `migrate_work` runs after the migrations and reads this table: it must survive, intact.
        assert "org_legacy_work" in table_names(conn)
        assert [tuple(row) for row in conn.execute("SELECT * FROM org_legacy_work ORDER BY id")] == legacy
        assert len(legacy) == 3
        assert [tuple(row) for row in conn.execute("SELECT * FROM tasks ORDER BY id")] == tasks
        assert conn.execute("SELECT COUNT(*) FROM task_comments").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_migration_34_can_run_twice(tmp_path: Path):
    with open_db(tmp_path / "old.db") as conn:
        _build_v32_with_work(conn)
        db.migrate(conn)
        # A crash between the statements and the version stamp must not make a rerun fail.
        with db.transaction(conn):
            for statement in db.MIGRATIONS[33]:
                statement(conn) if callable(statement) else conn.execute(statement)
        assert not [name for name in table_names(conn) if name.startswith("work_")]
        assert conn.execute("SELECT COUNT(*) FROM org_legacy_work").fetchone()[0] == 3


def test_migration_34_on_a_new_database_ends_without_work_tables(tmp_path: Path):
    with open_db(tmp_path / "t.db") as conn:
        db.migrate(conn)
        assert db.schema_version(conn) == 34
        assert not [name for name in table_names(conn) if name.startswith("work_")]
        assert "org_legacy_work" in table_names(conn)
