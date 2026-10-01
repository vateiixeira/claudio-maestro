"""Groups of related sessions inside a project."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from claudio_maestro import groups, projects, sessions
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.sessions import get_session_manager, group_http_error

router = APIRouter(prefix="/api")

ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The 80-character rule and trimming live in `groups.clean_name`; this only
    # stops absurd bodies before they reach it.
    name: str = Field(max_length=1000)


class GroupOut(BaseModel):
    id: int
    project_id: int
    name: str
    created_at: int


def _out(group: groups.Group) -> dict[str, Any]:
    return {
        "id": group.id, "project_id": group.project_id, "name": group.name,
        "created_at": group.created_at,
    }


def _changed(request: Request, project_id: int) -> None:
    """`groups.changed` `{project_id}`: the frontend reloads the group list."""
    request.app.state.hub.publish(
        {"session_id": None, "seq": 0, "type": "groups.changed",
         "data": {"project_id": project_id}}
    )


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(conn: DbDep) -> list[dict[str, Any]]:
    return [_out(group) for group in groups.list_groups(conn)]


@router.post(
    "/projects/{project_id}/groups", response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    project_id: int, body: GroupIn, request: Request, conn: DbDep
) -> dict[str, Any]:
    try:
        group = groups.create_group(conn, project_id, body.name)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, project_id)
    return _out(group)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def rename_group(
    group_id: int, body: GroupIn, request: Request, conn: DbDep
) -> dict[str, Any]:
    try:
        group = groups.rename_group(conn, group_id, body.name)
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, group.project_id)
    return _out(group)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, request: Request, manager: ManagerDep) -> Response:
    try:
        group = manager.remove_group(group_id)
    except groups.GroupError as exc:
        raise group_http_error(exc) from exc
    _changed(request, group.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
