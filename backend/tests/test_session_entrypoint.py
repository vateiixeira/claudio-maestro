"""Active sessions mark their transcripts with the app's own entrypoint, so the
editor extension lists them (it hides the SDK defaults `sdk-py`, `sdk-ts`, `sdk-cli`)."""

import pytest
from test_sessions import (  # noqa: F401
    by_session,
    env_cleanup,
    make_env,
    wait_until,
)

from claudio_maestro.agent.fake import text_turn
from claudio_maestro.sessions import SESSION_ENTRYPOINT


def test_session_entrypoint_is_not_hidden_by_the_editor_extension():
    assert SESSION_ENTRYPOINT == "claudio-maestro"
    assert SESSION_ENTRYPOINT not in {"sdk-cli", "sdk-ts", "sdk-py", "cli"}


@pytest.mark.anyio
async def test_new_and_resumed_clients_carry_the_session_entrypoint(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("olá")
    await wait_until(lambda: session.state == "idle")

    # An effort change reconnects the client with resume.
    await env.manager.update(session.session_id, effort="high")
    await wait_until(lambda: len(env.factory.clients) == 2 and session.state == "idle")

    first, second = env.factory.clients
    assert first.options.resume is False
    assert second.options.resume is True
    assert first.options.entrypoint == SESSION_ENTRYPOINT
    assert second.options.entrypoint == SESSION_ENTRYPOINT
