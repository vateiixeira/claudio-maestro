"""Lines of a CLI transcript (`.jsonl`) for the tests of the text index."""

import json
from pathlib import Path
from typing import Any

STAMP = "2026-10-14T20:41:40.051Z"


def user(text: Any, uuid: str = "u1", **extra: Any) -> dict[str, Any]:
    return {
        "type": "user", "uuid": uuid, "timestamp": STAMP,
        "message": {"role": "user", "content": text}, **extra,
    }


def assistant(text: str, uuid: str = "a1", **extra: Any) -> dict[str, Any]:
    return {
        "type": "assistant", "uuid": uuid, "timestamp": STAMP,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, **extra,
    }


def write(path: Path, entries: list[dict[str, Any]]) -> None:
    body = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries)
    path.write_text(body, encoding="utf-8")


def append(path: Path, entries: list[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as file:
        for entry in entries:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
