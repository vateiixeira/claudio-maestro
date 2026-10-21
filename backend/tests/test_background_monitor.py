"""A live Monitor keeps its session working until its background task ends.

Only the scripted fake agent is used; the task messages match the observed SDK.
"""

import time

import pytest
from claude_agent_sdk import ToolUseBlock
from test_background_bash import background_of, feed
from test_controls import connected
from test_sessions import env_cleanup, make_env, wait_until  # noqa: F401

from claudio_maestro.agent.fake import (
    background_tasks_changed_message,
    init_message,
    monitor_task_notification_message,
    monitor_task_started_message,
    response_messages,
    result_message,
    task_updated_message,
    tool_result_message,
)
from claudio_maestro.conversation import SUBAGENT_MAX_SECONDS, ConversationBuilder

SID = "s-1"
TOOL = "toolu_monitor"
TASK = "monitor-1"


def monitor_call(session_id=SID):
    return response_messages(
        session_id,
        [ToolUseBlock(id=TOOL, name="Monitor", input={
            "command": "sleep 8; echo done", "description": "Aguardar saída",
            "timeout_ms": 30000,
        })],
        stop_reason="tool_use",
    )


def started_builder():
    builder = ConversationBuilder()
    feed(builder, monitor_call())
    feed(builder, [monitor_task_started_message(SID, TASK, TOOL)])
    return builder


@pytest.mark.parametrize("is_backgrounded", [True, False, None])
def test_monitor_counts_as_running_until_it_ends(is_backgrounded):
    builder = ConversationBuilder()
    feed(builder, monitor_call())
    started = monitor_task_started_message(SID, TASK, TOOL)
    if is_backgrounded is None:
        started.data.pop("is_backgrounded")
    else:
        started.data["is_backgrounded"] = is_backgrounded

    events = feed(builder, [started])

    assert builder.subagents_running is True
    assert background_of(builder, TOOL) == {
        "task_id": TASK, "status": "running", "summary": None,
    }
    assert events[-1].data["background"]["status"] == "running"
    assert builder.running_task_ids() == [TASK]

    feed(builder, [monitor_task_notification_message(SID, TASK, TOOL)])

    assert builder.subagents_running is False
    assert background_of(builder, TOOL)["status"] == "completed"


def test_monitor_ends_with_empty_background_tasks_changed():
    builder = started_builder()
    assert builder.subagents_running is True

    feed(builder, [background_tasks_changed_message(SID, [])])

    assert builder.subagents_running is False
    assert background_of(builder, TOOL)["status"] == "stopped"


def monitor_turn(session_id):
    return [
        init_message(session_id),
        *monitor_call(session_id),
        monitor_task_started_message(session_id, TASK, TOOL),
        tool_result_message(TOOL, "Monitor started", tool_use_result={
            "details": {"taskId": TASK, "timeoutMs": 30000, "persistent": False},
        }),
        result_message(session_id),
    ]


@pytest.mark.anyio
async def test_idle_session_with_monitor_running_is_not_closed(make_env, env_cleanup):
    env, session = await connected(make_env, env_cleanup, monitor_turn)
    await session.send("monitore a saída")
    await wait_until(lambda: session.state == "idle")
    session.idle_since = time.monotonic() - env.manager._idle_timeout - 1

    await env.manager.close_idle()

    assert session.client is not None
    assert not env.factory.clients[0].closed
    assert session.subagents_running is True


def test_monitor_over_the_limit_stops_counting():
    builder = started_builder()
    assert builder.subagents_running is True

    builder._subagent_started[TOOL] -= SUBAGENT_MAX_SECONDS + 1

    assert builder.subagents_running is False
    assert builder.expire_lost_subagents() == []
    assert background_of(builder, TOOL)["status"] == "running"


def test_monitor_task_updated_is_correlated_by_task_id():
    builder = started_builder()
    assert builder.subagents_running is True

    feed(builder, [task_updated_message(
        SID, TASK, "", patch={"status": "completed", "end_time": 123456},
    )])

    assert builder.subagents_running is False
    assert background_of(builder, TOOL)["status"] == "completed"
