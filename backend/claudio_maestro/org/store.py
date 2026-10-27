"""Organização de agentes em SQLite: agentes, rotinas, fila de despertar, execuções,
registro, avisos, anúncios, PRs e conversas.

Funções simples sobre uma conexão, no estilo de `specialists/store.py`. Quem chama é dono da
transação quando várias escritas precisam ser atômicas (`db.transaction`).
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Final, Literal

Source = Literal["routine", "message", "assignment", "comment", "decision", "manual"]
Outcome = Literal[
    "starting", "running", "waiting", "concluded", "closed", "failed", "skipped", "missed",
    "cancelled",
]
WakeupState = Literal["pending", "taken", "dropped"]
NoticeKind = Literal["notice", "summary", "alert"]
CommentStatus = Literal["queued", "dispatching", "uncertain", "delivered", "dropped"]

# Lower number wins: manual > message > decision > comment > assignment > routine.
PRIORITY: Final = {
    "manual": 0, "message": 1, "decision": 2, "comment": 3, "assignment": 4, "routine": 5,
}
# Runs that hold the agent: at most one of them per agent.
ACTIVE_OUTCOMES: Final = ("starting", "running", "waiting")
# Outcomes that count toward the alert on repeated problems (the rest is noise or in flight).
COUNTED_OUTCOMES: Final = ("failed", "skipped", "concluded", "closed", "waiting")

ROUTINE_NAME_MAX = 80
ROUTINE_INSTRUCTION_MAX = 5000
WAKEUP_PAYLOAD_MAX = 20000


class _Unset:
    """Marks an argument left out, so `None` can still mean "clear it"."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = _Unset()


class OrgError(Exception):
    """Base error. The message is shown to the user."""


class NotFoundError(OrgError):
    pass


class DuplicateSlugError(OrgError):
    def __init__(self) -> None:
        super().__init__("Já existe um agente com esse identificador.")


class ReportsToCycleError(OrgError):
    def __init__(self) -> None:
        super().__init__("Um agente não pode reportar a si mesmo nem a um subordinado.")


class ReportsToOtherProjectError(OrgError):
    def __init__(self) -> None:
        super().__init__("O chefe precisa ser um agente do mesmo projeto.")


@dataclass(frozen=True)
class Agent:
    id: int
    slug: str
    name: str
    project_id: int
    reports_to: int | None
    enabled: bool
    main_session_id: str | None
    definition_hash: str | None
    # {model, effort, denied_tools, extra_project_ids} of the specialist this agent came from;
    # `None` on new agents and once the migration of the files absorbed it into `AGENT.md`.
    legacy: dict[str, Any] | None
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Routine:
    id: int
    project_id: int
    agent_id: int
    name: str
    instruction: str
    enabled: bool
    created_at: int
    updated_at: int


@dataclass(frozen=True)
class Schedule:
    id: int
    routine_id: int
    days: str  # ISO weekday digits, "1" = Monday ... "7" = Sunday, e.g. "1234567"
    time: str  # "HH:MM"
    last_fired_at: int | None


@dataclass(frozen=True)
class Wakeup:
    id: int
    agent_id: int
    source: Source
    priority: int
    routine_id: int | None
    payload: dict[str, Any] | None
    state: WakeupState
    run_id: int | None
    created_at: int
    taken_at: int | None


@dataclass(frozen=True)
class Run:
    id: int
    agent_id: int
    session_id: str | None
    source: Source
    routine_id: int | None
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
    agent_id: int
    run_id: int | None
    kind: NoticeKind
    text: str
    created_at: int
    read_at: int | None


@dataclass(frozen=True)
class Announcement:
    id: int
    agent_id: int
    run_id: int | None
    session_id: str | None  # the session the announcement came from
    text: str
    created_at: int
    delivered_at: int | None


@dataclass(frozen=True)
class Pr:
    url: str
    agent_id: int
    session_id: str | None
    created_at: int
    polled_at: int | None
    closed: bool


@dataclass(frozen=True)
class PrComment:
    comment_id: str  # "issue:<id>", "review:<id>" or "line:<id>"
    pr_url: str
    agent_id: int
    author: str
    body: str
    path: str | None
    line: int | None
    html_url: str
    created_at: int  # GitHub's time, epoch seconds
    received_at: int
    status: CommentStatus
    batch_at: int | None


@dataclass(frozen=True)
class Chat:
    session_id: str
    agent_id: int


def _fields(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _changes(allowed: tuple[str, ...], values: dict[str, Any]) -> dict[str, Any]:
    """The fields actually passed (not `UNSET`); unknown names are a programming error."""
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValueError(f"Campos desconhecidos: {', '.join(sorted(unknown))}")
    return {key: value for key, value in values.items() if value is not UNSET}


# Agents -------------------------------------------------------------------------

_AGENT_COLUMNS = (
    "id, slug, name, project_id, reports_to, enabled, main_session_id, definition_hash,"
    " legacy_json, created_at, updated_at"
)


def _agent(row: sqlite3.Row) -> Agent:
    fields = _fields(row)
    legacy = fields.pop("legacy_json")
    fields["legacy"] = json.loads(legacy) if legacy else None
    fields["enabled"] = bool(fields["enabled"])
    return Agent(**fields)


def _check_reports_to(
    conn: sqlite3.Connection, *, project_id: int, reports_to: int, agent_id: int | None
) -> None:
    boss = conn.execute("SELECT project_id FROM agents WHERE id = ?", (reports_to,)).fetchone()
    if boss is None:
        raise NotFoundError("O chefe escolhido não existe.")
    if boss["project_id"] != project_id:
        raise ReportsToOtherProjectError()
    if agent_id is not None and reports_to in subtree(conn, agent_id):
        raise ReportsToCycleError()


def create_agent(
    conn: sqlite3.Connection,
    *,
    slug: str,
    name: str,
    project_id: int,
    reports_to: int | None,
    now: int,
) -> Agent:
    if reports_to is not None:
        _check_reports_to(conn, project_id=project_id, reports_to=reports_to, agent_id=None)
    try:
        cursor = conn.execute(
            "INSERT INTO agents (slug, name, project_id, reports_to, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, project_id, reports_to, now, now),
        )
    except sqlite3.IntegrityError as error:
        if "agents.slug" in str(error):
            raise DuplicateSlugError() from error
        raise
    assert cursor.lastrowid is not None
    return get_agent(conn, cursor.lastrowid)


def get_agent(conn: sqlite3.Connection, agent_id: int) -> Agent:
    row = conn.execute(f"SELECT {_AGENT_COLUMNS} FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if row is None:
        raise NotFoundError("Agente não encontrado.")
    return _agent(row)


def get_agent_by_slug(conn: sqlite3.Connection, slug: str) -> Agent | None:
    row = conn.execute(f"SELECT {_AGENT_COLUMNS} FROM agents WHERE slug = ?", (slug,)).fetchone()
    return _agent(row) if row else None


def list_agents(conn: sqlite3.Connection, project_id: int | None = None) -> list[Agent]:
    if project_id is None:
        rows = conn.execute(f"SELECT {_AGENT_COLUMNS} FROM agents ORDER BY id")
    else:
        rows = conn.execute(
            f"SELECT {_AGENT_COLUMNS} FROM agents WHERE project_id = ? ORDER BY id", (project_id,)
        )
    return [_agent(row) for row in rows.fetchall()]


_AGENT_UPDATABLE = ("name", "reports_to", "enabled", "definition_hash")


def update_agent(
    conn: sqlite3.Connection,
    agent_id: int,
    *,
    now: int,
    name: str | _Unset = UNSET,
    reports_to: int | None | _Unset = UNSET,
    enabled: bool | _Unset = UNSET,
    definition_hash: str | None | _Unset = UNSET,
) -> Agent:
    """Change only the fields passed; `reports_to=None` makes the agent a top one."""
    agent = get_agent(conn, agent_id)
    values = _changes(
        _AGENT_UPDATABLE,
        {
            "name": name, "reports_to": reports_to, "enabled": enabled,
            "definition_hash": definition_hash,
        },
    )
    if values.get("reports_to") is not None:
        _check_reports_to(
            conn, project_id=agent.project_id, reports_to=values["reports_to"], agent_id=agent_id
        )
    if "enabled" in values:
        values["enabled"] = int(values["enabled"])
    values["updated_at"] = now
    assignments = ", ".join(f"{key} = ?" for key in values)
    conn.execute(f"UPDATE agents SET {assignments} WHERE id = ?", (*values.values(), agent_id))
    return get_agent(conn, agent_id)


def set_main_session(conn: sqlite3.Connection, agent_id: int, session_id: str | None) -> None:
    """Point the agent at its main conversation (kept out of `update_agent`: only the service
    decides it)."""
    cursor = conn.execute(
        "UPDATE agents SET main_session_id = ? WHERE id = ?", (session_id, agent_id)
    )
    if cursor.rowcount == 0:
        raise NotFoundError("Agente não encontrado.")


def clear_legacy(conn: sqlite3.Connection, agent_id: int) -> None:
    """Drop what the migration kept from the old specialist, once `AGENT.md` has it."""
    conn.execute("UPDATE agents SET legacy_json = NULL WHERE id = ?", (agent_id,))


def delete_agent(conn: sqlite3.Connection, agent_id: int) -> None:
    """Remove the agent and what hangs from it. Its subordinates become top agents and its
    sessions keep existing, just without an owner (the foreign key does it)."""
    get_agent(conn, agent_id)
    conn.execute("UPDATE agents SET reports_to = NULL WHERE reports_to = ?", (agent_id,))
    conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))


def subtree(conn: sqlite3.Connection, agent_id: int) -> list[int]:
    """The agent and all its descendants (reports, their reports, ...): the agent first, then
    by depth. Always terminates, even with a cycle written into the table by hand: the walk is
    cut at as many levels as there are agents, and each id is listed once."""
    rows = conn.execute(
        "WITH RECURSIVE tree(id, depth) AS ("
        " SELECT id, 0 FROM agents WHERE id = ?"
        " UNION"
        " SELECT a.id, tree.depth + 1 FROM agents a JOIN tree ON a.reports_to = tree.id"
        " WHERE tree.depth < (SELECT COUNT(*) FROM agents))"
        " SELECT id FROM tree GROUP BY id ORDER BY MIN(depth), id",
        (agent_id,),
    ).fetchall()
    return [row[0] for row in rows]


# Routines and their schedules ----------------------------------------------------

_ROUTINE_COLUMNS = "id, project_id, agent_id, name, instruction, enabled, created_at, updated_at"
_ROUTINE_UPDATABLE = ("name", "instruction", "enabled")


def _routine(row: sqlite3.Row) -> Routine:
    fields = _fields(row)
    fields["enabled"] = bool(fields["enabled"])
    return Routine(**fields)


def _check_routine_text(name: str | None, instruction: str | None) -> None:
    if name is not None and not 1 <= len(name) <= ROUTINE_NAME_MAX:
        raise OrgError(f"O nome da rotina precisa ter de 1 a {ROUTINE_NAME_MAX} caracteres.")
    if instruction is not None and not 1 <= len(instruction) <= ROUTINE_INSTRUCTION_MAX:
        raise OrgError(
            f"A instrução da rotina precisa ter de 1 a {ROUTINE_INSTRUCTION_MAX} caracteres."
        )


def create_routine(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    agent_id: int,
    name: str,
    instruction: str,
    enabled: bool = True,
    now: int,
) -> Routine:
    _check_routine_text(name, instruction)
    cursor = conn.execute(
        "INSERT INTO routines (project_id, agent_id, name, instruction, enabled, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, agent_id, name, instruction, int(enabled), now, now),
    )
    assert cursor.lastrowid is not None
    return get_routine(conn, cursor.lastrowid)


def get_routine(conn: sqlite3.Connection, routine_id: int) -> Routine:
    row = conn.execute(
        f"SELECT {_ROUTINE_COLUMNS} FROM routines WHERE id = ?", (routine_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("Rotina não encontrada.")
    return _routine(row)


def list_routines(
    conn: sqlite3.Connection, project_id: int | None = None, agent_id: int | None = None
) -> list[Routine]:
    conditions: list[str] = []
    values: list[int] = []
    for column, value in (("project_id", project_id), ("agent_id", agent_id)):
        if value is not None:
            conditions.append(f"{column} = ?")
            values.append(value)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(f"SELECT {_ROUTINE_COLUMNS} FROM routines{where} ORDER BY id", values)
    return [_routine(row) for row in rows.fetchall()]


def update_routine(
    conn: sqlite3.Connection,
    routine_id: int,
    *,
    now: int,
    name: str | _Unset = UNSET,
    instruction: str | _Unset = UNSET,
    enabled: bool | _Unset = UNSET,
) -> Routine:
    get_routine(conn, routine_id)
    values = _changes(
        _ROUTINE_UPDATABLE, {"name": name, "instruction": instruction, "enabled": enabled}
    )
    _check_routine_text(values.get("name"), values.get("instruction"))
    if "enabled" in values:
        values["enabled"] = int(values["enabled"])
    values["updated_at"] = now
    assignments = ", ".join(f"{key} = ?" for key in values)
    conn.execute(f"UPDATE routines SET {assignments} WHERE id = ?", (*values.values(), routine_id))
    return get_routine(conn, routine_id)


def delete_routine(conn: sqlite3.Connection, routine_id: int) -> None:
    cursor = conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    if cursor.rowcount == 0:
        raise NotFoundError("Rotina não encontrada.")


_SCHEDULE_COLUMNS = "id, routine_id, days, time, last_fired_at"


def _schedule(row: sqlite3.Row) -> Schedule:
    return Schedule(**_fields(row))


def replace_schedules(
    conn: sqlite3.Connection, routine_id: int, schedules: list[tuple[str, str]], now: int
) -> list[Schedule]:
    """Swap all of a routine's schedules for `(days, time)` pairs. The new ones start with
    `last_fired_at = now`, so editing never fires a slot that already passed today."""
    conn.execute("DELETE FROM routine_schedules WHERE routine_id = ?", (routine_id,))
    for days, time in schedules:
        conn.execute(
            "INSERT INTO routine_schedules (routine_id, days, time, last_fired_at)"
            " VALUES (?, ?, ?, ?)",
            (routine_id, days, time, now),
        )
    return list_schedules(conn, routine_id)


def list_schedules(conn: sqlite3.Connection, routine_id: int | None = None) -> list[Schedule]:
    if routine_id is None:
        rows = conn.execute(f"SELECT {_SCHEDULE_COLUMNS} FROM routine_schedules ORDER BY id")
    else:
        rows = conn.execute(
            f"SELECT {_SCHEDULE_COLUMNS} FROM routine_schedules WHERE routine_id = ? ORDER BY id",
            (routine_id,),
        )
    return [_schedule(row) for row in rows.fetchall()]


def mark_fired(conn: sqlite3.Connection, schedule_id: int, at: int) -> None:
    conn.execute("UPDATE routine_schedules SET last_fired_at = ? WHERE id = ?", (at, schedule_id))


# Wakeup queue -------------------------------------------------------------------

_WAKEUP_COLUMNS = (
    "id, agent_id, source, priority, routine_id, payload, state, run_id, created_at, taken_at"
)


def _wakeup(row: sqlite3.Row) -> Wakeup:
    fields = _fields(row)
    fields["payload"] = json.loads(fields["payload"]) if fields["payload"] else None
    return Wakeup(**fields)


def enqueue_wakeup(
    conn: sqlite3.Connection,
    *,
    agent_id: int,
    source: Source,
    payload: dict[str, Any] | None,
    routine_id: int | None = None,
    now: int,
) -> Wakeup:
    """Queue a wakeup. Only routine wakeups group: when the agent already has a pending one
    from the same `routine_id`, that one is returned and nothing is inserted. Every other origin
    queues one wakeup per event. The caller's transaction makes check and insert atomic."""
    if source == "routine":
        existing = conn.execute(
            f"SELECT {_WAKEUP_COLUMNS} FROM wakeups"
            " WHERE agent_id = ? AND state = 'pending' AND source = 'routine'"
            " AND routine_id IS ? ORDER BY id LIMIT 1",
            (agent_id, routine_id),
        ).fetchone()
        if existing is not None:
            return _wakeup(existing)
    encoded = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    if encoded is not None and len(encoded) > WAKEUP_PAYLOAD_MAX:
        raise OrgError(f"O texto do despertar passa de {WAKEUP_PAYLOAD_MAX} caracteres.")
    cursor = conn.execute(
        "INSERT INTO wakeups (agent_id, source, priority, routine_id, payload, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (agent_id, source, PRIORITY[source], routine_id, encoded, now),
    )
    row = conn.execute(
        f"SELECT {_WAKEUP_COLUMNS} FROM wakeups WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _wakeup(row)


def next_wakeup(conn: sqlite3.Connection, agent_id: int) -> Wakeup | None:
    """The pending wakeup to serve first: lowest `priority`, then the oldest."""
    row = conn.execute(
        f"SELECT {_WAKEUP_COLUMNS} FROM wakeups WHERE agent_id = ? AND state = 'pending'"
        " ORDER BY priority, id LIMIT 1",
        (agent_id,),
    ).fetchone()
    return _wakeup(row) if row else None


def take_wakeup(conn: sqlite3.Connection, wakeup_id: int, run_id: int | None, now: int) -> bool:
    """Mark a pending wakeup as served by `run_id`; False when it was no longer pending."""
    cursor = conn.execute(
        "UPDATE wakeups SET state = 'taken', run_id = ?, taken_at = ?"
        " WHERE id = ? AND state = 'pending'",
        (run_id, now, wakeup_id),
    )
    return cursor.rowcount == 1


def drop_wakeup(conn: sqlite3.Connection, wakeup_id: int, now: int) -> bool:
    """Discard a pending wakeup (agent off, usage cut, ...); False when it was not pending."""
    cursor = conn.execute(
        "UPDATE wakeups SET state = 'dropped', taken_at = ? WHERE id = ? AND state = 'pending'",
        (now, wakeup_id),
    )
    return cursor.rowcount == 1


def pending_wakeups(conn: sqlite3.Connection, agent_id: int | None = None) -> list[Wakeup]:
    """Pending ones in serving order (priority, then age), of one agent or of all."""
    where = "state = 'pending'"
    values: tuple[int, ...] = ()
    if agent_id is not None:
        where += " AND agent_id = ?"
        values = (agent_id,)
    rows = conn.execute(
        f"SELECT {_WAKEUP_COLUMNS} FROM wakeups WHERE {where} ORDER BY priority, id", values
    ).fetchall()
    return [_wakeup(row) for row in rows]


# Runs ---------------------------------------------------------------------------

_RUN_COLUMNS = (
    "id, agent_id, session_id, source, routine_id, scheduled_for, started_at, ended_at,"
    " outcome, reason"
)


def _run(row: sqlite3.Row) -> Run:
    return Run(**_fields(row))


def insert_run(
    conn: sqlite3.Connection,
    *,
    agent_id: int,
    source: Source,
    started_at: int,
    outcome: Outcome,
    session_id: str | None = None,
    routine_id: int | None = None,
    scheduled_for: int | None = None,
    reason: str | None = None,
    ended_at: int | None = None,
) -> Run:
    cursor = conn.execute(
        "INSERT INTO runs (agent_id, session_id, source, routine_id, scheduled_for, started_at,"
        " ended_at, outcome, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (agent_id, session_id, source, routine_id, scheduled_for, started_at, ended_at, outcome,
         reason),
    )
    assert cursor.lastrowid is not None
    return get_run(conn, cursor.lastrowid)


def get_run(conn: sqlite3.Connection, run_id: int) -> Run:
    row = conn.execute(f"SELECT {_RUN_COLUMNS} FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFoundError("Execução não encontrada.")
    return _run(row)


def run_for_session(conn: sqlite3.Connection, session_id: str) -> Run | None:
    """The most recent run that used this session (a session may serve several runs)."""
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE session_id = ?"
        " ORDER BY started_at DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return _run(row) if row else None


def update_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    session_id: str | None | _Unset = UNSET,
    outcome: Outcome | _Unset = UNSET,
    reason: str | None | _Unset = UNSET,
    ended_at: int | None | _Unset = UNSET,
) -> Run:
    """Change only the fields passed (`None` clears `session_id`, `reason` and `ended_at`)."""
    values = _changes(
        ("session_id", "outcome", "reason", "ended_at"),
        {"session_id": session_id, "outcome": outcome, "reason": reason, "ended_at": ended_at},
    )
    if values:
        assignments = ", ".join(f"{key} = ?" for key in values)
        cursor = conn.execute(
            f"UPDATE runs SET {assignments} WHERE id = ?", (*values.values(), run_id)
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Execução não encontrada.")
    return get_run(conn, run_id)


def list_runs(conn: sqlite3.Connection, agent_id: int, limit: int = 50) -> list[Run]:
    """Newest first."""
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE agent_id = ?"
        " ORDER BY started_at DESC, id DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    return [_run(row) for row in rows]


def last_runs(conn: sqlite3.Connection, agent_id: int, n: int) -> list[Run]:
    """The `n` newest runs that count toward the alert (newest first); skips running, missed
    and the like."""
    marks = ", ".join("?" for _ in COUNTED_OUTCOMES)
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE agent_id = ? AND outcome IN ({marks})"
        " ORDER BY started_at DESC, id DESC LIMIT ?",
        (agent_id, *COUNTED_OUTCOMES, n),
    ).fetchall()
    return [_run(row) for row in rows]


def active_run(conn: sqlite3.Connection, agent_id: int) -> Run | None:
    """The run that holds the agent (`starting`, `running` or `waiting`), newest first if
    there is more than one."""
    marks = ", ".join("?" for _ in ACTIVE_OUTCOMES)
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM runs WHERE agent_id = ? AND outcome IN ({marks})"
        " ORDER BY started_at DESC, id DESC LIMIT 1",
        (agent_id, *ACTIVE_OUTCOMES),
    ).fetchone()
    return _run(row) if row else None


# Registry (items the agent already handled) --------------------------------------

_ITEM_COLUMNS = "key, status, link, note, created_at, updated_at"


def _item(row: sqlite3.Row) -> Item:
    return Item(**_fields(row))


def get_items(conn: sqlite3.Connection, agent_id: int, keys: list[str]) -> list[Item]:
    if not keys:
        return []
    marks = ", ".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM registry WHERE agent_id = ? AND key IN ({marks})"
        " ORDER BY key",
        (agent_id, *keys),
    ).fetchall()
    return [_item(row) for row in rows]


def upsert_item(
    conn: sqlite3.Connection,
    agent_id: int,
    *,
    key: str,
    status: str,
    link: str | None,
    note: str | None,
    now: int,
) -> Item:
    conn.execute(
        "INSERT INTO registry (agent_id, key, status, link, note, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (agent_id, key) DO UPDATE SET"
        " status = excluded.status, link = excluded.link, note = excluded.note,"
        " updated_at = excluded.updated_at",
        (agent_id, key, status, link, note, now, now),
    )
    row = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM registry WHERE agent_id = ? AND key = ?", (agent_id, key)
    ).fetchone()
    return _item(row)


def list_items(conn: sqlite3.Connection, agent_id: int) -> list[Item]:
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM registry WHERE agent_id = ? ORDER BY key", (agent_id,)
    ).fetchall()
    return [_item(row) for row in rows]


def delete_item(conn: sqlite3.Connection, agent_id: int, key: str) -> None:
    conn.execute("DELETE FROM registry WHERE agent_id = ? AND key = ?", (agent_id, key))


# Notices ------------------------------------------------------------------------

_NOTICE_COLUMNS = "id, agent_id, run_id, kind, text, created_at, read_at"


def _notice(row: sqlite3.Row) -> Notice:
    return Notice(**_fields(row))


def add_notice(
    conn: sqlite3.Connection,
    *,
    agent_id: int,
    run_id: int | None,
    kind: NoticeKind,
    text: str,
    now: int,
) -> Notice:
    cursor = conn.execute(
        "INSERT INTO notices (agent_id, run_id, kind, text, created_at) VALUES (?, ?, ?, ?, ?)",
        (agent_id, run_id, kind, text, now),
    )
    row = conn.execute(
        f"SELECT {_NOTICE_COLUMNS} FROM notices WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _notice(row)


def list_notices(
    conn: sqlite3.Connection, *, unread_only: bool = False, limit: int = 200
) -> list[Notice]:
    """Newest first."""
    where = " WHERE read_at IS NULL" if unread_only else ""
    rows = conn.execute(
        f"SELECT {_NOTICE_COLUMNS} FROM notices{where} ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [_notice(row) for row in rows]


def mark_notices_read(conn: sqlite3.Connection, ids: list[int], now: int) -> int:
    """Mark the unread ones among `ids` as read; returns how many changed."""
    if not ids:
        return 0
    marks = ", ".join("?" for _ in ids)
    cursor = conn.execute(
        f"UPDATE notices SET read_at = ? WHERE read_at IS NULL AND id IN ({marks})", (now, *ids)
    )
    return cursor.rowcount


# Announcements ------------------------------------------------------------------

_ANNOUNCEMENT_COLUMNS = "id, agent_id, run_id, session_id, text, created_at, delivered_at"


def _announcement(row: sqlite3.Row) -> Announcement:
    return Announcement(**_fields(row))


def add_announcement(
    conn: sqlite3.Connection,
    *,
    agent_id: int,
    run_id: int | None,
    session_id: str | None,
    text: str,
    created_at: int,
) -> Announcement:
    cursor = conn.execute(
        "INSERT INTO announcements (agent_id, run_id, session_id, text, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (agent_id, run_id, session_id, text, created_at),
    )
    row = conn.execute(
        f"SELECT {_ANNOUNCEMENT_COLUMNS} FROM announcements WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _announcement(row)


def pending_announcements(conn: sqlite3.Connection, agent_id: int) -> list[Announcement]:
    """Not yet delivered, oldest first."""
    rows = conn.execute(
        f"SELECT {_ANNOUNCEMENT_COLUMNS} FROM announcements"
        " WHERE agent_id = ? AND delivered_at IS NULL ORDER BY created_at, id",
        (agent_id,),
    ).fetchall()
    return [_announcement(row) for row in rows]


def announcement_for_run(conn: sqlite3.Connection, run_id: int) -> Announcement | None:
    row = conn.execute(
        f"SELECT {_ANNOUNCEMENT_COLUMNS} FROM announcements WHERE run_id = ? ORDER BY id LIMIT 1",
        (run_id,),
    ).fetchone()
    return _announcement(row) if row else None


def update_announcement_text(
    conn: sqlite3.Connection, announcement_id: int, text: str
) -> Announcement:
    conn.execute("UPDATE announcements SET text = ? WHERE id = ?", (text, announcement_id))
    row = conn.execute(
        f"SELECT {_ANNOUNCEMENT_COLUMNS} FROM announcements WHERE id = ?", (announcement_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("Anúncio não encontrado.")
    return _announcement(row)


def mark_announcements_delivered(conn: sqlite3.Connection, ids: list[int], at: int) -> None:
    if not ids:
        return
    marks = ", ".join("?" for _ in ids)
    conn.execute(f"UPDATE announcements SET delivered_at = ? WHERE id IN ({marks})", (at, *ids))


def list_announcements(
    conn: sqlite3.Connection, agent_id: int, limit: int = 50
) -> list[Announcement]:
    """Newest first."""
    rows = conn.execute(
        f"SELECT {_ANNOUNCEMENT_COLUMNS} FROM announcements"
        " WHERE agent_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (agent_id, limit),
    ).fetchall()
    return [_announcement(row) for row in rows]


# Pull requests and their comments -------------------------------------------------

_PR_COLUMNS = "url, agent_id, session_id, created_at, polled_at, closed"
_COMMENT_COLUMNS = (
    "comment_id, pr_url, agent_id, author, body, path, line, html_url, created_at,"
    " received_at, status, batch_at"
)


def _pr(row: sqlite3.Row) -> Pr:
    fields = _fields(row)
    fields["closed"] = bool(fields["closed"])
    return Pr(**fields)


def normalize_pr_url(url: str) -> str:
    """A PR URL without query, fragment or trailing slash: the one form the registry keeps and
    compares, so a PR is never stored twice."""
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def upsert_pr(
    conn: sqlite3.Connection,
    *,
    url: str,
    agent_id: int,
    session_id: str | None,
    created_at: int,
) -> None:
    """Register a PR under its normalized URL. A known session is never overwritten by a
    missing one."""
    url = normalize_pr_url(url)
    conn.execute(
        "INSERT INTO agent_prs (url, agent_id, session_id, created_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (url) DO UPDATE SET"
        " session_id = COALESCE(excluded.session_id, agent_prs.session_id)",
        (url, agent_id, session_id, created_at),
    )


def get_pr(conn: sqlite3.Connection, url: str) -> Pr | None:
    row = conn.execute(
        f"SELECT {_PR_COLUMNS} FROM agent_prs WHERE url = ?", (normalize_pr_url(url),)
    ).fetchone()
    return _pr(row) if row else None


def open_prs(conn: sqlite3.Connection) -> list[Pr]:
    rows = conn.execute(
        f"SELECT {_PR_COLUMNS} FROM agent_prs WHERE closed = 0 ORDER BY created_at, url"
    ).fetchall()
    return [_pr(row) for row in rows]


def mark_pr_polled(conn: sqlite3.Connection, url: str, at: int) -> None:
    conn.execute("UPDATE agent_prs SET polled_at = ? WHERE url = ?", (at, normalize_pr_url(url)))


def close_pr(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("UPDATE agent_prs SET closed = 1 WHERE url = ?", (normalize_pr_url(url),))


def _comment(row: sqlite3.Row) -> PrComment:
    return PrComment(**_fields(row))


def insert_comment(conn: sqlite3.Connection, comment: PrComment) -> bool:
    """Queue a comment; False when it was already seen (same `comment_id`)."""
    cursor = conn.execute(
        f"INSERT OR IGNORE INTO agent_pr_comments ({_COMMENT_COLUMNS})"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            comment.comment_id, comment.pr_url, comment.agent_id, comment.author, comment.body,
            comment.path, comment.line, comment.html_url, comment.created_at,
            comment.received_at, comment.status, comment.batch_at,
        ),
    )
    return cursor.rowcount == 1


def queued_comments(conn: sqlite3.Connection) -> list[PrComment]:
    """Oldest first (by GitHub time, then arrival)."""
    rows = conn.execute(
        f"SELECT {_COMMENT_COLUMNS} FROM agent_pr_comments WHERE status = 'queued'"
        " ORDER BY created_at, received_at, comment_id"
    ).fetchall()
    return [_comment(row) for row in rows]


def mark_comments(
    conn: sqlite3.Connection, ids: list[str], status: CommentStatus, batch_at: int | None
) -> None:
    if not ids:
        return
    marks = ", ".join("?" for _ in ids)
    conn.execute(
        f"UPDATE agent_pr_comments SET status = ?, batch_at = ? WHERE comment_id IN ({marks})",
        (status, batch_at, *ids),
    )


def turns_today(conn: sqlite3.Connection, pr_url: str, day_start: int) -> int:
    """Turns spent on this PR since `day_start`: distinct batches of its comments."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT batch_at) FROM agent_pr_comments"
        " WHERE pr_url = ? AND batch_at >= ?",
        (pr_url, day_start),
    ).fetchone()
    return row[0]


# Conversations the agent started -------------------------------------------------


def add_chat(conn: sqlite3.Connection, session_id: str, agent_id: int) -> None:
    """Mark `session_id` as a conversation with the agent (a second call changes nothing)."""
    conn.execute(
        "INSERT OR IGNORE INTO agent_chats (session_id, agent_id) VALUES (?, ?)",
        (session_id, agent_id),
    )


def get_chat(conn: sqlite3.Connection, session_id: str) -> Chat | None:
    row = conn.execute(
        "SELECT session_id, agent_id FROM agent_chats WHERE session_id = ?", (session_id,)
    ).fetchone()
    return Chat(**_fields(row)) if row else None


def list_chats(conn: sqlite3.Connection, agent_id: int) -> list[Chat]:
    rows = conn.execute(
        "SELECT session_id, agent_id FROM agent_chats WHERE agent_id = ? ORDER BY rowid",
        (agent_id,),
    ).fetchall()
    return [Chat(**_fields(row)) for row in rows]
