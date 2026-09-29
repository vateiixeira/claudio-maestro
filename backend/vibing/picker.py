"""Native folder picker: runs `zenity --file-selection --directory` (no shell)."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

ZENITY = "zenity"
PICK_TIMEOUT = 5 * 60.0
# zenity exits with 1 when the user cancels (or closes the window).
CANCELLED = 1

PickFolder = Callable[[Path], Awaitable[str | None]]


class PickerError(Exception):
    """The picker failed. The message is for the log, not for the user."""


class PickerUnavailableError(PickerError):
    """zenity is not installed or there is no screen to show it on."""


class PickerTimeoutError(PickerError):
    """Nobody chose a folder within the time limit."""


async def default_spawn(*argv: str, **kwargs: Any) -> Any:
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def pick_folder(
    initial: Path,
    *,
    timeout: float = PICK_TIMEOUT,
    spawn: Callable[..., Awaitable[Any]] | None = None,
) -> str | None:
    """Ask the user for a folder, starting at `initial`.

    Returns the chosen path as zenity printed it, or None when the user
    cancels. The process is killed when the time runs out or the caller is
    cancelled (e.g. the browser closed the request).
    """
    start = spawn or default_spawn
    try:
        process = await start(
            ZENITY, "--file-selection", "--directory", f"--filename={initial}/",
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
    if code == CANCELLED:
        # Without a screen GTK warns and zenity also exits with 1.
        if b"cannot open display" in err.lower():
            raise PickerUnavailableError(err.decode("utf-8", "replace").strip())
        return None
    if code != 0:
        raise PickerError(f"zenity saiu com código {code}: {err.decode('utf-8', 'replace').strip()}")
    chosen = os.fsdecode(out).rstrip("\r\n")
    return chosen or None
