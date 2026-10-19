"""Output tokens of the running turn: summed per main-agent message, zeroed at the turn's end."""

from types import SimpleNamespace
from typing import Any

from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock

from claudio_maestro.agent.fake import response_messages, text_turn
from claudio_maestro.conversation import ConversationBuilder, Event

SID = "5e1d9c3a-2b4f-4a6e-8c7d-9e0f1a2b3c4d"


def stream(event: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return StreamEvent(uuid="u", session_id=SID, event=event, parent_tool_use_id=parent)


def start(message_id: str, parent: str | None = None) -> StreamEvent:
    return stream({"type": "message_start", "message": {"id": message_id}}, parent)


def message_delta(tokens: int | None, parent: str | None = None) -> StreamEvent:
    event: dict[str, Any] = {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
    if tokens is not None:
        event["usage"] = {"output_tokens": tokens}
    return stream(event, parent)


def result() -> ResultMessage:
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
        session_id=SID, total_cost_usd=0.0, usage={},
    )


def feed(builder: ConversationBuilder, *messages: Any) -> list[Event]:
    events: list[Event] = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def token_events(events: list[Event]) -> list[int]:
    return [e.data["output_tokens"] for e in events if e.type == "turn.tokens"]


def test_starts_at_zero():
    assert ConversationBuilder().turn_output_tokens == 0


def test_message_delta_sets_the_total_and_emits_an_event():
    builder = ConversationBuilder()
    events = feed(builder, start("m1"), message_delta(120))
    assert builder.turn_output_tokens == 120
    assert token_events(events) == [120]


def test_sums_the_messages_of_the_turn():
    builder = ConversationBuilder()
    events = feed(builder, start("m1"), message_delta(120), start("m2"), message_delta(80))
    assert builder.turn_output_tokens == 200
    assert token_events(events) == [120, 200]


def test_the_same_message_counts_its_last_value_only():
    builder = ConversationBuilder()
    events = feed(builder, start("m1"), message_delta(50), message_delta(120))
    assert builder.turn_output_tokens == 120
    assert token_events(events) == [50, 120]


def test_unchanged_total_emits_nothing():
    builder = ConversationBuilder()
    feed(builder, start("m1"), message_delta(50))
    assert token_events(feed(builder, message_delta(50))) == []


def test_message_delta_without_usage_is_ignored():
    builder = ConversationBuilder()
    assert token_events(feed(builder, start("m1"), message_delta(None))) == []
    assert builder.turn_output_tokens == 0


def test_subagent_messages_do_not_count():
    builder = ConversationBuilder()
    events = feed(builder, start("m1", "toolu_1"), message_delta(500, "toolu_1"))
    assert builder.turn_output_tokens == 0
    assert token_events(events) == []


def test_result_zeroes_the_total_and_tells_the_client():
    builder = ConversationBuilder()
    feed(builder, start("m1"), message_delta(120))
    events = feed(builder, result())
    assert builder.turn_output_tokens == 0
    assert token_events(events) == [0]
    types = [e.type for e in events]
    assert types.index("turn.tokens") < types.index("turn.result")


def test_result_without_tokens_emits_no_event():
    builder = ConversationBuilder()
    assert token_events(feed(builder, result())) == []


def test_next_turn_starts_from_zero():
    builder = ConversationBuilder()
    feed(builder, start("m1"), message_delta(120), result())
    feed(builder, start("m2"), message_delta(30))
    assert builder.turn_output_tokens == 30


def test_close_open_items_zeroes_a_failed_turn():
    builder = ConversationBuilder()
    feed(builder, start("m1"), message_delta(120))
    events = builder.close_open_items()
    assert builder.turn_output_tokens == 0
    assert token_events(events) == [0]


def test_assistant_message_usage_counts_when_there_was_no_stream():
    builder = ConversationBuilder()
    events = feed(builder, AssistantMessage(
        content=[TextBlock("oi")], model="m", message_id="m1", usage={"output_tokens": 40},
    ))
    assert builder.turn_output_tokens == 40
    assert token_events(events) == [40]


def test_assistant_usage_never_lowers_what_the_stream_reported():
    builder = ConversationBuilder()
    feed(builder, start("m1"), message_delta(120))
    feed(builder, AssistantMessage(
        content=[TextBlock("oi")], model="m", message_id="m1", usage={"output_tokens": 1},
    ))
    assert builder.turn_output_tokens == 120


def test_subagent_assistant_usage_does_not_count():
    builder = ConversationBuilder()
    feed(builder, AssistantMessage(
        content=[TextBlock("oi")], model="m", parent_tool_use_id="toolu_1", message_id="m1",
        usage={"output_tokens": 40},
    ))
    assert builder.turn_output_tokens == 0


def history_entry(uuid: str, message_id: str) -> SimpleNamespace:
    message = {"id": message_id, "model": "m", "content": [{"type": "text", "text": "olá"}]}
    return SimpleNamespace(type="assistant", uuid=uuid, message=message)


def test_replayed_history_message_is_not_counted():
    builder = ConversationBuilder()
    builder.load_history([history_entry("a1", "m1")], live=True)
    events = feed(
        builder,
        start("m1"),
        message_delta(300),
        AssistantMessage(content=[TextBlock("olá")], model="m", message_id="m1", uuid="a1",
                         usage={"output_tokens": 300}),
        AssistantMessage(content=[TextBlock("olá")], model="m", message_id="m1", uuid="other",
                         usage={"output_tokens": 300}),
    )
    assert builder.turn_output_tokens == 0
    assert token_events(events) == []


def test_new_message_after_history_counts_and_replay_does_not_double_it():
    builder = ConversationBuilder()
    builder.load_history([history_entry("a1", "m1")], live=True)
    feed(builder, start("m2"), message_delta(70))
    # The agentd replays the same stream after a reconnection: same message id, same total.
    feed(builder, start("m2"), message_delta(70))
    assert builder.turn_output_tokens == 70


def test_fake_helper_puts_usage_in_the_message_delta():
    messages = response_messages(SID, [TextBlock("oi")], output_tokens=1600)
    deltas = [m for m in messages if isinstance(m, StreamEvent) and m.event["type"] == "message_delta"]
    assert deltas[0].event["usage"] == {"output_tokens": 1600}
    builder = ConversationBuilder()
    events = feed(builder, *messages)
    assert builder.turn_output_tokens == 1600
    assert token_events(events) == [1600]


def test_fake_text_turn_defaults_to_no_usage():
    builder = ConversationBuilder()
    events = feed(builder, *text_turn(SID, "oi"))
    assert token_events(events) == []


# After a restart: the open turn's tokens come back from the saved conversation -----


def user_entry(uuid: str, content: Any) -> SimpleNamespace:
    return SimpleNamespace(type="user", uuid=uuid, message={"content": content})


def usage_entry(uuid: str, message_id: str, tokens: int | None) -> SimpleNamespace:
    message: dict[str, Any] = {"id": message_id, "model": "m", "content": [{"type": "text", "text": "x"}]}
    if tokens is not None:
        message["usage"] = {"output_tokens": tokens}
    return SimpleNamespace(type="assistant", uuid=uuid, message=message)


TOOL_RESULT = [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}]


def test_reattached_turn_sums_the_saved_messages_after_the_last_user_message():
    builder = ConversationBuilder()
    builder.load_history([
        user_entry("u0", "antes"),
        usage_entry("a0", "m0", 900),
        user_entry("u1", "faça isto"),
        usage_entry("a1", "m1", 100),
        user_entry("u2", TOOL_RESULT),
        usage_entry("a2", "m2", 50),
    ], live=True)
    assert builder.turn_output_tokens == 150


def test_saved_blocks_of_one_message_count_once():
    builder = ConversationBuilder()
    builder.load_history([
        user_entry("u1", "faça"),
        usage_entry("a1", "m1", 20),
        usage_entry("a2", "m1", 80),
    ], live=True)
    assert builder.turn_output_tokens == 80


def test_a_user_message_with_text_blocks_starts_the_count_again():
    builder = ConversationBuilder()
    builder.load_history([
        usage_entry("a0", "m0", 900),
        user_entry("u1", [{"type": "text", "text": "faça"}]),
        usage_entry("a1", "m1", 10),
    ], live=True)
    assert builder.turn_output_tokens == 10


def test_saved_messages_without_usage_count_zero():
    builder = ConversationBuilder()
    builder.load_history([user_entry("u1", "faça"), usage_entry("a1", "m1", None)], live=True)
    assert builder.turn_output_tokens == 0


def test_history_of_a_finished_session_does_not_count():
    builder = ConversationBuilder()
    builder.load_history([user_entry("u1", "faça"), usage_entry("a1", "m1", 100)])
    assert builder.turn_output_tokens == 0


def test_replay_after_reattach_does_not_count_saved_messages_twice():
    builder = ConversationBuilder()
    builder.load_history([user_entry("u1", "faça"), usage_entry("a1", "m1", 100)], live=True)
    feed(
        builder,
        start("m1"),
        message_delta(100),
        AssistantMessage(content=[TextBlock("x")], model="m", message_id="m1", uuid="a1",
                         usage={"output_tokens": 100}),
    )
    assert builder.turn_output_tokens == 100
    feed(builder, start("m2"), message_delta(30))
    assert builder.turn_output_tokens == 130
