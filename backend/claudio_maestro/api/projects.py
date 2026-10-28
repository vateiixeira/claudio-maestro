"""Project routes."""

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from claudio_maestro import db, groups, projects
from claudio_maestro.api.deps import DbDep, SettingsDep
from claudio_maestro.api.org import PROJECT_BUSY_TEXT
from claudio_maestro.org import store as org_store
from claudio_maestro.security import is_within

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    path: str = Field(min_length=1, max_length=4096)
    color: Color


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    color: Color | None = None
    position: int | None = Field(default=None, ge=0)


class ProjectOut(BaseModel):
    id: int
    name: str
    path: str
    color: str
    position: int
    created_at: int
    available: bool
    hidden_sessions: int = 0


_STATUS = {
    projects.ProjectNotFoundError: status.HTTP_404_NOT_FOUND,
    projects.DuplicateProjectPathError: status.HTTP_409_CONFLICT,
    projects.InvalidProjectPathError: status.HTTP_400_BAD_REQUEST,
    projects.ProjectPathNotAllowedError: status.HTTP_403_FORBIDDEN,
}


def _http_error(exc: projects.ProjectError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


def _out(project: projects.Project, hidden: dict[int, int]) -> dict[str, Any]:
    return {**asdict(project), "hidden_sessions": hidden.get(project.id, 0)}


@router.get("", response_model=list[ProjectOut])
async def list_projects(conn: DbDep, request: Request) -> list[dict[str, Any]]:
    hidden = request.app.state.sessions.hidden_counts()
    return [_out(project, hidden) for project in projects.list_projects(conn)]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, conn: DbDep, settings: SettingsDep, request: Request
) -> dict[str, Any]:
    try:
        project = projects.create_project(
            conn, name=body.name, path=body.path, color=body.color, home=settings.home_dir
        )
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc
    _sync_in_background(request, project.id)
    return _out(project, request.app.state.sessions.hidden_counts())


def _sync_in_background(request: Request, project_id: int) -> None:
    """Sync a new project's history without holding the response.

    Emits `project.synced` `{project_id}` when done, so the frontend reloads it.
    """
    state = request.app.state

    async def run() -> None:
        try:
            await state.history.sync_project(project_id)
        except Exception:
            logger.exception("Falha ao sincronizar o histórico do projeto %s", project_id)
        state.hub.publish(
            {"session_id": None, "seq": 0, "type": "project.synced",
             "data": {"project_id": project_id}}
        )

    task = asyncio.create_task(run())
    state.background.add(task)
    task.add_done_callback(state.background.discard)


@router.post("/{project_id}/sync")
async def sync_project(project_id: int, conn: DbDep, request: Request) -> list[dict[str, Any]]:
    """Read the project's history again. Returns its sessions, as the session listing."""
    try:
        projects.get_project(conn, project_id)
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc
    await request.app.state.history.sync_project(project_id)
    return request.app.state.sessions.list_sessions(project_id=project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, conn: DbDep) -> projects.Project:
    try:
        return projects.update_project(
            conn, project_id, name=body.name, color=body.color, position=body.position
        )
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc


def _holds_folder(session: Any, folder: Path) -> bool:
    """Whether the live process of the session reads `folder` or something inside it (its
    extra folders may be any folder of a project)."""
    return any(is_within(path, folder) for path in session.extra_dirs)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, conn: DbDep, request: Request, fence_id: str | None = None) -> Response:
    """Close the project's active sessions (pending prompts cancelled), then delete it."""
    manager = request.app.state.sessions
    try:
        projects.get_project(conn, project_id)
        org = request.app.state.org
        if any(org.is_busy(agent.id) for agent in org_store.list_agents(conn, project_id)):
            # Deleting would cut a run in the middle and leave a notice of an erased agent.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PROJECT_BUSY_TEXT)
        work = request.app.state.work
        receipt = work.reserve_project_deletion(project_id, fence_id=fence_id)
        try:
            # An agent of another project may hold this folder in its `addDirs`: its live
            # process keeps reading the folder, so it is closed before the project goes.
            folder = Path(projects.get_project(conn, project_id).path)
            for sid in manager.active_ids():
                session = manager.get(sid)
                if (
                    session.record.agent_id is not None
                    and session.record.project_id != project_id
                    and session.client is not None
                    and _holds_folder(session, folder)
                ):
                    await session.close()
            await manager.close_project(project_id)
            # Their groups die with the project: remember who sat in them from other projects.
            released = groups.foreign_members(conn, project_id)
            # The cascade takes the project's agents out of the database; their folders
            # (definition, memory, secrets) go too.
            orphans = org_store.list_agents(conn, project_id)
            with db.transaction(conn):
                fence = conn.execute('SELECT fence_id FROM work_project_fences WHERE project_id=?', (project_id,)).fetchone()
                if fence is None or fence['fence_id'] != receipt:
                    from claudio_maestro.work.store import WorkConflictError
                    raise WorkConflictError('O recibo da exclusão mudou.')
                if any(org.is_busy(agent.id) for agent in orphans):
                    # A run started while the sessions were being closed.
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PROJECT_BUSY_TEXT)
                projects.delete_project(conn, project_id)
        finally:
            work.release_deletion_owner(project_id)
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc
    for agent in orphans:
        request.app.state.agent_files.delete(agent.slug)
        request.app.state.hub.publish(
            {"session_id": None, "seq": 0, "type": "agent.changed", "data": {"id": agent.id}}
        )
    # The cascade took the project's sessions, and their labels, out of the database.
    manager.reconcile_label_ids()
    if released:
        manager.announce_group_released(released)
        request.app.state.hub.publish(
            {"session_id": None, "seq": 0, "type": "groups.changed", "data": {"project_id": project_id}}
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
