"""When each conversation item was created (`at`), used by "Enquanto você estava fora"."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import SessionMessage, TextBlock, ToolUseBlock
from history_fakes import assistant_entry, user_entry

from claudio_maestro.agent.fake import response_messages, tool_result_message
from claudio_maestro.conversation import ConversationBuilder
from claudio_maestro.history import read_transcript_file

SID = "s-1"


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_builder(clock: Clock) -> ConversationBuilder:
    builder = ConversationBuilder()
    builder._wall_clock = clock
    return builder


def feed(builder: ConversationBuilder, messages) -> None:
    for message in messages:
        builder.handle(message)


def by_type(builder: ConversationBuilder, kind: str) -> list[dict[str, Any]]:
    return [i for i in builder.snapshot() if i["type"] == kind]


# Live ---------------------------------------------------------------------


def test_live_items_carry_the_moment_they_were_created():
    clock = Clock(1_000)
    builder = make_builder(clock)
    builder.add_user_message("oi")
    clock.now = 1_050
    feed(builder, response_messages(SID, [TextBlock(text="olá")]))
    clock.now = 1_080
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})], stop_reason="tool_use"
    ))
    builder.add_notice("info", "aviso")

    [user] = by_type(builder, "user")
    [text] = by_type(builder, "text")
    [tool] = by_type(builder, "tool")
    [notice] = by_type(builder, "notice")
    assert (user["at"], text["at"], tool["at"], notice["at"]) == (1_000, 1_050, 1_080, 1_080)


def test_a_rewritten_item_keeps_its_first_moment():
    clock = Clock(1_000)
    builder = make_builder(clock)
    feed(builder, response_messages(SID, [TextBlock(text="a")]))
    first = by_type(builder, "text")[0]["at"]

    clock.now = 5_000
    # The same message arrives again (final version of a streamed block).
    for item in list(builder.items):
        builder._put(type(item)(item.id, item.text + "!", False, item.parent_tool_use_id))

    assert by_type(builder, "text")[0]["at"] == first == 1_000


def test_a_tool_result_does_not_move_the_tool():
    clock = Clock(1_000)
    builder = make_builder(clock)
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="t1", name="Bash", input={})], stop_reason="tool_use"
    ))
    clock.now = 2_000
    builder.handle(tool_result_message("t1", "ok"))

    [tool] = by_type(builder, "tool")
    assert tool["result"] is not None
    assert tool["at"] == 1_000


# History --------------------------------------------------------------------


def history() -> list[SessionMessage]:
    return [
        user_entry("faça", uuid="u1"),
        assistant_entry({"type": "text", "text": "feito"}, "m1"),
        assistant_entry({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}, "m2"),
    ]


def test_history_items_take_the_time_of_their_entry():
    builder = ConversationBuilder()
    builder.load_history(history(), entry_times={"u1": 100, "a-m1": 200, "a-m2": 300})

    assert [i["at"] for i in builder.snapshot()] == [100, 200, 300]


def test_history_without_times_leaves_them_null():
    clock = Clock(9_999)
    builder = make_builder(clock)
    builder.load_history(history())

    assert [i["at"] for i in builder.snapshot()] == [None, None, None]


def test_an_entry_without_time_is_null_even_when_others_have_one():
    builder = ConversationBuilder()
    builder.load_history(history(), entry_times={"u1": 100})

    assert [i["at"] for i in builder.snapshot()] == [100, None, None]


def test_items_after_a_history_load_use_the_clock_again():
    clock = Clock(7_000)
    builder = make_builder(clock)
    builder.load_history(history(), entry_times={"u1": 100})
    builder.add_user_message("mais")

    assert by_type(builder, "user")[-1]["at"] == 7_000


# Reading the transcript ------------------------------------------------------


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def entry(kind: str, uuid: str, parent: str | None, ts: float | None, **fields: Any) -> str:
    data: dict[str, Any] = {"type": kind, "uuid": uuid, "parentUuid": parent, "sessionId": "s", **fields}
    if ts is not None:
        data["timestamp"] = iso(ts)
    return json.dumps(data) + "\n"


def test_transcript_reads_the_time_of_each_entry(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        entry("user", "u1", None, 1_000, message={"role": "user", "content": "oi"})
        + entry("assistant", "a1", "u1", 1_010,
                message={"id": "m1", "role": "assistant", "content": [{"type": "text", "text": "x"}]})
        + entry("user", "u2", "a1", None, message={"role": "user", "content": "sem hora"})
    )

    times = read_transcript_file(path).entry_times

    assert times == {"u1": 1_000, "a1": 1_010}
