"""Activity per day and project, for the dashboard chart."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api")


@router.get("/activity")
async def get_activity(
    request: Request, days: Annotated[int, Query(ge=1, le=31)] = 14
) -> list[dict[str, Any]]:
    # Reads files: off the event loop.
    return await asyncio.to_thread(request.app.state.activity.read, days)
