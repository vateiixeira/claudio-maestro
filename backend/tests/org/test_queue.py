"""The wakeup queue of the organization: one active run per agent, the order of the origins, the
messages to the conversations, the usage cut, the time cap and the cancellations. Scripted fake
agent only; the real SDK is never touched."""

import asyncio
import json
import shutil
from contextlib import closing
from datetime import datetime
from typing import Any

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.files import WAKE_TEXT_MAX_CHARS
from claudio_maestro.org.service import (
    MAX_QUEUED_WAKEUPS,
    AgentDisabledError,
    QueueFullError,
    RunNotActiveError,
    WakeupNotPendingError,
)
from claudio_maestro.sessions import InvalidImageError

from .test_service import NOW, fresh, paused_run, paused_turn, world  # noqa: F401

pytestmark = pytest.mark.anyio

ROUTINE_TEXT = (
    'Execução da rotina "Ronda".\n\nFaça a ronda.\n\n'
    "Quando terminar, chame `concluir` com um resumo do que foi feito."
)
PIXEL = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAHnOcQAAAAABJRU5ErkJggg=="
)


def wakeup_rows(world, agent_id: int) -> list[dict[str, Any]]:
    with closing(db.connect(world.db_path)) as conn:
        rows = conn.execute(
            "SELECT id, source, state, run_id, payload FROM wakeups WHERE agent_id = ? ORDER BY id",
            (agent_id,),
        ).fetchall()
    return [dict(row) for row in rows]


async def sent_to(world, session_id: str) -> list[str]:
    client = next(c for c in world.factory.clients if c.options.session_id == session_id)
    return client.sent


# wake -----------------------------------------------------------------------------------


async def test_wake_manual_creates_run_session_and_sends_text(world):
    agent = world.add_agent(model="haiku", effort="low")

    wakeup = await world.service.wake(agent, source="manual", text="Só olhe o PR 12.")
    assert (wakeup.source, wakeup.state, wakeup.priority) == ("manual", "pending", 0)
    await world.service.drain(agent)

    [run] = world.runs(agent)
    assert (run.source, run.outcome, run.started_at) == ("manual", "running", NOW)
    assert run.session_id is not None and run.ended_at is None
    session = world.manager.get(run.session_id)
    assert session.record.agent_id == agent
    assert (session.record.model, session.record.effort) == ("haiku", "low")
    assert session.record.title == f"Revisor · {datetime.fromtimestamp(NOW):%d/%m %H:%M}"
    await wait_until(lambda: world.factory.clients and world.factory.clients[0].sent)
    assert world.sent() == ["Só olhe o PR 12."]
    [row] = wakeup_rows(world, agent)
    assert (row["state"], row["run_id"]) == ("taken", run.id)
    assert world.published("agent.run")[-1]["id"] == run.id
    with pytest.raises(FileNotFoundError):
        world.files.read_wake_text("revisor", wakeup.id)  # the text goes once it is sent


async def test_wake_without_text_sends_the_manual_prompt_and_the_routine_one(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)

    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)
    [first] = world.runs(agent)
    await world.service.conclude(first.session_id, "ok")
    await wait_until(lambda: world.record(first.session_id).finished)
    await world.service.wake(
        agent, source="routine", routine_id=routine, scheduled_for=NOW - 30
    )
    await world.service.drain(agent)

    assert world.sent(0)[0].startswith("Execução pedida manualmente.")
    run = world.runs(agent)[0]
    assert (run.source, run.routine_id, run.scheduled_for) == ("routine", routine, NOW - 30)
    assert await sent_to(world, run.session_id) == [ROUTINE_TEXT]


async def test_wake_in_the_background_starts_the_run_without_a_drain_call(world):
    agent = world.add_agent()

    await world.service.wake(agent, source="manual", text="Vá.")

    await wait_until(lambda: world.runs(agent) and world.runs(agent)[0].outcome == "running")
    await wait_until(lambda: world.factory.clients and world.sent() == ["Vá."])


async def test_wake_payload_is_stored_as_json_with_the_scheduled_time(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)

    wakeup = await world.service.wake(
        agent, source="comment", text="x", payload={"session_id": "abc", "n": 1},
        scheduled_for=NOW,
    )

    [row] = wakeup_rows(world, agent)
    assert json.loads(row["payload"]) == {"session_id": "abc", "n": 1, "scheduled_for": NOW}
    assert wakeup.payload == {"session_id": "abc", "n": 1, "scheduled_for": NOW}


async def test_a_comment_wakeup_without_a_session_goes_to_the_main_conversation(world):
    agent = world.add_agent()

    await world.service.wake(agent, source="comment", text="Comentário no PR.", payload={"x": 1})
    await world.service.drain(agent)

    main = world.agent(agent).main_session_id
    assert main is not None
    assert await sent_to(world, main) == ["Comentário no PR."]
    assert world.runs(agent) == []  # the main conversation has no run
    [row] = wakeup_rows(world, agent)
    assert (row["state"], row["run_id"]) == ("taken", None)


async def test_a_comment_wakeup_with_a_session_opens_a_comment_run_on_it(world):
    agent = world.add_agent()
    session = world.session_of(agent)

    await world.service.wake(
        agent, source="comment", text="Comentário no PR.", payload={"session_id": session.session_id}
    )
    await world.service.drain(agent)

    [run] = world.runs(agent)
    assert (run.source, run.outcome, run.session_id) == ("comment", "running", session.session_id)
    assert await sent_to(world, session.session_id) == ["Comentário no PR."]


async def test_routine_wakeups_of_the_same_routine_are_grouped(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.set_enabled(agent, False)

    first = await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    later = await world.service.wake(
        agent, source="routine", routine_id=routine, scheduled_for=NOW + 86400
    )

    assert first.id == later.id
    assert len(wakeup_rows(world, agent)) == 1
    assert world.files.read_wake_text("revisor", first.id)[0] == ROUTINE_TEXT


async def test_manual_text_has_a_limit_and_a_refused_wake_leaves_nothing(world):
    agent = world.add_agent()

    with pytest.raises(store.OrgError):
        await world.service.wake(agent, source="manual", text="x" * (WAKE_TEXT_MAX_CHARS + 1))
    with pytest.raises(store.NotFoundError):
        await world.service.wake(404, source="manual")
    with pytest.raises(store.NotFoundError):
        await world.service.wake(agent, source="routine", routine_id=999)

    assert wakeup_rows(world, agent) == []
    assert list(world.files.folder("revisor").glob("wake-*")) == []


async def test_a_failed_text_write_rolls_the_wakeup_back(world, monkeypatch):
    agent = world.add_agent()

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(world.files, "write_wake_text", fail)
    with pytest.raises(store.OrgError):
        await world.service.wake(agent, source="manual", text="oi")

    assert wakeup_rows(world, agent) == []


async def test_the_queue_has_a_limit_that_the_person_s_requests_do_not_count_in(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)
    for _ in range(MAX_QUEUED_WAKEUPS):
        await world.service.wake(agent, source="comment", text="c")

    with pytest.raises(QueueFullError):
        await world.service.wake(agent, source="comment", text="c")
    assert len(wakeup_rows(world, agent)) == MAX_QUEUED_WAKEUPS

    # What the person asks for is never refused for a full queue (nor counted in it).
    for source in ("manual", "message"):
        with pytest.raises(AgentDisabledError):
            await world.service.wake(agent, source=source, text="Oi")
    assert len(wakeup_rows(world, agent)) == MAX_QUEUED_WAKEUPS + 2
    with pytest.raises(QueueFullError):
        await world.service.wake(agent, source="comment", text="c")


# One active run per agent ----------------------------------------------------------------


async def test_two_wakeups_run_one_at_a_time(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.set_enabled(agent, False)
    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    with pytest.raises(AgentDisabledError):
        await world.service.wake(agent, source="manual", text="Agora.")
    world.set_enabled(agent, True)

    await world.service.drain(agent)

    [first] = world.runs(agent)
    assert first.source == "manual"  # manual goes before the routine that came first
    assert [w.source for w in world.wakeups(agent)] == ["routine"]
    await world.service.drain(agent)
    assert len(world.runs(agent)) == 1  # the second waits for the first

    await world.service.conclude(first.session_id, "Pronto.")
    await wait_until(lambda: world.record(first.session_id).finished)
    await wait_until(lambda: len(world.runs(agent)) == 2)
    second = world.runs(agent)[0]
    assert second.source == "routine" and second.session_id != first.session_id
    assert world.wakeups(agent) == []


async def test_concurrent_drains_start_a_single_run(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)
    for _ in range(3):
        with pytest.raises(AgentDisabledError):
            await world.service.wake(agent, source="manual")
    world.set_enabled(agent, True)

    await asyncio.gather(*(world.service.drain(agent) for _ in range(5)))

    assert len(world.runs(agent)) == 1
    assert len(world.factory.clients) == 1
    assert len(world.wakeups(agent)) == 2


async def test_two_services_over_the_same_data_start_a_single_run(world):
    """The lock of the agent is in memory; the claim in the database is what holds across
    two services (the old one and the new one around a restart)."""
    agent = world.add_agent()
    other = world.new_service()
    world.set_enabled(agent, False)
    for _ in range(2):
        with pytest.raises(AgentDisabledError):
            await world.service.wake(agent, source="manual")
    world.set_enabled(agent, True)

    await asyncio.gather(world.service.drain(agent), other.drain(agent))

    assert len(world.runs(agent)) == 1
    assert len(world.wakeups(agent)) == 1
    await other.shutdown()


async def test_the_claim_refuses_a_second_active_run_and_a_wakeup_already_taken(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)
    with pytest.raises(AgentDisabledError) as caught:
        await world.service.wake(agent, source="manual")
    wakeup = caught.value.wakeup

    first = world.service._claim_run(agent, wakeup)
    again = world.service._claim_run(agent, wakeup)

    assert first is not None and first.outcome == "starting"
    assert again is None
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        spare = store.enqueue_wakeup(conn, agent_id=agent, source="manual", payload=None, now=NOW)
    assert world.service._claim_run(agent, spare) is None  # an active run holds the agent
    assert len(world.runs(agent)) == 1


async def test_a_slow_start_does_not_block_another_agent(world):
    first = world.add_agent()
    other = world.add_agent(slug="outro")
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        if world.record(session_id).agent_id == first:
            reached.set()
            await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    await world.service.wake(first, source="manual", text="Lenta")
    try:
        await asyncio.wait_for(reached.wait(), 2)
        await world.service.wake(other, source="manual", text="Rápida")
        await wait_until(lambda: world.runs(other) and world.runs(other)[0].outcome == "running")
        assert world.runs(first)[0].outcome == "starting"
    finally:
        release.set()
    await wait_until(lambda: world.runs(first)[0].outcome == "running")


async def test_an_open_turn_of_the_agent_holds_the_run_until_it_ends(world):
    agent = world.add_agent()
    pause = paused_turn(world)
    main = await world.service.ensure_main(agent)
    await world.manager.send(main, "Converse comigo.")
    await asyncio.wait_for(pause.reached.wait(), 2)

    await world.service.wake(agent, source="manual", text="Rodar.")
    await world.service.drain(agent)
    await asyncio.sleep(0.05)
    assert world.runs(agent) == []  # the conversation is mid-turn

    pause.release.set()
    await wait_until(lambda: len(world.runs(agent)) == 1)  # the poller takes it up
    assert world.runs(agent)[0].source == "manual"


async def test_a_waiting_run_holds_the_agent_until_the_person_finishes_it(world):
    agent = world.add_agent()
    run = await world.started(agent)
    await world.service.on_closure(fresh(run.session_id, verdict="user_action", user_actions=["A"]))
    assert world.run_of(run.session_id).outcome == "waiting"

    await world.service.wake(agent, source="manual", text="Outra.")
    await world.service.drain(agent)
    await asyncio.sleep(0.05)
    assert len(world.runs(agent)) == 1

    await world.manager.update(run.session_id, finished=True)
    await wait_until(lambda: len(world.runs(agent)) == 2)


# Disabled agents ----------------------------------------------------------------------------


async def test_disabled_agent_finishes_current_run_but_takes_no_wakeup(world):
    agent = world.add_agent()
    run, pause = await paused_run(world, agent)

    world.set_enabled(agent, False)
    with pytest.raises(AgentDisabledError):
        await world.service.wake(agent, source="manual", text="Mais uma.")
    await world.service.drain(agent)
    assert world.run_of(run.session_id).outcome == "running"  # not killed
    assert world.manager.get(run.session_id).state == "running"

    pause.release.set()
    await world.service.conclude(run.session_id, "Pronto.")
    await wait_until(lambda: world.record(run.session_id).finished)
    await world.service.drain(agent)
    await asyncio.sleep(0.05)
    assert len(world.runs(agent)) == 1  # nothing new while it is off
    assert len(world.wakeups(agent)) == 1

    world.set_enabled(agent, True)
    await world.service.drain(agent)  # turning it back on drains again
    assert len(world.runs(agent)) == 2 and world.wakeups(agent) == []


async def test_turning_the_agent_back_on_resumes_the_queue_by_itself(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)
    with pytest.raises(AgentDisabledError):
        await world.service.wake(agent, source="manual", text="Quando voltar.")
    await asyncio.sleep(0.05)
    assert world.runs(agent) == []

    world.set_enabled(agent, True)  # nobody calls drain: the look at the queue finds it

    await wait_until(lambda: world.runs(agent) and world.runs(agent)[0].outcome == "running")
    await wait_until(lambda: world.factory.clients and world.sent() == ["Quando voltar."])


async def test_task_origins_without_a_task_are_dropped_or_refused(world):
    agent = world.add_agent()

    # An `assignment` needs a task; with none it has nothing to start, so it is dropped.
    await world.service.wake(agent, source="assignment", text="Tarefa 1")
    # A `decision` that does not say which decision it answers cannot be queued.
    with pytest.raises(store.OrgError):
        await world.service.wake(agent, source="decision", text="Decisão")
    await world.service.drain(agent)
    await asyncio.sleep(0.05)

    assert world.runs(agent) == [] and world.factory.clients == []
    assert world.wakeups(agent) == []
    assert [row["state"] for row in wakeup_rows(world, agent)] == ["dropped"]


async def test_a_wakeup_from_an_unknown_origin_is_refused(world):
    agent = world.add_agent()

    with pytest.raises(store.OrgError):
        await world.service.wake(agent, source="bogus")  # type: ignore[arg-type]

    assert wakeup_rows(world, agent) == []


async def test_a_disabled_agent_keeps_a_routine_wakeup_pending_without_error(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.set_enabled(agent, False)

    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    await world.service.drain(agent)

    assert world.runs(agent) == [] and len(world.wakeups(agent)) == 1


# Messages ---------------------------------------------------------------------------------


async def test_message_goes_straight_to_main_when_idle(world):
    agent = world.add_agent()

    wakeup = await world.service.wake(agent, source="message", text="Como vai?")
    await world.service.drain(agent)

    main = world.agent(agent).main_session_id
    assert main is not None
    await wait_until(lambda: world.factory.clients and world.sent() == ["Como vai?"])
    assert world.runs(agent) == []  # a message is not a run
    [row] = wakeup_rows(world, agent)
    assert (row["id"], row["state"], row["run_id"]) == (wakeup.id, "taken", None)
    assert world.service.is_conversation(main)


async def test_message_waits_while_run_is_active(world):
    agent = world.add_agent()
    run, pause = await paused_run(world, agent)

    await world.service.wake(agent, source="message", text="Oi, chefe.")
    await world.service.drain(agent)
    main = world.agent(agent).main_session_id
    await asyncio.sleep(0.05)
    assert [w.source for w in world.wakeups(agent)] == ["message"]
    assert len(world.factory.clients) == 1  # only the run's session

    await world.service.conclude(run.session_id, "Pronto.")
    await world.service.drain(agent)

    assert world.wakeups(agent) == []
    await wait_until(lambda: len(world.factory.clients) == 2)
    [delivered] = await sent_to(world, main)
    # The announcement of the run that just ended travels in front of the message.
    assert delivered.startswith("<maestro-anuncios>\n") and "concluída: Pronto." in delivered
    assert delivered.endswith("</maestro-anuncios>\n\nOi, chefe.")
    pause.release.set()


async def test_message_to_the_session_of_a_waiting_run_passes_and_resumes_it(world):
    agent = world.add_agent()
    run = await world.started(agent)
    await world.service.on_closure(fresh(run.session_id, verdict="incomplete", missing=["X"]))
    assert world.run_of(run.session_id).outcome == "waiting"

    await world.service.wake(
        agent, source="message", text="Pode seguir.", payload={"session_id": run.session_id}
    )
    await world.service.drain(agent)

    await wait_until(lambda: world.sent() == [world.sent()[0], "Pode seguir."])
    assert world.run_of(run.session_id).outcome == "running"
    assert world.service.is_conversation(run.session_id)  # the person took it back
    assert world.wakeups(agent) == []


async def test_message_to_a_disabled_agent_stays_pending_and_is_delivered_when_it_is_back(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)

    with pytest.raises(AgentDisabledError) as caught:
        await world.service.wake(agent, source="message", text="Está aí?")
    await world.service.drain(agent)
    assert [w.id for w in world.wakeups(agent)] == [caught.value.wakeup.id]
    assert world.factory.clients == []

    world.set_enabled(agent, True)
    await world.service.drain(agent)

    await wait_until(lambda: world.factory.clients and world.sent() == ["Está aí?"])
    assert world.wakeups(agent) == []


async def test_message_text_has_no_5000_character_limit_but_images_are_checked(world):
    agent = world.add_agent()

    wakeup = await world.service.wake(agent, source="message", text="x" * 9000)
    await world.service.drain(agent)
    await wait_until(lambda: world.factory.clients and world.sent() == ["x" * 9000])
    assert wakeup.state == "pending"

    with pytest.raises(InvalidImageError):
        await world.service.wake(
            agent, source="message", text="y", images=[{"media_type": "text/plain", "data": "eA=="}]
        )
    await world.service.wake(
        agent, source="message", text="com imagem",
        images=[{"media_type": "image/png", "data": PIXEL}],
    )
    await world.service.drain(agent)
    await wait_until(lambda: len(world.sent()) == 2)
    sent = world.sent()[-1]
    assert isinstance(sent, list)
    assert sent[0] == {"type": "text", "text": "com imagem"}
    assert sent[1]["type"] == "image" and sent[1]["source"]["data"] == PIXEL
    assert len(wakeup_rows(world, agent)) == 2  # the refused one left nothing


async def test_message_to_a_session_of_another_agent_is_refused(world):
    agent = world.add_agent()
    other = world.add_agent(slug="outro")
    foreign = world.manager.create_session(world.project, agent_id=other)

    with pytest.raises(store.NotFoundError):
        await world.service.wake(
            agent, source="message", text="oi", payload={"session_id": foreign.session_id}
        )
    with pytest.raises(store.NotFoundError):
        await world.service.wake(agent, source="message", text="oi", payload={"session_id": "x"})

    assert wakeup_rows(world, agent) == []


async def test_message_creates_the_main_conversation_if_missing_and_needs_a_project(world):
    agent = world.add_agent()
    shutil.rmtree(world.project.path)

    with pytest.raises(Exception, match="projeto"):
        await world.service.wake(agent, source="message", text="oi")

    assert wakeup_rows(world, agent) == []


async def test_a_message_whose_send_fails_alerts_and_does_not_block_the_queue(world):
    agent = world.add_agent()

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("sem conexão")

    real_send = world.manager.send
    world.manager.send = boom  # type: ignore[method-assign]
    await world.service.wake(agent, source="message", text="Perdida?")
    await world.service.drain(agent)
    world.manager.send = real_send  # type: ignore[method-assign]
    await world.service.wake(agent, source="manual", text="Segue.")
    await world.service.drain(agent)

    assert [n.kind for n in world.notices()] == ["alert"]
    assert len(world.runs(agent)) == 1 and world.wakeups(agent) == []


# Usage cut ------------------------------------------------------------------------------


async def test_usage_gate_skips_routine_but_not_manual(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.service.usage_gate = lambda: (95, "5 horas")
    world.set_enabled(agent, False)
    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    with pytest.raises(AgentDisabledError):
        await world.service.wake(agent, source="manual", text="Mesmo assim.")
    world.set_enabled(agent, True)

    await world.service.drain(agent)

    runs = world.runs(agent)
    skipped = next(r for r in runs if r.outcome == "skipped")
    assert skipped.reason == "Uso da assinatura em 95% (5 horas)."
    assert (skipped.source, skipped.routine_id, skipped.scheduled_for) == ("routine", routine, NOW)
    assert skipped.session_id is None and skipped.ended_at == NOW
    manual = next(r for r in runs if r.source == "manual")
    assert manual.outcome == "running"
    states = {w["source"]: w["state"] for w in wakeup_rows(world, agent)}
    assert states == {"routine": "dropped", "manual": "taken"}
    assert world.announcements(agent) == []
    assert list(world.files.folder("revisor").glob("wake-*")) == []


async def test_usage_gate_lets_messages_through_and_skips_while_the_agent_is_busy(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    run, pause = await paused_run(world, agent)
    world.service.usage_gate = lambda: (91, "semana")

    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    await world.service.wake(agent, source="comment", text="c")
    await world.service.drain(agent)

    assert sorted(r.source for r in world.runs(agent) if r.outcome == "skipped") == [
        "comment", "routine"
    ]
    assert world.wakeups(agent) == []
    pause.release.set()


async def test_usage_gate_without_a_reading_changes_nothing(world):
    agent = world.add_agent()
    world.service.usage_gate = lambda: None
    routine = world.add_routine(agent)

    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    await world.service.drain(agent)

    assert world.runs(agent)[0].outcome == "running"


# Failures while starting ------------------------------------------------------------------


async def test_a_missing_project_records_a_failed_run(world):
    agent = world.add_agent()
    shutil.rmtree(world.project.path)

    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)

    [run] = world.runs(agent)
    assert run.outcome == "failed" and run.session_id is None and run.ended_at == NOW
    assert run.reason and "projeto" in run.reason.lower()
    assert world.factory.clients == []
    assert world.published("agent.run")[-1]["outcome"] == "failed"
    assert world.service.is_busy(agent) is False


async def test_a_send_failure_records_a_failed_run_and_frees_the_agent(world):
    agent = world.add_agent()

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("sem conexão")

    real_send = world.manager.send
    world.manager.send = boom  # type: ignore[method-assign]
    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)
    world.manager.send = real_send  # type: ignore[method-assign]

    [run] = world.runs(agent)
    assert run.outcome == "failed" and "Confira a conversa" in (run.reason or "")
    assert [n.kind for n in world.notices()] == ["alert"]
    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)
    assert len(world.runs(agent)) == 2


async def test_a_missing_wake_text_fails_the_run_without_sending_anything_else(world):
    agent = world.add_agent()
    world.set_enabled(agent, False)
    with pytest.raises(AgentDisabledError) as caught:
        await world.service.wake(agent, source="manual", text="Pedido específico")
    world.files.delete_wake_text("revisor", caught.value.wakeup.id)
    world.set_enabled(agent, True)

    await world.service.drain(agent)

    assert world.factory.clients == []
    [run] = world.runs(agent)
    assert run.outcome == "failed" and run.session_id is None


async def test_a_session_that_cannot_be_created_fails_the_run(world, monkeypatch):
    agent = world.add_agent()

    def broken(*args: Any, **kwargs: Any):
        raise RuntimeError("banco indisponível")

    monkeypatch.setattr(world.manager, "create_session", broken)
    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)

    [run] = world.runs(agent)
    assert run.outcome == "failed" and run.reason == "Não foi possível criar a sessão do agente."


# The time cap -----------------------------------------------------------------------------


async def test_run_times_out_after_max_run_minutes(world):
    agent = world.add_agent(maxRunMinutes=1)
    run, pause = await paused_run(world, agent)
    client = world.factory.clients[0]
    world.now = NOW + 30
    await asyncio.sleep(0.05)
    assert world.run_of(run.session_id).outcome == "running"  # not yet

    world.now = NOW + 61

    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    saved = world.run_of(run.session_id)
    assert saved.reason == "Tempo máximo da execução (1 min) esgotado."
    assert saved.ended_at == NOW + 61
    await wait_until(lambda: client.interrupts == 1)
    [alert] = world.notices()
    assert alert.kind == "alert" and "1 min" in alert.text and alert.run_id == run.id
    [announcement] = world.announcements(agent)
    assert announcement.text.endswith("falhou: Tempo máximo da execução (1 min) esgotado.")
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    assert world.run_of(run.session_id).outcome == "failed"
    pause.release.set()


async def test_a_run_that_ended_before_the_cap_is_left_alone(world):
    agent = world.add_agent(maxRunMinutes=1)
    run = await world.started(agent)
    await world.service.conclude(run.session_id, "Pronto.")

    world.now = NOW + 600
    await asyncio.sleep(0.05)

    saved = world.run_of(run.session_id)
    assert saved.outcome == "concluded" and saved.reason is None
    assert world.factory.clients[0].interrupts == 0
    assert not world.service._watchers


async def test_recover_rearms_the_cap_of_a_run_in_flight(world):
    agent = world.add_agent(maxRunMinutes=1)
    run, pause = await paused_run(world, agent)
    await world.service.shutdown()
    service = world.new_service()
    await service.recover()

    world.now = NOW + 61

    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    pause.release.set()
    await service.shutdown()


async def test_a_message_cancelled_in_the_middle_of_the_send_leaves_no_file_behind(world):
    agent = world.add_agent()
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        reached.set()
        await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    await world.service.wake(agent, source="message", text="Não perca isto.")
    await asyncio.wait_for(reached.wait(), 2)
    assert len(list(world.files.folder("revisor").glob("wake-*"))) == 1
    assert wakeup_rows(world, agent)[0]["state"] == "taken"

    await world.service.shutdown()  # cancels the drainer inside the send

    assert list(world.files.folder("revisor").glob("wake-*")) == []
    release.set()


async def test_a_verdict_does_not_reopen_a_run_ended_by_the_cap(world):
    agent = world.add_agent(maxRunMinutes=1)
    run, pause = await paused_run(world, agent)
    world.now = NOW + 61
    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    reason = world.run_of(run.session_id).reason
    assert reason == "Tempo máximo da execução (1 min) esgotado."
    notices = len(world.notices())

    for verdict in ("user_action", "incomplete", "can_close"):
        await world.service.on_closure(
            fresh(run.session_id, verdict=verdict, user_actions=["A"], missing=["B"], evidence="ok")
        )
    await asyncio.sleep(0.1)

    saved = world.run_of(run.session_id)
    assert (saved.outcome, saved.reason) == ("failed", reason)
    assert len(world.notices()) == notices  # no "precisa de você" on top of the cap alert
    assert world.record(run.session_id).finished is False
    await world.service.wake(agent, source="manual", text="Seguinte.")
    pause.release.set()
    await wait_until(lambda: len(world.runs(agent)) == 2)  # the agent is free


async def test_recover_does_not_reopen_a_run_ended_by_the_cap(world):
    agent = world.add_agent(maxRunMinutes=1)
    run, pause = await paused_run(world, agent)
    world.now = NOW + 61
    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("UPDATE sessions SET turn_open = 1 WHERE session_id = ?", (run.session_id,))
    world.manager._sessions.pop(run.session_id)
    service = world.new_service()

    await service.recover()

    assert world.run_of(run.session_id).outcome == "failed"
    await service.shutdown()
    pause.release.set()


async def test_a_failed_run_that_goes_back_to_waiting_gets_the_time_cap_again_from_then(world):
    agent = world.add_agent(maxRunMinutes=1)
    run = await world.started(agent)
    world.service.on_turn_error(run.session_id, "Erro.")
    assert world.run_of(run.session_id).outcome == "failed"
    assert run.id not in world.service._watchers
    world.now = NOW + 100  # already past the cap counted from the start of the run

    await world.service.on_closure(fresh(run.session_id, verdict="user_action", user_actions=["A"]))

    assert world.run_of(run.session_id).outcome == "waiting"
    assert run.id in world.service._watchers
    await asyncio.sleep(0.3)  # the cap counts from the return, not from the start
    assert world.run_of(run.session_id).outcome == "waiting"
    world.now = NOW + 100 + 61

    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    assert world.run_of(run.session_id).reason == "Tempo máximo da execução (1 min) esgotado."
    await world.service.wake(agent, source="manual", text="Outra.")
    await wait_until(lambda: len(world.runs(agent)) == 2)  # the agent is free again


async def test_a_run_back_in_flight_after_an_error_is_watched_whatever_the_way_back(world):
    agent = world.add_agent(maxRunMinutes=1)
    run = await world.started(agent)
    world.service.on_turn_error(run.session_id, "Erro.")

    world.service._set_run_state(run.id, "running", None, only_from=("failed",))

    assert run.id in world.service._watchers
    world.now = NOW + 61
    await wait_until(lambda: world.run_of(run.session_id).outcome == "failed")
    assert world.run_of(run.session_id).reason == "Tempo máximo da execução (1 min) esgotado."


# Cancellations ----------------------------------------------------------------------------


async def test_cancel_wakeup_is_idempotent_and_only_affects_the_agents_pending_wakeup(world):
    agent = world.add_agent()
    other = world.add_agent(slug="outro")
    world.set_enabled(agent, False)
    with pytest.raises(AgentDisabledError) as caught:
        await world.service.wake(agent, source="manual", text="Não executar")
    wakeup = caught.value.wakeup

    with pytest.raises(store.NotFoundError):
        await world.service.cancel_wakeup(other, wakeup.id)
    with pytest.raises(store.NotFoundError):
        await world.service.cancel_wakeup(agent, 999)
    await world.service.cancel_wakeup(agent, wakeup.id)
    await world.service.cancel_wakeup(agent, wakeup.id)

    assert wakeup_rows(world, agent)[0]["state"] == "dropped"
    with pytest.raises(FileNotFoundError):
        world.files.read_wake_text("revisor", wakeup.id)
    world.set_enabled(agent, True)
    await world.service.drain(agent)
    assert world.factory.clients == [] and world.runs(agent) == []


async def test_cancel_wakeup_refuses_one_already_served(world):
    agent = world.add_agent()
    await world.service.wake(agent, source="manual")
    await world.service.drain(agent)
    [row] = wakeup_rows(world, agent)

    with pytest.raises(WakeupNotPendingError):
        await world.service.cancel_wakeup(agent, row["id"])


async def test_cancel_run_interrupts_the_turn_and_frees_the_agent(world):
    agent = world.add_agent()
    other = world.add_agent(slug="outro")
    run, pause = await paused_run(world, agent)
    client = world.factory.clients[0]

    with pytest.raises(store.NotFoundError):
        await world.service.cancel_run(other, run.id)
    cancelled = await world.service.cancel_run(agent, run.id)
    again = await world.service.cancel_run(agent, run.id)

    assert cancelled.outcome == "cancelled" and cancelled.ended_at == NOW
    assert again == cancelled
    assert client.interrupts == 1
    assert world.announcements(agent) == []
    await world.service.wake(agent, source="manual", text="Seguinte.")
    await wait_until(lambda: len(world.runs(agent)) == 2)  # waits for the turn to end first
    pause.release.set()


async def test_cancel_run_refuses_a_run_that_ended(world):
    agent = world.add_agent()
    run = await world.started(agent)
    await world.service.conclude(run.session_id, "Pronto.")

    with pytest.raises(RunNotActiveError):
        await world.service.cancel_run(agent, run.id)


async def test_cancelling_a_run_while_its_text_is_being_sent_interrupts_the_turn_that_starts(world):
    agent = world.add_agent()
    pause = paused_turn(world)
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        reached.set()
        await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    await world.service.wake(agent, source="manual", text="Apague tudo.")
    await asyncio.wait_for(reached.wait(), 2)
    [run] = world.runs(agent)
    assert run.outcome == "starting"

    await world.service.cancel_run(agent, run.id)
    release.set()
    await asyncio.wait_for(pause.reached.wait(), 2)  # the text did go out and a turn began
    client = world.factory.clients[0]

    await wait_until(lambda: client.interrupts >= 1)  # ...and it was stopped, not left to run
    assert world.runs(agent)[0].outcome == "cancelled"
    pause.release.set()
    await wait_until(lambda: world.service.is_busy(agent) is False)


async def test_a_run_failed_by_the_cap_while_its_text_is_being_sent_is_interrupted_too(world):
    agent = world.add_agent()
    pause = paused_turn(world)
    reached, release = asyncio.Event(), asyncio.Event()
    real_send = world.manager.send

    async def slow_send(session_id, text, *args, **kwargs):
        reached.set()
        await release.wait()
        return await real_send(session_id, text, *args, **kwargs)

    world.manager.send = slow_send
    await world.service.wake(agent, source="manual", text="Vá.")
    await asyncio.wait_for(reached.wait(), 2)
    [run] = world.runs(agent)
    world.service.on_turn_error(world.runs(agent)[0].session_id, "Erro no meio do envio.")
    assert world.runs(agent)[0].outcome == "failed"

    release.set()
    await asyncio.wait_for(pause.reached.wait(), 2)

    await wait_until(lambda: world.factory.clients[0].interrupts >= 1)
    assert world.runs(agent)[0].id == run.id and world.runs(agent)[0].outcome == "failed"
    pause.release.set()


# Shutdown ------------------------------------------------------------------------------------


async def test_shutdown_stops_the_workers_and_new_wakeups_wait(world):
    agent = world.add_agent()
    run, pause = await paused_run(world, agent)
    other = world.add_agent(slug="outro")

    await world.service.shutdown()
    assert not world.service._watchers
    await world.service.wake(other, source="manual", text="Depois.")
    await asyncio.sleep(0.05)

    assert world.runs(other) == [] and len(world.wakeups(other)) == 1
    pause.release.set()


# The queue of an instance that must not act by itself (`MAESTRO_ROUTINES_SCHEDULER=0`) -------


async def test_without_automatic_serving_only_the_person_s_requests_run(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.service.serve_automatic = False
    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    await world.service.wake(agent, source="comment", text="c")

    await world.service.drain(agent)

    assert world.runs(agent) == []
    assert sorted(w.source for w in world.wakeups(agent)) == ["comment", "routine"]
    assert world.service._agents_with_work() == []  # nothing to look at every few moments

    await world.service.wake(agent, source="manual", text="Rode agora.")
    await world.service.drain(agent)

    assert [r.source for r in world.runs(agent)] == ["manual"]
    assert sorted(w.source for w in world.wakeups(agent)) == ["comment", "routine"]


async def test_without_automatic_serving_a_message_is_still_delivered(world):
    agent = world.add_agent()
    world.service.serve_automatic = False
    await world.service.wake(agent, source="message", text="Oi")
    await world.service.drain(agent)

    assert world.wakeups(agent) == []


async def test_recover_does_not_take_up_the_queue_without_automatic_serving(world):
    agent = world.add_agent()
    routine = world.add_routine(agent)
    world.service.serve_automatic = False
    await world.service.wake(agent, source="routine", routine_id=routine, scheduled_for=NOW)
    kicks: list[Any] = []
    world.service.kick = lambda *a, **k: kicks.append(a)  # type: ignore[method-assign]

    await world.service.recover()

    assert kicks == []
    await asyncio.sleep(0.1)
    assert world.runs(agent) == []
    assert [w.source for w in world.wakeups(agent)] == ["routine"]
