"""Delivery records ("Entregas"): one per "Finalizar" click and local day.

Finishing again on the same day renews that day's record; on another day it opens
a new one that starts where the previous record ended (`from_cursor`).
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from claudio_maestro import db

STATUSES: tuple[str, ...] = ("pending", "done", "title_only", "error")
_COLUMNS = (
    "id, session_id, project_id, project_name, title, finished_at, day, from_cursor,"
    " to_cursor, status, summary_title, bullets, error, updated_at"
)


@dataclass
class Delivery:
    id: int
    session_id: str | None
    project_id: int | None
    project_name: str
    title: str
    finished_at: int
    day: str
    from_cursor: str | None
    to_cursor: str | None
    status: str
    summary_title: str | None = None
    bullets: list[str] = field(default_factory=list)
    error: str | None = None
    updated_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        """What the frontend receives (the day, cursors and updated_at are internal)."""
        return {
            "id": self.id, "session_id": self.session_id, "project_id": self.project_id,
            "project_name": self.project_name, "title": self.title,
            "finished_at": self.finished_at, "status": self.status,
            "summary_title": self.summary_title, "bullets": list(self.bullets),
            "error": self.error,
        }


def local_day(timestamp: int) -> str:
    return date.fromtimestamp(timestamp).isoformat()


def _delivery(row: sqlite3.Row) -> Delivery:
    try:
        bullets = json.loads(row["bullets"])
    except ValueError:
        bullets = []
    return Delivery(
        id=row["id"], session_id=row["session_id"], project_id=row["project_id"],
        project_name=row["project_name"], title=row["title"], finished_at=row["finished_at"],
        day=row["day"], from_cursor=row["from_cursor"], to_cursor=row["to_cursor"],
        status=row["status"], summary_title=row["summary_title"],
        bullets=[b for b in bullets if isinstance(b, str)] if isinstance(bullets, list) else [],
        error=row["error"], updated_at=row["updated_at"],
    )


def get(conn: sqlite3.Connection, delivery_id: int) -> Delivery | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM deliveries WHERE id = ?",
                       (delivery_id,)).fetchone()
    return None if row is None else _delivery(row)


def record_finish(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    project_id: int | None,
    project_name: str,
    title: str,
    finished_at: int,
    to_cursor: str | None,
    status: str,
) -> Delivery:
    """Record a "Finalizar" click: renew the session's record of the same local day, or
    open a new one starting at the end of the session's latest record."""
    day = local_day(finished_at)
    with db.transaction(conn):
        latest = conn.execute(
            "SELECT id, day, to_cursor FROM deliveries WHERE session_id = ?"
            " ORDER BY finished_at DESC, id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if latest is not None and latest["day"] == day:
            delivery_id = latest["id"]
            conn.execute(
                "UPDATE deliveries SET project_id = ?, project_name = ?, title = ?,"
                " finished_at = ?, to_cursor = ?, status = ?, summary_title = NULL,"
                " bullets = '[]', error = NULL, updated_at = ? WHERE id = ?",
                (project_id, project_name, title, finished_at, to_cursor, status,
                 finished_at, delivery_id),
            )
        else:
            cursor = conn.execute(
                "INSERT INTO deliveries (session_id, project_id, project_name, title,"
                " finished_at, day, from_cursor, to_cursor, status, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, project_id, project_name, title, finished_at, day,
                 latest["to_cursor"] if latest is not None else None, to_cursor, status,
                 finished_at),
            )
            delivery_id = cursor.lastrowid
    found = get(conn, delivery_id)
    assert found is not None
    return found


def list_day(conn: sqlite3.Connection, day: str) -> list[Delivery]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM deliveries WHERE day = ?"
        " ORDER BY project_name COLLATE NOCASE, finished_at, id",
        (day,),
    ).fetchall()
    return [_delivery(r) for r in rows]


def pending_ids(conn: sqlite3.Connection) -> list[int]:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM deliveries WHERE status = 'pending' ORDER BY id")]


def _set(conn: sqlite3.Connection, delivery_id: int, sql: str, params: tuple) -> Delivery | None:
    cursor = conn.execute(f"UPDATE deliveries SET {sql} WHERE id = ?", (*params, delivery_id))
    return get(conn, delivery_id) if cursor.rowcount else None


def mark_pending(conn: sqlite3.Connection, delivery_id: int, at: int) -> Delivery | None:
    return _set(conn, delivery_id, "status = 'pending', error = NULL, updated_at = ?", (at,))


def save_summary(conn: sqlite3.Connection, delivery_id: int, *, summary_title: str,
                 bullets: list[str], at: int) -> Delivery | None:
    return _set(conn, delivery_id,
                "status = 'done', summary_title = ?, bullets = ?, error = NULL, updated_at = ?",
                (summary_title, json.dumps(bullets, ensure_ascii=False), at))


def mark_title_only(conn: sqlite3.Connection, delivery_id: int, at: int) -> Delivery | None:
    return _set(conn, delivery_id,
                "status = 'title_only', summary_title = NULL, bullets = '[]', error = NULL,"
                " updated_at = ?", (at,))


def mark_error(conn: sqlite3.Connection, delivery_id: int, message: str,
               at: int) -> Delivery | None:
    """Keeps the last summary, like the digest agent does."""
    return _set(conn, delivery_id, "status = 'error', error = ?, updated_at = ?", (message, at))
