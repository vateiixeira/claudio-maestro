from types import SimpleNamespace

from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock, ToolUseBlock

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
