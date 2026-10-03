"""Another process wrote to a session the app holds a client for.

The app's own process delivers each assistant message through the SDK stream with the
same `uuid` it writes to the `.jsonl`; a message written by another process (the CLI
in a terminal, a second app instance) never comes through that stream.
"""

import json
from collections.abc import Collection, Iterable
from datetime import datetime


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def has_foreign_reply(
    lines: Iterable[str], own_uuids: Collection[str], since: float | None
) -> bool:
    """Whether the lines hold an assistant entry of the main chain written after `since`
    (the current client's start) whose uuid the app's stream did not deliver."""
    if since is None:
        return False
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        if entry.get("isSidechain") is True:
            continue
        uuid = entry.get("uuid")
        written = _timestamp(entry.get("timestamp"))
        if not isinstance(uuid, str) or written is None:
            continue
        if written > since and uuid not in own_uuids:
            return True
    return False
