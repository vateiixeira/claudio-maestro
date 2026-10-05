"""Whether a newer release exists (read-only; the check runs in the background)."""

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/updates")
def get_updates(request: Request) -> dict[str, Any]:
    return request.app.state.updates.state()
