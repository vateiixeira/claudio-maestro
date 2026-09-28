"""Turns the SDK message stream into a list of conversation items and events.

Two events are enough for the conversation: `item.upsert` (whole item, new or
replaced) and `item.append` (text chunk for an existing item). All translation
logic lives here, so the frontend only inserts by id and concatenates text.

Item ids for assistant blocks are f"{message_id}:{index}". The SDK emits one
AssistantMessage per content block; blocks of the same response share the
message_id, and each AssistantMessage arrives before its `content_block_stop`,
so the block index comes from the `content_block_start` that is open.
"""

import uuid
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
        self.init: SessionInit | None = None
        self.last_result: TurnResult | None = None
        self.rate_limit: RateLimit | None = None

    # Public API ------------------------------------------------------------

    def get(self, item_id: str) -> Item | None:
        position = self._positions.get(item_id)
        return None if position is None else self.items[position]

    def snapshot(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.items]

    def add_user_message(self, text: str) -> list[Event]:
        return [self._put(UserItem(id=f"user-{uuid.uuid4().hex}", text=text))]

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
        position = self._positions.get(item.id)
        if position is None:
            self._positions[item.id] = len(self.items)
            self.items.append(item)
        else:
            self.items[position] = item
        if isinstance(item, ToolItem):
            self._tools[item.tool_use_id] = item.id
        return Event("item.upsert", asdict(item))

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
        if isinstance(message.content, str):
            return []
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
        tool.result = {"content": block.content, "is_error": block.is_error, "details": details}
        tool.streaming = False
        return [self._put(tool)]

    # System, result, rate limit ------------------------------------------

    def _on_system(self, message: SystemMessage) -> list[Event]:
        if message.subtype != "init":
            return []
        data = message.data
        self.init = SessionInit(
            session_id=data.get("session_id"),
            model=data.get("model"),
            permission_mode=data.get("permissionMode"),
        )
        return [Event("session.init", asdict(self.init))]

    def _on_result(self, message: ResultMessage) -> list[Event]:
        events: list[Event] = []
        for item in self.items:
            if getattr(item, "streaming", False):
                item.streaming = False  # type: ignore[union-attr]
                events.append(self._put(item))
        self._streams.clear()

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
            text = "Limite de uso da assinatura atingido."
            if info.resets_at:
                when = datetime.fromtimestamp(info.resets_at, UTC).astimezone()
                text += f" Libera às {when:%H:%M} de {when:%d/%m}."
            events.append(self._notice("error", text))
        return events


def _result_error_text(message: ResultMessage) -> str:
    text = RESULT_ERROR_TEXT.get(message.subtype, "O turno terminou com erro.")
    detail = "; ".join(message.errors) if message.errors else message.result
    return f"{text} {detail}" if detail else text
