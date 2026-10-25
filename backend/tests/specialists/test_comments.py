"""CommentDispatcher: the queue of PR comments becomes a turn in the agent's session. Uses the
scripted fake agent and a fake usage reading; the real SDK is never touched."""

import asyncio
import logging
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any

import pytest
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.specialists import store
from claudio_maestro.specialists.comments import (
    DISPATCH_TICK,
    MAX_TURNS_PER_DAY,
    POLL_SECONDS,
    QUIET_SECONDS,
    CommentDispatcher,
)
from claudio_maestro.specialists.service import CommentNotSentError
from specialists.test_service import (  # noqa: F401
    NOW,
    PR,
    World,
    delete_session_row,
    started,
    world,
)

pytestmark = pytest.mark.anyio

NOON = int(datetime(2026, 10, 23, 12, 0).timestamp())


class FakeUsage:
    def __init__(self, limits: list[dict[str, Any]] | None = None) -> None:
        self.limits = limits or []

    def snapshot(self) -> dict[str, Any]:
        return {"enabled": True, "error": None, "limits": self.limits}


def over(percent: int, resets_at: float | None, label: str = "5h") -> dict[str, Any]:
    return {"label": label, "percent": percent, "resets_at": resets_at}


def queue(
    world: World,
    specialist_id: int,
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
                comment_id=comment_id, pr_url=pr, specialist_id=specialist_id, author=author,
                body=body, path=path, line=line, html_url=f"{pr}#x", created_at=at,
                received_at=at, status=status, batch_at=batch_at,  # type: ignore[arg-type]
            ),
        )


def register_pr(world: World, specialist_id: int, session_id: str | None, pr: str = PR) -> None:
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.upsert_pr(
            conn, url=pr, specialist_id=specialist_id, session_id=session_id, created_at=NOW
        )


def dispatcher(world: World, usage: FakeUsage | None = None) -> CommentDispatcher:
    return CommentDispatcher(world.service, usage or FakeUsage(), world.db_path, lambda: world.now)


def statuses(world: World) -> dict[str, tuple[str, int | None]]:
    with closing(db.connect(world.db_path)) as conn:
        rows = conn.execute("SELECT comment_id, status, batch_at FROM specialist_pr_comments")
        return {row["comment_id"]: (row["status"], row["batch_at"]) for row in rows}


def sent(world: World, session_id: str) -> list[Any]:
    [client] = [c for c in world.factory.clients if c.options.session_id == session_id]
    return client.sent


def comment_runs(world: World, specialist_id: int) -> list[store.Run]:
    return [run for run in world.runs(specialist_id) if run.trigger == "comment"]


async def agent_with_pr(world: World, *, open_run: bool = False) -> tuple[int, str]:
    """An agent whose first run opened the PR; returns the agent id and that session. The
    run is over by default (the comments then open a run of their own)."""
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    if not open_run:
        with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
            store.finish_run(conn, run.id, outcome="concluded", ended_at=NOW, reason=None)
    register_pr(world, specialist_id, run.session_id)
    return specialist_id, run.session_id


def alerts(world: World) -> list[str]:
    return [n.text for n in world.notices() if n.kind == "alert"]


def test_constants():
    assert (QUIET_SECONDS, MAX_TURNS_PER_DAY, POLL_SECONDS, DISPATCH_TICK) == (60, 10, 3600, 15)


async def test_waits_quiet_window(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOW + 30
    await dispatch.tick()
    assert len(sent(world, session_id)) == before
    assert statuses(world)["issue:1"] == ("queued", None)

    world.now = NOW + 61
    await dispatch.tick()
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"] == ("delivered", NOW + 61)


async def test_a_new_comment_restarts_the_quiet_window(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    queue(world, specialist_id, "issue:2", at=NOW + 50)
    before = len(sent(world, session_id))

    world.now = NOW + 70  # 70 s after the first, 20 s after the second
    await dispatcher(world).tick()

    assert len(sent(world, session_id)) == before


async def test_groups_review_into_one_turn(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "review:1", at=NOW, body="Visão geral")
    for number in (2, 3, 4):
        queue(world, specialist_id, f"line:{number}", at=NOW + number, body=f"c{number}",
              path="app.py", line=number)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await dispatcher(world).tick()

    messages = sent(world, session_id)[before:]
    assert len(messages) == 1
    for expected in ("Visão geral", "[app.py:2] c2", "[app.py:3] c3", "[app.py:4] c4"):
        assert expected in messages[0]
    assert {status for status, _ in statuses(world).values()} == {"delivered"}
    assert len(comment_runs(world, specialist_id)) == 1


async def test_usage_over_keeps_queue_and_alerts_once(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    usage = FakeUsage([over(93, NOW + 5000)])
    dispatch = dispatcher(world, usage)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await dispatch.tick()
    await dispatch.tick()

    assert len(sent(world, session_id)) == before
    assert statuses(world)["issue:1"] == ("queued", None)
    assert alerts(world) == ["Comentário no PR #9 na fila: uso da assinatura em 93%."]

    # A new window (another renewal time) warns again; once it renews, the queue drains.
    usage.limits = [over(95, NOW + 9000)]
    await dispatch.tick()
    assert len(alerts(world)) == 2

    world.now = NOW + 9001
    await dispatch.tick()
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"][0] == "delivered"
    assert len(alerts(world)) == 2


async def test_usage_below_the_limit_delivers(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    before = len(sent(world, session_id))

    world.now = NOW + 100
    await dispatcher(world, FakeUsage([over(89, NOW + 5000)])).tick()

    assert len(sent(world, session_id)) == before + 1


async def test_daily_cap(world):
    world.now = NOON
    specialist_id, session_id = await agent_with_pr(world)
    for number in range(MAX_TURNS_PER_DAY):
        queue(world, specialist_id, f"old:{number}", at=NOON - 7000, status="delivered",
              batch_at=NOON - 3600 + number)
    queue(world, specialist_id, "issue:11", at=NOON)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOON + 100
    await dispatch.tick()
    await dispatch.tick()

    assert len(sent(world, session_id)) == before
    assert statuses(world)["issue:11"] == ("queued", None)
    assert alerts(world) == [
        "Comentário no PR #9 na fila: limite de 10 turnos por dia atingido."
    ]

    # The next day the count starts over, and the alert may come again.
    world.now = NOON + 100 + 86400
    await dispatch.tick()
    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:11"][0] == "delivered"


async def test_the_tenth_batch_of_the_day_still_goes(world):
    world.now = NOON
    specialist_id, session_id = await agent_with_pr(world)
    for number in range(MAX_TURNS_PER_DAY - 1):
        queue(world, specialist_id, f"old:{number}", at=NOON - 7000, status="delivered",
              batch_at=NOON - 3600 + number)
    queue(world, specialist_id, "issue:10", at=NOON)
    before = len(sent(world, session_id))

    world.now = NOON + 100
    await dispatcher(world).tick()

    assert len(sent(world, session_id)) == before + 1


async def test_delivers_to_origin_session_and_reopens_finished(world):
    specialist_id, session_id = await agent_with_pr(world)
    await world.manager.update(session_id, finished=True)
    assert world.record(session_id).finished is True
    queue(world, specialist_id, "line:1", at=NOW, body="renomeie isso", path="app/models.py", line=12)

    world.now = NOW + 100
    await dispatcher(world).tick()

    [run] = comment_runs(world, specialist_id)
    assert (run.session_id, run.outcome) == (session_id, "running")
    assert world.record(session_id).finished is False
    text = sent(world, session_id)[-1]
    assert text.startswith(f"Comentário de @vini no PR {PR}:\n")
    assert "[app/models.py:12] renomeie isso" in text
    assert text.endswith(
        "Resolva o que foi pedido. Não comente no GitHub; ao terminar, chame concluir com o resumo."
    )


@pytest.mark.parametrize("deleted", [True, False])
async def test_missing_session_goes_to_main(world, deleted):
    specialist_id = world.add_specialist()
    origin = world.manager.create_session(world.project, specialist_id=specialist_id).session_id
    register_pr(world, specialist_id, origin if deleted else None)
    if deleted:
        delete_session_row(world, origin)
    queue(world, specialist_id, "issue:1", at=NOW, body="e o teste?")

    world.now = NOW + 100
    await dispatcher(world).tick()

    main = world.specialist(specialist_id).main_session_id
    assert main is not None and main != origin
    text = sent(world, main)[-1]
    assert "e o teste?" in text
    assert text.endswith("Resolva o que foi pedido e responda aqui.")
    assert "concluir" not in text
    assert comment_runs(world, specialist_id) == []
    assert statuses(world)["issue:1"][0] == "delivered"


async def test_a_pr_opened_from_the_main_conversation_goes_to_it_without_a_run(world):
    specialist_id = world.add_specialist()
    main = await world.service.ensure_main(specialist_id)
    register_pr(world, specialist_id, main)
    queue(world, specialist_id, "issue:1", at=NOW)

    world.now = NOW + 100
    await dispatcher(world).tick()

    assert sent(world, main)[-1].endswith("Resolva o que foi pedido e responda aqui.")
    assert comment_runs(world, specialist_id) == []


async def test_a_comment_whose_pr_is_unknown_goes_to_main(world):
    specialist_id = world.add_specialist()
    queue(world, specialist_id, "issue:1", at=NOW)  # PR never registered (an item's link)

    world.now = NOW + 100
    await dispatcher(world).tick()

    main = world.specialist(specialist_id).main_session_id
    assert main is not None and "ajuste isso" in sent(world, main)[-1]


async def test_queue_survives_restart(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    before = len(sent(world, session_id))

    world.now = NOW + 10
    await dispatcher(world).tick()  # the quiet window has not passed
    assert len(sent(world, session_id)) == before

    # "Restart": a brand-new dispatcher reads the queue from the database.
    world.now = NOW + 3600
    await dispatcher(world).tick()

    assert len(sent(world, session_id)) == before + 1
    assert statuses(world)["issue:1"][0] == "delivered"


async def test_a_failed_delivery_stays_queued_and_the_next_tick_retries(world, caplog):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    real_send = world.manager.send
    failing = True

    async def send(session_id, text, images=None):
        if failing:
            raise CommentNotSentError("a sessão não abriu")
        return await real_send(session_id, text, images)

    world.manager.send = send
    runs_before = len(world.runs(specialist_id))
    world.now = NOW + 100
    dispatch = dispatcher(world)

    with caplog.at_level(logging.ERROR):
        await dispatch.tick()

    assert statuses(world)["issue:1"] == ("queued", None)
    assert "a sessão não abriu" in caplog.text
    assert len(world.runs(specialist_id)) == runs_before  # no orphan comment run
    assert alerts(world) == ["Comentário no PR #9 não foi entregue: a sessão não abriu"]

    # The retries every tick neither warn again nor repeat the traceback.
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await dispatch.tick()
        await dispatch.tick()
    assert len(alerts(world)) == 1
    assert "Traceback" not in caplog.text and "ainda não entregues" in caplog.text
    assert len(world.runs(specialist_id)) == runs_before

    failing = False
    await dispatch.tick()
    assert statuses(world)["issue:1"][0] == "delivered"
    assert len(comment_runs(world, specialist_id)) == 1

    # The next dispatch waits for the current turn to end.
    await wait_until(lambda: world.manager.get(session_id).state == "idle")
    # Delivered once: a later failure of the same PR warns again.
    failing = True
    queue(world, specialist_id, "issue:2", at=world.now)
    world.now += 100
    await dispatch.tick()
    assert len(alerts(world)) == 2


async def test_a_failure_in_one_pr_does_not_stop_the_others(world):
    specialist_id, session_id = await agent_with_pr(world)
    other = "https://github.com/acme/app/pull/10"
    other_session = world.manager.create_session(world.project, specialist_id=specialist_id)
    register_pr(world, specialist_id, other_session.session_id, pr=other)
    queue(world, specialist_id, "issue:1", at=NOW)
    queue(world, specialist_id, "issue:2", at=NOW, pr=other)
    real = world.service.start_comment_run

    async def start(pr, comments):
        if pr.url == PR:
            raise CommentNotSentError("falhou")
        return await real(pr, comments)

    world.service.start_comment_run = start
    world.now = NOW + 100
    await dispatcher(world).tick()

    assert statuses(world)["issue:1"][0] == "queued"
    assert statuses(world)["issue:2"][0] == "delivered"


async def test_overlapping_ticks_deliver_once(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    before = len(sent(world, session_id))
    dispatch = dispatcher(world)

    world.now = NOW + 100
    await asyncio.gather(dispatch.tick(), dispatch.tick())

    assert len(sent(world, session_id)) == before + 1
    assert len(comment_runs(world, specialist_id)) == 1


async def test_comment_run_conclude_announces(world):
    specialist_id, session_id = await agent_with_pr(world)
    queue(world, specialist_id, "issue:1", at=NOW)
    world.now = NOW + 100
    await dispatcher(world).tick()
    await wait_until(lambda: world.manager.get(session_id).state == "idle")

    await world.service.conclude(session_id, "Renomeei a função.")

    [announcement] = [a for a in world.announcements(specialist_id)]
    assert announcement.text == "Comentário no PR #9 concluída: Renomeei a função."
    [run] = comment_runs(world, specialist_id)
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
    from claudio_maestro.specialists.comments import day_start

    moment = datetime(2026, 10, 23, 15, 30, 12)
    assert day_start(moment.timestamp()) == int(datetime(2026, 10, 23).timestamp())
    assert day_start((moment + timedelta(days=1)).timestamp()) == int(
        datetime(2026, 10, 24).timestamp()
    )


async def test_two_batches_while_the_run_is_open_leave_one_open_run(world):
    specialist_id, session_id = await agent_with_pr(world, open_run=True)
    dispatch = dispatcher(world)

    queue(world, specialist_id, "issue:1", at=NOW)
    world.now = NOW + 100
    await dispatch.tick()
    queue(world, specialist_id, "issue:2", at=world.now)
    world.now += 100
    await dispatch.tick()

    assert [r.outcome for r in world.runs(specialist_id)] == ["running"]
    assert comment_runs(world, specialist_id) == []
    await wait_until(lambda: world.manager.get(session_id).state == "idle")
    await world.service.conclude(session_id, "Feito.")
    assert [r.outcome for r in world.runs(specialist_id)] == ["concluded"]


async def test_connect_failure_keeps_the_comment_queued(world):
    from claudio_maestro.agent.base import AgentError

    agent = world.add_specialist()
    register_pr(world, agent, None)
    queue(world, agent, "issue:connect", at=NOW - 120)
    world.factory.connect_error = AgentError("Falha antes de enviar")
    await dispatcher(world).tick()
    assert statuses(world)["issue:connect"] == ("queued", None)
    assert not world.factory.clients[-1].sent


async def test_restart_does_not_replay_a_comment_with_uncertain_dispatch(world):
    agent = world.add_specialist()
    register_pr(world, agent, None)
    queue(world, agent, "issue:interrupted", at=NOW - 120)
    sent_once = asyncio.Event()
    real_send = world.manager.send

    async def interrupted_send(*args, **kwargs):
        result = await real_send(*args, **kwargs)
        sent_once.set()
        await asyncio.Event().wait()
        return result

    world.manager.send = interrupted_send
    task = asyncio.create_task(dispatcher(world).tick())
    await sent_once.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    world.manager.send = real_send
    await dispatcher(world).tick()
    assert sum(len(client.sent) for client in world.factory.clients) == 1
    assert statuses(world)["issue:interrupted"][0] == "uncertain"
    assert any("confira" in notice.text.lower() for notice in world.notices())


async def test_restart_preserves_the_run_of_an_uncertain_comment_send(world):
    agent, origin = await agent_with_pr(world)
    queue(world, agent, "issue:uncertain-run", at=NOW - 120)
    reached = asyncio.Event()
    real_send = world.manager.send

    async def interrupted_send(*args, **kwargs):
        result = await real_send(*args, **kwargs)
        reached.set()
        await asyncio.Event().wait()
        return result

    world.manager.send = interrupted_send
    task = asyncio.create_task(dispatcher(world).tick())
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    run = world.run_of(origin)
    assert run.trigger == "comment"
    assert any(event["id"] == run.id for event in world.published("specialist.run"))
    await world.service.conclude(origin, "Comentário atendido")
    assert world.run_of(origin).outcome == "concluded"
    assert any("Comentário atendido" in a.text for a in world.announcements(agent))


async def test_recovery_holds_a_dispatch_reserved_before_process_exit(world):
    agent = world.add_specialist()
    register_pr(world, agent, None)
    queue(world, agent, "issue:reserved", at=NOW - 120, status="dispatching", batch_at=NOW - 10)
    await dispatcher(world).tick()
    assert statuses(world)["issue:reserved"][0] == "uncertain"
    assert not world.factory.clients
    assert any("confira" in notice.text.lower() for notice in world.notices())
