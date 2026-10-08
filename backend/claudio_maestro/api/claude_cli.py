"""Which `claude` the app starts, and the button that runs `claude update`."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from claudio_maestro.claudecli import ClaudeCliBusy, ClaudeCliUnavailable

router = APIRouter()


@router.get("/api/claude-cli")
async def get_claude_cli(request: Request) -> dict[str, Any]:
    resolver = request.app.state.claude_cli
    await resolver.refresh()  # cached for 10 min
    return resolver.state()


@router.post("/api/claude-cli/update")
async def update_claude_cli(request: Request) -> dict[str, Any]:
    app = request.app

    async def refresh_models() -> bool:
        return await app.state.sessions.refresh_models_if_stale(force=True)

    try:
        outcome = await app.state.claude_cli.update(refresh_models)
    except (ClaudeCliBusy, ClaudeCliUnavailable) as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    return outcome.as_dict()
