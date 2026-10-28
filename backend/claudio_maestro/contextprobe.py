"""A throwaway agent client that reads the `full` context usage of a conversation.

The caller gives the options (a resumed, forked copy of the conversation, no message
sent); this module only runs the client: connect, ask, and close it on every path.
"""

import asyncio
import logging
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claudio_maestro.agent.base import AgentFactory, AgentOptions

logger = logging.getLogger(__name__)

# How long a close may take before the probe stops waiting for it (seconds). The close
# itself is not cancelled: it goes on in the background.
CLOSE_LIMIT = 5.0
# Closes still running past the limit, kept here so the loop's weak reference is not the
# only one.
_closing: set[asyncio.Future[Any]] = set()


async def probe_context(
    factory: AgentFactory,
    options: AgentOptions,
    limit: float,
    *,
    after_close: Callable[[], None] | None = None,
) -> dict[str, Any] | None:
    """The CLI's `get_context_usage("full")` answer for a client built from `options`.

    `limit` (seconds) covers connect and read together; going over it raises
    `TimeoutError`. Any failure of the factory, connect or read is raised as it came.
    The client is always closed, on success, failure, timeout and cancellation, and a
    failing or slow close never replaces the result or the error.

    `after_close` (blocking, run in a thread) is called once the close finished, on every
    path, even when that happens after the probe stopped waiting. It is where the caller
    removes what the process left behind; its failure is only logged."""
    client = factory(options)
    try:
        async with asyncio.timeout(limit):
            await client.connect()
            return await client.get_context_usage("full")
    finally:
        await _close(client, after_close)


async def _close(client: Any, after_close: Callable[[], None] | None = None) -> None:
    """Close without raising, and without waiting past `CLOSE_LIMIT`.

    `asyncio.wait` neither cancels the close when the limit passes nor when this task is
    cancelled meanwhile, so the process still goes away (and `after_close` still runs)."""

    async def close_then_clean() -> None:
        try:
            await client.close()
        finally:
            if after_close is not None:
                try:
                    await asyncio.to_thread(after_close)
                except Exception:
                    logger.exception("Falha ao limpar o que o processo temporário deixou")

    closing = asyncio.ensure_future(close_then_clean())
    _closing.add(closing)
    closing.add_done_callback(_closing.discard)
    closing.add_done_callback(_log_close_failure)
    done, _pending = await asyncio.wait([closing], timeout=CLOSE_LIMIT)
    if not done:
        logger.warning("O processo temporário do contexto demorou a encerrar")


def _log_close_failure(closing: asyncio.Future[Any]) -> None:
    if not closing.cancelled() and closing.exception() is not None:
        logger.warning(
            "Falha ao encerrar o processo temporário do contexto", exc_info=closing.exception()
        )


def delete_fork_files(projects_root: Path, fork_id: str) -> None:
    """Delete `<fork_id>.jsonl` and `<fork_id>/` from the CLI's project folders.

    The CLI writes a forked conversation under the folder of the original conversation's
    cwd, not under the cwd the probe ran in, so every folder directly under
    `projects_root` is searched. Only entries named exactly after `fork_id` (a canonical
    UUID, anything else is refused) go away, and no symlink is followed: a project folder
    that is a symlink is skipped, and a symlink named like the fork is only unlinked.
    Blocking. Raises `OSError` for what it could not delete, after trying the rest."""
    try:
        canonical = str(uuid.UUID(fork_id)) == fork_id
    except ValueError:
        canonical = False
    if not canonical:
        logger.warning("Id de cópia inválido; nada foi apagado")
        return
    try:
        folders = [e for e in os.scandir(projects_root) if e.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        return
    errors: list[OSError] = []
    for folder in folders:
        for name, is_dir in ((f"{fork_id}.jsonl", False), (fork_id, True)):
            path = Path(folder.path, name)
            try:
                mode = os.lstat(path).st_mode
            except FileNotFoundError:
                continue
            except OSError as error:
                errors.append(error)
                continue
            try:
                if stat.S_ISLNK(mode):
                    path.unlink()
                elif is_dir and stat.S_ISDIR(mode):
                    shutil.rmtree(path)
                elif not is_dir and stat.S_ISREG(mode):
                    path.unlink()
            except OSError as error:
                errors.append(error)
    if errors:
        raise errors[0]
