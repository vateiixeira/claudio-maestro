"""Plans a conversation can be linked to, and the link itself."""

import asyncio
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from vibing import gitinfo, projects, sessions
from vibing.api.deps import DbDep
from vibing.api.sessions import PlanOut, get_session_manager
from vibing.plans import PLAN_DIR, PlanCache, is_plan_path
from vibing.security import PathNotAllowedError, resolve_within

router = APIRouter(prefix="/api")

ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]

NOT_A_PLAN = "O arquivo não é um plano com tarefas."
OUTSIDE_PROJECT = "O plano precisa estar dentro de um projeto registrado."
BAD_BODY = "Informe o caminho do plano ou o modo automático."


class PlanLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = Field(default=None, min_length=1, max_length=4096)
    auto: Literal[True] | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> "PlanLinkIn":
        if (self.path is None) == (self.auto is None):
            raise ValueError(BAD_BODY)
        return self


class PlanTaskOut(BaseModel):
    number: int
    title: str
    done: bool


class PlanStateOut(BaseModel):
    link: Literal["auto", "manual", "off"]
    # Linked path, even when the file is gone.
    path: str | None
    plan: PlanOut | None
    tasks: list[PlanTaskOut]


class ProjectPlanOut(BaseModel):
    path: str
    title: str
    total: int
    done: int


def list_project_plans(root: Path, cache: PlanCache) -> list[dict[str, Any]]:
    """Plans in the project folder and in the repositories below it, newest first.

    Blocking (disk): run it off the event loop."""
    folders = [root]
    folders.extend(repo for repo in gitinfo.discover_scan(root)[0] if repo != root)
    found: dict[Path, tuple[float, dict[str, Any]]] = {}
    for folder in folders:
        try:
            files = sorted((folder.joinpath(*PLAN_DIR)).glob("*.md"))
        except OSError:
            continue
        for file in files:
            # Symlinks and folders that lead out of the project are dropped here.
            resolved = is_plan_path(file, [root])
            if resolved is None or resolved in found:
                continue
            progress = cache.read(resolved)
            if progress is None:
                continue
            try:
                mtime = resolved.stat().st_mtime
            except OSError:
                continue
            found[resolved] = (
                mtime,
                {
                    "path": str(resolved), "title": progress.title,
                    "total": progress.total, "done": progress.done,
                },
            )
    return [plan for _, plan in sorted(found.values(), key=lambda item: -item[0])]


@router.get("/projects/{project_id}/plans", response_model=list[ProjectPlanOut])
async def list_plans(
    project_id: int, conn: DbDep, manager: ManagerDep
) -> list[dict[str, Any]]:
    try:
        project = projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not project.available:
        return []
    return await asyncio.to_thread(list_project_plans, Path(project.path), manager.plan_cache)


def _get_session(manager: sessions.SessionManager, session_id: str) -> sessions.ActiveSession:
    try:
        return manager.get(session_id)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


async def _plan_state(manager: sessions.SessionManager, session_id: str) -> dict[str, Any]:
    """The link of a session and its plan, read now (the file only if it changed)."""
    await manager.refresh_plan(session_id)
    record = _get_session(manager, session_id).record
    link = record.plan_link or "auto"
    path = record.plan_path
    summary = None
    tasks: list[dict[str, Any]] = []
    if path:
        progress = await asyncio.to_thread(manager.plan_cache.read, Path(path))
        if progress is not None:
            summary = progress.summary(path)
            tasks = [
                {"number": task.number, "title": task.title, "done": task.done}
                for task in progress.tasks
            ]
    return {"link": link, "path": path, "plan": summary, "tasks": tasks}


async def _parse_body(request: Request) -> PlanLinkIn:
    try:
        data = await request.json()
        return PlanLinkIn.model_validate(data)
    except (ValueError, ValidationError) as exc:  # broken JSON, empty body or wrong shape
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=BAD_BODY) from exc


def _check_plan(raw: str, manager: sessions.SessionManager) -> Path:
    """Resolved path of a plan of a registered project. 403 when the file is outside
    every project (symlinks and `..` included), 400 when it is not a plan.

    Blocking (disk): run it off the event loop."""
    if "\x00" in raw or not os.path.isabs(os.path.expanduser(raw)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_PLAN)
    roots = manager.project_roots()
    try:
        resolved = resolve_within(Path(raw).expanduser(), roots)
    except PathNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=OUTSIDE_PROJECT) from exc
    plan = is_plan_path(resolved, roots)
    if plan is None or manager.plan_cache.read(plan) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_PLAN)
    return plan


@router.get("/sessions/{session_id}/plan", response_model=PlanStateOut)
async def get_plan(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    _get_session(manager, session_id)
    return await _plan_state(manager, session_id)


@router.put("/sessions/{session_id}/plan", response_model=PlanStateOut)
async def put_plan(session_id: str, request: Request, manager: ManagerDep) -> dict[str, Any]:
    session = _get_session(manager, session_id)
    body = await _parse_body(request)
    if body.path is not None:
        plan = await asyncio.to_thread(_check_plan, body.path, manager)
        changed = manager.link_plan(session_id, str(plan), source="manual")
        record = session.record
        if not changed and not (
            record.plan_path == str(plan) and record.plan_link == "manual"
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_PLAN)
    else:
        manager.auto_plan(session_id)
    return await _plan_state(manager, session_id)


@router.delete("/sessions/{session_id}/plan", response_model=PlanStateOut)
async def delete_plan(session_id: str, manager: ManagerDep) -> dict[str, Any]:
    _get_session(manager, session_id)
    manager.unlink_plan(session_id)
    return await _plan_state(manager, session_id)
