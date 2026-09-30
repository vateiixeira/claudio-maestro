"""Slash command catalog: throwaway client, filtering, cache, errors."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from vibing.agent.base import AgentError, AgentOptions
from vibing.agent.fake import FakeAgentFactory
from vibing.commands import (
    NO_HOOKS,
    CommandCatalog,
    CommandCatalogError,
    CommandInfo,
    parse_commands,
)

RAW = [
    {"name": "commit", "description": "Cria um commit", "argumentHint": ""},
    {"name": "hello", "description": "Diz olá (project)", "argumentHint": "<nome>"},
    {"name": "superpowers:brainstorming", "description": "Explora ideias"},
    {"name": "clear", "description": "Limpa", "builtin": True},
    {"name": "__internal", "description": "x"},
    {"description": "sem nome"},
    "lixo",
]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_parse_drops_builtins_internal_and_nameless_and_strips_project_suffix():
    assert parse_commands(RAW) == [
        CommandInfo("commit", "Cria um commit", ""),
        CommandInfo("hello", "Diz olá", "<nome>"),
        CommandInfo("superpowers:brainstorming", "Explora ideias", ""),
    ]


def test_parse_accepts_missing_or_invalid_list():
    assert parse_commands(None) == []
    assert parse_commands({"x": 1}) == []


@pytest.mark.anyio
async def test_list_uses_a_throwaway_client_without_hooks_in_the_folder(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    catalog = CommandCatalog(factory)
    commands = await catalog.list(tmp_path)
    assert [c.name for c in commands] == ["commit", "hello", "superpowers:brainstorming"]
    [client] = factory.clients
    options: AgentOptions = client.options
    assert options.cwd == tmp_path.resolve()
    assert options.resume is False
    assert options.settings == NO_HOOKS
    assert json.loads(NO_HOOKS) == {"disableAllHooks": True}
    assert options.setting_sources is None
    assert client.connected and client.closed


@pytest.mark.anyio
async def test_cache_lasts_five_minutes_per_folder(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = CommandCatalog(factory, clock=clock)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    await catalog.list(a)
    await catalog.list(a)
    assert len(factory.clients) == 1
    await catalog.list(b)
    assert len(factory.clients) == 2
    clock.now += 5 * 60 - 1
    await catalog.list(a)
    assert len(factory.clients) == 2
    clock.now += 1
    await catalog.list(a)
    assert len(factory.clients) == 3


class _GatedClient:
    """Fake client whose get_server_info waits for a gate."""

    def __init__(self, options: AgentOptions, gate: asyncio.Event, hang: bool = False) -> None:
        self.options = options
        self.gate = gate
        self.hang = hang
        self.closed = False

    async def connect(self) -> None:
        return None

    async def get_server_info(self) -> dict[str, Any] | None:
        if self.hang:
            await asyncio.Event().wait()
        await self.gate.wait()
        return {"commands": RAW}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_two_simultaneous_requests_open_one_client(tmp_path: Path):
    gate = asyncio.Event()
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, gate)
        clients.append(client)
        return client

    catalog = CommandCatalog(factory)  # type: ignore[arg-type]
    first = asyncio.create_task(catalog.list(tmp_path))
    second = asyncio.create_task(catalog.list(tmp_path))
    await asyncio.sleep(0)
    gate.set()
    assert (await first) == (await second)
    assert len(clients) == 1


@pytest.mark.anyio
async def test_timeout_raises_and_is_not_cached_and_closes(tmp_path: Path):
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, asyncio.Event(), hang=not clients)
        clients.append(client)
        if not client.hang:
            client.gate.set()
        return client

    catalog = CommandCatalog(factory, timeout=0.05)  # type: ignore[arg-type]
    with pytest.raises(CommandCatalogError, match="demorou demais"):
        await catalog.list(tmp_path)
    assert clients[0].closed
    assert [c.name for c in await catalog.list(tmp_path)][0] == "commit"
    assert len(clients) == 2


@pytest.mark.anyio
async def test_connect_failure_raises_with_the_agent_message_and_closes(tmp_path: Path):
    factory = FakeAgentFactory(connect_error=AgentError("CLI não encontrado."))
    catalog = CommandCatalog(factory)
    with pytest.raises(CommandCatalogError, match="CLI não encontrado."):
        await catalog.list(tmp_path)
    assert factory.clients[0].closed
    # Failures are not cached.
    with pytest.raises(CommandCatalogError):
        await catalog.list(tmp_path)
    assert len(factory.clients) == 2
