"""Run conversations with the Codex CLI's native app server."""

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any

from claude_agent_sdk import Message, PermissionResultAllow, ToolPermissionContext

from claudio_maestro.agent.base import AgentError, AgentOptions
from claudio_maestro.agent.codex_messages import (
    TEXT_DELTAS,
    CodexMessages,
    codex_item_id,
    context_from_usage,
    native_input,
    object_of,
    objects_of,
    read_rollout_usage,
    string_of,
)
from claudio_maestro.agent.codex_transport import (
    PROCESS_DIED_MESSAGE,
    RPC_TIMEOUT,
    CodexRPCError,
    CodexTransport,
    codex_pages,
    list_codex_models,
)

logger = logging.getLogger(__name__)

_THREAD_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PERMISSION_MODES = {
    "default": ("read-only", "on-request", "user"),
    "plan": ("read-only", "never", "user"),
    "acceptEdits": ("workspace-write", "on-request", "user"),
    "auto": ("workspace-write", "on-request", "auto_review"),
    "dontAsk": ("workspace-write", "never", "user"),
    "bypassPermissions": ("danger-full-access", "never", "user"),
}
_PERMISSION_TOOLS = {
    "item/commandExecution/requestApproval": ("Bash", ("command", "cwd")),
    "item/fileChange/requestApproval": ("Edit", ("grantRoot",)),
    "item/permissions/requestApproval": ("Permissões do Codex", ("permissions", "cwd")),
}


class CodexAgentClient:
    """AgentClient backed by a supervised local Codex CLI process."""

    provider = "codex"

    def __init__(self, options: AgentOptions, command: list[str] | None = None) -> None:
        self.options = options
        self.provider_session_id: str | None = None
        self._queue: asyncio.Queue[Message | AgentError | None] = asyncio.Queue()
        self._messages = CodexMessages(options.session_id, self._queue.put_nowait)
        self._transport = CodexTransport(
            options.cwd, command=command, env=options.env,
            on_notification=self._on_notification, on_request=self._on_request,
            on_exit=self._on_exit,
        )
        self._model = options.model if options.model != "default" else None
        self._effort = options.effort if options.effort != "default" else None
        self._mode = options.permission_mode or "default"
        self._inherited_effort: str | None = None
        self._inherited_effort_known = False
        self._catalog: list[dict[str, Any]] = []
        self._worker: asyncio.Task[None] | None = None
        self._prompts: asyncio.Queue[tuple[list[dict[str, Any]], str | None]] = asyncio.Queue()
        self._turn_id: str | None = None
        self._turn_started = asyncio.Event()
        self._turn_done: asyncio.Future[None] | None = None
        self._failure: AgentError | None = None
        self._closed = False
        self._patches: dict[str, list[dict[str, Any]]] = {}

    async def connect(self) -> None:
        self._validate_mode(self._mode)
        await self._transport.connect()
        try:
            response = await self._open_thread()
            thread = object_of(response.get("thread"))
            thread_id = string_of(thread.get("id"))
            if not _THREAD_ID.fullmatch(thread_id):
                raise AgentError("O Codex não devolveu um identificador de conversa válido.")
            if self.options.resume and not self.options.fork_session:
                if self.options.provider_session_id != thread_id:
                    raise AgentError("O Codex abriu uma conversa diferente da solicitada.")
            self.provider_session_id = thread_id
            self._model = string_of(response.get("model")) or self._model
            if self._effort is None:
                self._inherited_effort = string_of(response.get("reasoningEffort")) or None
                self._inherited_effort_known = True
            self._messages.model = self._model
            self._messages.init(self._mode)
            if self.options.replay_history and self.options.resume:
                await self._replay(thread)
            self._worker = asyncio.create_task(self._run_prompts())
        except (Exception, asyncio.CancelledError):
            await self.close()
            raise

    async def _open_thread(self) -> dict[str, Any]:
        sandbox, approval, reviewer = _PERMISSION_MODES[self._mode]
        params: dict[str, Any] = {
            "cwd": str(self.options.cwd),
            "sandbox": sandbox,
            "approvalPolicy": approval,
            "approvalsReviewer": reviewer,
        }
        if self._model:
            params["model"] = self._model
        if self._effort:
            params["config"] = {"model_reasoning_effort": self._effort}
        if self.options.system_prompt_append:
            params["developerInstructions"] = self.options.system_prompt_append

        thread_id = self.options.provider_session_id
        if not (self.options.resume and thread_id):
            return await self._transport.call("thread/start", params)
        if not _THREAD_ID.fullmatch(thread_id):
            raise AgentError("O identificador da conversa do Codex é inválido.")
        existing = await self._transport.call("thread/read", {"threadId": thread_id})
        thread = object_of(existing.get("thread"))
        cwd = string_of(thread.get("cwd"))
        try:
            matches = (
                thread.get("id") == thread_id
                and Path(cwd).is_absolute()
                and Path(cwd).resolve(strict=True) == self.options.cwd.resolve(strict=True)
            )
        except (OSError, RuntimeError, ValueError):
            matches = False
        if not matches:
            raise AgentError("A conversa do Codex pertence a outra pasta.")
        path = string_of(thread.get("path"))
        if path:
            home = self.options.env.get("CODEX_HOME", os.environ.get("CODEX_HOME"))
            codex_home = self.options.cwd / Path(home).expanduser() if home else Path.home() / ".codex"
            self._messages.usage = await asyncio.to_thread(
                read_rollout_usage, path, codex_home, thread_id
            )
        # Context updates can be sent ahead of the resume response.
        if not self.options.fork_session:
            self.provider_session_id = thread_id
        return await self._transport.call(
            "thread/fork" if self.options.fork_session else "thread/resume",
            {**params, "threadId": thread_id, "excludeTurns": True},
        )

    async def _replay(self, thread: dict[str, Any]) -> None:
        if self.provider_session_id is None:
            return
        has_page = False
        try:
            async for page in codex_pages(self._transport, "thread/turns/list", {
                "threadId": self.provider_session_id,
                "sortDirection": "asc",
                "itemsView": "full",
                "limit": 20,
            }):
                has_page = True
                self._replay_turns(page.get("data"))
        except CodexRPCError as error:
            if has_page or error.code != -32601:
                raise
            # Older app-server versions returned all turns in a thread read.
            old = await self._transport.call("thread/read", {
                "threadId": self.provider_session_id, "includeTurns": True,
            })
            self._replay_turns(
                object_of(old.get("thread")).get("turns") or thread.get("turns")
            )

    def _replay_turns(self, raw: Any) -> None:
        for turn in objects_of(raw):
            for item in objects_of(turn.get("items")):
                self._messages.item(item, completed=True, replay=True)

    async def send(
        self, content: str | list[dict[str, Any]], *, message_id: str | None = None
    ) -> None:
        self._require_running()
        prompt = native_input(content)
        if not prompt:
            raise AgentError("A mensagem está vazia.")
        if (self._turn_done is None or self._turn_done.done()) and self._prompts.empty():
            self._turn_started.clear()
        self._prompts.put_nowait((prompt, message_id))

    def _require_running(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self._closed or self.provider_session_id is None or self._worker is None:
            raise AgentError(PROCESS_DIED_MESSAGE)

    async def _run_prompts(self) -> None:
        while self._failure is None:
            prompt, message_id = await self._prompts.get()
            self._turn_done = asyncio.get_running_loop().create_future()
            self._turn_started.clear()
            self._turn_id = None
            self._patches.clear()
            self._messages.begin_turn()
            try:
                await self._run_turn(prompt, message_id)
            except CodexRPCError as error:
                self._messages.end_turn()
                self._queue.put_nowait(self._messages.result({}, error.message_pt))
            except AgentError as error:
                self._on_exit(error)
                return
            except Exception:
                logger.exception("Falha inesperada durante o turno do Codex")
                self._on_exit(AgentError("Falha inesperada durante o turno do Codex."))
                return
            finally:
                self._turn_id = None
                self._turn_done = None
                if self._prompts.empty():
                    self._turn_started.set()

    async def _run_turn(self, prompt: list[dict[str, Any]], message_id: str | None) -> None:
        thread_id = self.provider_session_id
        if self._messages.model != self._model:
            self._messages.model = self._model
            self._messages.init(self._mode)
        if len(prompt) == 1 and string_of(prompt[0].get("text")).strip() == "/compact":
            await self._transport.call("thread/compact/start", {"threadId": thread_id})
        else:
            params = self._turn_params(prompt, message_id)
            response = await self._transport.call("turn/start", params)
            turn = object_of(response.get("turn"))
            if self._turn_id is None:
                self._turn_id = string_of(turn.get("id")) or None
                self._turn_started.set()
            if not self._turn_id:
                raise AgentError("O Codex não devolveu um identificador de turno.")
            if turn.get("status") in {"completed", "interrupted", "failed"}:
                self._complete_turn(turn)
        assert self._turn_done is not None
        await self._turn_done

    def _turn_params(
        self, prompt: list[dict[str, Any]], message_id: str | None
    ) -> dict[str, Any]:
        sandbox, approval, reviewer = _PERMISSION_MODES[self._mode]
        if sandbox == "workspace-write":
            sandbox_policy: dict[str, Any] = {
                "type": "workspaceWrite",
                "writableRoots": [str(path.resolve()) for path in self.options.add_dirs],
                "networkAccess": False,
                "excludeTmpdirEnvVar": True,
                "excludeSlashTmp": True,
            }
        elif sandbox == "read-only":
            sandbox_policy = {"type": "readOnly", "networkAccess": False}
        else:
            sandbox_policy = {"type": "dangerFullAccess"}
        params: dict[str, Any] = {
            "threadId": self.provider_session_id,
            "input": prompt,
            "approvalPolicy": approval,
            "approvalsReviewer": reviewer,
            "sandboxPolicy": sandbox_policy,
        }
        if message_id is not None:
            params["clientUserMessageId"] = message_id
        effort = self._effort or self._inherited_effort
        if effort is not None:
            params["effort"] = effort
        if self._model:
            params["model"] = self._model
            params["collaborationMode"] = {
                "mode": "plan" if self._mode == "plan" else "default",
                "settings": {
                    "model": self._model,
                    "reasoning_effort": effort,
                    "developer_instructions": (
                        self.options.system_prompt_append if self._mode != "plan" else None
                    ),
                },
            }
        return params

    def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self.provider_session_id or params.get("threadId") != self.provider_session_id:
            return
        if method == "thread/tokenUsage/updated":
            self._messages.update_usage(object_of(params.get("tokenUsage")))
            return
        if self._turn_done is None or self._turn_done.done():
            return
        turn = object_of(params.get("turn"))
        turn_id = string_of(params.get("turnId") or turn.get("id"))
        if self._turn_id is None and method == "turn/started" and turn_id:
            self._turn_id = turn_id
            self._turn_started.set()
        if not turn_id or turn_id != self._turn_id:
            return
        if method == "turn/completed":
            self._complete_turn(turn)
        elif method in TEXT_DELTAS:
            self._messages.delta(method, params)
        elif method in {"item/started", "item/completed"}:
            item = object_of(params.get("item"))
            if item.get("type") == "fileChange":
                item_id = string_of(item.get("id"))
                if method == "item/started":
                    self._patches[item_id] = objects_of(item.get("changes"))
                else:
                    self._patches.pop(item_id, None)
            self._messages.item(item, completed=method == "item/completed")
        elif method == "model/rerouted":
            model = string_of(params.get("toModel"))
            if model:
                self._messages.model = model
                self._messages.init(self._mode)

    def _complete_turn(self, turn: dict[str, Any]) -> None:
        if self._turn_done is None or self._turn_done.done():
            return
        for item in objects_of(turn.get("items")):
            self._messages.item(item, completed=True)
        self._messages.end_turn()
        self._queue.put_nowait(self._messages.result(turn))
        self._turn_done.set_result(None)
        self._turn_started.set()

    async def _on_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.provider_session_id or params.get("threadId") != self.provider_session_id:
            raise NotImplementedError
        if not self._turn_id or params.get("turnId") != self._turn_id:
            raise NotImplementedError
        if method == "item/tool/requestUserInput":
            return await self._ask_questions(params)
        if method == "mcpServer/elicitation/request":
            return {"action": "decline", "content": None, "_meta": None}
        if method not in _PERMISSION_TOOLS:
            raise NotImplementedError
        name, keys = _PERMISSION_TOOLS[method]
        context = self._permission_context(params)
        tool_input = {key: params[key] for key in keys if params.get(key) is not None}
        item_id = string_of(params.get("itemId"))
        if method == "item/commandExecution/requestApproval":
            if params.get("networkApprovalContext") is not None:
                network = object_of(params.get("networkApprovalContext"))
                host, protocol = string_of(network.get("host")), string_of(network.get("protocol"))
                if not host or not protocol:
                    return {"decision": "decline"}
                name, tool_input = "Rede do Codex", {"host": host, "protocol": protocol}
                context.title = "Permissão para acessar a rede"
            elif params.get("kind") == "writeStdin" or not string_of(params.get("command")):
                return {"decision": "decline"}
            additional = object_of(params.get("additionalPermissions"))
            if additional and any(value is not None for value in additional.values()):
                name = "Permissões do Codex"
                tool_input["permissões adicionais"] = additional
        elif method == "item/fileChange/requestApproval":
            # A grantRoot can persist until the end of the session; the app
            # presents only one-operation approval for Codex.
            if params.get("grantRoot") or not self._patches.get(item_id):
                logger.info("Pedido de alteração de arquivos do Codex recusado (grantRoot ou sem patch)")
                return {"decision": "decline"}
            self._describe_file_approval(tool_input, item_id)
        decisions = params.get("availableDecisions")
        if isinstance(decisions, list) and "accept" not in decisions:
            return {"decision": "decline"}
        result = await self.options.can_use_tool(name, tool_input, context)
        allow = isinstance(result, PermissionResultAllow)
        if method == "item/permissions/requestApproval":
            # Grant exactly what was requested, for this turn only.
            return {"permissions": object_of(params.get("permissions")) if allow else {},
                    "scope": "turn"}
        return {"decision": "accept" if allow else "decline"}

    def _describe_file_approval(self, tool_input: dict[str, Any], item_id: str) -> None:
        changes = self._patches.get(item_id, [])
        if len(changes) == 1:
            tool_input["file_path"] = string_of(changes[0].get("path"))
            tool_input["new_string"] = string_of(changes[0].get("diff"))
        elif changes:
            tool_input["changes"] = changes

    def _permission_context(self, params: dict[str, Any]) -> ToolPermissionContext:
        item_id = string_of(params.get("itemId"))
        return ToolPermissionContext(
            tool_use_id=codex_item_id(item_id) if item_id else None,
            description=string_of(params.get("reason")) or None,
        )

    async def _ask_questions(self, params: dict[str, Any]) -> dict[str, Any]:
        questions = [
            question for question in objects_of(params.get("questions"))
            if isinstance(question.get("id"), str) and isinstance(question.get("question"), str)
        ]
        # The shared conversation prompt shows the answer as ordinary text.
        if not questions or any(q.get("isSecret") for q in questions):
            return {"answers": {}}
        form = {"questions": [
            {
                "header": string_of(q.get("header")),
                "question": q["question"],
                "options": objects_of(q.get("options")),
                "multiSelect": False,
            }
            for q in questions
        ]}
        result = await self.options.can_use_tool(
            "AskUserQuestion", form, self._permission_context(params)
        )
        answers = object_of((result.updated_input or {}).get("answers")) if isinstance(
            result, PermissionResultAllow
        ) else {}
        return {"answers": {
            q["id"]: {"answers": [answers[q["question"]]]}
            for q in questions if isinstance(answers.get(q["question"]), str)
        }}

    async def messages(self) -> AsyncIterator[Message]:
        while True:
            message = await self._queue.get()
            if isinstance(message, AgentError):
                raise message
            if message is None:
                return
            yield message

    def _on_exit(self, error: AgentError) -> None:
        if self._closed or self._failure is not None:
            return
        self._failure = error
        self._turn_started.set()
        if self._turn_done is not None and not self._turn_done.done():
            self._turn_done.set_result(None)
        self._queue.put_nowait(error)

    async def interrupt(self) -> None:
        self._require_running()
        if self._turn_done is None and self._prompts.empty():
            return
        try:
            async with asyncio.timeout(RPC_TIMEOUT):
                await self._turn_started.wait()
        except TimeoutError as error:
            raise AgentError("O Codex não confirmou o início do turno a tempo.") from error
        if self._failure is not None:
            raise self._failure
        turn_id, turn_done = self._turn_id, self._turn_done
        if turn_id is not None and turn_done is not None and not turn_done.done():
            try:
                await self._transport.call("turn/interrupt", {
                    "threadId": self.provider_session_id, "turnId": turn_id,
                })
            except CodexRPCError:
                if not turn_done.done():
                    raise

    async def stop_task(self, task_id: str) -> None:
        # Codex only exposes whole-turn interruption for model work.
        return None

    async def set_model(self, model: str | None) -> None:
        model = model if model and model != "default" else None
        self._model, self._inherited_effort = await self._model_defaults(model)
        self._inherited_effort_known = True
        self._messages.model = self._model
        self._messages.init(self._mode)

    async def _model_defaults(self, requested: str | None) -> tuple[str, str | None]:
        config = object_of((await self._transport.call(
            "config/read", {"cwd": str(self.options.cwd)}
        )).get("config"))
        configured_model = string_of(config.get("model"))
        model = requested or configured_model
        effort = None
        if not requested or not configured_model or requested == configured_model:
            effort = string_of(config.get("model_reasoning_effort")) or None
        if model and effort:
            return model, effort
        catalog = self._catalog or await list_codex_models(self._transport)
        self._catalog = catalog
        if model:
            entry = next((entry for entry in catalog if entry["value"] == model), {})
        else:
            entry = next((entry for entry in catalog if entry["isDefault"]), {})
        model = model or string_of(entry.get("value"))
        if not model:
            raise AgentError("O Codex não informou o modelo padrão.", refused=True)
        return model, effort or string_of(entry.get("defaultEffort")) or None

    def _validate_mode(self, mode: str) -> None:
        if mode not in _PERMISSION_MODES or (
            mode == "bypassPermissions" and not self.options.allow_bypass
        ):
            raise AgentError("Esse modo de permissão não está disponível no Codex.", refused=True)

    async def set_permission_mode(self, mode: str) -> None:
        self._validate_mode(mode)
        self._mode = mode

    async def set_effort(self, effort: str) -> None:
        if effort != "default":
            self._effort = effort
            return
        if not self._inherited_effort_known:
            _, self._inherited_effort = await self._model_defaults(self._model)
            self._inherited_effort_known = True
        self._effort = None

    async def set_remote_control(
        self, enabled: bool, *, name: str | None = None, reattach_session_id: str | None = None
    ) -> dict[str, Any]:
        raise AgentError("O Controle remoto está disponível nas sessões do Claude.", refused=True)

    async def get_server_info(self) -> dict[str, Any]:
        self._catalog = await list_codex_models(self._transport)
        return {"models": self._catalog}

    async def get_context_usage(self, detail: str = "full") -> dict[str, Any] | None:
        return context_from_usage(self._messages.usage, self._messages.model, full=detail == "full")

    async def detach(self) -> bool:
        return False

    async def close(self) -> None:
        self._closed = True
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        await self._transport.close()
        self._queue.put_nowait(None)
