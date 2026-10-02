"""Backend side of the agentd connection: one socket, request/response by `req`."""

import asyncio
import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from claudio_maestro.agent.spawn import SpawnSpec
from claudio_maestro.agentd import PROTOCOL
from claudio_maestro.agentd.paths import socket_path

logger = logging.getLogger(__name__)

START_WAIT = 3.0
HELLO_TIMEOUT = 2.0
STREAM_LIMIT = 256 * 1024 * 1024
START_COOLDOWN = 60.0  # after a failed start, new attempts wait this long (seconds)
GONE_WAIT = 13.0  # a killed child may take stdin grace + SIGTERM grace + SIGKILL (seconds)
GONE_POLL = 0.1


class AgentdUnavailable(Exception):
    pass


@dataclass
class AgentdChild:
    id: str
    session_id: str
    pid: int
    next_pos: int
    ack: int
    exit_code: int | None
    init: dict[str, Any] | None
    stderr: list[str] = field(default_factory=list)

    @classmethod
    def from_reply(cls, data: dict[str, Any]) -> "AgentdChild":
        """Ignore fields this version does not know (a newer agentd may send more)."""
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


class AgentdClient:
    def __init__(self, data_dir: Path, *, spawn_allowed: bool = True,
                 idle_exit: float = 600, orphan_timeout: float = 1800,
                 start_cooldown: float = START_COOLDOWN) -> None:
        self.data_dir = data_dir
        self.spawn_allowed = spawn_allowed
        self._idle_exit = idle_exit
        self._orphan_timeout = orphan_timeout
        self._start_cooldown = start_cooldown
        self._start_failed_at: float | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._req = 0
        self._waiting: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._subscriptions: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._procs: list[subprocess.Popen[bytes]] = []
        self.server_pid: int | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def ensure_running(self, *, start: bool = True) -> None:
        """Connect to the agentd, starting one when none runs (unless `start` is False).
        After a failed start no new one is tried for a while, so every new session does
        not wait for the start timeout again."""
        self._reap_launchers()
        async with self._connect_lock:
            if self.connected:
                return
            if await self._try_connect():
                return
            if not start or not self.spawn_allowed:
                raise AgentdUnavailable("agentd não está rodando")
            if self._start_failed_at is not None and \
                    time.monotonic() - self._start_failed_at < self._start_cooldown:
                raise AgentdUnavailable("agentd não subiu há pouco; sem nova tentativa por ora")
            self._start_server()
            deadline = asyncio.get_running_loop().time() + START_WAIT
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
                if await self._try_connect():
                    self._start_failed_at = None
                    return
            self._start_failed_at = time.monotonic()
            raise AgentdUnavailable("agentd não respondeu a tempo")

    def _reap_launchers(self) -> None:
        """Collect agentd processes we started that have already exited (no zombies)."""
        self._procs = [proc for proc in self._procs if proc.poll() is None]

    def _start_server(self) -> None:
        proc = subprocess.Popen(  # noqa: S603 - argument list, no shell
            [sys.executable, "-m", "claudio_maestro.agentd", "--data-dir", str(self.data_dir),
             "--idle-exit", str(self._idle_exit), "--orphan-timeout", str(self._orphan_timeout)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True, env=os.environ.copy(),
        )
        self._procs.append(proc)

    async def _try_connect(self) -> bool:
        try:
            reader, writer = await asyncio.open_unix_connection(
                str(socket_path(self.data_dir)), limit=STREAM_LIMIT)
        except (FileNotFoundError, ConnectionRefusedError, OSError):
            return False
        self._reader, self._writer = reader, writer
        self._read_task = asyncio.create_task(self._read_loop(reader, writer))
        try:
            reply = await asyncio.wait_for(self._call("hello", protocol=PROTOCOL), HELLO_TIMEOUT)
        except (AgentdUnavailable, TimeoutError):
            await self._close_connection()
            return False
        self.server_pid = reply.get("pid")
        return True

    async def _read_loop(self, reader: asyncio.StreamReader,
                         writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                message = json.loads(line)
                req = message.get("req")
                if req is not None:
                    future = self._waiting.pop(req, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                queue = self._subscriptions.get(message.get("id", ""))
                if queue is not None:
                    queue.put_nowait(message)
        except (ConnectionError, asyncio.IncompleteReadError, ValueError):
            logger.warning("Conexão com o agentd perdida")
        finally:
            self._drop_connection(writer)

    def _drop_connection(self, writer: asyncio.StreamWriter | None = None) -> None:
        """Forget the connection `writer` (default: the current one). A call for a
        connection that was already replaced only closes that old writer."""
        if writer is not None and writer is not self._writer:
            writer.close()
            return
        if self._writer is not None:
            self._writer.close()
        self._writer = None
        for future in self._waiting.values():
            if not future.done():
                future.set_exception(AgentdUnavailable("conexão com o agentd perdida"))
        self._waiting.clear()
        for queue in self._subscriptions.values():
            queue.put_nowait({"ev": "lost"})
        self._subscriptions.clear()

    async def _close_connection(self) -> None:
        writer, task = self._writer, self._read_task
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        if task is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, 2)
        self._drop_connection(writer)

    async def _call(self, op: str, **args: Any) -> dict[str, Any]:
        if self._writer is None:
            raise AgentdUnavailable("sem conexão com o agentd")
        self._req += 1
        req = self._req
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._waiting[req] = future
        payload = (json.dumps({"op": op, "req": req, **args}) + "\n").encode()
        try:
            async with self._write_lock:
                self._writer.write(payload)
                await self._writer.drain()
        except (ConnectionError, AttributeError) as error:
            self._discard_waiter(req)
            raise AgentdUnavailable(str(error)) from error
        try:
            reply = await future
        finally:
            self._waiting.pop(req, None)
        if not reply.get("ok"):
            raise AgentdUnavailable(str(reply.get("error")))
        return reply

    def _discard_waiter(self, req: int) -> None:
        future = self._waiting.pop(req, None)
        if future is None:
            return
        if not future.done():
            future.cancel()
        elif not future.cancelled():
            future.exception()  # mark as retrieved

    async def spawn(self, session_id: str, spec: SpawnSpec) -> str:
        await self.ensure_running()
        reply = await self._call("spawn", session_id=session_id, cmd=spec.cmd, cwd=spec.cwd,
                                 env=spec.env)
        return str(reply["id"])

    async def write(self, child_id: str, data: str) -> None:
        await self._call("write", id=child_id, data=data)

    async def subscribe(self, child_id: str, start: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscriptions[child_id] = queue
        try:
            await self._call("subscribe", id=child_id, **{"from": start})
        except BaseException:
            if self._subscriptions.get(child_id) is queue:
                del self._subscriptions[child_id]
            raise
        return queue

    async def unsubscribe(self, child_id: str) -> None:
        self._subscriptions.pop(child_id, None)
        with contextlib.suppress(AgentdUnavailable):
            await self._call("unsubscribe", id=child_id)

    async def ack(self, child_id: str, pos: int) -> None:
        with contextlib.suppress(AgentdUnavailable):
            await self._call("ack", id=child_id, pos=pos)

    async def pending(self, child_id: str) -> list[str]:
        return list((await self._call("pending", id=child_id))["lines"])

    async def list(self) -> list[AgentdChild]:
        await self.ensure_running()
        reply = await self._call("list")
        return [AgentdChild.from_reply(child) for child in reply["children"]]

    async def kill(self, child_id: str) -> None:
        """Ask the agentd to stop the child (it returns before the process is gone; see
        `wait_gone`). A lost connection is re-made first, but no agentd is started."""
        self._subscriptions.pop(child_id, None)
        with contextlib.suppress(AgentdUnavailable):
            await self.ensure_running(start=False)
            await self._call("kill", id=child_id)

    async def wait_gone(self, child_id: str, timeout: float = GONE_WAIT) -> bool:
        """Wait until the agentd no longer holds the child (its process has exited).
        True also when the agentd cannot be asked: there is nothing left to wait for."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                await self.ensure_running(start=False)
                reply = await self._call("list")
            except AgentdUnavailable:
                return True
            if not any(child.get("id") == child_id for child in reply["children"]):
                return True
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning("O processo da sessão %s não saiu a tempo", child_id)
                return False
            await asyncio.sleep(GONE_POLL)

    async def aclose(self) -> None:
        await self._close_connection()
        self._reap_launchers()
