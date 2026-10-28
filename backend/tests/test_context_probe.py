"""`probe_context`: a throwaway client that reads the full context usage and always closes.

Uses the fake agent client; nothing here starts the real SDK.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from test_agent_sdk_client import make_options
from test_context_breakdown import FULL_USAGE

from claudio_maestro import contextprobe
from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.fake import FakeAgentClient
from claudio_maestro.contextprobe import probe_context


class ProbeFactory:
    """Builds fake clients whose `connect`, `get_context_usage` and `close` can be
    delayed or made to fail, and keeps them for inspection."""

    def __init__(self) -> None:
        self.clients: list[FakeAgentClient] = []
        self.usage: dict[str, Any] | None = FULL_USAGE
        self.connect_gate: asyncio.Event | None = None
        self.read_gate: asyncio.Event | None = None
        self.close_gate: asyncio.Event | None = None
        self.connect_error: Exception | None = None
        self.read_error: Exception | None = None
        self.close_error: Exception | None = None
        self.read_started = asyncio.Event()

    def __call__(self, options):
        client = FakeAgentClient(options)
        client.context_usage = self.usage
        self.clients.append(client)
        connect, read, close = client.connect, client.get_context_usage, client.close

        async def slow_connect():
            if self.connect_gate is not None:
                await self.connect_gate.wait()
            if self.connect_error is not None:
                raise self.connect_error
            await connect()

        async def slow_read(detail="full"):
            self.read_started.set()
            if self.read_gate is not None:
                await self.read_gate.wait()
            if self.read_error is not None:
                raise self.read_error
            return await read(detail)

        async def slow_close():
            if self.close_gate is not None:
                await self.close_gate.wait()
            await close()
            if self.close_error is not None:
                raise self.close_error

        client.connect, client.get_context_usage, client.close = slow_connect, slow_read, slow_close
        return client


@pytest.fixture
def factory() -> ProbeFactory:
    return ProbeFactory()


def options(tmp_path: Path):
    return make_options(tmp_path, resume=True)


@pytest.mark.anyio
async def test_probe_returns_the_full_usage_and_closes(factory, tmp_path):
    opts = options(tmp_path)

    usage = await probe_context(factory, opts, 5)

    assert usage == FULL_USAGE
    (client,) = factory.clients
    assert client.options is opts
    assert client.connected and client.closed
    assert client.context_usage_details == ["full"]


@pytest.mark.anyio
async def test_probe_returns_none_when_the_cli_has_no_data(factory, tmp_path):
    factory.usage = None

    assert await probe_context(factory, options(tmp_path), 5) is None
    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_probe_closes_when_connect_fails(factory, tmp_path):
    factory.connect_error = AgentError("não abriu")

    with pytest.raises(AgentError):
        await probe_context(factory, options(tmp_path), 5)

    (client,) = factory.clients
    assert client.closed and client.context_usage_calls == 0


@pytest.mark.anyio
async def test_probe_closes_when_the_read_fails(factory, tmp_path):
    factory.read_error = AgentError("quebrou")

    with pytest.raises(AgentError):
        await probe_context(factory, options(tmp_path), 5)

    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_probe_times_out_in_the_read_and_closes(factory, tmp_path):
    factory.read_gate = asyncio.Event()  # never opens

    with pytest.raises(TimeoutError):
        await probe_context(factory, options(tmp_path), 0.05)

    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_probe_limit_includes_connect(factory, tmp_path):
    factory.connect_gate = asyncio.Event()  # never opens

    with pytest.raises(TimeoutError):
        await probe_context(factory, options(tmp_path), 0.05)

    (client,) = factory.clients
    assert client.closed and client.context_usage_calls == 0


@pytest.mark.anyio
async def test_probe_closes_when_the_caller_is_cancelled(factory, tmp_path):
    factory.read_gate = asyncio.Event()
    task = asyncio.create_task(probe_context(factory, options(tmp_path), 30))
    await asyncio.wait_for(factory.read_started.wait(), 2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_probe_closes_when_cancelled_during_connect(factory, tmp_path):
    factory.connect_gate = asyncio.Event()
    task = asyncio.create_task(probe_context(factory, options(tmp_path), 30))
    await asyncio.sleep(0.01)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_close_failure_does_not_mask_the_error(factory, tmp_path):
    factory.read_error = AgentError("quebrou")
    factory.close_error = RuntimeError("o close também falhou")

    with pytest.raises(AgentError, match="quebrou"):
        await probe_context(factory, options(tmp_path), 5)


@pytest.mark.anyio
async def test_close_failure_does_not_lose_the_usage(factory, tmp_path):
    factory.close_error = RuntimeError("o close falhou")

    assert await probe_context(factory, options(tmp_path), 5) == FULL_USAGE


@pytest.mark.anyio
async def test_a_close_that_hangs_does_not_hang_the_probe(
    factory, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(contextprobe, "CLOSE_LIMIT", 0.05)
    factory.close_gate = asyncio.Event()  # never opens

    usage = await asyncio.wait_for(probe_context(factory, options(tmp_path), 5), 2)

    assert usage == FULL_USAGE
    factory.close_gate.set()  # lets the abandoned close finish
    await asyncio.sleep(0.01)
    assert factory.clients[0].closed


@pytest.mark.anyio
async def test_a_refusing_factory_raises_without_a_client(tmp_path):
    def refuse(opts):
        raise AgentError("O servidor de E2E não inicia o agente real.")

    with pytest.raises(AgentError):
        await probe_context(refuse, options(tmp_path), 5)


# `after_close`: runs once the client's close finished ---------------------------------


@pytest.mark.anyio
async def test_after_close_runs_after_the_client_closed(factory, tmp_path):
    seen: list[bool] = []
    after = lambda: seen.append(factory.clients[0].closed)  # noqa: E731

    await probe_context(factory, options(tmp_path), 5, after_close=after)

    assert seen == [True]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["connect", "read", "timeout", "close"])
async def test_after_close_runs_on_every_path(factory, tmp_path, failure):
    calls: list[int] = []
    limit = 5.0
    if failure == "connect":
        factory.connect_error = AgentError("não abriu")
    elif failure == "read":
        factory.read_error = AgentError("quebrou")
    elif failure == "timeout":
        factory.read_gate = asyncio.Event()
        limit = 0.05
    else:
        factory.close_error = AgentError("não fechou")

    try:
        await probe_context(factory, options(tmp_path), limit, after_close=lambda: calls.append(1))
    except (AgentError, TimeoutError):
        pass

    assert calls == [1]


@pytest.mark.anyio
async def test_after_close_runs_when_the_caller_is_cancelled(factory, tmp_path):
    calls: list[int] = []
    factory.read_gate = asyncio.Event()
    task = asyncio.create_task(
        probe_context(factory, options(tmp_path), 30, after_close=lambda: calls.append(1))
    )
    await asyncio.wait_for(factory.read_started.wait(), 2)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls == [1]


@pytest.mark.anyio
async def test_after_close_runs_even_when_the_close_outlives_the_limit(
    factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(contextprobe, "CLOSE_LIMIT", 0.05)
    calls: list[int] = []
    factory.close_gate = asyncio.Event()

    await probe_context(factory, options(tmp_path), 5, after_close=lambda: calls.append(1))
    assert calls == []  # the probe stopped waiting; the close goes on

    factory.close_gate.set()
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.01)
    assert calls == [1]


@pytest.mark.anyio
async def test_a_failing_after_close_never_replaces_the_result(factory, tmp_path):
    def boom() -> None:
        raise OSError("disco")

    assert await probe_context(factory, options(tmp_path), 5, after_close=boom) == FULL_USAGE
