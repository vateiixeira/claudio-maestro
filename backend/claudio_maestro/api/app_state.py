"""Preferences kept in `app_state` as JSON values."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.editor import valid_editor_command
from claudio_maestro.sessions import EFFORTS, PERMISSION_MODES

router = APIRouter(prefix="/api/state")

ALLOWED_KEYS = ("preferences",)
MAX_BYTES = 64 * 1024
MAX_FINISHED_AFTER_DAYS = 365
MAX_MODEL_LENGTH = 100


def valid_finished_after_days(days: object) -> bool:
    return (
        isinstance(days, int) and not isinstance(days, bool)
        and 1 <= days <= MAX_FINISHED_AFTER_DAYS
    )


def valid_default_model(model: object) -> bool:
    return isinstance(model, str) and 1 <= len(model.strip()) <= MAX_MODEL_LENGTH


def valid_default_effort(effort: object) -> bool:
    return isinstance(effort, str) and effort in EFFORTS


def valid_default_mode(mode: object) -> bool:
    # bypassPermissions keeps asking for a confirmation per session.
    return isinstance(mode, str) and mode in PERMISSION_MODES and mode != "bypassPermissions"


@router.get("")
def get_state(conn: DbDep) -> dict[str, Any]:
    # Other keys (e.g. the models cache) are internal to the backend.
    return {row["key"]: json.loads(row["value"]) for row in conn.execute(
        "SELECT key, value FROM app_state ORDER BY key"
    ) if row["key"] in ALLOWED_KEYS}


@router.put("/{key}")
async def put_state(key: str, request: Request, conn: DbDep) -> Any:
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chave desconhecida.")
    body = await request.body()
    if len(body) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Conteúdo grande demais."
        )
    try:
        value = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON inválido.") from exc
    if key == "preferences" and isinstance(value, dict):
        if "editor_command" in value and not valid_editor_command(value["editor_command"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O comando do editor precisa ser uma lista de textos não vazios.",
            )
        if "finished_after_days" in value and not valid_finished_after_days(
            value["finished_after_days"]
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Os dias para ocultar sessões precisam ser um número inteiro de 1 a 365.",
            )
        checks = (
            ("new_session_model", valid_default_model, "O modelo padrão precisa ser um texto de até 100 caracteres."),
            ("new_session_effort", valid_default_effort, "Raciocínio padrão inválido."),
            ("new_session_mode", valid_default_mode, "Modo padrão inválido."),
        )
        for name, valid, message in checks:
            # null means "no default": the CLI decides, as before.
            if value.get(name) is not None and not valid(value[name]):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    return value
