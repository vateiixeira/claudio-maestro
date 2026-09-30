"""`cli_running`: a session without a client whose CLI is in the middle of a turn.

Nothing here starts the `claude` process or touches the real SDK. The signal comes
from the lines the CLI writes (main file and `subagents/agent-*.jsonl`) and expires
20 minutes after the last modification of any of them.
"""

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from test_cliwatch import Env as CliEnv
from test_cliwatch import row
from test_cliwatch import wait_until as wait_until_real
from test_plan_sessions import PLAN_DONE_TEXT, expected_plan, write_plan
from test_plan_sync import Rounds, append_line, index_session, process, tool_line
from test_sessions_api import api, factory, make_project  # noqa: F401  (fixtures)
from watchfiles import Change

from vibing.cliwatch import turn_open, was_interrupted
from vibing.sessions import CLI_TURN_STALE_SECONDS, SessionRecord, describe

T0 = 1_700_000_500  # epoch seconds of the first modification


def prompt_line(text: str = "oi", **extra: Any) -> str:
    return json.dumps({"type": "user", "isSidechain": False,
                       "message": {"role": "user", "content": text}, **extra})


def result_line() -> str:
    return json.dumps({"type": "user", "isSidechain": False, "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}})


def assistant_line(stop_reason: str | None, *, sidechain: bool = False) -> str:
    return json.dumps({"type": "assistant", "isSidechain": sidechain, "message": {
        "role": "assistant", "stop_reason": stop_reason,
        "content": [{"type": "text", "text": "..."}]}})


def interrupt_line() -> str:
    return json.dumps({"type": "user", "isSidechain": False, "message": {
        "role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}})


OPEN_FILE = prompt_line() + "\n" + assistant_line("tool_use") + "\n"


# turn_open (pure) ---------------------------------------------------------------


def test_turn_open_reads_the_last_decisive_entry():
    assert turn_open([prompt_line(), assistant_line("tool_use")]) is True
    assert turn_open([prompt_line(), assistant_line("tool_use"), assistant_line("end_turn")]) is False
    assert turn_open([assistant_line("end_turn"), prompt_line()]) is True
    assert turn_open([assistant_line("end_turn"), result_line()]) is True
    assert turn_open([assistant_line(None)]) is True  # partial write of a message


def test_turn_open_skips_lines_that_say_nothing_about_the_turn():
    noise = [
        json.dumps({"type": "attachment"}), json.dumps({"type": "system"}),
        json.dumps({"type": "last-prompt"}), "não é json", "[]", "",
        assistant_line("tool_use", sidechain=True),  # other chain
        prompt_line("meta", isMeta=True),
    ]
    assert turn_open([assistant_line("end_turn"), *noise]) is False
    assert turn_open([assistant_line("tool_use"), *noise]) is True
    assert turn_open(noise) is None
    assert turn_open([]) is None


@pytest.mark.parametrize(
    "stop_reason",
    ["end_turn", "stop_sequence", "max_tokens", "refusal", "model_context_window_exceeded", "pause_turn"],
)
def test_turn_open_any_stop_reason_but_none_and_tool_use_closes(stop_reason):
    assert turn_open([prompt_line(), assistant_line(stop_reason)]) is False


def test_turn_open_only_none_and_tool_use_keep_the_turn_open():
    assert turn_open([assistant_line("end_turn"), assistant_line("tool_use")]) is True
    assert turn_open([assistant_line("end_turn"), assistant_line(None)]) is True
    entry = {"type": "assistant", "message": {"content": []}}  # no stop_reason key at all
    assert turn_open([assistant_line("end_turn"), json.dumps(entry)]) is True


COMMAND_TEXTS = [
    "<command-name>/exit</command-name>",
    "<command-message>exit</command-message>",
    "<local-command-stdout>Goodbye!</local-command-stdout>",
    "<local-command-caveat>Caveat: ...</local-command-caveat>",
    "<bash-input>ls</bash-input>",
    "<bash-stdout>x</bash-stdout>",
    "<bash-stderr>y</bash-stderr>",
]


@pytest.mark.parametrize("text", COMMAND_TEXTS)
def test_turn_open_skips_user_command_entries_as_string(text):
    assert turn_open([assistant_line("end_turn"), prompt_line(text)]) is False
    assert turn_open([assistant_line("tool_use"), prompt_line(text)]) is True


@pytest.mark.parametrize("text", COMMAND_TEXTS)
def test_turn_open_skips_user_command_entries_as_text_block(text):
    block = json.dumps({"type": "user", "isSidechain": False, "message": {
        "role": "user", "content": [{"type": "text", "text": text}]}})
    assert turn_open([assistant_line("end_turn"), block]) is False


def test_turn_open_skips_compact_summaries():
    summary = prompt_line("resumo da conversa", isCompactSummary=True)
    assert turn_open([assistant_line("end_turn"), summary]) is False
    assert turn_open([summary]) is None


def test_turn_open_task_notification_opens_a_turn():
    notification = prompt_line("<task-notification><task-id>x</task-id></task-notification>")
    assert turn_open([assistant_line("end_turn"), notification]) is True


def test_turn_open_interruption_closes_the_turn():
    assert turn_open([prompt_line(), assistant_line("tool_use"), interrupt_line()]) is False


def test_turn_open_sidechain_reads_sidechain_entries_and_skips_the_main_chain():
    lines = [
        prompt_line("tarefa", isSidechain=True),
        assistant_line("tool_use", sidechain=True),
        assistant_line("end_turn"),  # main chain entry in the same lines: ignored
    ]
    assert turn_open(lines, sidechain=True) is True
    assert turn_open(lines) is False  # without the flag the sidechain is still ignored
    assert turn_open([assistant_line("tool_use", sidechain=True)]) is None
    assert turn_open([assistant_line("tool_use", sidechain=True)], sidechain=True) is True
    assert turn_open([assistant_line("end_turn")], sidechain=True) is None


def test_turn_open_sidechain_closes_on_end_turn_and_opens_on_result():
    done = [assistant_line("tool_use", sidechain=True), assistant_line("end_turn", sidechain=True)]
    assert turn_open(done, sidechain=True) is False
    result = json.dumps({"type": "user", "isSidechain": True, "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}})
    assert turn_open([*done, result], sidechain=True) is True
    assert turn_open([assistant_line(None, sidechain=True)], sidechain=True) is True  # old CLI
    skipped = [prompt_line("meta", isMeta=True, isSidechain=True),
               prompt_line("<bash-input>ls</bash-input>", isSidechain=True)]
    assert turn_open([*done, *skipped], sidechain=True) is False


def test_was_interrupted_only_when_the_last_decisive_main_entry_is_the_interruption():
    assert was_interrupted([prompt_line(), assistant_line("tool_use"), interrupt_line()]) is True
    assert was_interrupted([interrupt_line(), json.dumps({"type": "attachment"})]) is True
    assert was_interrupted([interrupt_line(), prompt_line("de novo")]) is False
    assert was_interrupted([interrupt_line(), assistant_line("end_turn")]) is False
    assert was_interrupted([assistant_line("end_turn")]) is False
    assert was_interrupted([]) is False


def test_only_closed_sessions_report_cli_running():
    record = SessionRecord(
        session_id="s", project_id=1, cwd="/x", title="t", created_at=0, last_activity_at=0,
    )
    kwargs = {"finished_after": 1e9, "now": 1.0}
    assert describe(record, "closed", None, 0, cli_running=True, **kwargs)["cli_running"] is True
    for state in ("idle", "running", "connecting", "awaiting_decision"):
        assert describe(record, state, None, 0, cli_running=True, **kwargs)["cli_running"] is False
    assert describe(record, "closed", None, 0, **kwargs)["cli_running"] is False


# Watcher ------------------------------------------------------------------------


@pytest.fixture
async def cli(tmp_path: Path):
    env = CliEnv(tmp_path)
    now = {"t": float(T0) + 10}
    env.now = now  # type: ignore[attr-defined]
    env.manager._clock = lambda: now["t"]
    yield env
    if env.task is not None:
        env.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await env.task
    await env.manager.shutdown()


def item(env: CliEnv, session_id: str = "s1") -> dict[str, Any]:
    return next(i for i in env.manager.list_sessions() if i["session_id"] == session_id)


def updates(env: CliEnv, session_id: str = "s1") -> list[dict[str, Any]]:
    return [e["data"] for e in env.events
            if e["type"] == "session.updated" and e["session_id"] == session_id]


def sub_file(env: CliEnv, session_id: str = "s1", name: str = "agent-a1.jsonl") -> Path:
    folder = env.history_dir / session_id / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


async def process_sub(env: CliEnv, path: Path, mtime: float) -> None:
    done = len(env.processed)
    os.utime(path, (mtime, mtime))
    env.watch.push((Change.modified, path))
    await wait_until_real(lambda: len(env.processed) > done)


async def sweep(env: CliEnv, *hooks: Any) -> None:
    with pytest.raises(asyncio.CancelledError):
        await env.manager.run_plan_sweep(30, sleep=Rounds(*hooks))


@pytest.mark.anyio
async def test_tool_use_opens_the_turn_and_end_turn_closes_it(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()

    await process(cli, "s1", T0)

    assert item(cli)["cli_running"] is True
    assert updates(cli)[-1]["cli_running"] is True
    assert "s1" not in cli.manager.active_ids()  # database only
    assert cli.manager.summary("s1")["cli_running"] is True  # snapshot

    append_line(path, assistant_line("end_turn"))
    await process(cli, "s1", T0 + 5)

    assert item(cli)["cli_running"] is False
    assert updates(cli)[-1]["cli_running"] is False


@pytest.mark.anyio
async def test_a_user_entry_after_end_turn_opens_the_turn(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    assert item(cli)["cli_running"] is False

    append_line(path, prompt_line("outra coisa"))
    await process(cli, "s1", T0 + 5)
    assert item(cli)["cli_running"] is True

    append_line(path, assistant_line("end_turn"))
    append_line(path, assistant_line("tool_use"))
    append_line(path, result_line())
    await process(cli, "s1", T0 + 10)
    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_a_pass_with_nothing_decisive_keeps_the_signal(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)

    append_line(path, json.dumps({"type": "attachment"}))
    await process(cli, "s1", T0 + 5)

    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_a_stale_signal_is_dropped_at_the_20_minute_cap(cli):
    assert CLI_TURN_STALE_SECONDS == 20 * 60
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS - 1
    await process(cli, "s1", T0)
    assert item(cli)["cli_running"] is True

    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS
    assert item(cli)["cli_running"] is True  # exactly at the cap still counts
    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 1
    assert item(cli)["cli_running"] is False
    assert cli.manager.summary("s1")["cli_running"] is False


@pytest.mark.anyio
async def test_a_pass_over_an_old_file_never_opens_the_signal(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 60

    await process(cli, "s1", T0)

    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_active_subagent_keeps_the_turn_open_while_the_main_file_is_still(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    assert item(cli)["cli_running"] is False

    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.now["t"] = T0 + 600
    await process_sub(cli, sub, T0 + 590)  # main file untouched for 10 minutes

    assert cli.processed[-1] == "s1"
    assert item(cli)["cli_running"] is True
    assert updates(cli)[-1]["cli_running"] is True
    # It lives on the newest of the files: 20 minutes after the subagent's last write.
    cli.now["t"] = T0 + 590 + CLI_TURN_STALE_SECONDS + 1
    assert item(cli)["cli_running"] is False


async def process_together(env: CliEnv, main: Path, subs: list[Path], mtime: float) -> None:
    """One watcher pass for changes to the main file and to subagent files."""
    done = len(env.processed)
    for file in (main, *subs):
        os.utime(file, (mtime, mtime))
    for file in (main, *subs):
        env.watch.push((Change.modified, file))
    await wait_until_real(lambda: len(env.processed) > done)


def sub_write(path: Path, *lines: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")


def sub_open(env: CliEnv, session_id: str = "s1") -> dict[str, bool]:
    return {p.name: v.open for p, v in env.watcher._subagent_open.get(session_id, {}).items()}


@pytest.mark.anyio
async def test_main_end_turn_and_subagent_tool_use_in_the_same_pass_keep_the_turn_open(cli):
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n" + assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()

    await process_together(cli, path, [sub], T0)

    assert item(cli)["cli_running"] is True
    assert sub_open(cli) == {"agent-a1.jsonl": True}


@pytest.mark.anyio
async def test_background_subagent_keeps_the_turn_open_after_the_main_end_turn(cli):
    # The real case: main `end_turn` at 14:20:13, the subagent silent until 14:22:04.
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n" + assistant_line("tool_use") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(prompt_line("tarefa", isSidechain=True) + "\n"
                   + assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)
    assert item(cli)["cli_running"] is True

    append_line(path, assistant_line("end_turn"))  # only the main chain writes
    await process(cli, "s1", T0 + 5)
    assert item(cli)["cli_running"] is True
    assert updates(cli)[-1]["cli_running"] is True

    # A pass with nothing decisive from anyone changes nothing.
    append_line(path, json.dumps({"type": "attachment"}))
    await process(cli, "s1", T0 + 10)
    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_the_turn_closes_when_the_subagent_ends_and_the_main_chain_is_closed(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)
    assert item(cli)["cli_running"] is True

    sub_write(sub, assistant_line("end_turn", sidechain=True))
    await process_sub(cli, sub, T0 + 5)

    assert item(cli)["cli_running"] is False
    assert updates(cli)[-1]["cli_running"] is False
    assert sub_open(cli) == {}  # closed subagents are not kept


@pytest.mark.anyio
async def test_a_subagent_that_died_open_stops_counting_after_the_20_minute_cap(cli):
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n" + assistant_line("tool_use") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)  # the subagent writes once and dies
    assert item(cli)["cli_running"] is True

    # Main-chain turns much later than the cap after the subagent's last write.
    for step in range(3):
        cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 100 + step * 10
        append_line(path, assistant_line("end_turn"))
        await process(cli, "s1", cli.now["t"])
        assert item(cli)["cli_running"] is False
        assert updates(cli)[-1]["cli_running"] is False
        assert sub_open(cli) == {}


@pytest.mark.anyio
async def test_a_recently_written_open_subagent_keeps_the_turn_after_the_main_end_turn(cli):
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n" + assistant_line("tool_use") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)

    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS - 60  # the subagent wrote 19 minutes ago
    append_line(path, assistant_line("end_turn"))
    await process(cli, "s1", cli.now["t"])

    assert item(cli)["cli_running"] is True
    assert sub_open(cli) == {"agent-a1.jsonl": True}
    # With the main chain closed, the signal lives on the subagent's last write.
    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 1
    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_subagent_states_keep_only_files_that_are_open_and_fresh(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    closed, alive, dead = (sub_file(cli, name=f"agent-{n}.jsonl") for n in ("a1", "a2", "a3"))
    closed.write_text(assistant_line("end_turn", sidechain=True) + "\n", encoding="utf-8")
    alive.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    dead.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [closed, alive, dead], T0)
    assert sub_open(cli) == {"agent-a2.jsonl": True, "agent-a3.jsonl": True}

    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 100
    sub_write(alive, assistant_line("tool_use", sidechain=True))
    await process_sub(cli, alive, cli.now["t"])

    assert sub_open(cli) == {"agent-a2.jsonl": True}  # a1 closed, a3 expired
    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_the_main_chain_keeps_the_turn_open_after_the_subagent_ends(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("end_turn", sidechain=True) + "\n", encoding="utf-8")
    cli.start()

    await process_together(cli, path, [sub], T0)

    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_a_turn_is_open_while_any_of_two_subagents_is_open(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    first = sub_file(cli, name="agent-a1.jsonl")
    second = sub_file(cli, name="agent-a2.jsonl")
    first.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    second.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [first, second], T0)
    assert item(cli)["cli_running"] is True

    sub_write(first, assistant_line("end_turn", sidechain=True))
    await process_sub(cli, first, T0 + 5)
    assert item(cli)["cli_running"] is True  # the other one still runs
    assert sub_open(cli) == {"agent-a2.jsonl": True}

    sub_write(second, assistant_line("end_turn", sidechain=True))
    await process_sub(cli, second, T0 + 10)
    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_a_subagent_pass_without_a_decisive_entry_keeps_its_previous_state(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)

    sub_write(sub, json.dumps({"type": "attachment", "isSidechain": True}))
    await process_sub(cli, sub, T0 + 5)

    assert sub_open(cli) == {"agent-a1.jsonl": True}
    assert item(cli)["cli_running"] is True


@pytest.mark.anyio
async def test_a_subagent_file_without_a_decisive_entry_does_not_count(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(json.dumps({"type": "attachment", "isSidechain": True}) + "\n", encoding="utf-8")
    cli.start()

    await process_together(cli, path, [sub], T0)

    assert item(cli)["cli_running"] is False
    assert sub_open(cli) == {}


@pytest.mark.anyio
async def test_an_interruption_of_the_main_chain_resets_the_subagents(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)
    assert item(cli)["cli_running"] is True

    append_line(path, interrupt_line())  # Esc: the foreground subagent dies without `end_turn`
    await process(cli, "s1", T0 + 5)
    assert item(cli)["cli_running"] is False
    assert sub_open(cli) == {}

    # A subagent that is still alive reopens the turn when it writes again.
    sub_write(sub, assistant_line("tool_use", sidechain=True))
    await process_sub(cli, sub, T0 + 10)
    assert item(cli)["cli_running"] is True
    assert sub_open(cli) == {"agent-a1.jsonl": True}


@pytest.mark.anyio
async def test_subagent_states_are_forgotten_when_the_app_takes_over_the_session(cli, monkeypatch):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)
    assert sub_open(cli) == {"agent-a1.jsonl": True}

    monkeypatch.setattr(cli.manager, "app_writing", lambda sid: True)
    append_line(path, assistant_line("tool_use"))
    os.utime(path, (T0 + 5, T0 + 5))
    cli.watch.push((Change.modified, path))
    await asyncio.sleep(0.5)
    await wait_until_real(lambda: not cli.watcher._bursts)
    monkeypatch.undo()

    assert "s1" not in cli.watcher._subagent_open
    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_subagent_states_are_forgotten_when_the_file_is_gone(cli):
    path = await index_session(cli)
    path.write_text(assistant_line("end_turn") + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()
    await process_together(cli, path, [sub], T0)
    assert "s1" in cli.watcher._subagent_open

    path.unlink()
    cli.watch.push((Change.deleted, path))
    await wait_until_real(lambda: len(cli.processed) > 1)

    assert "s1" not in cli.watcher._subagent_open
    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_subagent_file_is_not_a_session_and_is_never_indexed(cli):
    await index_session(cli)
    sub = sub_file(cli)
    sub.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    cli.start()

    await process_sub(cli, sub, T0)

    assert cli.processed == ["s1"]
    assert row(cli.db_path, "agent-a1") is None
    await wait_until_real(lambda: not cli.watcher._bursts)  # only the parent's burst existed
    # Files that are not `agent-*.jsonl` inside `subagents/` stay ignored.
    other = sub_file(cli, name="notes.jsonl")
    other.write_text("{}\n")
    cli.watch.push((Change.modified, other))
    deep = cli.history_dir / "s1" / "subagents" / "x" / "agent-b.jsonl"
    deep.parent.mkdir()
    deep.write_text("{}\n")
    cli.watch.push((Change.modified, deep))
    await asyncio.sleep(0.2)
    assert cli.processed == ["s1"]


@pytest.mark.anyio
async def test_a_plan_touched_by_a_subagent_links_the_parent_session(cli):
    plan = write_plan(cli.folder)
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n", encoding="utf-8")
    sub = sub_file(cli)
    sub.write_text(tool_line("Edit", str(plan), sidechain=True) + "\n", encoding="utf-8")
    cli.start()

    await process_sub(cli, sub, T0)

    await wait_until_real(lambda: cli.manager.plan_summary(cli.manager.get("s1").record) is not None)
    record = cli.manager.get("s1").record
    assert (record.plan_path, record.plan_link) == (str(plan), "auto")
    assert cli.manager.plan_summary(record) == expected_plan(plan)


@pytest.mark.anyio
async def test_subagent_lines_are_read_only_from_the_changed_files_and_only_once(cli, monkeypatch):
    from vibing import cliwatch

    path = await index_session(cli)
    path.write_text(prompt_line() + "\n", encoding="utf-8")
    quiet = sub_file(cli, name="agent-quiet.jsonl")
    quiet.write_text(assistant_line("tool_use", sidechain=True) + "\n", encoding="utf-8")
    busy = sub_file(cli, name="agent-busy.jsonl")
    busy.write_text(prompt_line("x") + "\n", encoding="utf-8")
    calls: list[tuple[str, int | None]] = []
    real = cliwatch.read_new_lines

    def spy(file: Path, offset: int | None, **kwargs: Any):
        calls.append((file.name, offset))
        return real(file, offset, **kwargs)

    monkeypatch.setattr(cliwatch, "read_new_lines", spy)
    cli.start()

    await process_sub(cli, busy, T0)
    size = busy.stat().st_size
    append_line(busy, prompt_line("y"))
    await process_sub(cli, busy, T0 + 5)

    sub_calls = [(name, offset) for name, offset in calls if name.startswith("agent-")]
    assert sub_calls == [("agent-busy.jsonl", None), ("agent-busy.jsonl", size)]  # not `quiet`


@pytest.mark.anyio
async def test_the_signal_is_forgotten_when_the_app_takes_over_the_session(cli, monkeypatch):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    assert item(cli)["cli_running"] is True

    monkeypatch.setattr(cli.manager, "app_writing", lambda sid: True)
    append_line(path, assistant_line("tool_use"))
    os.utime(path, (T0 + 5, T0 + 5))
    cli.watch.push((Change.modified, path))
    await asyncio.sleep(0.5)  # the pass is skipped: nothing is reported as processed
    await wait_until_real(lambda: not cli.watcher._bursts)
    monkeypatch.undo()

    assert item(cli)["cli_running"] is False


@pytest.mark.anyio
async def test_a_failing_turn_read_does_not_break_the_pass(cli, monkeypatch):
    path = await index_session(cli)
    path.write_text(prompt_line() + "\n", encoding="utf-8")

    def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("falha")

    monkeypatch.setattr("vibing.cliwatch.turn_open", boom)
    cli.start()

    await process(cli, "s1", T0)

    assert cli.processed == ["s1"]
    assert [e for e in cli.events if e["type"] == "session.updated"]


@pytest.mark.anyio
async def test_forgets_the_turn_state_when_the_file_is_gone(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    assert "s1" in cli.watcher._turn_open

    path.unlink()
    cli.watch.push((Change.deleted, path))
    await wait_until_real(lambda: len(cli.processed) > 1)

    assert "s1" not in cli.watcher._turn_open
    assert item(cli)["cli_running"] is False


# Sweep --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_sweep_announces_the_expiry_of_the_signal_for_a_database_only_session(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    assert "s1" not in cli.manager.active_ids()
    cli.events.clear()

    def expire() -> None:
        cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 1

    await sweep(cli, None, expire, None)

    sent = updates(cli)
    assert [u["cli_running"] for u in sent] == [False]
    assert sent[0]["state"] == "closed"
    assert "s1" not in cli.manager.active_ids()
    # Announced once: a later round has nothing more to say.
    cli.events.clear()
    await sweep(cli, None)
    assert updates(cli) == []


@pytest.mark.anyio
async def test_sweep_stays_quiet_while_the_signal_is_valid(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    cli.events.clear()

    await sweep(cli, None, None)

    assert updates(cli) == []


@pytest.mark.anyio
async def test_sweep_announces_expiry_for_a_session_in_memory_too(cli):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    cli.start()
    await process(cli, "s1", T0)
    cli.manager.get("s1")  # a closed session that is in memory
    cli.events.clear()

    def expire() -> None:
        cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 1

    await sweep(cli, None, expire, None)

    assert [u["cli_running"] for u in updates(cli)] == [False]


@pytest.mark.anyio
async def test_sweep_survives_a_failure_announcing_the_signal(cli, monkeypatch, caplog):
    path = await index_session(cli)
    path.write_text(OPEN_FILE, encoding="utf-8")
    plan = write_plan(cli.folder)
    cli.start()
    await process(cli, "s1", T0)
    cli.manager.link_plan("s1", str(plan), source="manual")
    cli.manager.get("s1").save(last_activity_at=int(time.time()))

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("anúncio falhou")

    monkeypatch.setattr(cli.manager, "_announce_session", boom)
    cli.now["t"] = T0 + CLI_TURN_STALE_SECONDS + 1

    await sweep(cli, None, None)

    assert "anúncio falhou" in caplog.text
    assert cli.manager.plan_summary(cli.manager.get("s1").record) == expected_plan(plan)


@pytest.mark.anyio
async def test_sweep_announces_a_plan_change_for_a_database_only_session(cli):
    plan = write_plan(cli.folder)
    await index_session(cli)
    cli.manager.link_plan("s1", str(plan), source="manual")
    cli.manager.get("s1").save(last_activity_at=int(time.time()))
    cli.manager._sessions.pop("s1")
    assert "s1" not in cli.manager.active_ids()
    cli.events.clear()

    def edit() -> None:
        plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")
        stat = plan.stat()
        os.utime(plan, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        cli.events.clear()

    await sweep(cli, None, edit, None)

    sent = updates(cli)
    assert [u["plan"] for u in sent] == [expected_plan(plan, done=2)]
    assert sent[0]["state"] == "closed"
    assert "s1" not in cli.manager.active_ids()


@pytest.mark.anyio
async def test_plan_change_is_not_announced_for_finished_database_sessions(cli):
    plan = write_plan(cli.folder)
    await index_session(cli)
    cli.manager.link_plan("s1", str(plan), source="manual")
    cli.manager.get("s1").save(finished=True, finished_at=T0)
    cli.manager._sessions.pop("s1")
    cli.events.clear()

    await cli.manager._refresh_plan_path(str(plan))

    assert updates(cli) == []


@pytest.mark.anyio
async def test_plan_link_rows_reads_only_the_database(cli):
    plan = write_plan(cli.folder)
    await index_session(cli)
    cli.manager.link_plan("s1", str(plan), source="manual")

    class Forbidden:
        def __getattr__(self, name: str):
            raise AssertionError("a thread não pode tocar o estado do loop")

    real_sessions = cli.manager._sessions
    cli.manager._sessions = Forbidden()  # type: ignore[assignment]
    box: list[Any] = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            box.append(cli.manager._plan_link_rows())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    try:
        thread = threading.Thread(target=work)
        thread.start()
        thread.join(3)
    finally:
        cli.manager._sessions = real_sessions
    assert errors == []
    assert [tuple(r)[:2] for r in box[0]] == [("s1", str(plan))]


# API ----------------------------------------------------------------------------


def test_api_exposes_cli_running_defaulting_to_false(api, home):
    project = make_project(api, home)
    created = api.post(f"/api/projects/{project['id']}/sessions")
    assert created.json()["cli_running"] is False
    listed = api.get("/api/sessions").json()
    assert [s["cli_running"] for s in listed] == [False]
    session_id = created.json()["session_id"]
    assert api.get(f"/api/sessions/{session_id}").json()["cli_running"] is False
