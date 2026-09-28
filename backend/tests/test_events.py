"""Event hub: fan-out of session events to every connected WebSocket."""

import asyncio
import json

import anyio
import pytest

from vibing.events import EventHub

WAIT = 2


class FakeWebSocket:
    """Minimal stand-in for starlette's WebSocket."""

    def __init__(self, fail_on_send: bool = False) -> None:
        self.fail_on_send = fail_on_send
        self.accepted = False
        self.closed = False
        self.sent: list[dict] = []
        self._incoming: asyncio.Queue[dict] = asyncio.Queue()

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        return await self._incoming.get()

    async def send_text(self, text: str) -> None:
        if self.fail_on_send:
            raise RuntimeError("conexão caiu")
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    def disconnect(self) -> None:
        self._incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})


async def wait_until(predicate) -> None:
    with anyio.fail_after(WAIT):
        while not predicate():
            await anyio.sleep(0.001)


def envelope(seq: int) -> dict:
    return {"session_id": "s1", "seq": seq, "type": "item.append", "data": {"text": "ç"}}


@pytest.mark.anyio
async def test_every_connection_gets_every_event():
    hub = EventHub()
    one, two = FakeWebSocket(), FakeWebSocket()
    async with anyio.create_task_group() as tg:
        tg.start_soon(hub.serve, one)
        tg.start_soon(hub.serve, two)
        await wait_until(lambda: hub.connection_count == 2)

        hub.publish(envelope(1))
        hub.publish(envelope(2))
        await wait_until(lambda: len(one.sent) == len(two.sent) == 2)

        one.disconnect()
        two.disconnect()

    assert one.accepted and two.accepted
    assert one.sent == two.sent == [envelope(1), envelope(2)]
    assert hub.connection_count == 0


@pytest.mark.anyio
async def test_failed_send_removes_only_that_connection():
    hub = EventHub()
    broken, healthy = FakeWebSocket(fail_on_send=True), FakeWebSocket()
    async with anyio.create_task_group() as tg:
        tg.start_soon(hub.serve, broken)
        tg.start_soon(hub.serve, healthy)
        await wait_until(lambda: hub.connection_count == 2)

        hub.publish(envelope(1))
        await wait_until(lambda: hub.connection_count == 1)
        hub.publish(envelope(2))
        await wait_until(lambda: len(healthy.sent) == 2)

        healthy.disconnect()

    assert broken.closed is True
    assert healthy.sent == [envelope(1), envelope(2)]


@pytest.mark.anyio
async def test_publish_does_not_wait_for_slow_connections():
    hub = EventHub()
    stuck = FakeWebSocket()
    gate = asyncio.Event()

    async def slow_send(text: str) -> None:
        await gate.wait()

    stuck.send_text = slow_send  # type: ignore[method-assign]
    async with anyio.create_task_group() as tg:
        tg.start_soon(hub.serve, stuck)
        await wait_until(lambda: hub.connection_count == 1)

        for seq in range(1, 50):
            hub.publish(envelope(seq))  # synchronous: returns without awaiting the socket

        gate.set()
        stuck.disconnect()


@pytest.mark.anyio
async def test_overflowing_connection_is_dropped():
    hub = EventHub(max_queue=3)
    stuck = FakeWebSocket()
    gate = asyncio.Event()

    async def slow_send(text: str) -> None:
        await gate.wait()

    stuck.send_text = slow_send  # type: ignore[method-assign]
    async with anyio.create_task_group() as tg:
        tg.start_soon(hub.serve, stuck)
        await wait_until(lambda: hub.connection_count == 1)

        for seq in range(1, 10):
            hub.publish(envelope(seq))
        await wait_until(lambda: hub.connection_count == 0)

    assert stuck.closed is True


@pytest.mark.anyio
async def test_publish_without_connections_is_harmless():
    EventHub().publish(envelope(1))
