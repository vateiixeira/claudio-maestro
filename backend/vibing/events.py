"""Fan-out of session events to every connected WebSocket.

Each connection has its own queue and sender task, so `publish` never waits on
a socket. A connection whose send fails, or whose queue overflows, is dropped
without affecting the others.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio

logger = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE = 10_000


class WebSocketLike(Protocol):
    async def accept(self) -> None: ...

    async def receive(self) -> Any: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


@dataclass(eq=False)
class _Connection:
    websocket: WebSocketLike
    queue: asyncio.Queue[str]
    dropped: asyncio.Event = field(default_factory=asyncio.Event)
    client_left: bool = False


class EventHub:
    def __init__(self, max_queue: int = DEFAULT_MAX_QUEUE) -> None:
        self._max_queue = max_queue
        self._connections: set[_Connection] = set()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def publish(self, envelope: dict[str, Any]) -> None:
        """Queue the envelope for every connection. Never blocks."""
        if not self._connections:
            return
        text = json.dumps(envelope, ensure_ascii=False, default=str)
        for connection in list(self._connections):
            try:
                connection.queue.put_nowait(text)
            except asyncio.QueueFull:
                logger.warning("Conexão WebSocket lenta demais; descartada.")
                self._drop(connection)

    async def serve(self, websocket: WebSocketLike) -> None:
        """Accept the socket and keep it registered until either side ends."""
        await websocket.accept()
        connection = _Connection(websocket, asyncio.Queue(maxsize=self._max_queue))
        self._connections.add(connection)
        try:
            async with anyio.create_task_group() as tg:

                async def until_done(wait: Callable[[], Awaitable[Any]]) -> None:
                    await wait()
                    tg.cancel_scope.cancel()

                tg.start_soon(until_done, lambda: self._send_loop(connection))
                tg.start_soon(until_done, lambda: self._receive_loop(connection))
                tg.start_soon(until_done, connection.dropped.wait)
        finally:
            # No await here: this also runs when the server cancels the task.
            self._connections.discard(connection)
        if not connection.client_left:
            with suppress(Exception):
                await websocket.close()

    def _drop(self, connection: _Connection) -> None:
        self._connections.discard(connection)
        connection.dropped.set()

    async def _send_loop(self, connection: _Connection) -> None:
        while True:
            text = await connection.queue.get()
            try:
                await connection.websocket.send_text(text)
            except Exception:
                self._drop(connection)
                return

    @staticmethod
    async def _receive_loop(connection: _Connection) -> None:
        # Clients have nothing to say on this socket; only wait for them to leave.
        try:
            while True:
                message = await connection.websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
        except Exception:
            pass
        connection.client_left = True
