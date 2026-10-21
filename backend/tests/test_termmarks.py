"""Tests for the OSC 133 mark reader and the shell rcfiles."""

import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claudio_maestro.termmarks import OscTracker, bash_rcfile, zsh_rcfiles

NONCE = "n0nce42"


def mark_a(nonce: str = NONCE) -> str:
    return f"\x1b]133;A;{nonce}\x07"


def mark_c(nonce: str = NONCE) -> str:
    return f"\x1b]133;C;{nonce}\x07"


def mark_d(code: int, nonce: str = NONCE) -> str:
    return f"\x1b]133;D;{code};{nonce}\x07"


def test_feed_splits_text_and_marks():
    tracker = OscTracker(NONCE)
    tracker.feed(mark_d(0) + mark_a() + "$ ")
    echo = "cd /usr\r\npwd\r\nls -d bin\r\n"
    prompt = "$ "
    # A multi-line paste: one C per line, a single D with the last exit code.
    stream = (
        echo
        + mark_c()
        + "/usr\r\n"
        + mark_c()
        + "bin\r\n"
        + mark_c()
        + mark_d(3)
        + mark_a()
        + prompt
    )
    events = tracker.feed(stream)
    assert events == [
        ("text", echo),
        ("start", None),
        ("text", "/usr\r\n"),
        ("start", None),
        ("text", "bin\r\n"),
        ("start", None),
        ("end", 3),
        ("prompt", None),
        ("text", prompt),
    ]
    assert tracker.busy is False


def test_busy_between_start_and_end():
    tracker = OscTracker(NONCE)
    assert tracker.busy is False
    tracker.feed(mark_c())
    assert tracker.busy is True
    tracker.feed(mark_c())
    assert tracker.busy is True
    tracker.feed(mark_d(0))
    assert tracker.busy is False


def test_orphan_end_before_first_start_is_dropped():
    tracker = OscTracker(NONCE)
    assert tracker.ready is False
    events = tracker.feed(mark_d(0) + mark_a() + "$ ")
    assert events == [("prompt", None), ("text", "$ ")]
    assert tracker.ready is True
    assert tracker.busy is False


def test_end_after_end_is_dropped():
    tracker = OscTracker(NONCE)
    events = tracker.feed(mark_c() + mark_d(0) + mark_d(1))
    assert events == [("start", None), ("end", 0)]


def test_end_carries_exit_code():
    tracker = OscTracker(NONCE)
    events = tracker.feed(mark_c() + mark_d(130))
    assert events == [("start", None), ("end", 130)]


def test_mark_split_across_chunks():
    tracker = OscTracker(NONCE)
    mark = mark_d(7)
    full = "out\r\n" + mark + "after"
    tracker.feed(mark_c())
    cut = full.index("133") + 5
    first = tracker.feed(full[:cut])
    second = tracker.feed(full[cut:])
    assert first == [("text", "out\r\n")]
    assert second == [("end", 7), ("text", "after")]
    assert tracker.busy is False


@pytest.mark.parametrize("cut", range(1, len("\x1b]133;D;5;n0nce42\x07")))
def test_mark_split_at_every_position(cut):
    tracker = OscTracker(NONCE)
    tracker.feed(mark_c())
    mark = mark_d(5)
    events = tracker.feed("x" + mark[:cut]) + tracker.feed(mark[cut:] + "y")
    assert events == [("text", "x"), ("end", 5), ("text", "y")]


def test_marks_with_wrong_nonce_are_text():
    tracker = OscTracker(NONCE)
    tracker.feed(mark_c())
    forged = "\x1b]133;D;0;outro\x07"
    events = tracker.feed(forged)
    assert events == [("text", forged)]
    assert tracker.busy is True
    forged_a = "\x1b]133;A;outro\x07"
    assert tracker.feed(forged_a) == [("text", forged_a)]
    assert tracker.ready is False


def test_other_escape_sequences_pass_through_as_text():
    tracker = OscTracker(NONCE)
    text = "\x1b[H\x1b[2J\x1b[3Jhello \x1b]0;title\x07\x1b[31mred\x1b[0m"
    assert tracker.feed(text) == [("text", text)]


def test_escape_at_chunk_end_is_held_until_resolved():
    tracker = OscTracker(NONCE)
    assert tracker.feed("abc\x1b") == [("text", "abc")]
    assert tracker.feed("[31mred") == [("text", "\x1b[31mred")]


def test_unterminated_escape_is_flushed_as_text_after_limit():
    tracker = OscTracker(NONCE)
    assert tracker.feed("\x1b]133;") == []
    filler = "x" * 300
    events = tracker.feed(filler)
    assert events == [("text", "\x1b]133;" + filler)]
    # Back to normal afterwards.
    assert tracker.feed(mark_a()) == [("prompt", None)]


def test_unterminated_escape_in_single_chunk_is_flushed():
    tracker = OscTracker(NONCE)
    data = "\x1b]133;" + "y" * 400
    assert tracker.feed(data) == [("text", data)]


def test_text_after_failed_prefix_still_finds_later_marks():
    tracker = OscTracker(NONCE)
    events = tracker.feed("\x1b]133;junk" + mark_c() + "ok")
    assert events == [("text", "\x1b]133;junk"), ("start", None), ("text", "ok")]


def test_empty_feed_returns_nothing():
    tracker = OscTracker(NONCE)
    assert tracker.feed("") == []


def test_bash_rcfile_content():
    rc = bash_rcfile()
    assert "[ -f ~/.bashrc ] && . ~/.bashrc" in rc
    assert "__maestro_nonce=$MAESTRO_OSC_NONCE; unset MAESTRO_OSC_NONCE" in rc
    assert "PROMPT_COMMAND=" in rc
    assert "PS0=" in rc
    assert "133;D" in rc
    assert "133;A" in rc
    assert "133;C" in rc
    assert rc.endswith("\n")


def test_zsh_rcfiles_content():
    files = zsh_rcfiles()
    assert set(files) == {".zshenv", ".zshrc"}
    assert '"$HOME/.zshenv"' in files[".zshenv"]
    assert '"$HOME/.zshrc"' in files[".zshrc"]
    assert "MAESTRO_OSC_NONCE" in files[".zshenv"]
    assert "unset MAESTRO_OSC_NONCE" in files[".zshenv"]
    rc = files[".zshrc"]
    assert "add-zsh-hook precmd" in rc
    assert "add-zsh-hook preexec" in rc
    assert "133;D" in rc and "133;A" in rc and "133;C" in rc
    # The user's files load before the hooks are registered.
    assert rc.index('"$HOME/.zshrc"') < rc.index("add-zsh-hook")


def _read_for(fd: int, seconds: float) -> str:
    out = b""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    return out.decode("utf-8", "replace")


def _read_until(fd: int, tracker: OscTracker, predicate, timeout: float = 8.0):
    events: list = []
    end = time.monotonic() + timeout
    while time.monotonic() < end and not predicate(events):
        events += tracker.feed(_read_for(fd, 0.1))
    return events


def _run_shell(argv: list[str], env: dict[str, str], cwd: Path):
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=cwd,
        env=env,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    return master, proc


def _shell_env(home: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "MAESTRO_"))
    }
    env.update(HOME=str(home), TERM="xterm-256color", MAESTRO_OSC_NONCE=NONCE)
    return env


def _exercise_shell(master: int, proc: subprocess.Popen):
    tracker = OscTracker(NONCE)
    try:
        events = _read_until(master, tracker, lambda ev: tracker.ready)
        assert tracker.ready, events
        os.write(master, b"echo hi; (exit 4)\r")
        events = _read_until(master, tracker, lambda ev: ("end", 4) in ev)
        kinds = [e for e in events if e[0] != "text"]
        assert ("start", None) in kinds
        assert ("end", 4) in kinds
        output = "".join(e[1] for e in events if e[0] == "text")
        assert "hi" in output
        assert NONCE not in output
        assert "\x1b]133" not in output
        # The nonce must not leak to child processes.
        os.write(master, b'echo "leak=[$MAESTRO_OSC_NONCE]"\r')
        events = _read_until(master, tracker, lambda ev: ("end", 0) in ev)
        output = "".join(e[1] for e in events if e[0] == "text")
        assert "leak=[]" in output
    finally:
        try:
            os.write(master, b"exit\r")
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        os.close(master)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_real_bash_emits_marks(tmp_path):
    home = tmp_path / "userhome"
    home.mkdir()
    rc = tmp_path / "rc"
    rc.write_text(bash_rcfile())
    master, proc = _run_shell(
        [shutil.which("bash"), "--rcfile", str(rc), "-i"], _shell_env(home), tmp_path
    )
    _exercise_shell(master, proc)


@pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")
def test_real_zsh_emits_marks(tmp_path):
    home = tmp_path / "userhome"
    home.mkdir()
    (home / ".zshrc").write_text("PROMPT='%% '\n")
    zdot = tmp_path / "zdot"
    zdot.mkdir()
    for name, content in zsh_rcfiles().items():
        (zdot / name).write_text(content)
    env = _shell_env(home)
    env["ZDOTDIR"] = str(zdot)
    master, proc = _run_shell([shutil.which("zsh"), "-i"], env, tmp_path)
    _exercise_shell(master, proc)
