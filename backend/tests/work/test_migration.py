"""The work schema is additive; existing conversation records are unchanged."""
from contextlib import closing

from claudio_maestro import db


def test_work_migration_preserves_legacy_data(tmp_path):
    with closing(db.connect(tmp_path / 'upgrade.db')) as conn:
        before = next(i for i, statements in enumerate(db.MIGRATIONS)
                      if any('CREATE TABLE work_items' in str(s) for s in statements))
        for statements in db.MIGRATIONS[:before]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute(f'PRAGMA user_version = {before}')
        conn.execute("INSERT INTO projects VALUES (1, 'p', '/p', '#fff', 0, 0)")
        conn.execute("INSERT INTO specialists (id, slug, name, project_id, created_at, updated_at) VALUES (1, 'old', 'Old', 1, 0, 0)")
        conn.execute("INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at, specialist_id) VALUES ('s', 1, '/p', 't', 0, 0, 1)")
        conn.execute("INSERT INTO specialist_runs (id, specialist_id, session_id, trigger, started_at, outcome) VALUES (7, 1, 's', 'manual', 10, 'running')")
        old_tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        snapshot = {table: [tuple(row) for row in conn.execute(f'SELECT * FROM {table}')] for table in old_tables}
        db.migrate(conn)
        for table in old_tables:
            assert [tuple(row) for row in conn.execute(f'SELECT * FROM {table}')] == snapshot[table]
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'work_items', 'work_attempts', 'work_events', 'work_dependencies', 'work_resource_claims', 'work_coordinators'} <= tables
        db.migrate(conn)
        assert conn.execute('SELECT COUNT(*) FROM work_items').fetchone()[0] == 0


def test_failed_work_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    with closing(db.connect(tmp_path / 'failed.db')) as conn:
        previous = len(db.MIGRATIONS) - 1
        for statements in db.MIGRATIONS[:previous]:
            for statement in statements:
                statement(conn) if callable(statement) else conn.execute(statement)
        conn.execute(f'PRAGMA user_version = {previous}')
        conn.execute("INSERT INTO projects VALUES (1, 'kept', '/kept', '#fff', 0, 0)")
        monkeypatch.setattr(db, 'MIGRATIONS', [*db.MIGRATIONS[:-1], [*db.MIGRATIONS[-1], 'NOT VALID SQL']])
        with pytest.raises(sqlite3.OperationalError):
            db.migrate(conn)
        assert db.schema_version(conn) == previous
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='work_items'").fetchone() is None
        assert conn.execute('SELECT name FROM projects').fetchone()[0] == 'kept'
