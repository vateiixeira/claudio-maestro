"""Routes of the digest agent: settings, passes and summaries."""

import asyncio
import json
import sqlite3
from contextlib import closing
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from claudio_maestro import db
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.sessions import get_session_manager
from claudio_maestro.digest import store
from claudio_maestro.digest.closure_store import get_closure
from claudio_maestro.digest.config import ConfigError, validate
from claudio_maestro.digest.service import ClosureItemNotFound, DigestService
from claudio_maestro.sessions import SessionManager

router = APIRouter(prefix="/api")

NOT_FOUND = "Sessão não encontrada."
ITEM_INVALID = "O item precisa ter de 1 a 200 caracteres."
ITEM_MAX = 200


def get_digest_service(request: Request) -> DigestService:
    return request.app.state.digest


ServiceDep = Annotated[DigestService, Depends(get_digest_service)]
ManagerDep = Annotated[SessionManager, Depends(get_session_manager)]


def _state(service: DigestService) -> dict[str, Any]:
    return {"config": service.config.to_dict(), "status": service.status()}


def _require_session(conn: sqlite3.Connection, session_id: str) -> None:
    row = conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


@router.get("/digest/config")
async def get_config(service: ServiceDep) -> dict[str, Any]:
    return _state(service)


@router.put("/digest/config")
async def put_config(request: Request, service: ServiceDep, manager: ManagerDep) -> dict[str, Any]:
    try:
        raw = json.loads(await request.body())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON inválido.") from exc
    known = [m.get("value") for m in manager.list_models() if isinstance(m.get("value"), str)]
    try:
        config = validate(raw, known)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await service.update_config(config)
    return _state(service)


@router.post("/digest/run", status_code=status.HTTP_202_ACCEPTED)
async def run_now(service: ServiceDep) -> dict[str, Any]:
    service.request_all()
    return service.status()


@router.get("/digest/runs")
async def list_runs(request: Request) -> list[dict[str, Any]]:
    path = request.app.state.settings.db_path

    def read() -> list[dict[str, Any]]:
        with closing(db.connect(path)) as conn:
            return store.list_runs(conn)

    return await asyncio.to_thread(read)


@router.get("/sessions/{session_id}/digest")
def get_session_digest(session_id: str, conn: DbDep) -> dict[str, Any] | None:
    _require_session(conn, session_id)
    digest = store.get_digest(conn, session_id)
    return None if digest is None else digest.to_dict()


@router.post("/sessions/{session_id}/digest", status_code=status.HTTP_202_ACCEPTED)
async def request_session_digest(
    session_id: str, request: Request, service: ServiceDep
) -> dict[str, bool]:
    path = request.app.state.settings.db_path

    def check() -> None:
        with closing(db.connect(path)) as conn:
            _require_session(conn, session_id)

    await asyncio.to_thread(check)
    service.request_session(session_id)
    return {"queued": True}


@router.get("/sessions/{session_id}/closure")
def get_session_closure(session_id: str, conn: DbDep) -> dict[str, Any] | None:
    _require_session(conn, session_id)
    row = conn.execute("SELECT last_activity_at FROM sessions WHERE session_id = ?",
                       (session_id,)).fetchone()
    closure = get_closure(conn, session_id)
    return None if closure is None else closure.to_dict(row["last_activity_at"])


@router.post("/sessions/{session_id}/closure/resolve")
async def resolve_closure_item(
    session_id: str, request: Request, service: ServiceDep
) -> dict[str, Any]:
    path = request.app.state.settings.db_path

    def check() -> None:
        with closing(db.connect(path)) as conn:
            _require_session(conn, session_id)

    await asyncio.to_thread(check)
    try:
        raw = json.loads(await request.body())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON inválido.") from exc
    item = raw.get("item") if isinstance(raw, dict) else None
    if not isinstance(item, str) or not item.strip() or len(item) > ITEM_MAX:
        raise HTTPException(status_code=422, detail=ITEM_INVALID)
    try:
        return await service.resolve_closure_item(session_id, item)
    except ClosureItemNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
