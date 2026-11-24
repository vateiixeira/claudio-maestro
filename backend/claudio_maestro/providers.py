"""Agent providers and whether they are enabled and installed."""

import json
import sqlite3
from typing import Any

from claudio_maestro.agent.codex_transport import codex_binary
from claudio_maestro.agent.kimi_client import kimi_binary

CLAUDE = "claude"
KIMI = "kimi"
CODEX = "codex"
PROVIDERS: tuple[str, ...] = (CLAUDE, KIMI, CODEX)
PROVIDER_NAMES = {CLAUDE: "Claude", KIMI: "Kimi Code", CODEX: "Codex CLI"}


def valid_provider(value: Any) -> bool:
    return isinstance(value, str) and value in PROVIDERS


def kimi_available() -> bool:
    """The `kimi` command exists on this machine."""
    return kimi_binary() is not None


def kimi_enabled(preferences: dict[str, Any]) -> bool:
    """The user turned Kimi Code on in the Preferências."""
    return preferences.get("kimi_enabled") is True


def codex_available() -> bool:
    return codex_binary() is not None


def codex_enabled(preferences: dict[str, Any]) -> bool:
    return preferences.get("codex_enabled") is True


def preferences_from(conn: sqlite3.Connection) -> dict[str, Any]:
    """The `preferences` object of `app_state`; empty when missing or invalid."""
    row = conn.execute("SELECT value FROM app_state WHERE key = 'preferences'").fetchone()
    if row is None:
        return {}
    try:
        value = json.loads(row["value"])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def provider_choices(preferences: dict[str, Any]) -> list[dict[str, Any]]:
    """What the new-conversation screen shows: every provider, with whether it can be used."""
    return [
        {"id": provider, "name": PROVIDER_NAMES[provider], "enabled": enabled,
         "available": available}
        for provider, enabled, available in (
            (CLAUDE, True, True),
            (KIMI, kimi_enabled(preferences), kimi_available()),
            (CODEX, codex_enabled(preferences), codex_available()),
        )
    ]
