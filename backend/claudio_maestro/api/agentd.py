"""Restart the agentd after an update changed it (only with no session running in it)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()


@router.post("/api/agentd/restart")
async def restart_agentd(request: Request) -> dict[str, Any]:
    agentd = request.app.state.agentd
    if agentd is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "o agentd está desligado")
    children = await agentd.live_children()
    if children is None:
        return {"restarted": False}
    live = sum(1 for child in children if child.exit_code is None)
    if live:
        noun = "sessão rodando" if live == 1 else "sessões rodando"
        raise HTTPException(status.HTTP_409_CONFLICT, f"há {live} {noun} no agentd")
    # A session still connecting could spawn between the check above and the shutdown.
    if request.app.state.sessions.live_count() > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "há sessões abertas no app")
    await agentd.shutdown_server()
    return {"restarted": True}
