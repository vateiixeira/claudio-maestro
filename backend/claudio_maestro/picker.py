"""Native folder picker: zenity on Linux, osascript on macOS (no shell)."""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

ZENITY = "zenity"
PICK_TIMEOUT = 5 * 60.0
# zenity exits with 1 when the user cancels (or closes the window).
CANCELLED = 1

OSASCRIPT = "osascript"
# The starting folder arrives as `item 1 of argv`, never pasted into the script text.
MAC_CHOOSE_FOLDER = (
    "return POSIX path of (choose folder default location (POSIX file (item 1 of argv)))"
)
# AppleScript error number when the user cancels the dialog.
MAC_CANCELLED = b"(-128)"

PickFolder = Callable[[Path], Awaitable[str | None]]


class PickerError(Exception):
    """The picker failed. The message is for the log, not for the user."""


class PickerUnavailableError(PickerError):
    """The system picker is not installed or there is no screen to show it on."""


class PickerTimeoutError(PickerError):
    """Nobody chose a folder within the time limit."""


def picker_argv(initial: Path, platform: str) -> tuple[str, ...]:
    """Command line of the system folder picker for `platform` (as in `sys.platform`)."""
    if platform == "darwin":
        return (OSASCRIPT, "-e", "on run argv", "-e", MAC_CHOOSE_FOLDER, "-e", "end run", str(initial))
    return (ZENITY, "--file-selection", "--directory", f"--filename={initial}/")


async def default_spawn(*argv: str, **kwargs: Any) -> Any:
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def pick_folder(
    initial: Path,
    *,
    timeout: float = PICK_TIMEOUT,
    spawn: Callable[..., Awaitable[Any]] | None = None,
    platform: str | None = None,
) -> str | None:
    """Ask the user for a folder, starting at `initial`.

    Returns the chosen path as the system picker printed it, or None when the user
    cancels. The process is killed when the time runs out or the caller is
    cancelled. The route cancels it when the browser disconnects (Starlette
    does not cancel the route itself, so `api/fs.py` polls the connection).
    """
    start = spawn or default_spawn
    system = platform or sys.platform
    try:
        process = await start(
            *picker_argv(initial, system),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise PickerUnavailableError(str(exc)) from exc
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(Exception):
            await asyncio.shield(process.wait())
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise PickerTimeoutError() from exc
    code = process.returncode
    if system == "darwin":
        if code == CANCELLED and MAC_CANCELLED in err:
            return None
        if code != 0:
            raise PickerError(
                f"osascript saiu com código {code}: {err.decode('utf-8', 'replace').strip()}"
            )
        chosen = os.fsdecode(out).rstrip("\r\n")
        if len(chosen) > 1:
            chosen = chosen.rstrip("/")
        return chosen or None
    if code == CANCELLED:
        # Without a screen GTK warns and zenity also exits with 1.
        if b"cannot open display" in err.lower():
            raise PickerUnavailableError(err.decode("utf-8", "replace").strip())
        return None
    if code != 0:
        raise PickerError(f"zenity saiu com código {code}: {err.decode('utf-8', 'replace').strip()}")
    chosen = os.fsdecode(out).rstrip("\r\n")
    return chosen or None
