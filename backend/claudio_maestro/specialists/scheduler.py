"""Fires the agents at their scheduled times.

`due_slot` finds the newest scheduled time that has come and not been fired yet. The
`Scheduler` checks every agent's schedules on each tick: a slot that is too late is only
recorded as `missed`; otherwise the run is skipped when the agent is still busy or the
subscription is nearly spent, and started when neither holds. A slot is marked as fired
before anything else, so it never fires twice.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from claudio_maestro import db
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store
from claudio_maestro.specialists.service import SpecialistService
from claudio_maestro.usage import UsageChecker

logger = logging.getLogger(__name__)

# A slot older than this is not started (the app was off or busy): it is recorded `missed`.
GRACE_SECONDS = 600
USAGE_LIMIT_PERCENT = 90
TICK_SECONDS = 30
# Days to look back for the newest slot: a schedule of a single weekday repeats in 7.
LOOKBACK_DAYS = 7

BUSY_REASON = "Uma execução anterior ainda está rodando ou esperando você."
MISSED_REASON = "O horário passou e o Maestro não disparou o agente (estava desligado ou ocupado)."


def due_slot(schedule: store.Schedule, now: datetime) -> datetime | None:
    """The newest time of the schedule that is `<= now` and after `last_fired_at`, or None.
    Days are ISO ("1" = Monday) and the times are the system's local time. `now` may be
    naive (taken as local). Each slot gets the offset of its own day, so a change of
    daylight saving time does not shift the slots of the other days."""
    now = now.astimezone()
    hour, minute = schedule.time.split(":")
    at = time(int(hour), int(minute))
    for offset in range(LOOKBACK_DAYS + 1):
        day = now.date() - timedelta(days=offset)
        if str(day.isoweekday()) not in schedule.days:
            continue
        slot = datetime.combine(day, at).astimezone()
        if slot > now:
            continue
        if schedule.last_fired_at is not None and slot.timestamp() <= schedule.last_fired_at:
            return None
        return slot
    return None


class Scheduler:
    def __init__(
        self,
        service: SpecialistService,
        sessions: SessionManager,
        usage: UsageChecker,
        db_path: Path,
        clock: Callable[[], float],
    ) -> None:
        self._service = service
        self._sessions = sessions
        self._usage = usage
        self._db_path = db_path
        self._clock = clock
        # limit label -> `resets_at` of the window already warned about. Memory only: after
        # a restart the same window may warn once more.
        self._usage_alerted: dict[str, float | None] = {}
        # One tick at a time: two overlapping ticks must not fire the same slot twice.
        self._lock = asyncio.Lock()

    async def run(self, interval: float = TICK_SECONDS) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha no agendador dos agentes")
            await asyncio.sleep(interval)

    async def tick(self) -> None:
        async with self._lock:
            await self._tick()

    async def _tick(self) -> None:
        now = self._clock()
        local = datetime.fromtimestamp(now).astimezone()
        with closing(db.connect(self._db_path)) as conn:
            enabled = {s.id: s.enabled for s in store.list_specialists(conn)}
            schedules = store.list_schedules(conn)
        for schedule in schedules:
            if schedule.specialist_id not in enabled:
                continue
            try:
                await self._handle(schedule, enabled[schedule.specialist_id], local, now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Falha ao disparar o agendamento %s do agente %s",
                    schedule.id,
                    schedule.specialist_id,
                )

    async def _handle(
        self, schedule: store.Schedule, enabled: bool, local: datetime, now: float
    ) -> None:
        slot = due_slot(schedule, local)
        if slot is None:
            return
        if not enabled:
            # A disabled agent never runs. The slot is still consumed, silently, so
            # enabling the agent later does not record a `missed` for old slots.
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                store.mark_fired(conn, schedule.id, int(now))
            return
        await self._fire(schedule, int(slot.timestamp()), now)

    async def _fire(self, schedule: store.Schedule, slot: int, now: float) -> None:
        # Marked first: whatever happens next, this slot is not fired again.
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.mark_fired(conn, schedule.id, int(now))
        specialist_id = schedule.specialist_id
        if now - slot > GRACE_SECONDS:
            self._service.record_missed(specialist_id, MISSED_REASON, scheduled_for=slot)
            return
        if self._service.is_busy(specialist_id):
            self._service.record_skipped(specialist_id, BUSY_REASON, scheduled_for=slot)
            return
        over = self._limit_over(now)
        if over is not None:
            percent, label = over
            self._service.record_skipped(
                specialist_id, f"Uso da assinatura em {percent}% ({label}).", scheduled_for=slot
            )
            self._warn_usage(specialist_id, now)
            return
        await self._service.start_run(specialist_id, trigger="schedule", scheduled_for=slot)

    def _limits_over(self, now: float) -> list[dict[str, Any]]:
        """Limits at or over the threshold whose window has not renewed yet; empty without
        a usable reading (usage check off or failed)."""
        snapshot = self._usage.snapshot()
        if not snapshot["enabled"] or snapshot["error"]:
            return []
        return [
            limit
            for limit in snapshot["limits"]
            if limit["percent"] >= USAGE_LIMIT_PERCENT
            and (limit["resets_at"] is None or limit["resets_at"] > now)
        ]

    def _limit_over(self, now: float) -> tuple[int, str] | None:
        """The fullest limit over the threshold, or None."""
        over = self._limits_over(now)
        if not over:
            return None
        top = max(over, key=lambda limit: limit["percent"])
        return top["percent"], top["label"]

    def _warn_usage(self, specialist_id: int, now: float) -> None:
        """One `alert` per window of each limit over the threshold."""
        for limit in self._limits_over(now):
            label, resets_at = limit["label"], limit["resets_at"]
            if label in self._usage_alerted and self._usage_alerted[label] == resets_at:
                continue
            self._usage_alerted[label] = resets_at
            self._service.add_alert(
                specialist_id,
                f"Uso da assinatura em {limit['percent']}% ({label}): os agentes agendados"
                " não rodam até o limite renovar.",
            )
