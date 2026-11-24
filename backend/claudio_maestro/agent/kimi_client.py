"""Kimi Code client over ACP (`kimi acp`): JSON-RPC on the process's stdio.

Implements the AgentClient protocol by translating ACP `session/update`
notifications into the SDK message types the rest of the app understands
(`StreamEvent`, `AssistantMessage`, `UserMessage`, `ResultMessage`), so the
conversation pipeline works unchanged for both providers.

Live text and thinking chunks become Anthropic-style stream events (one
`message_start` per assistant segment, `content_block_*` per chunk), closed by
a complete `AssistantMessage` with the same message id — the same shape the
Claude SDK produces. During a `session/load` replay there are no stream
events: the replayed chunks are grouped into complete messages, so they never
open a turn.

Verified against `kimi acp` 2.7.3 (`tests/test_kimi_client.py` uses a fake
process with the same message shapes).
"""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    PermissionResultAllow,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro.agent.base import AgentError, AgentOptions

logger = logging.getLogger(__name__)

CLI_NOT_FOUND_MESSAGE = (
    "O comando `kimi` não foi encontrado nesta máquina. "
    "Instale o Kimi Code (https://www.kimi.com/code) e faça login com `kimi`."
)
LOGIN_MESSAGE = "O login do Kimi expirou ou é inválido. Rode `kimi` no terminal e faça /login."
PROCESS_DIED_MESSAGE = "O processo do Kimi encerrou inesperadamente."
# A single ACP line can carry a whole tool output; the default 64 KiB stream
# limit would cut it.
STREAM_LIMIT = 64 * 1024 * 1024

# The app's effort levels (`EFFORTS`) as Kimi thinking levels.
EFFORT_TO_THINKING = {"low": "low", "medium": "low", "high": "high", "xhigh": "max", "max": "max"}
# The app's permission modes as Kimi modes (default, plan, auto, yolo).
MODE_TO_KIMI = {
    "default": "default",
    "plan": "plan",
    "acceptEdits": "auto",
    "auto": "auto",
    "dontAsk": "yolo",
    "bypassPermissions": "yolo",
}

_CLOSED = object()  # sentinel of the message queue: close() was called

# ACP does not expose the context window usage, but the CLI logs every step's
# token usage in the session's wire.jsonl. The window of the current kimi-code
# models is 256K (the "-256k" variant names it); it is an approximation.
KIMI_CONTEXT_WINDOW = 256_000
# Only the tail of wire.jsonl is read: it grows with the whole session.
WIRE_TAIL_BYTES = 256 * 1024
_USAGE_RE = re.compile(rb'"usage":\{([^{}]*)\}')
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def kimi_sessions_root() -> Path:
    """Where the CLI keeps its sessions (`MAESTRO_KIMI_SESSIONS` overrides, for tests)."""
    override = os.environ.get("MAESTRO_KIMI_SESSIONS")
    return Path(override) if override else Path.home() / ".kimi-code" / "sessions"


def wire_context(provider_session_id: str) -> dict[str, Any] | None:
    """`{"totalTokens", "rawMaxTokens"}` from the last step usage of a Kimi session.

    None when the session has no wire log yet (no turn ran) or it is unreadable.
    The log is internal to the CLI: a format change only costs the context meter.
    """
    if not _SESSION_ID_RE.match(provider_session_id):
        return None
    try:
        matches = sorted(
            kimi_sessions_root().glob(f"*/{provider_session_id}/agents/main/wire.jsonl")
        )
    except OSError:
        return None
    if not matches:
        return None
    path = matches[0]
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > WIRE_TAIL_BYTES:
                handle.seek(-WIRE_TAIL_BYTES, os.SEEK_END)
            tail = handle.read()
    except OSError:
        return None
    found = _USAGE_RE.findall(tail)
    if not found:
        return None
    try:
        usage = json.loads(b"{" + found[-1] + b"}")
    except ValueError:
        return None

    def tokens(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    # Cached input still occupies the window.
    used = tokens("inputOther") + tokens("inputCacheRead") + tokens("inputCacheCreation")
    if used <= 0:
        return None
    return {"totalTokens": used, "rawMaxTokens": KIMI_CONTEXT_WINDOW}


def kimi_binary() -> str | None:
    """The `kimi` executable: `MAESTRO_KIMI_CLI`, the PATH, or the official installer folder."""
    override = os.environ.get("MAESTRO_KIMI_CLI")
    if override:
        return override
    found = shutil.which("kimi")
    if found:
        return found
    fallback = Path.home() / ".kimi-code" / "bin" / "kimi"
    return str(fallback) if fallback.is_file() else None


def _text_of(content: Any) -> str:
    """Text of an ACP content block or a list of them. A block is
    `{"type": "text", "text": ...}` or wrapped as `{"type": "content", "content": block}`."""
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        return _text_of(content.get("content"))
    if isinstance(content, list):
        return "".join(_text_of(part) for part in content)
    return ""


class KimiAgentClient:
    """AgentClient backed by a `kimi acp` process."""

    provider = "kimi"

    def __init__(self, options: AgentOptions, command: list[str] | None = None) -> None:
        self.options = options
        self.provider_session_id: str | None = None
        self._command = command  # tests replace the process
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._closing = False
        # Config options of the session (model, thinking, mode), from session/new
        # or session/load and every config_option_update.
        self._config_options: list[dict[str, Any]] = []
        # True between the session/load request and its response: replayed updates
        # become complete messages, never stream events.
        self._replaying = False
        # Current assistant segment (live): message id, blocks and the open block.
        self._seg_id: str | None = None
        self._seg_blocks: list[dict[str, Any]] = []
        self._seg_open: int | None = None
        # Replayed assistant text, grouped into complete messages.
        self._replay_blocks: list[dict[str, Any]] = []
        # Replayed user chunks, grouped into one message per run.
        self._user_buffer: list[str] = []
        # Tool calls by ACP id: title, streamed input text, parsed input, emission state.
        self._tools: dict[str, dict[str, Any]] = {}
        # One turn at a time: the CLI refuses a prompt sent mid-turn
        # (`turn.agent_busy`), so sends wait for the running turn to end.
        self._turn_lock = asyncio.Lock()

    # Connection --------------------------------------------------------------

    async def connect(self) -> None:
        command = self._command or [kimi_binary() or "kimi", "acp"]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self.options.cwd),
                env=dict(os.environ),
                limit=STREAM_LIMIT,
            )
        except FileNotFoundError as error:
            raise AgentError(CLI_NOT_FOUND_MESSAGE) from error
        except OSError as error:
            raise AgentError(f"Não foi possível iniciar o Kimi: {error}") from error
        self._reader = asyncio.create_task(self._read_lines())
        try:
            await self._call(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "claudio-maestro", "version": "0"},
                },
            )
            await self._open_session()
            await self._apply_initial_config()
        except AgentError:
            await self.close()
            raise
        except Exception as error:
            await self.close()
            raise AgentError(f"Não foi possível conectar ao Kimi: {error}") from error

    async def _open_session(self) -> None:
        """session/new, or session/load when resuming a conversation the CLI knows."""
        params = {"cwd": str(self.options.cwd), "mcpServers": []}
        if self.options.resume and self.options.provider_session_id:
            self._replaying = True
            try:
                result = await self._call(
                    "session/load", {**params, "sessionId": self.options.provider_session_id}
                )
                self.provider_session_id = self.options.provider_session_id
                self._keep_config(result)
                self._flush_replay()
                return
            except AgentError as error:
                # The CLI no longer has the conversation: start a new one instead
                # of failing the session.
                logger.warning(
                    "Kimi não retomou a sessão %s (%s); começando uma nova",
                    self.options.provider_session_id,
                    error.message_pt,
                )
            finally:
                self._replaying = False
        result = await self._call("session/new", params)
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise AgentError("O Kimi não devolveu o id da sessão.")
        self.provider_session_id = session_id
        self._keep_config(result)

    async def _apply_initial_config(self) -> None:
        """Model, thinking and mode chosen in the app, applied to the new session."""
        if self.options.model:
            await self._set_config("model", self.options.model, quiet=True)
        if self.options.effort:
            thinking = EFFORT_TO_THINKING.get(self.options.effort)
            if thinking:
                await self._set_config("thinking", thinking, quiet=True)
        if self.options.permission_mode:
            mode = MODE_TO_KIMI.get(self.options.permission_mode)
            if mode:
                await self._set_config("mode", mode, quiet=True)

    async def _set_config(self, config_id: str, value: str, *, quiet: bool = False) -> None:
        """One `session/set_config_option`; `quiet` logs instead of raising (connect)."""
        if self.provider_session_id is None:
            return
        try:
            result = await self._call(
                "session/set_config_option",
                {"sessionId": self.provider_session_id, "configId": config_id, "value": value},
            )
            self._keep_config(result)
        except AgentError:
            if not quiet:
                raise
            logger.warning("Kimi recusou %s=%s na abertura", config_id, value, exc_info=True)

    def _keep_config(self, result: dict[str, Any]) -> None:
        options = result.get("configOptions")
        if isinstance(options, list):
            self._config_options = [o for o in options if isinstance(o, dict)]

    # JSON-RPC ----------------------------------------------------------------

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise AgentError(PROCESS_DIED_MESSAGE)
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    def _write(self, message: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _read_lines(self) -> None:
        """Route every line of the process: responses, agent requests, notifications."""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except ValueError:
                    logger.warning("Linha ilegível do Kimi: %.200s", line)
                    continue
                self._route(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao ler a saída do Kimi")
        finally:
            self._on_eof()

    def _route(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            future = self._pending.get(message["id"])
            if future is None or future.done():
                return
            error = message.get("error")
            if error is not None:
                text = error.get("message") if isinstance(error, dict) else str(error)
                future.set_exception(AgentError(_login_text(text)))
            else:
                future.set_result(message.get("result") or {})
        elif "method" in message and "id" in message:
            # A request from the agent: it must be answered in another task, or the
            # read loop would stall behind a permission the user has not answered.
            asyncio.ensure_future(self._answer_request(message))
        elif message.get("method") == "session/update":
            params = message.get("params") or {}
            self._on_update(params.get("update") or {})

    async def _answer_request(self, message: dict[str, Any]) -> None:
        method = message["method"]
        params = message.get("params") or {}
        try:
            if method == "session/request_permission":
                result = await self._on_permission(params)
            else:
                # fs/* and terminal/*: not offered in our capabilities; refuse anyway.
                self._write({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"Método não suportado: {method}"},
                })
                return
        except Exception:
            logger.exception("Falha ao atender %s do Kimi", method)
            result = {"outcome": {"outcome": "cancelled"}}
        self._write({"jsonrpc": "2.0", "id": message["id"], "result": result})

    async def _on_permission(self, params: dict[str, Any]) -> dict[str, Any]:
        """The agent asks before a tool: the app's permission prompt answers it."""
        tool_call = params.get("toolCall") or {}
        tool_use_id = tool_call.get("toolCallId") or ""
        title = tool_call.get("title") or "ferramenta"
        state = self._tools.get(tool_use_id) or {}
        tool_input = state.get("input") if isinstance(state.get("input"), dict) else {}
        description = _text_of(tool_call.get("content")) or None
        context = ToolPermissionContext(
            tool_use_id=tool_use_id,
            suggestions=[],
            title=title,
            display_name=title,
            description=description,
        )
        result = await self.options.can_use_tool(title, tool_input, context)
        options = [o for o in params.get("options") or [] if isinstance(o, dict)]

        def option_id(*kinds: str) -> str | None:
            for kind in kinds:
                for option in options:
                    if option.get("kind") == kind and isinstance(option.get("optionId"), str):
                        return option["optionId"]
            return None

        if isinstance(result, PermissionResultAllow):
            chosen = (
                option_id("allow_always", "allow_once")
                if result.updated_permissions
                else option_id("allow_once", "allow_always")
            )
        else:
            chosen = option_id("reject_once", "reject_always")
        if chosen is None:
            return {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "selected", "optionId": chosen}}

    def _on_eof(self) -> None:
        """The process ended: pending calls fail and the message stream closes."""
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(AgentError(PROCESS_DIED_MESSAGE))
        if not self._closing:
            self._queue.put_nowait(_CLOSED)

    # ACP updates -> SDK messages ----------------------------------------------

    def _on_update(self, update: dict[str, Any]) -> None:
        kind = update.get("sessionUpdate")
        if kind in ("agent_message_chunk", "agent_thought_chunk"):
            self._flush_user_buffer()
            thinking = kind == "agent_thought_chunk"
            text = _text_of(update.get("content"))
            if not text:
                return
            if self._replaying:
                self._replay_chunk(thinking, text)
            else:
                self._live_chunk(thinking, text)
        elif kind == "user_message_chunk":
            self._flush_segment()
            self._user_buffer.append(_text_of(update.get("content")))
        elif kind == "tool_call":
            self._flush_user_buffer()
            self._flush_segment()
            self._flush_replay_blocks()
            self._on_tool_call(update)
        elif kind == "tool_call_update":
            self._flush_user_buffer()
            self._flush_segment()
            self._flush_replay_blocks()
            self._on_tool_call_update(update)
        elif kind == "config_option_update":
            self._keep_config(update)
        # session_info_update, available_commands_update, plan: nothing the app shows.

    # Assistant text: live streaming --------------------------------------------

    def _stream(self, event: dict[str, Any]) -> None:
        self._queue.put_nowait(
            StreamEvent(
                uuid=uuid.uuid4().hex,
                session_id=self.options.session_id,
                event=event,
                parent_tool_use_id=None,
            )
        )

    def _live_chunk(self, thinking: bool, text: str) -> None:
        if self._seg_id is None:
            self._seg_id = f"kimi-{uuid.uuid4().hex}"
            self._seg_blocks = []
            self._seg_open = None
            self._stream({"type": "message_start", "message": {"id": self._seg_id}})
        block_type = "thinking" if thinking else "text"
        open_block = self._seg_blocks[self._seg_open] if self._seg_open is not None else None
        if open_block is None or open_block["type"] != block_type:
            if self._seg_open is not None:
                self._stream({"type": "content_block_stop", "index": self._seg_open})
            index = len(self._seg_blocks)
            block = {"index": index, "type": block_type, "text": ""}
            self._seg_blocks.append(block)
            self._seg_open = index
            start = (
                {"type": "thinking", "thinking": ""}
                if thinking
                else {"type": "text", "text": ""}
            )
            self._stream({"type": "content_block_start", "index": index, "content_block": start})
            open_block = block
        open_block["text"] += text
        delta = (
            {"type": "thinking_delta", "thinking": text}
            if thinking
            else {"type": "text_delta", "text": text}
        )
        self._stream({"type": "content_block_delta", "index": open_block["index"], "delta": delta})

    def _flush_segment(self) -> None:
        """Close the live segment with the complete assistant message (same id)."""
        if self._seg_id is None:
            return
        if self._seg_open is not None:
            self._stream({"type": "content_block_stop", "index": self._seg_open})
        content: list[Any] = [
            ThinkingBlock(thinking=block["text"], signature="")
            if block["type"] == "thinking"
            else TextBlock(text=block["text"])
            for block in self._seg_blocks
            if block["text"]
        ]
        message_id, self._seg_id, self._seg_blocks, self._seg_open = self._seg_id, None, [], None
        if content:
            self._queue.put_nowait(self._assistant(content, message_id=message_id))

    # Assistant text: replay (session/load) --------------------------------------

    def _replay_chunk(self, thinking: bool, text: str) -> None:
        block_type = "thinking" if thinking else "text"
        if self._replay_blocks and self._replay_blocks[-1]["type"] == block_type:
            self._replay_blocks[-1]["text"] += text
        else:
            self._replay_blocks.append({"type": block_type, "text": text})

    def _flush_replay_blocks(self) -> None:
        if not self._replay_blocks:
            return
        content: list[Any] = [
            ThinkingBlock(thinking=block["text"], signature="")
            if block["type"] == "thinking"
            else TextBlock(text=block["text"])
            for block in self._replay_blocks
            if block["text"]
        ]
        self._replay_blocks = []
        if content:
            self._queue.put_nowait(self._assistant(content, message_id=f"kimi-{uuid.uuid4().hex}"))

    def _flush_replay(self) -> None:
        """End of the session/load replay: nothing stays buffered."""
        self._flush_replay_blocks()
        self._flush_user_buffer()

    # Tools ----------------------------------------------------------------------

    def _on_tool_call(self, update: dict[str, Any]) -> None:
        tool_use_id = update.get("toolCallId") or f"kimi-tool-{uuid.uuid4().hex}"
        state = {
            "title": update.get("title") or "ferramenta",
            "input_text": "",
            "input": update.get("rawInput") if isinstance(update.get("rawInput"), dict) else None,
            "use_emitted": False,
        }
        self._tools[tool_use_id] = state
        if state["input"] is not None:
            self._emit_tool_use(tool_use_id)

    def _on_tool_call_update(self, update: dict[str, Any]) -> None:
        tool_use_id = update.get("toolCallId") or ""
        state = self._tools.get(tool_use_id)
        if state is None:
            state = {"title": "ferramenta", "input_text": "", "input": None, "use_emitted": False}
            self._tools[tool_use_id] = state
        raw_input = update.get("rawInput")
        if isinstance(raw_input, dict):
            state["input"] = raw_input
        elif update.get("status") == "in_progress":
            state["input_text"] += _text_of(update.get("content"))
            if state["input"] is None:
                state["input"] = _parse_json_object(state["input_text"])
        status = update.get("status")
        if status not in ("completed", "failed"):
            if state["input"] is not None:
                self._emit_tool_use(tool_use_id)
            return
        self._emit_tool_use(tool_use_id)
        output = update.get("rawOutput")
        if not isinstance(output, str):
            output = _text_of(update.get("content"))
        self._flush_user_buffer()
        self._queue.put_nowait(
            UserMessage(
                content=[ToolResultBlock(
                    tool_use_id=tool_use_id, content=output, is_error=status == "failed"
                )],
                uuid=uuid.uuid4().hex,
                parent_tool_use_id=None,
                tool_use_result=None,
                origin=None,
            )
        )

    def _emit_tool_use(self, tool_use_id: str) -> None:
        state = self._tools.get(tool_use_id)
        if state is None or state["use_emitted"]:
            return
        state["use_emitted"] = True
        tool_input = state["input"] if isinstance(state["input"], dict) else {}
        self._queue.put_nowait(
            self._assistant(
                [ToolUseBlock(id=tool_use_id, name=state["title"], input=tool_input)],
                message_id=f"kimi-{uuid.uuid4().hex}",
            )
        )

    # Messages -------------------------------------------------------------------

    def _assistant(self, content: list[Any], *, message_id: str) -> AssistantMessage:
        return AssistantMessage(
            content=content,
            model=self._current_model() or "kimi",
            parent_tool_use_id=None,
            error=None,
            usage=None,
            message_id=message_id,
            stop_reason=None,
            session_id=self.options.session_id,
            uuid=uuid.uuid4().hex,
        )

    def _current_model(self) -> str | None:
        for option in self._config_options:
            if option.get("id") == "model":
                value = option.get("currentValue")
                return value if isinstance(value, str) else None
        return None

    def _flush_user_buffer(self) -> None:
        if not self._user_buffer:
            return
        text = "".join(self._user_buffer)
        self._user_buffer = []
        if not text.strip():
            return
        self._queue.put_nowait(
            UserMessage(
                content=text,
                uuid=uuid.uuid4().hex,
                parent_tool_use_id=None,
                tool_use_result=None,
                origin={"kind": "human"},
            )
        )

    # AgentClient protocol ---------------------------------------------------------

    async def send(self, content: str | list[dict[str, Any]], *, message_id: str | None = None) -> None:
        if self.provider_session_id is None:
            raise AgentError(PROCESS_DIED_MESSAGE)
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        prompt: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                prompt.append({"type": "text", "text": block["text"]})
            elif block.get("type") == "image":
                source = block.get("source") or {}
                if isinstance(source.get("data"), str):
                    prompt.append({
                        "type": "image",
                        "data": source["data"],
                        "mimeType": source.get("media_type") or "image/png",
                    })
        if not prompt:
            raise AgentError("A mensagem está vazia.")
        self._flush_segment()
        # The answer comes in a task: send() returns once the prompt is written,
        # like the SDK's query(), and the ResultMessage closes the turn.
        asyncio.ensure_future(self._run_prompt(prompt))

    async def _run_prompt(self, prompt: list[dict[str, Any]]) -> None:
        # The lock serializes turns: a message sent mid-turn waits for the running
        # one instead of being refused with `turn.agent_busy`.
        async with self._turn_lock:
            try:
                result = await self._call(
                    "session/prompt", {"sessionId": self.provider_session_id, "prompt": prompt}
                )
            except AgentError as error:
                self._flush_segment()
                self._queue.put_nowait(self._result(is_error=True, text=error.message_pt))
                return
            self._flush_segment()
            self._flush_user_buffer()
            stop_reason = result.get("stopReason")
            self._queue.put_nowait(
                self._result(is_error=False, stop_reason=stop_reason if isinstance(stop_reason, str) else None)
            )

    def _result(
        self, *, is_error: bool, text: str | None = None, stop_reason: str | None = None
    ) -> ResultMessage:
        return ResultMessage(
            subtype="error_during_execution" if is_error else "success",
            duration_ms=0,
            duration_api_ms=0,
            is_error=is_error,
            num_turns=1,
            session_id=self.options.session_id,
            stop_reason=stop_reason,
            total_cost_usd=None,
            usage=None,
            result=text,
        )

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            yield item

    async def interrupt(self) -> None:
        self._notify("session/cancel", {"sessionId": self.provider_session_id})

    async def stop_task(self, task_id: str) -> None:
        return None  # Kimi background tasks are not exposed over ACP.

    async def set_model(self, model: str | None) -> None:
        if model is None:
            raise AgentError("O Kimi não tem um modelo padrão para voltar.", refused=True)
        await self._set_config("model", model)

    async def set_permission_mode(self, mode: str) -> None:
        kimi_mode = MODE_TO_KIMI.get(mode)
        if kimi_mode is None:
            raise AgentError(f"O Kimi não tem o modo {mode}.", refused=True)
        await self._set_config("mode", kimi_mode)

    async def set_effort(self, effort: str) -> None:
        thinking = EFFORT_TO_THINKING.get(effort)
        if thinking is None:
            raise AgentError(f"O Kimi não tem o raciocínio {effort}.", refused=True)
        await self._set_config("thinking", thinking)

    async def set_remote_control(
        self,
        enabled: bool,
        *,
        name: str | None = None,
        reattach_session_id: str | None = None,
    ) -> dict[str, Any]:
        raise AgentError("O Remote Control só existe nas sessões do Claude Code.", refused=True)

    async def get_server_info(self) -> dict[str, Any] | None:
        models = []
        for option in self._config_options:
            if option.get("id") != "model":
                continue
            for choice in option.get("options") or []:
                if isinstance(choice, dict) and isinstance(choice.get("value"), str):
                    models.append({
                        "value": choice["value"],
                        "displayName": choice.get("name") or choice["value"],
                        "description": choice.get("description") or "",
                        # The app's effort levels map to Kimi's thinking levels
                        # (EFFORT_TO_THINKING); the menu offers the three it has.
                        "supportsEffort": True,
                        "supportedEffortLevels": ["low", "high", "max"],
                    })
        return {"models": models} if models else None

    async def get_context_usage(self, detail: str = "full") -> dict[str, Any] | None:
        # ACP has no usage request: the totals come from the session's wire log.
        if self.provider_session_id is None:
            return None
        return await asyncio.to_thread(wire_context, self.provider_session_id)

    async def detach(self) -> bool:
        return False  # Without the agentd, the process does not outlive the app.

    async def close(self) -> None:
        self._closing = True
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (TimeoutError, asyncio.TimeoutError):
                logger.warning("O processo do Kimi não encerrou a tempo")
        self._queue.put_nowait(_CLOSED)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _login_text(text: Any) -> str:
    """A readable message for a JSON-RPC error, pointing at /login when it is auth."""
    message = str(text) if text else "Falha no Kimi."
    lowered = message.lower()
    if "auth" in lowered or "login" in lowered or "unauthorized" in lowered:
        return LOGIN_MESSAGE
    return f"Falha no Kimi: {message}"
