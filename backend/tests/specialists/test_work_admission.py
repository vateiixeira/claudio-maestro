"""Legacy admission yields to project work without touching tool permissions."""

from contextlib import closing

import pytest

from claudio_maestro import db
from claudio_maestro.specialists import store
from claudio_maestro.specialists.service import LegacyWorkModeError

from .test_scheduler import MONDAY, at
from .test_scheduler import World as SchedulerWorld
from .test_service import world  # noqa: F401

pytestmark = pytest.mark.anyio


def enable_mode(path, project_id):
    with closing(db.connect(path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO work_project_modes (project_id, enabled, paused, updated_at)"
            " VALUES (?, 1, 0, 1) ON CONFLICT(project_id) DO UPDATE SET enabled=1",
            (project_id,),
        )


@pytest.mark.parametrize("extra", [False, True])
async def test_manual_and_schedule_admission_check_all_projects(world, extra):
    target = world.add_project("Extra", "extra") if extra else world.project.id
    agent = world.add_specialist(extra_project_ids=[target] if extra else [])
    enable_mode(world.db_path, target)
    for trigger in ("manual", "schedule"):
        with pytest.raises(LegacyWorkModeError):
            await world.service.start_run(agent, trigger=trigger)
    assert world.runs(agent) == []
    assert world.factory.clients == []
    assert not world.service.legacy_available(agent)


async def test_message_is_refused_before_opening_or_queuing(world):
    agent = world.add_specialist()
    record = world.manager.create_session(world.project, agent_id=agent)
    enable_mode(world.db_path, world.project.id)
    with pytest.raises(LegacyWorkModeError):
        await world.service.send_message(record.session_id, "continuar")
    with closing(db.connect(world.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM specialist_chats").fetchone()[0] == 0
    assert world.runs(agent) == []
    assert world.factory.clients == []


async def test_pending_legacy_request_stays_queued_while_mode_is_active(world):
    agent = world.add_specialist()
    run = await world.service.start_run(agent, trigger="manual", defer_dispatch=True)
    enable_mode(world.db_path, world.project.id)
    await world.service.drain_queue(agent)
    assert world.factory.clients == []
    assert world.runs(agent)[0].id == run.id
    assert world.runs(agent)[0].outcome == "queued"


async def test_mode_is_rechecked_inside_the_claim_transaction(world, monkeypatch):
    agent = world.add_specialist()
    await world.service.start_run(agent, trigger="manual", defer_dispatch=True)
    create = world.manager.create_session

    def create_then_switch(*args, **kwargs):
        record = create(*args, **kwargs)
        enable_mode(world.db_path, world.project.id)
        return record

    monkeypatch.setattr(world.manager, "create_session", create_then_switch)
    await world.service.drain_queue(agent)
    assert world.runs(agent)[0].outcome == "queued"
    assert world.factory.clients == []


async def test_pr_comment_cannot_bypass_mode(world):
    agent = world.add_specialist()
    main = await world.service.ensure_main(agent)
    pr = store.Pr("https://github.com/org/repo/pull/1", agent, main, 1, None, False)
    enable_mode(world.db_path, world.project.id)
    with pytest.raises(LegacyWorkModeError):
        await world.service.start_comment_run(pr, [])
    assert world.factory.clients == []


async def test_scheduler_preserves_due_occurrence_in_work_mode(tmp_path, caplog):
    world = SchedulerWorld(tmp_path)
    try:
        agent = world.add_specialist()
        with closing(db.connect(world.db_path)) as conn:
            previous = store.list_schedules(conn, agent)[0].last_fired_at
        world.move_to(at(MONDAY, 12))  # Outside grace, still must not consume it.
        enable_mode(world.db_path, world.project.id)
        await world.scheduler.tick()
        await world.scheduler.tick()
        with closing(db.connect(world.db_path)) as conn:
            assert store.list_schedules(conn, agent)[0].last_fired_at == previous
        assert world.runs(agent) == []
        assert world.factory.clients == []
        assert "Falha ao disparar" not in caplog.text
    finally:
        await world.service.shutdown()
        await world.manager.shutdown()


async def test_scheduler_handles_mode_switch_at_admission_without_consuming(tmp_path, monkeypatch, caplog):
    world = SchedulerWorld(tmp_path)
    try:
        agent = world.add_specialist()
        with closing(db.connect(world.db_path)) as conn:
            previous = store.list_schedules(conn, agent)[0].last_fired_at
        world.move_to(at(MONDAY, 9))
        start = world.service.start_run

        async def switch_then_start(*args, **kwargs):
            enable_mode(world.db_path, world.project.id)
            return await start(*args, **kwargs)

        monkeypatch.setattr(world.service, "start_run", switch_then_start)
        await world.scheduler.tick()
        with closing(db.connect(world.db_path)) as conn:
            assert store.list_schedules(conn, agent)[0].last_fired_at == previous
        assert world.runs(agent) == []
        assert "Falha ao disparar" not in caplog.text
    finally:
        await world.service.shutdown()
        await world.manager.shutdown()
