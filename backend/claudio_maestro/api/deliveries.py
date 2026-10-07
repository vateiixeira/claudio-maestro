"""Routes of "Entregas": what was finished on a day, and the sessions still open."""

import asyncio
from contextlib import closing
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from claudio_maestro import db, deliveries
from claudio_maestro.digest.service import DeliveryConflict, DeliveryNotFound

router = APIRouter(prefix="/api")
INVALID_DATE = "Data inválida."


def _read_day(app: Any, day: date, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    with closing(db.connect(app.state.settings.db_path)) as conn:
        records = deliveries.list_day(conn, day.isoformat())
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM projects")}
    active = app.state.activity.sessions_on(day)
    delivered = {d.session_id for d in records if d.session_id}
    open_items = [
        {"session_id": s["session_id"], "project_id": s["project_id"],
         "project_name": names.get(s["project_id"], ""), "title": s.get("title") or "",
         "short": s.get("digest_short")}
        for s in sessions
        if s["session_id"] in active and s["session_id"] not in delivered
    ]
    open_items.sort(key=lambda s: (s["project_name"].casefold(), s["title"].casefold()))
    return {
        "date": day.isoformat(),
        "agent_enabled": app.state.digest.config.enabled,
        "deliveries": [d.to_dict() for d in records],
        "in_progress": open_items,
    }


@router.get("/deliveries")
async def get_deliveries(
    request: Request,
    day: Annotated[str | None, Query(alias="date")] = None,
) -> dict[str, Any]:
    try:
        wanted = date.fromisoformat(day) if day is not None else date.today()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=INVALID_DATE) from exc
    if day is not None and len(day) != 10:
        raise HTTPException(status_code=422, detail=INVALID_DATE)
    sessions = request.app.state.sessions.list_sessions()  # in memory, on the loop
    return await asyncio.to_thread(_read_day, request.app, wanted, sessions)


@router.post("/deliveries/{delivery_id}/summarize")
async def summarize_delivery(request: Request, delivery_id: int) -> dict[str, Any]:
    try:
        return await request.app.state.digest.resummarize(delivery_id)
    except DeliveryNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
    except DeliveryConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc
