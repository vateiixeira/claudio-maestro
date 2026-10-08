"""Routes of "Entregas": what was finished on a day, and the sessions still open."""

import asyncio
import re
from contextlib import closing
from datetime import date, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from claudio_maestro import db, deliveries
from claudio_maestro.digest.service import DeliveryConflict, DeliveryNotFound

router = APIRouter(prefix="/api")
INVALID_DATE = "Data inválida."
DAY_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}")
EARLIEST_DAY = date(2000, 1, 1)


def _parse_day(text: str) -> date:
    """A calendar day as `YYYY-MM-DD`, not before 2000, whose start the platform can express."""
    if not DAY_FORMAT.fullmatch(text):
        raise ValueError(text)
    parsed = date.fromisoformat(text)
    if parsed < EARLIEST_DAY:
        raise ValueError(text)
    datetime.combine(parsed, time.min).timestamp()  # what `sessions_on` does; may overflow
    return parsed


def _read_day(app: Any, day: date, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    with closing(db.connect(app.state.settings.db_path)) as conn:
        records = deliveries.list_day(conn, day.isoformat())
        prev_day, next_day = deliveries.neighbor_days(conn, day.isoformat())
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM projects")}
    active = app.state.activity.sessions_on(day)
    delivered = {d.session_id for d in records if d.session_id}
    open_items = [
        {"session_id": s["session_id"], "project_id": s["project_id"],
         "project_name": names.get(s["project_id"], ""), "title": s.get("title") or "",
         "short": s.get("digest_short")}
        for s in sessions
        if s["session_id"] in active and s["session_id"] not in delivered and s.get("mark") != "discarded"
    ]
    open_items.sort(key=lambda s: (s["project_name"].casefold(), s["title"].casefold()))
    return {
        "date": day.isoformat(),
        "agent_enabled": app.state.digest.config.enabled,
        "deliveries": [d.to_dict() for d in records],
        "in_progress": open_items,
        "prev_day": prev_day,
        "next_day": next_day,
    }


@router.get("/deliveries")
async def get_deliveries(
    request: Request,
    day: Annotated[str | None, Query(alias="date")] = None,
) -> dict[str, Any]:
    try:
        wanted = _parse_day(day) if day is not None else date.today()
    except (ValueError, OverflowError, OSError) as exc:
        raise HTTPException(status_code=422, detail=INVALID_DATE) from exc
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
