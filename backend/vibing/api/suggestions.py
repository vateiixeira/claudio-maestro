"""Suggestion routes for the message field: slash commands and files of the folder a
session or project works in. The browser never sends a path: it comes from the id."""

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from vibing import projects, sessions
from vibing.api.deps import DbDep
from vibing.api.sessions import ManagerDep
from vibing.commands import CommandCatalogError
from vibing.filesearch import FileSearchError

router = APIRouter(prefix="/api")

Q = Annotated[str, Query(max_length=200)]


def _existing(folder: Path) -> Path:
    if not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pasta do projeto não existe mais: {folder}",
        )
    return folder


def session_folder(manager: sessions.SessionManager, session_id: str) -> Path:
    try:
        record = manager.find_record(session_id)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _existing(Path(record.work_dir()))


def project_folder(conn: Any, project_id: int) -> Path:
    try:
        project = projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _existing(Path(project.path))


async def _commands(request: Request, folder: Path) -> list[dict[str, str]]:
    try:
        found = await request.app.state.commands.list(folder)
    except CommandCatalogError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [
        {"name": c.name, "description": c.description, "argument_hint": c.argument_hint}
        for c in found
    ]


@router.get("/sessions/{session_id}/commands")
async def session_commands(
    session_id: str, request: Request, manager: ManagerDep
) -> list[dict[str, str]]:
    return await _commands(request, session_folder(manager, session_id))


@router.get("/projects/{project_id}/commands")
async def project_commands(project_id: int, request: Request, conn: DbDep) -> list[dict[str, str]]:
    return await _commands(request, project_folder(conn, project_id))


async def _files(request: Request, folder: Path, q: str) -> list[dict[str, str]]:
    try:
        found = await request.app.state.files.search(folder, q)
    except FileSearchError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [{"path": m.path, "name": m.name, "type": m.type} for m in found]


@router.get("/sessions/{session_id}/files")
async def session_files(
    session_id: str, request: Request, manager: ManagerDep, q: Q = ""
) -> list[dict[str, str]]:
    return await _files(request, session_folder(manager, session_id), q)


@router.get("/projects/{project_id}/files")
async def project_files(
    project_id: int, request: Request, conn: DbDep, q: Q = ""
) -> list[dict[str, str]]:
    return await _files(request, project_folder(conn, project_id), q)
