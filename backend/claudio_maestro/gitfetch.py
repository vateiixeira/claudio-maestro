"""In-memory state of `git fetch` per repository.

Remembers when each repository was last fetched, the last failure, whether a fetch
is running, and how long the automatic loop must wait before trying again. It runs
nothing itself: the caller passes the coroutine that does the fetch. This module
imports no other part of the app, so `gitinfo` can read it while it builds a status.
"""

import asyncio
import logging
import os
import time
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Fetches running at the same time, over every repository.
MAX_CONCURRENT = 4
# After a failure the next automatic try waits twice as long, up to this.
MAX_BACKOFF_SECONDS = 30 * 60
GENERIC_ERROR = "Falha ao buscar do remoto."
INTERRUPTED_ERROR = "A busca no remoto foi interrompida antes de terminar."

FetchResult = Literal["fetched", "skipped", "failed"]


@dataclass
class _Entry:
    fetched_at: float | None = None
    error: str | None = None
    fetching: bool = False
    failures: int = 0
    last_attempt: float | None = None
    # Counts finished runs, so a request that waited behind another one can tell.
    generation: int = 0
    last_result: FetchResult = "skipped"


class _LoopState:
    """What belongs to one event loop: locks and semaphores cannot move between loops."""

    def __init__(self) -> None:
        self.slots = asyncio.Semaphore(MAX_CONCURRENT)
        self.locks: dict[str, asyncio.Lock] = {}


def _one_line(message: str) -> str:
    lines = message.strip().splitlines()
    return lines[-1].strip() if lines else GENERIC_ERROR


class FetchRegistry:
    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        # `clock` stamps `fetched_at` (epoch, shown to the user); `monotonic` times the waits.
        self._clock = clock
        self._monotonic = monotonic
        self._entries: dict[str, _Entry] = {}
        self._loops: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = (
            weakref.WeakKeyDictionary()
        )

    @staticmethod
    def key(path: str | os.PathLike[str]) -> str:
        return os.path.realpath(path)

    def _entry(self, key: str) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = _Entry()
        return entry

    def _loop_state(self) -> _LoopState:
        loop = asyncio.get_running_loop()
        state = self._loops.get(loop)
        if state is None:
            state = self._loops[loop] = _LoopState()
        return state

    def reset(self) -> None:
        self._entries.clear()

    def fields(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        entry = self._entries.get(self.key(path))
        if entry is None:
            return {"fetched_at": None, "fetch_error": None, "fetching": False}
        return {
            "fetched_at": entry.fetched_at, "fetch_error": entry.error, "fetching": entry.fetching,
        }

    def fill(self, status: Any) -> None:
        """Copy the fields into a `RepoStatus`."""
        fields = self.fields(status.path)
        status.fetched_at = fields["fetched_at"]
        status.fetch_error = fields["fetch_error"]
        status.fetching = fields["fetching"]

    def due(self, path: str | os.PathLike[str], interval: float) -> bool:
        """Whether the automatic loop should fetch this repository now.

        After a failure the wait doubles per consecutive failure, up to 30 minutes
        (never below `interval` itself); a success goes back to `interval`.
        """
        entry = self._entries.get(self.key(path))
        if entry is None:
            return True
        if entry.fetching:
            return False
        if entry.last_attempt is None:
            return True
        wait = interval
        if entry.failures:
            wait = min(interval * 2 ** min(entry.failures, 30), max(MAX_BACKOFF_SECONDS, interval))
        return self._monotonic() - entry.last_attempt >= wait

    async def fetch(
        self, path: str | os.PathLike[str], run: Callable[[], Awaitable[bool]]
    ) -> FetchResult:
        """Run `run` (True: fetched, False: nothing to fetch) and record the outcome.

        Never two at once for the same repository: a second request waits for the first
        and returns its result instead of fetching again. At most `MAX_CONCURRENT` run
        over all repositories. A failure is recorded, not raised.
        """
        key = self.key(path)
        entry = self._entry(key)
        state = self._loop_state()
        lock = state.locks.setdefault(key, asyncio.Lock())
        seen = entry.generation
        async with lock:
            if entry.generation != seen:
                return entry.last_result
            async with state.slots:
                entry.fetching = True
                try:
                    result = await self._run(entry, run)
                except asyncio.CancelledError:
                    # Cut short (the limit of "Verificar agora", a shutdown): it still counts
                    # as a try that failed, so the loop does not retry on its next tick.
                    entry.error = INTERRUPTED_ERROR
                    entry.failures += 1
                    entry.last_attempt = self._monotonic()
                    raise
                finally:
                    entry.fetching = False
            entry.last_attempt = self._monotonic()
            entry.last_result = result
            entry.generation += 1
            return result

    async def _run(self, entry: _Entry, run: Callable[[], Awaitable[bool]]) -> FetchResult:
        try:
            fetched = await run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            entry.error = _one_line(str(exc))
            logger.info("Falha ao buscar do remoto: %s", entry.error)
            entry.failures += 1
            return "failed"
        entry.failures = 0
        entry.error = None
        if not fetched:
            return "skipped"
        entry.fetched_at = self._clock()
        return "fetched"


registry = FetchRegistry()
