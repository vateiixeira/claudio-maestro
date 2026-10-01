"""Marco 5 in the conversation builder: local commands, background tasks, subagents."""

from types import SimpleNamespace

from claude_agent_sdk import TextBlock, ToolUseBlock

from claudio_maestro.agent.fake import (
    background_tasks_changed_message,
    local_command_message,
    response_messages,
    result_message,
    task_notification_message,
    task_progress_message,
    task_started_message,
    task_updated_message,
    tool_result_message,
)
from claudio_maestro.conversation import ConversationBuilder

SID = "s-1"


def feed(builder: ConversationBuilder, messages) -> list:
    events = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def test_local_command_stdout_becomes_info_notice():
    builder = ConversationBuilder()

    events = builder.handle(local_command_message("Compacted conversation"))

    [event] = events
    assert event.type == "item.upsert"
    assert event.data["type"] == "notice"
    assert event.data["level"] == "info"
    assert event.data["text"] == "Compacted conversation"


def test_echo_of_app_option_change_is_ignored():
    builder = ConversationBuilder()
    builder.expect_local_echo("Set model to sonnet")

    real = "Set model to `sonnet (claude-sonnet-5-5)`"
    assert builder.handle(local_command_message(real)) == []
    # Only as many echoes as expected are dropped.
    [event] = builder.handle(local_command_message(real))
    assert event.data["text"] == real


def test_other_local_output_is_shown():
    builder = ConversationBuilder()
    builder.expect_local_echo("Set model to opus")

    [event] = builder.handle(local_command_message("Set permission mode to plan"))
    assert event.data["level"] == "info"


def test_cleared_echo_is_shown():
    builder = ConversationBuilder()
    builder.expect_local_echo("Set model to opus")
    builder.clear_local_echo()

    assert len(builder.handle(local_command_message("Set model to opus"))) == 1


def test_plain_string_user_message_is_still_ignored():
    builder = ConversationBuilder()
    from claude_agent_sdk import UserMessage

    assert builder.handle(UserMessage(content="oi")) == []


def test_background_tasks_changed_is_ignored():
    builder = ConversationBuilder()
    assert builder.handle(background_tasks_changed_message(SID, [{"id": "t1"}])) == []
    assert builder.items == []


def agent_call(tool_use_id: str = "toolu_agent") -> list:
    return response_messages(
        SID,
        [ToolUseBlock(id=tool_use_id, name="Agent",
                      input={"description": "Explorar", "subagent_type": "Explore",
                             "prompt": "olhe"})],
        stop_reason="tool_use",
    )


def tool_item(builder: ConversationBuilder, tool_use_id: str) -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["tool_use_id"] == tool_use_id]
    return item


def test_subagent_follows_the_four_task_messages():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, [tool_result_message("toolu_agent", "Async agent launched successfully")])

    events = builder.handle(task_started_message(SID, "task-1", "toolu_agent",
                                                 description="Explorar", subagent_type="Explore"))
    [event] = events
    assert event.type == "item.upsert"
    sub = event.data["subagent"]
    assert sub["task_id"] == "task-1"
    assert sub["subagent_type"] == "Explore"
    assert sub["description"] == "Explorar"
    assert sub["status"] == "running"

    usage = {"total_tokens": 50, "tool_uses": 2, "duration_ms": 900}
    [event] = builder.handle(task_progress_message(
        SID, "task-1", "toolu_agent", description="Lendo main.py", last_tool_name="Read",
        usage=usage))
    sub = event.data["subagent"]
    assert sub["description"] == "Lendo main.py"
    assert sub["last_activity"] == "Read"
    assert sub["usage"] == usage

    # Child messages stay as items with the parent id (no stream events for subagents).
    child = feed(builder, [
        *response_messages(SID, [TextBlock(text="achei")], parent_tool_use_id="toolu_agent"),
    ])
    texts = [e.data for e in child if e.type == "item.upsert" and e.data["type"] == "text"]
    assert texts and all(t["parent_tool_use_id"] == "toolu_agent" for t in texts)

    [event] = builder.handle(task_updated_message(SID, "task-1", "completed"))
    assert event.data["subagent"]["status"] == "completed"

    [event] = builder.handle(task_notification_message(
        SID, "task-1", "toolu_agent", status="completed", summary="Resumo final"))
    sub = event.data["subagent"]
    assert sub["status"] == "completed"
    assert sub["summary"] == "Resumo final"
    assert tool_item(builder, "toolu_agent")["subagent"]["summary"] == "Resumo final"


def test_subagent_statuses_are_mapped():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    builder.handle(task_started_message(SID, "task-1", "toolu_agent"))

    [event] = builder.handle(task_updated_message(SID, "task-1", "killed"))
    assert event.data["subagent"]["status"] == "stopped"
    [event] = builder.handle(task_notification_message(SID, "task-1", "toolu_agent",
                                                       status="failed"))
    assert event.data["subagent"]["status"] == "failed"


def test_agent_tool_gets_subagent_before_task_started():
    builder = ConversationBuilder()
    feed(builder, agent_call())

    sub = tool_item(builder, "toolu_agent")["subagent"]
    assert sub["status"] == "running"
    assert sub["subagent_type"] == "Explore"
    assert sub["task_id"] is None


def test_task_messages_for_other_tools_are_ignored():
    builder = ConversationBuilder()
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_bash", name="Bash", input={"command": "sleep 9"})],
        stop_reason="tool_use"))

    assert builder.handle(task_started_message(SID, "task-9", "toolu_bash")) == []
    assert tool_item(builder, "toolu_bash")["subagent"] is None


def test_other_tools_have_no_subagent():
    builder = ConversationBuilder()
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_r", name="Read", input={})], stop_reason="tool_use"))
    assert tool_item(builder, "toolu_r")["subagent"] is None


def entry(type_: str, message: dict) -> SimpleNamespace:
    return SimpleNamespace(type=type_, message=message, uuid="u")


def test_history_marks_subagent_completed_when_result_exists():
    builder = ConversationBuilder()
    builder.load_history([
        entry("assistant", {"id": "m1", "content": [
            {"type": "tool_use", "id": "toolu_a", "name": "Task",
             "input": {"description": "Rever", "subagent_type": "reviewer"}},
            {"type": "tool_use", "id": "toolu_b", "name": "Agent",
             "input": {"description": "Outro", "subagent_type": "Explore"}},
        ]}),
        entry("user", {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_a", "content": "feito"},
        ]}),
    ])

    done = tool_item(builder, "toolu_a")["subagent"]
    assert done["status"] == "completed"
    assert done["subagent_type"] == "reviewer"
    assert done["description"] == "Rever"
    # Without a result the subagent is not left "running" forever.
    assert tool_item(builder, "toolu_b")["subagent"]["status"] == "stopped"


# Subagents stuck in running -------------------------------------------------


def status_of(builder: ConversationBuilder) -> str:
    return tool_item(builder, "toolu_agent")["subagent"]["status"]


def test_error_result_fails_the_subagent():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent")])

    events = feed(builder, [tool_result_message("toolu_agent", "quebrou", is_error=True)])

    assert status_of(builder) == "failed"
    assert events[-1].data["subagent"]["status"] == "failed"
    assert not builder.subagents_running


def test_turn_result_stops_subagent_without_task_id():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, agent_call("toolu_bg"))
    feed(builder, [task_started_message(SID, "task-2", "toolu_bg")])

    events = feed(builder, [result_message(SID)])

    assert status_of(builder) == "stopped"
    assert tool_item(builder, "toolu_bg")["subagent"]["status"] == "running"
    assert any(e.type == "item.upsert" and e.data["tool_use_id"] == "toolu_agent" for e in events)


def test_empty_background_tasks_ends_running_subagents():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, agent_call("toolu_bg"))
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent"),
                   task_started_message(SID, "task-2", "toolu_bg"),
                   tool_result_message("toolu_agent", "launched")])

    events = feed(builder, [background_tasks_changed_message(SID, [])])

    assert status_of(builder) == "completed"
    assert tool_item(builder, "toolu_bg")["subagent"]["status"] == "stopped"
    assert len(events) == 2
    assert not builder.subagents_running


def test_background_tasks_in_other_formats_are_ignored():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent")])

    for tasks in ([{"id": "task-1"}], ["task-1"]):
        assert feed(builder, [background_tasks_changed_message(SID, tasks)]) == []
    message = background_tasks_changed_message(SID)
    message.data["tasks"] = "estranho"
    assert feed(builder, [message]) == []
    assert status_of(builder) == "running"


def test_subagent_running_for_hours_no_longer_counts():
    builder = ConversationBuilder()
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent")])
    assert builder.subagents_running

    builder._subagent_started["toolu_agent"] -= 3 * 60 * 60 + 1

    assert not builder.subagents_running
    assert status_of(builder) == "running"
