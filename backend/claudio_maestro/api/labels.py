"""Global labels (slug + color) and the labels of a session."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from claudio_maestro import labels, sessions
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.sessions import (
    SessionOut,
    get_session_manager,
    label_http_error,
)

router = APIRouter(prefix="/api")

ManagerDep = Annotated[sessions.SessionManager, Depends(get_session_manager)]


class LabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Trimming, case and the real rules live in `labels.clean_slug` / `clean_color`; this only
    # stops absurd bodies before they reach them.
    slug: str = Field(max_length=1000)
    color: str = Field(max_length=100)


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, max_length=100)


class LabelOut(BaseModel):
    id: int
    slug: str
    color: str
    created_at: int


class SessionLabelsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_ids: list[int] = Field(max_length=200)


def _out(label: labels.Label) -> dict[str, Any]:
    return {
        "id": label.id, "slug": label.slug, "color": label.color, "created_at": label.created_at,
    }


def _changed(request: Request) -> None:
    """`labels.changed`: the frontend reloads the catalog."""
    request.app.state.hub.publish(
        {"session_id": None, "seq": 0, "type": "labels.changed", "data": {}}
    )


@router.get("/labels", response_model=list[LabelOut])
async def list_labels(conn: DbDep) -> list[dict[str, Any]]:
    return [_out(label) for label in labels.list_labels(conn)]


@router.post("/labels", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
async def create_label(body: LabelIn, request: Request, conn: DbDep) -> dict[str, Any]:
    try:
        label = labels.create_label(conn, body.slug, body.color)
    except labels.LabelError as exc:
        raise label_http_error(exc) from exc
    _changed(request)
    return _out(label)


@router.patch("/labels/{label_id}", response_model=LabelOut)
async def update_label(
    label_id: int, body: LabelPatch, request: Request, conn: DbDep
) -> dict[str, Any]:
    try:
        label = labels.update_label(conn, label_id, slug=body.slug, color=body.color)
    except labels.LabelError as exc:
        raise label_http_error(exc) from exc
    _changed(request)
    return _out(label)


@router.delete("/labels/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label(label_id: int, request: Request, manager: ManagerDep) -> Response:
    try:
        manager.remove_label(label_id)
    except labels.LabelError as exc:
        raise label_http_error(exc) from exc
    _changed(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/sessions/{session_id}/labels", response_model=SessionOut)
async def set_session_labels(
    session_id: str, body: SessionLabelsIn, manager: ManagerDep
) -> dict[str, Any]:
    try:
        return await manager.set_labels(session_id, body.label_ids)
    except sessions.SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except labels.LabelError as exc:
        raise label_http_error(exc) from exc
