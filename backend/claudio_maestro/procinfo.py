"""Best-effort start time of a live process, without inspecting its command line."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

_PROC = Path("/proc")
_ELAPSED = re.compile(
    r"(?:(?:(?P<days>\d+)-)?(?P<hours>\d+):)?(?P<minutes>\d+):(?P<seconds>\d+)"
)


def process_started_at(pid: int) -> float | None:
    """Epoch seconds at which pid started, or None when unavailable. Never raises."""
    try:
        if pid <= 0:
            return None
        if sys.platform == "linux":
            stat = (_PROC / str(pid) / "stat").read_text()
            # comm (field 2) may contain spaces and ')'; state is field 3.
            ticks = int(stat[stat.rindex(")") + 1:].split()[19])
            boot = next(line.split()[1] for line in (_PROC / "stat").read_text().splitlines()
                        if line.startswith("btime "))
            return int(boot) + ticks / os.sysconf("SC_CLK_TCK")
        result = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(pid)],
            capture_output=True, text=True, timeout=2, check=True,
        )
        match = _ELAPSED.fullmatch(result.stdout.strip())
        if match is None:
            return None
        days, hours, minutes, seconds = (
            int(match.group(name) or 0) for name in ("days", "hours", "minutes", "seconds")
        )
        if minutes >= 60 or seconds >= 60 or (days and hours >= 24):
            return None
        return time.time() - (days * 86400 + hours * 3600 + minutes * 60 + seconds)
    except Exception:
        # Metadata may disappear mid-read, be malformed, or be inaccessible.
        return None
