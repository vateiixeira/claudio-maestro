"""Database access of the digest agent: session digests and the pass log."""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

MAX_RUNS = 50

_DIGEST_COLUMNS = (
    "session_id, cursor, read_at, short, phases, plan_done, plan_ref, error, error_at"
)
_RUN_COLUMNS = (
    "id, started_at, finished_at, trigger, read_count, skipped_count, errors, stopped"
)


@dataclass
class Digest:
    session_id: str
    # uuid of the last transcript entry already read; None before the first reading.
    cursor: str | None = None
    read_at: int | None = None
    short: str | None = None
    phases: list[dict[str, Any]] = field(default_factory=list)
    plan_done: bool = False
    # Plan path `plan_done` refers to: the seal only goes away when the linked plan changes.
    plan_ref: str | None = None
    error: str | None = None
    error_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """What the frontend receives (the cursor and plan_ref are internal)."""
        return {
            "session_id": self.session_id, "read_at": self.read_at, "short": self.short,
            "phases": self.phases, "plan_done": self.plan_done, "error": self.error,
            "error_at": self.error_at,
        }


def _digest(row: sqlite3.Row) -> Digest:
    try:
        phases = json.loads(row["phases"])
    except ValueError:
        phases = []
    return Digest(
        session_id=row["session_id"], cursor=row["cursor"], read_at=row["read_at"],
        short=row["short"], phases=phases if isinstance(phases, list) else [],
        plan_done=bool(row["plan_done"]), plan_ref=row["plan_ref"], error=row["error"],
        error_at=row["error_at"],
    )


def get_digest(conn: sqlite3.Connection, session_id: str) -> Digest | None:
    row = conn.execute(
        f"SELECT {_DIGEST_COLUMNS} FROM session_digests WHERE session_id = ?", (session_id,)
    ).fetchone()
    return None if row is None else _digest(row)


def save_digest(conn: sqlite3.Connection, digest: Digest) -> None:
    """Write every field. Raises sqlite3.IntegrityError when the session is gone."""
    conn.execute(
        f"INSERT INTO session_digests ({_DIGEST_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET cursor = excluded.cursor,"
        " read_at = excluded.read_at, short = excluded.short, phases = excluded.phases,"
        " plan_done = excluded.plan_done, plan_ref = excluded.plan_ref,"
        " error = excluded.error, error_at = excluded.error_at",
        (
            digest.session_id, digest.cursor, digest.read_at, digest.short,
            json.dumps(digest.phases, ensure_ascii=False), int(digest.plan_done),
            digest.plan_ref, digest.error, digest.error_at,
        ),
    )


def save_error(conn: sqlite3.Connection, session_id: str, message: str, at: int) -> Digest | None:
    """Record a failed reading, keeping the last summary. None when the session is gone."""
    try:
        conn.execute(
            "INSERT INTO session_digests (session_id, error, error_at) VALUES (?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET error = excluded.error,"
            " error_at = excluded.error_at",
            (session_id, message, at),
        )
    except sqlite3.IntegrityError:
        return None
    return get_digest(conn, session_id)


def briefs(conn: sqlite3.Connection) -> dict[str, tuple[str | None, bool]]:
    """Short sentence and plan seal of every digested session."""
    return {
        row["session_id"]: (row["short"], bool(row["plan_done"]))
        for row in conn.execute("SELECT session_id, short, plan_done FROM session_digests")
    }


def _run(row: sqlite3.Row) -> dict[str, Any]:
    run = {key: row[key] for key in row.keys()}
    try:
        errors = json.loads(run["errors"])
    except ValueError:
        errors = []
    run["errors"] = errors if isinstance(errors, list) else []
    return run


def start_run(conn: sqlite3.Connection, trigger: str, at: int) -> int:
    cursor = conn.execute(
        "INSERT INTO digest_runs (started_at, trigger) VALUES (?, ?)", (at, trigger)
    )
    return int(cursor.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    at: int,
    read_count: int,
    skipped_count: int,
    errors: list[dict[str, Any]],
    stopped: str | None,
) -> dict[str, Any]:
    conn.execute(
        "UPDATE digest_runs SET finished_at = ?, read_count = ?, skipped_count = ?,"
        " errors = ?, stopped = ? WHERE id = ?",
        (at, read_count, skipped_count, json.dumps(errors, ensure_ascii=False), stopped, run_id),
    )
    conn.execute(
        "DELETE FROM digest_runs WHERE id NOT IN"
        " (SELECT id FROM digest_runs ORDER BY id DESC LIMIT ?)",
        (MAX_RUNS,),
    )
    row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM digest_runs WHERE id = ?", (run_id,)).fetchone()
    return _run(row)


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _run(row)
        for row in conn.execute(f"SELECT {_RUN_COLUMNS} FROM digest_runs ORDER BY id DESC")
    ]
