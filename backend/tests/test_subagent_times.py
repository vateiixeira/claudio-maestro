"""When each subagent started and was last active (`started_at`, `last_activity_at`)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import ToolUseBlock
from history_fakes import assistant_entry, user_entry

from claudio_maestro.agent.fake import (
    response_messages,
    task_notification_message,
    task_progress_message,
    task_started_message,
    task_updated_message,
    tool_result_message,
)
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


def feed(builder: ConversationBuilder, messages) -> list:
    events = []
    for message in messages:
        events.extend(builder.handle(message))
    return events


def agent_call() -> list:
    return response_messages(
        SID,
        [ToolUseBlock(id="toolu_agent", name="Agent",
                      input={"description": "Explorar", "subagent_type": "Explore", "prompt": "x"})],
        stop_reason="tool_use",
    )


def sub_of(builder: ConversationBuilder) -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["name"] == "Agent"]
    return item["subagent"]


# Live ---------------------------------------------------------------------


def test_live_subagent_starts_with_the_time_it_was_seen():
    clock = Clock(1_000.4)
    builder = make_builder(clock)

    feed(builder, agent_call())

    sub = sub_of(builder)
    assert sub["started_at"] == 1_000
    assert sub["last_activity_at"] == 1_000


def test_progress_moves_last_activity_but_not_the_start():
    clock = Clock(1_000)
    builder = make_builder(clock)
    feed(builder, agent_call())

    clock.now = 1_300
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent")])
    assert sub_of(builder)["started_at"] == 1_000
    assert sub_of(builder)["last_activity_at"] == 1_300

    clock.now = 1_700
    feed(builder, [task_progress_message(SID, "task-1", "toolu_agent")])
    assert sub_of(builder)["last_activity_at"] == 1_700
    assert sub_of(builder)["started_at"] == 1_000


def test_status_changes_and_the_result_count_as_activity():
    clock = Clock(1_000)
    builder = make_builder(clock)
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent")])

    clock.now = 1_100
    feed(builder, [task_updated_message(SID, "task-1", "completed")])
    assert sub_of(builder)["last_activity_at"] == 1_100

    clock.now = 1_200
    feed(builder, [task_notification_message(SID, "task-1", "toolu_agent")])
    assert sub_of(builder)["last_activity_at"] == 1_200

    clock.now = 1_300
    feed(builder, [tool_result_message("toolu_agent", "ok")])
    assert sub_of(builder)["last_activity_at"] == 1_300


def test_sending_a_message_to_a_finished_subagent_restarts_its_clock():
    clock = Clock(1_000)
    builder = make_builder(clock)
    feed(builder, agent_call())
    feed(builder, [task_started_message(SID, "task-1", "toolu_agent"),
                   tool_result_message("toolu_agent", "ok", tool_use_result={"agentId": "task-1"})])
    feed(builder, [task_updated_message(SID, "task-1", "completed")])

    clock.now = 5_000
    feed(builder, response_messages(
        SID, [ToolUseBlock(id="toolu_send", name="SendMessage",
                           input={"to": "task-1", "message": "mais"})], stop_reason="tool_use"))
    feed(builder, [tool_result_message("toolu_send", "ok",
                                       tool_use_result={"resumedAgentId": "task-1"})])

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["started_at"] == 5_000
    assert sub["last_activity_at"] == 5_000


# History --------------------------------------------------------------------


def history_entries() -> list:
    return [
        user_entry("faça"),
        assistant_entry({"type": "tool_use", "id": "toolu_1", "name": "Agent",
                         "input": {"description": "x", "prompt": "y"}}, "m1"),
        user_entry([{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}], uuid="u2"),
    ]


def test_history_uses_the_timestamps_of_the_transcript():
    builder = ConversationBuilder()
    builder.load_history(
        history_entries(),
        tool_times={"toolu_1": {"started_at": 2_000, "ended_at": 2_450}},
    )

    sub = sub_of(builder)
    assert sub["started_at"] == 2_000
    assert sub["last_activity_at"] == 2_450


def test_history_without_timestamps_leaves_the_fields_null():
    builder = ConversationBuilder()
    builder.load_history(history_entries())

    sub = sub_of(builder)
    assert sub["started_at"] is None
    assert sub["last_activity_at"] is None


def test_history_without_a_result_has_only_the_start():
    builder = ConversationBuilder()
    builder.load_history(
        history_entries()[:2], tool_times={"toolu_1": {"started_at": 2_000}}, live=True,
    )

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["started_at"] == 2_000
    assert sub["last_activity_at"] is None


def test_live_progress_after_a_reattach_sets_the_activity():
    clock = Clock(9_000)
    builder = make_builder(clock)
    builder.load_history(
        history_entries()[:2], tool_times={"toolu_1": {"started_at": 2_000}}, live=True,
    )
    feed(builder, [task_progress_message(SID, "task-1", "toolu_1")])

    sub = sub_of(builder)
    assert sub["started_at"] == 2_000
    assert sub["last_activity_at"] == 9_000


# Reading the transcript ------------------------------------------------------


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def entry(kind: str, uuid: str, parent: str | None, ts: float | None, **fields: Any) -> str:
    data: dict[str, Any] = {"type": kind, "uuid": uuid, "parentUuid": parent, "sessionId": "s", **fields}
    if ts is not None:
        data["timestamp"] = iso(ts)
    return json.dumps(data) + "\n"


def test_transcript_reads_the_times_of_agent_calls(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    agent = {"type": "tool_use", "id": "toolu_a", "name": "Agent", "input": {"prompt": "x"}}
    task = {"type": "tool_use", "id": "toolu_t", "name": "Task", "input": {"prompt": "x"}}
    read = {"type": "tool_use", "id": "toolu_r", "name": "Read", "input": {}}
    path.write_text(
        entry("user", "u1", None, 1_000, message={"role": "user", "content": "oi"})
        + entry("assistant", "a1", "u1", 1_010,
                message={"id": "m1", "role": "assistant", "content": [agent]})
        + entry("assistant", "a2", "a1", 1_011,
                message={"id": "m2", "role": "assistant", "content": [task]})
        + entry("assistant", "a3", "a2", 1_012,
                message={"id": "m3", "role": "assistant", "content": [read]})
        + entry("user", "u2", "a3", 1_500, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_a", "content": "ok"}]})
        + entry("user", "u3", "u2", None, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_t", "content": "ok"}]})
    )

    times = read_transcript_file(path).tool_times

    assert times["toolu_a"] == {"started_at": 1_010, "ended_at": 1_500}
    # No timestamp on the result: only the start is known.
    assert times["toolu_t"] == {"started_at": 1_011}
    assert "toolu_r" not in times
