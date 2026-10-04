"""Database access of the closure check: one row per session in `session_closure`."""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

VERDICTS: tuple[str, ...] = ("can_close", "user_action", "incomplete", "in_progress")

_COLUMNS = (
    "session_id, verdict, user_actions, missing, evidence, resolved, fingerprint,"
    " checked_at, error, error_at"
)


@dataclass
class Closure:
    session_id: str
    verdict: str | None = None
    user_actions: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    evidence: str | None = None
    # Items the user marked as done ("Já fiz"); the agent is told not to bring them back.
    resolved: list[str] = field(default_factory=list)
    # What the last check read; equal means no new call.
    fingerprint: str | None = None
    checked_at: int | None = None
    error: str | None = None
    error_at: int | None = None

    def is_stale(self, last_activity_at: int | None) -> bool:
        """Never checked, or the conversation moved after the check."""
        if self.checked_at is None:
            return True
        return last_activity_at is not None and last_activity_at > self.checked_at

    def to_dict(self, last_activity_at: int | None = None) -> dict[str, Any]:
        """What the frontend receives; a stale check shows no verdict."""
        stale = self.is_stale(last_activity_at)
        return {
            "session_id": self.session_id,
            "verdict": None if stale else self.verdict,
            "user_actions": [] if stale else list(self.user_actions),
            "missing": [] if stale else list(self.missing),
            "evidence": None if stale else self.evidence,
            "checked_at": self.checked_at,
            "error": self.error,
            "error_at": self.error_at,
        }


def _list(raw: Any) -> list[str]:
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _closure(row: sqlite3.Row) -> Closure:
    return Closure(
        session_id=row["session_id"],
        verdict=row["verdict"] if row["verdict"] in VERDICTS else None,
        user_actions=_list(row["user_actions"]), missing=_list(row["missing"]),
        evidence=row["evidence"], resolved=_list(row["resolved"]),
        fingerprint=row["fingerprint"], checked_at=row["checked_at"],
        error=row["error"], error_at=row["error_at"],
    )


def get_closure(conn: sqlite3.Connection, session_id: str) -> Closure | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM session_closure WHERE session_id = ?", (session_id,)
    ).fetchone()
    return None if row is None else _closure(row)


def save_closure(conn: sqlite3.Connection, closure: Closure) -> None:
    """Write every field. Raises sqlite3.IntegrityError when the session is gone."""
    conn.execute(
        f"INSERT INTO session_closure ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(session_id) DO UPDATE SET verdict = excluded.verdict,"
        " user_actions = excluded.user_actions, missing = excluded.missing,"
        " evidence = excluded.evidence, resolved = excluded.resolved,"
        " fingerprint = excluded.fingerprint, checked_at = excluded.checked_at,"
        " error = excluded.error, error_at = excluded.error_at",
        (
            closure.session_id, closure.verdict,
            json.dumps(closure.user_actions, ensure_ascii=False),
            json.dumps(closure.missing, ensure_ascii=False), closure.evidence,
            json.dumps(closure.resolved, ensure_ascii=False), closure.fingerprint,
            closure.checked_at, closure.error, closure.error_at,
        ),
    )


def save_closure_error(
    conn: sqlite3.Connection, session_id: str, message: str, at: int
) -> Closure | None:
    """Record a failed check, keeping the last verdict. None when the session is gone."""
    try:
        conn.execute(
            "INSERT INTO session_closure (session_id, error, error_at) VALUES (?, ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET error = excluded.error,"
            " error_at = excluded.error_at",
            (session_id, message, at),
        )
    except sqlite3.IntegrityError:
        return None
    return get_closure(conn, session_id)


def closure_briefs(conn: sqlite3.Connection) -> dict[str, tuple[str | None, int | None]]:
    """Verdict and check time of every checked session, for the session lists."""
    return {
        row["session_id"]: (row["verdict"] if row["verdict"] in VERDICTS else None,
                            row["checked_at"])
        for row in conn.execute("SELECT session_id, verdict, checked_at FROM session_closure")
    }
