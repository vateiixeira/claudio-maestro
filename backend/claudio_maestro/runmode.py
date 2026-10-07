"""Where the app is running: the official service, a home-made service, a terminal.

Decided once at startup. The official unit and plist set MAESTRO_RUN_MODE; anything
else is guessed from what systemd, launchd or a terminal leave in the process.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

OFFICIAL_UNIT = "claudio-maestro.service"
LAUNCHD_LABEL = "io.github.vateiixeira.claudio-maestro"
KILL_MODE_TIMEOUT = 5

Run = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], str | None]


@dataclass(frozen=True)
class RunMode:
    kind: str  # service-systemd | service-launchd | terminal | systemd | launchd | unknown
    unit: str | None = None
    kill_mode: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _unit_from_cgroup(text: str | None) -> str | None:
    """The last `.service` segment of the process cgroup (systemd puts each unit in its own)."""
    if not text:
        return None
    for line in text.splitlines():
        path = line.rsplit(":", 1)[-1]
        for part in reversed(path.split("/")):
            # user@1000.service is the user manager itself, not a unit someone wrote.
            if part.endswith(".service") and not part.startswith("user@"):
                return part
    return None


def detect_run_mode(env: Mapping[str, str], *, stdin_isatty: bool, cgroup_text: str | None) -> RunMode:
    official = env.get("MAESTRO_RUN_MODE")
    if official == "systemd":
        return RunMode("service-systemd", OFFICIAL_UNIT)
    if official == "launchd":
        return RunMode("service-launchd", LAUNCHD_LABEL)
    # Before the home-made services: a GNOME terminal inherits INVOCATION_ID.
    if stdin_isatty:
        return RunMode("terminal")
    if "INVOCATION_ID" in env:
        unit = _unit_from_cgroup(cgroup_text)
        return RunMode("systemd", unit) if unit else RunMode("unknown")
    xpc = env.get("XPC_SERVICE_NAME")
    if xpc and xpc != "0" and not xpc.startswith("application."):
        return RunMode("launchd", xpc)
    return RunMode("unknown")


def kill_mode(unit: str, *, run: Run = subprocess.run, which: Which = shutil.which) -> str | None:
    systemctl = which("systemctl")
    if systemctl is None:
        return None
    try:
        result = run(
            [systemctl, "--user", "show", unit, "-p", "KillMode", "--value"],
            capture_output=True, text=True, check=False, timeout=KILL_MODE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def _stdin_isatty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):  # closed stdin
        return False


def _read_cgroup() -> str | None:
    try:
        return Path("/proc/self/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None


def current_run_mode(*, run: Run = subprocess.run, which: Which = shutil.which) -> RunMode:
    mode = detect_run_mode(os.environ, stdin_isatty=_stdin_isatty(), cgroup_text=_read_cgroup())
    if mode.kind == "systemd" and mode.unit:
        mode = replace(mode, kill_mode=kill_mode(mode.unit, run=run, which=which))
    return mode
