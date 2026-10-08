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
    [
        # Marco 8: groups of related sessions of a project. Only the app knows them;
        # removing a group leaves its sessions loose (ON DELETE SET NULL).
        """
        CREATE TABLE session_groups (
          id          INTEGER PRIMARY KEY,
          project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name        TEXT NOT NULL,
          created_at  INTEGER NOT NULL
        )
        """,
        "CREATE INDEX session_groups_project_id ON session_groups(project_id)",
        "ALTER TABLE sessions ADD COLUMN group_id INTEGER"
        " REFERENCES session_groups(id) ON DELETE SET NULL",
        "CREATE INDEX sessions_group_id ON sessions(group_id)",
    ],
    [
        # Ajustes de sessões: folder whose history holds the transcript when it is not
        # the cwd (sessions moved into a worktree), the worktree the session is in now
        # and the newest branch of the transcript.
        "ALTER TABLE sessions ADD COLUMN history_dir TEXT",
        "ALTER TABLE sessions ADD COLUMN worktree_name TEXT",
        "ALTER TABLE sessions ADD COLUMN worktree_path TEXT",
        "ALTER TABLE sessions ADD COLUMN git_branch TEXT",
    ],
    [
        # Marco 10: summary of each conversation kept by the digest agent, and the
        # log of its passes (only the newest MAX_RUNS are kept).
        """
        CREATE TABLE session_digests (
          session_id  TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
          cursor      TEXT,
          read_at     INTEGER,
          short       TEXT,
          phases      TEXT NOT NULL DEFAULT '[]',
          plan_done   INTEGER NOT NULL DEFAULT 0,
          plan_ref    TEXT,
          error       TEXT,
          error_at    INTEGER
        )
        """,
        """
        CREATE TABLE digest_runs (
          id             INTEGER PRIMARY KEY,
          started_at     INTEGER NOT NULL,
          finished_at    INTEGER,
          trigger        TEXT NOT NULL,
          read_count     INTEGER NOT NULL DEFAULT 0,
          skipped_count  INTEGER NOT NULL DEFAULT 0,
          errors         TEXT NOT NULL DEFAULT '[]',
          stopped        TEXT
        )
        """,
    ],
    [
        # Sessions that survive backend restarts: a turn was running when the app
        # last stopped (kept live; read at startup to show "Interrompida").
        "ALTER TABLE sessions ADD COLUMN turn_open INTEGER NOT NULL DEFAULT 0",
    ],
    [
        # Marcações de sessão: what the user plans to do with the session ("on_hold",
        # "blocked", "review", "discarded"), the note of a blocked one, when one on hold wakes up,
        # and the priority pin.
        "ALTER TABLE sessions ADD COLUMN mark TEXT",
        "ALTER TABLE sessions ADD COLUMN mark_note TEXT",
        "ALTER TABLE sessions ADD COLUMN mark_until INTEGER",
        "ALTER TABLE sessions ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",
    ],
    [
        # When the backend let go of the session's process (shutdown with the agentd
        # keeping it): the next reattach judges writes by other processes from then on.
        "ALTER TABLE sessions ADD COLUMN detached_at REAL",
    ],
    [
        # Verificação de fechamento: whether the session can be closed, what the user
        # still has to do and what was not delivered, kept by the digest agent.
        """
        CREATE TABLE session_closure (
          session_id    TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
          verdict       TEXT,
          user_actions  TEXT NOT NULL DEFAULT '[]',
          missing       TEXT NOT NULL DEFAULT '[]',
          evidence      TEXT,
          resolved      TEXT NOT NULL DEFAULT '[]',
          fingerprint   TEXT,
          checked_at    INTEGER,
          error         TEXT,
          error_at      INTEGER
        )
        """,
    ],
    [
        # Entregas: one record per "Finalizar" click and local day, with the digest
        # agent's title and bullets. Copies of the title and project name keep the
        # record when the session or the project goes away.
        """
        CREATE TABLE deliveries (
          id             INTEGER PRIMARY KEY,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          project_id     INTEGER REFERENCES projects(id) ON DELETE SET NULL,
          project_name   TEXT NOT NULL,
          title          TEXT NOT NULL,
          finished_at    INTEGER NOT NULL,
          day            TEXT NOT NULL,
          from_cursor    TEXT,
          to_cursor      TEXT,
          status         TEXT NOT NULL,
          summary_title  TEXT,
          bullets        TEXT NOT NULL DEFAULT '[]',
          error          TEXT,
          updated_at     INTEGER NOT NULL
        )
        """,
        "CREATE INDEX deliveries_day ON deliveries(day)",
        "CREATE INDEX deliveries_session ON deliveries(session_id)",
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
