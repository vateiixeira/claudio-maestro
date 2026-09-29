"""Fake SDK history functions (`list_sessions`, `get_session_messages`, `rename_session`)."""

import time
from typing import Any

from claude_agent_sdk import SDKSessionInfo, SessionMessage


def info(
    session_id: str,
    cwd: str,
    *,
    summary: str = "",
    custom_title: str | None = None,
    first_prompt: str | None = None,
    created_ms: int | None = None,
    modified_ms: int | None = None,
) -> SDKSessionInfo:
    modified_ms = modified_ms if modified_ms is not None else 1_000_000_000_000
    return SDKSessionInfo(
        session_id=session_id,
        summary=summary,
        last_modified=modified_ms,
        custom_title=custom_title,
        first_prompt=first_prompt,
        cwd=cwd,
        created_at=created_ms if created_ms is not None else modified_ms - 60_000,
    )


def now_ms() -> int:
    return int(time.time() * 1000)


def user_entry(content: Any, session_id: str = "s", uuid: str = "u") -> SessionMessage:
    return SessionMessage(
        type="user", uuid=uuid, session_id=session_id,
        message={"role": "user", "content": content},
    )


def assistant_entry(block: dict[str, Any], message_id: str, session_id: str = "s") -> SessionMessage:
    return SessionMessage(
        type="assistant", uuid=f"a-{message_id}", session_id=session_id,
        message={"id": message_id, "role": "assistant", "model": "haiku", "content": [block]},
    )


class FakeHistory:
    def __init__(self) -> None:
        self.by_directory: dict[str, list[SDKSessionInfo]] = {}
        self.messages: dict[str, list[SessionMessage]] = {}
        self.failing: set[str] = set()
        self.list_calls: list[str] = []
        self.message_calls: list[tuple[str, str]] = []
        self.renames: list[tuple[str, str, str]] = []
        self.raw_results: dict[str, dict[str, dict[str, Any]]] = {}

    def read_tool_results(self, session_id: str, directory: str) -> dict[str, dict[str, Any]]:
        return dict(self.raw_results.get(session_id, {}))

    def add(self, directory: str, *infos: SDKSessionInfo) -> None:
        self.by_directory.setdefault(directory, []).extend(infos)

    def list_sessions(self, directory: str) -> list[SDKSessionInfo]:
        self.list_calls.append(directory)
        if directory in self.failing:
            raise RuntimeError("falha no SDK")
        return list(self.by_directory.get(directory, []))

    def get_session_messages(self, session_id: str, directory: str) -> list[SessionMessage]:
        self.message_calls.append((session_id, directory))
        return list(self.messages.get(session_id, []))

    def rename_session(self, session_id: str, title: str, directory: str) -> None:
        self.renames.append((session_id, title, directory))
