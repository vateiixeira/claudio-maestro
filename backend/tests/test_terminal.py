"""Tests for the session terminal manager (real bash in a temporary folder)."""

import asyncio
import os
import re
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
import pytest

from claudio_maestro import terminal as terminal_module
from claudio_maestro.termformat import TerminalRun, parse_terminal_message
from claudio_maestro.terminal import (
    REPLAY_LIMIT,
    Frame,
    Terminal,
    TerminalBusyError,
    TerminalManager,
    TerminalStartError,
)

pytestmark = pytest.mark.anyio

TIMEOUT = 15.0


class Sent:
    """Fake `send_message` that records every call."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.result = result

    async def __call__(self, session_id: str, text: str) -> bool:
        self.calls.append((session_id, text))
        return self.result

    def runs(self) -> list[TerminalRun]:
        parsed = [parse_terminal_message(text) for _, text in self.calls]
        assert all(run is not None for run in parsed)
        return [run for run in parsed if run is not None]


async def until(predicate: Any, timeout: float = TIMEOUT) -> None:
    with anyio.fail_after(timeout):
        while not predicate():
            await anyio.sleep(0.02)


def session_processes(sid: int) -> list[str]:
    """`pid args` of the live processes (zombies excluded) that belong to session `sid`."""
    out = subprocess.run(
        ["ps", "-eo", "pid,sid,stat,args"], capture_output=True, text=True, check=True
    ).stdout
    rows = [line.split(None, 3) for line in out.splitlines()[1:]]
    return [
        f"{row[0]} {row[3] if len(row) > 3 else ''}"
        for row in rows
        if row[1] == str(sid) and not row[2].startswith("Z")
    ]


def drain(queue: asyncio.Queue[Frame]) -> list[Frame]:
    frames: list[Frame] = []
    while not queue.empty():
        frames.append(queue.get_nowait())
    return frames


def run_states(frames: list[Frame]) -> list[str]:
    return [frame["state"] for frame in frames if frame["type"] == "run"]


@pytest.fixture
def sent() -> Sent:
    return Sent()


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


@pytest.fixture
async def manager(
    tmp_path: Path, sent: Sent, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[TerminalManager]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_TEST_LEAK", "1")
    monkeypatch.setenv("MAESTRO_TEST_LEAK", "1")
    instance = TerminalManager(send_message=sent, env_overrides={"HOME": str(home)})
    yield instance
    await instance.aclose()


async def test_open_runs_in_session_folder_with_clean_env(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    await manager.run(
        "s1", workdir, "pwd; echo $TERM; env | grep -c '^CLAUDE\\|^MAESTRO_' || true"
    )
    await until(lambda: sent.calls)
    assert sent.calls[0][0] == "s1"
    assert sent.runs()[0]["output"].split("\n") == [
        str(workdir.resolve()),
        "xterm-256color",
        "0",
    ]


async def test_run_sends_command_output_exit_and_duration(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    run_id = await manager.run("s1", workdir, "echo oi; false")
    await until(lambda: sent.calls)
    await anyio.sleep(0.1)
    assert len(sent.calls) == 1
    run = sent.runs()[0]
    assert run["command"] == "echo oi; false"
    assert run["output"] == "oi"
    assert run["exit_code"] == 1
    assert run["duration_ms"] is not None and run["duration_ms"] >= 0
    frames = [f for f in drain(queue) if f["type"] == "run"]
    assert [f["state"] for f in frames] == ["running", "sent"]
    assert all(f["run_id"] == run_id for f in frames)
    assert frames[1]["exit_code"] == 1


async def test_multiline_block_runs_once_and_keeps_cd(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    await manager.run("s1", workdir, "cd /\npwd")
    await until(lambda: len(sent.calls) == 1)
    assert sent.runs()[0]["output"] == "/"
    await manager.run("s1", workdir, "pwd")
    await until(lambda: len(sent.calls) == 2)
    assert sent.runs()[1]["output"] == "/"


async def test_run_while_busy_raises(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    await manager.run("s1", workdir, "sleep 2")
    with pytest.raises(TerminalBusyError):
        await manager.run("s1", workdir, "echo no")
    await until(lambda: sent.calls)
    assert len(sent.calls) == 1


async def test_run_right_after_open_waits_for_prompt(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "echo pronto")
    await until(lambda: sent.calls)
    assert sent.runs()[0]["output"] == "pronto"
    # Pasted only after readline took over: the tty did not echo the paste marks as ^[[200~.
    assert "^[[200~" not in terminal.replay()


async def test_typing_enter_during_run_cuts_capture(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "echo antes; sleep 1; echo depois")
    await until(lambda: any(f["type"] == "busy" and f["busy"] for f in drain(queue)))
    await anyio.sleep(0.2)
    terminal.write("x\r")
    await until(lambda: sent.calls, timeout=0.9)
    run = sent.runs()[0]
    assert "input" in run["notes"]
    assert "depois" not in run["output"]
    assert run["exit_code"] is None
    await anyio.sleep(1.3)
    assert len(sent.calls) == 1


async def test_ctrl_c_ends_run_with_130(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "sleep 5")
    await until(lambda: terminal.busy)
    terminal.write("\x03")
    await until(lambda: sent.calls)
    run = sent.runs()[0]
    assert run["exit_code"] == 130
    assert "input" not in run["notes"]


async def test_kill_interrupted_sends_nothing(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "sleep 5")
    await until(lambda: terminal.busy)
    await manager.kill("s1", interrupted=True)
    assert sent.calls == []
    frames = drain(queue)
    assert run_states(frames) == ["running", "interrupted"]
    assert frames[-1] == {"type": "exit"}
    assert manager.get("s1") is None


async def test_kill_not_interrupted_sends_shell_exit_note(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "sleep 5")
    await until(lambda: terminal.busy)
    await manager.kill("s1", interrupted=False)
    assert len(sent.calls) == 1
    assert "shell-exit" in sent.runs()[0]["notes"]
    assert run_states(drain(queue)) == ["running", "sent"]


async def test_kill_leaves_no_processes(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "sleep 30")
    await until(lambda: terminal.busy)
    pgid = terminal.pid
    os.killpg(pgid, 0)
    await manager.kill("s1", interrupted=True)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


async def test_replay_keeps_last_chars(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "head -c 400000 /dev/zero | tr '\\0' a")
    await until(lambda: sent.calls)
    await until(lambda: re.search(r"\$ (\x1b\[\?2004h)?$", terminal.replay()) is not None)
    assert len(terminal.replay()) <= REPLAY_LIMIT
    assert terminal.replay().count("a") > 200_000


async def test_invalid_utf8_output_is_replaced(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    await manager.run("s1", workdir, "printf '\\xff\\xfe ok'")
    await until(lambda: sent.calls)
    output = sent.runs()[0]["output"]
    assert "�" in output and "ok" in output


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh is not installed")
async def test_zsh_emits_marks(tmp_path: Path, sent: Sent, workdir: Path) -> None:
    home = tmp_path / "zhome"
    home.mkdir(exist_ok=True)
    manager = TerminalManager(send_message=sent, shell="zsh", env_overrides={"HOME": str(home)})
    try:
        await manager.run("s1", workdir, "false")
        await until(lambda: sent.calls)
        assert sent.runs()[0]["exit_code"] == 1
    finally:
        await manager.aclose()


async def test_open_is_idempotent(manager: TerminalManager, workdir: Path) -> None:
    first = await manager.open("s1", workdir)
    assert await manager.open("s1", workdir) is first
    assert manager.get("s1") is first
    assert manager.get("other") is None


async def test_failed_send_marks_run_failed(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    sent.result = False
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "true")
    await until(lambda: sent.calls)
    await until(lambda: "failed" in run_states(drain(queue)))


async def test_shell_exit_ends_run_and_removes_terminal(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "echo antes; exit 3")
    await until(lambda: sent.calls)
    assert "shell-exit" in sent.runs()[0]["notes"]
    await terminal.wait_closed()
    assert manager.get("s1") is None
    frames = drain(queue)
    assert frames[-1] == {"type": "exit"}
    with pytest.raises(ProcessLookupError):
        os.killpg(terminal.pid, 0)


async def test_resize_reaches_the_shell(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    assert (terminal.cols, terminal.rows) == (120, 30)
    terminal.resize(100, 40)
    await manager.run("s1", workdir, "stty size")
    await until(lambda: sent.calls)
    assert sent.runs()[0]["output"] == "40 100"


async def test_comment_only_command_still_finishes(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    await manager.run("s1", workdir, "# so um comentario")
    await until(lambda: sent.calls)
    await manager.run("s1", workdir, "echo depois")
    await until(lambda: len(sent.calls) == 2)
    assert sent.runs()[1]["output"] == "depois"


async def test_empty_command_is_rejected(manager: TerminalManager, workdir: Path) -> None:
    with pytest.raises(ValueError):
        await manager.run("s1", workdir, "  \n")


async def test_missing_folder_fails_to_start(manager: TerminalManager, tmp_path: Path) -> None:
    with pytest.raises(TerminalStartError):
        await manager.open("s1", tmp_path / "nope")
    assert manager.get("s1") is None


async def test_slow_subscriber_is_dropped(manager: TerminalManager, workdir: Path) -> None:
    terminal = await manager.open("s1", workdir)
    slow = terminal.subscribe()
    healthy = terminal.subscribe()
    for _ in range(1025):
        terminal._publish({"type": "output", "data": "x"})
        drain(healthy)
    assert drain(slow) == [{"type": "exit"}]
    terminal._publish({"type": "output", "data": "y"})
    assert drain(slow) == []
    assert drain(healthy) == [{"type": "output", "data": "y"}]


async def test_aclose_stops_every_terminal(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    one = await manager.open("s1", workdir)
    two = await manager.open("s2", workdir)
    await manager.aclose()
    for terminal in (one, two):
        with pytest.raises(ProcessLookupError):
            os.killpg(terminal.pid, 0)
    assert manager.get("s1") is None and manager.get("s2") is None
    assert isinstance(one, Terminal)


@pytest.mark.parametrize(
    "command",
    [
        "nohup sleep 300 >/dev/null 2>&1 &",
        "sleep 300 & disown",
        "bash -c 'trap \"\" HUP; sleep 300'",
    ],
    ids=["nohup", "disown", "foreground-ignoring-hup"],
)
async def test_kill_clears_the_whole_session(
    manager: TerminalManager,
    sent: Sent,
    workdir: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    monkeypatch.setattr(terminal_module, "KILL_GRACE_SECONDS", 0.5)
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, command)
    await until(lambda: any("sleep 300" in p for p in session_processes(terminal.pid)))
    await manager.kill("s1", interrupted=True)
    assert session_processes(terminal.pid) == []


@pytest.mark.parametrize("pidfd", [True, False], ids=["pidfd", "polling"])
async def test_shell_exit_with_background_job_closes_terminal(
    manager: TerminalManager,
    sent: Sent,
    workdir: Path,
    monkeypatch: pytest.MonkeyPatch,
    pidfd: bool,
) -> None:
    monkeypatch.setattr(terminal_module, "KILL_GRACE_SECONDS", 0.5)
    monkeypatch.setattr(terminal_module, "SHELL_POLL_SECONDS", 0.05)
    if not pidfd:
        monkeypatch.delattr(os, "pidfd_open", raising=False)
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "sleep 300 & disown; exit")
    await until(lambda: terminal.closed)
    with anyio.fail_after(TIMEOUT):
        await terminal.wait_closed()
    assert manager.get("s1") is None
    assert drain(queue)[-1] == {"type": "exit"}
    assert session_processes(terminal.pid) == []
    assert "shell-exit" in sent.runs()[0]["notes"]


async def test_run_clears_half_typed_line(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "true")
    await until(lambda: sent.calls)
    terminal.write("abc")
    await manager.run("s1", workdir, "echo oi")
    await until(lambda: len(sent.calls) == 2)
    run = sent.runs()[1]
    assert run["command"] == "echo oi"
    assert run["output"] == "oi"


async def test_shell_env_drops_virtual_env(
    tmp_path: Path, sent: Sent, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv = tmp_path / "venv"
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setenv("PATH", f"{venv}/bin:{os.environ['PATH']}")
    manager = TerminalManager(
        send_message=sent, env_overrides={"HOME": str(tmp_path / "home")}
    )
    try:
        await manager.run("s1", workdir, 'echo "VE=[$VIRTUAL_ENV]"; echo "$PATH"')
        await until(lambda: sent.calls)
        lines = sent.runs()[0]["output"].split("\n")
        assert lines[0] == "VE=[]"
        assert str(venv) not in lines[1]
        assert "/usr/bin" in lines[1]
    finally:
        await manager.aclose()


async def test_close_does_not_wait_forever_for_a_stuck_send(
    tmp_path: Path, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(terminal_module, "DELIVER_WAIT_SECONDS", 0.3)

    async def never(session_id: str, text: str) -> bool:
        await asyncio.Event().wait()
        return True

    manager = TerminalManager(send_message=never, env_overrides={"HOME": str(tmp_path / "home")})
    terminal = await manager.open("s1", workdir)
    queue = terminal.subscribe()
    await manager.run("s1", workdir, "true")
    await anyio.sleep(0.5)  # the command ends and its send hangs
    with anyio.fail_after(5):
        await manager.aclose()
    frames = drain(queue)
    assert frames[-1] == {"type": "exit"}
    assert "failed" in run_states(frames)


async def test_run_on_a_closed_terminal_is_a_start_error(
    manager: TerminalManager, sent: Sent, workdir: Path
) -> None:
    terminal = await manager.open("s1", workdir)
    await manager.run("s1", workdir, "sleep 5")
    await until(lambda: terminal.busy)
    await manager.kill("s1", interrupted=True)
    assert terminal.busy  # the end mark never came, yet the terminal is closed
    with pytest.raises(TerminalStartError):
        await terminal.run("echo x")
