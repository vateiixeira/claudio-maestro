"""Slash command catalog: throwaway client, filtering, cache, errors."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from claudio_maestro.agent.base import AgentError, AgentOptions
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.commands import (
    EXPIRE_SECONDS,
    NO_HOOKS,
    REFRESH_SECONDS,
    RETRY_SECONDS,
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
    assert options.entrypoint is None
    assert client.connected and client.closed


def _catalog(tmp_path: Path, factory: Any, clock: Clock | None = None, **kwargs: Any) -> CommandCatalog:
    config = tmp_path / "claude-config"
    config.mkdir(exist_ok=True)
    return CommandCatalog(factory, clock=clock or Clock(), config_dir=config, **kwargs)


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.anyio
async def test_cache_is_per_folder_and_answers_without_a_new_client(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    await catalog.list(a)
    await catalog.list(a)
    assert len(factory.clients) == 1
    await catalog.list(b)
    assert len(factory.clients) == 2
    clock.now += REFRESH_SECONDS - 1
    await catalog.list(a)
    await _settle()
    assert len(factory.clients) == 2


@pytest.mark.anyio
async def test_old_list_answers_at_once_and_is_refreshed_in_the_background(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    await catalog.list(tmp_path)
    factory.server_info = {"commands": [{"name": "nova", "description": ""}]}
    clock.now += REFRESH_SECONDS
    # The old list comes back right away; the new one is fetched behind it.
    assert [c.name for c in await catalog.list(tmp_path)][0] == "commit"
    await _settle()
    assert len(factory.clients) == 2
    assert factory.clients[1].closed
    assert [c.name for c in await catalog.list(tmp_path)] == ["nova"]
    await _settle()
    assert len(factory.clients) == 2


@pytest.mark.anyio
async def test_one_background_refresh_at_a_time_per_folder(tmp_path: Path):
    gate = asyncio.Event()
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, gate)
        clients.append(client)
        return client

    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    gate.set()
    await catalog.list(tmp_path)
    gate.clear()
    clock.now += REFRESH_SECONDS
    await catalog.list(tmp_path)
    await catalog.list(tmp_path)
    await _settle()
    assert len(clients) == 2
    gate.set()
    await _settle()
    assert clients[1].closed


@pytest.mark.anyio
async def test_failed_background_refresh_keeps_the_old_list(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    await catalog.list(tmp_path)
    factory.connect_error = AgentError("CLI não encontrado.")
    clock.now += REFRESH_SECONDS
    await catalog.list(tmp_path)
    await _settle()
    assert len(factory.clients) == 2
    assert [c.name for c in await catalog.list(tmp_path)][0] == "commit"
    # Right after a failure, opening the menu again starts no new client.
    await _settle()
    assert len(factory.clients) == 2
    clock.now += RETRY_SECONDS
    await catalog.list(tmp_path)
    await _settle()
    assert len(factory.clients) == 3


@pytest.mark.anyio
async def test_expired_entries_take_their_lock_with_them(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    await catalog.list(a)
    clock.now += EXPIRE_SECONDS
    await catalog.list(b)
    assert set(catalog._locks) == {b.resolve()}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "where",
    [
        "config/skills/nova",
        "config/commands/nova.md",
        "config/plugins/installed_plugins.json",
        "config/settings.json",
        "folder/.claude/skills/nova",
        "folder/.claude/commands/nova.md",
        "folder/.claude/settings.json",
        "folder/.claude/settings.local.json",
    ],
)
async def test_change_in_skills_commands_or_plugins_refreshes_before_ten_minutes(
    tmp_path: Path, where: str
):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    catalog = _catalog(tmp_path, factory)
    folder = tmp_path / "folder"
    folder.mkdir()
    roots = {"config": tmp_path / "claude-config", "folder": folder}
    await catalog.list(folder)
    root, rest = where.split("/", 1)
    target = roots[root] / rest
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix:
        target.write_text("{}")
    else:
        target.mkdir()
    await catalog.list(folder)
    await _settle()
    assert len(factory.clients) == 2
    # Nothing changed since: no new client.
    await catalog.list(folder)
    await _settle()
    assert len(factory.clients) == 2


@pytest.mark.anyio
async def test_list_unused_for_a_day_is_dropped_and_fetched_again(tmp_path: Path):
    factory = FakeAgentFactory(server_info={"commands": RAW})
    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    await catalog.list(tmp_path)
    factory.server_info = {"commands": [{"name": "nova", "description": ""}]}
    clock.now += EXPIRE_SECONDS
    assert [c.name for c in await catalog.list(tmp_path)] == ["nova"]
    assert len(factory.clients) == 2


@pytest.mark.anyio
async def test_close_cancels_the_background_refresh(tmp_path: Path):
    clients: list[_GatedClient] = []

    def factory(options: AgentOptions) -> _GatedClient:
        client = _GatedClient(options, asyncio.Event(), hang=bool(clients))
        if not clients:
            client.gate.set()
        clients.append(client)
        return client

    clock = Clock()
    catalog = _catalog(tmp_path, factory, clock)
    await catalog.list(tmp_path)
    clock.now += REFRESH_SECONDS
    await catalog.list(tmp_path)
    await _settle()
    await catalog.aclose()
    assert clients[1].closed


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
