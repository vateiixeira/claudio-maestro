"""A throwaway agent client that reads the `full` context usage of a conversation.

The caller gives the options (a resumed, forked copy of the conversation, no message
sent); this module only runs the client: connect, ask, and close it on every path.
"""

import asyncio
import logging
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
    factory: AgentFactory, options: AgentOptions, limit: float
) -> dict[str, Any] | None:
    """The CLI's `get_context_usage("full")` answer for a client built from `options`.

    `limit` (seconds) covers connect and read together; going over it raises
    `TimeoutError`. Any failure of the factory, connect or read is raised as it came.
    The client is always closed, on success, failure, timeout and cancellation, and a
    failing or slow close never replaces the result or the error."""
    client = factory(options)
    try:
        async with asyncio.timeout(limit):
            await client.connect()
            return await client.get_context_usage("full")
    finally:
        await _close(client)


async def _close(client: Any) -> None:
    """Close without raising, and without waiting past `CLOSE_LIMIT`.

    `asyncio.wait` neither cancels the close when the limit passes nor when this task is
    cancelled meanwhile, so the process still goes away."""
    closing = asyncio.ensure_future(client.close())
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
