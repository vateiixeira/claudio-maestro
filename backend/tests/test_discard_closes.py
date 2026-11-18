"""Discarding a session closes it for real: the client (with the turn, subagents and
background work) goes away at once, instead of waiting for the idle sweep.

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


@pytest.mark.anyio
async def test_discarding_an_idle_session_closes_its_client(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="discarded")

    assert session.state == "closed"
    assert session.client is None
    assert client.closed is True
    assert session.record.mark == "discarded"


@pytest.mark.anyio
async def test_discarding_a_session_mid_turn_closes_it(make_env, env_cleanup):
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
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="discarded")
    pause.release.set()

    assert session.state == "closed"
    assert session.pending_turns == 0
    assert client.closed is True


@pytest.mark.anyio
async def test_other_marks_keep_the_client(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    await env.manager.update(session.session_id, mark="review")

    assert session.state == "idle"
    assert client.closed is False


@pytest.mark.anyio
async def test_a_discarded_session_resumes_on_the_next_message(make_env, env_cleanup):
    env, session = await connected(
        make_env, env_cleanup, lambda sid: text_turn(sid, "de volta")
    )
    await env.manager.update(session.session_id, mark="discarded")
    await env.manager.update(session.session_id, mark=None)

    await session.send("voltei")

    await wait_until(lambda: session.state == "idle")
    assert len(env.factory.clients) == 2
    assert env.factory.clients[1].sent == ["voltei"]
