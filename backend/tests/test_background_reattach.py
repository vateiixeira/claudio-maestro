"""Reattached commands protect idle sessions, without reviving older processes."""

import time
from types import SimpleNamespace

import pytest
from history_fakes import assistant_entry, user_entry
from test_finishing_sessions import history_env  # noqa: F401
from test_sessions import wait_until
from test_subagent_endings import notification, queue
from test_subagent_times import entry

from claudio_maestro.agent.fake import (
    bash_task_notification_message,
    monitor_task_notification_message,
)
from claudio_maestro.conversation import SUBAGENT_MAX_SECONDS
from claudio_maestro.history import Transcript, read_transcript_file

TOOL = "toolu_background"
TASK = "task-background"


def transcript(*, name="Bash", age=60, timings=True, ending=None, result=True,
               error=False, details=True, background=True):
    input_ = {"command": "sleep 600"}
    if name == "Bash" and background:
        input_["run_in_background"] = True
    launch = {"backgroundTaskId" if name == "Bash" else "taskId": TASK}
    return Transcript(
        messages=[user_entry("oi"), assistant_entry({
            "type": "tool_use", "id": TOOL, "name": name, "input": input_}, "m1")],
        tool_results={TOOL: {"content": "launched", "is_error": error,
                             "details": launch if details else None}} if result else {},
        tool_times={TOOL: {"started_at": int(time.time()) - age}} if timings else {},
        task_endings=ending or {},
    )


def setup_session(history_env, saved, **kwargs):
    env = history_env(read_transcript=lambda *args: saved, **kwargs)
    sid = env.add_old_session()
    return env, env.manager.get(sid)


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
async def test_reattach_keeps_an_open_background_command_running(history_env, name):
    _, session = setup_session(history_env, transcript(name=name))
    await session.ensure_history(live=True, process_started_at=time.time() - 120)
    assert session.subagents_running
    assert session.builder.running_task_ids() == [TASK]
    [tool] = [i for i in session.builder.snapshot() if i["type"] == "tool"]
    assert tool["background"] == {"task_id": TASK, "status": "running", "summary": None}
    # A later event with only task_id must find the restored call.
    notification = (bash_task_notification_message if name == "Bash"
                    else monitor_task_notification_message)
    session.builder.handle(notification(session.session_id, TASK, None))
    assert not session.subagents_running


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("key", [TOOL, TASK, "other-tool"])
async def test_reattach_does_not_revive_a_finished_command(history_env, name, key):
    saved = transcript(name=name, ending={key: {
        "status": "completed", "task_id": TASK, "at": int(time.time()), "summary": "fim"}})
    _, session = setup_session(history_env, saved)
    await session.ensure_history(live=True, process_started_at=time.time() - 120)
    assert not session.subagents_running


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
async def test_reattach_skips_commands_from_an_earlier_process(history_env, name):
    _, session = setup_session(history_env, transcript(name=name, age=600))
    await session.ensure_history(live=True, process_started_at=time.time() - 120)
    assert not session.subagents_running


@pytest.mark.anyio
@pytest.mark.parametrize("timings", [True, False])
async def test_unknown_process_start_counts_commands_even_without_times(history_env, timings):
    _, session = setup_session(history_env, transcript(timings=timings))
    await session.ensure_history(live=True, process_started_at=None)
    assert session.subagents_running


@pytest.mark.anyio
async def test_known_process_start_skips_commands_without_times(history_env):
    _, session = setup_session(history_env, transcript(timings=False))
    await session.ensure_history(live=True, process_started_at=time.time() - 120)
    assert not session.subagents_running


@pytest.mark.anyio
async def test_process_start_has_two_second_tolerance(history_env):
    _, session = setup_session(history_env, transcript(age=121))
    await session.ensure_history(live=True, process_started_at=int(time.time()) - 120)
    assert session.subagents_running


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
async def test_not_live_load_does_not_track_background_commands(history_env, name):
    _, session = setup_session(history_env, transcript(name=name))
    await session.ensure_history()
    assert not session.subagents_running


@pytest.mark.anyio
@pytest.mark.parametrize("change", [{"result": False}, {"error": True},
                                   {"background": False}, {"name": "Read"}])
async def test_only_successful_background_launches_are_restored(history_env, change):
    _, session = setup_session(history_env, transcript(**change))
    await session.ensure_history(live=True, process_started_at=None)
    assert not session.subagents_running


@pytest.mark.anyio
async def test_result_without_task_id_still_counts(history_env):
    _, session = setup_session(history_env, transcript(details=False))
    await session.ensure_history(live=True, process_started_at=None)
    assert session.subagents_running
    [tool] = [i for i in session.builder.snapshot() if i["type"] == "tool"]
    assert tool["background"]["task_id"] is None


@pytest.mark.anyio
async def test_reattached_background_timeout_restarts_on_load(history_env, monkeypatch):
    clock = [50000.0]
    monkeypatch.setattr("claudio_maestro.conversation.time.monotonic", lambda: clock[0])
    _, session = setup_session(history_env, transcript(age=20000))
    await session.ensure_history(live=True, process_started_at=None)
    assert session.subagents_running
    clock[0] += SUBAGENT_MAX_SECONDS - 1
    assert session.subagents_running
    clock[0] += 2
    assert not session.subagents_running
    session.sync_subagents()
    [tool] = [i for i in session.builder.snapshot() if i["type"] == "tool"]
    assert tool["background"]["status"] == "running"


@pytest.mark.anyio
@pytest.mark.parametrize("case,kept", [("open", True), ("finished", False),
                                      ("new-process", False), ("unknown-process", True)])
async def test_idle_reattached_session_respects_background_commands(
    history_env, monkeypatch, case, kept
):
    now = time.time()
    saved = transcript(ending={TOOL: {"status": "completed", "task_id": TASK}}
                       if case == "finished" else None)
    started = None if case == "unknown-process" else now - (10 if case == "new-process" else 120)
    seen = []

    def process_start(pid):
        seen.append(pid)
        return started

    monkeypatch.setattr("claudio_maestro.sessions.process_started_at", process_start)
    env, session = setup_session(history_env, saved, idle_timeout=1)
    assert await session.reattach(SimpleNamespace(id="fake-child", pid=123, ack=0, init=None))
    assert seen == [123]
    assert session.state == "idle"
    session.idle_since = time.monotonic() - 10
    await env.manager.close_idle()
    assert (session.client is not None) is kept


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("end", ["notification", "update", "empty-list", "close"])
async def test_offwindow_background_protects_reattach_without_rendering_old_card(
    history_env, monkeypatch, name, end
):
    from claudio_maestro.agent.fake import (
        background_tasks_changed_message,
        task_updated_message,
    )

    saved = transcript(name=name)
    saved.messages.extend(user_entry(f"depois {n}") for n in range(500))
    monkeypatch.setattr("claudio_maestro.sessions.process_started_at", lambda pid: time.time() - 120)
    monkeypatch.setattr("claudio_maestro.sessions.SUBAGENT_END_GRACE_SECONDS", 0.01)
    env, session = setup_session(history_env, saved, idle_timeout=1)
    assert await session.reattach(SimpleNamespace(id="fake-child", pid=123, ack=0, init=None))
    assert session.history_truncated
    assert len(session.builder.items) == 500
    assert not any(i["type"] == "tool" for i in session.builder.snapshot())
    assert session.subagents_running
    assert session.builder.running_task_ids() == [TASK]
    session.idle_since = time.monotonic() - 10
    await env.manager.close_idle()
    assert session.client is not None
    if end == "notification":
        notification = (bash_task_notification_message if name == "Bash"
                        else monitor_task_notification_message)
        session.client.push([notification(session.session_id, TASK, None)])
    elif end == "update":
        session.client.push([task_updated_message(session.session_id, TASK, "completed")])
    elif end == "empty-list":
        session.client.push([background_tasks_changed_message(session.session_id, [])])
    else:
        await session.close()
    await wait_until(lambda: not session.subagents_running)
    assert not any(e["type"] == "item.upsert" and e["data"].get("type") == "tool"
                   for e in env.events)
    updates = [e["data"] for e in env.events if e["type"] == "session.updated"]
    assert any(e["subagents_running"] is True for e in updates)
    assert updates[-1]["subagents_running"] is False
    assert not any(i["type"] == "tool" for i in session.builder.snapshot())


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("offwindow", [False, True])
async def test_replayed_start_supplies_missing_restored_task_id(
    history_env, name, offwindow
):
    from claudio_maestro.agent.fake import (
        bash_task_started_message,
        monitor_task_started_message,
    )

    saved = transcript(name=name, details=False)
    if offwindow:
        saved.messages.extend(user_entry(f"depois {n}") for n in range(500))
    _, session = setup_session(history_env, saved)
    await session.ensure_history(live=True, process_started_at=None)
    assert session.subagents_running
    assert session.builder.running_task_ids() == []
    started = bash_task_started_message if name == "Bash" else monitor_task_started_message
    session.builder.handle(started(session.session_id, TASK, TOOL))
    assert session.builder.running_task_ids() == [TASK]
    notification = (bash_task_notification_message if name == "Bash"
                    else monitor_task_notification_message)
    session.builder.handle(notification(session.session_id, TASK, None))
    assert not session.subagents_running
    if offwindow:
        assert not any(i["type"] == "tool" for i in session.builder.snapshot())


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
async def test_offwindow_background_expires_after_three_hours(history_env, monkeypatch, name):
    clock = [50000.0]
    monkeypatch.setattr("claudio_maestro.conversation.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("claudio_maestro.sessions.process_started_at", lambda pid: None)
    saved = transcript(name=name, age=20000)
    saved.messages.extend(user_entry(f"depois {n}") for n in range(500))
    env, session = setup_session(history_env, saved, idle_timeout=1)
    assert await session.reattach(SimpleNamespace(id="fake-child", pid=123, ack=0, init=None))
    assert session.subagents_running
    session.idle_since = clock[0] - 10
    await env.manager.close_idle()
    assert session.client is not None
    clock[0] += SUBAGENT_MAX_SECONDS + 1
    await env.manager.close_idle()
    assert session.client is None
    updates = [e["data"] for e in env.events if e["type"] == "session.updated"]
    assert updates[-1]["subagents_running"] is False
    assert not any(i["type"] == "tool" for i in session.builder.snapshot())


@pytest.mark.anyio
@pytest.mark.parametrize("name", [["Bash"], {"name": "Monitor"}, None])
async def test_offwindow_scan_ignores_malformed_tool_names(history_env, name):
    saved = transcript()
    saved.messages.append(assistant_entry({
        "type": "tool_use", "id": "malformed", "name": name, "input": {}}, "bad"))
    saved.messages.extend(user_entry(f"depois {n}") for n in range(500))
    _, session = setup_session(history_env, saved)
    await session.ensure_history(live=True)
    assert session.subagents_running
    assert session.builder.running_task_ids() == [TASK]


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("case", ["finished", "earlier-process", "error", "missing-result"])
async def test_offwindow_scan_still_rejects_nonrunning_launches(history_env, name, case):
    saved = transcript(name=name, age=600 if case == "earlier-process" else 60,
                       error=case == "error", result=case != "missing-result",
                       ending={TASK: {"status": "completed", "task_id": TASK}}
                       if case == "finished" else None)
    saved.messages.extend(user_entry(f"depois {n}") for n in range(500))
    _, session = setup_session(history_env, saved)
    await session.ensure_history(live=True, process_started_at=time.time() - 120)
    assert not session.subagents_running
    assert not any(i["type"] == "tool" for i in session.builder.snapshot())


# Exercise the actual parser: compaction drops the launch from the visible chain,
# even when the chain has fewer messages than the display limit.
def compacted_transcript(tmp_path, name, *, case="open"):
    launch_time = None if case == "missing-time" else 1010
    input_ = {"command": "sleep 600", "run_in_background": True}
    result = entry("user", "u2", "a1", 1011,
                   toolUseResult={"backgroundTaskId" if name == "Bash" else "taskId": TASK},
                   message={"role": "user", "content": [{"type": "tool_result",
                            "tool_use_id": TOOL, "content": "launched",
                            "is_error": case == "error"}]})
    text = (
        entry("user", "u1", None, 1000, message={"role": "user", "content": "old prompt"})
        + entry("assistant", "a1", "u1", launch_time,
                message={"role": "assistant", "id": "m1", "content": [
                    {"type": "text", "text": "old answer"},
                    {"type": "tool_use", "id": TOOL, "name": name, "input": input_}]})
        + (result if case != "missing-result" else "")
        + entry("system", "boundary", None, 1020, subtype="compact_boundary",
                logicalParentUuid="a1" if case == "missing-result" else "u2")
        + entry("user", "summary", "boundary", 1021, isCompactSummary=True,
                message={"role": "user", "content": "summary"})
        + entry("assistant", "a2", "summary", 1022,
                message={"role": "assistant", "id": "m2", "content": [
                    {"type": "text", "text": "continued"}]})
    )
    if case in ("ended-tool", "ended-task"):
        ending = notification(TOOL, task_id=TASK)
        if case == "ended-task":
            ending = ending.replace(f"<tool-use-id>{TOOL}</tool-use-id>\n", "")
        text += queue(ending, 1030)
    path = tmp_path / "compacted.jsonl"
    path.write_text(text)
    saved = read_transcript_file(path)
    assert [message.uuid for message in saved.messages] == ["summary", "a2"]
    return saved


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("end", ["notification", "update", "empty-list", "close", "timeout"])
async def test_precompaction_launch_protects_reattach_without_old_messages(
    history_env, tmp_path, monkeypatch, name, end
):
    from claudio_maestro.agent.fake import (
        background_tasks_changed_message,
        task_updated_message,
    )

    clock = [time.monotonic()]
    if end == "timeout":
        monkeypatch.setattr("claudio_maestro.conversation.time", SimpleNamespace(
            monotonic=lambda: clock[0], time=time.time))
    monkeypatch.setattr("claudio_maestro.sessions.process_started_at", lambda pid: 1000)
    monkeypatch.setattr("claudio_maestro.sessions.SUBAGENT_END_GRACE_SECONDS", 0.01)
    env, session = setup_session(history_env, compacted_transcript(tmp_path, name), idle_timeout=1)
    assert await session.reattach(SimpleNamespace(id="fake-child", pid=123, ack=0, init=None))
    assert not session.history_truncated
    assert session.subagents_running
    assert session.builder.running_task_ids() == [TASK]
    assert [i["type"] for i in session.builder.snapshot()] == ["notice", "text"]
    session.idle_since = clock[0] - 10
    await env.manager.close_idle()
    assert session.client is not None
    if end == "notification":
        notify = bash_task_notification_message if name == "Bash" else monitor_task_notification_message
        session.client.push([notify(session.session_id, TASK, None)])
    elif end == "update":
        session.client.push([task_updated_message(session.session_id, TASK, "completed")])
    elif end == "empty-list":
        session.client.push([background_tasks_changed_message(session.session_id, [])])
    elif end == "timeout":
        clock[0] += SUBAGENT_MAX_SECONDS + 1
        await env.manager.close_idle()
        assert session.client is None
    else:
        await session.close()
    await wait_until(lambda: not session.subagents_running)
    assert [i["type"] for i in session.builder.snapshot()] == ["notice", "text"]


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Bash", "Monitor"])
@pytest.mark.parametrize("case,started,live,expected", [
    ("open", 1000, True, True),
    ("open", 1100, True, False),
    ("open", None, True, True),
    ("missing-time", None, True, True),
    ("missing-time", 1000, True, False),
    ("ended-tool", 1000, True, False),
    ("ended-task", 1000, True, False),
    ("error", 1000, True, False),
    ("missing-result", 1000, True, False),
    ("open", 1000, False, False),
])
async def test_precompaction_launch_keeps_reconstruction_guards(
    history_env, tmp_path, name, case, started, live, expected
):
    _, session = setup_session(history_env, compacted_transcript(tmp_path, name, case=case))
    await session.ensure_history(live=live, process_started_at=started)
    assert session.subagents_running is expected
    assert not any(item["type"] == "tool" for item in session.builder.snapshot())
