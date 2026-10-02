"""SDK Transport over the agentd: the `claude` process outlives this backend.

New mode (`spawn` given): connect() asks the agentd to start the process.
Reattach mode (`attach_id` given): connect() starts nothing. The SDK's initialize
is answered here with the response the agentd kept, control requests the CLI is
still waiting on are delivered again first, then the log from `attach_from`.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from claude_agent_sdk import CLIConnectionError, ProcessError
from claude_agent_sdk._internal.transport import Transport

from claudio_maestro.agent.agentd_client import AgentdClient, AgentdUnavailable
from claudio_maestro.agent.spawn import SpawnSpec

logger = logging.getLogger(__name__)


class AgentdConnectError(CLIConnectionError):
    """The agentd could not be reached when connecting (nothing was started)."""


class AgentdTransport(Transport):
    def __init__(
        self,
        agentd: AgentdClient,
        *,
        session_id: str,
        spawn: Callable[[], SpawnSpec] | None = None,
        attach_id: str | None = None,
        attach_from: int = 0,
        attach_init: dict[str, Any] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ) -> None:
        if (spawn is None) == (attach_id is None):
            raise ValueError("pass exactly one of spawn or attach_id")
        self._agentd = agentd
        self._session_id = session_id
        self._spawn = spawn
        self._attach_init = attach_init
        self._start = attach_from
        self._on_stderr = on_stderr
        self.child_id: str | None = attach_id
        self._reattach = attach_id is not None
        self._local: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._own_requests: set[str] = set()
        # Requests delivered from `pending` that the log replay may deliver again.
        self._redelivered: set[str] = set()
        self._uuid_pos: dict[str, int] = {}
        self._acked = attach_from
        self._detached = False
        self._ready = False
        self._ack_tasks: set[asyncio.Task[None]] = set()

    # Transport ---------------------------------------------------------------

    async def connect(self) -> None:
        try:
            if self._spawn is not None:
                spec = await asyncio.to_thread(self._spawn)
                self.child_id = await self._agentd.spawn(self._session_id, spec)
            else:
                assert self.child_id is not None
                for line in await self._agentd.pending(self.child_id):
                    message = json.loads(line)
                    self._redelivered.add(str(message.get("request_id")))
                    self._local.put_nowait(message)
            try:
                self._queue = await self._agentd.subscribe(self.child_id, self._start)
            except AgentdUnavailable:
                if self._spawn is not None:  # do not leave an orphan process behind
                    await self._agentd.kill(self.child_id)
                raise
        except AgentdUnavailable as error:
            raise AgentdConnectError(f"agentd indisponível: {error}") from error
        self._ready = True

    async def write(self, data: str) -> None:
        if self._detached or self.child_id is None:
            return
        message = json.loads(data)
        if message.get("type") == "control_request":
            request_id = str(message.get("request_id"))
            if self._reattach and (message.get("request") or {}).get("subtype") == "initialize":
                self._local.put_nowait({"type": "control_response", "response": {
                    "subtype": "success", "request_id": request_id,
                    "response": self._attach_init or {}}})
                if self._queue is not None:
                    self._queue.put_nowait({"ev": "wake"})
                return
            self._own_requests.add(request_id)
        try:
            await self._agentd.write(self.child_id, data)
        except AgentdUnavailable as error:
            raise CLIConnectionError(f"agentd indisponível: {error}") from error

    def read_messages(self) -> AsyncIterator[dict[str, Any]]:
        return self._read()

    async def _read(self) -> AsyncIterator[dict[str, Any]]:
        assert self._queue is not None
        while not self._detached:
            while not self._local.empty():
                yield self._local.get_nowait()
            event = await self._queue.get()
            kind = event.get("ev")
            if kind == "line":
                try:
                    message = json.loads(event["line"])
                except ValueError as error:
                    raise CLIConnectionError("O agentd enviou uma linha inválida.") from error
                if message.get("type") == "control_request" and \
                        str(message.get("request_id")) in self._redelivered:
                    # Already delivered from `pending`: the log (from the ack) has it too.
                    self._redelivered.discard(str(message.get("request_id")))
                    continue
                if message.get("type") == "control_response":
                    request_id = (message.get("response") or {}).get("request_id")
                    if request_id not in self._own_requests:
                        continue
                    self._own_requests.discard(request_id)
                if message.get("type") != "stream_event" and message.get("uuid"):
                    self._uuid_pos[message["uuid"]] = event["pos"]
                yield message
            elif kind == "gap":
                logger.warning("Sessão %s: parte do registro foi descartada", self._session_id)
            elif kind == "exit":
                for line in event.get("stderr") or []:
                    if self._on_stderr is not None:
                        self._on_stderr(line)
                code = event.get("code")
                if code:
                    raise ProcessError("O processo do agente encerrou", exit_code=code,
                                       stderr="\n".join(event.get("stderr") or []))
                return
            elif kind == "lost":
                raise CLIConnectionError("A conexão com o agentd caiu.")

    async def close(self) -> None:
        self._ready = False
        if self.child_id is not None and self._queue is not None:
            self._queue.put_nowait({"ev": "wake"})
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._agentd.unsubscribe(self.child_id), 2)

    def is_ready(self) -> bool:
        return self._ready and not self._detached

    async def end_input(self) -> None:
        return None

    # Agentd extras ---------------------------------------------------------

    def processed(self, message: Any) -> None:
        """The session handled `message`: confirm its line, unless it is a stream event."""
        uuid = getattr(message, "uuid", None)
        if uuid is None:
            data = getattr(message, "data", None)
            uuid = data.get("uuid") if isinstance(data, dict) else None
        pos = self._uuid_pos.pop(uuid, None) if uuid else None
        if pos is None or self.child_id is None or pos + 1 <= self._acked:
            return
        self._acked = pos + 1
        for key in [k for k, v in self._uuid_pos.items() if v < pos]:
            del self._uuid_pos[key]
        task = asyncio.create_task(self._agentd.ack(self.child_id, self._acked))
        self._ack_tasks.add(task)
        task.add_done_callback(self._ack_done)

    def _ack_done(self, task: asyncio.Task[None]) -> None:
        self._ack_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Sessão %s: falha ao confirmar posição", self._session_id,
                           exc_info=task.exception())

    def detach(self) -> None:
        self._detached = True
        if self._queue is not None:
            self._queue.put_nowait({"ev": "wake"})

    async def kill(self) -> None:
        if self.child_id is not None:
            await self._agentd.kill(self.child_id)
