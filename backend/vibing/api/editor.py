"""Open a file or folder in the user's editor."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from vibing import projects
from vibing.api.deps import DbDep
from vibing.security import PathNotAllowedError, resolve_within

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

DEFAULT_EDITOR_COMMAND = ["code"]

SpawnEditor = Callable[[list[str]], Awaitable[None]]

_children: set[asyncio.Task[None]] = set()


async def spawn_detached(argv: list[str]) -> None:
    """Start the editor without a shell and without waiting for it.

    Raises FileNotFoundError / PermissionError when the command cannot start.
    The process is reaped in the background so it never lingers as a zombie.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )

    async def reap() -> None:
        with suppress(Exception):
            await process.wait()

    task = asyncio.create_task(reap())
    _children.add(task)
    task.add_done_callback(_children.discard)


class OpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)


def valid_editor_command(command: object) -> bool:
    return (
        isinstance(command, list) and bool(command)
        and all(isinstance(part, str) and part for part in command)
    )


def _editor_command(conn) -> list[str]:
    row = conn.execute("SELECT value FROM app_state WHERE key = 'preferences'").fetchone()
    try:
        prefs = json.loads(row["value"]) if row else {}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="As preferências salvas estão corrompidas.",
        ) from exc
    command = prefs.get("editor_command") if isinstance(prefs, dict) else None
    if command is None:
        return list(DEFAULT_EDITOR_COMMAND)
    if not valid_editor_command(command):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O comando do editor precisa ser uma lista de textos.",
        )
    return command


@router.post("/open-in-editor", status_code=status.HTTP_204_NO_CONTENT)
async def open_in_editor(body: OpenIn, conn: DbDep, request: Request) -> Response:
    try:
        target = resolve_within(body.path, projects.project_roots(conn))
    except PathNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O caminho precisa estar dentro de um projeto.",
        ) from exc
    if not target.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caminho não encontrado.")
    command = _editor_command(conn)
    spawn: SpawnEditor = request.app.state.spawn_editor
    try:
        await spawn([*command, str(target)])
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Comando do editor não encontrado: {command[0]}",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não foi possível abrir o editor: {exc.strerror or exc}",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
