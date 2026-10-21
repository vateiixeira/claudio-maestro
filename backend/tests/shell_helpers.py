"""Shells for the terminal tests: which bash can run the terminal marks."""

import os
import shutil
import subprocess

MIN_BASH = (4, 4)
# Where Homebrew installs bash; the PATH of a service may not list them.
_FIXED_BASH = ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", "/bin/bash")


def _bash_version(path: str) -> tuple[int, int] | None:
    if not os.access(path, os.X_OK):
        return None
    try:
        out = subprocess.run(
            [path, "--norc", "--noprofile", "-c", 'printf "%s.%s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"'],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        ).stdout
        major, minor = out.strip().split(".")
        return int(major), int(minor)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def capable_bash() -> str | None:
    """A bash 4.4 or newer (the `PS0` of the marks needs it), or None when there is none."""
    candidates = [shutil.which("bash"), *_FIXED_BASH]
    for path in candidates:
        if path is None:
            continue
        version = _bash_version(path)
        if version is not None and version >= MIN_BASH:
            return path
    return None
