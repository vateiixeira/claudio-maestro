from types import SimpleNamespace

from claude_agent_sdk import (
    AssistantMessage,
    StreamEvent,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro.conversation import ConversationBuilder, TextItem, ToolItem


def entry(kind: str, uuid: str, message: dict) -> SimpleNamespace:
    return SimpleNamespace(type=kind, uuid=uuid, message=message)


def assistant_entry(uuid: str, message_id: str, block: dict) -> SimpleNamespace:
    return entry("assistant", uuid, {"id": message_id, "model": "m", "content": [block]})


def stream(event: dict) -> StreamEvent:
    return StreamEvent(uuid="se", session_id="s", event=event, parent_tool_use_id=None)


def history_with_running_agent() -> list[SimpleNamespace]:
    return [
        entry("user", "u1", {"content": "faça"}),
        assistant_entry("a1", "msg_1", {"type": "tool_use", "id": "toolu_1", "name": "Agent",
                                        "input": {"description": "x", "prompt": "y"}}),
    ]


def test_live_history_keeps_tools_pending_and_subagents_running():
    builder = ConversationBuilder()
    builder.load_history(history_with_running_agent(), live=True)
    tool = next(i for i in builder.items if isinstance(i, ToolItem))
    assert tool.result_missing is False
    assert tool.subagent is not None
    assert tool.subagent["status"] == "running"


def test_default_history_still_closes_everything():
    builder = ConversationBuilder()
    builder.load_history(history_with_running_agent())
    tool = next(i for i in builder.items if isinstance(i, ToolItem))
    assert tool.result_missing is True
    assert tool.subagent is not None
    assert tool.subagent["status"] == "stopped"


def test_replayed_message_from_history_is_dropped():
    builder = ConversationBuilder()
    builder.load_history([assistant_entry("a1", "msg_1", {"type": "text", "text": "olá"})],
                         live=True)
    before = builder.snapshot()
    events = builder.handle(AssistantMessage(content=[TextBlock("olá")], model="m",
                                             message_id="msg_1", uuid="a1"))
    assert events == []
    assert builder.snapshot() == before


def test_stream_of_a_message_already_on_disk_is_ignored():
    builder = ConversationBuilder()
    builder.load_history([assistant_entry("a1", "msg_1", {"type": "text", "text": "olá"})],
                         live=True)
    before = builder.snapshot()
    for event in (
        {"type": "message_start", "message": {"id": "msg_1"}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "olá"}},
        {"type": "content_block_stop", "index": 0},
    ):
        assert builder.handle(stream(event)) == []
    assert builder.snapshot() == before


def test_new_message_after_history_streams_normally():
    builder = ConversationBuilder()
    builder.load_history([assistant_entry("a1", "msg_1", {"type": "text", "text": "olá"})],
                         live=True)
    builder.handle(stream({"type": "message_start", "message": {"id": "msg_2"}}))
    builder.handle(stream({"type": "content_block_start", "index": 0,
                           "content_block": {"type": "text", "text": ""}}))
    builder.handle(stream({"type": "content_block_delta", "index": 0,
                           "delta": {"type": "text_delta", "text": "novo"}}))
    builder.handle(AssistantMessage(content=[TextBlock("novo")], model="m",
                                    message_id="msg_2", uuid="a2"))
    texts = [i.text for i in builder.items if isinstance(i, TextItem)]
    assert texts == ["olá", "novo"]
    assert not any(getattr(i, "streaming", False) for i in builder.items)


def test_replayed_tool_use_from_history_is_not_duplicated():
    builder = ConversationBuilder()
    builder.load_history(history_with_running_agent(), live=True)
    count = len(builder.items)
    builder.handle(AssistantMessage(
        content=[ToolUseBlock(id="toolu_1", name="Agent", input={"description": "x", "prompt": "y"})],
        model="m", message_id="msg_1", uuid="a1"))
    assert len(builder.items) == count


def test_mid_message_replay_does_not_duplicate_the_reply():
    # Disk has block 0 of msg_1. The replay starts after that block's line, so there is
    # no message_start: block 1 streams without a message id and must not become an item.
    builder = ConversationBuilder()
    builder.load_history([entry("user", "u1", {"content": "oi"}),
                          assistant_entry("a0", "msg_1", {"type": "text", "text": "primeiro"})],
                         live=True)
    for event in (
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "text_delta", "text": "segundo"}},
    ):
        assert builder.handle(stream(event)) == []
    builder.handle(AssistantMessage(content=[TextBlock("segundo")], model="m",
                                    message_id="msg_1", uuid="a1"))
    builder.handle(stream({"type": "content_block_stop", "index": 1}))
    texts = [(i.text, i.streaming) for i in builder.items if isinstance(i, TextItem)]
    assert texts == [("primeiro", False), ("segundo", False)]


def test_replayed_user_message_with_tool_result_already_on_disk_changes_nothing():
    builder = ConversationBuilder()
    builder.load_history([
        entry("user", "u1", {"content": "faça"}),
        assistant_entry("a1", "msg_1", {"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                        "input": {"command": "ls"}}),
        entry("user", "u2", {"content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": "ok"}]}),
    ], live=True)
    before = builder.snapshot()
    events = builder.handle(UserMessage(
        content=[ToolResultBlock(tool_use_id="toolu_1", content="ok")], uuid="u2",
        tool_use_result={"stdout": "ok"}))
    assert events == []
    assert builder.snapshot() == before


def test_skipped_stream_of_a_subagent_is_reset_by_its_next_message_start():
    builder = ConversationBuilder()
    builder.load_history([assistant_entry("a0", "msg_1", {"type": "text", "text": "x"})],
                         live=True)

    def sub_stream(event: dict) -> StreamEvent:
        return StreamEvent(uuid="se", session_id="s", event=event, parent_tool_use_id="toolu_p")

    # Mid-message stream of a subagent: skipped.
    assert builder.handle(sub_stream({"type": "content_block_start", "index": 1,
                                      "content_block": {"type": "text", "text": ""}})) == []
    assert builder.handle(sub_stream({"type": "content_block_delta", "index": 1,
                                      "delta": {"type": "text_delta", "text": "lost"}})) == []
    # Its next message streams normally, and the main thread's stream is untouched.
    builder.handle(sub_stream({"type": "message_start", "message": {"id": "msg_sub"}}))
    builder.handle(sub_stream({"type": "content_block_start", "index": 0,
                               "content_block": {"type": "text", "text": ""}}))
    builder.handle(sub_stream({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "text_delta", "text": "novo"}}))
    live_items = [i for i in builder.items if getattr(i, "streaming", False)]
    assert [(i.id, i.text, i.parent_tool_use_id) for i in live_items] == [
        ("msg_sub:0", "novo", "toolu_p")]


def test_stream_without_message_start_outside_live_mode_still_creates_an_item():
    builder = ConversationBuilder()
    builder.handle(stream({"type": "content_block_start", "index": 0,
                           "content_block": {"type": "text", "text": ""}}))
    assert any(isinstance(i, TextItem) and i.streaming for i in builder.items)
