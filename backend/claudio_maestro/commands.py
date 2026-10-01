"""Slash commands available in a folder: user, project and plugin commands and
skills, read from the CLI with a throwaway client that runs no hooks.

Built-in CLI commands are left out: the app has its own controls for them.
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

from claudio_maestro.agent.base import AgentClient, AgentError, AgentFactory, AgentOptions

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5 * 60
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


class CommandCatalog:
    """Commands per folder, cached for `CACHE_SECONDS`. Concurrent requests for the
    same folder share one client. Failures are not cached."""

    def __init__(
        self,
        agent_factory: AgentFactory,
        clock: Callable[[], float] = time.monotonic,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._factory = agent_factory
        self._clock = clock
        self._timeout = timeout
        self._cache: dict[Path, tuple[float, CommandList]] = {}
        self._locks: dict[Path, asyncio.Lock] = {}

    async def list(self, folder: Path) -> CommandList:
        key = folder.resolve()
        cached = self._fresh(key)
        if cached is not None:
            return cached
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._fresh(key)
            if cached is not None:
                return cached
            commands = await self._fetch(key)
            self._cache[key] = (self._clock(), commands)
            return commands

    def _fresh(self, key: Path) -> CommandList | None:
        entry = self._cache.get(key)
        if entry is None or self._clock() - entry[0] >= CACHE_SECONDS:
            return None
        return entry[1]

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
