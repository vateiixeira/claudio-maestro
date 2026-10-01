"""Turns the SDK message stream into a list of conversation items and events.

Two events are enough for the conversation: `item.upsert` (whole item, new or
replaced) and `item.append` (text chunk for an existing item). All translation
logic lives here, so the frontend only inserts by id and concatenates text.

Item ids for assistant blocks are f"{message_id}:{index}". The SDK emits one
AssistantMessage per content block; blocks of the same response share the
message_id, and each AssistantMessage arrives before its `content_block_stop`,
so the block index comes from the `content_block_start` that is open.
"""

import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

NoticeLevel = Literal["info", "warning", "error"]


# Items ---------------------------------------------------------------------


@dataclass
class UserItem:
    id: str
    text: str
    images: list[Any] = field(default_factory=list)
    type: Literal["user"] = field(default="user", init=False)


@dataclass
class TextItem:
    id: str
    text: str
    streaming: bool
    parent_tool_use_id: str | None = None
    type: Literal["text"] = field(default="text", init=False)


@dataclass
class ThinkingItem:
    id: str
    text: str
    streaming: bool
    parent_tool_use_id: str | None = None
    type: Literal["thinking"] = field(default="thinking", init=False)


@dataclass
class ToolItem:
    id: str
    tool_use_id: str
    name: str
    input: dict[str, Any]
    result: dict[str, Any] | None
    streaming: bool
    parent_tool_use_id: str | None = None
    # Loaded from history without a result anywhere in the transcript.
    result_missing: bool = False
    # Agent/Task only: {task_id, subagent_type, description, status, last_activity,
    # usage, summary}, updated by the SDK task messages.
    subagent: dict[str, Any] | None = None
    type: Literal["tool"] = field(default="tool", init=False)


@dataclass
class NoticeItem:
    id: str
    level: NoticeLevel
    text: str
    parent_tool_use_id: str | None = None
    type: Literal["notice"] = field(default="notice", init=False)


Item = UserItem | TextItem | ThinkingItem | ToolItem | NoticeItem


# Events --------------------------------------------------------------------


@dataclass
class Event:
    """`data` is a JSON-ready snapshot taken when the event was created."""

    type: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


@dataclass
class SessionInit:
    session_id: str | None
    model: str | None
    permission_mode: str | None


@dataclass
class TurnResult:
    subtype: str
    is_error: bool
    duration_ms: int
    total_cost_usd: float | None
    usage: dict[str, Any] | None
    errors: list[str] | None


@dataclass
class RateLimit:
    status: str
    resets_at: int | None
    rate_limit_type: str | None


ASSISTANT_ERROR_TEXT = {
    "authentication_failed": "Falha de autenticação. Rode `claude` no terminal e faça /login.",
    "billing_error": "Problema de cobrança na conta. Confira sua assinatura.",
    "rate_limit": "Limite de uso atingido. Tente de novo mais tarde.",
    "invalid_request": "A requisição foi recusada pela API.",
    "server_error": "A API está com problemas. Tente de novo em instantes.",
    "unknown": "Erro desconhecido na resposta do modelo.",
}

RESULT_ERROR_TEXT = {
    "error_max_turns": "O limite de turnos foi atingido.",
    "error_max_budget_usd": "O limite de custo foi atingido.",
    "error_during_execution": "O turno terminou com erro.",
}

INTERRUPTED_REASONS = {"aborted_streaming", "aborted_tools"}

ECHO_PREFIXES = ("Set model to ",)

SUBAGENT_TOOLS = {"Agent", "Task"}
# SDK task status -> status shown ("running" | "completed" | "failed" | "stopped").
# A subagent running longer than this is assumed lost (never blocks closing).
SUBAGENT_MAX_SECONDS = 3 * 60 * 60
_SUBAGENT_STATUS = {
    "pending": "running",
    "running": "running",
    "paused": "running",
    "completed": "completed",
    "failed": "failed",
    "killed": "stopped",
    "stopped": "stopped",
}

_TEXT_BLOCKS = {"text"}
_THINKING_BLOCKS = {"thinking", "redacted_thinking"}
_TOOL_BLOCKS = {"tool_use", "server_tool_use", "mcp_tool_use"}


@dataclass
class _Stream:
    """Streaming state of one response, per parent_tool_use_id."""

    message_id: str | None = None
    open_index: int | None = None
    finalized: set[int] = field(default_factory=set)


class ConversationBuilder:
    def __init__(self) -> None:
        self.items: list[Item] = []
        self._positions: dict[str, int] = {}
        self._tools: dict[str, str] = {}  # tool_use_id -> item id
        self._streams: dict[str | None, _Stream] = {}
        self._next_index: dict[str, int] = {}
        self._turn_error_shown = False
        # Subagent state by tool_use_id of the Agent/Task call, and task_id -> tool_use_id.
        self._subagents: dict[str, dict[str, Any]] = {}
        self._task_tools: dict[str, str] = {}
        # Monotonic time each subagent was first seen, by tool_use_id.
        self._subagent_started: dict[str, float] = {}
        # Echoes still expected from live changes by the app, counted by prefix.
        self._expected_echoes: dict[str, int] = {}
        self.init: SessionInit | None = None
        self.last_result: TurnResult | None = None
        self.rate_limit: RateLimit | None = None

    # Public API ------------------------------------------------------------

    def get(self, item_id: str) -> Item | None:
        position = self._positions.get(item_id)
        return None if position is None else self.items[position]

    def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.items]

    def add_user_message(
        self, text: str, images: list[dict[str, Any]] | None = None
    ) -> list[Event]:
        """`images` are light markers ({type, media_type, size}), never the base64."""
        item = UserItem(id=f"user-{uuid.uuid4().hex}", text=text, images=list(images or []))
        return [self._put(item)]

    def expect_local_echo(self, text: str) -> None:
        """The app changed the model live: the CLI answers at the next turn with a
        `<local-command-stdout>Set model to ...` line; one such line is dropped
        per expectation. `text` only selects the prefix."""
        for prefix in ECHO_PREFIXES:
            if text.startswith(prefix):
                self._expected_echoes[prefix] = self._expected_echoes.get(prefix, 0) + 1

    def cancel_local_echo(self, text: str) -> None:
        """The change `expect_local_echo` announced was refused: no echo will come."""
        for prefix in ECHO_PREFIXES:
            if text.startswith(prefix) and self._expected_echoes.get(prefix, 0) > 0:
                self._expected_echoes[prefix] -= 1

    def clear_local_echo(self) -> None:
        self._expected_echoes.clear()

    def add_notice(self, level: NoticeLevel, text: str) -> list[Event]:
        """Notice raised by the app itself (e.g. the agent process failed)."""
        return [self._notice(level, text)]

    def load_history(
        self,
        entries: list[Any],
        tool_results: dict[str, dict[str, Any]] | None = None,
        compact_uuids: set[str] | None = None,
    ) -> None:
        """Rebuild items from a saved conversation (`get_session_messages`).

        `user` entries carry text, images or tool result blocks; each `assistant`
        entry carries one block in the API format, as in the live stream.

        `get_session_messages` follows a single `parentUuid` chain, so results of
        parallel tool calls are often missing from `entries`. `tool_results`
        (read from the raw transcript, by `tool_use_id`) completes them and adds
        `details` (`toolUseResult`). A tool still without a result gets
        `result_missing`. Base64 images are never kept. Entries in
        `compact_uuids` (`isCompactSummary`) become a "Conversa compactada" notice.
        """
        tool_results = tool_results or {}
        compact_uuids = compact_uuids or set()
        for entry in entries:
            message = entry.message if isinstance(entry.message, dict) else {}
            content = message.get("content")
            if entry.type == "user" and getattr(entry, "uuid", None) in compact_uuids:
                self.add_notice("info", COMPACTED_TEXT)
            elif entry.type == "user":
                self._load_user(content)
            elif entry.type == "assistant" and isinstance(content, list):
                blocks = [b for b in (_block_from_dict(raw) for raw in content) if b is not None]
                if blocks:
                    self._on_assistant(
                        AssistantMessage(
                            content=blocks,
                            model=str(message.get("model") or ""),
                            message_id=message.get("id") or entry.uuid,
                        )
                    )
        self.close_open_items()
        for item in self.items:
            if not isinstance(item, ToolItem):
                continue
            raw = tool_results.get(item.tool_use_id)
            if raw is not None:
                self._note_agent_id(item, raw.get("details"))
                if item.result is None:
                    item.result = {
                        "content": cap_content(omit_images(raw.get("content"))),
                        "is_error": raw.get("is_error"),
                        "details": slim_details(item.name, raw.get("details")),
                    }
                elif item.result.get("details") is None:
                    item.result["details"] = slim_details(item.name, raw.get("details"))
            item.result_missing = item.result is None
            if item.subagent is not None and item.subagent["status"] == "running":
                if item.result is None:
                    item.subagent["status"] = "stopped"
                elif item.result.get("is_error"):
                    item.subagent["status"] = "failed"
                else:
                    item.subagent["status"] = "completed"

    def _load_user(self, content: Any) -> None:
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            return
        texts: list[str] = []
        images: list[dict[str, Any]] = []
        notices: list[str] = []
        for raw in content:
            if not isinstance(raw, dict):
                continue
            kind = raw.get("type")
            if kind == "text":
                text, notice = _classify_user_text(raw.get("text") or "")
                if notice:
                    notices.append(notice)
                if text:
                    texts.append(text)
            elif kind in ("image", "document"):
                images.append(_media_marker(raw))
        text = "\n".join(texts)
        if text.strip() or images:
            self._put(UserItem(id=f"user-{uuid.uuid4().hex}", text=text, images=images))
        for notice in notices:
            self.add_notice("info", notice)
        for raw in content:
            if not isinstance(raw, dict) or raw.get("type") != "tool_result":
                continue
            if self._tool_item(str(raw.get("tool_use_id"))) is None:
                continue
            self._attach_tool_result(
                ToolResultBlock(
                    tool_use_id=raw["tool_use_id"],
                    content=omit_images(raw.get("content")),
                    is_error=raw.get("is_error"),
                ),
                None,
            )

    def handle(self, message: Any) -> list[Event]:
        if isinstance(message, StreamEvent):
            return self._on_stream_event(message)
        if isinstance(message, AssistantMessage):
            return self._on_assistant(message)
        if isinstance(message, UserMessage):
            return self._on_user(message)
        if isinstance(message, ResultMessage):
            return self._on_result(message)
        if isinstance(message, RateLimitEvent):
            return self._on_rate_limit(message)
        if isinstance(message, SystemMessage):
            return self._on_system(message)
        return []

    # Items -----------------------------------------------------------------

    def _put(self, item: Item) -> Event:
        if isinstance(item, ToolItem):
            # A Write of a big file would otherwise weigh on every snapshot.
            item.input = _cut_strings(item.input, TOOL_INPUT_STRING_LIMIT)
        position = self._positions.get(item.id)
        if position is None:
            self._positions[item.id] = len(self.items)
            self.items.append(item)
        else:
            self.items[position] = item
        if isinstance(item, ToolItem):
            self._tools[item.tool_use_id] = item.id
            if item.name in SUBAGENT_TOOLS:
                item.subagent = self._subagent_for(item)
        return Event("item.upsert", asdict(item))

    def _subagent_for(self, item: ToolItem) -> dict[str, Any]:
        sub = self._subagents.get(item.tool_use_id)
        if sub is None:
            sub = {
                "task_id": None,
                "subagent_type": None,
                "description": None,
                "status": "running",
                "last_activity": None,
                "usage": None,
                "summary": None,
            }
            self._subagents[item.tool_use_id] = sub
            self._subagent_started[item.tool_use_id] = time.monotonic()
        if sub["subagent_type"] is None and isinstance(item.input.get("subagent_type"), str):
            sub["subagent_type"] = item.input["subagent_type"]
        if sub["description"] is None and isinstance(item.input.get("description"), str):
            sub["description"] = item.input["description"]
        return sub

    def _notice(self, level: NoticeLevel, text: str) -> Event:
        return self._put(NoticeItem(id=f"notice-{uuid.uuid4().hex}", level=level, text=text))

    def _tool_item(self, tool_use_id: str) -> ToolItem | None:
        item_id = self._tools.get(tool_use_id)
        item = self.get(item_id) if item_id else None
        return item if isinstance(item, ToolItem) else None

    # Stream events ---------------------------------------------------------

    def _on_stream_event(self, message: StreamEvent) -> list[Event]:
        event = message.event
        kind = event.get("type")
        parent = message.parent_tool_use_id
        if kind == "message_start":
            message_id = (event.get("message") or {}).get("id")
            self._streams[parent] = _Stream(message_id=message_id)
            return []
        if kind == "content_block_start":
            return self._on_block_start(parent, event)
        if kind == "content_block_delta":
            return self._on_block_delta(parent, event)
        if kind == "content_block_stop":
            stream = self._streams.get(parent)
            if stream is not None and stream.open_index == event.get("index"):
                stream.open_index = None
        return []

    def _on_block_start(self, parent: str | None, event: dict[str, Any]) -> list[Event]:
        stream = self._streams.setdefault(parent, _Stream())
        if stream.message_id is None:
            stream.message_id = f"msg-{uuid.uuid4().hex}"
        index = event.get("index", 0)
        block = event.get("content_block") or {}
        stream.open_index = index
        message_id = stream.message_id
        self._next_index[message_id] = max(self._next_index.get(message_id, 0), index + 1)

        item_id = f"{message_id}:{index}"
        block_type = block.get("type")
        item: Item
        if block_type in _TEXT_BLOCKS:
            item = TextItem(item_id, block.get("text", ""), True, parent)
        elif block_type in _THINKING_BLOCKS:
            item = ThinkingItem(item_id, block.get("thinking", ""), True, parent)
        elif block_type in _TOOL_BLOCKS and block.get("id"):
            item = ToolItem(
                id=item_id,
                tool_use_id=block["id"],
                name=block.get("name", ""),
                input=block.get("input") or {},
                result=None,
                streaming=True,
                parent_tool_use_id=parent,
            )
        else:
            # Server tool results and unknown blocks get no item of their own.
            return []
        return [self._put(item)]

    def _on_block_delta(self, parent: str | None, event: dict[str, Any]) -> list[Event]:
        stream = self._streams.get(parent)
        if stream is None or stream.message_id is None:
            return []
        item = self.get(f"{stream.message_id}:{event.get('index')}")
        if item is None or not getattr(item, "streaming", False):
            return []
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta" and isinstance(item, TextItem):
            chunk = delta.get("text", "")
        elif delta.get("type") == "thinking_delta" and isinstance(item, ThinkingItem):
            chunk = delta.get("thinking", "")
        else:
            return []
        item.text += chunk
        return [Event("item.append", {"item_id": item.id, "text": chunk})]

    # Assistant and user messages ------------------------------------------

    def _on_assistant(self, message: AssistantMessage) -> list[Event]:
        if message.error:
            self._turn_error_shown = True
            text = ASSISTANT_ERROR_TEXT.get(message.error, ASSISTANT_ERROR_TEXT["unknown"])
            return [self._notice("error", text)]

        parent = message.parent_tool_use_id
        message_id = message.message_id or message.uuid or f"msg-{uuid.uuid4().hex}"
        stream = self._streams.get(parent)
        events: list[Event] = []
        for block in message.content:
            if (
                stream is not None
                and stream.message_id == message_id
                and stream.open_index is not None
                and stream.open_index not in stream.finalized
            ):
                index = stream.open_index
                stream.finalized.add(index)
            else:
                index = self._next_index.get(message_id, 0)
            self._next_index[message_id] = max(self._next_index.get(message_id, 0), index + 1)
            events.extend(self._apply_block(block, f"{message_id}:{index}", parent))
        return events

    def _apply_block(self, block: Any, item_id: str, parent: str | None) -> list[Event]:
        if isinstance(block, TextBlock):
            return [self._put(TextItem(item_id, block.text, False, parent))]
        if isinstance(block, ThinkingBlock):
            return [self._put(ThinkingItem(item_id, block.thinking, False, parent))]
        if isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
            existing = self._tool_item(block.id)
            return [
                self._put(
                    ToolItem(
                        id=existing.id if existing else item_id,
                        tool_use_id=block.id,
                        name=block.name,
                        input=block.input,
                        result=existing.result if existing else None,
                        streaming=False,
                        parent_tool_use_id=parent,
                    )
                )
            ]
        if isinstance(block, ServerToolResultBlock):
            content_type = str(block.content.get("type", ""))
            result = {
                "content": block.content,
                "is_error": content_type.endswith("_error"),
                "details": None,
            }
            tool = self._tool_item(block.tool_use_id)
            if tool is not None:
                tool.result = result
                tool.streaming = False
                return [self._put(tool)]
            return [
                self._put(
                    ToolItem(
                        id=item_id,
                        tool_use_id=block.tool_use_id,
                        name=content_type or "server_tool",
                        input={},
                        result=result,
                        streaming=False,
                        parent_tool_use_id=parent,
                    )
                )
            ]
        if isinstance(block, ToolResultBlock):
            return self._attach_tool_result(block, None)
        return []

    def _on_user(self, message: UserMessage) -> list[Event]:
        # Plain text is the echo of what the user sent; add_user_message has it.
        # Output of a local command (e.g. after set_model) becomes a notice.
        if isinstance(message.content, str):
            if "<local-command-stdout>" not in message.content:
                return []
            output = _STDOUT.sub("", message.content).strip()
            prefix = next((p for p in ECHO_PREFIXES if output.startswith(p)), None)
            if prefix is not None and self._expected_echoes.get(prefix, 0) > 0:
                self._expected_echoes[prefix] -= 1
                return []
            return [self._notice("info", output)] if output else []
        events: list[Event] = []
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                events.extend(self._attach_tool_result(block, message.tool_use_result))
        return events

    def _attach_tool_result(
        self, block: ToolResultBlock, details: dict[str, Any] | None
    ) -> list[Event]:
        tool = self._tool_item(block.tool_use_id)
        if tool is None:
            return [
                self._notice(
                    "warning",
                    f"Chegou o resultado de uma ferramenta desconhecida ({block.tool_use_id}).",
                )
            ]
        tool.result = {
            "content": cap_content(block.content),
            "is_error": block.is_error,
            "details": slim_details(tool.name, details),
        }
        tool.streaming = False
        if block.is_error and tool.subagent is not None and tool.subagent["status"] == "running":
            tool.subagent["status"] = "failed"
        self._note_agent_id(tool, details)
        events = [self._put(tool)]
        if tool.name == "SendMessage" and not block.is_error:
            events.extend(self._resume_subagent(details))
        return events

    def _note_agent_id(self, tool: ToolItem, details: Any) -> None:
        """The Agent/Task result names the task (`agentId`): a later SendMessage
        resume finds the card by it even without any Task* message."""
        agent_id = details.get("agentId") if isinstance(details, dict) else None
        if tool.name in SUBAGENT_TOOLS and isinstance(agent_id, str) and agent_id:
            self._task_tools.setdefault(agent_id, tool.tool_use_id)

    def _resume_subagent(self, details: dict[str, Any] | None) -> list[Event]:
        """SendMessage woke a subagent that had ended: its Agent/Task card runs again."""
        task_id = details.get("resumedAgentId") if isinstance(details, dict) else None
        tool_use_id = self._task_tools.get(task_id) if isinstance(task_id, str) else None
        tool = self._tool_item(tool_use_id) if tool_use_id else None
        if tool is None or tool_use_id not in self._subagents:
            return []
        # A card loaded from history has no task_id; stopping it needs one.
        self._subagents[tool_use_id]["task_id"] = task_id
        self._subagents[tool_use_id]["status"] = "running"
        self._subagent_started[tool_use_id] = time.monotonic()
        return [self._put(tool)]

    # System, result, rate limit ------------------------------------------

    def _on_task(self, message: SystemMessage) -> list[Event]:
        """Task* messages update the subagent card of the Agent/Task call."""
        task_id = getattr(message, "task_id", None)
        tool_use_id = getattr(message, "tool_use_id", None)
        tool = self._tool_item(tool_use_id) if tool_use_id else None
        if tool is None or tool.name not in SUBAGENT_TOOLS:
            # After a SendMessage resume the CLI names the SendMessage call, not the
            # Agent/Task one; the card is still the one that started the task.
            tool_use_id = self._task_tools.get(task_id)
            tool = self._tool_item(tool_use_id) if tool_use_id else None
        if tool is None or tool.name not in SUBAGENT_TOOLS:
            return []
        self._task_tools[task_id] = tool_use_id
        sub = self._subagent_for(tool)
        sub["task_id"] = task_id
        if isinstance(message, TaskStartedMessage):
            sub["subagent_type"] = message.data.get("subagent_type") or sub["subagent_type"]
            sub["description"] = message.description or sub["description"]
            sub["status"] = "running"
        elif isinstance(message, TaskProgressMessage):
            sub["description"] = message.description or sub["description"]
            sub["last_activity"] = message.last_tool_name or sub["last_activity"]
            sub["usage"] = dict(message.usage) if message.usage else sub["usage"]
        elif isinstance(message, TaskUpdatedMessage):
            status = message.status or message.patch.get("status")
            sub["status"] = _SUBAGENT_STATUS.get(str(status), sub["status"])
        elif isinstance(message, TaskNotificationMessage):
            sub["status"] = _SUBAGENT_STATUS.get(message.status, sub["status"])
            sub["summary"] = message.summary
            if message.usage:
                sub["usage"] = dict(message.usage)
        return [self._put(tool)]

    def _on_system(self, message: SystemMessage) -> list[Event]:
        if isinstance(
            message,
            (TaskStartedMessage, TaskProgressMessage, TaskUpdatedMessage, TaskNotificationMessage),
        ):
            return self._on_task(message)
        if message.subtype == "background_tasks_changed":
            return self._on_background_tasks(message.data)
        if message.subtype != "init":
            return []
        data = message.data
        self.init = SessionInit(
            session_id=data.get("session_id"),
            model=data.get("model"),
            permission_mode=data.get("permissionMode"),
        )
        return [Event("session.init", asdict(self.init))]

    @property
    def subagents_running(self) -> bool:
        """Some subagent (usually in the background) has not finished yet.

        Last resort: one running for longer than SUBAGENT_MAX_SECONDS no longer counts.
        """
        now = time.monotonic()
        return any(
            sub["status"] == "running"
            and now - self._subagent_started.get(tool_use_id, now) <= SUBAGENT_MAX_SECONDS
            for tool_use_id, sub in self._subagents.items()
        )

    def _end_subagents(self, status_for: Callable[[str, ToolItem], str | None]) -> list[Event]:
        """Give running subagents the status `status_for` returns (None keeps them)."""
        events: list[Event] = []
        for tool_use_id, sub in self._subagents.items():
            tool = self._tool_item(tool_use_id)
            if sub["status"] != "running" or tool is None:
                continue
            status = status_for(tool_use_id, tool)
            if status is not None:
                sub["status"] = status
                events.append(self._put(tool))
        return events

    def running_task_ids(self) -> list[str]:
        """Task ids of subagents still running (those the CLI already announced)."""
        return [
            sub["task_id"] for sub in self._subagents.values()
            if sub["status"] == "running" and sub["task_id"]
        ]

    def stop_running_subagents(self) -> list[Event]:
        """The client went away: subagents still running died with it."""
        return self._end_subagents(lambda _id, _tool: "stopped")

    def _on_background_tasks(self, data: Any) -> list[Event]:
        """No background task left: every subagent still running has ended.
        Any other shape of `tasks` is ignored."""
        tasks = data.get("tasks") if isinstance(data, dict) else None
        if not isinstance(tasks, list) or tasks:
            return []
        return self._end_subagents(
            lambda _id, tool: "completed" if tool.result is not None else "stopped"
        )

    def close_open_items(self) -> list[Event]:
        """End every item still streaming; used at the end of a turn or on failure."""
        events: list[Event] = []
        for item in self.items:
            if getattr(item, "streaming", False):
                item.streaming = False  # type: ignore[union-attr]
                events.append(self._put(item))
        self._streams.clear()
        return events

    def _on_result(self, message: ResultMessage) -> list[Event]:
        events = self.close_open_items()
        # A subagent that never got a task_id did not survive the turn.
        events.extend(self._end_subagents(
            lambda tool_use_id, _tool: (
                "stopped" if self._subagents[tool_use_id]["task_id"] is None else None
            )
        ))

        if message.terminal_reason in INTERRUPTED_REASONS:
            events.append(self._notice("info", "Interrompido."))
        elif message.is_error and not self._turn_error_shown:
            events.append(self._notice("error", _result_error_text(message)))
        self._turn_error_shown = False

        self.last_result = TurnResult(
            subtype=message.subtype,
            is_error=message.is_error,
            duration_ms=message.duration_ms,
            total_cost_usd=message.total_cost_usd,
            usage=message.usage,
            errors=message.errors,
        )
        events.append(Event("turn.result", asdict(self.last_result)))
        return events

    def _on_rate_limit(self, message: RateLimitEvent) -> list[Event]:
        info = message.rate_limit_info
        self.rate_limit = RateLimit(
            status=info.status,
            resets_at=info.resets_at,
            rate_limit_type=info.rate_limit_type,
        )
        events = [Event("rate_limit", asdict(self.rate_limit))]
        if info.status == "rejected":
            events.append(self._notice("error", rate_limit_text(info.resets_at)))
        return events


def rate_limit_text(resets_at: int | None, now: datetime | None = None) -> str:
    """"Limite da assinatura atingido. Libera às 14:30." in local time; the date
    is added when the release is not today."""
    text = "Limite da assinatura atingido."
    if not resets_at:
        return text
    when = datetime.fromtimestamp(resets_at, UTC).astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    if when.date() == today:
        return f"{text} Libera às {when:%H:%M}."
    return f"{text} Libera às {when:%H:%M} de {when:%d/%m}."


def cap_items(items: list[dict[str, Any]], max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """The newest items whose JSON fits in `max_bytes`; True when some were left out."""
    total = 2  # the brackets
    kept = 0
    for item in reversed(items):
        size = len(json.dumps(item)) + 2  # ", " between items
        if total + size > max_bytes:
            break
        total += size
        kept += 1
    if kept == len(items):
        return items, False
    return items[len(items) - kept:], True


_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?(</system-reminder>|$)", re.DOTALL)
_COMMAND_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_STDOUT = re.compile(r"</?local-command-std(out|err)>")
INTERRUPTED_TEXT = "Interrompido."
COMPACTED_TEXT = "Conversa compactada"
# How the CLI opens the summary it writes when a conversation is compacted.
COMPACT_SUMMARY_PREFIX = "This session is being continued from a previous conversation"


def _classify_user_text(text: str) -> tuple[str, str | None]:
    """Split what the CLI writes as a user message: (text kept, notice text)."""
    text = _SYSTEM_REMINDER.sub("", text).strip()
    if not text or text.startswith("Caveat:"):
        return "", None
    match = _COMMAND_NAME.search(text)
    if match:
        name = match.group(1).strip()
        args = _COMMAND_ARGS.search(text)
        arguments = args.group(1).strip() if args else ""
        return (f"{name} {arguments}" if arguments else name), None
    if "<local-command-stdout>" in text or "<local-command-stderr>" in text:
        output = _STDOUT.sub("", text).strip()
        return "", output or None
    if "<task-notification>" in text:
        return "", "Subagente em segundo plano terminou"
    if text.startswith("[Request interrupted by user"):
        return "", INTERRUPTED_TEXT
    if text.startswith(COMPACT_SUMMARY_PREFIX):
        return "", COMPACTED_TEXT
    return text, None


def classify_user_text(text: str) -> tuple[str, str | None]:
    """Public name of `_classify_user_text`, used by the digest agent."""
    return _classify_user_text(text)


DETAILS_STRING_LIMIT = 20_000
TOOL_INPUT_STRING_LIMIT = 20_000
CONTENT_LIMIT = 200_000
_EDIT_TOOLS = {"Edit", "MultiEdit", "Write"}
_EDIT_DETAIL_KEYS = ("filePath", "structuredPatch", "type", "userModified")
_READ_DROPPED_KEYS = {"content", "base64"}


def _cut(text: str, limit: int) -> str:
    # Already cut (its marker starts right at the limit): cutting again is a no-op.
    if len(text) <= limit or text.startswith("…[cortado ", limit):
        return text
    return f"{text[:limit]}…[cortado {len(text) - limit} caracteres]"


def _cut_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _cut(value, limit)
    if isinstance(value, list):
        return [_cut_strings(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _cut_strings(v, limit) for k, v in value.items()}
    return value


def slim_details(tool_name: str, details: Any) -> Any:
    """`toolUseResult` without whole-file copies, so snapshots stay small.

    Edit/MultiEdit/Write keep the patch (the frontend's diff only uses
    `structuredPatch`); Read keeps path and line counts (the text is in the
    result content); any other tool gets long strings cut.
    """
    if not isinstance(details, dict):
        return _cut_strings(details, DETAILS_STRING_LIMIT)
    if tool_name in _EDIT_TOOLS:
        return {key: details[key] for key in _EDIT_DETAIL_KEYS if key in details}
    if tool_name == "Read":
        slim = {k: v for k, v in details.items() if k not in _READ_DROPPED_KEYS}
        file = details.get("file")
        if isinstance(file, dict):
            slim["file"] = {k: v for k, v in file.items() if k not in _READ_DROPPED_KEYS}
        return _cut_strings(slim, DETAILS_STRING_LIMIT)
    return _cut_strings(details, DETAILS_STRING_LIMIT)


def cap_content(content: Any) -> Any:
    """Tool result content with each text cut at 200 000 characters."""
    return _cut_strings(content, CONTENT_LIMIT)


def _base64_size(data: Any) -> int | None:
    if not isinstance(data, str):
        return None
    return len(data) * 3 // 4 - data[-2:].count("=")


def _media_marker(raw: dict[str, Any]) -> dict[str, Any]:
    """Light stand-in for an image or document: type, media type and size, no data."""
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    return {
        "type": raw.get("type"),
        "media_type": source.get("media_type"),
        "size": _base64_size(source.get("data")),
    }


def omit_images(content: Any) -> Any:
    """Tool result content with image blocks replaced by a marker without the base64."""
    if not isinstance(content, list):
        return content
    result = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image":
            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            block = {"type": "image", "omitted": True, "media_type": source.get("media_type")}
        result.append(block)
    return result


def _block_from_dict(raw: Any) -> Any:
    """API-format content block to the SDK block type, or None when not shown."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind == "text":
        return TextBlock(text=raw.get("text", ""))
    if kind == "thinking":
        # Saved thinking is often empty (only the signature is kept): not shown.
        thinking = raw.get("thinking") or ""
        if not thinking.strip():
            return None
        return ThinkingBlock(thinking=thinking, signature=raw.get("signature", ""))
    if kind in _TOOL_BLOCKS and raw.get("id"):
        return ToolUseBlock(id=raw["id"], name=raw.get("name", ""), input=raw.get("input") or {})
    return None


def _result_error_text(message: ResultMessage) -> str:
    text = RESULT_ERROR_TEXT.get(message.subtype, "O turno terminou com erro.")
    detail = "; ".join(message.errors) if message.errors else message.result
    return f"{text} {detail}" if detail else text
