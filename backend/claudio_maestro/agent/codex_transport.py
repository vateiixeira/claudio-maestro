"""The native Codex CLI app-server protocol over a child process's stdio."""

import asyncio
import json
import logging
import os
import shutil
import signal
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Self

from claudio_maestro.agent.base import AgentError

logger = logging.getLogger(__name__)

CLI_NOT_FOUND_MESSAGE = (
    "O comando `codex` não foi encontrado. Instale o Codex CLI e entre com `codex login`."
)
PROCESS_DIED_MESSAGE = "O processo do Codex encerrou inesperadamente."
STREAM_LIMIT = 64 * 1024 * 1024
RPC_TIMEOUT = 20
RequestId = int | str
Notification = Callable[[str, dict[str, Any]], None]
ServerRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def codex_binary() -> str | None:
    """Executable selected by the local app owner, or the one installed on PATH."""
    override = os.environ.get("MAESTRO_CODEX_CLI")
    found = os.path.expanduser(override) if override else shutil.which("codex")
    if found and os.path.isfile(found) and os.access(found, os.X_OK):
        # Keep the installer entrypoint, but never resolve a relative executable
        # from the project directory assigned to the child.
        return os.path.abspath(found)
    return None


class CodexRPCError(AgentError):
    def __init__(self, error: dict[str, Any]) -> None:
        self.code = error.get("code")
        self.data = error.get("data")
        super().__init__(codex_error_message(error.get("message")), refused=True)


def codex_error_message(detail: Any, kind: Any = None) -> str:
    message = detail if isinstance(detail, str) else ""
    lowered = message.lower()
    if kind == "unauthorized" or any(
        word in lowered for word in ("unauthorized", "not logged in", "invalid auth", "401")
    ):
        return "O login do Codex expirou ou está ausente. Rode `codex login` no terminal."
    if kind == "usageLimitExceeded" or "usage limit" in lowered or "rate limit" in lowered:
        return "O Codex atingiu o limite de uso da conta."
    if kind == "contextWindowExceeded" or "context window" in lowered:
        return "O contexto do Codex está cheio. Compacte a conversa ou inicie outra."
    if kind == "sandboxError":
        return "O Codex não conseguiu executar a operação dentro das permissões da sessão."
    if "model" in lowered and any(word in lowered for word in ("not supported", "unavailable", "not found")):
        return "O modelo escolhido não está disponível no Codex."
    if "thread" in lowered and any(word in lowered for word in ("not found", "no rollout")):
        return "O Codex não encontrou a conversa salva."
    # Provider error text may include headers, tokens, or response bodies.
    return "O Codex recusou a operação."


class CodexTransport:
    def __init__(
        self,
        cwd: Path,
        *,
        command: list[str] | None = None,
        env: dict[str, str] | None = None,
        on_notification: Notification | None = None,
        on_request: ServerRequest | None = None,
        on_exit: Callable[[AgentError], None] | None = None,
    ) -> None:
        self.cwd = cwd
        self.command = command
        self.env = env or {}
        self.on_notification = on_notification
        self.on_request = on_request
        self.on_exit = on_exit
        self.initialization: dict[str, Any] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._server_tasks: dict[RequestId, asyncio.Task[None]] = {}
        self._closing = False

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        command = self.command
        if command is None:
            binary = codex_binary()
            if binary is None:
                raise AgentError(CLI_NOT_FOUND_MESSAGE)
            command = [binary, "app-server"]
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.cwd,
                env=os.environ | self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=STREAM_LIMIT,
                start_new_session=os.name == "posix",
            )
        except FileNotFoundError as error:
            if not self.cwd.is_dir():
                raise AgentError("A pasta da sessão do Codex não existe.") from error
            raise AgentError(CLI_NOT_FOUND_MESSAGE) from error
        except OSError as error:
            logger.warning("Falha ao iniciar o Codex: %s", error)
            raise AgentError("Não foi possível iniciar o Codex.") from error
        self._reader = asyncio.create_task(self._read())
        try:
            self.initialization = await self.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "claudio-maestro",
                        "title": "Cláudio Maestro",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            await self._write({"method": "initialized"})
        except (Exception, asyncio.CancelledError):
            await self.close()
            raise

    async def call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            message: dict[str, Any] = {"method": method, "id": request_id}
            if params is not None:
                message["params"] = params
            async with asyncio.timeout(RPC_TIMEOUT):
                await self._write(message)
                return await future
        except TimeoutError as error:
            raise AgentError(f"O Codex não respondeu a tempo ({method}).") from error
        finally:
            self._pending.pop(request_id, None)
            if future.done() and not future.cancelled():
                future.exception()  # _write may have failed after the reader set an error.

    async def _write(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if self._closing or proc is None or proc.stdin is None or proc.returncode is not None:
            raise AgentError(PROCESS_DIED_MESSAGE)
        try:
            proc.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            await proc.stdin.drain()
        except (ConnectionError, OSError) as error:
            raise AgentError(PROCESS_DIED_MESSAGE) from error

    async def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout
        failure = AgentError(PROCESS_DIED_MESSAGE)
        try:
            while line := await stdout.readline():
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    logger.debug("O Codex escreveu uma linha fora do protocolo")
                    continue
                if isinstance(message, dict):
                    self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao ler o protocolo do Codex")
            failure = AgentError("Falha ao ler a resposta do Codex.")
        finally:
            self._fail_pending(failure)
            for task in self._server_tasks.values():
                task.cancel()
            if not self._closing and self.on_exit is not None:
                self.on_exit(failure)

    def _dispatch(self, message: dict[str, Any]) -> None:
        method, request_id = message.get("method"), message.get("id")
        if not isinstance(method, str):
            future = self._pending.get(request_id) if type(request_id) is int else None
            if future is not None and not future.done():
                error = message.get("error")
                if isinstance(error, dict):
                    future.set_exception(CodexRPCError(error))
                else:
                    result = message.get("result")
                    future.set_result(result if isinstance(result, dict) else {})
            return

        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if isinstance(request_id, (int, str)):
            if request_id not in self._server_tasks:
                self._server_tasks[request_id] = asyncio.create_task(
                    self._handle_request(request_id, method, params)
                )
            return
        if method == "serverRequest/resolved":
            resolved_id = params.get("requestId")
            if isinstance(resolved_id, (int, str)):
                task = self._server_tasks.get(resolved_id)
                if task is not None:
                    task.cancel()
        if self.on_notification is not None:
            self.on_notification(method, params)

    async def _handle_request(
        self, request_id: RequestId, method: str, params: dict[str, Any]
    ) -> None:
        try:
            try:
                if self.on_request is None:
                    raise NotImplementedError
                response: dict[str, Any] = {"result": await self.on_request(method, params)}
            except NotImplementedError:
                response = {"error": {"code": -32601, "message": "Method not supported"}}
            except Exception:
                logger.exception("Falha ao responder ao pedido %s do Codex", method)
                response = {"error": {"code": -32603, "message": "Client error"}}
            with suppress(AgentError, TimeoutError):
                async with asyncio.timeout(RPC_TIMEOUT):
                    await self._write({"id": request_id, **response})
        finally:
            self._server_tasks.pop(request_id, None)

    def _fail_pending(self, failure: AgentError) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(failure)

    async def close(self) -> None:
        self._closing = True
        self._fail_pending(AgentError(PROCESS_DIED_MESSAGE))
        reader, self._reader = self._reader, None
        tasks = list(self._server_tasks.values())
        if reader is not None:
            tasks.append(reader)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._server_tasks.clear()
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.stdin is not None:
            proc.stdin.close()
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
        elif proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except TimeoutError:
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            await proc.wait()


def normalize_codex_models(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Map Codex-native model ids and reasoning levels to the shared model menu."""
    models = []
    data = result.get("data")
    if not isinstance(data, list):
        return models
    for entry in data:
        if not isinstance(entry, dict) or entry.get("hidden") is True:
            continue
        model = entry.get("model") or entry.get("id")
        if not isinstance(model, str) or not model:
            continue
        options = entry.get("supportedReasoningEfforts")
        levels = [
            option["reasoningEffort"] for option in options
            if isinstance(option, dict) and isinstance(option.get("reasoningEffort"), str)
        ] if isinstance(options, list) else []
        models.append({
            "value": model,
            "displayName": entry.get("displayName") or model,
            "description": entry.get("description") or "",
            "supportsEffort": bool(levels),
            "supportedEffortLevels": levels,
            "defaultEffort": entry.get("defaultReasoningEffort"),
            "isDefault": entry.get("isDefault") is True,
        })
    return models


async def list_codex_models(transport: CodexTransport) -> list[dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    async for page in codex_pages(transport, "model/list", {"limit": 100}):
        for model in normalize_codex_models(page):
            models.setdefault(model["value"], model)
    return list(models.values())


async def codex_pages(
    transport: CodexTransport, method: str, params: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    """Read a JSON-RPC collection in order; cursors are opaque and must progress."""
    seen: set[str] = set()
    while True:
        page = await transport.call(method, params)
        yield page
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            return
        seen.add(cursor)
        params = {**params, "cursor": cursor}
