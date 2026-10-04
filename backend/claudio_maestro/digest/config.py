"""Settings of the digest agent, kept in `app_state` under `digest_agent`."""

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from typing import Any

CONFIG_KEY = "digest_agent"
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
MODEL_ALIASES: tuple[str, ...] = ("default", "opus", "sonnet", "haiku")
MAX_INSTRUCTIONS = 4000
LIMITS: dict[str, tuple[int, int]] = {
    "interval_minutes": (2, 240),
    "min_new_messages": (1, 500),
    "open_turn_minutes": (5, 480),
    "window_days": (1, 30),
}
MESSAGES: dict[str, str] = {
    "enabled": "Ligado precisa ser verdadeiro ou falso.",
    "model": "Escolha um modelo da lista.",
    "effort": "Escolha um nível de raciocínio da lista.",
    "extra_instructions": "As instruções extras podem ter até 4.000 caracteres.",
    "interval_minutes": "O intervalo precisa ser um número inteiro de 2 a 240 minutos.",
    "min_new_messages": "O mínimo de mensagens novas precisa ser um número inteiro de 1 a 500.",
    "open_turn_minutes": "O teto com turno aberto precisa ser um número inteiro de 5 a 480 minutos.",
    "window_days": "A janela precisa ser um número inteiro de 1 a 30 dias.",
    "closure_auto": "Verificar entrega automaticamente precisa ser verdadeiro ou falso.",
}


@dataclass(frozen=True)
class DigestConfig:
    enabled: bool = False
    model: str = "sonnet"
    effort: str = "medium"
    extra_instructions: str = ""
    interval_minutes: int = 10
    min_new_messages: int = 10
    open_turn_minutes: int = 30
    window_days: int = 3
    closure_auto: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FIELD_NAMES = tuple(f.name for f in fields(DigestConfig))


class ConfigError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__(" ".join(errors.values()))
        self.errors = errors


def model_known(model: str, known: Iterable[str]) -> bool:
    return model in MODEL_ALIASES or model in set(known)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _field_ok(name: str, value: Any, known_models: Iterable[str] | None) -> bool:
    """`known_models=None` accepts any well-formed model id (stored values)."""
    if name in ("enabled", "closure_auto"):
        return isinstance(value, bool)
    if name == "model":
        if not isinstance(value, str) or not 1 <= len(value) <= 100:
            return False
        return known_models is None or model_known(value, known_models)
    if name == "effort":
        return value in EFFORTS
    if name == "extra_instructions":
        return isinstance(value, str) and len(value) <= MAX_INSTRUCTIONS
    low, high = LIMITS[name]
    return _is_int(value) and low <= value <= high


def coerce(raw: Any) -> DigestConfig:
    """Stored value to config: a missing or invalid field takes the default."""
    if not isinstance(raw, dict):
        return DigestConfig()
    values = {
        name: raw[name] for name in FIELD_NAMES
        if name in raw and _field_ok(name, raw[name], None)
    }
    return DigestConfig(**values)


def validate(raw: Any, known_models: Iterable[str]) -> DigestConfig:
    """Body of `PUT /api/digest/config`. Missing fields take the default."""
    if not isinstance(raw, dict):
        raise ConfigError({"body": "Envie a configuração como um objeto."})
    known = list(known_models)
    errors: dict[str, str] = {}
    for name in raw:
        if name not in FIELD_NAMES:
            errors[name] = f"Campo desconhecido: {name}."
    for name in FIELD_NAMES:
        if name in raw and not _field_ok(name, raw[name], known):
            errors[name] = MESSAGES[name]
    if errors:
        raise ConfigError(errors)
    return DigestConfig(**{name: raw[name] for name in FIELD_NAMES if name in raw})


def load_config(conn: sqlite3.Connection) -> DigestConfig:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (CONFIG_KEY,)).fetchone()
    if row is None:
        return DigestConfig()
    try:
        return coerce(json.loads(row["value"]))
    except ValueError:
        return DigestConfig()


def save_config(conn: sqlite3.Connection, config: DigestConfig) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (CONFIG_KEY, json.dumps(config.to_dict(), ensure_ascii=False)),
    )
