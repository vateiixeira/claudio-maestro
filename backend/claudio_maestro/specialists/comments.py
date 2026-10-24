"""Delivers the owner's PR comments to the agents.

Comments reach the queue through the webhook or the `gh` sweep. The dispatcher looks at the
queue every few seconds (and when the webhook adds to it) and, for each PR whose newest
comment has been quiet for a minute, sends the whole batch as one turn of the agent's session.
A batch waits when the subscription is nearly spent or the PR already used its turns of the
day; the queue is in the database, so it survives a restart of the backend.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from itertools import groupby
from pathlib import Path

from claudio_maestro import db
from claudio_maestro.specialists import github_hooks, store
from claudio_maestro.specialists.gh_comments import GhRunner, poll_comments
from claudio_maestro.specialists.scheduler import limits_over
from claudio_maestro.specialists.service import SpecialistService
from claudio_maestro.usage import UsageChecker

logger = logging.getLogger(__name__)

# A PR's comments wait this long after the newest one, so a review and its line comments
# arrive as one turn.
QUIET_SECONDS = 60
MAX_TURNS_PER_DAY = 10
# The sweep with `gh` (the safety net for the webhook).
POLL_SECONDS = 3600
DISPATCH_TICK = 15


def day_start(now: float) -> int:
    """Midnight (local time) of the day `now` falls in."""
    return int(datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _number(pr_url: str) -> str:
    last = pr_url.rstrip("/").rsplit("/", 1)[-1]
    return f"#{last}" if last.isdigit() else ""


class CommentDispatcher:
    def __init__(
        self,
        service: SpecialistService,
        usage: UsageChecker,
        db_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._service = service
        self._usage = usage
        self._db_path = db_path
        self._clock = clock
        # Windows of usage and days already warned about, per PR. Memory only: after a
        # restart the same warning may come once more.
        self._warned: set[tuple[str, str, str]] = set()
        # PRs whose last delivery failed: warned about once, until a delivery works.
        self._failed: set[str] = set()
        # One tick at a time: two overlapping ticks must not deliver a batch twice.
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """A comment entered the queue: look at it without waiting for the next tick."""
        self._wake.set()

    async def run(self, interval: float = DISPATCH_TICK) -> None:
        """Tick at startup (what stayed in the queue), then every `interval` seconds or
        as soon as `wake` is called."""
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha ao entregar os comentários de PR aos agentes")
            try:
                await asyncio.wait_for(self._wake.wait(), interval)
            except TimeoutError:
                pass
            self._wake.clear()

    async def tick(self) -> None:
        async with self._lock:
            await self._tick()

    async def _tick(self) -> None:
        now = self._clock()
        with closing(db.connect(self._db_path)) as conn:
            queued = store.queued_comments(conn)
        ordered = sorted(queued, key=lambda comment: store.normalize_pr_url(comment.pr_url))
        for url, group in groupby(ordered, key=lambda c: store.normalize_pr_url(c.pr_url)):
            comments = list(group)
            if max(c.received_at for c in comments) > now - QUIET_SECONDS:
                continue
            try:
                await self._deliver(url, comments, now)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # They stay queued, unmarked: the next tick tries again.
                self._delivery_failed(url, comments[0].specialist_id, error)

    async def _deliver(self, url: str, comments: list[store.PrComment], now: float) -> None:
        specialist_id = comments[0].specialist_id
        number = _number(url)
        label = f"PR {number}" if number else "PR"
        over = sorted(limits_over(self._usage, now), key=lambda limit: -limit["percent"])
        if over:
            top = over[0]
            window = (url, "usage", f"{top['label']}@{top['resets_at']}")
            self._warn_once(
                window, specialist_id,
                f"Comentário no {label} na fila: uso da assinatura em {top['percent']}%.",
            )
            return
        start = day_start(now)
        with closing(db.connect(self._db_path)) as conn:
            turns = store.turns_today(conn, url, start)
            pr = store.get_pr(conn, url)
        if turns >= MAX_TURNS_PER_DAY:
            self._warn_once(
                (url, "day", str(start)), specialist_id,
                f"Comentário no {label} na fila: limite de {MAX_TURNS_PER_DAY} turnos por dia atingido.",
            )
            return
        if pr is None:
            # A PR known only by the link of an item of the agent's registry.
            pr = store.Pr(
                url=url, specialist_id=specialist_id, session_id=None,
                created_at=int(now), polled_at=None, closed=False,
            )
        await self._service.start_comment_run(pr, comments)
        self._failed.discard(url)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.mark_comments(conn, [c.comment_id for c in comments], "delivered", int(now))

    def _delivery_failed(self, url: str, specialist_id: int, error: Exception) -> None:
        """The first failure of a PR warns the person and logs the traceback; the retries
        that follow (every tick) only log one line."""
        reason = " ".join(str(error).split())[:200] or type(error).__name__
        if url in self._failed:
            logger.warning("Comentários do PR %s ainda não entregues: %s", url, reason)
            return
        self._failed.add(url)
        logger.exception("Falha ao entregar comentários do PR %s ao agente", url)
        number = _number(url)
        self._service.add_alert(
            specialist_id,
            f"Comentário no PR {number} não foi entregue: {reason}"
            if number
            else f"Comentário no PR não foi entregue: {reason}",
        )

    def _warn_once(self, key: tuple[str, str, str], specialist_id: int, text: str) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        self._service.add_alert(specialist_id, text)


async def run_poll(
    db_path: Path,
    *,
    run_gh: GhRunner,
    clock: Callable[[], float] = time.time,
    on_queued: Callable[[], None] = lambda: None,
    interval: float = POLL_SECONDS,
) -> None:
    """The sweep with `gh`: at startup and then every `interval` seconds. It does nothing
    while no owner is configured. A failure is logged and the next round tries again."""
    while True:
        try:
            with closing(db.connect(db_path)) as conn:
                owner = github_hooks.get_owner(conn)
            if await poll_comments(db_path, owner=owner, run_gh=run_gh, now=clock()):
                on_queued()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha na varredura de comentários de PR")
        await asyncio.sleep(interval)
