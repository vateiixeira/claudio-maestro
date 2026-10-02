"""Bash run with `run_in_background`: the card follows the task and the session
counts as working while it runs. Only the scripted fake agent is used."""

import asyncio
from types import SimpleNamespace

import pytest
from claude_agent_sdk import ToolUseBlock
from test_controls import connected
from test_sessions import env_cleanup, make_env, wait_until  # noqa: F401

from claudio_maestro.agent.fake import (
    background_bash_turn,
    background_tasks_changed_message,
    bash_task_notification_message,
    bash_task_started_message,
    init_message,
    response_messages,
    result_message,
    task_started_message,
    task_updated_message,
    text_turn,
    tool_result_message,
)
from claudio_maestro.conversation import SUBAGENT_MAX_SECONDS, ConversationBuilder

SID = "s-1"


def feed(builder: ConversationBuilder, messages) -> list:
    events = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def bash_call(tool_use_id="toolu_bash", *, background=True, command="sleep 8; echo done",
              message_id=None):
    tool_input = {"command": command}
    if background:
        tool_input["run_in_background"] = True
    return response_messages(
        SID, [ToolUseBlock(id=tool_use_id, name="Bash", input=tool_input)],
        message_id=message_id, stop_reason="tool_use")


def tool_item(builder: ConversationBuilder, tool_use_id="toolu_bash") -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["tool_use_id"] == tool_use_id]
    return item


def background_of(builder: ConversationBuilder, tool_use_id="toolu_bash") -> dict | None:
    return tool_item(builder, tool_use_id)["background"]


def started_builder() -> ConversationBuilder:
    builder = ConversationBuilder()
    feed(builder, bash_call())
    feed(builder, [bash_task_started_message(SID, "bg-1", "toolu_bash")])
    return builder


# Builder ---------------------------------------------------------------------


def test_bash_without_task_has_no_background_state():
    builder = ConversationBuilder()
    feed(builder, bash_call())

    assert background_of(builder) is None
    assert not builder.subagents_running


def test_task_started_marks_background_bash_as_running():
    builder = ConversationBuilder()
    feed(builder, bash_call())

    events = feed(builder, [bash_task_started_message(SID, "bg-1", "toolu_bash")])

    assert background_of(builder) == {"task_id": "bg-1", "status": "running", "summary": None}
    assert events[-1].type == "item.upsert"
    assert events[-1].data["background"]["status"] == "running"
    assert tool_item(builder)["subagent"] is None
    assert builder.subagents_running
    assert builder.running_task_ids() == ["bg-1"]


def test_foreground_bash_task_is_ignored():
    builder = ConversationBuilder()
    feed(builder, bash_call(background=False))

    events = feed(builder, [bash_task_started_message(SID, "t-1", "toolu_bash", is_backgrounded=False)])

    assert events == []
    assert background_of(builder) is None
    assert not builder.subagents_running


def test_task_messages_for_other_tools_are_still_ignored():
    builder = ConversationBuilder()
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_r", name="Read", input={})], stop_reason="tool_use"))

    assert builder.handle(task_started_message(SID, "t-9", "toolu_r")) == []


def test_background_survives_the_tool_result_and_the_turn_result():
    builder = started_builder()

    feed(builder, [tool_result_message("toolu_bash", "Command running in background with ID: bg-1."),
                   result_message(SID)])

    assert background_of(builder)["status"] == "running"
    assert builder.subagents_running


def test_notification_completes_with_summary():
    builder = started_builder()

    events = feed(builder, [bash_task_notification_message(
        SID, "bg-1", "toolu_bash", summary="Background command completed (exit code 0)")])

    background = background_of(builder)
    assert background["status"] == "completed"
    assert background["summary"] == "Background command completed (exit code 0)"
    assert events[-1].data["background"]["status"] == "completed"
    assert not builder.subagents_running


def test_notification_failed():
    builder = started_builder()

    feed(builder, [bash_task_notification_message(SID, "bg-1", "toolu_bash", status="failed")])

    assert background_of(builder)["status"] == "failed"


def test_task_updated_without_tool_use_id_is_mapped_by_task_id():
    builder = started_builder()

    feed(builder, [task_updated_message(SID, "bg-1", "killed")])

    assert background_of(builder)["status"] == "stopped"
    assert not builder.subagents_running


def test_task_updated_without_known_status_keeps_running():
    builder = started_builder()

    feed(builder, [task_updated_message(SID, "bg-1", "", patch={"end_time": 5})])

    assert background_of(builder)["status"] == "running"


def test_empty_background_tasks_ends_running_bash_and_a_later_message_overwrites():
    builder = started_builder()
    feed(builder, [tool_result_message("toolu_bash", "Command running in background")])

    events = feed(builder, [background_tasks_changed_message(SID, [])])

    assert background_of(builder)["status"] == "completed"
    assert len(events) == 1
    assert not builder.subagents_running

    feed(builder, [bash_task_notification_message(SID, "bg-1", "toolu_bash", status="failed")])
    assert background_of(builder)["status"] == "failed"


def test_empty_background_tasks_without_result_stops_bash():
    builder = started_builder()

    feed(builder, [background_tasks_changed_message(SID, [])])

    assert background_of(builder)["status"] == "stopped"


def test_non_empty_background_tasks_keep_bash_running():
    builder = started_builder()

    assert builder.handle(background_tasks_changed_message(SID, [{"task_id": "bg-1"}])) == []
    assert background_of(builder)["status"] == "running"


def test_stop_running_marks_background_bash_as_stopped():
    builder = started_builder()

    events = builder.stop_running_subagents()

    assert background_of(builder)["status"] == "stopped"
    assert len(events) == 1
    assert builder.running_task_ids() == []


def test_background_bash_running_for_hours_no_longer_counts():
    builder = started_builder()
    assert builder.subagents_running

    builder._subagent_started["toolu_bash"] -= SUBAGENT_MAX_SECONDS + 1

    assert not builder.subagents_running
    assert background_of(builder)["status"] == "running"


def test_replayed_tool_use_keeps_background_state():
    builder = ConversationBuilder()
    feed(builder, bash_call(message_id="m-1"))
    feed(builder, [bash_task_started_message(SID, "bg-1", "toolu_bash")])

    feed(builder, bash_call(message_id="m-1"))  # the final message repeats the block

    assert background_of(builder)["status"] == "running"


def test_history_has_no_invented_background_status():
    builder = ConversationBuilder()
    builder.load_history([
        SimpleNamespace(type="assistant", uuid="u", message={"id": "m1", "content": [
            {"type": "tool_use", "id": "toolu_bash", "name": "Bash",
             "input": {"command": "sleep 8", "run_in_background": True}}]}),
        SimpleNamespace(type="user", uuid="u2", message={"content": [
            {"type": "tool_result", "tool_use_id": "toolu_bash",
             "content": "Command running in background with ID: bg-1."}]}),
    ])

    assert background_of(builder) is None
    assert not builder.subagents_running


# Session ---------------------------------------------------------------------


def _updates(env, sid):
    return [e["data"] for e in env.recorder.of(sid, "session.updated")]


async def with_background_bash(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, background_bash_turn)
    await session.send("rode em segundo plano")
    await wait_until(lambda: session.state == "idle" and session.subagents_running)
    return env, session


def card(session) -> dict:
    [tool] = [i for i in session.snapshot()["items"] if i["type"] == "tool"]
    return tool


@pytest.mark.anyio
async def test_session_stays_running_after_the_turn_result(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)
    sid = session.session_id

    summary = env.manager.summary(sid)
    assert summary["state"] == "idle"
    assert summary["display_state"] == "running"
    assert summary["subagents_running"] is True
    assert _updates(env, sid)[-1]["subagents_running"] is True
    assert card(session)["background"]["status"] == "running"


@pytest.mark.anyio
async def test_running_background_bash_keeps_client_open_when_idle(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)
    env.manager._idle_timeout = 0

    await env.manager.close_idle()

    assert session.client is not None
    assert not env.factory.clients[0].closed


@pytest.mark.anyio
async def test_effort_waits_for_running_background_bash(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id

    summary = await env.manager.update(sid, effort="high")
    await asyncio.sleep(0.02)
    assert summary["effort_pending"] is True
    assert len(env.factory.clients) == 1
    assert not client.closed

    turn = text_turn(sid, "fim")
    client.push([background_tasks_changed_message(sid, []),
                 task_updated_message(sid, "bg-1", "completed"),
                 bash_task_notification_message(sid, "bg-1", "toolu_bash"),
                 init_message(sid), *turn[2:]])
    await wait_until(lambda: len(env.factory.clients) == 2 and not session.effort_pending)
    assert env.factory.clients[1].options.effort == "high"


@pytest.mark.anyio
async def test_completion_by_notification_announces_waiting(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id
    before = len(_updates(env, sid))

    turn = text_turn(sid, "fim")
    # The order seen in the real SDK: tasks cleared, then the terminal messages, then the turn.
    client.push([background_tasks_changed_message(sid, []),
                 task_updated_message(sid, "bg-1", "completed"),
                 bash_task_notification_message(sid, "bg-1", "toolu_bash"),
                 init_message(sid), *turn[2:]])
    await wait_until(lambda: session.state == "idle" and not session.subagents_running
                     and not session._autonomous_turn)
    await asyncio.sleep(0.02)

    assert card(session)["background"]["status"] == "completed"
    assert "exit code 0" in card(session)["background"]["summary"]
    later = _updates(env, sid)[before:]
    assert later[-1]["display_state"] == "waiting"
    assert later[-1]["subagents_running"] is False
    # No flash of "waiting" between the end of the task and the turn the CLI opens.
    assert all(u["display_state"] != "waiting" for u in later[:-1])


@pytest.mark.anyio
async def test_completion_by_task_updated_only(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)
    client = env.factory.clients[0]
    sid = session.session_id

    client.push([task_updated_message(sid, "bg-1", "killed")])
    await wait_until(lambda: not session.subagents_running)
    await asyncio.sleep(0.02)

    assert card(session)["background"]["status"] == "stopped"
    assert env.manager.summary(sid)["display_state"] == "waiting"
    assert _updates(env, sid)[-1]["subagents_running"] is False


@pytest.mark.anyio
async def test_stop_subagents_stops_background_bash(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)

    await session.stop_subagents()

    assert env.factory.clients[0].stopped_tasks == ["bg-1"]


@pytest.mark.anyio
async def test_close_marks_background_bash_stopped(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)

    await session.close()

    assert card(session)["background"]["status"] == "stopped"
    assert not session.subagents_running
    upserts = env.recorder.of(session.session_id, "item.upsert")
    assert upserts[-1]["data"]["background"]["status"] == "stopped"


@pytest.mark.anyio
async def test_tool_result_after_task_started_does_not_end_the_task(make_env, env_cleanup):
    env, session = await with_background_bash(make_env, env_cleanup)

    assert card(session)["result"] is not None
    assert session.subagents_running
