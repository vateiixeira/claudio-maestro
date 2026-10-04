"""A subagent lost without any notification: past SUBAGENT_MAX_SECONDS without activity
the sweep (`expire_lost_subagents`) moves its card to "stopped" and announces it; a later
Task* message brings the truth back. A background Bash only stops counting."""

import pytest
from claude_agent_sdk import ToolUseBlock
from test_background_bash import background_of, bash_call, feed, tool_item
from test_controls import connected  # noqa: F401
from test_sessions import env_cleanup, make_env  # noqa: F401
from test_subagent_endings import load

from claudio_maestro.agent.fake import (
    bash_task_notification_message,
    bash_task_started_message,
    response_messages,
    task_notification_message,
    task_progress_message,
    task_started_message,
    task_updated_message,
    tool_result_message,
)
from claudio_maestro.conversation import SUBAGENT_MAX_SECONDS, ConversationBuilder

SID = "s-1"
TOOL = "toolu_agent"


def agent_call(tool_use_id: str = TOOL, message_id: str | None = None, parent: str | None = None):
    return response_messages(
        SID,
        [ToolUseBlock(id=tool_use_id, name="Agent",
                      input={"description": "Explorar", "prompt": "x", "run_in_background": True})],
        message_id=message_id, parent_tool_use_id=parent, stop_reason="tool_use")


def running_builder() -> ConversationBuilder:
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", TOOL)])
    return builder


def sub_of(builder: ConversationBuilder, tool_use_id: str = TOOL) -> dict:
    return tool_item(builder, tool_use_id)["subagent"]


def age(builder: ConversationBuilder, tool_use_id: str = TOOL, seconds: float | None = None):
    builder._subagent_started[tool_use_id] -= (
        SUBAGENT_MAX_SECONDS + 1 if seconds is None else seconds
    )


def test_sweep_moves_a_lost_subagent_to_stopped_and_announces_it():
    builder = running_builder()
    age(builder)

    events = builder.expire_lost_subagents()

    assert sub_of(builder)["status"] == "stopped"
    assert builder.running_task_ids() == []
    assert not builder.subagents_running
    assert [e.type for e in events] == ["item.upsert"]
    assert events[0].data["subagent"]["status"] == "stopped"
    assert events[0].data["tool_use_id"] == TOOL


def test_sweep_is_silent_the_second_time():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    assert builder.expire_lost_subagents() == []


def test_sweep_keeps_a_recent_subagent_running():
    builder = running_builder()
    age(builder, seconds=SUBAGENT_MAX_SECONDS - 60)

    assert builder.expire_lost_subagents() == []
    assert sub_of(builder)["status"] == "running"
    assert builder.running_task_ids() == ["task-1"]


def test_progress_counts_as_activity_for_a_long_running_subagent():
    builder = running_builder()
    age(builder)  # started over 3 h ago...
    feed(builder, [task_progress_message(SID, "task-1", TOOL)])  # ...but alive just now

    assert builder.subagents_running
    assert builder.expire_lost_subagents() == []
    assert sub_of(builder)["status"] == "running"


def test_child_message_counts_as_activity():
    builder = running_builder()
    age(builder)
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_child", name="Read", input={"file_path": "/x"})],
        parent_tool_use_id=TOOL, stop_reason="tool_use"))

    assert builder.subagents_running
    assert builder.expire_lost_subagents() == []


def child_tool_call(tool_use_id: str = "toolu_child"):
    return response_messages(
        SID, [ToolUseBlock(id=tool_use_id, name="Read", input={"file_path": "/x"})],
        parent_tool_use_id=TOOL, stop_reason="tool_use")


def test_child_tool_result_counts_as_activity():
    builder = running_builder()
    feed(builder, child_tool_call())
    age(builder)  # the child call went out long ago; only its result is recent

    feed(builder, [tool_result_message("toolu_child", "ok", parent_tool_use_id=TOOL)])

    assert builder.subagents_running
    assert builder.expire_lost_subagents() == []
    assert sub_of(builder)["status"] == "running"


def test_child_message_revives_an_expired_card():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    events = feed(builder, child_tool_call())

    assert sub_of(builder)["status"] == "running"
    assert any(e.type == "item.upsert" and e.data.get("tool_use_id") == TOOL
               and e.data["subagent"]["status"] == "running" for e in events)
    assert builder.running_task_ids() == ["task-1"]


def test_child_tool_result_revives_an_expired_card():
    builder = running_builder()
    feed(builder, child_tool_call())
    age(builder)
    builder.expire_lost_subagents()

    feed(builder, [tool_result_message("toolu_child", "ok", parent_tool_use_id=TOOL)])

    assert sub_of(builder)["status"] == "running"
    assert builder.subagents_running


def test_reattached_running_card_counts_from_its_last_activity():
    now = 1_000_000.0
    builder = load(
        live=True, now=now,
        times={"toolu_1": {"started_at": int(now) - 4 * 3600, "ended_at": int(now) - 600}},
    )

    assert builder.subagents_running
    assert builder.expire_lost_subagents() == []
    assert sub_of(builder, "toolu_1")["status"] == "running"


def test_reattached_running_card_with_old_activity_expires():
    now = 1_000_000.0
    builder = load(
        live=True, now=now,
        times={"toolu_1": {"started_at": int(now) - 5 * 3600, "ended_at": int(now) - 4 * 3600}},
    )

    assert [e.type for e in builder.expire_lost_subagents()] == ["item.upsert"]
    assert sub_of(builder, "toolu_1")["status"] == "stopped"


def test_expired_subagent_comes_back_on_progress():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    events = feed(builder, [task_progress_message(SID, "task-1", TOOL)])

    assert sub_of(builder)["status"] == "running"
    assert events and events[-1].data["subagent"]["status"] == "running"
    assert builder.running_task_ids() == ["task-1"]
    assert builder.subagents_running
    # and the clock restarted: the next sweep leaves it alone
    assert builder.expire_lost_subagents() == []


def test_expired_subagent_comes_back_on_started():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    feed(builder, [task_started_message(SID, "task-1", TOOL)])

    assert sub_of(builder)["status"] == "running"


def test_expired_subagent_takes_the_status_of_a_late_notification():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    feed(builder, [task_notification_message(SID, "task-1", TOOL, status="failed")])

    assert sub_of(builder)["status"] == "failed"
    assert builder.running_task_ids() == []


def test_expired_subagent_takes_the_status_of_a_late_update():
    builder = running_builder()
    age(builder)
    builder.expire_lost_subagents()

    feed(builder, [task_updated_message(SID, "task-1", "completed")])

    assert sub_of(builder)["status"] == "completed"


def test_progress_does_not_revive_a_subagent_stopped_by_the_user():
    builder = running_builder()
    builder.stop_running_subagents()

    feed(builder, [task_progress_message(SID, "task-1", TOOL)])

    assert sub_of(builder)["status"] == "stopped"


def test_a_completed_subagent_is_never_touched():
    builder = running_builder()
    feed(builder, [task_notification_message(SID, "task-1", TOOL)])
    age(builder)

    assert builder.expire_lost_subagents() == []
    assert sub_of(builder)["status"] == "completed"


def test_background_bash_past_the_limit_stays_running_but_stops_counting():
    builder = ConversationBuilder()
    feed(builder, bash_call())
    feed(builder, [bash_task_started_message(SID, "bg-1", "toolu_bash")])
    age(builder, "toolu_bash")

    assert builder.expire_lost_subagents() == []

    assert background_of(builder)["status"] == "running"
    assert builder.running_task_ids() == ["bg-1"]
    assert not builder.subagents_running


def test_background_bash_notification_after_the_limit_sets_its_status():
    builder = ConversationBuilder()
    feed(builder, bash_call())
    feed(builder, [bash_task_started_message(SID, "bg-1", "toolu_bash")])
    age(builder, "toolu_bash")
    builder.expire_lost_subagents()

    feed(builder, [bash_task_notification_message(SID, "bg-1", "toolu_bash")])

    assert background_of(builder)["status"] == "completed"
    assert builder.running_task_ids() == []


def test_replayed_launch_keeps_an_expired_card_stopped():
    builder = ConversationBuilder()
    feed(builder, agent_call(message_id="m-1"))
    feed(builder, [task_started_message(SID, "task-1", TOOL)])
    age(builder)
    builder.expire_lost_subagents()

    feed(builder, agent_call(message_id="m-1"))  # a repeated block must not wake it

    assert sub_of(builder)["status"] == "stopped"


# Session / manager ----------------------------------------------------------


@pytest.mark.anyio
async def test_idle_sweep_announces_the_stopped_card(make_env, env_cleanup):  # noqa: F811
    from test_controls_review import with_background_agent

    env, session = await with_background_agent(make_env, env_cleanup)
    sid = session.session_id
    for key in session.builder._subagent_started:
        session.builder._subagent_started[key] -= SUBAGENT_MAX_SECONDS + 1
    before = len(env.recorder.of(sid, "item.upsert"))

    await env.manager.close_idle()

    upserts = env.recorder.of(sid, "item.upsert")[before:]
    assert upserts[-1]["data"]["subagent"]["status"] == "stopped"
    [tool] = [i for i in session.snapshot()["items"] if i["type"] == "tool"]
    assert tool["subagent"]["status"] == "stopped"
    assert session.builder.running_task_ids() == []
