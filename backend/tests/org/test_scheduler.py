"""Scheduler of the routines: due slots, grace period, silent slots of what is off, and the
usage warning. Uses a fake clock and a fake `OrgService` that only records the calls; the
real SDK is never touched."""

import asyncio
import logging
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from test_sessions import Recorder, make_project

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.scheduler import (
    GRACE_SECONDS,
    TICK_SECONDS,
    USAGE_LIMIT_PERCENT,
    Scheduler,
    due_slot,
    limit_over,
    limits_over,
)
from claudio_maestro.usage import UsageChecker, UsageLimit, UsageReport

pytestmark = pytest.mark.anyio

FUTURE = 4_000_000_000.0  # a `resets_at` far after the fake clock
EVERY_DAY = "1234567"
WEEKDAYS = "12345"


def at(day: int, hour: int, minute: int = 0, second: int = 0, month: int = 10) -> datetime:
    """Local time in 2026; 26/10/2026 is a Monday."""
    return datetime(2026, month, day, hour, minute, second)


MONDAY = 26


def ts(moment: datetime) -> int:
    return int(moment.timestamp())


def same(slot: datetime | None, expected: datetime) -> bool:
    """`due_slot` gives a slot with a timezone; the expected one is local time."""
    return slot is not None and slot.timestamp() == expected.timestamp()


def schedule(days: str, time: str, last_fired_at: int | None) -> store.Schedule:
    return store.Schedule(id=1, routine_id=1, days=days, time=time, last_fired_at=last_fired_at)


def limit(percent: int, label: str = "Sessão", resets_at: float | None = FUTURE) -> UsageLimit:
    return UsageLimit("session", label, percent, "critical", resets_at)


def test_constants():
    assert (GRACE_SECONDS, USAGE_LIMIT_PERCENT, TICK_SECONDS) == (600, 90, 30)


# due_slot -----------------------------------------------------------------------


def test_due_slot_same_day_and_weekday_filter():
    last = ts(at(MONDAY, 8))
    # Monday 09:30 with a 09:00 slot: it is today's.
    assert same(due_slot(schedule(EVERY_DAY, "09:00", last), at(MONDAY, 9, 30)), at(MONDAY, 9))
    # Sunday 01/11/2026 is not in Monday-Friday: the newest slot is Friday's.
    friday = at(30, 9)
    assert same(due_slot(schedule(WEEKDAYS, "09:00", ts(at(29, 8))), at(1, 12, month=11)), friday)
    # Only Wednesday (3): on Monday, the last one was the Wednesday before.
    assert same(due_slot(schedule("3", "09:00", ts(at(15, 0))), at(MONDAY, 12)), at(21, 9))


def test_due_slot_none_before_first_slot():
    last = ts(at(MONDAY, 0))
    assert due_slot(schedule(EVERY_DAY, "09:00", last), at(MONDAY, 8, 59, 59)) is None
    # Today's slot has not come yet and the one of yesterday was already fired.
    assert due_slot(schedule(EVERY_DAY, "09:00", ts(at(25, 9, 0, 1))), at(MONDAY, 8)) is None


def test_due_slot_ignores_slots_before_last_fired():
    fired = ts(at(MONDAY, 9, 0, 3))
    assert due_slot(schedule(EVERY_DAY, "09:00", fired), at(MONDAY, 12)) is None
    assert same(due_slot(schedule(EVERY_DAY, "09:00", fired), at(27, 9)), at(27, 9))
    # Never fired: the newest slot counts.
    assert same(due_slot(schedule(EVERY_DAY, "09:00", None), at(MONDAY, 12)), at(MONDAY, 9))


def test_due_slot_returns_only_the_newest_slot():
    last = ts(at(MONDAY, 8))
    assert same(due_slot(schedule(EVERY_DAY, "09:00", last), at(29, 10)), at(29, 9))


def test_due_slot_exactly_on_the_hour_counts():
    last = ts(at(MONDAY, 8))
    assert same(due_slot(schedule(EVERY_DAY, "09:00", last), at(MONDAY, 9)), at(MONDAY, 9))


# World --------------------------------------------------------------------------


class FakeService:
    """The part of `OrgService` the scheduler touches; it only records the calls."""

    def __init__(self) -> None:
        self.usage_gate: Any = lambda: None
        self.wakes: list[dict[str, Any]] = []
        self.missed: list[tuple[int, int | None, int]] = []
        self.alerts: list[tuple[int, str]] = []
        self.fail_for: set[int] = set()
        self.hold: asyncio.Event | None = None

    async def wake(self, agent_id: int, **kwargs: Any) -> None:
        if self.hold is not None:
            await self.hold.wait()
        if agent_id in self.fail_for:
            raise store.OrgError("falhou")
        self.wakes.append({"agent_id": agent_id, **kwargs})

    def record_missed(self, agent_id: int, routine_id: int | None, scheduled_for: int) -> None:
        self.missed.append((agent_id, routine_id, scheduled_for))

    def add_alert(self, agent_id: int, text: str) -> None:
        self.alerts.append((agent_id, text))


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.now = float(ts(at(MONDAY, 8)))
        self.recorder = Recorder()
        self.service = FakeService()
        self.limits: list[UsageLimit] = []
        self.usage_error = False
        self.usage = UsageChecker(self.recorder, enabled=True, fetch=self._fetch)
        self.scheduler = Scheduler(
            self.service,  # type: ignore[arg-type]
            self.usage,
            self.db_path,
            clock=lambda: self.now,
        )

    async def _fetch(self) -> UsageReport:
        if self.usage_error:
            raise RuntimeError("fora do ar")
        return UsageReport(limits=self.limits, plan="Max")

    async def set_usage(self, *limits: UsageLimit) -> None:
        self.limits = list(limits)
        await self.usage.refresh()

    def move_to(self, moment: datetime) -> None:
        self.now = float(ts(moment))

    def add_agent(self, slug: str = "revisor", enabled: bool = True) -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            agent = store.create_agent(
                conn, slug=slug, name=slug.title(), project_id=self.project.id,
                reports_to=None, now=1,
            )
            if not enabled:
                store.update_agent(conn, agent.id, now=1, enabled=False)
        return agent.id

    def add_routine(
        self,
        agent_id: int,
        name: str = "Ronda",
        instruction: str = "Faça a ronda.",
        schedules: tuple[tuple[str, str], ...] = ((EVERY_DAY, "09:00"),),
        enabled: bool = True,
    ) -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            routine = store.create_routine(
                conn, project_id=self.project.id, agent_id=agent_id, name=name,
                instruction=instruction, enabled=enabled, now=1,
            )
            store.replace_schedules(conn, routine.id, list(schedules), now=int(self.now))
        return routine.id

    def set_agent_enabled(self, agent_id: int, enabled: bool) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            store.update_agent(conn, agent_id, now=1, enabled=enabled)

    def set_routine_enabled(self, routine_id: int, enabled: bool) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            store.update_routine(conn, routine_id, now=1, enabled=enabled)

    def schedules(self, routine_id: int) -> list[store.Schedule]:
        with closing(db.connect(self.db_path)) as conn:
            return store.list_schedules(conn, routine_id)

    def usage_alerts(self) -> list[tuple[int, str]]:
        return [a for a in self.service.alerts if a[1].startswith("Uso da assinatura")]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


# usage helpers ------------------------------------------------------------------


async def test_limit_over_picks_the_fullest_limit_over_the_cut(world):
    await world.set_usage(limit(40, "Semana"), limit(92, "Sessão"), limit(95, "Mês"))
    assert [item["label"] for item in limits_over(world.usage, world.now)] == ["Sessão", "Mês"]
    assert limit_over(world.usage, world.now) == (95, "Mês")


async def test_limit_over_is_none_below_the_cut_or_without_a_usable_reading(world):
    await world.set_usage(limit(USAGE_LIMIT_PERCENT - 1))
    assert limit_over(world.usage, world.now) is None
    await world.set_usage(limit(USAGE_LIMIT_PERCENT))
    assert limit_over(world.usage, world.now) == (USAGE_LIMIT_PERCENT, "Sessão")
    world.usage_error = True
    await world.usage.refresh()  # keeps the old limits but the read now has an error
    assert world.usage.snapshot()["error"]
    assert limit_over(world.usage, world.now) is None
    world.usage_error = False
    await world.usage.refresh()
    world.usage.enabled = False
    assert limit_over(world.usage, world.now) is None


async def test_limit_already_renewed_is_ignored_and_one_without_reset_time_counts(world):
    await world.set_usage(limit(97, "Sessão", world.now), limit(95, "Semana", world.now - 60))
    assert limit_over(world.usage, world.now) is None
    await world.set_usage(limit(97, "Sessão", None))
    assert limit_over(world.usage, world.now) == (97, "Sessão")


async def test_the_scheduler_wires_the_usage_gate_into_the_service(world):
    assert world.service.usage_gate() is None
    await world.set_usage(limit(93, "Sessão"))
    assert world.service.usage_gate() == (93, "Sessão")
    world.now = FUTURE + 1  # the window renewed
    assert world.service.usage_gate() is None


# tick ---------------------------------------------------------------------------


async def test_tick_does_nothing_before_the_slot(world):
    agent = world.add_agent()
    world.add_routine(agent)
    world.move_to(at(MONDAY, 8, 59))

    await world.scheduler.tick()

    assert world.service.wakes == [] and world.service.missed == []


async def test_tick_wakes_the_routine_agent_with_instruction(world):
    agent = world.add_agent()
    routine = world.add_routine(agent, name="Ronda", instruction="Veja o Sentry.")
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()
    await world.scheduler.tick()

    [call] = world.service.wakes
    assert call == {
        "agent_id": agent,
        "source": "routine",
        "routine_id": routine,
        "scheduled_for": ts(at(MONDAY, 9)),
    }
    # No free text: the service builds the prompt of the routine from the routine itself.
    assert world.schedules(routine)[0].last_fired_at == int(world.now)
    assert world.service.missed == []

    # The next day's slot fires again.
    world.move_to(at(27, 9, 0, 1))
    await world.scheduler.tick()
    assert [w["scheduled_for"] for w in world.service.wakes] == [ts(at(MONDAY, 9)), ts(at(27, 9))]


async def test_late_but_inside_the_grace_still_fires(world):
    agent = world.add_agent()
    world.add_routine(agent)
    world.move_to(at(MONDAY, 9, 9, 59))

    await world.scheduler.tick()

    [call] = world.service.wakes
    assert call["scheduled_for"] == ts(at(MONDAY, 9)) and world.service.missed == []


async def test_tick_marks_missed_after_grace(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.move_to(at(MONDAY, 9, 10, 1))

    await world.scheduler.tick()
    await world.scheduler.tick()

    assert world.service.missed == [(agent, routine, ts(at(MONDAY, 9)))]
    assert world.service.wakes == []
    assert world.schedules(routine)[0].last_fired_at == int(world.now)
    assert world.usage_alerts() == []


async def test_backend_down_records_a_single_missed_per_schedule(world):
    agent = world.add_agent()
    one = world.add_routine(agent, name="Um", schedules=((EVERY_DAY, "09:00"),))
    two = world.add_routine(
        agent, name="Dois", schedules=((EVERY_DAY, "09:00"), (EVERY_DAY, "18:00"))
    )
    world.move_to(at(29, 10))  # the app was off for three days

    await world.scheduler.tick()
    await world.scheduler.tick()

    assert sorted(world.service.missed) == sorted(
        [(agent, one, ts(at(29, 9))), (agent, two, ts(at(29, 9))), (agent, two, ts(at(28, 18)))]
    )
    assert world.service.wakes == []


async def test_disabled_routine_consumes_slot_silently(world):
    agent = world.add_agent()
    routine = world.add_routine(agent, enabled=False)
    for day in (MONDAY, 27, 28):  # disabled for three days, with the scheduler ticking
        world.move_to(at(day, 9, 0, 5))
        await world.scheduler.tick()
        assert world.schedules(routine)[0].last_fired_at == int(world.now)
    world.set_routine_enabled(routine, True)

    # Enabled later: no `missed` for the old slots, and the next slot fires.
    world.move_to(at(28, 15))
    await world.scheduler.tick()
    assert world.service.wakes == [] and world.service.missed == []

    world.move_to(at(29, 9, 0, 5))
    await world.scheduler.tick()
    [call] = world.service.wakes
    assert call["scheduled_for"] == ts(at(29, 9)) and world.service.missed == []


async def test_disabled_agent_consumes_slot_silently(world):
    agent = world.add_agent(enabled=False)
    routine = world.add_routine(agent)
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()
    assert world.schedules(routine)[0].last_fired_at == int(world.now)
    world.move_to(at(29, 12))  # also past the grace of an old slot: still silent
    await world.scheduler.tick()
    assert world.service.wakes == [] and world.service.missed == []

    world.set_agent_enabled(agent, True)
    world.move_to(at(30, 9, 0, 5))
    await world.scheduler.tick()
    [call] = world.service.wakes
    assert call["agent_id"] == agent and call["scheduled_for"] == ts(at(30, 9))
    assert world.service.missed == []


async def test_an_old_slot_of_a_disabled_routine_is_not_a_missed(world):
    agent = world.add_agent()
    routine = world.add_routine(agent, enabled=False)
    world.move_to(at(29, 10))

    await world.scheduler.tick()

    assert world.service.missed == [] and world.service.wakes == []
    assert world.schedules(routine)[0].last_fired_at == int(world.now)


async def test_overlapping_ticks_fire_once(world):
    agent = world.add_agent()
    world.add_routine(agent)
    world.move_to(at(MONDAY, 9, 0, 5))
    world.service.hold = asyncio.Event()

    first = asyncio.create_task(world.scheduler.tick())
    second = asyncio.create_task(world.scheduler.tick())
    await asyncio.sleep(0.05)
    world.service.hold.set()
    await asyncio.gather(first, second)

    assert len(world.service.wakes) == 1


async def test_a_failing_wake_does_not_stop_the_other_routines(world, caplog):
    broken = world.add_agent("quebrado")
    healthy = world.add_agent("saudavel")
    world.add_routine(broken, name="Quebrada")
    world.add_routine(healthy, name="Boa")
    world.service.fail_for = {broken}
    world.move_to(at(MONDAY, 9, 0, 5))

    with caplog.at_level(logging.ERROR):
        await world.scheduler.tick()

    assert [w["agent_id"] for w in world.service.wakes] == [healthy]
    assert "Quebrada" in caplog.text or str(broken) in caplog.text


async def test_a_disabled_scheduler_does_nothing(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.scheduler.enabled = False
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert world.service.wakes == [] and world.service.missed == []
    assert world.schedules(routine)[0].last_fired_at != int(world.now)

    world.scheduler.enabled = True
    await world.scheduler.tick()
    assert len(world.service.wakes) == 1


async def test_run_keeps_ticking_after_a_failure(world, monkeypatch, caplog):
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(world.scheduler, "tick", flaky)
    with caplog.at_level(logging.ERROR):
        task = asyncio.create_task(world.scheduler.run(interval=0.001))
        for _ in range(200):
            if calls >= 3:
                break
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls >= 3 and "agendador" in caplog.text


# usage warning ------------------------------------------------------------------


async def test_tick_skips_when_usage_over_limit_and_alerts_once(world):
    agent = world.add_agent()
    routine = world.add_routine(agent, schedules=((EVERY_DAY, "09:00"), (EVERY_DAY, "09:05")))
    await world.set_usage(limit(40, "Semana", FUTURE + 1), limit(92, "Sessão", FUTURE))
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    # The service decides the skip (through the gate); the scheduler still hands it the wakeup.
    assert [w["scheduled_for"] for w in world.service.wakes] == [ts(at(MONDAY, 9))]
    [(alert_agent, text)] = world.usage_alerts()
    assert alert_agent == agent and "92%" in text and "Sessão" in text
    assert "Semana" not in text

    # The next slot, same window of the limit: no new usage alert.
    world.move_to(at(MONDAY, 9, 5, 5))
    await world.scheduler.tick()
    assert len(world.service.wakes) == 2 and len(world.usage_alerts()) == 1
    assert world.schedules(routine)[1].last_fired_at == int(world.now)

    # The window renewed and the new one is full again: one more alert.
    await world.set_usage(limit(95, "Sessão", FUTURE + 99_000.0))
    world.move_to(at(27, 9, 0, 5))
    await world.scheduler.tick()
    alerts = world.usage_alerts()
    assert len(alerts) == 2 and "95%" in alerts[-1][1]


async def test_the_usage_alert_is_once_per_window_per_agent(world):
    one, two = world.add_agent("um"), world.add_agent("dois")
    world.add_routine(one, name="A")
    world.add_routine(two, name="B")
    await world.set_usage(limit(93))
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert sorted(agent for agent, _ in world.usage_alerts()) == sorted([one, two])


async def test_usage_below_the_limit_has_no_alert_and_at_the_limit_has(world):
    agent = world.add_agent()
    world.add_routine(agent, schedules=((EVERY_DAY, "09:00"), (EVERY_DAY, "09:05")))
    await world.set_usage(limit(USAGE_LIMIT_PERCENT - 1))
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()
    assert len(world.service.wakes) == 1 and world.usage_alerts() == []

    await world.set_usage(limit(USAGE_LIMIT_PERCENT))
    world.move_to(at(MONDAY, 9, 5, 5))
    await world.scheduler.tick()
    assert len(world.service.wakes) == 2 and len(world.usage_alerts()) == 1


async def test_no_usage_alert_when_usage_is_off_or_failed(world):
    agent = world.add_agent()
    world.add_routine(agent, schedules=((EVERY_DAY, "09:00"), (EVERY_DAY, "09:05")))
    world.usage.enabled = False
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()

    world.usage.enabled = True
    await world.set_usage(limit(99))
    world.usage_error = True
    await world.usage.refresh()
    world.move_to(at(MONDAY, 9, 5, 5))
    await world.scheduler.tick()

    assert len(world.service.wakes) == 2 and world.usage_alerts() == []


async def test_a_missed_slot_over_the_limit_is_only_missed(world):
    agent = world.add_agent()
    world.add_routine(agent)
    await world.set_usage(limit(97))
    world.move_to(at(MONDAY, 9, 10, 1))

    await world.scheduler.tick()

    assert len(world.service.missed) == 1 and world.service.wakes == []
    assert world.usage_alerts() == []


async def test_a_wake_that_fails_warns_the_owner_of_the_agent(world):
    broken = world.add_agent("quebrado")
    healthy = world.add_agent("saudavel")
    world.add_routine(broken, name="Quebrada")
    world.add_routine(healthy, name="Boa")
    world.service.fail_for = {broken}
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    [(agent_id, text)] = [a for a in world.service.alerts if a[0] == broken]
    assert 'rotina "Quebrada"' in text and "falhou" in text
    assert [a for a in world.service.alerts if a[0] == healthy] == []
    # The slot was consumed: the next tick does not warn again.
    await world.scheduler.tick()
    assert len([a for a in world.service.alerts if a[0] == broken]) == 1
