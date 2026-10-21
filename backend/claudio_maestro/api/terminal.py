"""Terminal of a session: the WebSocket that carries the shell, the play button's run and the kill.

The browser never sends a path: the folder comes from the session id and has to be inside a
registered project (or a proven linked worktree of one). Host and Origin of the WebSocket are
checked by `HostOriginMiddleware`, like every other socket of the app.
"""

import asyncio
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, status
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from starlette.websockets import WebSocketDisconnect

from claudio_maestro import sessions
from claudio_maestro.api.sessions import ManagerDep
from claudio_maestro.projectpath import resolve_project_path
from claudio_maestro.security import PathNotAllowedError
from claudio_maestro.terminal import (
    Terminal,
    TerminalBusyError,
    TerminalManager,
    TerminalStartError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

COLS_RANGE = (2, 500)
ROWS_RANGE = (1, 200)
COMMAND_MAX_LENGTH = 20_000

# Close codes of the terminal WebSocket (the 4000 range belongs to the application).
CLOSE_NOT_FOUND = 4404
CLOSE_FOLDER_UNAVAILABLE = 4409
CLOSE_START_FAILED = 4500


class SessionFolderError(Exception):
    """The folder of the session is gone or is not inside a project."""


async def session_terminal_dir(manager: sessions.SessionManager, session_id: str) -> Path:
    """The folder where the shell of the session runs.

    Raises `SessionNotFoundError` for an unknown session and `SessionFolderError` when the
    folder does not exist (anymore) or is outside the registered projects.
    """
    record = manager.find_record(session_id)
    try:
        folder = await resolve_project_path(record.work_dir(), manager.project_roots())
    except PathNotAllowedError as exc:
        raise SessionFolderError(str(exc)) from exc
    if not folder.is_dir():
        raise SessionFolderError("A pasta da sessão não existe mais.")
    return folder


def _terminals(request: Request) -> TerminalManager:
    return request.app.state.terminals


# WebSocket -------------------------------------------------------------------


def _in_range(value: Any, bounds: tuple[int, int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and bounds[0] <= value <= bounds[1]


def _apply_client_frame(terminal: Terminal, raw: str) -> None:
    """Write what the browser typed or resize the PTY. Anything malformed is ignored."""
    try:
        frame = json.loads(raw)
        if not isinstance(frame, dict):
            return
        kind = frame.get("type")
        if kind == "input":
            data = frame.get("data")
            if isinstance(data, str) and data:
                terminal.write(data)
        elif kind == "resize":
            cols, rows = frame.get("cols"), frame.get("rows")
            if _in_range(cols, COLS_RANGE) and _in_range(rows, ROWS_RANGE):
                terminal.resize(cols, rows)
    except Exception:
        # No frame, however odd, may take the connection down.
        logger.exception("Could not handle a frame of the terminal of session %s", terminal.session_id)


async def _pump_output(websocket: WebSocket, queue: "asyncio.Queue[dict[str, Any]]") -> None:
    """Forward the frames of the terminal to the browser until the shell is gone."""
    while True:
        frame = await queue.get()
        await websocket.send_json(frame)
        if frame.get("type") == "exit":
            return


async def _read_input(websocket: WebSocket, terminal: Terminal) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if text is not None:
            _apply_client_frame(terminal, text)


async def _refuse(websocket: WebSocket, code: int) -> None:
    """Close with an application code. The handshake is accepted first: a close before the
    accept becomes an HTTP 403 under uvicorn and the browser would only see code 1006."""
    await websocket.accept()
    await websocket.close(code=code)


@router.websocket("/ws/terminal/{session_id}")
async def terminal_socket(websocket: WebSocket, session_id: str) -> None:
    app = websocket.app
    try:
        folder = await session_terminal_dir(app.state.sessions, session_id)
    except sessions.SessionNotFoundError:
        await _refuse(websocket, CLOSE_NOT_FOUND)
        return
    except SessionFolderError:
        await _refuse(websocket, CLOSE_FOLDER_UNAVAILABLE)
        return
    try:
        terminal = await app.state.terminals.open(session_id, folder)
    except TerminalStartError:
        logger.exception("Could not open the terminal of session %s", session_id)
        await _refuse(websocket, CLOSE_START_FAILED)
        return

    await websocket.accept()
    # No `await` between the replay and the subscription, or output is lost or repeated.
    replay = terminal.replay()
    queue = terminal.subscribe()
    cols, rows = terminal.cols, terminal.rows
    # It may have closed while the handshake was accepted, before we subscribed: then no `exit`
    # frame would ever come through the queue.
    already_closed = terminal.closed
    pump = reader = None
    try:
        await websocket.send_json({"type": "replay", "data": replay, "cols": cols, "rows": rows})
        if already_closed:
            await websocket.send_json({"type": "exit"})
            return
        pump = asyncio.ensure_future(_pump_output(websocket, queue))
        reader = asyncio.ensure_future(_read_input(websocket, terminal))
        await asyncio.wait({pump, reader}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        # Leaving only drops this subscriber: the shell goes on for the next one.
        terminal.unsubscribe(queue)
        for task in (pump, reader):
            if task is not None:
                task.cancel()
        for task in (pump, reader):
            if task is not None:
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task
        with suppress(RuntimeError, WebSocketDisconnect, OSError):
            await websocket.close()


# HTTP ------------------------------------------------------------------------


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Annotated[str, StringConstraints(min_length=1, max_length=COMMAND_MAX_LENGTH)]

    @field_validator("command")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("O comando está vazio.")
        return value


class RunOut(BaseModel):
    run_id: str


@router.post(
    "/api/sessions/{session_id}/terminal/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunOut,
)
async def run_command(
    session_id: str, body: RunIn, request: Request, manager: ManagerDep
) -> dict[str, str]:
    """Paste the command of a code block into the terminal of the session (the play button)."""
    try:
        folder = await session_terminal_dir(manager, session_id)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SessionFolderError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A pasta da sessão não existe mais."
        ) from exc
    try:
        run_id = await _terminals(request).run(session_id, folder, body.command)
    except TerminalBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="O terminal está ocupado."
        ) from exc
    except TerminalStartError as exc:
        logger.warning("Terminal of session %s did not open: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="O terminal não abriu."
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"run_id": run_id}


@router.delete(
    "/api/sessions/{session_id}/terminal", status_code=status.HTTP_204_NO_CONTENT
)
async def close_terminal(session_id: str, request: Request, manager: ManagerDep) -> Response:
    """Close the terminal of the session, with whatever runs in it."""
    try:
        manager.find_record(session_id)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await _terminals(request).kill(session_id, interrupted=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
