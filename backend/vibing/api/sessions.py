"""Session routes: create, list, snapshot, send, interrupt, answer prompts."""

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from vibing import projects, sessions
from vibing.api.deps import DbDep

router = APIRouter(prefix="/api")

# Every route is async: sessions live on the event loop and must not be read
# or changed from the threadpool.


def get_session_manager(request: Request) -> sessions.SessionManager:
    return request.app.state.sessions


ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow_once", "allow_always", "deny"]


class SessionOut(BaseModel):
    session_id: str
    project_id: int
    cwd: str
    title: str
    created_at: int
    last_activity_at: int
    state: str
    error: str | None


_STATUS = {
    sessions.SessionNotFoundError: status.HTTP_404_NOT_FOUND,
    sessions.ProjectUnavailableError: status.HTTP_409_CONFLICT,
    sessions.EmptyMessageError: status.HTTP_400_BAD_REQUEST,
    sessions.PromptNotFoundError: status.HTTP_409_CONFLICT,
    sessions.AlwaysNotAvailableError: status.HTTP_400_BAD_REQUEST,
    sessions.InvalidDecisionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    sessions.SessionClosedError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def _http_error(exc: sessions.SessionError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


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
async def create_session(project_id: int, conn: DbDep, manager: ManagerDep) -> dict[str, Any]:
    project = _get_project(conn, project_id)
    try:
        record = manager.create_session(project)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    return sessions.SessionSummary(record, "closed", None).to_dict()


@router.get("/projects/{project_id}/sessions", response_model=list[SessionOut])
async def list_sessions(project_id: int, conn: DbDep, manager: ManagerDep) -> list[dict[str, Any]]:
    _get_project(conn, project_id)
    return [summary.to_dict() for summary in manager.list_for_project(project_id)]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    return _get_session(manager, session_id).snapshot()


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def send_message(session_id: str, body: MessageIn, manager: ManagerDep) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    try:
        await session.send(body.text)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    return {"state": session.state}


@router.post("/sessions/{session_id}/interrupt", status_code=status.HTTP_202_ACCEPTED)
async def interrupt(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    await session.interrupt()
    return {"state": session.state}


@router.post("/sessions/{session_id}/prompts/{prompt_id}")
async def answer_prompt(
    session_id: str, prompt_id: str, body: DecisionIn, manager: ManagerDep
) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    try:
        session.resolve_prompt(prompt_id, body.decision)
    except sessions.SessionError as exc:
        raise _http_error(exc) from exc
    return {"prompt_id": prompt_id, "decision": body.decision}
