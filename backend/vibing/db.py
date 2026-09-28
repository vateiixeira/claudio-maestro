"""SQLite connection and schema migrations versioned by `PRAGMA user_version`."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Each migration is a list of statements. Migration N (1-based) brings the
# schema to `user_version = N`. Never edit a migration that has shipped;
# append a new one instead (e.g. `ALTER TABLE sessions ADD COLUMN group_id ...`).
MIGRATIONS: list[list[str]] = [
    [
        """
        CREATE TABLE projects (
          id          INTEGER PRIMARY KEY,
          name        TEXT NOT NULL,
          path        TEXT NOT NULL UNIQUE,
          color       TEXT NOT NULL,
          position    INTEGER NOT NULL,
          created_at  INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE sessions (
          session_id       TEXT PRIMARY KEY,
          project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          cwd              TEXT NOT NULL,
          title            TEXT NOT NULL,
          created_at       INTEGER NOT NULL,
          last_activity_at INTEGER NOT NULL,
          last_seen_at     INTEGER,
          finished         INTEGER NOT NULL DEFAULT 0,
          model            TEXT,
          effort           TEXT,
          permission_mode  TEXT
        )
        """,
        "CREATE INDEX sessions_project_id ON sessions(project_id)",
        """
        CREATE TABLE app_state (
          key   TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """,
    ],
]

SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection in autocommit mode with foreign keys on.

    Use `transaction(conn)` to group writes. `check_same_thread=False` because
    FastAPI may run a dependency and its endpoint on different threads; each
    connection is still used by one request at a time.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block inside BEGIN IMMEDIATE ... COMMIT, rolling back on error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Safe to call on every start."""
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Banco na versão {current}, mais nova que a suportada ({SCHEMA_VERSION})."
        )
    while current < SCHEMA_VERSION:
        with transaction(conn):
            # Re-read under the write lock in case another process migrated.
            current = schema_version(conn)
            if current >= SCHEMA_VERSION:
                break
            for statement in MIGRATIONS[current]:
                conn.execute(statement)
            current += 1
            conn.execute(f"PRAGMA user_version = {current}")


def init_db(path: Path) -> None:
    """Create the data folder if needed and bring the schema up to date."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
    finally:
        conn.close()
