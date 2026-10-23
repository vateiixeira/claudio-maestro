"""Scheduler of the agents: due slots, grace period, skips and usage alerts. Uses a fake
clock and the scripted fake agent; the real SDK is never touched."""

import asyncio
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_sessions import Recorder, fake_history, make_project, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    FakeAgentFactory,
    PauseStep,
    PermissionStep,
    init_message,
    text_turn,
)
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store
from claudio_maestro.specialists.files import SpecialistFiles
from claudio_maestro.specialists.scheduler import (
    GRACE_SECONDS,
    TICK_SECONDS,
    USAGE_LIMIT_PERCENT,
    Scheduler,
    due_slot,
)
from claudio_maestro.specialists.service import SpecialistService
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
    return store.Schedule(id=1, specialist_id=1, days=days, time=time, last_fired_at=last_fired_at)


def test_constants():
    assert (GRACE_SECONDS, USAGE_LIMIT_PERCENT, TICK_SECONDS) == (600, 90, 30)


# due_slot -----------------------------------------------------------------------


def test_due_slot_same_day_and_weekday_filter():
    last = ts(at(MONDAY, 8))
    # Monday 09:30 with a 09:00 slot: it is today's.
    assert same(due_slot(schedule(EVERY_DAY, "09:00", last), at(MONDAY, 9, 30)), at(MONDAY, 9))
    # Sunday 03/11/2026 is not in Monday-Friday: the newest slot is Friday's.
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
    assert same(due_slot(schedule(EVERY_DAY, "09:00", ts(at(MONDAY, 8))), at(MONDAY, 9)), at(MONDAY, 9))


# World --------------------------------------------------------------------------


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.now = float(ts(at(MONDAY, 8)))
        self.recorder = Recorder()
        self.turns: Any = lambda sid: text_turn(sid, "feito")
        self.factory = FakeAgentFactory(
            script=lambda content: self.turns(self.factory.clients[-1].options.session_id)
        )
        self.files = SpecialistFiles(tmp_path / "agents")
        self.manager = SessionManager(
            self.db_path,
            self.recorder,
            agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            session_setup=lambda record: self.service.session_setup(record),
            on_finished=lambda sid, at: self.service.on_finished(sid, at),
            on_turn_error=lambda sid, error: self.service.on_turn_error(sid, error),
            on_init=lambda sid, servers: self.service.on_init(sid, servers),
        )
        self.service = SpecialistService(
            self.db_path,
            files=self.files,
            sessions=self.manager,
            publish=self.recorder,
            clock=lambda: self.now,
            finish_poll=0.005,
        )
        self.limits: list[UsageLimit] = []
        self.usage_error = False
        self.usage = UsageChecker(self.recorder, enabled=True, fetch=self._fetch)
        self.scheduler = Scheduler(
            self.service, self.manager, self.usage, self.db_path, clock=lambda: self.now
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

    def add_specialist(
        self,
        slug: str = "revisor",
        schedules: tuple[tuple[str, str], ...] = ((EVERY_DAY, "09:00"),),
        enabled: bool = True,
    ) -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            created = store.create_specialist(
                conn, slug=slug, name=slug.title(), project_id=self.project.id, now=1
            )
            if not enabled:
                store.update_specialist(conn, created.id, now=1, enabled=False)
            store.replace_schedules(conn, created.id, list(schedules), now=int(self.now))
        self.files.create(slug, slug.title())
        return created.id

    def runs(self, specialist_id: int) -> list[store.Run]:
        with closing(db.connect(self.db_path)) as conn:
            return list(reversed(store.list_runs(conn, specialist_id)))

    def schedules(self, specialist_id: int) -> list[store.Schedule]:
        with closing(db.connect(self.db_path)) as conn:
            return store.list_schedules(conn, specialist_id)

    def notices(self) -> list[store.Notice]:
        with closing(db.connect(self.db_path)) as conn:
            return list(reversed(store.list_notices(conn)))


@pytest.fixture
async def world(tmp_path: Path):
    built = World(tmp_path)
    yield built
    await built.service.shutdown()
    await built.manager.shutdown()


def limit(percent: int, label: str = "Sessão", resets_at: float | None = FUTURE) -> UsageLimit:
    return UsageLimit("session", label, percent, "critical", resets_at)


# tick ---------------------------------------------------------------------------


async def test_tick_does_nothing_before_the_slot(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 8, 59))

    await world.scheduler.tick()

    assert world.runs(specialist_id) == []
    assert world.factory.clients == []


async def test_tick_fires_once_per_slot(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()
    await world.scheduler.tick()

    [run] = world.runs(specialist_id)
    assert run.outcome == "running" and run.trigger == "schedule"
    assert run.scheduled_for == ts(at(MONDAY, 9))
    assert run.session_id is not None
    assert len(world.factory.clients) == 1
    assert world.schedules(specialist_id)[0].last_fired_at == int(world.now)

    # The next day's slot fires again.
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    world.move_to(at(27, 9, 0, 1))
    await world.scheduler.tick()
    assert len(world.runs(specialist_id)) == 2


async def test_late_but_inside_the_grace_still_fires(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 9, 59))

    await world.scheduler.tick()

    [run] = world.runs(specialist_id)
    assert run.outcome == "running" and run.scheduled_for == ts(at(MONDAY, 9))


async def test_past_the_grace_records_missed_and_does_not_start(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 10, 1))

    await world.scheduler.tick()
    await world.scheduler.tick()

    [run] = world.runs(specialist_id)
    assert run.outcome == "missed" and run.trigger == "schedule"
    assert run.scheduled_for == ts(at(MONDAY, 9))
    assert run.session_id is None and run.ended_at == int(world.now)
    assert run.reason
    assert world.factory.clients == []


async def test_backend_down_records_single_missed(world):
    one = world.add_specialist(schedules=((EVERY_DAY, "09:00"),))
    two = world.add_specialist(
        slug="outro", schedules=((EVERY_DAY, "09:00"), (EVERY_DAY, "18:00"))
    )
    world.move_to(at(29, 10))  # the app was off for three days

    await world.scheduler.tick()
    await world.scheduler.tick()

    assert [(r.outcome, r.scheduled_for) for r in world.runs(one)] == [
        ("missed", ts(at(29, 9)))
    ]
    assert sorted((r.outcome, r.scheduled_for) for r in world.runs(two)) == sorted(
        [("missed", ts(at(29, 9))), ("missed", ts(at(28, 18)))]
    )
    assert world.factory.clients == []
    assert world.notices() == []  # missed never counts toward the alert
    assert [m for m in world.recorder.envelopes if m["type"] == "specialist.run"]


async def test_missed_between_failures_does_not_repeat_the_streak_alert(world):
    specialist_id = world.add_specialist()
    for _ in range(2):
        world.service.record_skipped(specialist_id, "x")
    assert len(world.notices()) == 1

    world.move_to(at(MONDAY, 12))
    await world.scheduler.tick()

    assert [r.outcome for r in world.runs(specialist_id)][-1] == "missed"
    assert len(world.notices()) == 1


async def test_disabled_specialist_never_fires(world):
    specialist_id = world.add_specialist(enabled=False)
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()
    world.move_to(at(29, 12))
    await world.scheduler.tick()

    assert world.runs(specialist_id) == []
    assert world.factory.clients == []


async def test_reenabled_specialist_records_no_missed_and_fires_the_next_slot(world):
    specialist_id = world.add_specialist(enabled=False)
    for day in (MONDAY, 27, 28):  # disabled for three days, with the scheduler ticking
        world.move_to(at(day, 9, 0, 5))
        await world.scheduler.tick()
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_specialist(conn, specialist_id, now=1, enabled=True)

    world.move_to(at(28, 15))
    await world.scheduler.tick()
    assert world.runs(specialist_id) == []

    world.move_to(at(29, 9, 0, 5))
    await world.scheduler.tick()
    [run] = world.runs(specialist_id)
    assert run.outcome == "running" and run.scheduled_for == ts(at(29, 9))


async def test_skips_when_running(world):
    specialist_id = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    skipped = [r for r in world.runs(specialist_id) if r.outcome == "skipped"]
    assert len(skipped) == 1
    assert skipped[0].reason == "Uma execução anterior ainda está rodando ou esperando você."
    assert skipped[0].scheduled_for == ts(at(MONDAY, 9))
    assert skipped[0].trigger == "schedule" and skipped[0].session_id is None
    assert len(world.factory.clients) == 1
    assert world.schedules(specialist_id)[0].last_fired_at == int(world.now)

    # Marked as fired: it does not record a second skip for the same slot.
    await world.scheduler.tick()
    assert len([r for r in world.runs(specialist_id) if r.outcome == "skipped"]) == 1
    pause.release.set()


async def test_skips_when_a_decision_is_pending(world):
    specialist_id = world.add_specialist()
    world.turns = lambda sid: [
        init_message(sid),
        PermissionStep("Bash", {"command": "git push origin main"}),
        *text_turn(sid, "ok")[1:],
    ]
    run = await world.service.start_run(specialist_id, trigger="manual")
    await wait_until(lambda: world.manager.get(run.session_id).state == "awaiting_decision")
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    outcomes = [r.outcome for r in world.runs(specialist_id)]
    assert outcomes == ["running", "skipped"]


async def test_runs_when_the_previous_session_is_idle(world):
    specialist_id = world.add_specialist()
    run = await world.service.start_run(specialist_id, trigger="manual")
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert [r.outcome for r in world.runs(specialist_id)] == ["running", "running"]


async def test_skips_over_usage_limit_and_alerts_once_per_window(world):
    specialist_id = world.add_specialist()
    await world.set_usage(limit(40, "Semana", FUTURE + 1), limit(92, "Sessão", FUTURE))
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    [run] = world.runs(specialist_id)
    assert run.outcome == "skipped"
    assert run.reason == "Uso da assinatura em 92% (Sessão)."
    assert world.factory.clients == []
    alerts = [n for n in world.notices() if n.kind == "alert" and n.text.startswith("Uso da assinatura")]
    assert len(alerts) == 1 and alerts[0].specialist_id == specialist_id
    assert "92%" in alerts[0].text and "Sessão" in alerts[0].text

    # The next slot, same window of the limit: skipped again, no new usage alert.
    world.move_to(at(27, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["skipped", "skipped"]
    alerts = [n for n in world.notices() if n.kind == "alert" and n.text.startswith("Uso da assinatura")]
    assert len(alerts) == 1

    # The limit renewed (new `resets_at`) and went over again: it warns again.
    await world.set_usage(limit(95, "Sessão", FUTURE + 99_000.0))
    world.move_to(at(28, 9, 0, 5))
    await world.scheduler.tick()
    alerts = [n for n in world.notices() if n.kind == "alert" and n.text.startswith("Uso da assinatura")]
    assert len(alerts) == 2 and "95%" in alerts[-1].text


async def test_usage_below_the_limit_runs_and_at_the_limit_skips(world):
    specialist_id = world.add_specialist()
    await world.set_usage(limit(89))
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running"]

    await wait_until(lambda: world.manager.get(world.runs(specialist_id)[0].session_id).state == "idle")
    await world.set_usage(limit(USAGE_LIMIT_PERCENT))
    world.move_to(at(27, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running", "skipped"]


async def test_fires_when_usage_is_off_or_failed(world):
    specialist_id = world.add_specialist()
    world.usage.enabled = False
    world.limits = [limit(99)]
    world.move_to(at(MONDAY, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running"]
    await wait_until(lambda: world.manager.get(world.runs(specialist_id)[0].session_id).state == "idle")

    world.usage.enabled = True
    await world.set_usage(limit(99))
    world.usage_error = True
    await world.usage.refresh()  # keeps the old limits but the read now has an error
    assert world.usage.snapshot()["error"]
    world.move_to(at(27, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running", "running"]


async def test_one_failing_agent_does_not_stop_the_others(world):
    first = world.add_specialist()
    second = world.add_specialist(slug="outro")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE projects SET path = ? WHERE id = ?", ("/nao/existe", world.project.id))
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert [r.outcome for r in world.runs(first)] == ["failed"]
    assert [r.outcome for r in world.runs(second)] == ["failed"]


async def test_run_loop_ticks_until_cancelled(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 0, 5))

    task = asyncio.create_task(world.scheduler.run(interval=0.01))
    await wait_until(lambda: len(world.runs(specialist_id)) == 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_loop_survives_a_failing_tick(world, monkeypatch):
    calls = []

    async def boom() -> None:
        calls.append(1)
        raise RuntimeError("falha")

    monkeypatch.setattr(world.scheduler, "tick", boom)
    task = asyncio.create_task(world.scheduler.run(interval=0.005))
    await wait_until(lambda: len(calls) >= 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# is_busy ------------------------------------------------------------------------


async def test_is_busy_follows_the_sessions_of_that_agent(world):
    one = world.add_specialist()
    two = world.add_specialist(slug="outro")
    assert world.service.is_busy(one) is False

    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    run = await world.service.start_run(one, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    assert world.service.is_busy(one) is True
    assert world.service.is_busy(two) is False

    pause.release.set()
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    assert world.service.is_busy(one) is False


async def test_is_busy_with_a_pending_decision_and_ignores_finished_sessions(world):
    specialist_id = world.add_specialist()
    world.turns = lambda sid: [
        init_message(sid),
        PermissionStep("Bash", {"command": "git push origin main"}),
        *text_turn(sid, "ok")[1:],
    ]
    run = await world.service.start_run(specialist_id, trigger="manual")
    await wait_until(lambda: world.manager.get(run.session_id).state == "awaiting_decision")
    assert world.service.is_busy(specialist_id) is True

    session = world.manager.get(run.session_id)
    session.save(finished=True)
    assert world.service.is_busy(specialist_id) is False


# Usage windows that already renewed -----------------------------------------------


async def test_usage_limit_already_renewed_is_ignored(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 0, 5))
    # `resets_at` equal to now or before: the reading is old, the window is over.
    await world.set_usage(limit(97, "Sessão", world.now), limit(95, "Semana", world.now - 60))

    await world.scheduler.tick()

    assert [r.outcome for r in world.runs(specialist_id)] == ["running"]
    assert world.notices() == []


async def test_usage_limit_without_reset_time_still_counts(world):
    specialist_id = world.add_specialist()
    await world.set_usage(limit(97, "Sessão", None))
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert [r.outcome for r in world.runs(specialist_id)] == ["skipped"]


# Concurrency and failures ---------------------------------------------------------


async def test_concurrent_ticks_fire_once(world):
    specialist_id = world.add_specialist()
    world.move_to(at(MONDAY, 9, 0, 5))
    real_start_run = world.service.start_run
    calls: list[int] = []

    async def slow_start_run(*args: Any, **kwargs: Any):
        calls.append(1)
        await asyncio.sleep(0.05)
        return await real_start_run(*args, **kwargs)

    world.service.start_run = slow_start_run  # type: ignore[method-assign]

    await asyncio.gather(world.scheduler.tick(), world.scheduler.tick())

    assert len(calls) == 1
    assert len(world.runs(specialist_id)) == 1


async def test_start_run_raising_keeps_the_slot_fired_and_goes_on(world):
    first = world.add_specialist()
    second = world.add_specialist(slug="outro")
    real_start_run = world.service.start_run

    async def flaky_start_run(specialist_id: int, **kwargs: Any):
        if specialist_id == first:
            raise RuntimeError("falha inesperada")
        return await real_start_run(specialist_id, **kwargs)

    world.service.start_run = flaky_start_run  # type: ignore[method-assign]
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()
    await world.scheduler.tick()

    assert world.schedules(first)[0].last_fired_at == int(world.now)
    assert world.runs(first) == []
    assert [r.outcome for r in world.runs(second)] == ["running"]


async def test_failing_mark_fired_of_a_disabled_agent_does_not_stop_the_others(
    world, monkeypatch
):
    disabled = world.add_specialist(enabled=False)
    other = world.add_specialist(slug="outro")
    disabled_schedule = world.schedules(disabled)[0].id
    real_mark_fired = store.mark_fired

    def flaky_mark_fired(conn: Any, schedule_id: int, at: int) -> None:
        if schedule_id == disabled_schedule:
            raise RuntimeError("banco travado")
        real_mark_fired(conn, schedule_id, at)

    monkeypatch.setattr(store, "mark_fired", flaky_mark_fired)
    world.move_to(at(MONDAY, 9, 0, 5))

    await world.scheduler.tick()

    assert world.runs(disabled) == []
    assert [r.outcome for r in world.runs(other)] == ["running"]


# Daylight saving time ------------------------------------------------------------


@pytest.fixture
def new_york(monkeypatch):
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo("America/New_York")
    except Exception:
        pytest.skip("sem tzdata")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_due_slot_after_the_end_of_dst_does_not_repeat_yesterdays_slot(new_york):
    # 31/10/2026 09:00 EDT fired; on 01/11 (EST since 02:00) at 08:00 the next is not due.
    fired = ts(datetime(2026, 10, 31, 9, 0, 5))
    sched = schedule(EVERY_DAY, "09:00", fired)

    assert due_slot(sched, datetime(2026, 11, 1, 8, 0)) is None
    assert same(due_slot(sched, datetime(2026, 11, 1, 9, 0, 1)), datetime(2026, 11, 1, 9))


def test_due_slot_across_the_start_of_dst(new_york):
    # 07/03/2026 09:00 EST fired; DST starts 08/03 at 02:00.
    fired = ts(datetime(2026, 3, 7, 9, 0, 5))
    sched = schedule(EVERY_DAY, "09:00", fired)

    assert due_slot(sched, datetime(2026, 3, 8, 8, 59)) is None
    assert same(due_slot(sched, datetime(2026, 3, 8, 9, 0, 1)), datetime(2026, 3, 8, 9))


def test_due_slot_yesterdays_slot_uses_yesterdays_offset(new_york):
    # Never fired, 01/11 at 08:00 EST: the newest slot is 31/10 09:00 EDT = 13:00 UTC.
    slot = due_slot(schedule(EVERY_DAY, "09:00", None), datetime(2026, 11, 1, 8, 0))
    assert slot is not None
    assert slot.timestamp() == datetime(2026, 10, 31, 13, 0, tzinfo=UTC).timestamp()


async def test_tick_records_no_false_missed_when_dst_ends(world, new_york):
    world.move_to(datetime(2026, 10, 30, 12, 0))
    specialist_id = world.add_specialist()
    world.move_to(datetime(2026, 10, 31, 9, 0, 5))
    await world.scheduler.tick()
    [run] = world.runs(specialist_id)
    assert run.outcome == "running"
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")

    world.move_to(datetime(2026, 11, 1, 8, 0))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running"]

    world.move_to(datetime(2026, 11, 1, 9, 0, 5))
    await world.scheduler.tick()
    assert [r.outcome for r in world.runs(specialist_id)] == ["running", "running"]


async def test_tick_records_no_false_missed_when_dst_starts(world, new_york):
    world.move_to(datetime(2026, 3, 6, 12, 0))
    specialist_id = world.add_specialist()
    world.move_to(datetime(2026, 3, 7, 9, 0, 5))
    await world.scheduler.tick()
    [run] = world.runs(specialist_id)
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")

    world.move_to(datetime(2026, 3, 8, 8, 0))  # DST began at 02:00
    await world.scheduler.tick()
    assert len(world.runs(specialist_id)) == 1

    world.move_to(datetime(2026, 3, 8, 9, 0, 5))
    await world.scheduler.tick()
    runs = world.runs(specialist_id)
    assert [r.outcome for r in runs] == ["running", "running"]
    assert runs[1].scheduled_for == ts(datetime(2026, 3, 8, 9))
