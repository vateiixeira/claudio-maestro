"""Open a file or folder in the user's editor."""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from claudio_maestro import gitinfo, projects
from claudio_maestro.api.deps import DbDep
from claudio_maestro.security import PathNotAllowedError, resolve_within

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


async def _worktree_file(raw: str, roots: list[Path]) -> Path | None:
    """The resolved `raw` (absolute) when it stays inside a proven linked worktree."""
    if not raw or "\x00" in raw or not os.path.isabs(raw):
        return None
    target = Path(os.path.realpath(raw))
    found = await gitinfo.project_worktree(target, roots)
    if found is None or not target.is_relative_to(found.path):
        return None
    return target


@router.post("/open-in-editor", status_code=status.HTTP_204_NO_CONTENT)
async def open_in_editor(body: OpenIn, conn: DbDep, request: Request) -> Response:
    roots = projects.project_roots(conn)
    try:
        target = resolve_within(body.path, roots)
    except PathNotAllowedError as exc:
        # The one exception: a file of a proven linked worktree of a repository in a project.
        target = await _worktree_file(body.path, roots)
        if target is None:
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
