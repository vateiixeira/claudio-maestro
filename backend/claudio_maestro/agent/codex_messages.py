"""Translate native Codex items and usage into the shared conversation protocol."""

import json
import os
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro.agent.codex_transport import codex_error_message

CONTEXT_TAIL_BYTES = 256 * 1024
TEXT_DELTAS = {
    "item/agentMessage/delta": "text",
    "item/plan/delta": "text",
    "item/reasoning/summaryTextDelta": "thinking",
}
TOOL_NAMES = {
    "commandExecution": "Bash",
    "fileChange": "Codex: alterações em arquivos",
    "webSearch": "WebSearch",
    "imageView": "Visualização de imagem",
    "imageGeneration": "Geração de imagem",
    "collabAgentToolCall": "Codex: subagente",
    "collabToolCall": "Codex: subagente",
}


def object_of(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def objects_of(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def string_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def int_of(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _image_marker(block: dict[str, Any]) -> dict[str, Any]:
    """{type, media_type, size} of a replayed image; only inline data reveals them."""
    url = string_of(block.get("url")) if block.get("type") == "image" else ""
    header, sep, data = url.partition(",")
    if sep and header.startswith("data:") and header.endswith(";base64"):
        media_type = header[len("data:"):-len(";base64")] or None
        padding = len(data) - len(data.rstrip("="))
        size = max(len(data) * 3 // 4 - padding, 0)
        return {"type": "image", "media_type": media_type, "size": size}
    return {"type": "image", "media_type": None, "size": None}


def _join_text(value: Any) -> str:
    return "\n".join(part for part in value if isinstance(part, str)) if isinstance(value, list) else ""


def codex_item_id(item_id: str) -> str:
    return f"codex-{item_id}"


def context_from_usage(
    usage: dict[str, Any], model: str | None, *, full: bool
) -> dict[str, Any] | None:
    last = object_of(usage.get("last"))
    limit = int_of(usage.get("modelContextWindow"))
    used = last.get("totalTokens")
    if type(used) is not int or used < 0 or not limit:
        return None
    context: dict[str, Any] = {"totalTokens": used, "rawMaxTokens": limit, "model": model}
    if full:
        request = min(int_of(last.get("inputTokens")), used)
        cache = min(int_of(last.get("cachedInputTokens")), request)
        output = min(int_of(last.get("outputTokens")), used - request)
        reasoning = min(int_of(last.get("reasoningOutputTokens")), output)
        context["categories"] = [
            {"name": name, "tokens": tokens, "kind": kind}
            for name, tokens, kind in (
                ("Entrada", request - cache, "used"),
                ("Entrada em cache", cache, "used"),
                ("Saída", output - reasoning, "used"),
                ("Raciocínio", reasoning, "used"),
                ("Outros tokens no contexto", used - request - output, "used"),
                ("Espaço livre", limit - used, "free"),
            )
            if tokens > 0
        ]
    return context


def read_rollout_usage(path: str, codex_home: Path, thread_id: str) -> dict[str, Any]:
    """Bounded fallback for older CLI versions that omit usage when resuming."""
    try:
        source = Path(path).resolve(strict=True)
        roots = (codex_home / "sessions", codex_home / "archived_sessions")
        if (
            source.suffix != ".jsonl"
            or not source.stem.endswith(f"-{thread_id}")
            or not any(source.is_relative_to(root.resolve()) for root in roots)
        ):
            return {}
        fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                return {}
            handle.seek(max(0, info.st_size - CONTEXT_TAIL_BYTES))
            lines = handle.read(CONTEXT_TAIL_BYTES).splitlines()
    except (OSError, RuntimeError, ValueError):
        return {}
    for line in reversed(lines):
        if b'"token_count"' not in line:
            continue
        try:
            event = object_of(json.loads(line))
        except (ValueError, UnicodeError):
            continue
        payload = object_of(event.get("payload"))
        info = object_of(payload.get("info"))
        if event.get("type") != "event_msg" or payload.get("type") != "token_count" or not info:
            continue
        usage = object_of(info.get("last_token_usage"))
        if "total_tokens" in usage:
            return {
                "modelContextWindow": info.get("model_context_window"),
                "last": {
                    "totalTokens": usage.get("total_tokens"),
                    "inputTokens": usage.get("input_tokens"),
                    "cachedInputTokens": usage.get("cached_input_tokens"),
                    "outputTokens": usage.get("output_tokens"),
                    "reasoningOutputTokens": usage.get("reasoning_output_tokens"),
                },
            }
    return {}


def native_input(content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
    prompt: list[dict[str, Any]] = []
    for block in objects_of(blocks):
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            prompt.append({"type": "text", "text": block["text"], "text_elements": []})
        elif block.get("type") == "image":
            source = object_of(block.get("source"))
            data = string_of(source.get("data"))
            if data:
                media = string_of(source.get("media_type")) or "image/png"
                prompt.append({"type": "image", "url": f"data:{media};base64,{data}"})
    return prompt


class CodexMessages:
    """One renderer for both live and historical thread items."""

    def __init__(self, session_id: str, emit: Callable[[Message], None]) -> None:
        self.session_id = session_id
        self.emit = emit
        self.model: str | None = None
        self.usage: dict[str, Any] = {}
        self._turn_usage: dict[str, int] | None = None
        self._starting_usage: dict[str, Any] = {}
        self._stream_item: str | None = None
        self._partial = ""
        self._stream_kind = "text"
        self._summary_index = 0
        self._shown_tools: set[str] = set()
        self._completed: set[str] = set()

    def begin_turn(self) -> None:
        self.end_turn()
        self._turn_usage = None
        self._starting_usage = object_of(self.usage.get("total"))
        self._shown_tools.clear()
        self._completed.clear()

    def end_turn(self) -> None:
        if self._stream_item is not None:
            self._finish_stream(self._partial)

    def _assistant(
        self, item_id: str, content: list[TextBlock | ThinkingBlock | ToolUseBlock]
    ) -> None:
        self.emit(AssistantMessage(
            content=content, model=self.model or "codex", session_id=self.session_id,
            message_id=item_id, uuid=item_id,
        ))

    def init(self, permission_mode: str) -> None:
        self.emit(SystemMessage("init", {
            "session_id": self.session_id,
            "model": self.model,
            "permissionMode": permission_mode,
        }))

    def _stream(self, kind: str, **fields: Any) -> None:
        self.emit(StreamEvent(uuid.uuid4().hex, self.session_id, {"type": kind, **fields}))

    def delta(self, method: str, params: dict[str, Any]) -> None:
        native_id, fragment = string_of(params.get("itemId")), string_of(params.get("delta"))
        if not native_id or not fragment:
            return
        item_id = codex_item_id(native_id)
        if item_id in self._completed or self._stream_item not in (None, item_id):
            return
        block_type = TEXT_DELTAS[method]
        if self._stream_item is None:
            self._stream_item, self._partial, self._stream_kind = item_id, "", block_type
            self._summary_index = int_of(params.get("summaryIndex"))
            self._stream("message_start", message={"id": item_id})
            self._stream("content_block_start", index=0, content_block={"type": block_type})
        if block_type == "thinking":
            summary_index = int_of(params.get("summaryIndex"))
            if summary_index > self._summary_index:
                fragment = f"\n{fragment}"
                self._summary_index = summary_index
        self._partial += fragment
        self._stream("content_block_delta", index=0, delta={
            "type": f"{block_type}_delta", block_type: fragment,
        })

    def _finish_stream(self, text: str) -> None:
        item_id = self._stream_item
        if item_id is None:
            return
        block = ThinkingBlock(text, "") if self._stream_kind == "thinking" else TextBlock(text)
        # The builder attaches the final block to the open index of this message.
        self._assistant(item_id, [block])
        self._stream("content_block_stop", index=0)
        self._completed.add(item_id)
        self._stream_item, self._partial = None, ""

    def item(self, item: dict[str, Any], *, completed: bool, replay: bool = False) -> None:
        native_id, kind = string_of(item.get("id")), string_of(item.get("type"))
        if not native_id:
            return
        item_id = codex_item_id(native_id)
        if item_id in self._completed:
            return
        if kind == "userMessage":
            if replay and completed:
                self._replay_user(item_id, item)
        elif kind in {"agentMessage", "plan", "reasoning"}:
            if completed:
                self._complete_text(item_id, kind, item)
        elif kind == "contextCompaction":
            if completed:
                self.emit(UserMessage(
                    "<local-command-stdout>Conversa compactada</local-command-stdout>"
                ))
        else:
            self._tool(item_id, kind, item, completed=completed)

        if completed:
            self._completed.add(item_id)

    def _complete_text(self, item_id: str, kind: str, item: dict[str, Any]) -> None:
        if kind == "reasoning":
            text = _join_text(item.get("summary")) or _join_text(item.get("content"))
        else:
            text = string_of(item.get("text"))
        if item_id == self._stream_item:
            self._finish_stream(text or self._partial)
        elif text:
            block = ThinkingBlock(text, "") if kind == "reasoning" else TextBlock(text)
            self._assistant(item_id, [block])

    def _replay_user(self, item_id: str, item: dict[str, Any]) -> None:
        text = "\n".join(
            string_of(block.get("text")) for block in objects_of(item.get("content"))
            if block.get("type") == "text"
        )
        images = [
            _image_marker(block) for block in objects_of(item.get("content"))
            if block.get("type") in {"image", "localImage"}
        ]
        if not text and not images:
            return
        identity = string_of(item.get("clientId")) or item_id
        # Images become light markers: the history keeps no base64, URL or path.
        origin: dict[str, Any] = (
            {"kind": "codex_replay", "images": images} if images else {"kind": "human"}
        )
        self.emit(UserMessage(text, uuid=identity, origin=origin))

    def _tool(self, item_id: str, kind: str, item: dict[str, Any], *, completed: bool) -> None:
        name = TOOL_NAMES.get(kind)
        if kind in {"mcpToolCall", "dynamicToolCall"}:
            tool = string_of(item.get("tool"))
            server = string_of(item.get("server"))
            name = f"mcp__{server}__{tool}" if server and tool else tool
        if not name:
            return
        if item_id not in self._shown_tools:
            self._shown_tools.add(item_id)
            content = object_of(item.get("arguments")) if "arguments" in item else {
                key: item[key] for key in ("command", "cwd", "query", "changes", "path", "tool", "prompt")
                if key in item
            }
            self._assistant(item_id, [ToolUseBlock(id=item_id, name=name, input=content)])
        if not completed:
            return
        output = next((
            item[key] for key in ("aggregatedOutput", "error", "result", "contentItems", "changes", "results")
            if item.get(key) is not None
        ), "")
        error = item.get("status") in {"failed", "declined", "interrupted"} or item.get("success") is False
        self.emit(UserMessage([
            ToolResultBlock(tool_use_id=item_id, content=output, is_error=error),
        ], uuid=f"{item_id}-result"))

    def update_usage(self, usage: dict[str, Any]) -> None:
        if not usage:
            return
        self.usage = usage
        current = object_of(usage.get("total"))
        last = object_of(usage.get("last"))
        self._turn_usage = {}
        for source, field in (
            ("inputTokens", "input_tokens"),
            ("outputTokens", "output_tokens"),
            ("cachedInputTokens", "cache_read_input_tokens"),
        ):
            initial, total = self._starting_usage.get(source), current.get(source)
            if type(initial) is int and type(total) is int and total >= initial:
                self._turn_usage[field] = total - initial
            else:
                self._turn_usage[field] = int_of(last.get(source))

    def result(self, turn: dict[str, Any], error: str | None = None) -> ResultMessage:
        status = turn.get("status")
        failed = status == "failed" or error is not None
        terminal = "aborted_streaming" if status == "interrupted" else None
        detail = object_of(turn.get("error"))
        if failed and error is None:
            error = codex_error_message(detail.get("message"), detail.get("codexErrorInfo"))
        return ResultMessage(
            subtype="error_during_execution" if failed else "success",
            duration_ms=int_of(turn.get("durationMs")), duration_api_ms=0, num_turns=1,
            is_error=failed, session_id=self.session_id, result=error,
            terminal_reason=terminal, usage=self._turn_usage,
        )
