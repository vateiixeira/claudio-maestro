"""Scripted fake agent client for tests. Starts no external process.

A script is a function called on every `send` with the content sent; it returns
the steps of that turn. Steps are SDK messages (delivered by `messages()`) or
one of the control steps below. Turns run one after another, in send order.

    client = FakeAgentClient(options, script=scripted(
        text_turn(session_id, "olá"),
        tool_turn(session_id, tool_name="Write", ask_permission=True),
    ))

The helpers at the bottom build the same message sequences the real SDK emits
with `include_partial_messages=True`.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ContentBlock,
    Message,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from vibing.agent.base import AgentError, AgentOptions

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_FAILURE = "O processo do agente encerrou inesperadamente."
# Shape of `get_server_info()["models"]` in the real SDK (0.2.161).
DEFAULT_SERVER_MODELS: list[dict[str, Any]] = [
    {
        "value": "default",
        "displayName": "Default (recommended)",
        "description": "Opus 5.5",
        "supportsEffort": True,
        "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"],
    },
    {
        "value": "haiku",
        "displayName": "Haiku",
        "description": "Haiku 4.5",
        "supportsEffort": False,
        "supportedEffortLevels": [],
    },
]
# Texts the real SDK sends when interrupt() cancels a pending permission.
INTERRUPTED_FOR_TOOL_USE = "[Request interrupted by user for tool use]"
TOOL_USE_REJECTED = (
    "The user doesn't want to proceed with this tool use. The tool use was rejected"
    " (eg. if it was a file edit, the new_string was NOT written to the file)."
    " STOP what you are doing and wait for the user to tell you how to proceed."
)


# Control steps -------------------------------------------------------------


@dataclass
class PermissionStep:
    """Calls `options.can_use_tool` and waits for the answer."""

    tool_name: str
    input: dict[str, Any]
    tool_use_id: str | None = None
    suggestions: list[PermissionUpdate] = field(default_factory=list)


@dataclass
class FailStep:
    """The process dies: `messages()` raises AgentError, later sends fail."""

    message: str = DEFAULT_FAILURE


@dataclass
class PauseStep:
    """Holds the turn until the test sets `release`. Sets `reached` when it gets there."""

    release: asyncio.Event = field(default_factory=asyncio.Event)
    reached: asyncio.Event = field(default_factory=asyncio.Event)


Step = Message | PermissionStep | FailStep | PauseStep
Script = Callable[[str | list[dict[str, Any]]], Iterable[Step]]
# A fixed error, or one chosen from the options (e.g. fail only without resume).
ConnectError = AgentError | Callable[[AgentOptions], AgentError | None]


@dataclass
class PermissionRecord:
    tool_name: str
    input: dict[str, Any]
    context: ToolPermissionContext
    result: PermissionResultAllow | PermissionResultDeny


def scripted(*turns: Iterable[Step]) -> Script:
    """Script that plays the given turns in order, one per send. Extra sends get no steps."""
    pending = [list(turn) for turn in turns]

    def script(content: str | list[dict[str, Any]]) -> list[Step]:
        return pending.pop(0) if pending else []

    return script


class _Closed:
    pass


@dataclass
class _Failure:
    message: str


# Client --------------------------------------------------------------------


class FakeAgentClient:
    """AgentClient without a process. Records everything it receives."""

    def __init__(
        self,
        options: AgentOptions,
        script: Script | None = None,
        connect_error: ConnectError | None = None,
        server_info: dict[str, Any] | None = None,
    ) -> None:
        self.options = options
        self.script: Script = script or (lambda content: [])
        self.connect_error = connect_error
        self.server_info = (
            server_info if server_info is not None else {"models": DEFAULT_SERVER_MODELS}
        )
        self.server_info_calls = 0
        # Answer of `get_context_usage()` (SDK format); None: no data.
        self.context_usage: dict[str, Any] | None = None
        self.context_usage_calls = 0
        # When set, close() stops here until the test releases it.
        self.close_pause: PauseStep | None = None

        self.sent: list[str | list[dict[str, Any]]] = []
        self.interrupts = 0
        self.stopped_tasks: list[str] = []
        self.model_calls: list[str | None] = []
        self.permission_mode_calls: list[str] = []
        # Raised by set_model / set_permission_mode (after recording the call).
        self.set_model_error: AgentError | None = None
        self.set_permission_mode_error: AgentError | None = None
        self.permission_results: list[PermissionRecord] = []
        self.connected = False
        self.closed = False
        self.failed = False

        self._turns: asyncio.Queue[list[Step]] = asyncio.Queue()
        self._out: asyncio.Queue[Message | _Failure | _Closed] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._current: asyncio.Task[None] | None = None
        self._pending_tool_use_id: str | None = None

    async def connect(self) -> None:
        error = self.connect_error
        if callable(error):
            error = error(self.options)
        if error is not None:
            raise error
        self.connected = True
        self._worker = asyncio.create_task(self._run_turns())

    async def send(self, content: str | list[dict[str, Any]]) -> None:
        if not self.connected or self.closed:
            raise AgentError("O agente não está conectado.")
        if self.failed:
            raise AgentError(DEFAULT_FAILURE)
        self.sent.append(content)
        await self._turns.put(list(self.script(content)))

    def push(self, steps: Iterable[Step]) -> None:
        """A turn the CLI opens by itself (e.g. a background subagent finished):
        played like a sent turn, but without anything in `sent`."""
        self._turns.put_nowait(list(steps))

    async def get_server_info(self) -> dict[str, Any] | None:
        self.server_info_calls += 1
        return self.server_info

    async def get_context_usage(self) -> dict[str, Any] | None:
        self.context_usage_calls += 1
        return self.context_usage

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            item = await self._out.get()
            if isinstance(item, _Closed):
                return
            if isinstance(item, _Failure):
                raise AgentError(item.message)
            yield item

    async def interrupt(self) -> None:
        """Mirrors the real SDK: with a permission pending, the callback task is
        cancelled, the tool is refused and the turn ends with `aborted_tools`;
        otherwise it ends with `aborted_streaming`."""
        self.interrupts += 1
        current = self._current
        if current is None or current.done():
            return
        pending_tool_use_id = self._pending_tool_use_id
        current.cancel()
        await asyncio.wait([current])
        self._pending_tool_use_id = None
        reason = "aborted_streaming"
        if pending_tool_use_id is not None:
            reason = "aborted_tools"
            await self._out.put(
                tool_result_message(pending_tool_use_id, TOOL_USE_REJECTED, is_error=True)
            )
            await self._out.put(
                UserMessage(
                    content=[TextBlock(text=INTERRUPTED_FOR_TOOL_USE)],
                    uuid=str(uuid.uuid4()),
                )
            )
        await self._out.put(
            result_message(
                self.options.session_id,
                subtype="error_during_execution",
                is_error=True,
                terminal_reason=reason,
            )
        )

    async def stop_task(self, task_id: str) -> None:
        self.stopped_tasks.append(task_id)

    async def set_model(self, model: str | None) -> None:
        self.model_calls.append(model)
        if self.set_model_error is not None:
            raise self.set_model_error

    async def set_permission_mode(self, mode: str) -> None:
        self.permission_mode_calls.append(mode)
        if self.set_permission_mode_error is not None:
            raise self.set_permission_mode_error

    async def close(self) -> None:
        if self.close_pause is not None:
            self.close_pause.reached.set()
            await self.close_pause.release.wait()
        self.closed = True
        for task in (self._current, self._worker):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.wait([task])
        await self._out.put(_Closed())

    async def _run_turns(self) -> None:
        while not self.failed:
            steps = await self._turns.get()
            self._current = asyncio.create_task(self._run_steps(steps))
            try:
                await asyncio.wait([self._current])
            finally:
                if not self._current.done():
                    self._current.cancel()
                self._current = None

    async def _run_steps(self, steps: list[Step]) -> None:
        for step in steps:
            if isinstance(step, PermissionStep):
                await self._ask_permission(step)
            elif isinstance(step, FailStep):
                self.failed = True
                await self._out.put(_Failure(step.message))
                return
            elif isinstance(step, PauseStep):
                step.reached.set()
                await step.release.wait()
            else:
                await self._out.put(step)
            # Yield so tests observe messages one at a time, like a real stream.
            await asyncio.sleep(0)

    async def _ask_permission(self, step: PermissionStep) -> None:
        context = ToolPermissionContext(
            suggestions=list(step.suggestions),
            tool_use_id=step.tool_use_id or new_tool_use_id(),
            display_name=step.tool_name,
        )
        self._pending_tool_use_id = context.tool_use_id
        result = await self.options.can_use_tool(step.tool_name, step.input, context)
        self._pending_tool_use_id = None
        self.permission_results.append(
            PermissionRecord(step.tool_name, step.input, context, result)
        )


class FakeAgentFactory:
    """AgentFactory that builds FakeAgentClients and keeps them for inspection."""

    def __init__(
        self,
        script: Script | None = None,
        connect_error: ConnectError | None = None,
        server_info: dict[str, Any] | None = None,
    ) -> None:
        self.script = script
        self.connect_error = connect_error
        self.server_info = server_info
        self.clients: list[FakeAgentClient] = []

    def __call__(self, options: AgentOptions) -> FakeAgentClient:
        client = FakeAgentClient(options, self.script, self.connect_error, self.server_info)
        self.clients.append(client)
        return client


# Message helpers -----------------------------------------------------------


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def new_tool_use_id() -> str:
    return f"toolu_{uuid.uuid4().hex[:24]}"


def _stream(session_id: str, event: dict[str, Any], parent: str | None) -> StreamEvent:
    return StreamEvent(
        uuid=str(uuid.uuid4()), session_id=session_id, event=event, parent_tool_use_id=parent
    )


def init_message(
    session_id: str, model: str = DEFAULT_MODEL, permission_mode: str = "default"
) -> SystemMessage:
    return SystemMessage(
        subtype="init",
        data={
            "type": "system",
            "subtype": "init",
            "session_id": session_id,
            "model": model,
            "permissionMode": permission_mode,
            "cwd": "",
            "tools": [],
            "apiKeySource": "none",
        },
    )


def status_message(session_id: str) -> SystemMessage:
    return SystemMessage(
        subtype="status",
        data={"type": "system", "subtype": "status", "session_id": session_id},
    )


def response_messages(
    session_id: str,
    blocks: list[ContentBlock],
    *,
    message_id: str | None = None,
    model: str = DEFAULT_MODEL,
    parent_tool_use_id: str | None = None,
    stop_reason: str = "end_turn",
) -> list[Message]:
    """One assistant response streamed block by block, as the SDK emits it."""
    message_id = message_id or new_message_id()
    parent = parent_tool_use_id
    out: list[Message] = [
        _stream(
            session_id,
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [],
                },
            },
            parent,
        )
    ]
    for index, block in enumerate(blocks):
        start, deltas = _stream_block(block)
        out.append(
            _stream(
                session_id,
                {"type": "content_block_start", "index": index, "content_block": start},
                parent,
            )
        )
        out.extend(
            _stream(
                session_id,
                {"type": "content_block_delta", "index": index, "delta": d},
                parent,
            )
            for d in deltas
        )
        out.append(
            AssistantMessage(
                content=[block],
                model=model,
                parent_tool_use_id=parent,
                message_id=message_id,
                session_id=session_id,
                uuid=str(uuid.uuid4()),
            )
        )
        out.append(
            _stream(session_id, {"type": "content_block_stop", "index": index}, parent)
        )
    out.append(
        _stream(
            session_id,
            {"type": "message_delta", "delta": {"stop_reason": stop_reason}},
            parent,
        )
    )
    out.append(_stream(session_id, {"type": "message_stop"}, parent))
    return out


def _stream_block(block: ContentBlock) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": ""}, [{"type": "text_delta", "text": block.text}]
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": "", "signature": ""}, [
            {"type": "thinking_delta", "thinking": block.thinking},
            {"type": "signature_delta", "signature": block.signature},
        ]
    if isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
        kind = "tool_use" if isinstance(block, ToolUseBlock) else "server_tool_use"
        return {"type": kind, "id": block.id, "name": block.name, "input": {}}, [
            {"type": "input_json_delta", "partial_json": json.dumps(block.input)}
        ]
    raise ValueError(f"Bloco sem representação em stream: {type(block).__name__}")


def tool_result_message(
    tool_use_id: str,
    content: str | list[dict[str, Any]] | None = "ok",
    *,
    is_error: bool = False,
    tool_use_result: dict[str, Any] | None = None,
    parent_tool_use_id: str | None = None,
) -> UserMessage:
    return UserMessage(
        content=[ToolResultBlock(tool_use_id=tool_use_id, content=content, is_error=is_error)],
        uuid=str(uuid.uuid4()),
        parent_tool_use_id=parent_tool_use_id,
        tool_use_result=tool_use_result,
    )


def result_message(
    session_id: str,
    *,
    subtype: str = "success",
    is_error: bool = False,
    result: str | None = None,
    errors: list[str] | None = None,
    terminal_reason: str | None = "completed",
    duration_ms: int = 1000,
    total_cost_usd: float | None = 0.001,
    usage: dict[str, Any] | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=duration_ms,
        duration_api_ms=duration_ms,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=total_cost_usd,
        usage=usage if usage is not None else {"input_tokens": 10, "output_tokens": 5},
        result=result,
        errors=errors,
        terminal_reason=terminal_reason,
        uuid=str(uuid.uuid4()),
    )


def text_turn(
    session_id: str,
    text: str,
    *,
    thinking: str | None = None,
    model: str = DEFAULT_MODEL,
    message_id: str | None = None,
) -> list[Message]:
    """init, status, one response (optional thinking, then text), result."""
    blocks: list[ContentBlock] = []
    if thinking is not None:
        blocks.append(ThinkingBlock(thinking=thinking, signature="sig"))
    blocks.append(TextBlock(text=text))
    return [
        init_message(session_id, model),
        status_message(session_id),
        *response_messages(session_id, blocks, message_id=message_id, model=model),
        result_message(session_id, result=text),
    ]


def tool_turn(
    session_id: str,
    *,
    tool_name: str = "Write",
    tool_input: dict[str, Any] | None = None,
    tool_use_id: str | None = None,
    result_content: str | list[dict[str, Any]] | None = "ok",
    is_error: bool = False,
    tool_use_result: dict[str, Any] | None = None,
    final_text: str = "Pronto.",
    ask_permission: bool = False,
    suggestions: list[PermissionUpdate] | None = None,
    model: str = DEFAULT_MODEL,
) -> list[Step]:
    """init, status, a response with one tool use, [permission], the tool result,
    a second response with text, result."""
    tool_use_id = tool_use_id or new_tool_use_id()
    tool_input = tool_input if tool_input is not None else {}
    steps: list[Step] = [
        init_message(session_id, model),
        status_message(session_id),
        *response_messages(
            session_id,
            [ToolUseBlock(id=tool_use_id, name=tool_name, input=tool_input)],
            model=model,
            stop_reason="tool_use",
        ),
    ]
    if ask_permission:
        steps.append(
            PermissionStep(tool_name, tool_input, tool_use_id, list(suggestions or []))
        )
    steps.append(
        tool_result_message(
            tool_use_id, result_content, is_error=is_error, tool_use_result=tool_use_result
        )
    )
    steps.extend(response_messages(session_id, [TextBlock(text=final_text)], model=model))
    steps.append(result_message(session_id, result=final_text))
    return steps


# Local commands and background tasks ---------------------------------------


def local_command_message(text: str) -> UserMessage:
    """What the CLI sends at the start of a turn after set_model/set_permission_mode."""
    return UserMessage(
        content=f"<local-command-stdout>{text}</local-command-stdout>", uuid=str(uuid.uuid4())
    )


def background_tasks_changed_message(session_id: str, tasks: list[Any] | None = None) -> SystemMessage:
    return SystemMessage(
        subtype="background_tasks_changed",
        data={"type": "system", "subtype": "background_tasks_changed",
              "session_id": session_id, "tasks": tasks or []},
    )


def task_started_message(
    session_id: str,
    task_id: str,
    tool_use_id: str,
    *,
    description: str = "Explorar o código",
    subagent_type: str = "Explore",
    prompt: str = "explore",
) -> TaskStartedMessage:
    data = {
        "type": "system", "subtype": "task_started", "session_id": session_id,
        "task_id": task_id, "tool_use_id": tool_use_id, "description": description,
        "task_type": "local_agent", "subagent_type": subagent_type,
        "is_backgrounded": True, "prompt": prompt,
    }
    return TaskStartedMessage(
        subtype="task_started", data=data, task_id=task_id, description=description,
        uuid=str(uuid.uuid4()), session_id=session_id, tool_use_id=tool_use_id,
        task_type="local_agent",
    )


def task_progress_message(
    session_id: str,
    task_id: str,
    tool_use_id: str,
    *,
    description: str = "Lendo arquivos",
    last_tool_name: str | None = "Read",
    usage: dict[str, int] | None = None,
) -> TaskProgressMessage:
    usage = usage or {"total_tokens": 100, "tool_uses": 1, "duration_ms": 500}
    data = {
        "type": "system", "subtype": "task_progress", "session_id": session_id,
        "task_id": task_id, "tool_use_id": tool_use_id, "description": description,
        "usage": usage, "last_tool_name": last_tool_name,
    }
    return TaskProgressMessage(
        subtype="task_progress", data=data, task_id=task_id, description=description,
        usage=usage,  # type: ignore[arg-type]
        uuid=str(uuid.uuid4()), session_id=session_id, tool_use_id=tool_use_id,
        last_tool_name=last_tool_name,
    )


def task_updated_message(
    session_id: str, task_id: str, status: str, patch: dict[str, Any] | None = None
) -> TaskUpdatedMessage:
    patch = patch if patch is not None else {"status": status}
    data = {"type": "system", "subtype": "task_updated", "session_id": session_id,
            "task_id": task_id, "patch": patch}
    return TaskUpdatedMessage(
        subtype="task_updated", data=data, task_id=task_id, patch=patch,
        status=status,  # type: ignore[arg-type]
        session_id=session_id, uuid=str(uuid.uuid4()),
    )


def task_notification_message(
    session_id: str,
    task_id: str,
    tool_use_id: str,
    *,
    status: str = "completed",
    summary: str = "Terminei.",
    usage: dict[str, int] | None = None,
) -> TaskNotificationMessage:
    usage = usage or {"total_tokens": 300, "tool_uses": 3, "duration_ms": 2000}
    data = {
        "type": "system", "subtype": "task_notification", "session_id": session_id,
        "task_id": task_id, "tool_use_id": tool_use_id, "status": status,
        "summary": summary, "output_file": "/tmp/out", "usage": usage,
    }
    return TaskNotificationMessage(
        subtype="task_notification", data=data, task_id=task_id,
        status=status,  # type: ignore[arg-type]
        output_file="/tmp/out", summary=summary, uuid=str(uuid.uuid4()),
        session_id=session_id, tool_use_id=tool_use_id,
        usage=usage,  # type: ignore[arg-type]
    )
