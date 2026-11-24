"""Codex version, native account limits, models and the local updater."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from claudio_maestro.codexcli import CodexUpdateUnavailable

router = APIRouter(prefix="/api/codex-cli")


@router.get("")
async def get_codex_cli(request: Request) -> dict[str, Any]:
    return await request.app.state.codex_cli.refresh()


@router.post("/refresh")
async def refresh_codex_cli(request: Request) -> dict[str, Any]:
    return await request.app.state.codex_cli.refresh(force=True)


@router.post("/update")
async def update_codex_cli(request: Request) -> dict[str, Any]:
    try:
        return await request.app.state.codex_cli.update()
    except CodexUpdateUnavailable as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
