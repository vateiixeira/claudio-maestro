"""Project routes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from vibing import projects
from vibing.api.deps import DbDep, SettingsDep

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


_STATUS = {
    projects.ProjectNotFoundError: status.HTTP_404_NOT_FOUND,
    projects.DuplicateProjectPathError: status.HTTP_409_CONFLICT,
    projects.InvalidProjectPathError: status.HTTP_400_BAD_REQUEST,
    projects.ProjectPathNotAllowedError: status.HTTP_403_FORBIDDEN,
}


def _http_error(exc: projects.ProjectError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


@router.get("", response_model=list[ProjectOut])
def list_projects(conn: DbDep) -> list[projects.Project]:
    return projects.list_projects(conn)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, conn: DbDep, settings: SettingsDep) -> projects.Project:
    try:
        return projects.create_project(
            conn, name=body.name, path=body.path, color=body.color, home=settings.home_dir
        )
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate, conn: DbDep) -> projects.Project:
    try:
        return projects.update_project(
            conn, project_id, name=body.name, color=body.color, position=body.position
        )
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, conn: DbDep, request: Request) -> Response:
    """Close the project's active sessions (pending prompts cancelled), then delete it."""
    try:
        projects.get_project(conn, project_id)
        await request.app.state.sessions.close_project(project_id)
        projects.delete_project(conn, project_id)
    except projects.ProjectError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
