"""Folder browser route."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from vibing import fs
from vibing.api.deps import SettingsDep

router = APIRouter(prefix="/api/fs")


class DirEntryOut(BaseModel):
    name: str
    path: str
    git: bool


class DirListingOut(BaseModel):
    path: str
    parent: str | None
    entries: list[DirEntryOut]


_STATUS = {
    fs.BrowseNotAllowedError: status.HTTP_403_FORBIDDEN,
    fs.BrowseNotFoundError: status.HTTP_404_NOT_FOUND,
    fs.BrowseNotADirectoryError: status.HTTP_400_BAD_REQUEST,
}


@router.get("/dirs", response_model=DirListingOut)
def list_dirs(settings: SettingsDep, path: str | None = None) -> fs.DirListing:
    try:
        return fs.list_dirs(path, settings.home_dir)
    except fs.BrowseError as exc:
        raise HTTPException(status_code=_STATUS[type(exc)], detail=str(exc)) from exc
