"""The agentd server: owns `claude` processes and their stdout log.

It reads only `type`, `request_id` and `request.subtype` of the lines it passes
on, to keep unanswered control requests and the initialize response. Everything
else about the protocol stays in the backend.
"""

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import signal
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claudio_maestro.agentd import PROTOCOL, peer
from claudio_maestro.agentd.paths import lock_path, private_dir, socket_path

logger = logging.getLogger("claudio_maestro.agentd")

LOG_LIMIT_BYTES = 64 * 1024 * 1024
STDERR_LINES = 50
KILL_GRACE = 5.0
STREAM_LIMIT = 256 * 1024 * 1024  # one JSON line can carry many images
WATCH_INTERVAL = 0.1
EXIT_POLL = 0.1
DRAIN_GRACE = 1.0  # time the pumps get to read what is buffered after a process exits


class LockedError(Exception):
    """Another agentd holds the lock of this data dir."""


@dataclass
class Child:
    id: str
    session_id: str
    proc: asyncio.subprocess.Process
    lines: deque[tuple[int, str, int]] = field(default_factory=deque)  # (pos, text, bytes)
    pumps: list[asyncio.Task[None]] = field(default_factory=list)
    next_pos: int = 0
    ack: int = 0
    size: int = 0
    truncated_from: int = 0
    pending: dict[str, str] = field(default_factory=dict)
    init_request: str | None = None
    init: Any = None
    stderr: deque[str] = field(default_factory=lambda: deque(maxlen=STDERR_LINES))
    exit_code: int | None = None
    subscribers: set["Client"] = field(default_factory=set)
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def info(self) -> dict[str, Any]:
        return {"id": self.id, "session_id": self.session_id, "pid": self.proc.pid,
                "next_pos": self.next_pos, "ack": self.ack, "exit_code": self.exit_code,
                "init": self.init}


class Client:
    """One backend connection. Every outgoing message goes through one queue,
    so replies and events keep their order."""

    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.task = asyncio.create_task(self._drain())

    def send(self, message: dict[str, Any]) -> None:
        self.queue.put_nowait(message)

    async def _drain(self) -> None:
        with contextlib.suppress(OSError):  # ConnectionError is an OSError
            while (message := await self.queue.get()) is not None:
                self.writer.write((json.dumps(message) + "\n").encode())
                await self.writer.drain()

    async def close(self) -> None:
        self.queue.put_nowait(None)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.task, 2)
        self.writer.close()


def _peek(line: str) -> dict[str, Any] | None:
    """Parse only lines that may matter to the agentd's own bookkeeping."""
    if '"control_' not in line:
        return None
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


class Agentd:
    def __init__(self, data_dir: Path, *, idle_exit: float, orphan_timeout: float) -> None:
        self.data_dir = data_dir
        self.idle_exit = idle_exit
        self.orphan_timeout = orphan_timeout
        self.children: dict[str, Child] = {}
        self.clients: set[Client] = set()
        self.ready = asyncio.Event()
        self._stopping = asyncio.Event()
        self._alone_since = time.monotonic()
        self._lock_fd: int | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    # Lifecycle -------------------------------------------------------------

    def _acquire_lock(self) -> None:
        private_dir(self.data_dir)
        fd = os.open(lock_path(self.data_dir), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(fd)
            raise LockedError from error
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._lock_fd = fd

    async def serve(self) -> None:
        self._acquire_lock()
        path = socket_path(self.data_dir)
        private_dir(path.parent)
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        server = await asyncio.start_unix_server(self._handle, str(path), limit=STREAM_LIMIT)
        os.chmod(path, 0o600)
        logger.info("agentd %s ouvindo em %s", os.getpid(), path)
        self.ready.set()
        watcher = asyncio.create_task(self._watch())
        try:
            await self._stopping.wait()
        finally:
            watcher.cancel()
            server.close()
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            try:
                for client in list(self.clients):
                    await client.close()
                await self._kill_all()
            finally:
                if self._lock_fd is not None:
                    os.close(self._lock_fd)
                logger.info("agentd %s encerrado", os.getpid())

    def request_stop(self) -> None:
        """Synchronous variant of `stop`, safe in signal handlers."""
        self._stopping.set()

    async def stop(self) -> None:
        self.request_stop()

    def _background(self, coro: Any) -> asyncio.Task[Any]:
        """Run `coro` as a task, keeping a reference so it is not garbage-collected."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            if self.clients:
                self._alone_since = time.monotonic()
                continue
            alone = time.monotonic() - self._alone_since
            if not self.children and alone >= self.idle_exit:
                logger.info("Sem sessões e sem backend; saindo")
                self._stopping.set()
                return
            if self.children and alone >= self.orphan_timeout:
                logger.info("Sem backend há %.0f s; encerrando as sessões", alone)
                self._stopping.set()
                return

    async def _kill_all(self) -> None:
        for child in list(self.children.values()):
            self._terminate(child)
        waits = [c.done.wait() for c in self.children.values()]
        if waits:
            try:
                await asyncio.wait_for(asyncio.gather(*waits), KILL_GRACE * 2)
            except TimeoutError:
                logger.warning("Alguns processos não encerraram a tempo")

    # Connections -----------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        if peer.peer_uid(sock) not in (os.getuid(), None):
            logger.warning("Conexão de outro usuário recusada")
            writer.close()
            return
        client = Client(writer)
        self.clients.add(client)
        try:
            while line := await reader.readline():
                request: Any = {}
                try:
                    request = json.loads(line)
                    reply = await self._dispatch(client, request)
                except Exception as error:  # noqa: BLE001 - one bad request must not kill the server
                    logger.exception("Pedido inválido")
                    reply = {"ok": False, "error": str(error)}
                    if not isinstance(request, dict):
                        request = {}
                reply["req"] = request.get("req")
                client.send(reply)
                # Backlog of a subscribe goes after its reply.
                if request.get("op") == "subscribe" and reply.get("ok"):
                    self._replay(client, self.children[request["id"]], request["from"])
        finally:
            self.clients.discard(client)
            for child in self.children.values():
                child.subscribers.discard(client)
            self._alone_since = time.monotonic()
            await client.close()

    async def _dispatch(self, client: Client, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "hello":
            if request.get("protocol") != PROTOCOL:
                return {"ok": False, "error": "protocol"}
            return {"ok": True, "protocol": PROTOCOL, "pid": os.getpid()}
        if op == "spawn":
            child = await self._spawn(request["session_id"], request["cmd"],
                                      request.get("cwd"), request.get("env") or {})
            return {"ok": True, "id": child.id}
        if op == "list":
            return {"ok": True, "children": [c.info() for c in self.children.values()]}
        if op == "shutdown":
            self._stopping.set()
            return {"ok": True}
        child = self.children.get(request.get("id", ""))
        if child is None:
            return {"ok": False, "error": "unknown child"}
        if op == "write":
            await self._write(child, request["data"])
            return {"ok": True}
        if op == "subscribe":
            start = request.get("from")
            if not isinstance(start, int) or isinstance(start, bool):
                return {"ok": False, "error": "from must be an integer"}
            child.subscribers.add(client)
            return {"ok": True}
        if op == "unsubscribe":
            child.subscribers.discard(client)
            return {"ok": True}
        if op == "ack":
            self._ack(child, int(request["pos"]))
            return {"ok": True}
        if op == "pending":
            return {"ok": True, "lines": list(child.pending.values())}
        if op == "kill":
            self._terminate(child)
            return {"ok": True}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # Children --------------------------------------------------------------

    async def _spawn(self, session_id: str, cmd: list[str], cwd: str | None,
                     env: dict[str, str]) -> Child:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=STREAM_LIMIT,
        )
        child = Child(id=uuid.uuid4().hex, session_id=session_id, proc=proc)
        self.children[child.id] = child
        logger.info("Sessão %s: processo %s iniciado (%s)", session_id, proc.pid, child.id)
        child.pumps = [self._background(self._pump_stdout(child)),
                       self._background(self._pump_stderr(child))]
        self._background(self._watch_exit(child))
        return child

    async def _write(self, child: Child, data: str) -> None:
        stdin = child.proc.stdin
        if stdin is None or child.exit_code is not None or child.proc.returncode is not None:
            raise RuntimeError("process has exited")
        stdin.write(data.encode())
        await stdin.drain()
        # Bookkeeping only after the process took the line: a refused response
        # must leave its request pending.
        message = _peek(data)
        if message is None:
            return
        kind = message.get("type")
        if kind == "control_response":
            child.pending.pop(str((message.get("response") or {}).get("request_id")), None)
        elif kind == "control_request" and \
                (message.get("request") or {}).get("subtype") == "initialize":
            child.init_request = message.get("request_id")

    def _ack(self, child: Child, pos: int) -> None:
        child.ack = max(child.ack, min(pos, child.next_pos))
        while child.lines and child.lines[0][0] < child.ack:
            child.size -= child.lines.popleft()[2]
        child.truncated_from = max(child.truncated_from, child.ack)

    def _replay(self, client: Client, child: Child, start: int) -> None:
        first = child.lines[0][0] if child.lines else child.next_pos
        if start < first and start < child.next_pos:
            client.send({"ev": "gap", "id": child.id, "from": first})
        for pos, text, _size in child.lines:
            if pos >= start:
                client.send({"ev": "line", "id": child.id, "pos": pos, "line": text})
        if child.exit_code is not None:
            client.send({"ev": "exit", "id": child.id, "code": child.exit_code,
                         "stderr": list(child.stderr)})

    async def _pump_stdout(self, child: Child) -> None:
        stdout = child.proc.stdout
        assert stdout is not None
        while True:
            try:
                raw = await stdout.readline()
            except ValueError:
                # A line over STREAM_LIMIT; the stream is out of sync, so stop the session.
                logger.exception("Sessão %s: linha grande demais no stdout", child.session_id)
                self._terminate(child)
                return
            if not raw:
                return
            text = raw.decode(errors="replace").rstrip("\n")
            if not text:
                continue
            self._note_output(child, text)
            pos = child.next_pos
            child.next_pos += 1
            child.lines.append((pos, text, len(raw)))
            child.size += len(raw)
            while child.size > LOG_LIMIT_BYTES and child.lines:
                child.size -= child.lines.popleft()[2]
                child.truncated_from = child.lines[0][0] if child.lines else child.next_pos
            for client in child.subscribers:
                client.send({"ev": "line", "id": child.id, "pos": pos, "line": text})

    async def _watch_exit(self, child: Child) -> None:
        """Detect the exit from `returncode`, not from stdout EOF: a grandchild
        that inherited the pipes keeps them open after `claude` is gone."""
        while child.proc.returncode is None:
            await asyncio.sleep(EXIT_POLL)
        _done, pending = await asyncio.wait(child.pumps, timeout=DRAIN_GRACE)
        for pump in pending:
            pump.cancel()
        if pending:
            await asyncio.wait(pending)
        # Release our ends of the pipes even if a grandchild still holds the other ones.
        transport = getattr(child.proc, "_transport", None)
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.close()
        child.exit_code = child.proc.returncode
        logger.info("Sessão %s: processo saiu com código %s", child.session_id, child.exit_code)
        for client in child.subscribers:
            client.send({"ev": "exit", "id": child.id, "code": child.exit_code,
                         "stderr": list(child.stderr)})
        child.done.set()

    def _note_output(self, child: Child, text: str) -> None:
        message = _peek(text)
        if message is None:
            return
        kind = message.get("type")
        if kind == "control_request":
            child.pending[str(message.get("request_id"))] = text
        elif kind == "control_cancel_request":
            child.pending.pop(str(message.get("request_id")), None)
        elif kind == "control_response":
            response = message.get("response") or {}
            if child.init_request and response.get("request_id") == child.init_request:
                child.init = response.get("response")

    async def _pump_stderr(self, child: Child) -> None:
        stderr = child.proc.stderr
        assert stderr is not None
        while True:
            try:
                raw = await stderr.readline()
            except ValueError:
                logger.exception("Sessão %s: linha grande demais no stderr", child.session_id)
                return
            if not raw:
                return
            child.stderr.append(raw.decode(errors="replace").rstrip("\n"))

    def _terminate(self, child: Child) -> None:
        if child.exit_code is None and child.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                child.proc.send_signal(signal.SIGTERM)
        self._background(self._reap(child))

    async def _reap(self, child: Child) -> None:
        try:
            await asyncio.wait_for(child.done.wait(), KILL_GRACE)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                child.proc.kill()
            try:
                await asyncio.wait_for(child.done.wait(), KILL_GRACE)
            except TimeoutError:
                logger.warning("Sessão %s: processo %s não saiu nem com SIGKILL",
                               child.session_id, child.proc.pid)
        self.children.pop(child.id, None)
