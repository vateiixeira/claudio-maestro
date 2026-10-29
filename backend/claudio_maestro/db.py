"""SQLite connection and schema migrations versioned by `PRAGMA user_version`."""

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

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


# Statements of migrations 27 (PR), 28 (CI) and 29 (pool), copied from the `work` package that
# migration 34 retired. A migration that was published never changes, so a new database still
# climbs from version 0 through them; migration 34 drops what they create.
_PR_SCHEMA = [
    """CREATE TABLE work_prs (
        url TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        origin_attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
        last_attempt_id INTEGER NOT NULL REFERENCES work_attempts(id),
        origin_session_id TEXT NOT NULL,
        last_session_id TEXT NOT NULL,
        workspace TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        polled_at INTEGER,
        closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)),
        head_sha TEXT
    )""",
    """CREATE TABLE work_pr_batches (
        id TEXT PRIMARY KEY,
        pr_url TEXT NOT NULL REFERENCES work_prs(url) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('dispatching','delivered','uncertain','rejected')),
        created_at INTEGER NOT NULL,
        receipt TEXT
    )""",
    """CREATE TABLE work_pr_comments (
        pr_url TEXT NOT NULL REFERENCES work_prs(url) ON DELETE CASCADE,
        comment_id TEXT NOT NULL,
        author TEXT NOT NULL,
        body_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        received_at INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','dispatching','delivered','uncertain')),
        batch_id TEXT REFERENCES work_pr_batches(id),
        PRIMARY KEY(pr_url,comment_id)
    )""",
    """CREATE TABLE work_pr_registrations (
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        url TEXT NOT NULL,
        attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
        state TEXT NOT NULL CHECK(state IN ('pending','registered','blocked')),
        workspace TEXT,
        capture_ref TEXT,
        reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(session_id,url)
    )""",
    """CREATE TABLE work_pr_inbox (
        batch_id TEXT PRIMARY KEY REFERENCES work_pr_batches(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        attempt_id INTEGER NOT NULL UNIQUE REFERENCES work_attempts(id),
        receipt TEXT NOT NULL UNIQUE,
        dossier_ref TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    'CREATE INDEX work_pr_comments_pending ON work_pr_comments(status,pr_url)',
]

_CI_SCHEMA = [
    """CREATE TABLE work_ci_receipts (
        evidence_ref TEXT PRIMARY KEY,
        attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
        session_id TEXT NOT NULL,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        work_revision INTEGER NOT NULL,
        source_revision TEXT,
        dossier_ref TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        target_digest TEXT NOT NULL,
        evidence_digest TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    'CREATE INDEX work_ci_receipts_attempt ON work_ci_receipts(attempt_id)',
]

_POOL_SCHEMA = [
    """CREATE TABLE work_pool_config (
        id INTEGER PRIMARY KEY CHECK(id=1),
        global_limit INTEGER NOT NULL CHECK(global_limit BETWEEN 1 AND 2),
        default_project_limit INTEGER NOT NULL CHECK(default_project_limit BETWEEN 1 AND 2),
        revision INTEGER NOT NULL DEFAULT 1
    )""",
    'INSERT INTO work_pool_config VALUES (1,1,1,1)',
    'ALTER TABLE work_attempt_signals ADD COLUMN dispatch_id TEXT',
    'ALTER TABLE work_attempt_signals ADD COLUMN correlated_result INTEGER NOT NULL DEFAULT 0 CHECK(correlated_result IN (0,1))',
    'ALTER TABLE work_notifications ADD COLUMN dispatch_id TEXT',
    """CREATE TABLE work_project_pool_limits (
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        worker_limit INTEGER NOT NULL CHECK(worker_limit BETWEEN 1 AND 2)
    )""",
    """CREATE TABLE work_project_resources (
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        resource TEXT NOT NULL CHECK(length(resource)<=180),
        PRIMARY KEY(project_id,resource)
    )""",
    """CREATE TABLE work_process_closures (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK(status IN ('closing','closed','uncertain')),
        updated_at INTEGER NOT NULL,
        agentd_child_id TEXT,
        agentd_instance_id TEXT
    )""",
    """CREATE TABLE work_capacity_suspensions (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        reason TEXT NOT NULL CHECK(reason='human_decision_quiescent'),
        suspended_at INTEGER NOT NULL
    )""",
]

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

# Phase 3: collection generations and their compact publication receipts.
MIGRATIONS.append([
    """CREATE TABLE work_collections (
        id TEXT PRIMARY KEY,
        work_item_id INTEGER NOT NULL UNIQUE REFERENCES work_items(id) ON DELETE CASCADE,
        source TEXT NOT NULL,
        source_instance TEXT NOT NULL,
        source_project TEXT NOT NULL,
        cursor TEXT NOT NULL DEFAULT '',
        finalized INTEGER NOT NULL DEFAULT 0,
        total INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE work_collection_pages (
        collection_id TEXT NOT NULL REFERENCES work_collections(id) ON DELETE CASCADE,
        cursor TEXT NOT NULL,
        digest TEXT NOT NULL,
        receipt_ref TEXT NOT NULL,
        PRIMARY KEY (collection_id, cursor)
    )""",
    """CREATE TABLE work_collection_items (
        collection_id TEXT NOT NULL REFERENCES work_collections(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        source_revision TEXT,
        PRIMARY KEY (collection_id, work_item_id)
    )""",
    """CREATE TABLE work_collection_inputs (
        collection_id TEXT NOT NULL REFERENCES work_collections(id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        PRIMARY KEY (collection_id, work_item_id)
    )""",
    """CREATE TABLE work_input_history (
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL,
        dossier_ref TEXT NOT NULL,
        PRIMARY KEY (work_item_id, revision)
    )""",
])

# Phase 4: independent evidence, exact human decisions and durable CTO feed.
MIGRATIONS.append([
    """CREATE TABLE work_attempt_inputs (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        dossier_ref TEXT NOT NULL,
        source_revision TEXT
    )""",
    """CREATE TABLE work_attempt_workspaces (
        attempt_id INTEGER PRIMARY KEY REFERENCES work_attempts(id) ON DELETE CASCADE,
        paths_ref TEXT NOT NULL
    )""",
    """CREATE TABLE work_review_bindings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        author_attempt_id INTEGER NOT NULL UNIQUE REFERENCES work_attempts(id) ON DELETE CASCADE,
        review_attempt_id INTEGER UNIQUE REFERENCES work_attempts(id) ON DELETE SET NULL,
        input_revision INTEGER NOT NULL,
        item_revision INTEGER NOT NULL,
        dossier_ref TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','reviewing','approved','returned','stale','blocked')),
        disposition TEXT,
        reason TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""",
    """CREATE TABLE work_decision_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        attempt_id INTEGER NOT NULL REFERENCES work_attempts(id) ON DELETE CASCADE,
        work_revision INTEGER NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        dossier_ref TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        request_ref TEXT NOT NULL,
        answer_ref TEXT,
        receipt TEXT UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('pending','answered','resumed','expired')),
        resume_attempt_id INTEGER REFERENCES work_attempts(id) ON DELETE SET NULL,
        created_at INTEGER NOT NULL,
        answered_at INTEGER
    )""",
    "CREATE UNIQUE INDEX work_decision_pending ON work_decision_requests(attempt_id) WHERE status IN ('pending','answered')",
    """CREATE TABLE work_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL UNIQUE REFERENCES work_events(id) ON DELETE CASCADE,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        coordinator_session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
        attempt_id INTEGER REFERENCES work_attempts(id) ON DELETE SET NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL CHECK(length(summary)<=500),
        dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('queued','dispatching','sent','uncertain','unsent')),
        created_at INTEGER NOT NULL,
        seen_at INTEGER,
        model_received_at INTEGER
    )""",
    "CREATE INDEX work_notifications_queue ON work_notifications(coordinator_session_id,dispatch_state,id)",
])

MIGRATIONS.append(_PR_SCHEMA)

# Backend-issued evidence for read-only GitHub Actions verification.
MIGRATIONS.append(_CI_SCHEMA)

MIGRATIONS.append(_POOL_SCHEMA)

# The owner of a session is an agent now, not only a legacy specialist.
MIGRATIONS.append(["ALTER TABLE sessions RENAME COLUMN specialist_id TO agent_id"])


_WAKE_SOURCES = "'routine', 'message', 'assignment', 'comment', 'decision', 'manual'"


def carry_agent_sequences(conn: sqlite3.Connection) -> None:
    """Keep the AUTOINCREMENT watermark of the old tables on the new ones, so ids of rows
    deleted before the copy are not reused (runs and notices are referenced from outside)."""
    pairs = (
        ("specialists", "agents"),
        ("specialists", "routines"),
        ("specialist_schedules", "routine_schedules"),
        ("specialist_runs", "runs"),
        ("specialist_notices", "notices"),
        ("specialist_announcements", "announcements"),
    )
    for old, new in pairs:
        row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (old,)).fetchone()
        if row is None:
            continue
        if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (new,)).fetchone():
            conn.execute(
                "UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = ?", (row[0], new)
            )
        else:
            conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (new, row[0]))


_SESSIONS_AGENT_FK_OLD = "agent_id INTEGER REFERENCES specialists(id) ON DELETE SET NULL"
_SESSIONS_AGENT_FK_NEW = "agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL"


def rebind_sessions_agent_fk(conn: sqlite3.Connection) -> None:
    """Point `sessions.agent_id` at `agents` instead of `specialists`, without rebuilding the
    table (21 tables reference `sessions`, several with CASCADE).

    This is the "Making Other Kinds Of Table Schema Changes" procedure of the SQLite docs: the
    table text is edited in `sqlite_schema` and `schema_version` is bumped so every connection
    reparses it. It is safe here because the column and its type stay the same, only the parent
    table of the foreign key changes, and the ids already match (the copy kept them). Runs inside
    the transaction of `migrate`; the caller must have copied `agents` first.
    """
    row = conn.execute("SELECT sql FROM sqlite_schema WHERE type = 'table' AND name = 'sessions'")
    sql = row.fetchone()[0]
    if sql.count(_SESSIONS_AGENT_FK_OLD) != 1:
        raise RuntimeError(
            "Não foi possível migrar a tabela de sessões: a coluna agent_id não tem a forma"
            " esperada. Nada foi alterado."
        )
    # Refuse before touching the schema if some session points at an id the copy lacks.
    orphans = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE agent_id IS NOT NULL"
        " AND agent_id NOT IN (SELECT id FROM agents)"
    ).fetchone()[0]
    if orphans:
        raise sqlite3.IntegrityError(
            f"{orphans} sessão(ões) apontam para um agente que não existe; a migração foi desfeita."
        )
    version = conn.execute("PRAGMA schema_version").fetchone()[0]
    conn.execute("PRAGMA writable_schema = ON")
    try:
        conn.execute(
            "UPDATE sqlite_schema SET sql = replace(sql, ?, ?)"
            " WHERE type = 'table' AND name = 'sessions'",
            (_SESSIONS_AGENT_FK_OLD, _SESSIONS_AGENT_FK_NEW),
        )
        conn.execute(f"PRAGMA schema_version = {version + 1}")
    finally:
        conn.execute("PRAGMA writable_schema = OFF")
    if conn.execute("PRAGMA foreign_key_check(sessions)").fetchall():
        raise sqlite3.IntegrityError("A chave estrangeira de sessions.agent_id ficou inconsistente.")


# Organização de agentes: o agente passa a ser um `AGENT.md` mais estas tabelas. Os dados
# das `specialist_*` são copiados aqui (ids preservados, para `sessions.agent_id`, anúncios e
# avisos continuarem apontando para a mesma coisa); as tabelas antigas ficam até o fim do marco.
MIGRATIONS.append([
    """
    CREATE TABLE agents (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      slug             TEXT NOT NULL UNIQUE,
      name             TEXT NOT NULL,
      project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      reports_to       INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      enabled          INTEGER NOT NULL DEFAULT 1,
      main_session_id  TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      definition_hash  TEXT,
      legacy_json      TEXT,
      created_at       INTEGER NOT NULL,
      updated_at       INTEGER NOT NULL
    )
    """,
    "CREATE INDEX agents_project ON agents(project_id)",
    "CREATE INDEX agents_reports_to ON agents(reports_to)",
    """
    CREATE TABLE routines (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      agent_id     INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      name         TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
      instruction  TEXT NOT NULL CHECK (length(instruction) BETWEEN 1 AND 5000),
      enabled      INTEGER NOT NULL DEFAULT 1,
      created_at   INTEGER NOT NULL,
      updated_at   INTEGER NOT NULL
    )
    """,
    "CREATE INDEX routines_agent ON routines(agent_id)",
    "CREATE INDEX routines_project ON routines(project_id)",
    """
    CREATE TABLE routine_schedules (
      id             INTEGER PRIMARY KEY AUTOINCREMENT,
      routine_id     INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
      days           TEXT NOT NULL,
      time           TEXT NOT NULL,
      last_fired_at  INTEGER
    )
    """,
    "CREATE INDEX routine_schedules_routine ON routine_schedules(routine_id)",
    f"""
    CREATE TABLE runs (
      id             INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_id       INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      session_id     TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      source         TEXT NOT NULL CHECK (source IN ({_WAKE_SOURCES})),
      routine_id     INTEGER REFERENCES routines(id) ON DELETE SET NULL,
      scheduled_for  INTEGER,
      started_at     INTEGER NOT NULL,
      ended_at       INTEGER,
      outcome        TEXT NOT NULL CHECK (
        outcome IN ('starting', 'running', 'waiting', 'concluded', 'closed', 'failed',
                    'skipped', 'missed', 'cancelled')
      ),
      reason         TEXT
    )
    """,
    "CREATE INDEX runs_agent ON runs(agent_id, id)",
    "CREATE INDEX runs_session ON runs(session_id)",
    f"""
    CREATE TABLE wakeups (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      source      TEXT NOT NULL CHECK (source IN ({_WAKE_SOURCES})),
      priority    INTEGER NOT NULL,
      routine_id  INTEGER REFERENCES routines(id) ON DELETE SET NULL,
      payload     TEXT CHECK (payload IS NULL OR length(payload) <= 20000),
      state       TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'taken', 'dropped')),
      run_id      INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      created_at  INTEGER NOT NULL,
      taken_at    INTEGER
    )
    """,
    "CREATE INDEX wakeups_queue ON wakeups(agent_id, state, priority, id)",
    """
    CREATE TABLE registry (
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      key         TEXT NOT NULL,
      status      TEXT NOT NULL,
      link        TEXT,
      note        TEXT,
      created_at  INTEGER NOT NULL,
      updated_at  INTEGER NOT NULL,
      PRIMARY KEY (agent_id, key)
    )
    """,
    """
    CREATE TABLE notices (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      run_id      INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      kind        TEXT NOT NULL CHECK (kind IN ('notice', 'summary', 'alert')),
      text        TEXT NOT NULL,
      created_at  INTEGER NOT NULL,
      read_at     INTEGER
    )
    """,
    "CREATE INDEX notices_read ON notices(read_at)",
    """
    CREATE TABLE announcements (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_id      INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      run_id        INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      session_id    TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      text          TEXT NOT NULL,
      created_at    INTEGER NOT NULL,
      delivered_at  INTEGER
    )
    """,
    "CREATE INDEX announcements_pending ON announcements(agent_id, delivered_at)",
    """
    CREATE TABLE agent_chats (
      session_id  TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX agent_chats_agent ON agent_chats(agent_id)",
    """
    CREATE TABLE agent_prs (
      url         TEXT PRIMARY KEY,
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      session_id  TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      created_at  INTEGER NOT NULL,
      polled_at   INTEGER,
      closed      INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE agent_pr_comments (
      comment_id   TEXT PRIMARY KEY,
      pr_url       TEXT NOT NULL,
      agent_id     INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      author       TEXT NOT NULL,
      body         TEXT NOT NULL,
      path         TEXT,
      line         INTEGER,
      html_url     TEXT NOT NULL,
      created_at   INTEGER NOT NULL,
      received_at  INTEGER NOT NULL,
      status       TEXT NOT NULL DEFAULT 'queued' CHECK (
        status IN ('queued', 'dispatching', 'uncertain', 'delivered', 'dropped')
      ),
      batch_at     INTEGER
    )
    """,
    "CREATE INDEX agent_pr_comments_status_pr ON agent_pr_comments(status, pr_url)",
    # --- Cópia dos dados das `specialist_*` ---
    # `legacy_json` leva o que o `AGENT.md` vai absorver depois (model, effort, denied_tools,
    # extra_project_ids e os padrões que pediam o ok do dono, `always_ask_patterns` e
    # `outward_patterns`, que o `migrate_files` converte em regras `Bash(...)` negadas);
    # `migrate_files` o apaga. Os dois padrões passam por `json_valid` para que um texto
    # malformado vire `[]` em vez de derrubar a migração.
    """
    INSERT INTO agents (id, slug, name, project_id, enabled, main_session_id, legacy_json,
                        created_at, updated_at)
    SELECT id, slug, name, project_id, enabled, main_session_id,
           json_object('model', model, 'effort', effort, 'denied_tools', json(denied_tools),
                       'extra_project_ids', json(extra_project_ids),
                       'always_ask_patterns',
                       CASE WHEN json_valid(always_ask_patterns) THEN json(always_ask_patterns)
                            ELSE json('[]') END,
                       'outward_patterns',
                       CASE WHEN json_valid(outward_patterns) THEN json(outward_patterns)
                            ELSE json('[]') END),
           created_at, updated_at
    FROM specialists
    """,
    # One routine per specialist (same id), holding all its schedules. `run_text` and the name
    # are clamped to the new CHECKs so no row is lost.
    """
    INSERT INTO routines (id, project_id, agent_id, name, instruction, enabled, created_at,
                          updated_at)
    SELECT id, project_id, id,
           CASE WHEN trim(name) = '' THEN 'Rotina' ELSE substr(name, 1, 80) END,
           CASE WHEN trim(run_text) = '' THEN 'Execute a rotina agendada.'
                ELSE substr(run_text, 1, 5000) END,
           1, created_at, updated_at
    FROM specialists
    """,
    """
    INSERT INTO routine_schedules (id, routine_id, days, time, last_fired_at)
    SELECT id, specialist_id, days, time, last_fired_at FROM specialist_schedules
    """,
    # Runs: chat messages (`message = 1`) are not runs any more and are dropped; `queued` becomes
    # `cancelled` (the old queue is not carried over); `schedule` becomes `routine`. Several runs
    # may share a session, so `session_id` is copied as it was.
    """
    INSERT INTO runs (id, agent_id, session_id, source, routine_id, scheduled_for, started_at,
                      ended_at, outcome, reason)
    SELECT r.id, r.specialist_id,
           CASE WHEN r.outcome = 'queued' THEN NULL ELSE r.session_id END,
           CASE r.trigger WHEN 'schedule' THEN 'routine' ELSE r.trigger END,
           CASE WHEN r.trigger = 'schedule' THEN r.specialist_id END,
           r.scheduled_for, r.started_at,
           CASE WHEN r.outcome = 'queued' THEN COALESCE(r.ended_at, r.started_at)
                ELSE r.ended_at END,
           CASE r.outcome WHEN 'queued' THEN 'cancelled' ELSE r.outcome END,
           CASE WHEN r.outcome = 'queued' THEN 'Fila migrada' ELSE r.reason END
    FROM specialist_runs r
    WHERE r.message = 0
    """,
    """
    INSERT INTO registry (agent_id, key, status, link, note, created_at, updated_at)
    SELECT specialist_id, key, status, link, note, created_at, updated_at FROM specialist_items
    """,
    # Notices point at a run now, not at a session: the latest copied run of the notice's session.
    """
    INSERT INTO notices (id, agent_id, run_id, kind, text, created_at, read_at)
    SELECT n.id, n.specialist_id,
           (SELECT r.id FROM specialist_runs r JOIN runs c ON c.id = r.id
            WHERE n.session_id IS NOT NULL AND r.session_id = n.session_id
            ORDER BY r.started_at DESC, r.id DESC LIMIT 1),
           n.kind, n.text, n.created_at, n.read_at
    FROM specialist_notices n
    """,
    """
    INSERT INTO announcements (id, agent_id, run_id, session_id, text, created_at, delivered_at)
    SELECT a.id, a.specialist_id, (SELECT id FROM runs WHERE id = a.run_id), a.session_id, a.text,
           a.created_at, a.delivered_at
    FROM specialist_announcements a
    """,
    "INSERT INTO agent_chats (session_id, agent_id) SELECT session_id, specialist_id FROM specialist_chats",
    """
    INSERT INTO agent_prs (url, agent_id, session_id, created_at, polled_at, closed)
    SELECT url, specialist_id, session_id, created_at, polled_at, closed FROM specialist_prs
    """,
    """
    INSERT INTO agent_pr_comments (comment_id, pr_url, agent_id, author, body, path, line,
                                   html_url, created_at, received_at, status, batch_at)
    SELECT comment_id, pr_url, specialist_id, author, body, path, line, html_url, created_at,
           received_at, status, batch_at
    FROM specialist_pr_comments
    """,
    carry_agent_sequences,
    rebind_sessions_agent_fk,
    # Transitional: `sessions.agent_id` now needs a row in `agents`, but the old specialist
    # service still creates and edits `specialists` until it is removed at the end of the
    # milestone. These triggers mirror it (same id) so its sessions keep working; dropping the
    # `specialists` table drops them.
    """
    CREATE TRIGGER specialists_mirror_insert AFTER INSERT ON specialists
    BEGIN
      INSERT INTO agents (id, slug, name, project_id, enabled, main_session_id, created_at,
                          updated_at)
      VALUES (new.id, new.slug, new.name, new.project_id, new.enabled, new.main_session_id,
              new.created_at, new.updated_at);
    END
    """,
    """
    CREATE TRIGGER specialists_mirror_update
    AFTER UPDATE OF slug, name, project_id, enabled, main_session_id, updated_at ON specialists
    BEGIN
      UPDATE agents SET slug = new.slug, name = new.name, project_id = new.project_id,
                        enabled = new.enabled, main_session_id = new.main_session_id,
                        updated_at = new.updated_at
      WHERE id = new.id;
    END
    """,
    """
    CREATE TRIGGER specialists_mirror_delete AFTER DELETE ON specialists
    BEGIN
      DELETE FROM agents WHERE id = old.id;
    END
    """,
])

# The old agents (`specialists`) were copied into `agents` and friends by migration 31, and the
# service that used them is gone: drop the old tables. Children first, so the implicit DELETE
# that SQLite runs before dropping a parent has nothing left to cascade into. `IF EXISTS` makes
# the step safe to rerun. Dropping `specialists` also drops its mirror triggers; `sessions`
# already points at `agents` (migration 31), so it is untouched.
MIGRATIONS.append([
    f"DROP TABLE IF EXISTS {table}"
    for table in (
        "specialist_pr_comments",
        "specialist_prs",
        "specialist_chats",
        "specialist_announcements",
        "specialist_notices",
        "specialist_items",
        "specialist_runs",
        "specialist_schedules",
        "specialists",
    )
] + [
    # The index of `sessions.agent_id` kept the name it had when the column was `specialist_id`.
    "DROP INDEX IF EXISTS sessions_specialist",
    "CREATE INDEX IF NOT EXISTS sessions_agent ON sessions(agent_id)",
])

def carry_task_sequence(conn: sqlite3.Connection) -> None:
    """Keep the AUTOINCREMENT watermark of `work_items` on `tasks`, so the id of an item deleted
    before the copy is never reused (a dossier on disk may still carry it)."""
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'work_items'").fetchone()
    if row is None:
        return
    if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = 'tasks'").fetchone():
        conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'tasks'", (row[0],))
    else:
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('tasks', ?)", (row[0],))


# Organização de agentes, marco 2: tarefas. Os `work_items` viram `tasks` (mesmo id) e cada
# tentativa antiga vira um comentário `app`. O que a cópia não alcança sem os arquivos em disco
# (coordenadores, decisões pendentes, PRs) vai para `org_legacy_work`, que o `migrate_work` lê e
# esvazia; a migração seguinte apaga as tabelas `work_*` e não toca nessa de passagem.
_TASK_STATUSES = "'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled'"
MIGRATIONS.append([
    f"""
    CREATE TABLE tasks (
      id                  INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id          INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      parent_task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
      title               TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
      description         TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 20000),
      status              TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ({_TASK_STATUSES})),
      priority            TEXT NOT NULL DEFAULT 'normal'
                          CHECK (priority IN ('urgent', 'high', 'normal', 'low')),
      assignee_agent_id   INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      reviewer_agent_id   INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      created_by_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      created_by          TEXT NOT NULL DEFAULT 'human'
                          CHECK (created_by IN ('human', 'agent', 'routine')),
      routine_id          INTEGER REFERENCES routines(id) ON DELETE SET NULL,
      revision            INTEGER NOT NULL DEFAULT 1,
      run_count           INTEGER NOT NULL DEFAULT 0,
      max_runs            INTEGER NOT NULL DEFAULT 20,
      worktree_path       TEXT,
      branch              TEXT,
      blocked_reason      TEXT,
      legacy_json         TEXT,
      created_at          INTEGER NOT NULL,
      updated_at          INTEGER NOT NULL,
      closed_at           INTEGER
    )
    """,
    "CREATE INDEX tasks_project_status ON tasks(project_id, status, id)",
    "CREATE INDEX tasks_assignee ON tasks(assignee_agent_id, status)",
    """
    CREATE TABLE task_comments (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      task_id          INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      author_kind      TEXT NOT NULL CHECK (author_kind IN ('human', 'agent', 'app')),
      author_agent_id  INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      run_id           INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      text             TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 20000),
      created_at       INTEGER NOT NULL
    )
    """,
    "CREATE INDEX task_comments_task ON task_comments(task_id, id)",
    """
    CREATE TABLE task_sessions (
      agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      session_id  TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      cwd         TEXT NOT NULL,
      created_at  INTEGER NOT NULL,
      PRIMARY KEY (agent_id, task_id)
    )
    """,
    """
    CREATE TABLE decisions (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
      agent_id     INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
      run_id       INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      session_id   TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
      question     TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 2000),
      options      TEXT NOT NULL DEFAULT '[]',
      answer       TEXT,
      receipt      TEXT UNIQUE,
      status       TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'answered', 'expired')),
      created_at   INTEGER NOT NULL,
      answered_at  INTEGER
    )
    """,
    "CREATE INDEX decisions_status ON decisions(status, created_at)",
    """
    CREATE TABLE ci_receipts (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
      agent_id    INTEGER REFERENCES agents(id) ON DELETE SET NULL,
      run_id      INTEGER REFERENCES runs(id) ON DELETE SET NULL,
      run_url     TEXT,
      repository  TEXT,
      head_sha    TEXT,
      conclusion  TEXT,
      jobs        TEXT,
      receipt     TEXT UNIQUE,
      created_at  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX ci_receipts_task ON ci_receipts(task_id, id)",
    """
    CREATE TABLE org_legacy_work (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      kind        TEXT NOT NULL CHECK (kind IN ('coordinator', 'decision', 'pr')),
      project_id  INTEGER,
      task_id     INTEGER,
      data        TEXT NOT NULL
    )
    """,
    "ALTER TABLE runs ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN commented INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE runs ADD COLUMN rewoken INTEGER NOT NULL DEFAULT 0",
    "CREATE INDEX runs_task ON runs(task_id)",
    "ALTER TABLE wakeups ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL",
    "ALTER TABLE routines ADD COLUMN create_task INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE agent_prs ADD COLUMN task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL",
    # --- Cópia dos `work_items` (mesmo id) ---
    """
    INSERT INTO tasks (id, project_id, parent_task_id, title, status, priority, blocked_reason,
                       created_by, legacy_json, created_at, updated_at, closed_at)
    SELECT w.id, w.project_id, w.parent_id, w.title,
           CASE w.status WHEN 'backlog' THEN 'todo' WHEN 'ready' THEN 'todo'
                         WHEN 'active' THEN 'in_progress' WHEN 'waiting' THEN 'blocked'
                         WHEN 'review' THEN 'in_review' ELSE w.status END,
           w.priority,
           CASE WHEN w.status = 'waiting' THEN 'Aguardava decisão no sistema anterior.' END,
           'human',
           json_object(
             'dossier_ref', (SELECT dossier_ref FROM work_specs WHERE work_item_id = w.id),
             'source', w.source, 'external_id', w.external_id,
             'coordinator_session_id',
             (SELECT session_id FROM work_coordinators WHERE project_id = w.project_id)),
           w.created_at, w.updated_at,
           CASE WHEN w.status IN ('done', 'cancelled') THEN w.updated_at END
    FROM work_items w
    ORDER BY w.id
    """,
    carry_task_sequence,
    # Each old attempt becomes a note on its task, numbered in order inside the task.
    """
    INSERT INTO task_comments (task_id, author_kind, text, created_at)
    SELECT a.work_item_id, 'app',
           'Tentativa ' || a.n || ' (' ||
           CASE a.role WHEN 'investigator' THEN 'investigador' WHEN 'implementer' THEN 'implementador'
                       ELSE 'revisor' END
           || '): ' ||
           CASE a.state WHEN 'starting' THEN 'iniciando' WHEN 'dispatching' THEN 'enviando'
                        WHEN 'running' THEN 'em andamento' WHEN 'waiting' THEN 'aguardando'
                        WHEN 'uncertain' THEN 'incerta' WHEN 'succeeded' THEN 'concluída'
                        WHEN 'failed' THEN 'falhou' ELSE 'cancelada' END
           || ', ' || COALESCE('sessão ' || a.session_id, 'sem sessão'),
           a.created_at
    FROM (SELECT work_item_id, id, role, state, session_id, created_at,
                 ROW_NUMBER() OVER (PARTITION BY work_item_id ORDER BY id) AS n
          FROM work_attempts) a
    ORDER BY a.work_item_id, a.id
    """,
    # --- Passagem para `migrate_work`, que precisa dos arquivos em disco ---
    """
    INSERT INTO org_legacy_work (kind, project_id, task_id, data)
    SELECT 'coordinator', project_id, NULL,
           json_object('session_id', session_id, 'created_at', created_at)
    FROM work_coordinators ORDER BY project_id
    """,
    """
    INSERT INTO org_legacy_work (kind, project_id, task_id, data)
    SELECT 'decision', w.project_id, d.work_item_id,
           json_object('request_ref', d.request_ref, 'created_at', d.created_at)
    FROM work_decision_requests d JOIN work_items w ON w.id = d.work_item_id
    WHERE d.status = 'pending' ORDER BY d.id
    """,
    """
    INSERT INTO org_legacy_work (kind, project_id, task_id, data)
    SELECT 'pr', project_id, work_item_id,
           json_object('url', url, 'last_session_id', last_session_id, 'created_at', created_at,
                       'polled_at', polled_at, 'closed', closed)
    FROM work_prs ORDER BY created_at, url
    """,
])

# The work items became tasks (migration 33) and the service that used the `work_*` tables is
# gone: drop them. Children first (an attempt points at its item, a notification at an event and
# an attempt, ...), so the implicit DELETE that SQLite runs before dropping a parent has nothing
# left to cascade into. `IF EXISTS` makes the step safe to rerun. Their indexes go with them.
# `org_legacy_work` stays: `migrate_work` runs after the migrations, in the same start, and reads
# it; it empties the table by itself.
LEGACY_WORK_TABLES = (
    "work_notifications",
    "work_events",
    "work_pr_comments",
    "work_pr_inbox",
    "work_pr_batches",
    "work_prs",
    "work_review_bindings",
    "work_decision_requests",
    "work_ci_receipts",
    "work_attempt_inputs",
    "work_attempt_signals",
    "work_attempt_workspaces",
    "work_capacity_suspensions",
    "work_process_closures",
    "work_pr_registrations",
    "work_resource_claims",
    "work_collection_inputs",
    "work_collection_items",
    "work_collection_pages",
    "work_collections",
    "work_dependencies",
    "work_input_history",
    "work_specs",
    "work_attempts",
    "work_items",
    "work_coordinators",
    "work_pool_config",
    "work_project_fences",
    "work_project_modes",
    "work_project_pool_limits",
    "work_project_resources",
)
MIGRATIONS.append([f"DROP TABLE IF EXISTS {table}" for table in LEGACY_WORK_TABLES])

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


BACKUPS_DIRNAME = "backups"
BACKUPS_KEPT = 5


def backup_before_migration(
    path: Path,
    current: int,
    target: int,
    *,
    keep: int = BACKUPS_KEPT,
    now: Callable[[], datetime] | None = None,
) -> Path | None:
    """Copy the database to `backups/` (next to it) before migrating `current` -> `target`.

    Uses SQLite's backup API, which copies a consistent read even with WAL. The
    folder is 0700 and the copy 0600. Keeps only the `keep` newest copies.
    """
    backups_dir = path.parent / BACKUPS_DIRNAME
    backups_dir.mkdir(mode=0o700, exist_ok=True)
    backups_dir.chmod(0o700)  # a folder that already existed may have looser permissions
    stamp = (now or datetime.now)()
    dest = backups_dir / f"antes-migracao-{current}-para-{target}-{stamp:%Y%m%d-%H%M%S}.db"
    try:
        with closing(sqlite3.connect(path)) as src, closing(sqlite3.connect(dest)) as dst:
            src.backup(dst)
        dest.chmod(0o600)
    except BaseException:
        dest.unlink(missing_ok=True)  # a partial copy must not take one of the kept slots
        raise
    # Order by the timestamp at the end of the name: the versions have a varying number of digits.
    copies = sorted(backups_dir.glob("antes-migracao-*.db"), key=_backup_stamp)
    for old in copies[:-keep]:
        old.unlink(missing_ok=True)
    return dest


def _backup_stamp(file: Path) -> tuple[str, str]:
    """Sort key of a backup: the `%Y%m%d-%H%M%S` that ends its name, then the name itself."""
    return file.stem[-15:], file.name


def init_db(path: Path) -> None:
    """Create the data folder if needed and bring the schema up to date.

    An existing database that is behind gets a copy in `backups/` first. The copy
    is made before `PRAGMA journal_mode = WAL`, which already rewrites the header
    of a database that is not in WAL yet.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    conn = connect(path)
    try:
        current = schema_version(conn)
        if existed and current < SCHEMA_VERSION:
            try:
                copy = backup_before_migration(path, current, SCHEMA_VERSION)
            except (OSError, sqlite3.Error) as exc:
                raise RuntimeError(
                    "Não foi possível copiar o banco antes de migrar para "
                    f"{path.parent / BACKUPS_DIRNAME}: {exc}"
                ) from exc
            logger.info("Cópia do banco antes de migrar: %s", copy)
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn)
    finally:
        conn.close()
