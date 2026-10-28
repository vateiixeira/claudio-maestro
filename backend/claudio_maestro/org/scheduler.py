"""Fires the routines at their scheduled times.

`due_slot` finds the newest scheduled time that has come and not been fired yet. The
`Scheduler` checks every schedule of the routines on each tick: a slot that is too late is only
recorded as `missed`; any other slot wakes the agent of the routine through the service, which
queues the wakeup and serves it one run at a time; a routine that creates a task opens the task
instead, assigned to its agent (the assignment is what wakes it). Each tick also expires the
decisions nobody answered in time. The scheduler also supplies the service's
`usage_gate`: while the subscription is over the cut, the service turns the wakeups that are not
the person's into `skipped` runs, and the scheduler warns once per window of each limit.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.decisions import DecisionService
from claudio_maestro.org.service import OrgService
from claudio_maestro.org.tasks import TaskService
from claudio_maestro.usage import UsageChecker

logger = logging.getLogger(__name__)

# A slot older than this is not started (the app was off or busy): it is recorded `missed`.
GRACE_SECONDS = 600
USAGE_LIMIT_PERCENT = 90
TICK_SECONDS = 30
# Days to look back for the newest slot: a schedule of a single weekday repeats in 7.
LOOKBACK_DAYS = 7
TASK_TITLE_MAX = store.TASK_TITLE_MAX
NO_TASK_SERVICE = "O serviço de tarefas não está disponível."


class RoutineAgentDisabledError(store.OrgError):
    """"Run now" of a routine whose agent is off: nothing is created."""

    def __init__(self) -> None:
        super().__init__("O agente está desligado.")


def routine_task_title(name: str, moment: datetime) -> str:
    """`"<name> · dd/mm"`, with the name cut so the title fits the limit of a task title."""
    suffix = f" · {moment:%d/%m}"
    return name[: TASK_TITLE_MAX - len(suffix)].rstrip() + suffix


def limits_over(usage: UsageChecker, now: float) -> list[dict[str, Any]]:
    """Limits at or over the threshold whose window has not renewed yet; empty without a
    usable reading (usage check off or failed)."""
    snapshot = usage.snapshot()
    if not snapshot["enabled"] or snapshot["error"]:
        return []
    return [
        limit
        for limit in snapshot["limits"]
        if limit["percent"] >= USAGE_LIMIT_PERCENT
        and (limit["resets_at"] is None or limit["resets_at"] > now)
    ]


def limit_over(usage: UsageChecker, now: float) -> tuple[int, str] | None:
    """The fullest limit over the threshold as (percent, label), or None."""
    over = limits_over(usage, now)
    if not over:
        return None
    top = max(over, key=lambda limit: limit["percent"])
    return top["percent"], top["label"]


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
        service: OrgService,
        usage: UsageChecker,
        db_path: Path,
        clock: Callable[[], float],
        tasks: TaskService | None = None,
        decisions: DecisionService | None = None,
    ) -> None:
        self._service = service
        self._tasks = tasks
        self._decisions = decisions
        self._usage = usage
        self._db_path = db_path
        self._clock = clock
        # (agent id, limit label) -> `resets_at` of the window already warned about. Memory
        # only: after a restart the same window may warn once more.
        self._usage_alerted: dict[tuple[int, str], float | None] = {}
        # One tick at a time: two overlapping ticks must not fire the same slot twice.
        self._lock = asyncio.Lock()
        # Off (set once at startup, e.g. by the E2E server): `tick` does nothing, so no slot is
        # fired, consumed or recorded as missed.
        self.enabled = True
        self._service.usage_gate = lambda: limit_over(self._usage, self._clock())

    async def run(self, interval: float = TICK_SECONDS) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha no agendador das rotinas")
            await asyncio.sleep(interval)

    async def tick(self) -> None:
        async with self._lock:
            if self.enabled:
                await self._tick()

    async def _tick(self) -> None:
        await self._expire_decisions()
        now = self._clock()
        local = datetime.fromtimestamp(now).astimezone()
        with closing(db.connect(self._db_path)) as conn:
            routines = {r.id: r for r in store.list_routines(conn)}
            agents = {a.id: a for a in store.list_agents(conn)}
            schedules = store.list_schedules(conn)
        for schedule in schedules:
            routine = routines.get(schedule.routine_id)
            if routine is None:
                continue
            agent = agents.get(routine.agent_id)
            if agent is None:
                continue
            try:
                await self._handle(schedule, routine, agent.enabled, local, now)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception(
                    "Falha ao disparar o agendamento %s da rotina %s (agente %s)",
                    schedule.id,
                    routine.name,
                    routine.agent_id,
                )
                self._warn_failed(routine, error)

    async def _expire_decisions(self) -> None:
        if self._decisions is None:
            return
        try:
            await self._decisions.expire_stale()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao expirar as decisões sem resposta")

    async def _handle(
        self,
        schedule: store.Schedule,
        routine: store.Routine,
        agent_enabled: bool,
        local: datetime,
        now: float,
    ) -> None:
        slot = due_slot(schedule, local)
        if slot is None:
            return
        if not routine.enabled or not agent_enabled:
            # What is off never runs. The slot is still consumed, silently, so turning it on
            # later does not record a `missed` for old slots.
            self._mark_fired(schedule, now)
            return
        scheduled_for = int(slot.timestamp())
        self._mark_fired(schedule, now)
        if now - scheduled_for > GRACE_SECONDS:
            self._service.record_missed(routine.agent_id, routine.id, scheduled_for)
            return
        # Over the cut, the service skips the wakeup by itself (`usage_gate`); the warning is ours.
        self._warn_usage(routine.agent_id, now)
        if routine.create_task:
            await self._fire_task(routine, scheduled_for, now)
            return
        await self._service.wake(
            routine.agent_id,
            source="routine",
            routine_id=routine.id,
            scheduled_for=scheduled_for,
        )

    async def run_now(self, routine: store.Routine) -> store.Task:
        """"Run now" of a routine that creates a task, the same path as a scheduled firing.
        Returns the new task. Being the person's (`manual`), it is created even over the usage
        cut; only the assignment wakeup is held by the service until the usage comes down."""
        if not routine.create_task:
            raise store.OrgError("A rotina não cria tarefas.")
        with closing(db.connect(self._db_path)) as conn:
            if not store.get_agent(conn, routine.agent_id).enabled:
                raise RoutineAgentDisabledError
        return await self._create_task(routine, self._clock())

    async def _fire_task(
        self, routine: store.Routine, scheduled_for: int | None, now: float
    ) -> store.Task | store.Run:
        """A scheduled firing is gated: its assignment wakeup would be dropped over the usage
        cut, so over it no task is created and the firing is `skipped`."""
        over = self._service.usage_gate()
        if over is not None:
            percent, label = over
            return self._service.record_skipped(
                routine.agent_id,
                f"Uso da assinatura em {percent}% ({label}).",
                routine_id=routine.id,
                scheduled_for=scheduled_for,
            )
        return await self._create_task(routine, now)

    async def _create_task(self, routine: store.Routine, now: float) -> store.Task:
        """Open the task of the routine, assigned to its agent (the assignment wakes it)."""
        if self._tasks is None:
            raise store.OrgError(NO_TASK_SERVICE)
        return await self._tasks.create_task(
            project_id=routine.project_id,
            title=routine_task_title(routine.name, datetime.fromtimestamp(now).astimezone()),
            description=routine.instruction,
            assignee_agent_id=routine.agent_id,
            actor_agent_id=None,
            created_by="routine",
            routine_id=routine.id,
        )

    def _warn_failed(self, routine: store.Routine, error: Exception) -> None:
        """The slot is already consumed, so a wakeup that could not be queued would otherwise
        vanish into the log: tell the owner of the routine."""
        reason = (
            " ".join(str(error).split())[:200] if isinstance(error, store.OrgError) else ""
        ) or "erro inesperado (veja o registro do app)"
        try:
            self._service.add_alert(
                routine.agent_id, f'A rotina "{routine.name}" não disparou: {reason}'
            )
        except Exception:
            logger.exception("Falha ao avisar que a rotina %s não disparou", routine.name)

    def _mark_fired(self, schedule: store.Schedule, now: float) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.mark_fired(conn, schedule.id, int(now))

    def _warn_usage(self, agent_id: int, now: float) -> None:
        """One `alert` per window of each limit over the threshold, for each agent."""
        for limit in limits_over(self._usage, now):
            key = (agent_id, limit["label"])
            resets_at = limit["resets_at"]
            if key in self._usage_alerted and self._usage_alerted[key] == resets_at:
                continue
            self._usage_alerted[key] = resets_at
            self._service.add_alert(
                agent_id,
                f"Uso da assinatura em {limit['percent']}% ({limit['label']}): as rotinas"
                " agendadas não rodam até o limite renovar.",
            )
