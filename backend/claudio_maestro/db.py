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


def migrate_specialist_queue(conn: sqlite3.Connection) -> None:
    """Extend run states without losing runs, references or the AUTOINCREMENT watermark."""
    sequence = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'specialist_runs'"
    ).fetchone()
    conn.execute(
        """
        CREATE TABLE specialist_runs_queue (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          trigger        TEXT NOT NULL CHECK (trigger IN ('schedule', 'manual', 'comment')),
          scheduled_for  INTEGER,
          started_at     INTEGER NOT NULL,
          ended_at       INTEGER,
          outcome        TEXT NOT NULL CHECK (
            outcome IN ('running', 'concluded', 'closed', 'waiting', 'failed', 'skipped',
                        'missed', 'queued', 'starting', 'cancelled')
          ),
          reason         TEXT
        )
        """
    )
    references = conn.execute(
        "SELECT id, run_id FROM specialist_announcements WHERE run_id IS NOT NULL"
    ).fetchall()
    conn.execute("INSERT INTO specialist_runs_queue SELECT * FROM specialist_runs")
    conn.execute("DROP TABLE specialist_runs")
    conn.execute("ALTER TABLE specialist_runs_queue RENAME TO specialist_runs")
    # DROP invokes ON DELETE SET NULL on announcement links. Restore them in the
    # same transaction, before any other connection can observe the new schema.
    conn.executemany(
        "UPDATE specialist_announcements SET run_id = ? WHERE id = ?",
        [(row["run_id"], row["id"]) for row in references],
    )
    conn.execute(
        "CREATE INDEX specialist_runs_specialist_started ON specialist_runs(specialist_id, started_at)"
    )
    conn.execute("CREATE INDEX specialist_runs_session ON specialist_runs(session_id)")
    conn.execute(
        "CREATE INDEX specialist_runs_pending ON specialist_runs(outcome, specialist_id, id)"
    )
    if sequence is not None:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'specialist_runs'")
        conn.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('specialist_runs', ?)",
            (sequence[0],),
        )


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
    [
        # Etiquetas: catálogo global (slug + cor hex) e a ligação N:M com as conversas.
        # Apagar a etiqueta ou a conversa remove só a ligação. O id nunca é reaproveitado
        # (AUTOINCREMENT): um id antigo não pode voltar como outra etiqueta.
        """
        CREATE TABLE labels (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          slug        TEXT NOT NULL UNIQUE,
          color       TEXT NOT NULL,
          created_at  INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE session_labels (
          session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
          label_id    INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
          PRIMARY KEY (session_id, label_id)
        )
        """,
        "CREATE INDEX session_labels_label_id ON session_labels(label_id)",
    ],
    [
        # Remote Control por sessão: whether the user wants it on (it comes back by itself
        # after any restart), the id of its bridge (so a new process of the same
        # conversation keeps the same entry in the Claude app) and the version of the
        # code that spawned the session's process (what its arguments contain).
        "ALTER TABLE sessions ADD COLUMN remote_control INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN remote_control_bridge TEXT",
        "ALTER TABLE sessions ADD COLUMN spawn_version INTEGER NOT NULL DEFAULT 0",
    ],
    [
        # Agentes (specialists): a named routine bound to a project, with its schedules,
        # run history, memory items and notices. Lists (extra projects, patterns, MCP
        # servers) are JSON text. Removing the project or the agent removes everything
        # that hangs from it; removing a session only unlinks it (the history stays).
        """
        CREATE TABLE specialists (
          id                   INTEGER PRIMARY KEY AUTOINCREMENT,
          slug                 TEXT NOT NULL UNIQUE,
          name                 TEXT NOT NULL,
          project_id           INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          extra_project_ids    TEXT NOT NULL DEFAULT '[]',
          autonomy             TEXT NOT NULL DEFAULT 'ask' CHECK (autonomy IN ('ask', 'full')),
          outward_patterns     TEXT NOT NULL DEFAULT '[]',
          always_ask_patterns  TEXT NOT NULL DEFAULT '[]',
          close_by_check       INTEGER NOT NULL DEFAULT 1,
          model                TEXT,
          effort               TEXT,
          run_text             TEXT NOT NULL DEFAULT 'Execute a rotina agendada.',
          enabled              INTEGER NOT NULL DEFAULT 1,
          last_mcp             TEXT NOT NULL DEFAULT '[]',
          created_at           INTEGER NOT NULL,
          updated_at           INTEGER NOT NULL
        )
        """,
        # Weekdays are ISO digits (1 = Monday ... 7 = Sunday); `last_fired_at` is the
        # last slot already handled, so a restart never fires the same slot twice.
        """
        CREATE TABLE specialist_schedules (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          days           TEXT NOT NULL,
          time           TEXT NOT NULL,
          last_fired_at  INTEGER
        )
        """,
        "CREATE INDEX specialist_schedules_specialist ON specialist_schedules(specialist_id)",
        """
        CREATE TABLE specialist_runs (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          trigger        TEXT NOT NULL CHECK (trigger IN ('schedule', 'manual')),
          scheduled_for  INTEGER,
          started_at     INTEGER NOT NULL,
          ended_at       INTEGER,
          outcome        TEXT NOT NULL CHECK (
            outcome IN ('running', 'concluded', 'closed', 'waiting', 'failed', 'skipped', 'missed')
          ),
          reason         TEXT
        )
        """,
        "CREATE INDEX specialist_runs_specialist_started ON specialist_runs(specialist_id, started_at)",
        "CREATE INDEX specialist_runs_session ON specialist_runs(session_id)",
        # What the agent already looked at, by its own key (a ticket, a PR, a file).
        """
        CREATE TABLE specialist_items (
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          key            TEXT NOT NULL,
          status         TEXT NOT NULL,
          link           TEXT,
          note           TEXT,
          created_at     INTEGER NOT NULL,
          updated_at     INTEGER NOT NULL,
          PRIMARY KEY (specialist_id, key)
        )
        """,
        """
        CREATE TABLE specialist_notices (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          kind           TEXT NOT NULL CHECK (kind IN ('notice', 'summary', 'alert')),
          text           TEXT NOT NULL,
          created_at     INTEGER NOT NULL,
          read_at        INTEGER
        )
        """,
        "CREATE INDEX specialist_notices_read ON specialist_notices(read_at)",
        "ALTER TABLE sessions ADD COLUMN specialist_id INTEGER REFERENCES specialists(id) ON DELETE SET NULL",
        "CREATE INDEX sessions_specialist ON sessions(specialist_id)",
    ],
    # Tools an agent can never use (names in the CLI's permission rule form), JSON text.
    ["ALTER TABLE specialists ADD COLUMN denied_tools TEXT NOT NULL DEFAULT '[]'"],
    [
        # Conversa principal de cada agente, anúncios dos agentes e fila de comentários de PR.
        # `specialist_runs` is rebuilt only to widen the CHECK on `trigger` ('comment'): nothing
        # references it yet, so dropping it is safe with foreign keys on, and the rows and the
        # two indexes are carried over.
        "ALTER TABLE specialists ADD COLUMN main_session_id TEXT"
        " REFERENCES sessions(session_id) ON DELETE SET NULL",
        """
        CREATE TABLE specialist_runs_new (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          trigger        TEXT NOT NULL CHECK (trigger IN ('schedule', 'manual', 'comment')),
          scheduled_for  INTEGER,
          started_at     INTEGER NOT NULL,
          ended_at       INTEGER,
          outcome        TEXT NOT NULL CHECK (
            outcome IN ('running', 'concluded', 'closed', 'waiting', 'failed', 'skipped', 'missed')
          ),
          reason         TEXT
        )
        """,
        "INSERT INTO specialist_runs_new (id, specialist_id, session_id, trigger, scheduled_for,"
        " started_at, ended_at, outcome, reason) SELECT id, specialist_id, session_id, trigger,"
        " scheduled_for, started_at, ended_at, outcome, reason FROM specialist_runs",
        "DROP TABLE specialist_runs",
        "ALTER TABLE specialist_runs_new RENAME TO specialist_runs",
        "CREATE INDEX specialist_runs_specialist_started ON specialist_runs(specialist_id, started_at)",
        "CREATE INDEX specialist_runs_session ON specialist_runs(session_id)",
        # What an agent announced to its main conversation; `delivered_at` is set once the
        # announcement was handed to that conversation.
        """
        CREATE TABLE specialist_announcements (
          id             INTEGER PRIMARY KEY AUTOINCREMENT,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          run_id         INTEGER REFERENCES specialist_runs(id) ON DELETE SET NULL,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          text           TEXT NOT NULL,
          created_at     INTEGER NOT NULL,
          delivered_at   INTEGER
        )
        """,
        "CREATE INDEX specialist_announcements_pending ON specialist_announcements(specialist_id, delivered_at)",
        # PRs an agent opened (url without trailing slash) and the comments found on them.
        """
        CREATE TABLE specialist_prs (
          url            TEXT PRIMARY KEY,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
          created_at     INTEGER NOT NULL,
          polled_at      INTEGER,
          closed         INTEGER NOT NULL DEFAULT 0
        )
        """,
        # `comment_id` is `issue:<id>`, `review:<id>` or `line:<id>`; `created_at` is the
        # GitHub time, `received_at` when we saw it, `batch_at` when it went out in a turn.
        """
        CREATE TABLE specialist_pr_comments (
          comment_id     TEXT PRIMARY KEY,
          pr_url         TEXT NOT NULL,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          author         TEXT NOT NULL,
          body           TEXT NOT NULL,
          path           TEXT,
          line           INTEGER,
          html_url       TEXT NOT NULL,
          created_at     INTEGER NOT NULL,
          received_at    INTEGER NOT NULL,
          status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'delivered', 'dropped')),
          batch_at       INTEGER
        )
        """,
        "CREATE INDEX specialist_pr_comments_status_pr ON specialist_pr_comments(status, pr_url)",
    ],
    # A durable reservation prevents replay after an interrupted comment send.
    [
        """
        CREATE TABLE specialist_pr_comments_new (
          comment_id     TEXT PRIMARY KEY,
          pr_url         TEXT NOT NULL,
          specialist_id  INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE,
          author         TEXT NOT NULL,
          body           TEXT NOT NULL,
          path           TEXT,
          line           INTEGER,
          html_url       TEXT NOT NULL,
          created_at     INTEGER NOT NULL,
          received_at    INTEGER NOT NULL,
          status         TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'dispatching', 'uncertain', 'delivered', 'dropped')),
          batch_at       INTEGER
        )

        """,
        "INSERT INTO specialist_pr_comments_new SELECT * FROM specialist_pr_comments",
        "DROP TABLE specialist_pr_comments",
        "ALTER TABLE specialist_pr_comments_new RENAME TO specialist_pr_comments",
        "CREATE INDEX specialist_pr_comments_status_pr ON specialist_pr_comments(status, pr_url)",
    ],
    [
        "ALTER TABLE specialists ADD COLUMN queue_paused INTEGER NOT NULL DEFAULT 0",
        migrate_specialist_queue,
    ],
    [
        "ALTER TABLE specialist_runs ADD COLUMN message INTEGER NOT NULL DEFAULT 0",
        """CREATE TABLE specialist_chats (
            session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
            specialist_id INTEGER NOT NULL REFERENCES specialists(id) ON DELETE CASCADE
        )""",
        "CREATE INDEX specialist_chats_agent ON specialist_chats(specialist_id)",
    ],
    [
        """CREATE TABLE work_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            parent_id INTEGER REFERENCES work_items(id) ON DELETE SET NULL,
            source TEXT NOT NULL,
            source_instance TEXT NOT NULL,
            source_project TEXT NOT NULL,
            external_id TEXT NOT NULL,
            source_revision TEXT,
            title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
            priority TEXT NOT NULL CHECK (priority IN ('urgent', 'high', 'normal', 'low')),
            status TEXT NOT NULL CHECK (status IN ('backlog', 'ready', 'active', 'waiting', 'blocked', 'review', 'done', 'cancelled')),
            phase TEXT NOT NULL CHECK (phase IN ('investigation', 'implementation', 'testing', 'review')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE (project_id, source, source_instance, source_project, external_id)
        )""",
        "CREATE INDEX work_items_project_status ON work_items(project_id, status, id)",
        """CREATE TABLE work_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
            session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
            role TEXT NOT NULL CHECK (role IN ('investigator', 'implementer', 'reviewer')),
            state TEXT NOT NULL CHECK (state IN ('starting', 'dispatching', 'running', 'waiting', 'uncertain', 'succeeded', 'failed', 'cancelled')),
            work_revision INTEGER NOT NULL,
            result_kind TEXT CHECK (result_kind IN ('investigation', 'implementation', 'review', 'decision')),
            result_ref TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            ended_at INTEGER
        )""",
        """CREATE UNIQUE INDEX work_attempts_one_active ON work_attempts(work_item_id)
            WHERE state IN ('starting', 'dispatching', 'running', 'waiting', 'uncertain')""",
        "CREATE UNIQUE INDEX work_attempts_session ON work_attempts(session_id)",
        "CREATE INDEX work_attempts_item ON work_attempts(work_item_id, id)",
        """CREATE TABLE work_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
            attempt_id INTEGER REFERENCES work_attempts(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            actor TEXT NOT NULL,
            revision INTEGER NOT NULL,
            data TEXT NOT NULL CHECK (length(data) <= 4000),
            created_at INTEGER NOT NULL,
            delivered_at INTEGER
        )""",
        "CREATE INDEX work_events_pending ON work_events(delivered_at, id)",
        "CREATE INDEX work_events_item ON work_events(work_item_id, id)",
        """CREATE TABLE work_resource_claims (
            resource TEXT PRIMARY KEY,
            attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL
        )""",
        "CREATE INDEX work_resource_claims_attempt ON work_resource_claims(attempt_id)",
        """CREATE TABLE work_dependencies (
            work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
            depends_on_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (work_item_id, depends_on_id),
            CHECK (work_item_id != depends_on_id)
        )""",
        """CREATE TABLE work_coordinators (
            project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL
        )""",
    ],
]

MIGRATIONS.append([
    """CREATE TABLE work_project_modes (
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
        paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
        updated_at INTEGER NOT NULL
    )""",
    """CREATE TABLE work_specs (
        work_item_id INTEGER PRIMARY KEY REFERENCES work_items(id) ON DELETE CASCADE,
        dossier_ref TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('investigator', 'implementer', 'reviewer'))
    )""",
    """CREATE TABLE work_attempt_signals (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        result_seen INTEGER NOT NULL DEFAULT 0,
        quiescent INTEGER NOT NULL DEFAULT 0,
        error_seen INTEGER NOT NULL DEFAULT 0,
        proven_unsent INTEGER NOT NULL DEFAULT 0,
        terminal_kind TEXT NOT NULL DEFAULT 'unknown',
        limit_reached INTEGER NOT NULL DEFAULT 0,
        started_at INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
    )""",
])

MIGRATIONS.append([
    """CREATE TABLE work_project_fences (
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        fence_id TEXT NOT NULL UNIQUE,
        reason TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
])

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
