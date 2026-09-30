"""Fixes from the deep review of marco 5: modes, subagents, models, options, images.

Only the scripted fake agent is used.
"""

import asyncio
import base64

import pytest
from claude_agent_sdk import ToolUseBlock

from test_controls import PLAN, connected, options_events, prompt_turn
from test_sessions import by_session, make_env, env_cleanup, session_row, wait_until  # noqa: F401
from vibing.agent.base import AgentOptions
from vibing.agent.fake import (
    DEFAULT_SERVER_MODELS,
    FakeAgentFactory,
    PauseStep,
    background_tasks_changed_message,
    init_message,
    response_messages,
    result_message,
    task_notification_message,
    task_started_message,
    text_turn,
)
from vibing.agent.sdk_client import build_sdk_options
from vibing.conversation import SUBAGENT_MAX_SECONDS
from vibing.sessions import InvalidDecisionError, InvalidImageError


# Modes ---------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["auto", "dontAsk"])
async def test_auto_and_dont_ask_modes_are_accepted(make_env, env_cleanup, mode):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    summary = await env.manager.update(session.session_id, permission_mode=mode)

    assert summary["permission_mode"] == mode


@pytest.mark.anyio
async def test_init_with_auto_mode_is_saved(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: [init_message(sid, permission_mode="auto"), *text_turn(sid, "ok")[1:]])
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("oi")
    await wait_until(lambda: session.state == "idle")

    assert session.record.permission_mode == "auto"


@pytest.mark.anyio
@pytest.mark.parametrize("model", ["opus[1m]", "claude-opus-5-5", "a" * 100])
async def test_valid_models_are_accepted(make_env, env_cleanup, model):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    assert (await env.manager.update(session.session_id, model=model))["model"] == model


@pytest.mark.anyio
@pytest.mark.parametrize("model", ["opus 1", "x;rm", "a" * 101, "ópus"])
async def test_invalid_models_are_refused(make_env, env_cleanup, model):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()

    with pytest.raises(InvalidDecisionError):
        await env.manager.update(session.session_id, model=model)


# Plans ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_approving_plan_switches_to_default_mode(make_env, env_cleanup):
    env, session, data = await prompt_turn(make_env, env_cleanup, "ExitPlanMode", PLAN)
    session.save(permission_mode="plan")

    session.resolve_prompt(data["prompt_id"], "approve")

    assert session.record.permission_mode == "default"
    assert session_row(env.db_path, session.session_id)["permission_mode"] == "default"
    assert options_events(env, session)[-1]["permission_mode"] == "default"
    await wait_until(lambda: session.state == "idle")


# Options changed while connecting --------------------------------------------


@pytest.mark.anyio
async def test_options_changed_during_connect_are_applied(make_env, env_cleanup):
    gate = asyncio.Event()
    reached = asyncio.Event()
    script, ids = by_session(lambda sid: text_turn(sid, "oi"))
    factory = FakeAgentFactory(script=script)
    original = factory.__call__

    class SlowFactory:
        clients = factory.clients

        def __call__(self, options: AgentOptions):
            client = original(options)
            connect = client.connect

            async def slow_connect():
                reached.set()
                await gate.wait()
                await connect()

            client.connect = slow_connect
            return client

    env = make_env(factory=SlowFactory())
    env_cleanup.append(env.manager)
    session = env.new_session()
    ids.append(session.session_id)

    send = asyncio.create_task(session.send("olá"))
    await reached.wait()
    await env.manager.update(session.session_id, model="opus", permission_mode="acceptEdits")
    gate.set()
    await send
    await wait_until(lambda: session.state == "idle")

    client = factory.clients[0]
    assert client.model_calls == ["opus"]
    assert client.permission_mode_calls == ["acceptEdits"]


# Subagents -----------------------------------------------------------------


def background_agent(sid: str) -> list:
    return [
        init_message(sid),
        *response_messages(
            sid,
            [ToolUseBlock(id="toolu_agent", name="Agent",
                          input={"description": "Explorar", "subagent_type": "Explore",
                                 "prompt": "olhe"})],
            stop_reason="tool_use",
        ),
        task_started_message(sid, "task-1", "toolu_agent"),
        result_message(sid),
    ]


async def with_background_agent(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, background_agent)
    await session.send("rode em segundo plano")
    await wait_until(lambda: session.state == "idle" and session.subagents_running)
    return env, session


@pytest.mark.anyio
async def test_running_subagent_keeps_client_open_when_idle(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    env.manager._idle_timeout = 0

    await env.manager.close_idle()

    assert session.client is not None
    assert not env.factory.clients[0].closed


@pytest.mark.anyio
async def test_effort_waits_for_running_subagent(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id

    summary = await env.manager.update(sid, effort="high")
    await asyncio.sleep(0.02)
    assert summary["effort_pending"] is True
    assert len(env.factory.clients) == 1

    pause = PauseStep()
    turn = text_turn(sid, "o subagente terminou")
    client.push([task_notification_message(sid, "task-1", "toolu_agent"),
                 init_message(sid), turn[2], pause, *turn[3:-1], turn[-1]])
    await asyncio.wait_for(pause.reached.wait(), 2)
    await asyncio.sleep(0.02)
    # Subagent done, but the autonomous turn is still running: no reconnect yet.
    assert len(env.factory.clients) == 1
    assert not client.closed

    pause.release.set()
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    assert env.factory.clients[1].options.effort == "high"
    texts = [i["text"] for i in session.snapshot()["items"] if i["type"] == "text"]
    assert "o subagente terminou" in texts


@pytest.mark.anyio
async def test_close_marks_running_subagents_stopped(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)

    await session.close()

    [tool] = [i for i in session.snapshot()["items"] if i["type"] == "tool"]
    assert tool["subagent"]["status"] == "stopped"
    upserts = env.recorder.of(session.session_id, "item.upsert")
    assert upserts[-1]["data"]["subagent"]["status"] == "stopped"
    assert not session.subagents_running


@pytest.mark.anyio
async def test_failure_marks_running_subagents_stopped(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)

    await session._fail("caiu")

    [tool] = [i for i in session.snapshot()["items"] if i["type"] == "tool"]
    assert tool["subagent"]["status"] == "stopped"


# Display state with a background subagent ------------------------------------


def _updates(env, sid):
    return [e["data"] for e in env.recorder.of(sid, "session.updated")]


@pytest.mark.anyio
async def test_idle_with_background_subagent_shows_as_running(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    sid = session.session_id

    summary = env.manager.summary(sid)
    assert summary["state"] == "idle"
    assert summary["display_state"] == "running"
    assert summary["subagents_running"] is True
    last = _updates(env, sid)[-1]
    assert last["display_state"] == "running"
    assert last["subagents_running"] is True


@pytest.mark.anyio
async def test_subagent_end_announces_waiting(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id
    before = len(_updates(env, sid))

    turn = text_turn(sid, "o subagente terminou")
    client.push([task_notification_message(sid, "task-1", "toolu_agent"), init_message(sid), *turn[2:]])
    await wait_until(lambda: session.state == "idle" and not session.subagents_running)
    await asyncio.sleep(0.02)

    assert env.manager.summary(sid)["display_state"] == "waiting"
    later = _updates(env, sid)[before:]
    assert any(u["subagents_running"] is False for u in later)
    assert later[-1]["display_state"] == "waiting"
    assert later[-1]["subagents_running"] is False


@pytest.mark.anyio
async def test_background_tasks_cleared_announces_without_a_turn(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id
    before = len(_updates(env, sid))

    await session.stop_subagents()
    client.push([background_tasks_changed_message(sid, [])])
    await wait_until(lambda: not session.subagents_running)
    await asyncio.sleep(0.02)

    later = _updates(env, sid)[before:]
    assert len(later) == 1
    assert later[0]["state"] == "idle"
    assert later[0]["display_state"] == "waiting"
    assert later[0]["subagents_running"] is False


@pytest.mark.anyio
async def test_close_announces_subagents_stopped(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    sid = session.session_id
    before = len(_updates(env, sid))

    await session.close()

    later = _updates(env, sid)[before:]
    assert later, "close() must announce the session"
    assert later[-1]["display_state"] != "running"
    assert later[-1]["subagents_running"] is False


@pytest.mark.anyio
async def test_expired_subagent_is_announced_by_the_idle_sweep(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    sid = session.session_id
    before = len(_updates(env, sid))

    for key in session.builder._subagent_started:
        session.builder._subagent_started[key] -= SUBAGENT_MAX_SECONDS + 1
    assert not session.subagents_running
    await env.manager.close_idle()

    later = _updates(env, sid)[before:]
    assert len(later) == 1
    assert later[0]["display_state"] == "waiting"
    assert later[0]["subagents_running"] is False
    assert session.client is not None  # the sweep only announced; idle timeout not reached


# Models --------------------------------------------------------------------


@pytest.mark.anyio
async def test_models_updated_event_is_published_once(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)

    events = [e for e in env.recorder.envelopes if e["type"] == "models.updated"]
    assert len(events) == 1
    assert events[0]["session_id"] is None and events[0]["seq"] == 0
    assert [m["value"] for m in events[0]["data"]["models"]] == [
        m["value"] for m in DEFAULT_SERVER_MODELS]

    await session.close()
    await session.send("de novo")
    await wait_until(lambda: len(env.factory.clients) == 2)
    assert len([e for e in env.recorder.envelopes if e["type"] == "models.updated"]) == 1


# Images --------------------------------------------------------------------


@pytest.mark.anyio
async def test_images_over_total_limit_are_refused(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    four_mb = base64.b64encode(b"0" * (4 * 1024 * 1024)).decode()

    with pytest.raises(InvalidImageError) as info:
        await session.send("veja", images=[{"media_type": "image/png", "data": four_mb}] * 8)

    assert "30 MB" in str(info.value)


def test_sdk_options_raise_buffer_size(tmp_path):
    async def allow(name, tool_input, context):
        return None

    sdk = build_sdk_options(AgentOptions(
        cwd=tmp_path, session_id="s", resume=False, can_use_tool=allow))

    assert sdk.max_buffer_size == 64 * 1024 * 1024


# Stopping subagents on demand ------------------------------------------------


@pytest.mark.anyio
async def test_stop_subagents_when_idle(make_env, env_cleanup):
    env, session = await with_background_agent(make_env, env_cleanup)
    client = env.factory.clients[0]

    await session.stop_subagents()

    assert client.stopped_tasks == ["task-1"]
    assert client.interrupts == 0
    assert session.state == "idle"


@pytest.mark.anyio
async def test_stop_subagents_during_a_turn_does_not_interrupt_it(make_env, env_cleanup):
    pause = PauseStep()

    def turn(sid):
        steps = background_agent(sid)
        return [*steps[:-1], pause, steps[-1]]

    env, session = await connected(make_env, env_cleanup, turn)
    await session.send("rode em segundo plano")
    await pause.reached.wait()
    await wait_until(lambda: session.subagents_running)
    client = env.factory.clients[0]
    assert session.state == "running"

    await session.stop_subagents()

    assert client.stopped_tasks == ["task-1"]
    assert client.interrupts == 0
    assert session.state == "running"
    pause.release.set()
    await wait_until(lambda: session.state == "idle")


@pytest.mark.anyio
async def test_stop_subagents_without_subagent_or_client_does_nothing(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup)
    client = env.factory.clients[0]

    await session.stop_subagents()
    assert client.stopped_tasks == []

    await session.close()
    await session.stop_subagents()  # no client: no effect, no error
    assert client.stopped_tasks == []
