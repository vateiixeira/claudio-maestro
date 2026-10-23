"""Agentes (specialists) in SQLite: registry, schedules, runs, memory items and notices.

Plain functions over a connection, like `groups.py`. Callers own the transaction when
they need several writes to be atomic (`db.transaction`).
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

Autonomy = Literal["ask", "full"]
Trigger = Literal["schedule", "manual"]
Outcome = Literal["running", "concluded", "closed", "waiting", "failed", "skipped", "missed"]
NoticeKind = Literal["notice", "summary", "alert"]

DEFAULT_RUN_TEXT = "Execute a rotina agendada."
# Outcomes that count toward the alert on repeated problems (the rest is noise or in flight).
COUNTED_OUTCOMES = ("failed", "skipped", "concluded", "closed", "waiting")


class SpecialistError(Exception):
    """Base error. The message is shown to the user."""


class SpecialistNotFoundError(SpecialistError):
    pass


class DuplicateSlugError(SpecialistError):
    pass


@dataclass(frozen=True)
class Specialist:
    id: int
    slug: str
    name: str
    project_id: int
    extra_project_ids: list[int]
    autonomy: Autonomy
    outward_patterns: list[str]
    always_ask_patterns: list[str]
    close_by_check: bool
    model: str | None
    effort: str | None
    run_text: str
    enabled: bool
    last_mcp: list[dict[str, str]]
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Schedule:
    id: int
    specialist_id: int
    days: str  # ISO weekday digits, "1" = Monday ... "7" = Sunday, e.g. "1234567"
    time: str  # "HH:MM"
    last_fired_at: int | None


@dataclass(frozen=True)
class Run:
    id: int
    specialist_id: int
    session_id: str | None
    trigger: Trigger
    scheduled_for: int | None
    started_at: int
    ended_at: int | None
    outcome: Outcome
    reason: str | None


@dataclass(frozen=True)
class Item:
    key: str
    status: str
    link: str | None
    note: str | None
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Notice:
    id: int
    specialist_id: int
    session_id: str | None
    kind: NoticeKind
    text: str
    created_at: int
    read_at: int | None


# Specialists ------------------------------------------------------------------

_JSON_FIELDS = ("extra_project_ids", "outward_patterns", "always_ask_patterns", "last_mcp")
_BOOL_FIELDS = ("close_by_check", "enabled")
_UPDATABLE = (
    "slug", "name", "project_id", "autonomy", "model", "effort", "run_text",
    *_JSON_FIELDS, *_BOOL_FIELDS,
)
_COLUMNS = (
    "id, slug, name, project_id, extra_project_ids, autonomy, outward_patterns,"
    " always_ask_patterns, close_by_check, model, effort, run_text, enabled, last_mcp,"
    " created_at, updated_at"
)


def _specialist(row: sqlite3.Row) -> Specialist:
    fields = {key: row[key] for key in row.keys()}
    for key in _JSON_FIELDS:
        fields[key] = json.loads(fields[key])
    for key in _BOOL_FIELDS:
        fields[key] = bool(fields[key])
    return Specialist(**fields)


def _duplicate_slug(slug: str) -> DuplicateSlugError:
    return DuplicateSlugError(f"Já existe um agente com o identificador “{slug}”.")


def create_specialist(
    conn: sqlite3.Connection, *, slug: str, name: str, project_id: int, now: int
) -> Specialist:
    try:
        cursor = conn.execute(
            "INSERT INTO specialists (slug, name, project_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (slug, name, project_id, now, now),
        )
    except sqlite3.IntegrityError as error:
        if "specialists.slug" in str(error):
            raise _duplicate_slug(slug) from error
        raise
    assert cursor.lastrowid is not None
    return get_specialist(conn, cursor.lastrowid)


def get_specialist(conn: sqlite3.Connection, specialist_id: int) -> Specialist:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM specialists WHERE id = ?", (specialist_id,)
    ).fetchone()
    if row is None:
        raise SpecialistNotFoundError("Agente não encontrado.")
    return _specialist(row)


def list_specialists(conn: sqlite3.Connection) -> list[Specialist]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM specialists ORDER BY id").fetchall()
    return [_specialist(row) for row in rows]


def update_specialist(
    conn: sqlite3.Connection, specialist_id: int, *, now: int, **fields: Any
) -> Specialist:
    unknown = set(fields) - set(_UPDATABLE)
    if unknown:
        raise ValueError(f"Campos desconhecidos: {', '.join(sorted(unknown))}")
    values: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _JSON_FIELDS:
            value = json.dumps(value, ensure_ascii=False)
        elif key in _BOOL_FIELDS:
            value = int(value)
        values[key] = value
    values["updated_at"] = now
    assignments = ", ".join(f"{key} = ?" for key in values)
    try:
        cursor = conn.execute(
            f"UPDATE specialists SET {assignments} WHERE id = ?",
            (*values.values(), specialist_id),
        )
    except sqlite3.IntegrityError as error:
        if "specialists.slug" in str(error):
            raise _duplicate_slug(str(fields.get("slug"))) from error
        raise
    if cursor.rowcount == 0:
        raise SpecialistNotFoundError("Agente não encontrado.")
    return get_specialist(conn, specialist_id)


def delete_specialist(conn: sqlite3.Connection, specialist_id: int) -> None:
    cursor = conn.execute("DELETE FROM specialists WHERE id = ?", (specialist_id,))
    if cursor.rowcount == 0:
        raise SpecialistNotFoundError("Agente não encontrado.")


# Schedules --------------------------------------------------------------------

_SCHEDULE_COLUMNS = "id, specialist_id, days, time, last_fired_at"


def _schedule(row: sqlite3.Row) -> Schedule:
    return Schedule(**{key: row[key] for key in row.keys()})


def replace_schedules(
    conn: sqlite3.Connection, specialist_id: int, schedules: list[tuple[str, str]], now: int
) -> list[Schedule]:
    """Swap all of an agent's schedules for `(days, time)` pairs. The new ones start
    with `last_fired_at = now`, so editing never fires a slot that already passed today."""
    conn.execute("DELETE FROM specialist_schedules WHERE specialist_id = ?", (specialist_id,))
    for days, time in schedules:
        conn.execute(
            "INSERT INTO specialist_schedules (specialist_id, days, time, last_fired_at)"
            " VALUES (?, ?, ?, ?)",
            (specialist_id, days, time, now),
        )
    return list_schedules(conn, specialist_id)


def list_schedules(conn: sqlite3.Connection, specialist_id: int | None = None) -> list[Schedule]:
    if specialist_id is None:
        rows = conn.execute(f"SELECT {_SCHEDULE_COLUMNS} FROM specialist_schedules ORDER BY id")
    else:
        rows = conn.execute(
            f"SELECT {_SCHEDULE_COLUMNS} FROM specialist_schedules WHERE specialist_id = ?"
            " ORDER BY id",
            (specialist_id,),
        )
    return [_schedule(row) for row in rows.fetchall()]


def mark_fired(conn: sqlite3.Connection, schedule_id: int, at: int) -> None:
    conn.execute("UPDATE specialist_schedules SET last_fired_at = ? WHERE id = ?", (at, schedule_id))


# Runs -------------------------------------------------------------------------

_RUN_COLUMNS = "id, specialist_id, session_id, trigger, scheduled_for, started_at, ended_at, outcome, reason"


def _run(row: sqlite3.Row) -> Run:
    return Run(**{key: row[key] for key in row.keys()})


def insert_run(
    conn: sqlite3.Connection,
    *,
    specialist_id: int,
    trigger: Trigger,
    started_at: int,
    outcome: Outcome,
    session_id: str | None = None,
    scheduled_for: int | None = None,
    reason: str | None = None,
    ended_at: int | None = None,
) -> Run:
    cursor = conn.execute(
        "INSERT INTO specialist_runs (specialist_id, session_id, trigger, scheduled_for,"
        " started_at, ended_at, outcome, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (specialist_id, session_id, trigger, scheduled_for, started_at, ended_at, outcome, reason),
    )
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM specialist_runs WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _run(row)


def finish_run(
    conn: sqlite3.Connection, run_id: int, *, outcome: Outcome, ended_at: int, reason: str | None = None
) -> None:
    conn.execute(
        "UPDATE specialist_runs SET outcome = ?, ended_at = ?, reason = ? WHERE id = ?",
        (outcome, ended_at, reason, run_id),
    )


def run_for_session(conn: sqlite3.Connection, session_id: str) -> Run | None:
    """The most recent run that used this session."""
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM specialist_runs WHERE session_id = ?"
        " ORDER BY started_at DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return _run(row) if row else None


def list_runs(conn: sqlite3.Connection, specialist_id: int, limit: int = 50) -> list[Run]:
    """Newest first."""
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM specialist_runs WHERE specialist_id = ?"
        " ORDER BY started_at DESC, id DESC LIMIT ?",
        (specialist_id, limit),
    ).fetchall()
    return [_run(row) for row in rows]


def last_runs(conn: sqlite3.Connection, specialist_id: int, n: int) -> list[Run]:
    """The `n` newest runs that count toward the alert (newest first); skips running,
    missed and the like."""
    marks = ", ".join("?" for _ in COUNTED_OUTCOMES)
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM specialist_runs"
        f" WHERE specialist_id = ? AND outcome IN ({marks})"
        " ORDER BY started_at DESC, id DESC LIMIT ?",
        (specialist_id, *COUNTED_OUTCOMES, n),
    ).fetchall()
    return [_run(row) for row in rows]


# Items ------------------------------------------------------------------------

_ITEM_COLUMNS = "key, status, link, note, created_at, updated_at"


def _item(row: sqlite3.Row) -> Item:
    return Item(**{key: row[key] for key in row.keys()})


def get_items(conn: sqlite3.Connection, specialist_id: int, keys: list[str]) -> list[Item]:
    if not keys:
        return []
    marks = ", ".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM specialist_items"
        f" WHERE specialist_id = ? AND key IN ({marks}) ORDER BY key",
        (specialist_id, *keys),
    ).fetchall()
    return [_item(row) for row in rows]


def upsert_item(
    conn: sqlite3.Connection,
    specialist_id: int,
    *,
    key: str,
    status: str,
    link: str | None,
    note: str | None,
    now: int,
) -> Item:
    conn.execute(
        "INSERT INTO specialist_items (specialist_id, key, status, link, note, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (specialist_id, key) DO UPDATE SET"
        " status = excluded.status, link = excluded.link, note = excluded.note,"
        " updated_at = excluded.updated_at",
        (specialist_id, key, status, link, note, now, now),
    )
    row = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM specialist_items WHERE specialist_id = ? AND key = ?",
        (specialist_id, key),
    ).fetchone()
    return _item(row)


def list_items(conn: sqlite3.Connection, specialist_id: int) -> list[Item]:
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM specialist_items WHERE specialist_id = ? ORDER BY key",
        (specialist_id,),
    ).fetchall()
    return [_item(row) for row in rows]


def delete_item(conn: sqlite3.Connection, specialist_id: int, key: str) -> None:
    conn.execute(
        "DELETE FROM specialist_items WHERE specialist_id = ? AND key = ?", (specialist_id, key)
    )


# Notices ----------------------------------------------------------------------

_NOTICE_COLUMNS = "id, specialist_id, session_id, kind, text, created_at, read_at"


def _notice(row: sqlite3.Row) -> Notice:
    return Notice(**{key: row[key] for key in row.keys()})


def add_notice(
    conn: sqlite3.Connection,
    *,
    specialist_id: int,
    session_id: str | None,
    kind: NoticeKind,
    text: str,
    now: int,
) -> Notice:
    cursor = conn.execute(
        "INSERT INTO specialist_notices (specialist_id, session_id, kind, text, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (specialist_id, session_id, kind, text, now),
    )
    row = conn.execute(
        f"SELECT {_NOTICE_COLUMNS} FROM specialist_notices WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _notice(row)


def list_notices(
    conn: sqlite3.Connection, *, unread_only: bool = False, limit: int = 200
) -> list[Notice]:
    """Newest first."""
    where = " WHERE read_at IS NULL" if unread_only else ""
    rows = conn.execute(
        f"SELECT {_NOTICE_COLUMNS} FROM specialist_notices{where} ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_notice(row) for row in rows]


def mark_notices_read(conn: sqlite3.Connection, ids: list[int], now: int) -> int:
    """Mark the unread ones among `ids` as read; returns how many changed."""
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE specialist_notices SET read_at = ? WHERE read_at IS NULL AND id IN ({marks})",
        (now, *ids),
    )
    return cursor.rowcount
