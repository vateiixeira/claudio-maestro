"""Discarding a session closes it for real after a grace period: the client (with the
turn, subagents and background work) and the terminal go away at the first sweep past
the grace, instead of living on until the idle sweep (which never takes a busy session
nor a terminal).

Only the scripted fake agent is used.
"""

import asyncio

import pytest
from test_controls import connected
from test_sessions import (  # noqa: F401
    by_session,
    env_cleanup,
    make_env,
    wait_until,
)

from claudio_maestro.agent.fake import PauseStep, text_turn
from claudio_maestro.sessions import DEFAULT_DISCARD_GRACE


def expire(env) -> None:
    """Every discard already counts as older than the grace."""
    env.manager._discard_grace = 0


async def paused(make_env, env_cleanup):
    """Env and session in the middle of a turn held by the returned pause."""
    pause = PauseStep()

    def turn(sid):
        messages = text_turn(sid, "resposta")
        return [*messages[:2], pause, *messages[2:]]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await asyncio.wait_for(pause.reached.wait(), 1)
    assert session.state == "running"
    return env, session, pause


def test_the_grace_is_one_hour():
    assert DEFAULT_DISCARD_GRACE == 60 * 60


@pytest.mark.anyio
async def test_discarding_keeps_the_session_open_during_the_grace(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="discarded")
    await env.manager.close_discarded()

    assert session.state == "idle"
    assert client.closed is False


@pytest.mark.anyio
async def test_a_discarded_idle_session_closes_after_the_grace(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await env.manager.update(session.session_id, mark="discarded")

    expire(env)
    await env.manager.close_discarded()

    assert session.state == "closed"
    assert client.closed is True
    assert session.record.mark == "discarded"


@pytest.mark.anyio
async def test_a_discarded_session_mid_turn_keeps_working_then_closes(make_env, env_cleanup):
    env, session, pause = await paused(make_env, env_cleanup)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="discarded")
    await env.manager.close_discarded()
    assert session.state == "running"

    expire(env)
    await env.manager.close_discarded()
    pause.release.set()

    assert session.state == "closed"
    assert session.pending_turns == 0
    assert client.closed is True


@pytest.mark.anyio
async def test_taking_the_mark_off_cancels_the_close(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await env.manager.update(session.session_id, mark="discarded")
    await env.manager.update(session.session_id, mark=None)

    expire(env)
    await env.manager.close_discarded()

    assert session.state == "idle"
    assert env.factory.clients[0].closed is False


@pytest.mark.anyio
async def test_a_message_to_a_discarded_session_cancels_the_close(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de volta")
    )
    await env.manager.update(session.session_id, mark="discarded")

    await session.send("voltei")  # takes the mark off on its own
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)
    expire(env)
    await env.manager.close_discarded()

    assert session.record.mark is None
    assert session.state == "idle"


@pytest.mark.anyio
async def test_other_marks_never_close(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    await env.manager.update(session.session_id, mark="review")
    expire(env)
    await env.manager.close_discarded()

    assert session.state == "idle"
    assert env.factory.clients[0].closed is False


@pytest.mark.anyio
async def test_a_session_found_discarded_counts_from_the_first_sweep(make_env, env_cleanup):
    # After a backend restart the time of the discard is gone: the grace starts again.
    env, session = await connected(make_env, env_cleanup)
    session.save(mark="discarded")

    await env.manager.close_discarded()
    assert session.state == "idle"

    expire(env)
    await env.manager.close_discarded()
    assert session.state == "closed"


@pytest.mark.anyio
async def test_the_close_is_tried_again_while_the_session_is_busy(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await env.manager.update(session.session_id, mark="discarded")
    expire(env)

    await session._lock.acquire()  # a send or connect in progress
    await env.manager.close_discarded()
    assert session.state == "idle"

    session._lock.release()
    await env.manager.close_discarded()
    assert session.state == "closed"


@pytest.mark.anyio
async def test_a_discarded_session_resumes_on_the_next_message(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de volta")
    )
    await env.manager.update(session.session_id, mark="discarded")
    expire(env)
    await env.manager.close_discarded()
    await env.manager.update(session.session_id, mark=None)

    await session.send("voltei")

    await wait_until(lambda: session.state == "idle")
    assert len(env.factory.clients) == 2
    assert env.factory.clients[1].sent == ["voltei"]


@pytest.mark.anyio
async def test_the_agents_hook_runs_at_the_discard_and_the_terminal_at_the_close(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup)
    closed_terminals: list[str] = []
    discarded: list[str] = []

    async def close_terminal(session_id: str) -> None:
        closed_terminals.append(session_id)

    async def on_discarded(session_id: str) -> None:
        discarded.append(session_id)

    env.manager._close_terminal = close_terminal
    env.manager._on_discarded = on_discarded
    await env.manager.update(session.session_id, mark="discarded")
    await env.manager.update(session.session_id, mark="discarded")  # no change: no call
    await env.manager.close_discarded()
    assert (closed_terminals, discarded) == ([], [session.session_id])

    expire(env)
    await env.manager.close_discarded()
    await env.manager.close_discarded()  # once only

    assert closed_terminals == [session.session_id]
    assert discarded == [session.session_id]


@pytest.mark.anyio
async def test_a_failing_agents_hook_does_not_stop_the_discard(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    async def boom(session_id: str) -> None:
        raise RuntimeError("falhou")

    env.manager._on_discarded = boom
    await env.manager.update(session.session_id, mark="discarded")

    assert session.record.mark == "discarded"
    expire(env)
    await env.manager.close_discarded()
    assert session.state == "closed"


@pytest.mark.anyio
async def test_the_idle_sweep_closes_discarded_sessions_even_if_that_fails(
    make_env, env_cleanup, monkeypatch
):
    env, _session = await connected(make_env, env_cleanup)
    calls: list[str] = []

    async def discarded_boom() -> None:
        calls.append("discarded")
        raise RuntimeError("falhou")

    async def idle() -> None:
        calls.append("idle")

    monkeypatch.setattr(env.manager, "close_discarded", discarded_boom)
    monkeypatch.setattr(env.manager, "close_idle", idle)
    sweep = asyncio.create_task(env.manager.run_idle_sweep(0.01))
    try:
        await wait_until(lambda: calls[:2] == ["discarded", "idle"])
    finally:
        sweep.cancel()


@pytest.mark.anyio
async def test_a_closed_and_forgotten_discarded_session_still_loses_its_terminal(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup)
    sid = session.session_id
    closed_terminals: list[str] = []

    async def close_terminal(session_id: str) -> None:
        closed_terminals.append(session_id)

    env.manager._close_terminal = close_terminal
    await env.manager.update(sid, mark="discarded")
    await session.close()
    env.manager.forget_closed()
    assert sid not in env.manager.active_ids()

    expire(env)
    await env.manager.close_discarded()

    assert closed_terminals == [sid]
