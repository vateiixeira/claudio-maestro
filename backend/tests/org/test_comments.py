"""CommentDispatcher: the queue of the owner's PR comments becomes a `comment` wakeup of the agent,
which the drainer sends to the session that opened the PR. Scripted fake agent only; the real SDK
is never touched."""

import asyncio
import json
import logging
import shutil
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.comments import (
    DISPATCH_TICK,
    MAX_TURNS_PER_DAY,
    POLL_SECONDS,
    QUIET_SECONDS,
    CommentDispatcher,
    day_start,
)
from claudio_maestro.org.service import QueueFullError

from .test_queue import wakeup_rows
from .test_service import NOW, World, world  # noqa: F401

pytestmark = pytest.mark.anyio

NOON = int(datetime(2026, 10, 23, 12, 0).timestamp())
PR = "https://github.com/acme/app/pull/9"
ASK_ORIGIN = "Resolva o que foi pedido. Não comente no GitHub; ao terminar, chame concluir com o resumo."
ASK_MAIN = "Resolva o que foi pedido e responda aqui."


def queue(
    world: World,
    agent_id: int,
    comment_id: str,
    *,
    at: int,
    pr: str = PR,
    author: str = "vini",
    body: str = "ajuste isso",
    path: str | None = None,
    line: int | None = None,
    status: str = "queued",
    batch_at: int | None = None,
) -> None:
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        assert store.insert_comment(
            conn,
            store.PrComment(
                comment_id=comment_id, pr_url=pr, agent_id=agent_id, author=author,
                body=body, path=path, line=line, html_url=f"{pr}#x", created_at=at,
                received_at=at, status=status, batch_at=batch_at,  # type: ignore[arg-type]
            ),
        )


def register_pr(world: World, agent_id: int, session_id: str | None, pr: str = PR) -> None:
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.upsert_pr(conn, url=pr, agent_id=agent_id, session_id=session_id, created_at=NOW)


def dispatcher(world: World) -> CommentDispatcher:
    return CommentDispatcher(world.service, world.db_path, lambda: world.now)


def statuses(world: World) -> dict[str, tuple[str, int | None]]:
    with closing(db.connect(world.db_path)) as conn:
        rows = conn.execute("SELECT comment_id, status, batch_at FROM agent_pr_comments")
        return {row["comment_id"]: (row["status"], row["batch_at"]) for row in rows}


def sent(world: World, session_id: str) -> list[str]:
    """Everything sent to the session, whichever client (process) carried it."""
    return [
        text for client in world.factory.clients
        if client.options.session_id == session_id for text in client.sent
    ]


def comment_runs(world: World, agent_id: int) -> list[store.Run]:
    return [run for run in world.runs(agent_id) if run.source == "comment"]


def comment_wakeups(world: World, agent_id: int) -> list[dict[str, Any]]:
    return [row for row in wakeup_rows(world, agent_id) if row["source"] == "comment"]


async def deliver(world: World, dispatch: CommentDispatcher, agent_id: int) -> None:
    """A tick of the dispatcher and the drain of what it queued."""
    await dispatch.tick()
    await world.service.drain(agent_id)


async def agent_with_pr(world: World, *, open_run: bool = False) -> tuple[int, str]:
    """An agent whose first run opened the PR; returns the agent id and that session. The
    run is over by default (the comments then open a run of their own)."""
    agent = world.add_agent()
    run = await world.started(agent)
    if not open_run:
        with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
            store.update_run(conn, run.id, outcome="concluded", ended_at=NOW)
    register_pr(world, agent, run.session_id)
    return agent, run.session_id


def alerts(world: World) -> list[str]:
    return [n.text for n in world.notices() if n.kind == "alert"]


def delete_session_row(world: World, session_id: str) -> None:
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def test_constants():
    assert (QUIET_SECONDS, MAX_TURNS_PER_DAY, POLL_SECONDS, DISPATCH_TICK) == (60, 10, 3600, 15)


# The quiet window, the batch and the caps ---------------------------------------------------


async def test_comment_batch_wakes_agent_in_pr_session(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "line:1", at=NOW, body="renomeie isso", path="app/models.py", line=12)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    [row] = comment_wakeups(world, agent)
    assert row["state"] == "taken" and json.loads(row["payload"]) == {
        "session_id": session_id, "pr_url": PR, "comment_ids": ["line:1"],
    }
    [run] = comment_runs(world, agent)
    assert (run.session_id, run.source, run.outcome) == (session_id, "comment", "running")
    assert run.id == row["run_id"]
    [text] = sent(world, session_id)[before:]
    assert text == (
        f"Comentário de @vini no PR {PR}:\n[app/models.py:12] renomeie isso\n{ASK_ORIGIN}"
    )
    assert statuses(world)["line:1"] == ("delivered", NOW + 100)
    assert world.published("agent.run")[-1]["id"] == run.id


async def test_waits_quiet_window(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOW + 30
    await deliver(world, dispatch, agent)
    assert len(sent(world, session_id)) == before
    assert comment_wakeups(world, agent) == []
    assert statuses(world)["issue:1"] == ("queued", None)

    world.now = NOW + 61
    await deliver(world, dispatch, agent)
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"] == ("delivered", NOW + 61)


async def test_a_new_comment_restarts_the_quiet_window(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    queue(world, agent, "issue:2", at=NOW + 50)
    before = len(sent(world, session_id))

    world.now = NOW + 70  # 70 s after the first, 20 s after the second
    await deliver(world, dispatcher(world), agent)

    assert len(sent(world, session_id)) == before
    assert comment_wakeups(world, agent) == []


async def test_groups_review_into_one_turn(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "review:1", at=NOW, body="Visão geral")
    for number in (2, 3, 4):
        queue(world, agent, f"line:{number}", at=NOW + number, body=f"c{number}",
              path="app.py", line=number)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    messages = sent(world, session_id)[before:]
    assert len(messages) == 1
    for expected in ("Visão geral", "[app.py:2] c2", "[app.py:3] c3", "[app.py:4] c4"):
        assert expected in messages[0]
    assert {status for status, _ in statuses(world).values()} == {"delivered"}
    assert len(comment_wakeups(world, agent)) == 1
    assert len(comment_runs(world, agent)) == 1


async def test_a_long_batch_is_not_cut_at_the_wake_text_limit(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW, body="x" * 20_000)

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    assert "x" * 20_000 in sent(world, session_id)[-1]


async def test_usage_over_keeps_queue_and_alerts_once(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    world.service.usage_gate = lambda: (93, "5h")
    dispatch = dispatcher(world)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await deliver(world, dispatch, agent)
    await deliver(world, dispatch, agent)

    assert len(sent(world, session_id)) == before
    assert comment_wakeups(world, agent) == []
    assert statuses(world)["issue:1"] == ("queued", None)
    assert alerts(world) == ["Comentário no PR #9 na fila: uso da assinatura em 93%."]

    # It renews: the queue drains. A later spike warns again.
    world.service.usage_gate = lambda: None
    await deliver(world, dispatch, agent)
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"][0] == "delivered"
    assert len(alerts(world)) == 1

    await wait_until(lambda: world.manager.get(session_id).state == "idle")
    queue(world, agent, "issue:2", at=world.now)
    world.service.usage_gate = lambda: (95, "5h")
    world.now += 100
    await deliver(world, dispatch, agent)
    assert len(alerts(world)) == 2


async def test_usage_below_the_limit_delivers(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    world.service.usage_gate = lambda: None
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    assert len(sent(world, session_id)) == before + 1


async def test_daily_cap(world):
    world.now = NOON
    agent, session_id = await agent_with_pr(world)
    for number in range(MAX_TURNS_PER_DAY):
        queue(world, agent, f"old:{number}", at=NOON - 7000, status="delivered",
              batch_at=NOON - 3600 + number)
    queue(world, agent, "issue:11", at=NOON)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOON + 100
    await deliver(world, dispatch, agent)
    await deliver(world, dispatch, agent)

    assert len(sent(world, session_id)) == before
    assert statuses(world)["issue:11"] == ("queued", None)
    assert alerts(world) == [
        "Comentário no PR #9 na fila: limite de 10 turnos por dia atingido."
    ]

    # The next day the count starts over.
    world.now = NOON + 100 + 86400
    await deliver(world, dispatch, agent)
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:11"][0] == "delivered"


async def test_the_tenth_batch_of_the_day_still_goes(world):
    world.now = NOON
    agent, session_id = await agent_with_pr(world)
    for number in range(MAX_TURNS_PER_DAY - 1):
        queue(world, agent, f"old:{number}", at=NOON - 7000, status="delivered",
              batch_at=NOON - 3600 + number)
    queue(world, agent, "issue:10", at=NOON)
    before = len(sent(world, session_id))

    world.now = NOON + 100
    await deliver(world, dispatcher(world), agent)

    assert len(sent(world, session_id)) == before + 1


# Where the comments go ----------------------------------------------------------------------


async def test_delivers_to_origin_session_and_reopens_finished(world):
    agent, session_id = await agent_with_pr(world)
    await world.manager.update(session_id, finished=True)
    assert world.record(session_id).finished is True
    queue(world, agent, "line:1", at=NOW, body="renomeie isso", path="app/models.py", line=12)

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    [run] = comment_runs(world, agent)
    assert (run.session_id, run.outcome) == (session_id, "running")
    assert world.record(session_id).finished is False
    text = sent(world, session_id)[-1]
    assert text.startswith(f"Comentário de @vini no PR {PR}:\n")
    assert "[app/models.py:12] renomeie isso" in text
    assert text.endswith(ASK_ORIGIN)


async def test_a_closed_process_is_resumed_to_receive_the_comments(world):
    agent, session_id = await agent_with_pr(world)
    await world.manager.get(session_id).close()
    clients_before = len(world.factory.clients)
    queue(world, agent, "issue:1", at=NOW, body="e o teste?")

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    assert len(world.factory.clients) == clients_before + 1
    reopened = world.factory.clients[-1]
    assert reopened.options.session_id == session_id and reopened.options.resume is True
    assert "e o teste?" in reopened.sent[-1]
    [run] = comment_runs(world, agent)
    assert (run.session_id, run.outcome) == (session_id, "running")


@pytest.mark.parametrize("deleted", [True, False])
async def test_missing_session_goes_to_main(world, deleted):
    agent = world.add_agent()
    origin = world.manager.create_session(world.project, agent_id=agent).session_id
    register_pr(world, agent, origin if deleted else None)
    if deleted:
        delete_session_row(world, origin)
    queue(world, agent, "issue:1", at=NOW, body="e o teste?")

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    main = world.agent(agent).main_session_id
    assert main is not None and main != origin
    text = sent(world, main)[-1]
    assert "e o teste?" in text
    assert text.endswith(ASK_MAIN)
    assert "concluir" not in text
    assert comment_runs(world, agent) == []
    assert statuses(world)["issue:1"][0] == "delivered"
    [row] = comment_wakeups(world, agent)
    assert (row["state"], row["run_id"]) == ("taken", None)


async def test_a_session_deleted_after_the_batch_was_queued_falls_back_to_main(world):
    agent, session_id = await agent_with_pr(world, open_run=True)
    queue(world, agent, "issue:1", at=NOW, body="e o teste?")
    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)  # the open run holds it: still pending
    assert [row["state"] for row in comment_wakeups(world, agent)] == ["pending"]

    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_run(conn, world.run_of(session_id).id, outcome="concluded", ended_at=NOW)
    # The process still remembers the session: the delete is only in the database, and the
    # run that would be born on it is refused by the foreign key.
    delete_session_row(world, session_id)
    await world.service.drain(agent)

    main = world.agent(agent).main_session_id
    assert main is not None
    text = sent(world, main)[-1]
    assert "e o teste?" in text and text.endswith(ASK_MAIN)
    assert [r.source for r in world.runs(agent)] == ["manual"]  # no orphan comment run
    [row] = comment_wakeups(world, agent)
    assert (row["state"], row["run_id"]) == ("taken", None)


async def test_a_session_of_another_agent_in_the_payload_is_not_used(world):
    agent = world.add_agent()
    stranger = world.add_agent("outro")
    foreign = world.manager.create_session(world.project, agent_id=stranger).session_id

    await world.service.wake(
        agent, source="comment", text=f"Comentário de @vini no PR {PR}:\nx\n{ASK_ORIGIN}",
        payload={"session_id": foreign},
    )
    await world.service.drain(agent)

    assert sent(world, foreign) == []
    main = world.agent(agent).main_session_id
    assert main is not None and main != foreign
    assert sent(world, main)[-1].endswith(ASK_MAIN)
    assert comment_runs(world, agent) == []


async def test_a_pr_opened_from_the_main_conversation_goes_to_it_without_a_run(world):
    agent = world.add_agent()
    main = await world.service.ensure_main(agent)
    register_pr(world, agent, main)
    queue(world, agent, "issue:1", at=NOW)

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    assert sent(world, main)[-1].endswith(ASK_MAIN)
    assert comment_runs(world, agent) == []
    assert statuses(world)["issue:1"][0] == "delivered"


async def test_a_comment_whose_pr_is_unknown_goes_to_main(world):
    agent = world.add_agent()
    queue(world, agent, "issue:1", at=NOW)  # PR never registered (an item's link)

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    main = world.agent(agent).main_session_id
    assert main is not None and "ajuste isso" in sent(world, main)[-1]


# The queue of the agent: one run at a time, disabled agents, the usage cut --------------------


async def test_a_comment_waits_for_the_open_run_of_the_agent(world):
    agent, session_id = await agent_with_pr(world, open_run=True)
    queue(world, agent, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    world.now = NOW + 100

    await deliver(world, dispatcher(world), agent)

    assert [row["state"] for row in comment_wakeups(world, agent)] == ["pending"]
    assert len(sent(world, session_id)) == before
    assert [r.outcome for r in world.runs(agent)] == ["running"]

    await world.service.conclude(session_id, "Feito.")
    await wait_until(lambda: world.record(session_id).finished)
    await world.service.drain(agent)

    assert len(sent(world, session_id)) == before + 1
    assert [r.source for r in world.runs(agent)] == ["comment", "manual"]
    assert [r.outcome for r in world.runs(agent)] == ["running", "concluded"]


async def test_a_comment_for_the_waiting_run_that_opened_the_pr_is_a_message_to_it(world):
    agent, session_id = await agent_with_pr(world, open_run=True)
    run = world.run_of(session_id)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_run(conn, run.id, outcome="waiting")
    queue(world, agent, "issue:1", at=NOW, body="pode seguir")
    before = len(sent(world, session_id))
    world.now = NOW + 100

    await deliver(world, dispatcher(world), agent)

    assert "pode seguir" in sent(world, session_id)[before]
    assert len(sent(world, session_id)) == before + 1
    assert [(r.source, r.outcome) for r in world.runs(agent)] == [("manual", "running")]
    [row] = comment_wakeups(world, agent)
    assert (row["state"], row["run_id"]) == ("taken", None)


async def test_two_prs_of_the_agent_never_run_together(world):
    agent, first = await agent_with_pr(world)
    other = "https://github.com/acme/app/pull/10"
    second = world.manager.create_session(world.project, agent_id=agent).session_id
    register_pr(world, agent, second, pr=other)
    queue(world, agent, "issue:1", at=NOW)
    queue(world, agent, "issue:2", at=NOW, pr=other)
    world.now = NOW + 100

    await deliver(world, dispatcher(world), agent)

    active = [r for r in comment_runs(world, agent) if r.outcome in store.ACTIVE_OUTCOMES]
    assert len(active) == 1
    assert [row["state"] for row in comment_wakeups(world, agent)].count("pending") == 1


async def test_a_disabled_agent_is_not_woken_and_wakes_when_turned_on(world):
    agent, session_id = await agent_with_pr(world)
    world.set_enabled(agent, False)
    queue(world, agent, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    world.now = NOW + 100

    await deliver(world, dispatcher(world), agent)

    assert len(sent(world, session_id)) == before
    assert [row["state"] for row in comment_wakeups(world, agent)] == ["pending"]
    assert comment_runs(world, agent) == []

    world.set_enabled(agent, True)
    await world.service.drain(agent)

    assert len(sent(world, session_id)) == before + 1
    assert len(comment_runs(world, agent)) == 1


async def test_a_comment_dropped_by_the_usage_cut_goes_back_to_the_queue(world):
    agent, session_id = await agent_with_pr(world, open_run=True)
    queue(world, agent, "issue:1", at=NOW)
    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)  # held by the open run
    assert statuses(world)["issue:1"] == ("delivered", NOW + 100)

    world.service.usage_gate = lambda: (93, "5h")
    await world.service.drain(agent)

    assert statuses(world)["issue:1"] == ("queued", None)
    assert [row["state"] for row in comment_wakeups(world, agent)] == ["dropped"]
    assert [r.outcome for r in comment_runs(world, agent)] == ["skipped"]

    world.service.usage_gate = lambda: None
    await world.service.conclude(session_id, "Feito.")
    await deliver(world, dispatcher(world), agent)
    assert statuses(world)["issue:1"][0] == "delivered"


async def test_queue_survives_restart(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    before = len(sent(world, session_id))

    world.now = NOW + 10
    await deliver(world, dispatcher(world), agent)  # the quiet window has not passed
    assert len(sent(world, session_id)) == before

    # "Restart": a brand-new dispatcher reads the queue from the database.
    world.now = NOW + 3600
    await deliver(world, dispatcher(world), agent)

    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"][0] == "delivered"


# Failures -----------------------------------------------------------------------------------


async def test_a_failed_delivery_stays_queued_and_the_next_tick_retries(world, caplog):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    real_wake = world.service.wake
    failing = True

    async def wake(*args, **kwargs):
        if failing:
            raise store.OrgError("a fila não aceitou")
        return await real_wake(*args, **kwargs)

    world.service.wake = wake
    world.now = NOW + 100
    dispatch = dispatcher(world)

    with caplog.at_level(logging.ERROR):
        await dispatch.tick()

    assert statuses(world)["issue:1"] == ("queued", None)
    assert "a fila não aceitou" in caplog.text
    assert comment_wakeups(world, agent) == []
    assert alerts(world) == ["Comentário no PR #9 não foi entregue: a fila não aceitou"]

    # The retries every tick neither warn again nor repeat the traceback.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await dispatch.tick()
        await dispatch.tick()
    assert len(alerts(world)) == 1
    assert "Traceback" not in caplog.text and "ainda não entregues" in caplog.text

    failing = False
    await deliver(world, dispatch, agent)
    assert statuses(world)["issue:1"][0] == "delivered"
    assert len(comment_runs(world, agent)) == 1

    # Delivered once: a later failure of the same PR warns again.
    await wait_until(lambda: world.manager.get(session_id).state == "idle")
    failing = True
    queue(world, agent, "issue:2", at=world.now)
    world.now += 100
    await dispatch.tick()
    assert len(alerts(world)) == 2


async def test_a_full_queue_keeps_the_comments_queued(world):
    agent, _ = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)

    async def wake(*args, **kwargs):
        raise QueueFullError()

    world.service.wake = wake
    world.now = NOW + 100
    await dispatcher(world).tick()

    assert statuses(world)["issue:1"] == ("queued", None)
    assert "A fila já tem 50" in alerts(world)[0]


async def test_a_failure_in_one_pr_does_not_stop_the_others(world):
    agent, _ = await agent_with_pr(world)
    other = "https://github.com/acme/app/pull/10"
    other_session = world.manager.create_session(world.project, agent_id=agent)
    register_pr(world, agent, other_session.session_id, pr=other)
    queue(world, agent, "issue:1", at=NOW)
    queue(world, agent, "issue:2", at=NOW, pr=other)
    real = world.service.wake

    async def wake(agent_id, **kwargs):
        if kwargs["payload"]["pr_url"] == PR:
            raise store.OrgError("falhou")
        return await real(agent_id, **kwargs)

    world.service.wake = wake
    world.now = NOW + 100
    await dispatcher(world).tick()

    assert statuses(world)["issue:1"][0] == "queued"
    assert statuses(world)["issue:2"][0] == "delivered"


@pytest.mark.parametrize("error", [RuntimeError("caiu"), asyncio.CancelledError()])
async def test_an_unknown_failure_of_the_queueing_is_not_replayed(world, error):
    agent, _ = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    calls = []
    real = world.service.wake

    async def wake(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return await real(*args, **kwargs)

    world.service.wake = wake
    world.now = NOW + 100
    dispatch = dispatcher(world)
    task = asyncio.create_task(dispatch.tick())
    await asyncio.gather(task, return_exceptions=True)

    assert statuses(world)["issue:1"][0] == "uncertain"
    assert any("confira" in text.lower() for text in alerts(world))
    await dispatch.tick()
    assert len(calls) == 1  # never again on its own
    assert comment_wakeups(world, agent) == []


async def test_recovery_holds_a_dispatch_reserved_before_process_exit(world):
    agent = world.add_agent()
    register_pr(world, agent, None)
    queue(world, agent, "issue:reserved", at=NOW - 120, status="dispatching", batch_at=NOW - 10)

    await dispatcher(world).tick()

    assert statuses(world)["issue:reserved"][0] == "uncertain"
    assert comment_wakeups(world, agent) == []
    assert not world.factory.clients
    assert any("confira" in notice.text.lower() for notice in world.notices())


async def test_overlapping_ticks_deliver_once(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOW + 100
    await asyncio.gather(dispatch.tick(), dispatch.tick())
    await world.service.drain(agent)

    assert len(sent(world, session_id)) == before + 1
    assert len(comment_wakeups(world, agent)) == 1
    assert len(comment_runs(world, agent)) == 1


async def test_a_session_that_fails_to_send_ends_the_run_and_frees_the_agent(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    real_send = world.manager.send

    async def send(*args, **kwargs):
        raise RuntimeError("sem conexão")

    world.manager.send = send
    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)
    world.manager.send = real_send

    [run] = comment_runs(world, agent)
    assert run.outcome == "failed"
    assert world.service.is_busy(agent) is False
    assert statuses(world)["issue:1"][0] == "delivered"  # the batch was queued; the failure is the run's


# A send that provably did not leave --------------------------------------------------------


def not_started(world: World, result: dict[str, Any]) -> Any:
    real_send = world.manager.send

    async def send(*args, **kwargs):
        return result

    world.manager.send = send
    return real_send


@pytest.mark.parametrize("path", ["pr-session", "main", "waiting-run"])
async def test_a_send_that_did_not_start_returns_the_batch_to_the_queue(world, path):
    if path == "main":
        agent = world.add_agent()
        session_id = None
    else:
        agent, session_id = await agent_with_pr(world, open_run=path == "waiting-run")
        if path == "waiting-run":
            with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
                store.update_run(conn, world.run_of(session_id).id, outcome="waiting")
    if session_id is None:
        register_pr(world, agent, None)
    queue(world, agent, "issue:1", at=NOW, body="ajuste isso")
    real_send = not_started(world, {"state": "idle", "send_started": False})
    dispatch = dispatcher(world)

    world.now = NOW + 100
    await deliver(world, dispatch, agent)

    assert statuses(world)["issue:1"] == ("queued", None)
    assert [row["state"] for row in comment_wakeups(world, agent)] == ["taken"]
    assert any(n.kind == "alert" for n in world.notices())
    assert world.service.is_busy(agent) is (path == "waiting-run")
    if path == "pr-session":
        assert [r.outcome for r in comment_runs(world, agent)] == ["failed"]

    # Nothing is sent again by itself in the same moment (the quiet window runs again), and
    # once the connection works the next tick delivers it.
    await deliver(world, dispatch, agent)
    assert statuses(world)["issue:1"] == ("queued", None)
    world.manager.send = real_send
    world.now += QUIET_SECONDS + 1
    await deliver(world, dispatch, agent)
    assert statuses(world)["issue:1"][0] == "delivered"
    target = session_id or world.agent(agent).main_session_id
    assert "ajuste isso" in sent(world, target)[-1]


@pytest.mark.parametrize("path", ["pr-session", "main"])
@pytest.mark.parametrize("how", ["state-error", "exception"])
async def test_a_send_without_confirmation_is_never_replayed(world, path, how):
    if path == "main":
        agent = world.add_agent()
        register_pr(world, agent, None)
    else:
        agent, _ = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    real_send = world.manager.send

    async def send(*args, **kwargs):
        if how == "exception":
            raise RuntimeError("caiu")
        return {"state": "error", "send_started": True}

    world.manager.send = send
    world.now = NOW + 100
    dispatch = dispatcher(world)
    await deliver(world, dispatch, agent)
    world.manager.send = real_send
    world.now += 1000
    await deliver(world, dispatch, agent)

    assert statuses(world)["issue:1"][0] == "delivered"
    assert len(comment_wakeups(world, agent)) == 1


async def test_a_comment_does_not_reach_a_run_that_stopped_waiting(world):
    agent, session_id = await agent_with_pr(world, open_run=True)  # the run is `running`
    await world.service.wake(
        agent, source="comment", text=f"x\n{ASK_ORIGIN}", payload={"session_id": session_id}
    )
    before = len(sent(world, session_id))
    with closing(db.connect(world.db_path)) as conn:
        [wakeup] = [w for w in store.pending_wakeups(conn, agent) if w.source == "comment"]

    served = await world.service._serve_comment(world.agent(agent), wakeup)

    assert served is False
    assert len(sent(world, session_id)) == before
    assert [row["state"] for row in comment_wakeups(world, agent)] == ["pending"]


async def test_the_alert_of_a_comment_with_no_main_conversation_names_the_pr(world):
    agent = world.add_agent()
    register_pr(world, agent, None)
    queue(world, agent, "issue:1", at=NOW)
    shutil.rmtree(world.project.path)

    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)

    assert any(
        text.startswith("Comentário no PR #9 não entregue:") for text in alerts(world)
    )


# Conclude, loops -----------------------------------------------------------------------------


async def test_comment_run_conclude_announces(world):
    agent, session_id = await agent_with_pr(world)
    queue(world, agent, "issue:1", at=NOW)
    world.now = NOW + 100
    await deliver(world, dispatcher(world), agent)
    await wait_until(lambda: world.manager.get(session_id).state == "idle")

    await world.service.conclude(session_id, "Renomeei a função.")

    [announcement] = [a for a in world.announcements(agent) if a.run_id == world.run_of(session_id).id]
    assert announcement.text == "Comentário no PR #9 concluída: Renomeei a função."
    [run] = comment_runs(world, agent)
    assert world.run_of(session_id).id == run.id
    assert world.run_of(session_id).outcome == "concluded"


async def test_run_loop_ticks_and_wake_ticks_sooner(world):
    dispatch = dispatcher(world)
    ticks: list[int] = []

    async def tick() -> None:
        ticks.append(1)

    dispatch.tick = tick  # type: ignore[method-assign]
    task = asyncio.create_task(dispatch.run(interval=3600))
    try:
        await wait_until(lambda: len(ticks) == 1)  # at startup
        await asyncio.sleep(0.02)
        assert len(ticks) == 1
        dispatch.wake()
        await wait_until(lambda: len(ticks) == 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_run_loop_survives_a_failing_tick(world, caplog):
    dispatch = dispatcher(world)
    calls: list[int] = []

    async def tick() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    dispatch.tick = tick  # type: ignore[method-assign]
    task = asyncio.create_task(dispatch.run(interval=0.005))
    try:
        with caplog.at_level(logging.ERROR):
            await wait_until(lambda: len(calls) >= 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert "boom" in caplog.text


def test_local_day_start_is_midnight_of_the_clock():
    moment = datetime(2026, 10, 23, 15, 30, 12)
    assert day_start(moment.timestamp()) == int(datetime(2026, 10, 23).timestamp())
    assert day_start((moment + timedelta(days=1)).timestamp()) == int(
        datetime(2026, 10, 24).timestamp()
    )
