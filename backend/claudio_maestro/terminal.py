"""One terminal (a PTY running the user's shell) per session.

The shell is interactive and prints OSC 133 marks (see `termmarks.py`), so the manager knows
when a command starts and ends. The play button of a code block calls `TerminalManager.run`:
the command is pasted into the shell, its output is captured between the marks and, when it
ends, goes to the session as a user message through the `send_message` callback.

Everything here runs on the event loop of the app: the PTY is read with `add_reader` and
there are no threads. The transport (WebSocket and HTTP) is not here: it subscribes to the
frames of a `Terminal` and writes what the user types.
"""

import asyncio
import codecs
import fcntl
import logging
import os
import secrets
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from claudio_maestro.termformat import RUN_OUTPUT_LIMIT, EndedBy, format_run_message
from claudio_maestro.termmarks import (
    MarkEvent,
    OscTracker,
    bash_rcfile,
    zsh_rcfiles,
)

logger = logging.getLogger(__name__)

REPLAY_LIMIT = 262_144
COALESCE_SECONDS = 0.016
PROMPT_WAIT_SECONDS = 5.0
KILL_GRACE_SECONDS = 2.0
# Quiet time after the prompt mark before the shell counts as ready for a pasted command: the
# mark comes from PROMPT_COMMAND, before readline draws the prompt and enables bracketed paste.
PROMPT_SETTLE_SECONDS = 0.05
# How long a closing terminal waits for the sends in flight before cancelling them.
DELIVER_WAIT_SECONDS = 5.0
# Interval of the fallback watch for the shell's end, where `os.pidfd_open` does not exist.
SHELL_POLL_SECONDS = 0.25
# Interval of the checks while the processes of a closing terminal go away.
STOP_POLL_SECONDS = 0.05

DEFAULT_COLS = 120
DEFAULT_ROWS = 30
SUBSCRIBER_QUEUE_SIZE = 1024
# Raw characters kept of a running command; past this the start is dropped (the message to the
# Claude keeps only the last RUN_OUTPUT_LIMIT characters of the clean output anyway).
CAPTURE_LIMIT = 4 * RUN_OUTPUT_LIMIT

# Ctrl+E (end of line) and Ctrl+U (kill backwards): clears a half-typed line before the paste.
_CLEAR_LINE = "\x05\x15"
_PASTE_START = "\x1b[200~"
_PASTE_END = "\x1b[201~"

Frame = dict[str, Any]
SendMessage = Callable[[str, str], Awaitable[bool]]
RunState = Literal["running", "sent", "interrupted", "failed"]


class TerminalBusyError(Exception):
    """A command is already running in the terminal."""


class TerminalStartError(Exception):
    """The shell could not be started or never showed its first prompt."""


class _Capture:
    """The output of the command started by `run`, between its first start mark and its end."""

    def __init__(self, run_id: str, command: str) -> None:
        self.run_id = run_id
        self.command = command
        self.started_at: float | None = None
        self._chunks: list[str] = []
        self._size = 0

    @property
    def started(self) -> bool:
        return self.started_at is not None

    def add(self, text: str) -> None:
        self._chunks.append(text)
        self._size += len(text)
        if self._size > 2 * CAPTURE_LIMIT:
            joined = "".join(self._chunks)[-CAPTURE_LIMIT:]
            self._chunks = [joined]
            self._size = len(joined)

    def text(self) -> str:
        return "".join(self._chunks)

    def duration_ms(self) -> int:
        if self.started_at is None:
            return 0
        return max(0, round((time.monotonic() - self.started_at) * 1000))


_HAS_PROC = os.path.isdir("/proc/self")


def _session_members(sid: int) -> list[int]:
    """Live processes of the session `sid` (the shell started it, so its id is the shell's pid).

    Job control puts each job in its own process group and `nohup`/`disown` detach it from the
    shell, but they all stay in the session, which is what a closing terminal has to clear.
    """
    members: list[int] = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return members
    wanted = str(sid).encode()
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        # "pid (comm) state ppid pgrp session ...": comm may hold spaces and parentheses.
        fields = data.rpartition(b") ")[2].split()
        if len(fields) > 3 and fields[0] != b"Z" and fields[3] == wanted:
            members.append(int(name))
    return members


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pick_shell(shell: str | None) -> str:
    """The shell executable: bash or zsh (the `$SHELL` of the user, bash for anything else)."""
    candidate = shell if shell is not None else os.environ.get("SHELL", "")
    name = os.path.basename(candidate)
    if name not in ("bash", "zsh"):
        name = "bash"
    if os.path.isabs(candidate) and os.path.basename(candidate) == name:
        if os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(name)
    if found is None and name == "zsh":
        found = shutil.which("bash")
    if found is None:
        raise TerminalStartError(f"Shell not found: {name}")
    return found


def _shell_env(nonce: str, overrides: dict[str, str] | None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CLAUDE", "MAESTRO_"))
        and key not in ("INVOCATION_ID", "JOURNAL_STREAM")
    }
    env.update(
        TERM="xterm-256color",
        COLORTERM="truecolor",
        TERM_PROGRAM="claudio-maestro",
        MAESTRO_OSC_NONCE=nonce,
    )
    if overrides:
        env.update(overrides)
    # The venv of the Maestro is not the one of the project the user works on.
    venv = env.pop("VIRTUAL_ENV", None)
    if venv:
        venv_bin = os.path.join(venv, "bin")
        env["PATH"] = os.pathsep.join(
            entry
            for entry in env.get("PATH", "").split(os.pathsep)
            if os.path.normpath(entry) != os.path.normpath(venv_bin)
        )
    return env


class Terminal:
    """A shell in a PTY, its output history and its subscribers."""

    def __init__(
        self,
        session_id: str,
        cwd: Path,
        *,
        send_message: SendMessage,
        shell: str | None,
        env_overrides: dict[str, str] | None,
        on_closing: Callable[["Terminal", "asyncio.Task[None]"], None],
    ) -> None:
        self.session_id = session_id
        self.cols = DEFAULT_COLS
        self.rows = DEFAULT_ROWS
        self._send_message = send_message
        self._on_closing = on_closing
        self._loop = asyncio.get_running_loop()
        self._nonce = secrets.token_hex(8)
        self._tracker = OscTracker(self._nonce)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._replay = ""
        self._pending_output: list[str] = []
        self._flush_handle: asyncio.TimerHandle | None = None
        self._subscribers: list[asyncio.Queue[Frame]] = []
        self._announced_busy = False
        self._at_prompt = asyncio.Event()
        self._prompt_seen = False
        self._settle_handle: asyncio.TimerHandle | None = None
        self._capture: _Capture | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._out = bytearray()
        self._writer_on = False
        self._alive = True
        self._close_task: asyncio.Task[None] | None = None
        self._tmpdir = Path(tempfile.mkdtemp(prefix="maestro-term-"))
        self._master_fd = -1
        try:
            self._proc = self._spawn(cwd, shell, env_overrides)
        except BaseException:
            self._cleanup_files()
            if self._master_fd >= 0:
                os.close(self._master_fd)
            raise
        self._loop.add_reader(self._master_fd, self._on_readable)
        self._pidfd = -1
        self._poll_handle: asyncio.TimerHandle | None = None
        self._watch_shell()

    # Start ---------------------------------------------------------------------------

    def _spawn(
        self, cwd: Path, shell: str | None, env_overrides: dict[str, str] | None
    ) -> "subprocess.Popen[bytes]":
        exe = _pick_shell(shell)
        env = _shell_env(self._nonce, env_overrides)
        if os.path.basename(exe) == "zsh":
            for name, content in zsh_rcfiles().items():
                (self._tmpdir / name).write_text(content)
            env["ZDOTDIR"] = str(self._tmpdir)
            args = [exe, "-i"]
        else:
            rcfile = self._tmpdir / "bashrc"
            rcfile.write_text(bash_rcfile())
            args = [exe, "--rcfile", str(rcfile), "-i"]
        master, slave = os.openpty()
        self._master_fd = master
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
            os.set_blocking(master, False)
            try:
                return subprocess.Popen(
                    args,
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=cwd,
                    env=env,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise TerminalStartError(f"Could not start the shell: {exc}") from exc
        finally:
            os.close(slave)

    def _watch_shell(self) -> None:
        """Notice the end of the shell even when the PTY never reaches EOF.

        A background job that outlives the shell keeps the slave side open, so the master
        does not read EOF.
        """
        opener = getattr(os, "pidfd_open", None)
        if opener is not None:
            try:
                self._pidfd = opener(self._proc.pid)
            except OSError:
                self._pidfd = -1
            else:
                self._loop.add_reader(self._pidfd, self._shell_exited)
                return
        self._poll_handle = self._loop.call_later(SHELL_POLL_SECONDS, self._poll_shell)

    def _poll_shell(self) -> None:
        self._poll_handle = None
        if not self._alive:
            return
        if self._proc.poll() is not None:
            self._shell_exited()
        else:
            self._poll_handle = self._loop.call_later(SHELL_POLL_SECONDS, self._poll_shell)

    def _unwatch_shell(self) -> None:
        if self._pidfd >= 0:
            self._loop.remove_reader(self._pidfd)
            with suppress(OSError):
                os.close(self._pidfd)
            self._pidfd = -1
        if self._poll_handle is not None:
            self._poll_handle.cancel()
            self._poll_handle = None

    # State ---------------------------------------------------------------------------

    @property
    def pid(self) -> int:
        """Process id of the shell, which is also the id of its process group."""
        return self._proc.pid

    @property
    def busy(self) -> bool:
        """True while a command runs in the shell (between its start and end marks)."""
        return self._tracker.busy

    @property
    def closed(self) -> bool:
        return not self._alive

    def replay(self) -> str:
        """The last `REPLAY_LIMIT` characters the shell printed, marks included.

        To show the history and follow the output, call `replay()` and then `subscribe()`
        with no `await` between them, so that nothing is lost or repeated.
        """
        return self._replay

    # Subscribers ---------------------------------------------------------------------

    def subscribe(self) -> "asyncio.Queue[Frame]":
        # What is buffered already went into the replay; do not hand it to the new queue.
        self._flush_output()
        queue: asyncio.Queue[Frame] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[Frame]") -> None:
        with suppress(ValueError):
            self._subscribers.remove(queue)

    def _publish(self, frame: Frame) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                self._drop(queue)

    def _drop(self, queue: "asyncio.Queue[Frame]") -> None:
        """Disconnect a subscriber that does not keep up: it gets only an `exit`."""
        self.unsubscribe(queue)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait({"type": "exit"})

    def _flush_output(self) -> None:
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._pending_output:
            data = "".join(self._pending_output)
            self._pending_output.clear()
            self._publish({"type": "output", "data": data})

    # Reading -------------------------------------------------------------------------

    def _on_readable(self) -> None:
        try:
            data = os.read(self._master_fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._shell_exited()
            return
        self._consume(data)

    def _drain(self) -> None:
        """Read what the shell left in the PTY before it ended (bounded: a job may keep writing)."""
        for _ in range(32):
            try:
                data = os.read(self._master_fd, 65536)
            except OSError:
                return
            if not data:
                return
            self._consume(data)

    def _consume(self, data: bytes) -> None:
        text = self._decoder.decode(data)
        if not text:
            return
        self._replay = (self._replay + text)[-REPLAY_LIMIT:]
        self._pending_output.append(text)
        if self._flush_handle is None:
            self._flush_handle = self._loop.call_later(COALESCE_SECONDS, self._flush_output)
        self._handle_events(self._tracker.feed(text))
        if self._prompt_seen:
            self._arm_settle()
        if self._tracker.busy != self._announced_busy:
            self._announced_busy = self._tracker.busy
            self._flush_output()
            self._publish({"type": "busy", "busy": self._announced_busy})

    def _handle_events(self, events: list[MarkEvent]) -> None:
        for kind, value in events:
            capture = self._capture
            if kind == "text":
                if capture is not None and capture.started:
                    capture.add(value)
            elif kind == "start":
                self._set_not_ready()
                if capture is not None and capture.started_at is None:
                    capture.started_at = time.monotonic()
            elif kind == "end":
                if capture is not None and capture.started:
                    self._end_capture("done", value)
            else:  # prompt
                self._prompt_seen = True
                if capture is not None and not capture.started:
                    # The shell ran nothing (an empty line or a comment): it is back at the prompt.
                    self._end_capture("done", None)

    def _arm_settle(self) -> None:
        if self._settle_handle is not None:
            self._settle_handle.cancel()
        self._settle_handle = self._loop.call_later(PROMPT_SETTLE_SECONDS, self._settled)

    def _settled(self) -> None:
        self._settle_handle = None
        if self._prompt_seen and self._alive:
            self._at_prompt.set()

    def _set_not_ready(self) -> None:
        self._prompt_seen = False
        self._at_prompt.clear()
        if self._settle_handle is not None:
            self._settle_handle.cancel()
            self._settle_handle = None

    def _shell_exited(self) -> None:
        if self._alive:
            self._drain()
            self._start_close(interrupted=False)

    # Writing -------------------------------------------------------------------------

    def write(self, data: str) -> None:
        """Send what the user typed to the shell."""
        if not self._alive:
            return
        capture = self._capture
        if capture is not None and capture.started and "\r" in data:
            self._end_capture("input", None)
        self._send_bytes(data.encode("utf-8", errors="replace"))

    def resize(self, cols: int, rows: int) -> None:
        if not self._alive or cols < 1 or rows < 1:
            return
        cols, rows = min(cols, 65535), min(rows, 65535)
        self.cols, self.rows = cols, rows
        with suppress(OSError):
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _send_bytes(self, data: bytes) -> None:
        self._out += data
        self._flush_input()

    def _flush_input(self) -> None:
        while self._out and self._alive:
            try:
                written = os.write(self._master_fd, self._out)
            except BlockingIOError:
                if not self._writer_on:
                    self._loop.add_writer(self._master_fd, self._flush_input)
                    self._writer_on = True
                return
            except OSError:
                self._out.clear()
                break
            del self._out[:written]
        if self._writer_on:
            self._loop.remove_writer(self._master_fd)
            self._writer_on = False

    # Runs ----------------------------------------------------------------------------

    async def run(self, command: str) -> str:
        """Paste `command` into the shell and capture its output; returns the run id."""
        if not command.strip():
            raise ValueError("Empty command")
        self._check_free()
        if not self._at_prompt.is_set():
            try:
                await asyncio.wait_for(self._at_prompt.wait(), PROMPT_WAIT_SECONDS)
            except TimeoutError:
                self._check_free()
                raise TerminalStartError("The shell did not show its prompt in time") from None
            self._check_free()
        run_id = uuid.uuid4().hex
        self._capture = _Capture(run_id, command)
        self._set_not_ready()
        pasted = command.replace(_PASTE_START, "").replace(_PASTE_END, "")
        self._send_bytes(f"{_CLEAR_LINE}{_PASTE_START}{pasted}{_PASTE_END}\r".encode())
        self._publish({"type": "run", "run_id": run_id, "state": "running", "exit_code": None})
        return run_id

    def _check_free(self) -> None:
        if not self._alive:
            raise TerminalStartError("The terminal was closed")
        if self._capture is not None or self._tracker.busy:
            raise TerminalBusyError("A command is already running")

    def _end_capture(
        self, ended_by: EndedBy, exit_code: int | None, *, send: bool = True
    ) -> None:
        capture, self._capture = self._capture, None
        if capture is None:
            return
        if not send:
            self._publish(
                {"type": "run", "run_id": capture.run_id, "state": "interrupted", "exit_code": None}
            )
            return
        task = asyncio.ensure_future(
            self._deliver(capture, exit_code, capture.duration_ms(), ended_by)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(
        self, capture: _Capture, exit_code: int | None, duration_ms: int, ended_by: EndedBy
    ) -> None:
        ok = False
        try:
            text = format_run_message(
                capture.command, capture.text(), exit_code, duration_ms, ended_by
            )
            ok = await self._send_message(self.session_id, text)
        except Exception:
            logger.exception("Could not send the terminal run to session %s", self.session_id)
        except asyncio.CancelledError:
            self._publish(
                {"type": "run", "run_id": capture.run_id, "state": "failed", "exit_code": exit_code}
            )
            raise
        state: RunState = "sent" if ok else "failed"
        self._publish(
            {"type": "run", "run_id": capture.run_id, "state": state, "exit_code": exit_code}
        )

    # Closing -------------------------------------------------------------------------

    async def close(self, *, interrupted: bool) -> None:
        """Stop the shell and everything it started. Safe to call more than once."""
        await asyncio.shield(self._start_close(interrupted=interrupted))

    async def wait_closed(self) -> None:
        if self._close_task is not None:
            await asyncio.shield(self._close_task)

    def _start_close(self, *, interrupted: bool) -> "asyncio.Task[None]":
        if self._close_task is not None:
            return self._close_task
        self._alive = False
        self._unwatch_shell()
        self._loop.remove_reader(self._master_fd)
        if self._writer_on:
            self._loop.remove_writer(self._master_fd)
            self._writer_on = False
        self._flush_output()
        self._set_not_ready()
        self._at_prompt.set()  # wakes a `run` that is waiting for the prompt
        self._end_capture("shell-exit", None, send=not interrupted)
        self._close_task = asyncio.ensure_future(self._close())
        self._close_task.add_done_callback(self._log_close_failure)
        self._on_closing(self, self._close_task)
        return self._close_task

    @staticmethod
    def _log_close_failure(task: "asyncio.Task[None]") -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.error("Closing a terminal failed", exc_info=task.exception())

    async def _close(self) -> None:
        try:
            await self._terminate()
            if self._tasks:
                _, stuck = await asyncio.wait(set(self._tasks), timeout=DELIVER_WAIT_SECONDS)
                for task in stuck:
                    task.cancel()
                if stuck:
                    await asyncio.gather(*stuck, return_exceptions=True)
        finally:
            self._publish({"type": "exit"})
            self._subscribers.clear()
            with suppress(OSError):
                os.close(self._master_fd)
            self._cleanup_files()

    def _signal(self, signum: int) -> None:
        """Signal every process of the shell's session, not only its process group."""
        for pid in _session_members(self.pid):
            with suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signum)
        if not _HAS_PROC and self._proc.returncode is None:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(self.pid, signum)

    def _running(self) -> bool:
        if self._proc.poll() is None or _session_members(self.pid):
            return True
        return not _HAS_PROC and _group_alive(self.pid)

    async def _wait_gone(self, timeout: float, *, resignal: int | None = None) -> bool:
        deadline = self._loop.time() + timeout
        while self._running():
            if self._loop.time() >= deadline:
                return False
            if resignal is not None:
                self._signal(resignal)  # catches what the dying processes forked meanwhile
            await asyncio.sleep(STOP_POLL_SECONDS)
        return True

    async def _terminate(self) -> None:
        """SIGHUP to the whole session, SIGKILL after the grace period (as `_stop` in gitinfo)."""
        try:
            if self._running():
                self._signal(signal.SIGHUP)
                if await self._wait_gone(KILL_GRACE_SECONDS):
                    return
        except BaseException:
            # Cancelled while waiting: the processes must still not outlive us.
            self._signal(signal.SIGKILL)
            raise
        self._signal(signal.SIGKILL)
        try:
            await self._wait_gone(KILL_GRACE_SECONDS, resignal=signal.SIGKILL)
        except BaseException:
            self._signal(signal.SIGKILL)
            raise

    def _cleanup_files(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TerminalManager:
    """The terminals of the app, one per session."""

    def __init__(
        self,
        *,
        send_message: SendMessage,
        shell: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        self._send_message = send_message
        self._shell = shell
        self._env_overrides = env_overrides
        self._terminals: dict[str, Terminal] = {}
        self._closing: set[asyncio.Task[None]] = set()

    def get(self, session_id: str) -> Terminal | None:
        return self._terminals.get(session_id)

    async def open(self, session_id: str, cwd: Path) -> Terminal:
        """The live terminal of the session, started in `cwd` when there is none."""
        existing = self._terminals.get(session_id)
        if existing is not None:
            return existing
        try:
            terminal = Terminal(
                session_id,
                cwd,
                send_message=self._send_message,
                shell=self._shell,
                env_overrides=self._env_overrides,
                on_closing=self._on_closing,
            )
        except OSError as exc:
            raise TerminalStartError(f"Could not start the terminal: {exc}") from exc
        self._terminals[session_id] = terminal
        return terminal

    async def run(self, session_id: str, cwd: Path, command: str) -> str:
        """Run `command` in the terminal of the session; returns the run id."""
        terminal = await self.open(session_id, cwd)
        return await terminal.run(command)

    async def kill(self, session_id: str, *, interrupted: bool) -> None:
        terminal = self._terminals.get(session_id)
        if terminal is not None:
            await terminal.close(interrupted=interrupted)

    async def aclose(self) -> None:
        await asyncio.gather(
            *(t.close(interrupted=True) for t in list(self._terminals.values())),
            return_exceptions=True,
        )
        if self._closing:
            await asyncio.gather(*list(self._closing), return_exceptions=True)

    def _on_closing(self, terminal: Terminal, task: "asyncio.Task[None]") -> None:
        if self._terminals.get(terminal.session_id) is terminal:
            del self._terminals[terminal.session_id]
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
