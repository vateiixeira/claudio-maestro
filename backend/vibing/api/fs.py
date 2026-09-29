"""Folder browser, repository preview and native folder picker routes."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from vibing import fs, picker
from vibing.api.deps import SettingsDep
from vibing.security import PathNotAllowedError, resolve_within

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fs")


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


@router.get("/repos", response_model=ReposOut)
async def preview_repos(settings: SettingsDep, path: str) -> dict:
    try:
        repos, limit_reached = await fs.preview_repos(path, settings.home_dir)
    except fs.BrowseError as exc:
        raise HTTPException(status_code=_STATUS[type(exc)], detail=str(exc)) from exc
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
            chosen = await request.app.state.pick_folder(settings.home_dir)
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
