"""A model or mode change the agent refuses does not end the session.

Only the scripted fake agent is used.
"""

import pytest

from test_controls import connected, options_events
from test_sessions import by_session, make_env, env_cleanup, wait_until  # noqa: F401
from claudio_maestro.agent import AgentError
from claudio_maestro.agent.fake import text_turn

AUTO_UNAVAILABLE = "Cannot set permission mode to auto: auto mode unavailable for this model"
AUTO_MESSAGE = "O modo Automático não está disponível para este modelo."


def refused(text: str) -> AgentError:
    return AgentError(text, refused=True)


def notice_texts(session) -> list[tuple[str, str]]:
    return [
        (item["level"], item["text"])
        for item in session.snapshot()["items"]
        if item["type"] == "notice"
    ]


@pytest.mark.anyio
async def test_auto_mode_refused_keeps_session_and_reverts(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_permission_mode_error = refused(AUTO_UNAVAILABLE)

    summary = await env.manager.update(session.session_id, permission_mode="auto")

    assert summary["permission_mode"] == "default"
    assert session.record.permission_mode == "default"
    assert session.client is client and session.state == "idle"
    assert client.closed is False
    assert options_events(env, session)[-1]["permission_mode"] == "default"
    assert ("warning", AUTO_MESSAGE) in notice_texts(session)


@pytest.mark.anyio
async def test_refused_mode_keeps_previous_non_default_mode(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await env.manager.update(session.session_id, permission_mode="plan")
    env.factory.clients[0].set_permission_mode_error = refused("boom")

    summary = await env.manager.update(session.session_id, permission_mode="acceptEdits")

    assert summary["permission_mode"] == "plan"
    assert session.state == "idle"


@pytest.mark.anyio
async def test_other_mode_refusal_shows_the_reason(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_permission_mode_error = refused("Mode not allowed here")

    await env.manager.update(session.session_id, permission_mode="plan")

    assert session.record.permission_mode == "default"
    assert ("warning", "Não foi possível trocar o modo: Mode not allowed here") in notice_texts(
        session
    )


@pytest.mark.anyio
async def test_model_refused_keeps_session_and_reverts(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await env.manager.update(session.session_id, model="sonnet")
    client = env.factory.clients[0]
    client.set_model_error = refused("Unknown model")

    summary = await env.manager.update(session.session_id, model="opus")

    assert summary["model"] == "sonnet"
    assert session.client is client and session.state == "idle"
    assert options_events(env, session)[-1]["model"] == "sonnet"
    assert ("warning", "Não foi possível trocar o modelo: Unknown model") in notice_texts(session)


@pytest.mark.anyio
async def test_refused_model_leaves_no_local_echo_expectation(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_model_error = refused("Unknown model")

    await env.manager.update(session.session_id, model="opus")

    assert session.builder._expected_echoes.get("Set model to ", 0) == 0


@pytest.mark.anyio
async def test_refused_mode_does_not_undo_the_model_change(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_permission_mode_error = refused(AUTO_UNAVAILABLE)

    summary = await env.manager.update(
        session.session_id, model="opus", permission_mode="auto"
    )

    assert summary["model"] == "opus"
    assert summary["permission_mode"] == "default"
    assert client.model_calls == ["opus"]
    assert session.state == "idle"


@pytest.mark.anyio
async def test_refused_model_still_applies_the_mode(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_model_error = refused("Unknown model")

    summary = await env.manager.update(
        session.session_id, model="opus", permission_mode="plan"
    )

    assert summary["model"] != "opus"
    assert summary["permission_mode"] == "plan"
    assert client.permission_mode_calls == ["plan"]


@pytest.mark.anyio
async def test_dead_client_on_mode_change_still_fails_the_session(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_permission_mode_error = AgentError("O agente morreu.")

    await env.manager.update(session.session_id, permission_mode="plan")

    assert session.client is None
    assert session.state == "error"
    assert ("error", "O agente morreu.") in notice_texts(session)


@pytest.mark.anyio
async def test_dead_client_on_model_change_still_fails_the_session(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_model_error = AgentError("O agente morreu.")

    await env.manager.update(session.session_id, model="opus")

    assert session.client is None
    assert session.state == "error"


# Reconcile after connecting -------------------------------------------------


@pytest.mark.anyio
async def test_reconcile_refused_mode_reverts_and_keeps_client(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_permission_mode_error = refused(AUTO_UNAVAILABLE)
    # The user chose "auto" while the client was connecting with "default".
    session.save(permission_mode="auto")

    ok = await session._reconcile_options(client, (session.record.model, "default"))

    assert ok is True
    assert session.record.permission_mode == "default"
    assert session.client is client and session.state == "idle"
    assert options_events(env, session)[-1]["permission_mode"] == "default"
    assert ("warning", AUTO_MESSAGE) in notice_texts(session)


@pytest.mark.anyio
async def test_reconcile_refused_model_reverts_and_still_applies_mode(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_model_error = refused("Unknown model")
    used_model = session.record.model
    session.save(model="opus", permission_mode="plan")

    ok = await session._reconcile_options(client, (used_model, "default"))

    assert ok is True
    assert session.record.model == used_model
    assert session.record.permission_mode == "plan"
    assert client.permission_mode_calls == ["plan"]
    assert ("warning", "Não foi possível trocar o modelo: Unknown model") in notice_texts(session)


@pytest.mark.anyio
async def test_reconcile_dead_client_still_fails_the_session(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_permission_mode_error = AgentError("O agente morreu.")
    session.save(permission_mode="plan")

    ok = await session._reconcile_options(client, (session.record.model, "default"))

    assert ok is False
    assert session.client is None and session.state == "error"
