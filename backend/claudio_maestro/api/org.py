"""Routes of the organization of agents: the agents, their `AGENT.md`, memory, secrets and
registry, conversations, wakeups and runs, routines, notices and the GitHub settings.

Everything a person types is validated here before it reaches the store or the disk, so no
request ends in a 500 from a foreign key or puts a path outside the agents folder. The slug
is checked before any access to the disk; `addDirs` entries go through the same rule the
session applies (`resolve_add_dirs`: inside a registered project, symlinks and `..`
followed), and an error never quotes a resolved path. Secrets are write-only: they are read
from the request by hand (a validation error of the framework echoes the input) and no
response or event ever carries a value.

The service and the files come from `app.state.org` (`OrgService`) and `app.state.agent_files`
(`AgentFiles`).
"""

import asyncio
import dataclasses
import re
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from claudio_maestro import db, projects
from claudio_maestro.api.deps import DbDep
from claudio_maestro.org import github_hooks, store
from claudio_maestro.org.definition import (
    AgentDefinition,
    DefinitionError,
    definition_hash,
    parse_definition,
    render_definition,
    template,
)
from claudio_maestro.org.files import (
    SLUG_MAX_LENGTH,
    SLUG_PATTERN,
    AgentFiles,
    InvalidSecretNameError,
    InvalidSecretValueError,
    MemoryTooLongError,
    SecretsFileError,
)
from claudio_maestro.org.service import (
    AddDirOutsideProjectsError,
    AgentDisabledError,
    OrgService,
    QueueFullError,
    RunNotActiveError,
    WakeupNotPendingError,
    resolve_add_dirs,
)
from claudio_maestro.sessions import ProjectUnavailableError, SessionNotFoundError

router = APIRouter(prefix="/api")

MAX_NAME = 100
MAX_RUN_TEXT = 5000
MAX_SCHEDULES = 50
MAX_SECRETS_PER_REQUEST = 50
MAX_SECRET_VALUE = 20_000
MAX_NOTICE_IDS = 500
MAX_ITEM_KEY = 1000
DAYS = "1234567"
TIME_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")

AGENT_NOT_FOUND = "Agente não encontrado."
PROJECT_NOT_FOUND = "Projeto não encontrado."
FILES_GONE = "A pasta do agente não existe mais."
DEFINITION_MISSING = "O AGENT.md do agente não foi encontrado."
DEFINITION_UNREADABLE = "Não foi possível abrir o AGENT.md do agente."
FOLDER_NOT_CREATED = "Não foi possível criar a pasta do agente."
BAD_SLUG = "O identificador deve ter letras minúsculas, números e hífens entre eles."
BUSY_TEXT = (
    "O agente está executando ou tem uma conversa com turno em andamento ou esperando você. "
    "Finalize-a antes de excluir o agente."
)
NAME_FROM_FILE = "O nome do agente vem do AGENT.md; altere o campo name: na definição."
AGENT_DISABLED = "O agente está desligado."
HASH_MISMATCH = (
    "O AGENT.md mudou desde que você o abriu. Recarregue para ver a versão atual."
)
PROJECT_UNAVAILABLE = "A pasta do projeto não está disponível."
CONVERSATION_NOT_FOUND = "Conversa não encontrada."
ROUTINE_OTHER_PROJECT = "O projeto da rotina precisa ser o mesmo do agente."
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9-]{1,39}")
SECRET_MIN, SECRET_MAX = 16, 256
BAD_GITHUB_BODY = (
    'Envie {"login": "usuario-do-github", "secret": "segredo"}, com um ou os dois campos. '
    f"O login tem até 39 letras, números ou hífens; o segredo tem de {SECRET_MIN} a {SECRET_MAX} "
    "caracteres, sem espaço no começo nem no fim."
)
BAD_SECRETS_BODY = 'Envie {"values": {"NOME": "valor" ou null}}.'

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME)]
# The length of the routine texts is checked by the store, in Portuguese.
RoutineText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20_000)]


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    # Checked by hand against `files.SLUG_PATTERN`, so the error is one sentence in Portuguese.
    slug: str = Field(max_length=200)
    project_id: int
    reports_to: int | None = None
    kind: Literal["cto", "worker"] | None = None


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Always refused (`NAME_FROM_FILE`): the name comes from the `AGENT.md`. Declared so the
    # refusal is one sentence in Portuguese and not a generic "extra field" error.
    name: Any = None
    # `null` makes the agent a top one.
    reports_to: int | None = None
    enabled: bool | None = None


class DuplicateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    slug: str = Field(max_length=200)


class DefinitionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    hash: str | None = Field(default=None, max_length=200)


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Checked by hand, so the error comes as one sentence in Portuguese.
    days: str = Field(max_length=20)
    time: str = Field(max_length=20)


class ConversationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: Annotated[str, StringConstraints(min_length=1, max_length=100)] | None = None
    new: bool = False


class WakeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_RUN_TEXT)] | None = None


class RoutineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional: it is the agent's project, and any other value is refused.
    project_id: int | None = None
    agent_id: int
    name: RoutineText
    instruction: RoutineText
    enabled: bool = True
    schedules: Annotated[list[ScheduleIn], Field(max_length=MAX_SCHEDULES)] = []


class RoutinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: RoutineText | None = None
    instruction: RoutineText | None = None
    enabled: bool | None = None
    schedules: Annotated[list[ScheduleIn], Field(max_length=MAX_SCHEDULES)] | None = None


class NoticesRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: Annotated[list[int], Field(max_length=MAX_NOTICE_IDS)]


# Helpers ----------------------------------------------------------------------------------


def _now() -> int:
    return int(time.time())


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


def _not_found(message: str = AGENT_NOT_FOUND) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


def _files(request: Request) -> AgentFiles:
    return request.app.state.agent_files


def _org(request: Request) -> OrgService:
    return request.app.state.org


def _publish(request: Request, kind: str, data: dict[str, Any]) -> None:
    request.app.state.hub.publish({"session_id": None, "seq": 0, "type": kind, "data": data})


def _changed(request: Request, agent_id: int) -> None:
    _publish(request, "agent.changed", {"id": agent_id})


def _get(conn: sqlite3.Connection, agent_id: int) -> store.Agent:
    try:
        return store.get_agent(conn, agent_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc


_slug_locks: dict[str, threading.Lock] = {}
_slug_locks_guard = threading.Lock()


def _slug_lock(slug: str) -> threading.Lock:
    """One lock per agent folder: a read-modify-write of its files (`secrets.env` is merged
    from what is on disk; `AGENT.md` is compared with the hash the screen opened) must not
    interleave with another one of the same agent."""
    with _slug_locks_guard:
        return _slug_locks.setdefault(slug, threading.Lock())


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(values))


def _check_slug(slug: str) -> None:
    if len(slug) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise _unprocessable(BAD_SLUG)


def _require_project(conn: sqlite3.Connection, project_id: int) -> projects.Project:
    try:
        return projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise _not_found(PROJECT_NOT_FOUND) from exc


def _read_definition(files: AgentFiles, slug: str) -> tuple[AgentDefinition | None, str | None]:
    """The parsed `AGENT.md`, or (None, a sentence in Portuguese) when it is missing or does
    not open. The sentence never quotes a path."""
    try:
        return files.read_definition(slug), None
    except FileNotFoundError:
        return None, DEFINITION_MISSING
    except DefinitionError as exc:
        return None, exc.message
    except (OSError, ValueError):
        return None, DEFINITION_UNREADABLE


def _schedule_out(schedule: store.Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "days": schedule.days,
        "time": schedule.time,
        "last_fired_at": schedule.last_fired_at,
    }


def _routine_out(conn: sqlite3.Connection, routine: store.Routine) -> dict[str, Any]:
    return {
        **asdict(routine),
        "schedules": [_schedule_out(s) for s in store.list_schedules(conn, routine.id)],
    }


def _agent_out(
    request: Request, conn: sqlite3.Connection, agent: store.Agent
) -> dict[str, Any]:
    definition, error = _read_definition(_files(request), agent.slug)
    runs = store.list_runs(conn, agent.id, 1)
    org = _org(request)
    return {
        "id": agent.id,
        "slug": agent.slug,
        "name": agent.name,
        "description": definition.description if definition else "",
        "project_id": agent.project_id,
        "reports_to": agent.reports_to,
        "enabled": agent.enabled,
        "model": definition.model if definition else None,
        "effort": definition.effort if definition else None,
        # Set when the file is missing or invalid (it can happen after the migration).
        "definition_error": error,
        "busy": org.is_busy(agent.id),
        "main_session_id": agent.main_session_id,
        # Announcements the main conversation has not received, plus one while it waits for
        # an answer.
        "unseen": org.unseen(agent.id),
        "last_run": asdict(runs[0]) if runs else None,
    }


def _one(request: Request, conn: sqlite3.Connection, agent_id: int) -> dict[str, Any]:
    return _agent_out(request, conn, store.get_agent(conn, agent_id))


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


def _create_agent(
    request: Request,
    conn: sqlite3.Connection,
    *,
    name: str,
    slug: str,
    project_id: int,
    reports_to: int | None,
    text: str,
) -> store.Agent:
    """The row and the folder together: when the folder cannot be made, the row goes too.
    Check, row and hash are written in one transaction."""
    files = _files(request)
    created = False
    try:
        with db.transaction(conn):
            _require_project(conn, project_id)
            agent = store.create_agent(
                conn, slug=slug, name=name, project_id=project_id, reports_to=reports_to,
                now=_now(),
            )
            try:
                files.create(slug, text)
            except FileExistsError as exc:
                raise _conflict(f"Já existe uma pasta para o identificador “{slug}”.") from exc
            created = True
            agent = store.update_agent(
                conn, agent.id, now=_now(), definition_hash=definition_hash(text)
            )
    except store.DuplicateSlugError as exc:
        raise _conflict(str(exc)) from exc
    except (store.ReportsToCycleError, store.ReportsToOtherProjectError, store.NotFoundError) as exc:
        raise _unprocessable(str(exc)) from exc
    except DefinitionError as exc:
        raise _unprocessable(exc.message) from exc
    except OSError as exc:
        if created:
            files.delete(slug)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=FOLDER_NOT_CREATED
        ) from exc
    except BaseException:
        if created:
            files.delete(slug)
        raise
    return agent


# Agents -------------------------------------------------------------------------------------


@router.get("/agents")
async def list_agents(
    request: Request, conn: DbDep, project_id: int | None = None
) -> list[dict[str, Any]]:
    return [_agent_out(request, conn, a) for a in store.list_agents(conn, project_id)]


@router.post("/agents", status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentCreate, request: Request, conn: DbDep) -> dict[str, Any]:
    _check_slug(body.slug)
    agent = _create_agent(
        request, conn, name=body.name, slug=body.slug, project_id=body.project_id,
        reports_to=body.reports_to, text=template(body.name, body.kind or "worker"),
    )
    _changed(request, agent.id)
    return _one(request, conn, agent.id)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: int, request: Request, conn: DbDep) -> dict[str, Any]:
    _get(conn, agent_id)
    return _one(request, conn, agent_id)


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: int, body: AgentPatch, request: Request, conn: DbDep
) -> dict[str, Any]:
    if "name" in body.model_fields_set:
        raise _unprocessable(NAME_FROM_FILE)
    given = {name: getattr(body, name) for name in body.model_fields_set}
    for name, value in given.items():
        if value is None and name != "reports_to":
            raise _unprocessable(f"O campo “{name}” não aceita valor nulo.")
    try:
        # The cycle and project checks and the write are one transaction.
        with db.transaction(conn):
            _get(conn, agent_id)
            if given:
                store.update_agent(conn, agent_id, now=_now(), **given)
    except (store.ReportsToCycleError, store.ReportsToOtherProjectError, store.NotFoundError) as exc:
        raise _unprocessable(str(exc)) from exc
    _changed(request, agent_id)
    if given.get("enabled") is True:
        # What waited while the agent was off is served now.
        _org(request).kick(agent_id)
    return _one(request, conn, agent_id)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: int, request: Request, conn: DbDep) -> Response:
    agent = _get(conn, agent_id)
    if _org(request).is_busy(agent_id):
        raise _conflict(BUSY_TEXT)
    sessions = request.app.state.sessions
    session_ids = {
        row[0]
        for row in conn.execute("SELECT session_id FROM sessions WHERE agent_id = ?", (agent_id,))
    }
    for session_id in sessions.active_ids():
        try:
            session = sessions.get(session_id)
        except SessionNotFoundError:
            continue
        if session.record.agent_id == agent_id and session.client is not None:
            await session.close()
    try:
        with db.transaction(conn):
            # Holding the write lock no run can be claimed any more: look again, because one
            # may have started while the sessions were being closed.
            if _org(request).is_busy(agent_id):
                raise _conflict(BUSY_TEXT)
            # The sessions stay: the schema unlinks them (`ON DELETE SET NULL`).
            store.delete_agent(conn, agent_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    _files(request).delete(agent.slug)
    # Sessions kept in memory still carry the old link.
    sessions.refresh_records(session_ids)
    _changed(request, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/agents/{agent_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_agent(
    agent_id: int, body: DuplicateIn, request: Request, conn: DbDep
) -> dict[str, Any]:
    """Another agent with the same `AGENT.md` and nothing else: no memory, no secrets, no
    boss, and no `addDirs` (they were folders of the other project)."""
    source = _get(conn, agent_id)
    _check_slug(body.slug)
    definition, error = _read_definition(_files(request), source.slug)
    if definition is None:
        raise _unprocessable(error or DEFINITION_UNREADABLE)
    text = render_definition(dataclasses.replace(definition, add_dirs=[]))
    agent = _create_agent(
        request, conn, name=definition.name, slug=body.slug, project_id=body.project_id,
        reports_to=None, text=text,
    )
    _changed(request, agent.id)
    return _one(request, conn, agent.id)


# AGENT.md -----------------------------------------------------------------------------------


def _definition_response(exc: DefinitionError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": exc.message, "field": exc.field, "line": exc.line},
    )


def _add_dirs_line(text: str) -> int | None:
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("addDirs"):
            return number
    return None


@router.get("/agents/{agent_id}/definition")
async def get_definition(agent_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    agent = _get(conn, agent_id)
    try:
        text = _files(request).read_definition_text(agent.slug)
    except FileNotFoundError as exc:
        raise _not_found(DEFINITION_MISSING) from exc
    except DefinitionError as exc:
        raise _unprocessable(exc.message) from exc
    except (OSError, ValueError) as exc:
        raise _unprocessable(DEFINITION_UNREADABLE) from exc
    return {"text": text, "hash": definition_hash(text)}


def _save_definition(
    files: AgentFiles,
    conn: sqlite3.Connection,
    agent_id: int,
    slug: str,
    definition: AgentDefinition,
    text: str,
    expected_hash: str | None,
) -> str:
    """Compare the hash, write the file and the row of the table (name and hash) under the
    lock of the agent, so two saves never leave the file of one and the hash of the other."""
    with _slug_lock(slug):
        if expected_hash is not None:
            try:
                current: str | None = definition_hash(files.read_definition_text(slug))
            except FileNotFoundError:
                raise  # gone: 404, as without a hash
            except (OSError, ValueError):
                current = None
            if current != expected_hash:
                raise _conflict(HASH_MISMATCH)
        files.write_definition(slug, text)
        new_hash = definition_hash(text)
        with db.transaction(conn):
            # The file rules: the name the screens list follows the one in the header.
            store.update_agent(
                conn, agent_id, now=_now(), name=definition.name, definition_hash=new_hash
            )
    return new_hash


@router.put("/agents/{agent_id}/definition", response_model=None)
async def put_definition(
    agent_id: int, body: DefinitionIn, request: Request, conn: DbDep
) -> dict[str, str] | JSONResponse:
    agent = _get(conn, agent_id)
    try:
        definition = parse_definition(body.text)
    except DefinitionError as exc:
        return _definition_response(exc)
    project = _require_project(conn, agent.project_id)
    try:
        resolve_add_dirs(
            definition.add_dirs, projects.project_roots(conn), Path(project.path)
        )
    except AddDirOutsideProjectsError as exc:
        # The entry is what the person wrote; the resolved path is not quoted.
        return _definition_response(
            DefinitionError(str(exc), field="addDirs", line=_add_dirs_line(body.text))
        )
    files = _files(request)
    try:
        new_hash = await asyncio.to_thread(
            _save_definition, files, conn, agent_id, agent.slug, definition, body.text, body.hash
        )
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    except store.NotFoundError as exc:  # deleted while it was being saved
        raise _not_found(str(exc)) from exc
    except DefinitionError as exc:
        return _definition_response(exc)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DEFINITION_UNREADABLE
        ) from exc
    _changed(request, agent_id)
    return {"text": body.text, "hash": new_hash}


# Memory and secrets -------------------------------------------------------------------------


@router.get("/agents/{agent_id}/memory")
async def get_memory(agent_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    agent = _get(conn, agent_id)
    try:
        return {"text": _files(request).read_memory(agent.slug)}
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc


@router.put("/agents/{agent_id}/memory")
async def put_memory(
    agent_id: int, body: TextIn, request: Request, conn: DbDep
) -> dict[str, str]:
    agent = _get(conn, agent_id)
    try:
        _files(request).write_memory(agent.slug, body.text)
    except MemoryTooLongError as exc:
        raise _unprocessable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    _changed(request, agent_id)
    return {"text": body.text}


@router.get("/agents/{agent_id}/secrets")
async def get_secrets(agent_id: int, request: Request, conn: DbDep) -> dict[str, list[str]]:
    agent = _get(conn, agent_id)
    try:
        return {"names": _files(request).secret_names(agent.slug)}
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc


def _write_secrets(files: AgentFiles, slug: str, values: dict[str, str | None]) -> list[str]:
    # `write_secrets` reads what is on disk, merges and writes: one at a time per agent.
    with _slug_lock(slug):
        files.write_secrets(slug, values)
        return files.secret_names(slug)


@router.put("/agents/{agent_id}/secrets")
async def put_secrets(agent_id: int, request: Request, conn: DbDep) -> dict[str, list[str]]:
    agent = _get(conn, agent_id)
    # Read by hand: the validation errors of the framework quote the input back.
    try:
        body = await request.json()
    except ValueError as exc:
        raise _unprocessable(BAD_SECRETS_BODY) from exc
    values = body.get("values") if isinstance(body, dict) and set(body) == {"values"} else None
    if not isinstance(values, dict) or len(values) > MAX_SECRETS_PER_REQUEST:
        raise _unprocessable(BAD_SECRETS_BODY)
    for value in values.values():
        if value is not None and (not isinstance(value, str) or len(value) > MAX_SECRET_VALUE):
            # No name in the message: it is not validated yet and may be a pasted token.
            raise _unprocessable(
                f"Valor inválido para um segredo: use texto de até {MAX_SECRET_VALUE} caracteres."
            )
    try:
        names = await asyncio.to_thread(_write_secrets, _files(request), agent.slug, values)
    except (InvalidSecretNameError, InvalidSecretValueError, SecretsFileError) as exc:
        raise _unprocessable(str(exc)) from exc
    except FileNotFoundError as exc:
        raise _not_found(FILES_GONE) from exc
    # Names only: no event carries a value, nor even a name.
    _changed(request, agent_id)
    return {"names": names}


# Registry -----------------------------------------------------------------------------------


@router.get("/agents/{agent_id}/registry")
async def list_registry(agent_id: int, conn: DbDep) -> list[dict[str, Any]]:
    _get(conn, agent_id)
    return [asdict(item) for item in store.list_items(conn, agent_id)]


@router.delete("/agents/{agent_id}/registry", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registry_item(
    agent_id: int,
    key: Annotated[str, Query(min_length=1, max_length=MAX_ITEM_KEY)],
    request: Request,
    conn: DbDep,
) -> Response:
    """The key travels in the query, as is: in the path, `..` or `%2F` could be changed on
    the way."""
    _get(conn, agent_id)
    with db.transaction(conn):
        store.delete_item(conn, agent_id, key)
    _changed(request, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Conversations ------------------------------------------------------------------------------


@router.get("/agents/{agent_id}/conversations")
async def list_conversations(
    agent_id: int, request: Request, conn: DbDep
) -> list[dict[str, Any]]:
    _get(conn, agent_id)
    return _org(request).conversations(agent_id)


@router.post("/agents/{agent_id}/conversations", status_code=status.HTTP_201_CREATED)
async def open_conversation(
    agent_id: int, request: Request, conn: DbDep, body: ConversationIn | None = None
) -> dict[str, str]:
    _get(conn, agent_id)
    try:
        record = await _org(request).open_conversation(
            agent_id,
            session_id=body.session_id if body else None,
            new=body.new if body else False,
        )
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except ProjectUnavailableError as exc:
        raise _conflict(str(exc)) from exc
    except projects.ProjectNotFoundError as exc:
        raise _conflict(PROJECT_UNAVAILABLE) from exc
    return {"session_id": record.session_id}


@router.post("/agents/{agent_id}/main")
async def open_main(agent_id: int, request: Request, conn: DbDep) -> dict[str, str]:
    """The agent's main conversation, created on first use."""
    _get(conn, agent_id)
    try:
        session_id = await _org(request).ensure_main(agent_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except ProjectUnavailableError as exc:
        raise _conflict(str(exc)) from exc
    return {"session_id": session_id}


@router.get("/agents/{agent_id}/messages")
async def pending_messages(
    agent_id: int,
    request: Request,
    conn: DbDep,
    session_id: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[dict[str, Any]]:
    """Messages queued for a conversation of the agent, waiting for a run to end."""
    agent = _get(conn, agent_id)
    owner = conn.execute(
        "SELECT agent_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if owner is None or owner["agent_id"] != agent_id:
        raise _not_found(CONVERSATION_NOT_FOUND)
    files = _files(request)
    result = []
    for wakeup in store.pending_wakeups(conn, agent_id):
        if wakeup.source != "message":
            continue
        target = (wakeup.payload or {}).get("session_id") or agent.main_session_id
        if target != session_id:
            continue
        try:
            preview = files.wake_preview(agent.slug, wakeup.id)
        except (OSError, ValueError):
            preview = "Mensagem indisponível."
        result.append({"id": wakeup.id, "text": preview})
    return result


@router.get("/agents/{agent_id}/announcements")
async def list_announcements(
    agent_id: int,
    conn: DbDep,
    pending: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """What the runs announced to the agent's main conversation, newest first."""
    _get(conn, agent_id)
    found = (
        store.pending_announcements(conn, agent_id)[::-1][:limit]
        if pending
        else store.list_announcements(conn, agent_id, limit)
    )
    return [
        {key: value for key, value in asdict(a).items() if key != "agent_id"} for a in found
    ]


# Runs and wakeups ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/runs")
async def list_runs(
    agent_id: int, conn: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[dict[str, Any]]:
    _get(conn, agent_id)
    return [asdict(run) for run in store.list_runs(conn, agent_id, limit)]


async def _wake(
    request: Request, agent_id: int, *, text: str | None, routine_id: int | None = None
) -> dict[str, Any]:
    try:
        wakeup = await _org(request).wake(
            agent_id, source="manual", text=text, routine_id=routine_id
        )
    except AgentDisabledError as exc:
        # The wakeup stays pending (`GET /wakeups`) until the agent is turned on.
        raise _conflict(AGENT_DISABLED) from exc
    except QueueFullError as exc:
        raise _conflict(str(exc)) from exc
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except store.OrgError as exc:
        raise _unprocessable(str(exc)) from exc
    return asdict(wakeup)


@router.post("/agents/{agent_id}/wake", status_code=status.HTTP_202_ACCEPTED)
async def wake_agent(
    agent_id: int, request: Request, conn: DbDep, body: WakeIn | None = None
) -> dict[str, Any]:
    _get(conn, agent_id)
    return await _wake(request, agent_id, text=body.text if body else None)


@router.get("/agents/{agent_id}/wakeups")
async def list_wakeups(agent_id: int, request: Request, conn: DbDep) -> list[dict[str, Any]]:
    """The queue: what waits for the agent, in the order it will be served."""
    agent = _get(conn, agent_id)
    files = _files(request)
    result = []
    for wakeup in store.pending_wakeups(conn, agent_id):
        try:
            preview = files.wake_preview(agent.slug, wakeup.id)
        except (OSError, ValueError):
            preview = ""
        result.append({**asdict(wakeup), "text": preview})
    return result


@router.post("/agents/{agent_id}/wakeups/{wakeup_id}/cancel")
async def cancel_wakeup(
    agent_id: int, wakeup_id: int, request: Request, conn: DbDep
) -> dict[str, Any]:
    _get(conn, agent_id)
    try:
        await _org(request).cancel_wakeup(agent_id, wakeup_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except WakeupNotPendingError as exc:
        raise _conflict(str(exc)) from exc
    return {"id": wakeup_id, "state": "dropped"}


@router.post("/agents/{agent_id}/runs/{run_id}/cancel")
async def cancel_run(
    agent_id: int, run_id: int, request: Request, conn: DbDep
) -> dict[str, Any]:
    _get(conn, agent_id)
    try:
        run = await _org(request).cancel_run(agent_id, run_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except RunNotActiveError as exc:
        raise _conflict(str(exc)) from exc
    return asdict(run)


# Routines -----------------------------------------------------------------------------------


@router.get("/routines")
async def list_routines(conn: DbDep, project_id: int | None = None) -> list[dict[str, Any]]:
    return [_routine_out(conn, r) for r in store.list_routines(conn, project_id)]


@router.post("/routines", status_code=status.HTTP_201_CREATED)
async def create_routine(body: RoutineCreate, request: Request, conn: DbDep) -> dict[str, Any]:
    schedules = _clean_schedules(body.schedules)
    try:
        with db.transaction(conn):
            agent = _get(conn, body.agent_id)
            if body.project_id is not None and body.project_id != agent.project_id:
                raise _unprocessable(ROUTINE_OTHER_PROJECT)
            routine = store.create_routine(
                conn, project_id=agent.project_id, agent_id=agent.id, name=body.name,
                instruction=body.instruction, enabled=body.enabled, now=_now(),
            )
            store.replace_schedules(conn, routine.id, schedules, _now())
    except store.OrgError as exc:
        raise _unprocessable(str(exc)) from exc
    _changed(request, agent.id)
    return _routine_out(conn, routine)


@router.patch("/routines/{routine_id}")
async def update_routine(
    routine_id: int, body: RoutinePatch, request: Request, conn: DbDep
) -> dict[str, Any]:
    given = {name: getattr(body, name) for name in body.model_fields_set}
    for name, value in given.items():
        if value is None:
            raise _unprocessable(f"O campo “{name}” não aceita valor nulo.")
    schedules = _clean_schedules(given.pop("schedules")) if "schedules" in given else None
    try:
        with db.transaction(conn):
            routine = store.get_routine(conn, routine_id)
            if given:
                routine = store.update_routine(conn, routine_id, now=_now(), **given)
            if schedules is not None:
                store.replace_schedules(conn, routine_id, schedules, _now())
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except store.OrgError as exc:
        raise _unprocessable(str(exc)) from exc
    _changed(request, routine.agent_id)
    return _routine_out(conn, routine)


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(routine_id: int, request: Request, conn: DbDep) -> Response:
    try:
        with db.transaction(conn):
            routine = store.get_routine(conn, routine_id)
            store.delete_routine(conn, routine_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    _changed(request, routine.agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/routines/{routine_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_routine(routine_id: int, request: Request, conn: DbDep) -> dict[str, Any]:
    """"Run now": a manual wakeup with the instruction of the routine."""
    try:
        routine = store.get_routine(conn, routine_id)
    except store.NotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return await _wake(request, routine.agent_id, text=None, routine_id=routine.id)


# Notices ------------------------------------------------------------------------------------


@router.get("/agent-notices")
async def list_notices(conn: DbDep, unread: bool = False) -> list[dict[str, Any]]:
    return [asdict(notice) for notice in store.list_notices(conn, unread_only=unread)]


@router.post("/agent-notices/read")
async def read_notices(body: NoticesRead, request: Request, conn: DbDep) -> dict[str, int]:
    ids = _dedupe(body.ids)
    with db.transaction(conn):
        marks = ", ".join("?" for _ in ids)
        changing = (
            {
                row[0]
                for row in conn.execute(
                    f"SELECT id FROM notices WHERE read_at IS NULL AND id IN ({marks})", ids
                )
            }
            if ids
            else set()
        )
        updated = store.mark_notices_read(conn, ids, _now())
    if updated:
        # Not the shape of a new notice: `read_ids` (only the ones that changed) tells the
        # other screens what to mark.
        _publish(request, "agent.notice", {"read_ids": [i for i in ids if i in changing]})
    return {"updated": updated}


# GitHub: the owner whose PR comments are accepted, and the webhook secret -------------------


def _github_state(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    """The settings as the screen sees them. The secret is only ever written."""
    settings = request.app.state.settings
    queued = conn.execute(
        "SELECT COUNT(*) FROM agent_pr_comments WHERE status = 'queued'"
    ).fetchone()[0]
    return {
        "login": github_hooks.get_owner(conn),
        "secret_set": github_hooks.read_secret(settings.data_dir) is not None,
        "hooks_port": settings.hooks_port,
        "queued": queued,
    }


@router.get("/agents-github")
async def get_github(request: Request, conn: DbDep) -> dict[str, Any]:
    return _github_state(request, conn)


@router.put("/agents-github")
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
