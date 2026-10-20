"""Remote Control of a session: the saved mark, the live state and the retries.

Only the scripted fake agent is used.
"""

import asyncio

import pytest
from test_controls import connected, options_events
from test_controls_refused import notice_texts, refused
from test_sessions import (  # noqa: F401
    by_session,
    env_cleanup,
    make_env,
    session_row,
    wait_until,
)

from claudio_maestro.agent import AgentError
from claudio_maestro.agent.fake import PauseStep, bridge_state_message, text_turn
from claudio_maestro.sessions import (
    REMOTE_RETRY_DELAYS,
    RemoteControlUnavailable,
    SessionRecord,
    remote_name,
)

URL = "https://claude.ai/code/session_fake"
FAILED_PREFIX = "Não foi possível ligar o Remote Control: "


def calls(client) -> list[dict]:
    return client.remote_control_calls


# Turning it on -------------------------------------------------------------


@pytest.mark.anyio
async def test_enable_with_client_calls_agent_and_saves_bridge(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    changed = await session.set_remote_control(True)

    assert changed is True
    assert calls(client)[-1] == {
        "enabled": True, "name": session.record.title, "reattach_session_id": None
    }
    assert session.record.title == "olá"
    assert session.record.remote_control is True
    assert session.record.remote_control_bridge == "cse_fake"
    assert session_row(env.db_path, session.session_id)["remote_control_bridge"] == "cse_fake"
    assert session_row(env.db_path, session.session_id)["remote_control"] == 1
    assert session.remote_state == "connecting"
    assert session.remote_url == URL
    assert session.remote_error is None
    last = options_events(env, session)[-1]
    assert last["remote_control"] is True
    assert last["remote_control_state"] == "connecting"
    assert last["remote_control_url"] == URL
    assert last["remote_control_error"] is None


@pytest.mark.anyio
async def test_enable_when_already_enabled_changes_nothing(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)

    assert await session.set_remote_control(True) is False
    assert len(calls(env.factory.clients[0])) == 1


@pytest.mark.anyio
async def test_enable_without_client_connects_with_resume_then_enables(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.close()
    assert session.client is None

    await session.set_remote_control(True)

    assert len(env.factory.clients) == 2
    fresh = env.factory.clients[1]
    assert fresh.options.resume is True
    assert fresh.connected is True
    assert calls(fresh)[-1]["enabled"] is True
    assert session.client is fresh
    assert session.remote_state == "connecting"
    assert calls(env.factory.clients[0]) == []


@pytest.mark.anyio
async def test_enable_on_finished_session_is_unavailable(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    session.save(finished=True)

    with pytest.raises(RemoteControlUnavailable, match="Reabra a sessão"):
        await session.set_remote_control(True)

    assert session.record.remote_control is False
    assert calls(env.factory.clients[0]) == []


@pytest.mark.anyio
async def test_enable_when_connect_fails_ends_failed_and_keeps_mark(make_env, env_cleanup):
    env = make_env(connect_error=AgentError("sem claude"))
    env_cleanup.append(env.manager)
    session = env.new_session()

    await session.set_remote_control(True)

    assert session.record.remote_control is True
    assert session.remote_state == "failed"
    assert session.remote_error == "sem claude"
    assert session.remote_url is None


# Live state ----------------------------------------------------------------


@pytest.mark.anyio
async def test_bridge_state_connected_sets_on(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    before = len(options_events(env, session))

    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")

    assert len(options_events(env, session)) > before
    assert options_events(env, session)[-1]["remote_control_state"] == "on"
    assert session.remote_url == URL


@pytest.mark.anyio
async def test_bridge_state_ready_sets_connecting(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")

    client.push([bridge_state_message("ready")])
    await wait_until(lambda: session.remote_state == "connecting")


@pytest.mark.anyio
async def test_unknown_bridge_state_is_ignored(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")

    client.push([bridge_state_message("something_new"), bridge_state_message("ready")])
    await wait_until(lambda: session.remote_state == "connecting")
    client.push([bridge_state_message("something_new")])
    await asyncio.sleep(0.02)

    assert session.remote_state == "connecting"


@pytest.mark.anyio
async def test_bridge_state_failed_sets_failed_with_detail(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)

    client.push([bridge_state_message("failed", detail="sem rede", failure_kind="terminal")])
    await wait_until(lambda: session.remote_state == "failed")

    assert session.remote_error == "sem rede"
    assert session.record.remote_control is True
    assert options_events(env, session)[-1]["remote_control_error"] == "sem rede"
    assert session.client is client and session.state == "idle"


@pytest.mark.anyio
async def test_bridge_policy_disabled_sets_failed(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)

    env.factory.clients[0].push([bridge_state_message("policy_disabled", detail="bloqueado")])
    await wait_until(lambda: session.remote_state == "failed")

    assert session.remote_error == "bloqueado"


@pytest.mark.anyio
async def test_bridge_state_without_mark_is_ignored(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    env.factory.clients[0].push([bridge_state_message("connected")])
    await asyncio.sleep(0.02)

    assert session.remote_state == "off"
    assert session.remote_url is None


@pytest.mark.anyio
async def test_connected_after_failure_clears_error(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    client.push([bridge_state_message("failed", detail="sem rede")])
    await wait_until(lambda: session.remote_state == "failed")

    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")

    assert session.remote_error is None


# Refusals and retries ------------------------------------------------------


@pytest.mark.anyio
async def test_refused_enable_sets_failed_notice_and_keeps_mark(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_remote_control_error = refused("Remote Control is disabled by your organization")

    await session.set_remote_control(True)

    assert session.record.remote_control is True
    assert session.remote_state == "failed"
    assert session.remote_error == "Remote Control is disabled by your organization"
    assert session.remote_url is None
    warnings = [text for level, text in notice_texts(session) if level == "warning"]
    assert warnings == [FAILED_PREFIX + "Remote Control is disabled by your organization"]
    assert session.client is client and session.state == "idle"
    assert options_events(env, session)[-1]["remote_control_state"] == "failed"


@pytest.mark.anyio
async def test_failure_that_kills_the_client_fails_the_session(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_remote_control_error = AgentError("pipe quebrado")

    await session.set_remote_control(True)

    assert session.client is None and session.state == "error"
    assert session.record.remote_control is True
    assert session.remote_state == "off"


@pytest.mark.anyio
async def test_refused_reattach_retries_without_reattach(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.save(remote_control_bridge="cse_old")
    client.set_remote_control_error_once = refused("bridge session expired")

    await session.set_remote_control(True)

    assert [call["reattach_session_id"] for call in calls(client)] == ["cse_old", None]
    assert session.record.remote_control_bridge == "cse_fake"
    assert session_row(env.db_path, session.session_id)["remote_control_bridge"] == "cse_fake"
    assert session.remote_state == "connecting"
    assert not [text for level, text in notice_texts(session) if level == "warning"]


@pytest.mark.anyio
async def test_reattach_is_sent_and_kept_when_accepted(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.save(remote_control_bridge="cse_old")

    await session.set_remote_control(True)

    assert [call["reattach_session_id"] for call in calls(client)] == ["cse_old"]
    assert session.record.remote_control_bridge == "cse_old"


@pytest.mark.anyio
async def test_refusal_without_reattach_is_not_retried_at_once(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_remote_control_error = refused("no")

    await session.set_remote_control(True)

    assert len(calls(client)) == 1


@pytest.mark.anyio
async def test_retry_after_failure_succeeds(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error_once = refused("sem rede")

    await session.set_remote_control(True)
    assert session.remote_state == "failed"

    await wait_until(lambda: session.remote_state == "connecting" and len(calls(client)) == 2)

    assert session.remote_error is None
    assert session.remote_url == URL
    assert session.record.remote_control_bridge == "cse_fake"


@pytest.mark.anyio
async def test_retry_delays_grow_and_the_last_repeats(make_env, env_cleanup):
    assert REMOTE_RETRY_DELAYS == (30, 60, 120, 300, 600)
    env, session = await connected(make_env, env_cleanup)

    assert session.remote_retry_delays == REMOTE_RETRY_DELAYS
    assert [session.remote_retry_delay(n) for n in range(7)] == [30, 60, 120, 300, 600, 600, 600]


@pytest.mark.anyio
async def test_notice_is_shown_once_across_retries(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error = refused("sem rede")

    await session.set_remote_control(True)
    await wait_until(lambda: len(calls(client)) >= 4)

    warnings = [text for level, text in notice_texts(session) if level == "warning"]
    assert warnings == [FAILED_PREFIX + "sem rede"]


@pytest.mark.anyio
async def test_bridge_failure_schedules_a_retry(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    await session.set_remote_control(True)

    client.push([bridge_state_message("failed", detail="queda")])
    await wait_until(lambda: len(calls(client)) == 2)
    await wait_until(lambda: session.remote_state == "connecting")

    assert session.remote_error is None


@pytest.mark.anyio
async def test_close_cancels_the_retry_and_turns_state_off(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_remote_control_error = refused("sem rede")
    await session.set_remote_control(True)
    task = session._remote_retry_task
    assert task is not None and not task.done()

    await session.close()

    await asyncio.sleep(0)
    assert task.cancelled()
    assert session.remote_state == "off" and session.remote_url is None
    assert session.record.remote_control is True


@pytest.mark.anyio
async def test_detach_cancels_the_retry(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_remote_control_error = refused("sem rede")
    await session.set_remote_control(True)
    task = session._remote_retry_task
    assert task is not None

    await session.detach()

    assert task.cancelled() or task.done()


@pytest.mark.anyio
async def test_close_cancels_a_retry_that_is_calling_the_agent(make_env, env_cleanup):
    """The retry task enables Remote Control itself: it must stay reachable meanwhile."""
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error_once = refused("sem rede")
    await session.set_remote_control(True)
    client.remote_control_pause = PauseStep()
    await asyncio.wait_for(client.remote_control_pause.reached.wait(), 1)
    task = session._remote_retry_task
    try:
        assert task is not None and not task.done()

        await session.close()

        await asyncio.sleep(0)
        assert task.cancelled()
    finally:
        client.remote_control_pause.release.set()  # never leave the lock held


@pytest.mark.anyio
async def test_disable_cancels_a_retry_that_is_calling_the_agent(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error_once = refused("sem rede")
    await session.set_remote_control(True)
    client.remote_control_pause = PauseStep()
    await asyncio.wait_for(client.remote_control_pause.reached.wait(), 1)
    task = session._remote_retry_task
    try:
        assert task is not None and not task.done()

        await asyncio.wait_for(session.set_remote_control(False), 1)

        await asyncio.sleep(0)
        assert task.cancelled()
    finally:
        client.remote_control_pause.release.set()


@pytest.mark.anyio
async def test_connected_does_not_cancel_a_retry_that_is_calling_the_agent(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error_once = refused("sem rede")
    await session.set_remote_control(True)
    client.remote_control_pause = PauseStep()
    await asyncio.wait_for(client.remote_control_pause.reached.wait(), 1)
    task = session._remote_retry_task

    client.push([bridge_state_message("connected")])
    await wait_until(lambda: session.remote_state == "on")
    client.remote_control_pause.release.set()
    await asyncio.wait([task], timeout=1)

    assert not task.cancelled()
    assert session.remote_state == "on"


@pytest.mark.anyio
async def test_unexpected_error_in_a_retry_is_logged_not_left_in_the_task(
    make_env, env_cleanup, caplog
):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    client.set_remote_control_error_once = refused("sem rede")
    await session.set_remote_control(True)
    first = session._remote_retry_task
    client.set_remote_control_error = RuntimeError("boom")  # not an AgentError
    session.remote_retry_delays = (60,)

    await asyncio.wait([first], timeout=1)

    assert first.done() and not first.cancelled()
    assert first.exception() is None
    assert "boom" in caplog.text
    assert session.client is client and session.state == "idle"
    assert session.remote_state == "failed"


@pytest.mark.anyio
async def test_refused_reattach_forgets_the_old_bridge_even_if_the_second_call_fails(
    make_env, env_cleanup
):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    session.save(remote_control_bridge="cse_old")
    client.set_remote_control_error_once = refused("bridge session expired")
    client.set_remote_control_error = refused("sem rede")

    await session.set_remote_control(True)

    assert [call["reattach_session_id"] for call in calls(client)][:2] == ["cse_old", None]
    assert session.record.remote_control_bridge is None
    assert session_row(env.db_path, session.session_id)["remote_control_bridge"] is None
    await wait_until(lambda: len(calls(client)) >= 4)
    # Later attempts make one call each, without the dead bridge.
    assert all(call["reattach_session_id"] is None for call in calls(client)[1:])


@pytest.mark.anyio
async def test_policy_disabled_is_not_retried_automatically(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    await session.set_remote_control(True)

    client.push([bridge_state_message("policy_disabled", detail="bloqueado")])
    await wait_until(lambda: session.remote_state == "failed")
    await asyncio.sleep(0.05)

    assert session.remote_state == "failed"
    assert session.remote_error == "bloqueado"
    assert len(calls(client)) == 1
    assert session._remote_retry_task is None or session._remote_retry_task.done()


@pytest.mark.anyio
async def test_policy_disabled_drops_a_retry_already_waiting(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.set_remote_control_error = refused("sem rede")
    await session.set_remote_control(True)
    task = session._remote_retry_task
    assert task is not None and not task.done()

    client.push([bridge_state_message("policy_disabled")])
    await wait_until(lambda: session.remote_error and "política" in session.remote_error)
    await asyncio.sleep(0)

    assert task.cancelled()
    assert session.remote_state == "failed"


@pytest.mark.anyio
async def test_policy_disabled_can_be_retried_by_the_user(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    client.push([bridge_state_message("policy_disabled")])
    await wait_until(lambda: session.remote_state == "failed")

    await session.set_remote_control(False)
    await session.set_remote_control(True)

    assert session.remote_state == "connecting"
    assert [call["enabled"] for call in calls(client)] == [True, False, True]


@pytest.mark.anyio
async def test_failed_bridge_with_any_kind_keeps_retrying(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    session.remote_retry_delays = (0,)
    await session.set_remote_control(True)

    client.push([bridge_state_message("failed", detail="x", failure_kind="terminal")])

    await wait_until(lambda: len(calls(client)) == 2)


# Turning it off ------------------------------------------------------------


@pytest.mark.anyio
async def test_disable_sends_false_and_clears_bridge(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)

    changed = await session.set_remote_control(False)

    assert changed is True
    assert calls(client)[-1]["enabled"] is False
    assert session.record.remote_control is False
    assert session.record.remote_control_bridge is None
    assert session_row(env.db_path, session.session_id)["remote_control_bridge"] is None
    assert session_row(env.db_path, session.session_id)["remote_control"] == 0
    assert session.remote_state == "off"
    assert session.remote_url is None
    last = options_events(env, session)[-1]
    assert last["remote_control"] is False and last["remote_control_state"] == "off"


@pytest.mark.anyio
async def test_disable_cancels_the_retry(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    env.factory.clients[0].set_remote_control_error = refused("sem rede")
    await session.set_remote_control(True)
    task = session._remote_retry_task
    assert task is not None

    await session.set_remote_control(False)
    await asyncio.sleep(0)

    assert task.cancelled()
    assert session.remote_state == "off"


@pytest.mark.anyio
async def test_disable_without_client_only_clears_the_mark(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    await session.set_remote_control(True)
    await session.close()
    client = env.factory.clients[0]
    sent = len(calls(client))

    await session.set_remote_control(False)

    assert session.record.remote_control is False
    assert len(calls(client)) == sent
    assert len(env.factory.clients) == 1


@pytest.mark.anyio
async def test_disable_when_off_changes_nothing(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    assert await session.set_remote_control(False) is False
    assert calls(env.factory.clients[0]) == []


@pytest.mark.anyio
async def test_refused_disable_leaves_the_mark_off_and_warns(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    await session.set_remote_control(True)
    client.set_remote_control_error = refused("não deu")

    await session.set_remote_control(False)

    assert session.record.remote_control is False
    assert session.remote_state == "off"
    assert session.client is client
    assert ("warning", "Não foi possível desligar o Remote Control: não deu") in notice_texts(
        session
    )


@pytest.mark.anyio
async def test_disable_while_enabling_ends_off(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.remote_control_pause = PauseStep()

    enabling = asyncio.create_task(session.set_remote_control(True))
    await asyncio.wait_for(client.remote_control_pause.reached.wait(), 1)
    disabling = asyncio.create_task(session.set_remote_control(False))
    await wait_until(lambda: session.record.remote_control is False)
    client.remote_control_pause.release.set()
    await asyncio.wait_for(asyncio.gather(enabling, disabling), 1)

    assert session.record.remote_control is False
    assert session.remote_state == "off"
    assert session.remote_url is None
    assert session.record.remote_control_bridge is None
    assert [call["enabled"] for call in calls(client)] == [True, False]
    assert options_events(env, session)[-1]["remote_control_state"] == "off"


@pytest.mark.anyio
async def test_enable_again_while_disable_waits_keeps_it_on(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]
    client.remote_control_pause = PauseStep()
    enabling = asyncio.create_task(session.set_remote_control(True))
    await asyncio.wait_for(client.remote_control_pause.reached.wait(), 1)
    disabling = asyncio.create_task(session.set_remote_control(False))
    await wait_until(lambda: session.record.remote_control is False)
    again = asyncio.create_task(session.set_remote_control(True))
    await wait_until(lambda: session.record.remote_control is True)
    client.remote_control_pause.release.set()
    await asyncio.wait_for(asyncio.gather(enabling, disabling, again), 1)

    assert session.record.remote_control is True
    assert session.remote_state == "connecting"
    assert session.remote_url == URL
    assert calls(client)[-1]["enabled"] is True


# Name ----------------------------------------------------------------------


def record(**fields) -> SessionRecord:
    base = {
        "session_id": "s", "project_id": 1, "cwd": "/p", "title": "", "created_at": 0,
        "last_activity_at": 0,
    }
    return SessionRecord(**{**base, **fields})


def test_remote_name_is_one_line_and_short():
    assert remote_name(record(title="a\nb")) == "a b"
    assert remote_name(record(title="  muitos   espaços\t aqui ")) == "muitos espaços aqui"
    assert len(remote_name(record(title="x" * 100))) == 60
    assert remote_name(record(title="")) == "Cláudio Maestro"
    assert remote_name(record(title="", first_prompt="")) == "Cláudio Maestro"


def test_remote_name_falls_back_to_the_first_prompt():
    assert remote_name(record(title="Nova sessão", first_prompt="conserta\no teste")) == (
        "conserta o teste"
    )
    assert remote_name(record(title="Nova sessão")) == "Cláudio Maestro"


# A session without a turn still works --------------------------------------


@pytest.mark.anyio
async def test_remote_control_does_not_disturb_turns(make_env, env_cleanup):
    script, ids = by_session(lambda sid: text_turn(sid, "oi"), lambda sid: text_turn(sid, "dois"))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)
    await session.send("um")
    await wait_until(lambda: session.state == "idle")
    await session.set_remote_control(True)
    env.factory.clients[0].push([bridge_state_message("connected")])

    await session.send("dois")
    await wait_until(lambda: session.state == "idle" and session.pending_turns == 0)

    assert session.remote_state == "on"
