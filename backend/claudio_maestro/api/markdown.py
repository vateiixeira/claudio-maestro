"""Markdown files of a project, read for the reader page. Read only."""

import asyncio
import os
import stat
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from claudio_maestro import sessions
from claudio_maestro.api.sessions import get_session_manager
from claudio_maestro.projectpath import resolve_project_path
from claudio_maestro.security import PathNotAllowedError

router = APIRouter(prefix="/api")

ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]

MAX_BYTES = 1024 * 1024
MAX_PATH = 4096
BAD_PATH = "Informe o caminho de um arquivo."
OUTSIDE = "O arquivo precisa estar dentro de um projeto."
NOT_MARKDOWN = "Só arquivos markdown (.md) podem ser lidos aqui."
NOT_FOUND = "Arquivo não encontrado."
TOO_BIG = "O arquivo passa de 1 MB."
NOT_TEXT = "O arquivo não é texto UTF-8."


class MarkdownOut(BaseModel):
    path: str
    content: str
    mtime: float


def _error(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _read(target: Path) -> dict[str, Any]:
    """Contents of a regular file up to MAX_BYTES. Blocking: run it off the loop.

    `target` is already resolved, so O_NOFOLLOW only bites when a symlink was swapped in
    after the check (ELOOP, a 404). O_NONBLOCK keeps a FIFO named `x.md` from hanging the open; `fstat` on the open
    file rejects anything that is not a regular file."""
    try:
        fd = os.open(
            target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY
        )
    except OSError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, NOT_FOUND) from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):  # also a folder, which opens fine read-only
            raise _error(status.HTTP_404_NOT_FOUND, NOT_FOUND)
        if info.st_size > MAX_BYTES:
            raise _error(status.HTTP_413_CONTENT_TOO_LARGE, TOO_BIG)
        with os.fdopen(fd, "rb") as handle:
            fd = -1  # the file object owns it now
            data = handle.read(MAX_BYTES + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_BYTES:  # grew after the fstat
        raise _error(status.HTTP_413_CONTENT_TOO_LARGE, TOO_BIG)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(status.HTTP_400_BAD_REQUEST, NOT_TEXT) from exc
    return {"path": str(target), "content": content, "mtime": info.st_mtime}


@router.get("/sessions/{session_id}/markdown", response_model=MarkdownOut)
async def read_markdown(session_id: str, manager: ManagerDep, path: str = "") -> dict[str, Any]:
    try:
        record = manager.get(session_id).record
    except sessions.SessionNotFoundError as exc:
        raise _error(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if not path.strip() or "\x00" in path or len(path) > MAX_PATH:
        raise _error(status.HTTP_400_BAD_REQUEST, BAD_PATH)
    raw = os.path.expanduser(path)
    roots = manager.project_roots()
    work_dir = await asyncio.to_thread(record.work_dir)
    # Relative paths: the folder the conversation works in now, then the one it started
    # in (Claude may have named the file before entering a worktree).
    bases = [Path(work_dir)]
    if record.cwd != work_dir:
        bases.append(Path(record.cwd))
    if os.path.isabs(raw):
        bases = bases[:1]  # the base does not matter for an absolute path
    target: Path | None = None
    for base in bases:
        try:
            candidate = await resolve_project_path(raw, roots, base=base)
        except PathNotAllowedError:
            continue
        if target is None:
            target = candidate
        if await asyncio.to_thread(candidate.is_file):
            target = candidate
            break
    if target is None:
        raise _error(status.HTTP_403_FORBIDDEN, OUTSIDE)
    if target.suffix.lower() != ".md":
        raise _error(status.HTTP_400_BAD_REQUEST, NOT_MARKDOWN)
    return await asyncio.to_thread(_read, target)
