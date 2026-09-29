"""SQLite connection and schema migrations versioned by `PRAGMA user_version`."""

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

# Titles the app or the sync set by themselves (history.DEFAULT_APP_TITLE, history.UNTITLED).
_AUTOMATIC_TITLES = ("Nova sessão", "Sessão sem título")
_TITLE_MAX_LENGTH = 80


def _automatic_title(text: str | None) -> str | None:
    """How the app and the sync turn a prompt or summary into a title."""
    if not text or not text.strip():
        return None
    return " ".join(text.split())[:_TITLE_MAX_LENGTH].rstrip()


def mark_custom_titles(conn: sqlite3.Connection) -> None:
    """Migration 3: keep names given in the app before `title_custom` existed.

    Heuristic: a title is automatic when it is one of the default titles or
    equals the first prompt or the summary cut like the app and the sync do.
    Rows the sync already filled (first prompt or summary known) whose title
    matches neither were renamed by someone: they get `title_custom = 1`, so
    the sync never replaces them. Rows without first prompt and summary cannot
    be told apart and stay automatic. A title set by `/rename` in the CLI also
    ends up marked; the only effect is that later CLI renames stop replacing it.
    """
    rows = conn.execute(
        "SELECT session_id, title, first_prompt, summary FROM sessions WHERE title_custom = 0"
    ).fetchall()
    for session_id, title, first_prompt, summary in rows:
        if title in _AUTOMATIC_TITLES or (first_prompt is None and summary is None):
            continue
        if title in (_automatic_title(first_prompt), _automatic_title(summary)):
            continue
        conn.execute("UPDATE sessions SET title_custom = 1 WHERE session_id = ?", (session_id,))


# Each migration is a list of SQL statements or functions of the connection.
# Migration N (1-based) brings the schema to `user_version = N`. Never edit a
# migration that has shipped; append a new one instead.
MIGRATIONS: list[list[str | Callable[[sqlite3.Connection], None]]] = [
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
    [
        # Marco 3: history index. `title_custom` marks a title set by the user in
        # the app (sync never replaces it); `rename_pending` a title still to be
        # written to the SDK history; `file_modified_at` the history file mtime.
        "ALTER TABLE sessions ADD COLUMN summary TEXT",
        "ALTER TABLE sessions ADD COLUMN first_prompt TEXT",
        "ALTER TABLE sessions ADD COLUMN title_custom INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN rename_pending INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN file_modified_at INTEGER",
    ],
    [
        # Marco 6: the history file mtime as the app itself last left it, so a
        # restart does not mistake the app's own writes for external activity.
        "ALTER TABLE sessions ADD COLUMN app_modified_at INTEGER",
        mark_custom_titles,
    ],
    [
        # Marco 7: when the session was finished by the user (None when open or
        # finished by inactivity). Feeds "Finalizadas hoje" in the dashboard.
        "ALTER TABLE sessions ADD COLUMN finished_at INTEGER",
    ],
    [
        # Marco 9: plan the conversation executes. `plan_link` is "auto" (last plan
        # read or edited), "manual" (chosen by the user) or "off" (never auto-link).
        "ALTER TABLE sessions ADD COLUMN plan_path TEXT",
        "ALTER TABLE sessions ADD COLUMN plan_link TEXT",
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
                if callable(statement):
                    statement(conn)
                else:
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
