"""Persist the next Claude folder; never switch credentials of running sessions."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from claudio_maestro.claudeprofile import ProfileError, read_selection, save_selection
from claudio_maestro.config import claude_config_dir

router = APIRouter(prefix="/api/claude-profile")


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    folder: str | None = Field(max_length=4096)


def profile_state(request: Request) -> dict:
    settings = request.app.state.settings
    root = settings.profile_root or settings.data_dir
    default = (
        settings.default_claude_config_dir or claude_config_dir().expanduser().resolve()
    )
    active = settings.claude_config_dir or default
    selected = read_selection(root, settings.home_dir)
    return {
        "active_folder": str(active),
        "default_folder": str(default),
        "selected_folder": str(selected) if selected is not None else None,
        "restart_required": (selected or default) != active
        or (selected is not None) != settings.profile_isolated,
    }


@router.get("")
def get_profile(request: Request) -> dict:
    try:
        return profile_state(request)
    except ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("")
def put_profile(body: Selection, request: Request) -> dict:
    settings = request.app.state.settings
    try:
        save_selection(
            settings.profile_root or settings.data_dir, body.folder, settings.home_dir
        )
        return profile_state(request)
    except ProfileError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, "Não foi possível salvar a pasta do Claude.") from exc
