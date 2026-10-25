"""Persistent agent queue: concurrency, holds, cancellation and crash recovery, offline."""

import asyncio
from contextlib import closing

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    PauseStep,
    PermissionStep,
    init_message,
    text_turn,
)
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store
from claudio_maestro.specialists.service import SpecialistService

from .test_service import NOW, world  # noqa: F401

pytestmark = pytest.mark.anyio


def pause_queue(world, agent_id, paused=True):
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_specialist(conn, agent_id, now=NOW, queue_paused=paused)


async def test_concurrent_requests_share_one_fifo_and_advance_when_the_turn_ends(world):
    agent_id = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]

    first, second = await asyncio.gather(
        world.service.start_run(agent_id, trigger="manual", text="Primeira"),
        world.service.start_run(agent_id, trigger="schedule", text="Segunda", scheduled_for=NOW),
    )
    await asyncio.wait_for(pause.reached.wait(), 2)

    assert first.outcome == "running"
    assert second.outcome == "queued" and second.session_id is None
    assert len(world.factory.clients) == 1
    assert world.factory.clients[0].sent == ["Primeira"]
    world.turns = lambda sid: text_turn(sid, "ok")
    pause.release.set()
    await wait_until(lambda: len(world.factory.clients) == 2 and world.factory.clients[1].sent)
    assert world.factory.clients[1].sent == ["Segunda"]
    assert len(world.runs(agent_id)) == 2
    assert next(r for r in world.runs(agent_id) if r.id == second.id).outcome == "running"


async def test_paused_queue_survives_restart_with_its_original_text_outside_sqlite(world):
    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    run = await world.service.start_run(agent_id, trigger="manual", text="Pedido original único")
    assert run.outcome == "queued" and run.session_id is None
    assert not world.factory.clients
    payload = world.files.read_run_text("revisor", run.id)
    assert payload == "Pedido original único"
    assert b"Pedido original" not in world.db_path.read_bytes()
    await world.service.shutdown()
    world.service = SpecialistService(
        world.db_path, files=world.files, sessions=world.manager,
        publish=world.recorder, clock=lambda: world.now, finish_poll=0.005,
    )
    await world.service.recover()
    assert not world.factory.clients
    pause_queue(world, agent_id, False)
    await world.service.drain_queue()
    await wait_until(lambda: world.factory.clients and world.factory.clients[0].sent)
    assert world.factory.clients[0].sent == [payload]
    assert len(world.runs(agent_id)) == 1
    with pytest.raises(FileNotFoundError):
        world.files.read_run_text("revisor", run.id)


async def test_permission_and_closure_waits_hold_later_work(world):
    agent_id = world.add_specialist()
    world.turns = lambda sid: [
        init_message(sid), PermissionStep("Bash", {"command": "git push origin main"}),
        *text_turn(sid, "ok")[1:],
    ]
    first = await world.service.start_run(agent_id, trigger="manual")
    await wait_until(lambda: world.manager.get(first.session_id).state == "awaiting_decision")
    second = await world.service.start_run(agent_id, trigger="manual")
    assert second.outcome == "queued"
    await world.service.drain_queue()
    assert len(world.factory.clients) == 1


async def test_cancel_is_idempotent_and_only_affects_the_requested_agents_queued_run(world):
    agent_id = world.add_specialist()
    other = world.add_specialist(slug="outro")
    pause_queue(world, agent_id)
    run = await world.service.start_run(agent_id, trigger="manual", text="Não executar")
    with pytest.raises(store.SpecialistNotFoundError):
        await world.service.cancel_run(other, run.id)
    cancelled = await world.service.cancel_run(agent_id, run.id)
    assert cancelled.outcome == "cancelled" and cancelled.ended_at == NOW
    assert await world.service.cancel_run(agent_id, run.id) == cancelled
    pause_queue(world, agent_id, False)
    await world.service.drain_queue()
    assert not world.factory.clients
    with pytest.raises(FileNotFoundError):
        world.files.read_run_text("revisor", run.id)


async def test_running_run_cannot_be_cancelled_as_a_pending_delivery(world):
    agent_id = world.add_specialist()
    run = await world.service.start_run(agent_id, trigger="manual")
    with pytest.raises(store.RunNotQueuedError):
        await world.service.cancel_run(agent_id, run.id)


async def test_recovery_does_not_resend_uncertain_work_and_pauses_later_requests(world):
    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    uncertain = await world.service.start_run(agent_id, trigger="manual", text="Publicar")
    await world.service.start_run(agent_id, trigger="manual", text="Próxima tarefa")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_runs SET outcome = 'starting' WHERE id = ?", (uncertain.id,))
        store.update_specialist(conn, agent_id, now=NOW, queue_paused=False)
    await world.service.recover()
    assert not world.factory.clients
    assert world.specialist(agent_id).queue_paused
    failed = next(r for r in world.runs(agent_id) if r.id == uncertain.id)
    assert failed.outcome == "failed" and "confira" in failed.reason.lower()
    assert any(n.kind == "alert" for n in world.notices())


async def test_a_missing_payload_fails_without_sending_a_different_default_request(world):
    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    run = await world.service.start_run(agent_id, trigger="manual", text="Pedido específico")
    world.files.delete_run_text("revisor", run.id)
    pause_queue(world, agent_id, False)
    await world.service.drain_queue()
    assert not world.factory.clients
    assert world.runs(agent_id)[0].outcome == "failed"


async def test_pausing_does_not_interrupt_the_current_turn(world):
    agent_id = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    first = await world.service.start_run(agent_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    pause_queue(world, agent_id)
    await world.service.start_run(agent_id, trigger="manual")
    assert world.manager.get(first.session_id).state == "running"
    pause.release.set()
    await wait_until(lambda: world.manager.get(first.session_id).state == "idle")
    await world.service.drain_queue()
    assert len(world.factory.clients) == 1


async def test_queue_limit_refuses_more_work_without_creating_a_request(world):
    from claudio_maestro.specialists.service import MAX_QUEUED_RUNS, QueueFullError

    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    for _ in range(MAX_QUEUED_RUNS):
        await world.service.start_run(agent_id, trigger="manual")
    with pytest.raises(QueueFullError):
        await world.service.start_run(agent_id, trigger="manual")
    assert len(world.runs(agent_id)) == MAX_QUEUED_RUNS
    assert not world.factory.clients


async def test_failed_payload_write_rolls_back_both_the_request_and_schedule_slot(world, monkeypatch):
    agent_id = world.add_specialist()
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        [schedule] = store.replace_schedules(conn, agent_id, [("1234567", "09:00")], NOW - 60)

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(world.files, "write_run_text", fail)
    with pytest.raises(store.SpecialistError):
        await world.service.start_run(
            agent_id, trigger="schedule", scheduled_for=NOW, schedule_id=schedule.id,
        )
    assert world.runs(agent_id) == []
    with closing(db.connect(world.db_path)) as conn:
        assert store.list_schedules(conn, agent_id)[0].last_fired_at == NOW - 60
    assert not world.factory.clients


async def test_multiple_schedule_slots_collapse_into_one_pending_routine(world):
    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    first = await world.service.start_run(agent_id, trigger="schedule", scheduled_for=NOW)
    later = await world.service.start_run(agent_id, trigger="schedule", scheduled_for=NOW + 86400)
    assert first.id == later.id
    assert len(world.runs(agent_id)) == 1


async def test_recovery_of_a_live_starting_run_never_sends_it_again(world):
    agent_id = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    first = await world.service.start_run(agent_id, trigger="manual", text="Só uma vez")
    await asyncio.wait_for(pause.reached.wait(), 2)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE specialist_runs SET outcome = 'starting' WHERE id = ?", (first.id,))
    world.files.write_run_text("revisor", first.id, "Só uma vez")
    await world.service.recover()
    assert world.run_of(first.session_id).outcome == "running"
    assert not world.specialist(agent_id).queue_paused
    assert len(world.factory.clients) == 1
    assert world.factory.clients[0].sent == ["Só uma vez"]
    pause.release.set()


async def test_a_slow_start_does_not_block_other_agents_or_their_cancellations(world):
    first = world.add_specialist()
    other = world.add_specialist(slug="outro")
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        if world.record(session_id).specialist_id == first:
            reached.set()
            await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    task = asyncio.create_task(world.service.start_run(first, trigger="manual"))
    try:
        await asyncio.wait_for(reached.wait(), 2)
        run = await asyncio.wait_for(world.service.start_run(other, trigger="manual"), 1)
        assert run.session_id is not None
        pause_queue(world, other)
        pending = await asyncio.wait_for(world.service.start_run(other, trigger="manual"), 1)
        cancelled = await asyncio.wait_for(world.service.cancel_run(other, pending.id), 1)
        assert cancelled.outcome == "cancelled"
        await asyncio.wait_for(world.service.drain_queue(other), 1)
    finally:
        release.set()
        await task


async def test_queue_worker_keeps_advancing_other_agents_during_a_slow_start(world):
    first = world.add_specialist()
    other = world.add_specialist(slug="outro")
    pause_queue(world, first)
    pause_queue(world, other)
    await world.service.start_run(first, trigger="manual", text="Lenta")
    await world.service.start_run(other, trigger="manual", text="Primeira")
    second = await world.service.start_run(other, trigger="manual", text="Segunda")
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        if world.record(session_id).specialist_id == first:
            reached.set()
            await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    pause_queue(world, first, False)
    pause_queue(world, other, False)
    world.service.wake_queue()
    try:
        await asyncio.wait_for(reached.wait(), 2)
        await asyncio.wait_for(wait_until(lambda: any(c.sent == ["Segunda"] for c in world.factory.clients)), 1)
        assert next(r for r in world.runs(other) if r.id == second.id).session_id is not None
        assert not release.is_set()
    finally:
        release.set()


async def test_recovery_returns_without_waiting_for_queued_session_startup(world):
    agent_id = world.add_specialist()
    pause_queue(world, agent_id)
    await world.service.start_run(agent_id, trigger="manual", text="Retomar depois do reinício")
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        reached.set()
        await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    pause_queue(world, agent_id, False)
    task = asyncio.create_task(world.service.recover())
    try:
        await asyncio.wait_for(reached.wait(), 2)
        await asyncio.wait_for(asyncio.shield(task), 1)
        assert not release.is_set()
    finally:
        release.set()
        await task


async def test_lost_running_session_holds_later_work_until_the_person_finishes_it(world):
    agent_id = world.add_specialist()
    first = await world.service.start_run(agent_id, trigger="manual", text="Ação anterior")
    await wait_until(lambda: world.manager.get(first.session_id).state == "idle")
    pause_queue(world, agent_id)
    pending = await world.service.start_run(agent_id, trigger="manual", text="Não antecipar")
    await world.service.shutdown()
    await world.manager.shutdown()
    # Crash snapshot: the previous turn was open, but no process reattached on restart.
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE sessions SET turn_open = 1 WHERE session_id = ?", (first.session_id,))
        store.update_specialist(conn, agent_id, now=NOW, queue_paused=False)
    world.manager = SessionManager(
        world.db_path, world.recorder, agent_factory=world.factory,
        history_exists=lambda *args: False,
        session_setup=lambda record: world.service.session_setup(record),
        on_finished=lambda sid, at: world.service.on_finished(sid, at),
    )
    world.service = SpecialistService(
        world.db_path, files=world.files, sessions=world.manager,
        publish=world.recorder, clock=lambda: world.now, finish_poll=0.005,
    )
    await world.service.recover()
    assert world.run_of(first.session_id).outcome == "waiting"
    assert next(r for r in world.runs(agent_id) if r.id == pending.id).outcome == "queued"
    assert len(world.factory.clients) == 1
    await world.manager.update(first.session_id, finished=True)
    await world.service.drain_queue()
    await wait_until(lambda: len(world.factory.clients) == 2 and world.factory.clients[1].sent)
    assert world.factory.clients[1].sent == ["Não antecipar"]


async def test_reply_to_waiting_conversation_can_pass_an_older_queued_routine(world):
    agent = world.add_specialist()
    chat = await world.service.open_conversation(agent)
    first = await world.service.send_message(chat.session_id, "Primeira")
    await wait_until(lambda: next(r for r in world.runs(agent) if r.id == first.id).outcome == "concluded")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.finish_run(conn, first.id, outcome="waiting", ended_at=NOW, reason="Precisa de você")
    routine = await world.service.start_run(agent, trigger="manual", text="Rotina posterior")
    assert routine.outcome == "queued"
    await world.service.send_message(chat.session_id, "Pode continuar")
    await wait_until(lambda: "Pode continuar" in world.factory.clients[0].sent)
    assert world.factory.clients[0].sent[:2] == ["Primeira", "Pode continuar"]
    await wait_until(lambda: len(world.factory.clients) == 2 and world.factory.clients[1].sent)
    assert world.factory.clients[1].sent == ["Rotina posterior"]
