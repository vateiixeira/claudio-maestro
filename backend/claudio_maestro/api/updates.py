"""Whether a newer release exists, and the button that updates the app to it."""

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from claudio_maestro.selfupdate import UpdateBusy, UpdateNotAllowed

router = APIRouter()


def survives(app: FastAPI) -> bool:
    """Whether sessions outlive a restart of the app (new ones also go through the agentd)."""
    return app.state.agentd is not None and app.state.agentd_new_sessions


class ApplyBody(BaseModel):
    version: str
    confirm_sessions_drop: bool = False


@router.get("/api/updates")
async def get_updates(request: Request) -> dict[str, Any]:
    app = request.app
    eligibility = await app.state.self_updater.check()
    agentd = app.state.agentd
    live_children = None
    if agentd is not None:
        children = await agentd.live_children()
        if children is not None:
            live_children = sum(1 for child in children if child.exit_code is None)
    return {
        **app.state.updates.state(),
        "run_mode": app.state.run_mode.as_dict(),
        "self_update": {"can": eligibility.ok, "reason": eligibility.reason, "mode": eligibility.mode},
        "job": app.state.self_updater.job_state(),
        "last_result": app.state.update_result,
        "agentd": {"enabled": survives(app), "live_children": live_children},
        "live_sessions": app.state.sessions.live_count(),
        "port": app.state.port,
    }


@router.post("/api/updates/apply", status_code=status.HTTP_202_ACCEPTED)
async def apply_update(body: ApplyBody, request: Request) -> dict[str, Any]:
    app = request.app
    state = app.state.updates.state()
    latest = state["latest"]
    if not state["available"] or latest is None or latest["version"] != body.version:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "essa versão não foi anunciada como mais nova")
    if not survives(app) and not body.confirm_sessions_drop:
        live = app.state.sessions.live_count()
        if live:
            noun = "sessão em andamento será encerrada" if live == 1 else "sessões em andamento serão encerradas"
            # Structured so the page can show the confirmation even when its own count is stale.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"code": "sessions_drop", "sessions": live, "message": f"{live} {noun}; confirme para continuar"},
            )
    try:
        await app.state.self_updater.apply(body.version)
    except (UpdateNotAllowed, UpdateBusy) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"job": app.state.self_updater.job_state()}
