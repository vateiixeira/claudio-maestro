"""Agent providers: Claude Code (always on) and Kimi Code (optional, over ACP).

The provider of a session is chosen when it is created and never changes.
Kimi Code is enabled in the Preferências (`kimi_enabled`) and needs the `kimi`
command on the machine.
"""

import json
import sqlite3
from typing import Any

from claudio_maestro.agent.kimi_client import kimi_binary

CLAUDE = "claude"
KIMI = "kimi"
PROVIDERS: tuple[str, ...] = (CLAUDE, KIMI)
PROVIDER_NAMES = {CLAUDE: "Claude Code", KIMI: "Kimi Code"}


def valid_provider(value: Any) -> bool:
    return isinstance(value, str) and value in PROVIDERS


def kimi_available() -> bool:
    """The `kimi` command exists on this machine."""
    return kimi_binary() is not None


def kimi_enabled(preferences: dict[str, Any]) -> bool:
    """The user turned Kimi Code on in the Preferências."""
    return preferences.get("kimi_enabled") is True


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
        )
    ]
