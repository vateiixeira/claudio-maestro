"""Folder browser, repository preview and native folder picker routes."""

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from vibing import fs, picker
from vibing.api.deps import SettingsDep
from vibing.security import PathNotAllowedError, resolve_within

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fs")

# How often long requests (folder picker, repository preview) check whether the browser gave up.
DISCONNECT_POLL = 0.5


class DirEntryOut(BaseModel):
    name: str
    path: str
    git: bool
    branch: str | None = None
    detached: bool = False


class DirListingOut(BaseModel):
    path: str
    parent: str | None
    entries: list[DirEntryOut]


class RepoOut(BaseModel):
    name: str
    rel_path: str
    path: str
    branch: str | None
    detached: bool


class ReposOut(BaseModel):
    repos: list[RepoOut]
    limit_reached: bool


class PickOut(BaseModel):
    path: str | None


_STATUS = {
    fs.BrowseNotAllowedError: status.HTTP_403_FORBIDDEN,
    fs.BrowseNotFoundError: status.HTTP_404_NOT_FOUND,
    fs.BrowseNotADirectoryError: status.HTTP_400_BAD_REQUEST,
}


@router.get("/dirs", response_model=DirListingOut)
async def list_dirs(settings: SettingsDep, path: str | None = None) -> fs.DirListing:
    try:
        listing = await asyncio.to_thread(fs.list_dirs, path, settings.home_dir)
    except fs.BrowseError as exc:
        raise HTTPException(status_code=_STATUS[type(exc)], detail=str(exc)) from exc
    return await fs.with_branches(listing)


async def _run_until_disconnect[T](request: Request, work: Awaitable[T]) -> T | None:
    """Run `work` as a task, but cancel it if the browser disconnects.

    Starlette does not cancel the route when the client goes away, so the
    connection is polled. Cancelling stops what `work` awaits (the picker's zenity,
    the git processes). Returns None when the client left.
    """
    task = asyncio.ensure_future(work)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=DISCONNECT_POLL)
            if done:
                return task.result()
            if await request.is_disconnected():
                return None
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@router.get("/repos", response_model=ReposOut)
async def preview_repos(settings: SettingsDep, request: Request, path: str) -> dict:
    try:
        result = await _run_until_disconnect(request, fs.preview_repos(path, settings.home_dir))
    except fs.BrowseError as exc:
        raise HTTPException(status_code=_STATUS[type(exc)], detail=str(exc)) from exc
    if result is None:  # the browser left: nobody reads the answer
        return {"repos": [], "limit_reached": False}
    repos, limit_reached = result
    return {"repos": repos, "limit_reached": limit_reached}


@router.post("/pick", response_model=PickOut)
async def pick_folder(settings: SettingsDep, request: Request) -> dict:
    """Open the system folder picker and return the chosen folder (null: cancelled)."""
    lock: asyncio.Lock = request.app.state.pick_lock
    if lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O seletor de pastas já está aberto.",
        )
    async with lock:
        try:
            chosen = await _run_until_disconnect(
                request, request.app.state.pick_folder(settings.home_dir)
            )
        except picker.PickerUnavailableError as exc:
            logger.warning("Seletor de pastas indisponível: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="O seletor de pastas do sistema não está disponível.",
            ) from exc
        except picker.PickerTimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="O seletor de pastas passou do tempo limite.",
            ) from exc
        except picker.PickerError as exc:
            logger.warning("Seletor de pastas falhou: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="O seletor de pastas do sistema falhou.",
            ) from exc
    if chosen is None:
        return {"path": None}
    try:
        resolved = resolve_within(chosen, [settings.home_dir.resolve()])
    except PathNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A pasta escolhida precisa estar dentro da pasta pessoal.",
        ) from exc
    return {"path": str(resolved)}
