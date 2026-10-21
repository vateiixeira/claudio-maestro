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
