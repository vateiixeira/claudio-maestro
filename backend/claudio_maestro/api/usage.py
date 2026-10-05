"""Subscription usage (read-only; the check runs in the background)."""

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/usage")
def get_usage(request: Request) -> dict[str, Any]:
    return request.app.state.usage.snapshot()
