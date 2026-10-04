"""Subagents that ended while the app was away: the transcript's `<task-notification>`
gives the final status of cards rebuilt in live mode (a reattached session)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from history_fakes import assistant_entry, user_entry

from claudio_maestro.conversation import SUBAGENT_MAX_SECONDS, ConversationBuilder
from claudio_maestro.history import read_transcript_file

ASYNC_DETAILS = {"isAsync": True, "status": "async_launched", "agentId": "agent-1"}
LAUNCHED = {"content": "Async agent launched successfully.", "is_error": None,
            "details": ASYNC_DETAILS}


def agent_entries(tool_use_id: str = "toolu_1") -> list:
    return [
        user_entry("faça"),
        assistant_entry({"type": "tool_use", "id": tool_use_id, "name": "Agent",
                         "input": {"description": "x", "prompt": "y",
                                   "run_in_background": True}}, f"m-{tool_use_id}"),
    ]


def ending(status: str = "completed", at: int | None = 2_000, task_id: str = "agent-1",
           summary: str | None = "Agent finished") -> dict[str, Any]:
    return {"status": status, "at": at, "task_id": task_id, "summary": summary}


def sub_of(builder: ConversationBuilder, tool_use_id: str = "toolu_1") -> dict:
    [item] = [i for i in builder.snapshot() if i["type"] == "tool" and i["id"] and
              i["tool_use_id"] == tool_use_id]
    return item["subagent"]


NOW = 5_000.0


def load(live: bool = True, endings=None, resumes=None, times=None, entries=None,
         results=None, now: float = NOW) -> ConversationBuilder:
    builder = ConversationBuilder()
    builder._wall_clock = lambda: now
    builder.load_history(
        entries or agent_entries(),
        results if results is not None else {"toolu_1": LAUNCHED},
        live=live,
        tool_times=times or {"toolu_1": {"started_at": 1_000, "ended_at": 1_001}},
        task_endings=endings, task_resumes=resumes,
    )
    return builder


# load_history ---------------------------------------------------------------


def test_live_history_applies_the_notification_status():
    builder = load(endings={"toolu_1": ending("completed", at=2_000)})

    sub = sub_of(builder)
    assert sub["status"] == "completed"
    assert sub["task_id"] == "agent-1"
    assert sub["summary"] == "Agent finished"
    assert sub["last_activity_at"] == 2_000
    assert sub["started_at"] == 1_000
    assert not builder.subagents_running


@pytest.mark.parametrize(("raw", "shown"), [
    ("failed", "failed"), ("killed", "stopped"), ("stopped", "stopped"),
])
def test_notification_statuses_are_mapped(raw, shown):
    builder = load(endings={"toolu_1": ending(raw)})

    assert sub_of(builder)["status"] == shown
    assert not builder.subagents_running


def test_live_history_without_notification_keeps_running():
    builder = load(endings=None)

    assert sub_of(builder)["status"] == "running"
    assert builder.subagents_running


def test_live_history_card_without_notification_gets_the_task_id_from_the_result():
    # The "Stop subagents" button only reaches subagents that have a task_id.
    builder = load(endings=None)

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["task_id"] == "agent-1"
    assert "agent-1" in builder.running_task_ids()


SYNC_RESULT = {"content": "done", "is_error": None,
               "details": {"status": "completed", "agentId": "agent-1", "result": "done"}}


def test_live_history_finished_sync_subagent_is_completed_without_task_id():
    # A synchronous Agent result also carries `agentId`, but it is not a running task.
    builder = load(endings=None, results={"toolu_1": SYNC_RESULT})

    sub = sub_of(builder)
    assert sub["status"] == "completed"
    assert sub["task_id"] is None
    assert builder.running_task_ids() == []
    assert not builder.subagents_running


def test_live_history_failed_sync_subagent_is_failed():
    result = {**SYNC_RESULT, "is_error": True}
    builder = load(endings=None, results={"toolu_1": result})

    assert sub_of(builder)["status"] == "failed"
    assert not builder.subagents_running


def test_live_history_sync_subagent_resumed_later_runs_again():
    builder = load(endings=None, results={"toolu_1": SYNC_RESULT}, resumes={"agent-1": 3_000})

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["task_id"] == "agent-1"
    assert builder.running_task_ids() == ["agent-1"]


def test_live_history_result_without_details_stays_running():
    result = {"content": "Async agent launched successfully.", "is_error": None, "details": None}
    builder = load(endings=None, results={"toolu_1": result})

    assert sub_of(builder)["status"] == "running"
    assert builder.subagents_running


def test_live_history_async_flag_alone_counts_as_background():
    result = {"content": "ok", "is_error": None,
              "details": {"isAsync": True, "agentId": "agent-1"}}
    builder = load(endings=None, results={"toolu_1": result})

    assert sub_of(builder)["status"] == "running"
    assert builder.running_task_ids() == ["agent-1"]


def test_task_id_of_the_result_does_not_replace_the_one_from_a_notification():
    builder = load(endings={"toolu_1": ending("completed", at=2_000, task_id="agent-2")},
                   resumes={"agent-2": 3_000})

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["task_id"] == "agent-2"
    assert builder.running_task_ids() == ["agent-2"]


def test_task_id_already_on_the_card_is_kept_when_the_history_loads_again():
    builder = load(endings=None)
    builder._subagents["toolu_1"]["task_id"] = "agent-7"

    builder.load_history(
        agent_entries(), {"toolu_1": LAUNCHED}, live=True,
        tool_times={"toolu_1": {"started_at": 1_000}},
    )

    assert sub_of(builder)["task_id"] == "agent-7"


def test_notification_of_another_agent_does_not_end_this_one():
    builder = load(endings={"toolu_other": ending(task_id="agent-9")})

    assert sub_of(builder)["status"] == "running"


def test_notification_found_by_task_id_when_it_names_another_tool_call():
    # After a resume the CLI may name the SendMessage call, not the Agent one.
    builder = load(endings={"toolu_send": ending("completed", task_id="agent-1")})

    assert sub_of(builder)["status"] == "completed"


def test_resume_after_the_notification_keeps_it_running_when_live():
    builder = load(endings={"toolu_1": ending("completed", at=2_000)},
                   resumes={"agent-1": 3_000})

    sub = sub_of(builder)
    assert sub["status"] == "running"
    assert sub["started_at"] == 3_000
    assert builder.subagents_running


def test_notification_after_the_resume_ends_it_again():
    builder = load(endings={"toolu_1": ending("completed", at=4_000)},
                   resumes={"agent-1": 3_000})

    assert sub_of(builder)["status"] == "completed"


def test_resume_before_the_notification_does_not_matter():
    builder = load(endings={"toolu_1": ending("completed", at=2_000)},
                   resumes={"agent-1": 1_500})

    assert sub_of(builder)["status"] == "completed"


def test_notification_applies_when_not_live_too():
    builder = load(live=False, endings={"toolu_1": ending("failed")}, results={})

    assert sub_of(builder)["status"] == "failed"


def test_not_live_resume_without_a_result_is_stopped():
    builder = load(live=False, endings={"toolu_1": ending("completed", at=2_000)},
                   resumes={"agent-1": 3_000}, results={})

    assert sub_of(builder)["status"] == "stopped"


def test_notification_makes_a_later_live_notification_harmless():
    builder = load(endings={"toolu_1": ending("completed")})

    assert sub_of(builder)["status"] == "completed"
    assert not builder.subagents_running


# Three hour guard -----------------------------------------------------------


def test_old_subagent_without_notification_no_longer_counts():
    now = 1_000_000.0
    builder = load(now=now, times={"toolu_1": {"started_at": int(now) - SUBAGENT_MAX_SECONDS - 600}})

    assert sub_of(builder)["status"] == "running"
    assert not builder.subagents_running


def test_recent_subagent_without_notification_counts():
    now = 1_000_000.0
    builder = load(now=now, times={"toolu_1": {"started_at": int(now) - 600}})

    assert builder.subagents_running


def test_subagent_resumed_long_after_its_first_start_counts():
    now = 1_000_000.0
    builder = load(
        now=now, times={"toolu_1": {"started_at": int(now) - SUBAGENT_MAX_SECONDS - 600}},
        endings={"toolu_1": ending("completed", at=int(now) - 3_000)},
        resumes={"agent-1": int(now) - 60},
    )

    assert builder.subagents_running


# read_transcript_file -------------------------------------------------------


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def notification(tool_use_id: str, status: str = "completed", task_id: str = "agent-1",
                 summary: str = "Agent \"x\" finished") -> str:
    return (
        "<task-notification>\n"
        f"<task-id>{task_id}</task-id>\n"
        f"<tool-use-id>{tool_use_id}</tool-use-id>\n"
        "<output-file>/tmp/x.output</output-file>\n"
        f"<status>{status}</status>\n"
        f"<summary>{summary}</summary>\n"
        "<result>algo <status>failed</status> dentro do resultado</result>\n"
        "</task-notification>"
    )


def line(data: dict[str, Any]) -> str:
    return json.dumps(data) + "\n"


def queue(content: str, ts: float, operation: str = "enqueue") -> str:
    return line({"type": "queue-operation", "operation": operation, "timestamp": iso(ts),
                 "sessionId": "s", "content": content})


def user_line(uuid: str, parent: str | None, content: Any, ts: float, **extra: Any) -> str:
    return line({"type": "user", "uuid": uuid, "parentUuid": parent, "sessionId": "s",
                 "timestamp": iso(ts), "message": {"role": "user", "content": content},
                 **extra})


def test_transcript_reads_notifications_from_queue_operations(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(queue(notification("toolu_a", "completed"), 1_500))

    endings = read_transcript_file(path).task_endings

    assert endings == {"toolu_a": {
        "status": "completed", "at": 1_500, "task_id": "agent-1",
        "summary": "Agent \"x\" finished",
    }}


def test_transcript_reads_notifications_from_user_messages(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        user_line("u1", None, "oi", 1_000)
        + user_line("u2", "u1", notification("toolu_a", "failed"), 1_600)
        + user_line("u3", "u2", [{"type": "text", "text": notification("toolu_b", "killed",
                                                                        task_id="agent-2")}], 1_700)
    )

    endings = read_transcript_file(path).task_endings

    assert endings["toolu_a"]["status"] == "failed"
    assert endings["toolu_a"]["at"] == 1_600
    assert endings["toolu_b"]["status"] == "killed"
    assert endings["toolu_b"]["task_id"] == "agent-2"


def test_the_same_notification_in_both_places_counts_once(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        queue(notification("toolu_a"), 1_500)
        + user_line("u2", None, notification("toolu_a"), 1_501)
        + queue(notification("toolu_a"), 1_500, operation="remove")
    )

    endings = read_transcript_file(path).task_endings

    assert list(endings) == ["toolu_a"]
    assert endings["toolu_a"]["at"] == 1_501


def test_the_latest_notification_of_a_tool_call_wins(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        queue(notification("toolu_a", "completed"), 3_000)
        + queue(notification("toolu_a", "failed"), 2_000)
    )

    assert read_transcript_file(path).task_endings["toolu_a"]["status"] == "completed"


def test_a_user_message_that_only_quotes_a_notification_is_ignored(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(user_line("u1", None, "veja: " + notification("toolu_a"), 1_000))

    assert read_transcript_file(path).task_endings == {}


def test_transcript_reads_the_resumes(tmp_path: Path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        user_line("u1", None, [{"type": "tool_result", "tool_use_id": "toolu_send",
                                "content": "ok"}], 3_000,
                  toolUseResult={"success": True, "resumedAgentId": "agent-1"})
        + user_line("u2", "u1", [{"type": "tool_result", "tool_use_id": "toolu_send2",
                                  "content": "ok"}], 3_500,
                    toolUseResult={"success": True, "resumedAgentId": "agent-1"})
    )

    assert read_transcript_file(path).task_resumes == {"agent-1": 3_500}
