"""Routes of the agents (specialists): registry, schedules, skill, learnings, secrets,
memory items, runs and notices.

Everything a person types is validated here before it reaches the store or the disk, so
no request can end in a 500 from a foreign key or put a path outside the agents folder.
Secrets are write-only: they are read from the request by hand (a validation error of
the framework echoes the input) and no response or event ever carries a value.
"""

import re
import sqlite3
import time
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from claudio_maestro import db, projects
from claudio_maestro.api.deps import DbDep
from claudio_maestro.sessions import (
    MODEL_PATTERN,
    InvalidDecisionError,
    ProjectUnavailableError,
)
from claudio_maestro.specialists import github_hooks, store
from claudio_maestro.specialists.files import (
    SLUG_MAX_LENGTH,
    SLUG_PATTERN,
    InvalidSecretNameError,
    InvalidSecretValueError,
    LearningsTooLongError,
    SkillInvalidError,
    SpecialistFiles,
    parse_skill,
)
from claudio_maestro.specialists.policy import MAX_TOOL_NAME, is_tool_name
from claudio_maestro.specialists.service import QueueFullError

router = APIRouter(prefix="/api")

MAX_NAME = 100
MAX_PATTERNS = 100
MAX_PATTERN = 100
# What reaches the check below; past this the framework refuses it on its own.
MAX_PATTERN_INPUT = 1000
MAX_RUN_TEXT = 5000
MAX_SCHEDULES = 50
MAX_EXTRA_PROJECTS = 50
MAX_SECRETS_PER_REQUEST = 50
MAX_SECRET_VALUE = 20_000
MAX_NOTICE_IDS = 500
MAX_ITEM_KEY = 1000
DAYS = "1234567"
TIME_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
# A command pattern is plain words: no quotes, globs, parentheses or shell operators.
COMMAND_PATTERN = re.compile(r"[\w .:/-]+")

AGENT_NOT_FOUND = "Agente não encontrado."
PROJECT_NOT_FOUND = "Projeto não encontrado."
FILES_GONE = "A pasta do agente não existe mais."
UNREADABLE_FILE = (
    "O arquivo está em uma codificação inválida (esperado UTF-8). "
    "Salve um texto novo para substituí-lo."
)
BUSY_TEXT = (
    "O agente tem uma conversa com turno em andamento ou esperando você. "
    "Finalize-a antes de excluir o agente."
)
BAD_PATTERN = (
    "Os padrões aceitam só letras, números, espaço e os sinais - _ . / :, "
    "com até 100 caracteres cada."
)
BAD_TOOL = (
    "Use o nome da ferramenta (ex.: WebFetch ou mcp__servidor__ferramenta) ou o servidor "
    f"inteiro (mcp__servidor), com até {MAX_TOOL_NAME} caracteres. "
    "Sem parênteses, espaços nem curingas."
)
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9-]{1,39}")
SECRET_MIN, SECRET_MAX = 16, 256
BAD_GITHUB_BODY = (
    'Envie {"login": "usuario-do-github", "secret": "segredo"}, com um ou os dois campos. '
    f"O login tem até 39 letras, números ou hífens; o segredo tem de {SECRET_MIN} a {SECRET_MAX} "
    "caracteres, sem espaço no começo nem no fim."
)
BAD_SECRETS_BODY = 'Envie {"values": {"NOME": "valor" ou null}}.'

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME)]
Pattern = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PATTERN_INPUT)
]
Patterns = Annotated[list[Pattern], Field(max_length=MAX_PATTERNS)]
Tool = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_PATTERN_INPUT)
]
Tools = Annotated[list[Tool], Field(max_length=MAX_PATTERNS)]
RunText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_RUN_TEXT)
]


class SpecialistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    # The folder name: lowercase letters, digits and single hyphens. `files.SLUG_PATTERN`
    # is stricter than this pattern (no leading, trailing or doubled hyphen) and is also
    # checked, so nothing with `/`, `..` or the like ever reaches the disk.
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,%d}$" % (SLUG_MAX_LENGTH - 1))
    project_id: int


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Checked by hand, so the error comes as one sentence in Portuguese.
    days: str = Field(max_length=20)
    time: str = Field(max_length=20)


class ConversationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    new: bool = False


class SpecialistPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    project_id: int | None = None
    extra_project_ids: Annotated[list[int], Field(max_length=MAX_EXTRA_PROJECTS)] | None = None
    autonomy: Literal["ask", "full"] | None = None
    outward_patterns: Patterns | None = None
    always_ask_patterns: Patterns | None = None
    denied_tools: Tools | None = None
    close_by_check: bool | None = None
    # `null` goes back to the default model / effort.
    model: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=MODEL_PATTERN.pattern)
    ] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    run_text: RunText | None = None
    enabled: bool | None = None
    queue_paused: bool | None = None
    schedules: Annotated[list[ScheduleIn], Field(max_length=MAX_SCHEDULES)] | None = None


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_RUN_TEXT)] | None = None


class NoticesRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[int], Field(max_length=MAX_NOTICE_IDS)]


# Helpers ----------------------------------------------------------------------------------

_NULLABLE = ("model", "effort")


def _now() -> int:
    return int(time.time())


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


def _not_found(message: str = AGENT_NOT_FOUND) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _files(request: Request) -> SpecialistFiles:
    return request.app.state.specialist_files


def _publish(request: Request, kind: str, data: dict[str, Any]) -> None:
    request.app.state.hub.publish({"session_id": None, "seq": 0, "type": kind, "data": data})


def _changed(request: Request, specialist_id: int) -> None:
    _publish(request, "specialist.changed", {"id": specialist_id})


def _get(conn: sqlite3.Connection, specialist_id: int) -> store.Specialist:
    try:
        return store.get_specialist(conn, specialist_id)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc


def _project_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT id FROM projects")}


def _description(files: SpecialistFiles, slug: str) -> str:
    try:
        return parse_skill(files.read_skill(slug)).description
    except (OSError, ValueError):
        return ""


def _schedule_out(schedule: store.Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "days": schedule.days,
        "time": schedule.time,
        "last_fired_at": schedule.last_fired_at,
    }


def _out(
    conn: sqlite3.Connection,
    files: SpecialistFiles,
    specialist: store.Specialist,
    project_ids: set[int],
    unseen: int = 0,
) -> dict[str, Any]:
    runs = store.list_runs(conn, specialist.id, 1)
    open_sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE specialist_id = ? AND finished = 0", (specialist.id,)
    ).fetchone()[0]
    return {
        "id": specialist.id,
        "slug": specialist.slug,
        "name": specialist.name,
        "description": _description(files, specialist.slug),
        "project_id": specialist.project_id,
        # Projects removed since the agent was configured are not listed.
        "extra_project_ids": [i for i in specialist.extra_project_ids if i in project_ids],
        "autonomy": specialist.autonomy,
        "outward_patterns": specialist.outward_patterns,
        "always_ask_patterns": specialist.always_ask_patterns,
        "denied_tools": specialist.denied_tools,
        "close_by_check": specialist.close_by_check,
        "model": specialist.model,
        "effort": specialist.effort,
        "run_text": specialist.run_text,
        "enabled": specialist.enabled,
        "queue_paused": specialist.queue_paused,
        "last_mcp": specialist.last_mcp,
        "schedules": [_schedule_out(s) for s in store.list_schedules(conn, specialist.id)],
        "last_run": asdict(runs[0]) if runs else None,
        "open_sessions": open_sessions,
        "main_session_id": specialist.main_session_id,
        # Announcements the main conversation has not received, plus one while it waits
        # for an answer.
        "unseen": unseen,
    }


def _one(request: Request, conn: sqlite3.Connection, specialist_id: int) -> dict[str, Any]:
    return _out(
        conn, _files(request), store.get_specialist(conn, specialist_id), _project_ids(conn),
        request.app.state.specialists.unseen(specialist_id),
    )


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _clean_schedules(items: list[ScheduleIn]) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    days_by_time: dict[str, set[str]] = {}
    for item in items:
        days = item.days.strip()
        if not days or any(ch not in DAYS for ch in days):
            raise _unprocessable(
                "Os dias do horário devem ser números de 1 (segunda) a 7 (domingo)."
            )
        at = item.time.strip()
        if not TIME_PATTERN.fullmatch(at):
            raise _unprocessable("O horário deve estar no formato HH:MM, de 00:00 a 23:59.")
        day_set = set(days)
        if days_by_time.setdefault(at, set()) & day_set:
            raise _unprocessable(f"O horário {at} está repetido nos mesmos dias.")
        days_by_time[at] |= day_set
        cleaned.append(("".join(sorted(day_set)), at))
    return cleaned


def _clean_patterns(patterns: list[str]) -> list[str]:
    for pattern in patterns:
        if len(pattern) > MAX_PATTERN or not COMMAND_PATTERN.fullmatch(pattern):
            raise _unprocessable(BAD_PATTERN)
    return _dedupe(patterns)


def _clean_tools(tools: list[str]) -> list[str]:
    for tool in tools:
        if not is_tool_name(tool):
            raise _unprocessable(BAD_TOOL)
    return _dedupe(tools)


def _require_project(conn: sqlite3.Connection, project_id: int) -> None:
    if project_id not in _project_ids(conn):
        raise _not_found(PROJECT_NOT_FOUND)


# Registry -----------------------------------------------------------------------------------


@router.get("/specialists")
async def list_specialists(request: Request, conn: DbDep) -> list[dict[str, Any]]:
    files = _files(request)
    project_ids = _project_ids(conn)
    service = request.app.state.specialists
    return [
        _out(conn, files, s, project_ids, service.unseen(s.id))
        for s in store.list_specialists(conn)
    ]


@router.post("/specialists", status_code=status.HTTP_201_CREATED)
async def create_specialist(
    body: SpecialistCreate, request: Request, conn: DbDep
) -> dict[str, Any]:
    if not SLUG_PATTERN.fullmatch(body.slug):
        raise _unprocessable(
            "O identificador deve ter letras minúsculas, números e hífens entre eles."
        )
    files = _files(request)
    try:
        with db.transaction(conn):
            _require_project(conn, body.project_id)
            specialist = store.create_specialist(
                conn, slug=body.slug, name=body.name, project_id=body.project_id, now=_now()
            )
            try:
                files.create(body.slug, body.name)
            except FileExistsError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Já existe uma pasta para o identificador “{body.slug}”.",
                ) from exc
            except Exception:
                files.delete(body.slug)
                raise
    except store.DuplicateSlugError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    _changed(request, specialist.id)
    return _one(request, conn, specialist.id)


@router.patch("/specialists/{specialist_id}")
async def update_specialist(
    specialist_id: int, body: SpecialistPatch, request: Request, conn: DbDep
) -> dict[str, Any]:
    given = {name: getattr(body, name) for name in body.model_fields_set}
    for name, value in given.items():
        if value is None and name not in _NULLABLE:
            raise _unprocessable(f"O campo “{name}” não aceita valor nulo.")
    schedules = _clean_schedules(given.pop("schedules")) if "schedules" in given else None
    for field in ("outward_patterns", "always_ask_patterns"):
        if field in given:
            given[field] = _clean_patterns(given[field])
    if "denied_tools" in given:
        given["denied_tools"] = _clean_tools(given["denied_tools"])
    now = _now()
    try:
        with db.transaction(conn):
            previous = store.get_specialist(conn, specialist_id)
            if "project_id" in given:
                _require_project(conn, given["project_id"])
            project_id = given.get("project_id", previous.project_id)
            if "extra_project_ids" in given or "project_id" in given:
                extras = _dedupe(given.get("extra_project_ids", previous.extra_project_ids))
                if "extra_project_ids" in given:
                    missing = set(extras) - _project_ids(conn)
                    if missing:
                        raise _unprocessable("Um dos projetos adicionais não existe.")
                given["extra_project_ids"] = [i for i in extras if i != project_id]
            if given:
                store.update_specialist(conn, specialist_id, now=now, **given)
            if schedules is not None:
                store.replace_schedules(conn, specialist_id, schedules, now)
            if given.get("enabled") is True and not previous.enabled:
                # Slots of the period it was off are not "missed": start from now.
                for schedule in store.list_schedules(conn, specialist_id):
                    store.mark_fired(conn, schedule.id, now)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    _changed(request, specialist_id)
    if given.get("queue_paused") is False:
        await request.app.state.specialists.drain_queue(specialist_id)
        request.app.state.specialists.wake_queue()
    return _one(request, conn, specialist_id)


@router.delete("/specialists/{specialist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_specialist(specialist_id: int, request: Request, conn: DbDep) -> Response:
    specialist = _get(conn, specialist_id)
    if request.app.state.specialists.is_busy(specialist_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=BUSY_TEXT)
    session_ids = {
        row[0]
        for row in conn.execute(
            "SELECT session_id FROM sessions WHERE specialist_id = ?", (specialist_id,)
        )
    }
    try:
        with db.transaction(conn):
            # The sessions stay: the schema unlinks them (`ON DELETE SET NULL`).
            store.delete_specialist(conn, specialist_id)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    _files(request).delete(specialist.slug)
    # Sessions kept in memory still carry the old link.
    request.app.state.sessions.refresh_records(session_ids)
    _changed(request, specialist_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Skill and learnings ---------------------------------------------------------------------------


@router.get("/specialists/{specialist_id}/skill")
async def get_skill(specialist_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    specialist = _get(conn, specialist_id)
    try:
        return {"text": _files(request).read_skill(specialist.slug)}
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    except UnicodeDecodeError as exc:
        raise _unprocessable(UNREADABLE_FILE) from exc


@router.put("/specialists/{specialist_id}/skill")
async def put_skill(
    specialist_id: int, body: TextIn, request: Request, conn: DbDep
) -> dict[str, str]:
    specialist = _get(conn, specialist_id)
    try:
        meta = _files(request).write_skill(specialist.slug, body.text)
    except SkillInvalidError as exc:
        raise _unprocessable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    _changed(request, specialist_id)
    return {"name": meta.name, "description": meta.description}


@router.get("/specialists/{specialist_id}/learnings")
async def get_learnings(specialist_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    specialist = _get(conn, specialist_id)
    try:
        return {"text": _files(request).read_learnings(specialist.slug)}
    except UnicodeDecodeError as exc:
        raise _unprocessable(UNREADABLE_FILE) from exc


@router.put("/specialists/{specialist_id}/learnings")
async def put_learnings(
    specialist_id: int, body: TextIn, request: Request, conn: DbDep
) -> dict[str, str]:
    specialist = _get(conn, specialist_id)
    try:
        _files(request).write_learnings(specialist.slug, body.text)
    except LearningsTooLongError as exc:
        raise _unprocessable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    _changed(request, specialist_id)
    return {"text": body.text}


# Secrets (names only come back) -------------------------------------------------------------------


@router.get("/specialists/{specialist_id}/secrets")
async def get_secrets(
    specialist_id: int, request: Request, conn: DbDep
) -> dict[str, list[str]]:
    specialist = _get(conn, specialist_id)
    return {"names": _files(request).secret_names(specialist.slug)}


@router.put("/specialists/{specialist_id}/secrets")
async def put_secrets(
    specialist_id: int, request: Request, conn: DbDep
) -> dict[str, list[str]]:
    specialist = _get(conn, specialist_id)
    # Read by hand: the validation errors of the framework quote the input back.
    try:
        body = await request.json()
    except ValueError as exc:
        raise _unprocessable(BAD_SECRETS_BODY) from exc
    values = body.get("values") if isinstance(body, dict) and set(body) == {"values"} else None
    if not isinstance(values, dict) or len(values) > MAX_SECRETS_PER_REQUEST:
        raise _unprocessable(BAD_SECRETS_BODY)
    for name, value in values.items():
        if value is not None and (not isinstance(value, str) or len(value) > MAX_SECRET_VALUE):
            # No name in the message: it is not validated yet and may be a pasted token.
            raise _unprocessable(
                f"Valor inválido para um segredo: use texto de até {MAX_SECRET_VALUE} caracteres."
            )
    files = _files(request)
    try:
        files.write_secrets(specialist.slug, values)
    except (InvalidSecretNameError, InvalidSecretValueError) as exc:
        raise _unprocessable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    # Names only: no event carries a value, nor even a name.
    _changed(request, specialist_id)
    return {"names": files.secret_names(specialist.slug)}


# Memory items, runs ---------------------------------------------------------------------------------


@router.get("/specialists/{specialist_id}/items")
async def list_items(specialist_id: int, conn: DbDep) -> list[dict[str, Any]]:
    _get(conn, specialist_id)
    return [asdict(item) for item in store.list_items(conn, specialist_id)]


@router.delete("/specialists/{specialist_id}/items", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    specialist_id: int,
    key: Annotated[str, Query(min_length=1, max_length=MAX_ITEM_KEY)],
    request: Request,
    conn: DbDep,
) -> Response:
    """The key travels in the query, as is: in the path, `..` or `%2F` could be changed
    on the way."""
    _get(conn, specialist_id)
    with db.transaction(conn):
        store.delete_item(conn, specialist_id, key)
    _changed(request, specialist_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/specialists/{specialist_id}/messages")
async def pending_messages(
    specialist_id: int, request: Request, conn: DbDep,
    session_id: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[dict[str, Any]]:
    _get(conn, specialist_id)
    try:
        return request.app.state.specialists.pending_messages(specialist_id, session_id)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/specialists/{specialist_id}/conversations")
async def list_conversations(specialist_id: int, request: Request, conn: DbDep) -> list[dict[str, Any]]:
    _get(conn, specialist_id)
    return request.app.state.specialists.conversations(specialist_id)


@router.post("/specialists/{specialist_id}/conversations", status_code=status.HTTP_201_CREATED)
async def open_conversation(
    specialist_id: int, request: Request, conn: DbDep, body: ConversationIn | None = None
) -> dict[str, Any]:
    _get(conn, specialist_id)
    from claudio_maestro.sessions import ProjectUnavailableError

    try:
        record = await request.app.state.specialists.open_conversation(
            specialist_id, session_id=body.session_id if body else None, new=body.new if body else False
        )
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except (ProjectUnavailableError, projects.ProjectNotFoundError) as exc:
        raise HTTPException(status_code=409, detail="A pasta do projeto não está disponível.") from exc
    return {"session_id": record.session_id}


@router.get("/specialists/{specialist_id}/runs")
async def list_runs(
    specialist_id: int, conn: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict[str, Any]]:
    _get(conn, specialist_id)
    return [asdict(run) for run in store.list_runs(conn, specialist_id, limit)]


@router.post("/specialists/{specialist_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_specialist(
    specialist_id: int, request: Request, conn: DbDep, body: RunIn | None = None
) -> dict[str, Any]:
    _get(conn, specialist_id)
    try:
        run = await request.app.state.specialists.start_run(
            specialist_id, trigger="manual", text=body.text if body else None
        )
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except QueueFullError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except store.SpecialistError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return asdict(run)


@router.post("/specialists/{specialist_id}/runs/{run_id}/cancel")
async def cancel_run(specialist_id: int, run_id: int, request: Request, conn: DbDep) -> dict[str, Any]:
    _get(conn, specialist_id)
    try:
        run = await request.app.state.specialists.cancel_run(specialist_id, run_id)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except store.RunNotQueuedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return asdict(run)


@router.post("/specialists/{specialist_id}/main")
async def open_main(specialist_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    """The agent's main conversation, created on first use."""
    _get(conn, specialist_id)
    try:
        session_id = await request.app.state.specialists.ensure_main(specialist_id)
    except store.SpecialistNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except (ProjectUnavailableError, InvalidDecisionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"session_id": session_id}


@router.get("/specialists/{specialist_id}/announcements")
async def list_announcements(
    specialist_id: int,
    conn: DbDep,
    pending: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """What the runs announced to the agent's main conversation, newest first."""
    _get(conn, specialist_id)
    found = (
        store.pending_announcements(conn, specialist_id)[::-1][:limit]
        if pending
        else store.list_announcements(conn, specialist_id, limit)
    )
    return [
        {key: value for key, value in asdict(announcement).items() if key != "specialist_id"}
        for announcement in found
    ]


# Notices -------------------------------------------------------------------------------------------------


@router.get("/specialist-notices")
async def list_notices(conn: DbDep, unread: bool = False) -> list[dict[str, Any]]:
    return [asdict(notice) for notice in store.list_notices(conn, unread_only=unread)]


@router.post("/specialist-notices/read")
async def read_notices(body: NoticesRead, request: Request, conn: DbDep) -> dict[str, int]:
    ids = _dedupe(body.ids)
    with db.transaction(conn):
        marks = ", ".join("?" for _ in ids)
        changing = (
            {
                row[0]
                for row in conn.execute(
                    f"SELECT id FROM specialist_notices WHERE read_at IS NULL AND id IN ({marks})",
                    ids,
                )
            }
            if ids
            else set()
        )
        updated = store.mark_notices_read(conn, ids, _now())
    if updated:
        # Not the shape of a new notice: `read_ids` (only the ones that changed) tells the
        # other screens what to mark.
        _publish(request, "specialist.notice", {"read_ids": [i for i in ids if i in changing]})
    return {"updated": updated}


# GitHub: the owner whose PR comments are accepted, and the webhook secret ---------------------------


def _github_state(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """The settings as the screen sees them. The secret is only ever written."""
    settings = request.app.state.settings
    queued = conn.execute(
        "SELECT COUNT(*) FROM specialist_pr_comments WHERE status = 'queued'"
    ).fetchone()[0]
    return {
        "login": github_hooks.get_owner(conn),
        "secret_set": github_hooks.read_secret(settings.data_dir) is not None,
        "hooks_port": settings.hooks_port,
        "queued": queued,
    }


@router.get("/specialists/github")
async def get_github(request: Request, conn: DbDep) -> dict[str, Any]:
    return _github_state(request, conn)


@router.put("/specialists/github")
async def put_github(request: Request, conn: DbDep) -> dict[str, Any]:
    # Read by hand: the validation errors of the framework quote the input back, and the
    # secret must not come back in any response.
    try:
        body = await request.json()
    except ValueError as exc:
        raise _unprocessable(BAD_GITHUB_BODY) from exc
    if not isinstance(body, dict) or not body or not set(body) <= {"login", "secret"}:
        raise _unprocessable(BAD_GITHUB_BODY)
    login, secret = body.get("login"), body.get("secret")
    if "login" in body and not (isinstance(login, str) and LOGIN_PATTERN.fullmatch(login)):
        raise _unprocessable(BAD_GITHUB_BODY)
    if "secret" in body and not (
        isinstance(secret, str)
        and SECRET_MIN <= len(secret) <= SECRET_MAX
        # The receiver reads it back trimmed: padding would never match the signature.
        and secret == secret.strip()
    ):
        raise _unprocessable(BAD_GITHUB_BODY)
    if isinstance(secret, str):
        github_hooks.write_secret(request.app.state.settings.data_dir, secret)
    if isinstance(login, str):
        with db.transaction(conn):
            github_hooks.set_owner(conn, login)
    return _github_state(request, conn)
