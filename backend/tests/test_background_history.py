"""Real JSONL parser inputs for background launch timing and notifications."""

import pytest
from test_subagent_endings import notification, queue
from test_subagent_times import entry

from claudio_maestro.history import read_transcript_file


@pytest.mark.parametrize("name,detail_key", [("Bash", "backgroundTaskId"), ("Monitor", "taskId")])
def test_transcript_reads_background_call_times_and_launch_ids(tmp_path, name, detail_key):
    path = tmp_path / "s.jsonl"
    path.write_text(
        entry("user", "u1", None, 1000, message={"role": "user", "content": "oi"})
        + entry("assistant", "a1", "u1", 1010, message={"id": "m1", "role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_bg", "name": name,
             "input": {"command": "sleep 600", "run_in_background": True}}]})
        + entry("user", "u2", "a1", 1011, toolUseResult={detail_key: "task-1"},
                message={"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_bg", "content": "launched"}]})
    )
    saved = read_transcript_file(path)
    assert saved.tool_times == {"toolu_bg": {"started_at": 1010, "ended_at": 1011}}
    assert saved.tool_results["toolu_bg"]["details"] == {detail_key: "task-1"}


def test_transcript_accepts_ending_with_only_task_id(tmp_path):
    path = tmp_path / "s.jsonl"
    text = notification("toolu_bg", task_id="task-1").replace(
        "<tool-use-id>toolu_bg</tool-use-id>\n", "")
    path.write_text(queue(text, 1500))
    assert read_transcript_file(path).task_endings == {"task-1": {
        "status": "completed", "at": 1500, "task_id": "task-1", "summary": 'Agent "x" finished'}}


def test_monitor_events_without_status_do_not_end_tasks(tmp_path):
    path = tmp_path / "s.jsonl"
    intermediate = ("<task-notification><task-id>task-1</task-id><event>change</event>"
                    "</task-notification>")
    path.write_text(queue(intermediate, 1500))
    assert read_transcript_file(path).task_endings == {}
    path.write_text(queue(notification("toolu_bg", task_id="task-1"), 1400)
                    + queue(intermediate, 1500))
    assert read_transcript_file(path).task_endings["toolu_bg"]["status"] == "completed"


STOPPED = {"message": "Successfully stopped task: task-1 (sleep 600)", "task_id": "task-1",
           "task_type": "local_bash", "command": "sleep 600"}


def task_stop(details, *, at=1600, is_error=False, name="TaskStop"):
    """A stop call by the model and its result, as the CLI writes them."""
    return (
        entry("assistant", "a9", None, at - 1, message={"id": "m9", "role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_stop", "name": name, "input": {"task_id": "task-1"}}]})
        + entry("user", "u9", "a9", at, toolUseResult=details, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_stop", "content": "stopped",
             "is_error": is_error}]})
    )


def test_task_stop_ends_the_task_it_names(tmp_path):
    """The CLI writes no `<task-notification>` for a task the model stopped."""
    path = tmp_path / "s.jsonl"
    path.write_text(task_stop(STOPPED))
    assert read_transcript_file(path).task_endings == {"task-1": {
        "status": "stopped", "at": 1600, "task_id": "task-1", "summary": None}}


@pytest.mark.parametrize("details,is_error,name", [
    ("Error: No task found with ID: task-1", True, "TaskStop"),
    (STOPPED, True, "TaskStop"),
    (STOPPED, False, "Read"),
    ({"message": "ok"}, False, "TaskStop"),
])
def test_only_a_successful_task_stop_ends_a_task(tmp_path, details, is_error, name):
    path = tmp_path / "s.jsonl"
    path.write_text(task_stop(details, is_error=is_error, name=name))
    assert read_transcript_file(path).task_endings == {}


@pytest.mark.parametrize("notified_at,status", [(1500, "stopped"), (1700, "completed")])
def test_the_latest_of_stop_and_notification_wins(tmp_path, notified_at, status):
    """Same task id, whatever comes first in the file."""
    path = tmp_path / "s.jsonl"
    text = notification("toolu_bg", task_id="task-1").replace(
        "<tool-use-id>toolu_bg</tool-use-id>\n", "")
    path.write_text(task_stop(STOPPED, at=1600) + queue(text, notified_at))
    assert read_transcript_file(path).task_endings["task-1"]["status"] == status
