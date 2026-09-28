"""Conversion of SDK messages into conversation items and events."""

import json
from datetime import UTC, datetime
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from vibing.agent.fake import text_turn, tool_turn
from vibing.conversation import (
    ConversationBuilder,
    Event,
    NoticeItem,
    TextItem,
    ThinkingItem,
    ToolItem,
    UserItem,
)

SID = "5e1d9c3a-2b4f-4a6e-8c7d-9e0f1a2b3c4d"
MODEL = "claude-haiku-4-5"


# Builders for real SDK message instances -----------------------------------


def stream(event: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return StreamEvent(uuid="u", session_id=SID, event=event, parent_tool_use_id=parent)


def message_start(message_id: str, parent: str | None = None) -> StreamEvent:
    return stream(
        {
            "type": "message_start",
            "message": {"id": message_id, "type": "message", "role": "assistant",
                        "model": MODEL, "content": []},
        },
        parent,
    )


def block_start(index: int, block: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return stream(
        {"type": "content_block_start", "index": index, "content_block": block}, parent
    )


def delta(index: int, payload: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return stream({"type": "content_block_delta", "index": index, "delta": payload}, parent)


def block_stop(index: int, parent: str | None = None) -> StreamEvent:
    return stream({"type": "content_block_stop", "index": index}, parent)


def assistant(
    message_id: str | None, *blocks: Any, parent: str | None = None, error: str | None = None
) -> AssistantMessage:
    return AssistantMessage(
        content=list(blocks),
        model=MODEL,
        parent_tool_use_id=parent,
        message_id=message_id,
        error=error,  # type: ignore[arg-type]
        session_id=SID,
    )


def init() -> SystemMessage:
    return SystemMessage(
        subtype="init",
        data={"type": "system", "subtype": "init", "session_id": SID,
              "model": MODEL, "permissionMode": "default"},
    )


def result(**overrides: Any) -> ResultMessage:
    values: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1200,
        "duration_api_ms": 1000,
        "is_error": False,
        "num_turns": 1,
        "session_id": SID,
        "total_cost_usd": 0.0012,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    values.update(overrides)
    return ResultMessage(**values)


def feed(builder: ConversationBuilder, *messages: Any) -> list[Event]:
    events: list[Event] = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def compact(events: list[Event]) -> list[tuple]:
    """Summarize events so sequences can be compared exactly."""
    out = []
    for event in events:
        data = event.data
        if event.type == "item.upsert":
            out.append((event.type, data["id"], data["type"], data.get("streaming")))
        elif event.type == "item.append":
            out.append((event.type, data["item_id"], data["text"]))
        else:
            out.append((event.type,))
    return out


# Text turn with thinking -------------------------------------------------


def test_text_turn_with_thinking_exact_events_and_items():
    builder = ConversationBuilder()
    user_events = builder.add_user_message("oi")

    events = feed(
        builder,
        init(),
        SystemMessage(subtype="status", data={"subtype": "status"}),
        message_start("msg_1"),
        block_start(0, {"type": "thinking", "thinking": "", "signature": ""}),
        RateLimitEvent(
            rate_limit_info=RateLimitInfo(status="allowed", resets_at=1790000000,
                                          rate_limit_type="five_hour"),
            uuid="r", session_id=SID,
        ),
        SystemMessage(subtype="thinking_tokens", data={}),
        delta(0, {"type": "thinking_delta", "thinking": "Hmm, "}),
        delta(0, {"type": "thinking_delta", "thinking": "saudação."}),
        delta(0, {"type": "signature_delta", "signature": "sig"}),
        assistant("msg_1", ThinkingBlock(thinking="Hmm, saudação.", signature="sig")),
        block_stop(0),
        block_start(1, {"type": "text", "text": ""}),
        delta(1, {"type": "text_delta", "text": "Olá"}),
        delta(1, {"type": "text_delta", "text": "!"}),
        assistant("msg_1", TextBlock(text="Olá!")),
        block_stop(1),
        stream({"type": "message_delta", "delta": {"stop_reason": "end_turn"}}),
        stream({"type": "message_stop"}),
        result(),
    )

    user_id = user_events[0].data["id"]
    assert compact(user_events) == [("item.upsert", user_id, "user", None)]
    assert compact(events) == [
        ("session.init",),
        ("item.upsert", "msg_1:0", "thinking", True),
        ("rate_limit",),
        ("item.append", "msg_1:0", "Hmm, "),
        ("item.append", "msg_1:0", "saudação."),
        ("item.upsert", "msg_1:0", "thinking", False),
        ("item.upsert", "msg_1:1", "text", True),
        ("item.append", "msg_1:1", "Olá"),
        ("item.append", "msg_1:1", "!"),
        ("item.upsert", "msg_1:1", "text", False),
        ("turn.result",),
    ]
    assert builder.items == [
        UserItem(id=user_id, text="oi", images=[]),
        ThinkingItem(id="msg_1:0", text="Hmm, saudação.", streaming=False),
        TextItem(id="msg_1:1", text="Olá!", streaming=False),
    ]
    assert events[0].data == {"session_id": SID, "model": MODEL, "permission_mode": "default"}
    assert builder.init is not None and builder.init.model == MODEL
    assert builder.init.permission_mode == "default"
    turn = events[-1].data
    assert turn == {
        "subtype": "success",
        "is_error": False,
        "duration_ms": 1200,
        "total_cost_usd": 0.0012,
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "errors": None,
    }
    assert builder.last_result is not None and builder.last_result.subtype == "success"
    assert events[2].data == {"status": "allowed", "resets_at": 1790000000,
                              "rate_limit_type": "five_hour"}


def test_accumulated_text_is_visible_while_streaming():
    builder = ConversationBuilder()
    feed(
        builder,
        message_start("msg_1"),
        block_start(0, {"type": "text", "text": ""}),
        delta(0, {"type": "text_delta", "text": "Par"}),
        delta(0, {"type": "text_delta", "text": "cial"}),
    )

    assert builder.get("msg_1:0") == TextItem(id="msg_1:0", text="Parcial", streaming=True)


def test_events_are_json_serializable_snapshots():
    builder = ConversationBuilder()
    events = feed(
        builder,
        message_start("msg_1"),
        block_start(0, {"type": "text", "text": ""}),
        delta(0, {"type": "text_delta", "text": "a"}),
    )

    json.dumps([e.to_dict() for e in events])
    json.dumps(builder.snapshot())
    # The upsert payload is a copy: later appends do not change it.
    assert events[0].data["text"] == ""
    assert events[0].to_dict() == {"type": "item.upsert", "data": events[0].data}


# Tool turn ---------------------------------------------------------------


WRITE_RESULT = {
    "type": "create",
    "filePath": "/p/a.txt",
    "content": "x",
    "structuredPatch": [],
    "originalFile": None,
    "userModified": False,
}


def tool_messages() -> list[Any]:
    return [
        init(),
        message_start("msg_1"),
        block_start(0, {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {}}),
        delta(0, {"type": "input_json_delta", "partial_json": '{"file_path": "/p/a.txt"'}),
        delta(0, {"type": "input_json_delta", "partial_json": ', "content": "x"}'}),
        assistant("msg_1", ToolUseBlock(id="toolu_1", name="Write",
                                        input={"file_path": "/p/a.txt", "content": "x"})),
        block_stop(0),
        stream({"type": "message_delta", "delta": {"stop_reason": "tool_use"}}),
        stream({"type": "message_stop"}),
        UserMessage(
            content=[ToolResultBlock(tool_use_id="toolu_1", content="File created",
                                     is_error=False)],
            tool_use_result=WRITE_RESULT,
        ),
        message_start("msg_2"),
        block_start(0, {"type": "text", "text": ""}),
        delta(0, {"type": "text_delta", "text": "Pronto."}),
        assistant("msg_2", TextBlock(text="Pronto.")),
        block_stop(0),
        stream({"type": "message_stop"}),
        result(),
    ]


def test_tool_turn_creates_tool_item_with_input_and_result():
    builder = ConversationBuilder()

    events = feed(builder, *tool_messages())

    assert compact(events) == [
        ("session.init",),
        ("item.upsert", "msg_1:0", "tool", True),
        ("item.upsert", "msg_1:0", "tool", False),
        ("item.upsert", "msg_1:0", "tool", False),
        ("item.upsert", "msg_2:0", "text", True),
        ("item.append", "msg_2:0", "Pronto."),
        ("item.upsert", "msg_2:0", "text", False),
        ("turn.result",),
    ]
    assert events[1].data["input"] == {}
    assert events[2].data["input"] == {"file_path": "/p/a.txt", "content": "x"}
    assert events[2].data["result"] is None
    tool = builder.get("msg_1:0")
    assert tool == ToolItem(
        id="msg_1:0",
        tool_use_id="toolu_1",
        name="Write",
        input={"file_path": "/p/a.txt", "content": "x"},
        result={"content": "File created", "is_error": False, "details": WRITE_RESULT},
        streaming=False,
    )
    assert events[3].data["result"]["details"]["filePath"] == "/p/a.txt"


def test_two_responses_in_same_turn_have_distinct_ids():
    builder = ConversationBuilder()

    feed(builder, *tool_messages())

    assert [item.id for item in builder.items] == ["msg_1:0", "msg_2:0"]
    assert [item.type for item in builder.items] == ["tool", "text"]


def test_tool_result_without_matching_tool_becomes_warning():
    builder = ConversationBuilder()

    events = builder.handle(
        UserMessage(content=[ToolResultBlock(tool_use_id="toolu_x", content="?")])
    )

    assert len(events) == 1
    notice = builder.items[0]
    assert isinstance(notice, NoticeItem)
    assert notice.level == "warning"
    assert events[0].type == "item.upsert"
    assert events[0].data["type"] == "notice"


def test_plain_user_echo_is_ignored():
    builder = ConversationBuilder()

    assert builder.handle(UserMessage(content="oi")) == []
    assert builder.handle(UserMessage(content=[TextBlock(text="oi")])) == []
    assert builder.items == []


# Without stream ----------------------------------------------------------


def test_assistant_message_without_open_stream_creates_sequential_items():
    builder = ConversationBuilder()

    events = feed(
        builder,
        assistant("msg_9", ThinkingBlock(thinking="pensei", signature="s"),
                  TextBlock(text="resposta")),
        assistant("msg_9", ToolUseBlock(id="toolu_2", name="Bash", input={"command": "ls"})),
    )

    assert compact(events) == [
        ("item.upsert", "msg_9:0", "thinking", False),
        ("item.upsert", "msg_9:1", "text", False),
        ("item.upsert", "msg_9:2", "tool", False),
    ]
    assert builder.get("msg_9:2").input == {"command": "ls"}


def test_tool_result_attaches_to_tool_created_without_stream():
    builder = ConversationBuilder()
    feed(builder, assistant("msg_9", ToolUseBlock(id="toolu_2", name="Bash", input={})))

    builder.handle(
        UserMessage(content=[ToolResultBlock(tool_use_id="toolu_2", content="ok",
                                             is_error=True)])
    )

    assert builder.get("msg_9:0").result == {"content": "ok", "is_error": True,
                                             "details": None}


# Subagents ---------------------------------------------------------------


def test_subagent_messages_keep_parent_tool_use_id():
    builder = ConversationBuilder()
    parent = "toolu_task"

    events = feed(
        builder,
        message_start("msg_1"),
        block_start(0, {"type": "tool_use", "id": parent, "name": "Task", "input": {}}),
        assistant("msg_1", ToolUseBlock(id=parent, name="Task", input={"prompt": "p"})),
        block_stop(0),
        message_start("msg_sub", parent=parent),
        block_start(0, {"type": "text", "text": ""}, parent=parent),
        delta(0, {"type": "text_delta", "text": "sub"}, parent=parent),
        assistant("msg_sub", TextBlock(text="sub"), parent=parent),
        block_stop(0, parent=parent),
        assistant("msg_sub2", ToolUseBlock(id="toolu_s", name="Read", input={}), parent=parent),
    )

    assert builder.get("msg_1:0").parent_tool_use_id is None
    assert builder.get("msg_sub:0").parent_tool_use_id == parent
    assert builder.get("msg_sub2:0").parent_tool_use_id == parent
    assert events[-1].data["parent_tool_use_id"] == parent
    streaming_upsert = next(
        e for e in events if e.type == "item.upsert" and e.data["id"] == "msg_sub:0"
    )
    assert streaming_upsert.data["parent_tool_use_id"] == parent


# Errors ------------------------------------------------------------------


def test_authentication_error_becomes_error_notice():
    builder = ConversationBuilder()

    events = builder.handle(
        assistant("msg_e", TextBlock(text="Invalid API key · Please run /login"),
                  error="authentication_failed")
    )

    assert compact(events) == [("item.upsert", builder.items[0].id, "notice", None)]
    notice = builder.items[0]
    assert notice.level == "error"
    assert notice.text == "Falha de autenticação. Rode `claude` no terminal e faça /login."


def test_result_with_error_emits_notice_and_turn_result():
    builder = ConversationBuilder()

    events = builder.handle(
        result(subtype="error_max_turns", is_error=True, errors=["max turns reached"])
    )

    assert [e.type for e in events] == ["item.upsert", "turn.result"]
    notice = builder.items[0]
    assert notice.level == "error"
    assert "max turns reached" in notice.text
    assert events[1].data["is_error"] is True
    assert events[1].data["errors"] == ["max turns reached"]


def test_result_error_after_assistant_error_does_not_repeat_notice():
    builder = ConversationBuilder()

    feed(
        builder,
        assistant("msg_e", TextBlock(text="x"), error="authentication_failed"),
        result(is_error=True, result="Invalid API key"),
    )

    assert [i.type for i in builder.items] == ["notice"]


def test_interrupted_result_is_info_notice():
    builder = ConversationBuilder()

    builder.handle(
        result(subtype="error_during_execution", is_error=True,
               terminal_reason="aborted_streaming")
    )

    assert builder.items[0].level == "info"
    assert builder.items[0].text == "Interrompido."


def test_rate_limit_rejected_emits_error_notice_with_reset_time():
    builder = ConversationBuilder()
    resets_at = 1790000000

    events = builder.handle(
        RateLimitEvent(
            rate_limit_info=RateLimitInfo(status="rejected", resets_at=resets_at,
                                          rate_limit_type="five_hour"),
            uuid="r", session_id=SID,
        )
    )

    assert [e.type for e in events] == ["rate_limit", "item.upsert"]
    assert events[0].data == {"status": "rejected", "resets_at": resets_at,
                              "rate_limit_type": "five_hour"}
    notice = builder.items[0]
    assert notice.level == "error"
    assert datetime.fromtimestamp(resets_at, UTC).astimezone().strftime("%H:%M") in notice.text


def test_rate_limit_allowed_creates_no_item():
    builder = ConversationBuilder()

    events = builder.handle(
        RateLimitEvent(rate_limit_info=RateLimitInfo(status="allowed_warning"),
                       uuid="r", session_id=SID)
    )

    assert [e.type for e in events] == ["rate_limit"]
    assert builder.items == []


# Closing and unknown ------------------------------------------------------


def test_result_closes_items_left_open():
    builder = ConversationBuilder()
    feed(
        builder,
        message_start("msg_1"),
        block_start(0, {"type": "thinking", "thinking": ""}),
        delta(0, {"type": "thinking_delta", "thinking": "meio"}),
    )

    events = builder.handle(result())

    assert compact(events) == [
        ("item.upsert", "msg_1:0", "thinking", False),
        ("turn.result",),
    ]
    assert builder.get("msg_1:0") == ThinkingItem(id="msg_1:0", text="meio", streaming=False)


def test_unknown_message_is_ignored():
    builder = ConversationBuilder()

    assert builder.handle(object()) == []
    assert builder.handle(SystemMessage(subtype="task_progress", data={})) == []
    assert builder.handle(stream({"type": "ping"})) == []
    assert builder.handle(delta(5, {"type": "text_delta", "text": "órfão"})) == []
    assert builder.items == []


# Server tools ------------------------------------------------------------


def test_server_tool_blocks_become_tool_items():
    builder = ConversationBuilder()

    feed(
        builder,
        message_start("msg_1"),
        block_start(0, {"type": "server_tool_use", "id": "srvtoolu_1",
                        "name": "web_search", "input": {}}),
        assistant("msg_1", ServerToolUseBlock(id="srvtoolu_1", name="web_search",
                                              input={"query": "vue"})),
        block_stop(0),
        block_start(1, {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_1"}),
        assistant("msg_1", ServerToolResultBlock(tool_use_id="srvtoolu_1",
                                                 content={"type": "advisor_result"})),
        block_stop(1),
        block_start(2, {"type": "text", "text": ""}),
        assistant("msg_1", TextBlock(text="achei")),
        block_stop(2),
    )

    assert [i.id for i in builder.items] == ["msg_1:0", "msg_1:2"]
    tool = builder.get("msg_1:0")
    assert tool.name == "web_search"
    assert tool.input == {"query": "vue"}
    assert tool.result == {"content": {"type": "advisor_result"}, "is_error": False,
                           "details": None}


def test_server_tool_result_without_use_becomes_tool_item():
    builder = ConversationBuilder()

    builder.handle(
        assistant("msg_1", ServerToolResultBlock(tool_use_id="srvtoolu_9",
                                                 content={"type": "web_search_tool_result"}))
    )

    tool = builder.items[0]
    assert isinstance(tool, ToolItem)
    assert tool.name == "web_search_tool_result"


# Fake helpers produce what the builder expects ---------------------------


def test_fake_text_turn_converts_to_final_items():
    builder = ConversationBuilder()

    feed(builder, *text_turn(SID, "olá", thinking="pensando"))

    assert [(i.type, i.text, i.streaming) for i in builder.items] == [
        ("thinking", "pensando", False),
        ("text", "olá", False),
    ]


def test_fake_tool_turn_converts_to_tool_and_text():
    builder = ConversationBuilder()
    steps = tool_turn(SID, tool_name="Edit", tool_input={"file_path": "/p/b.py"},
                      tool_use_id="toolu_7", tool_use_result=WRITE_RESULT,
                      final_text="Editado.")

    feed(builder, *steps)

    tool, text = builder.items
    assert tool.type == "tool" and tool.name == "Edit"
    assert tool.input == {"file_path": "/p/b.py"}
    assert tool.result["details"] == WRITE_RESULT
    assert text.text == "Editado."
    assert tool.id.split(":")[0] != text.id.split(":")[0]
