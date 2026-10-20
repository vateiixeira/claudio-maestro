"""Slash commands available in a folder: user, project and plugin commands and
skills, read from the CLI with a throwaway client that runs no hooks.

Built-in CLI commands are left out: the app has its own controls for them.

Starting the CLI takes seconds, so a list once read answers at once from memory. It
is read again in the background when it gets old or when a folder of skills,
commands or plugins changes, and the next request gets the new list.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_agent_sdk import PermissionResultDeny

from claudio_maestro.agent.base import (
    AgentClient,
    AgentError,
    AgentFactory,
    AgentOptions,
)
from claudio_maestro.config import claude_config_dir

logger = logging.getLogger(__name__)

# A list older than this is read again in the background on its next use.
REFRESH_SECONDS = 10 * 60
# A list unused for this long is dropped; the next request waits for a new one.
EXPIRE_SECONDS = 24 * 60 * 60
# After a failed background refresh, the next one waits this long.
RETRY_SECONDS = 60
TIMEOUT_SECONDS = 10.0
# Connecting fires SessionStart hooks; this keeps the list and runs none.
NO_HOOKS = '{"disableAllHooks": true}'
_PROJECT_SUFFIX = " (project)"


class CommandCatalogError(Exception):
    """Failure with a message ready to show (pt-BR)."""


@dataclass(frozen=True)
class CommandInfo:
    name: str
    description: str
    argument_hint: str


# `CommandCatalog.list` shadows the builtin inside the class body, so annotations
# there use this alias.
CommandList = list[CommandInfo]


async def _deny_all(tool_name: str, tool_input: dict[str, Any], context: Any) -> PermissionResultDeny:
    return PermissionResultDeny(message="Cliente só para listar comandos.")


def parse_commands(raw: Any) -> list[CommandInfo]:
    """`get_server_info()["commands"]` without built-ins, internal names and nameless
    entries, with the " (project)" suffix removed, sorted by name."""
    found: list[CommandInfo] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or entry.get("builtin") is True:
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or name.startswith("__"):
            continue
        description = entry.get("description")
        description = description if isinstance(description, str) else ""
        if description.endswith(_PROJECT_SUFFIX):
            description = description[: -len(_PROJECT_SUFFIX)]
        hint = entry.get("argumentHint")
        found.append(CommandInfo(name, description, hint if isinstance(hint, str) else ""))
    found.sort(key=lambda command: command.name)
    return found


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


@dataclass
class _Entry:
    commands: CommandList
    fetched_at: float
    used_at: float
    # Modification times of the places the list comes from, read before the fetch.
    stamp: tuple[int | None, ...]


class CommandCatalog:
    """Commands per folder, kept in memory. Concurrent requests for the same folder
    share one client. Failures are not cached; a failed background refresh keeps the
    old list."""

    def __init__(
        self,
        agent_factory: AgentFactory,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = TIMEOUT_SECONDS,
        config_dir: Path | None = None,
    ) -> None:
        self._factory = agent_factory
        self._clock = clock
        self._timeout = timeout
        self._config_dir = config_dir
        self._cache: dict[Path, _Entry] = {}
        self._locks: dict[Path, asyncio.Lock] = {}
        self._refreshing: dict[Path, asyncio.Task[None]] = {}
        self._failed_at: dict[Path, float] = {}

    async def list(self, folder: Path) -> CommandList:
        key = folder.resolve()
        self._drop_expired()
        entry = self._cache.get(key)
        if entry is not None:
            entry.used_at = self._clock()
            if self._is_old(key, entry):
                self._refresh_later(key)
            return entry.commands
        async with self._lock(key):
            entry = self._cache.get(key)
            if entry is not None:
                return entry.commands
            return await self._load(key)

    async def aclose(self) -> None:
        """Cancels the background refreshes (on app shutdown)."""
        tasks = list(self._refreshing.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    def _lock(self, key: Path) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._cache.items() if now - e.used_at >= EXPIRE_SECONDS]:
            del self._cache[key]
            self._failed_at.pop(key, None)
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                del self._locks[key]

    def _is_old(self, key: Path, entry: _Entry) -> bool:
        return self._clock() - entry.fetched_at >= REFRESH_SECONDS or self._stamp(key) != entry.stamp

    def _stamp(self, folder: Path) -> tuple[int | None, ...]:
        """Where a new skill, command or plugin shows up. A folder's time changes when
        an entry is added to or removed from it; edits inside an entry wait for
        `REFRESH_SECONDS`."""
        config = self._config_dir if self._config_dir is not None else claude_config_dir()
        project = folder / ".claude"
        return tuple(
            _mtime(path)
            for path in (
                config / "skills",
                config / "commands",
                config / "plugins" / "installed_plugins.json",
                config / "settings.json",
                project / "skills",
                project / "commands",
                project / "settings.json",
                project / "settings.local.json",
            )
        )

    async def _load(self, key: Path) -> CommandList:
        stamp = self._stamp(key)
        commands = await self._fetch(key)
        now = self._clock()
        self._cache[key] = _Entry(commands, now, now, stamp)
        return commands

    def _refresh_later(self, key: Path) -> None:
        if key in self._refreshing:
            return
        failed_at = self._failed_at.get(key)
        if failed_at is not None and self._clock() - failed_at < RETRY_SECONDS:
            return
        task = asyncio.create_task(self._refresh(key))
        self._refreshing[key] = task

        def forget(done: asyncio.Task[None]) -> None:
            if self._refreshing.get(key) is done:
                del self._refreshing[key]

        task.add_done_callback(forget)

    async def _refresh(self, key: Path) -> None:
        async with self._lock(key):
            try:
                await self._load(key)
                self._failed_at.pop(key, None)
            except CommandCatalogError as exc:
                self._failed_at[key] = self._clock()
                logger.warning("Falha ao atualizar os comandos de %s: %s", key, exc)

    async def _fetch(self, folder: Path) -> CommandList:
        client: AgentClient | None = None
        try:
            client = self._factory(
                AgentOptions(
                    cwd=folder,
                    session_id=str(uuid.uuid4()),
                    resume=False,
                    can_use_tool=_deny_all,
                    settings=NO_HOOKS,
                )
            )
            info = await asyncio.wait_for(self._read(client), self._timeout)
        except TimeoutError as exc:
            raise CommandCatalogError("A lista de comandos demorou demais. Tente de novo.") from exc
        except AgentError as exc:
            raise CommandCatalogError(exc.message_pt) from exc
        except Exception as exc:
            logger.exception("Falha ao listar os comandos de %s", folder)
            raise CommandCatalogError("Não foi possível carregar os comandos.") from exc
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()
        return parse_commands((info or {}).get("commands"))

    @staticmethod
    async def _read(client: AgentClient) -> dict[str, Any] | None:
        await client.connect()
        return await client.get_server_info()
