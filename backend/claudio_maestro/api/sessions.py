"""Session routes: create, list, snapshot, send, interrupt, stop subagents, answer prompts."""

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from claudio_maestro import groups, projects, sessions
from claudio_maestro.api.deps import DbDep

router = APIRouter(prefix="/api")

# Every route is async: sessions live on the event loop and must not be read
# or changed from the threadpool.


def get_session_manager(request: Request) -> sessions.SessionManager:
    return request.app.state.sessions


ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]


class ImageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: str
    data: str  # base64


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    images: list[ImageIn] = []


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow_once", "allow_always", "deny", "answer", "approve", "reject"]
    # answer: {"<question text>": "<label>" or ["<label>", ...] for multiSelect}
    answers: dict[str, str | list[str]] | None = None
    # reject (plan): what the model should change
    message: Annotated[str, StringConstraints(max_length=20_000)] | None = None


class ContextOut(BaseModel):
    used_tokens: int
    max_tokens: int
    percent: float


class PendingPermissionOut(BaseModel):
    prompt_id: str
    tool_name: str
    summary: str
    can_allow_always: bool


class PlanCurrentOut(BaseModel):
    number: int
    title: str


class PlanOut(BaseModel):
    path: str
    title: str
    total: int
    done: int
    # First task not done; None when the plan is complete.
    current: PlanCurrentOut | None = None


class SessionOut(BaseModel):
    session_id: str
    project_id: int
    cwd: str
    title: str
    created_at: int
    last_activity_at: int
    last_seen_at: int | None
    finished: bool
    state: str
    error: str | None
    seq: int
    display_state: Literal["running", "waiting", "finished"]
    unread: bool
    awaiting_decision: bool
    summary: str | None = None
    first_prompt: str | None = None
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None
    effort_pending: bool = False
    model_resolved: str | None = None
    # Context window usage; None when unknown.
    context: ContextOut | None = None
    # Oldest pending tool permission (answered by POST /sessions/{id}/prompts/{prompt_id}).
    pending_permission: PendingPermissionOut | None = None
    # When the user finished the session; None when open or finished by inactivity.
    finished_at: int | None = None
    # Last tool of the main conversation ("Edit sessions.py"); None after a restart.
    last_action: str | None = None
    # Kind of the oldest pending prompt.
    pending_kind: Literal["tool", "question", "plan"] | None = None
    # Progress of the plan the conversation executes, from the memory cache; None
    # without a plan, with an unreadable one or before its first reading.
    plan: PlanOut | None = None
    # True only for a session without a client (`closed`) whose CLI is in the middle of
    # a turn (last main-chain entry left it open and something was written in the last
    # 20 minutes). Always False for sessions the app is connected to.
    cli_running: bool = False
    # True for a session with a client whose subagent or background Bash has not
    # finished after the main turn ended; it then shows as running.
    subagents_running: bool = False
    # Group of related sessions in the project; None when loose.
    group_id: int | None = None
    # Linked worktree the session works in (None outside worktrees) and the newest
    # branch of its transcript.
    worktree_name: str | None = None
    worktree_path: str | None = None
    git_branch: str | None = None
    # Short sentence of the digest agent's summary; None before the first reading.
    digest_short: str | None = None
    # The digest agent marked the linked plan as completed.
    plan_done: bool = False
    # A turn was running when the app stopped and the session has no client now.
    interrupted: bool = False
    # What the user plans to do with the session; None when unmarked.
    mark: Literal["on_hold", "blocked", "review"] | None = None
    mark_note: str | None = None
    # When a session on hold wakes up (seconds); None without a date.
    mark_until: int | None = None
    priority: bool = False


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class SessionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finished: bool | None = None
    title: Title | None = None
    model: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._\[\]-]{1,100}$")
    ] | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    permission_mode: Literal[
        "default", "acceptEdits", "plan", "bypassPermissions", "auto", "dontAsk"
    ] | None = None
    confirm_bypass: bool = False
    group_id: int | None = None
    # Plain strings: `resolve_mark` validates both and answers in Portuguese.
    mark: str | None = None
    mark_note: Annotated[str, StringConstraints(strip_whitespace=True)] | None = None
    mark_until: int | None = None
    priority: bool | None = None


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: int | None = None


class SeenManyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ids: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=100)]],
        Field(max_length=500),
    ]


_STATUS = {
    sessions.SessionNotFoundError: status.HTTP_404_NOT_FOUND,
    sessions.ProjectUnavailableError: status.HTTP_409_CONFLICT,
    sessions.EmptyMessageError: status.HTTP_400_BAD_REQUEST,
    sessions.PromptNotFoundError: status.HTTP_409_CONFLICT,
    sessions.AlwaysNotAvailableError: status.HTTP_400_BAD_REQUEST,
    sessions.InvalidDecisionError: status.HTTP_400_BAD_REQUEST,
    sessions.BypassNotConfirmedError: status.HTTP_400_BAD_REQUEST,
    sessions.InvalidAnswerError: status.HTTP_400_BAD_REQUEST,
    sessions.RejectMessageRequiredError: status.HTTP_400_BAD_REQUEST,
    sessions.InvalidImageError: status.HTTP_400_BAD_REQUEST,
    sessions.InvalidMarkError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    sessions.ContinuedElsewhereError: status.HTTP_409_CONFLICT,
    sessions.SessionClosedError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _http_error(exc: sessions.SessionError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


_GROUP_STATUS = {
    groups.GroupNotFoundError: status.HTTP_404_NOT_FOUND,
    groups.InvalidGroupNameError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    groups.DuplicateGroupNameError: status.HTTP_409_CONFLICT,
    groups.GroupProjectMismatchError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def group_http_error(exc: groups.GroupError) -> HTTPException:
    return HTTPException(status_code=_GROUP_STATUS[type(exc)], detail=str(exc))


def _get_session(manager: sessions.SessionManager, session_id: str) -> sessions.ActiveSession:
    try:
        return manager.get(session_id)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc


def _get_project(conn: sqlite3.Connection, project_id: int) -> projects.Project:
    try:
        return projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    project_id: int,
    conn: DbDep,
    manager: ManagerDep,
    body: Annotated[SessionCreate | None, Body()] = None,
) -> dict[str, Any]:
    project = _get_project(conn, project_id)
    try:
        record = manager.create_session(project, group_id=body.group_id if body else None)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    return manager.describe_record(record)


@router.get("/projects/{project_id}/sessions", response_model=list[SessionOut])
async def list_sessions(project_id: int, conn: DbDep, manager: ManagerDep) -> list[dict[str, Any]]:
    _get_project(conn, project_id)
    return manager.list_sessions(project_id=project_id)


@router.get("/sessions", response_model=list[SessionOut])
async def list_all_sessions(
    manager: ManagerDep,
    project_id: int | None = None,
    state: Literal["running", "waiting", "finished"] | None = None,
) -> list[dict[str, Any]]:
    return manager.list_sessions(project_id=project_id, display_state=state)


@router.get("/sessions/search", response_model=list[SessionOut])
async def search_sessions(
    manager: ManagerDep,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return manager.search(q, limit)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str, body: SessionPatch, manager: ManagerDep
) -> dict[str, Any]:
    try:
        return await manager.update(
            session_id,
            finished=body.finished,
            title=body.title,
            model=body.model,
            effort=body.effort,
            permission_mode=body.permission_mode,
            confirm_bypass=body.confirm_bypass,
            group_id=body.group_id if "group_id" in body.model_fields_set else ...,
            mark=body.mark if "mark" in body.model_fields_set else ...,
            mark_note=body.mark_note if "mark_note" in body.model_fields_set else ...,
            mark_until=body.mark_until if "mark_until" in body.model_fields_set else ...,
            priority=body.priority,
        )
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc


@router.post("/sessions/seen")
async def mark_many_seen(body: SeenManyIn, manager: ManagerDep) -> dict[str, int]:
    return {"updated": await manager.mark_seen_many(body.session_ids)}


@router.post("/sessions/{session_id}/seen", response_model=SessionOut)
async def mark_seen(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    try:
        return await manager.mark_seen(session_id)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc


@router.get("/models")
async def list_models(manager: ManagerDep) -> list[dict[str, Any]]:
    """Models of the SDK (cached after the first connected session), or a fixed list."""
    return manager.list_models()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    """Snapshot. An old session gets its saved conversation loaded, without a client."""
    _get_session(manager, session_id)
    return await manager.open(session_id)


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: MessageIn, manager: ManagerDep) -> dict[str, Any]:
    _get_session(manager, session_id)
    try:
        return await manager.send(
            session_id, body.text, [image.model_dump() for image in body.images]
        )
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc


@router.post("/sessions/{session_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    await session.interrupt()
    return {"state": session.state}


@router.post("/sessions/{session_id}/subagents/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_subagents(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    """Stop the running subagents, during a turn or not, without interrupting the turn."""
    session = _get_session(manager, session_id)
    await session.stop_subagents()
    return {"state": session.state}


@router.post("/sessions/{session_id}/prompts/{prompt_id}")
async def answer_prompt(
    session_id: str, prompt_id: str, body: DecisionIn, manager: ManagerDep
) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    try:
        session.resolve_prompt(
            prompt_id, body.decision, answers=body.answers, message=body.message
        )
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    return {"prompt_id": prompt_id, "decision": body.decision}
