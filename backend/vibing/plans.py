"""Progress of implementation plans (`docs/superpowers/plans/*.md`).

A task starts at a `### Tarefa N: title` (or `### Task N: title`) heading, with any
separator (`:`, `.`, `-`, `–`, `—`) or none, and an empty title meaning "Tarefa N". It
runs until the next heading of level 1 to 3. It is done when it has at least
one checkbox and all are checked. Fenced code blocks are ignored.
"""

import json
import os
import re
import stat as stat_module
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_PLAN_BYTES = 2 * 1024 * 1024
PLAN_DIR = ("docs", "superpowers", "plans")
# Tools whose `file_path` input links a conversation to the plan it touches.
PLAN_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write"})

_TASK = re.compile(
    r"^###\s+(?:Tarefa|Task)\s+(\d+)(?!\w)\s*[:.\-–—]?\s*(.*?)\s*$", re.IGNORECASE
)
_HEADING = re.compile(r"^(#{1,3})\s+\S")
_TITLE = re.compile(r"^#\s+(.+?)\s*$")
_BOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class PlanTask:
    number: int
    title: str
    done: bool


@dataclass(frozen=True)
class PlanProgress:
    title: str
    tasks: tuple[PlanTask, ...]

    @property
    def total(self) -> int:
        return len(self.tasks)

    @property
    def done(self) -> int:
        return sum(1 for task in self.tasks if task.done)

    @property
    def current(self) -> PlanTask | None:
        return next((task for task in self.tasks if not task.done), None)

    def summary(self, path: str) -> dict[str, Any]:
        current = self.current
        return {
            "path": path, "title": self.title, "total": self.total, "done": self.done,
            "current": {"number": current.number, "title": current.title} if current else None,
        }


def parse_plan(text: str, fallback_title: str) -> PlanProgress | None:
    title: str | None = None
    tasks: list[PlanTask] = []
    number: int | None = None
    task_title = ""
    boxes = checked = 0
    in_fence = False

    def close() -> None:
        if number is not None:
            tasks.append(PlanTask(number, task_title, boxes > 0 and boxes == checked))

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if title is None and not tasks and number is None and (match := _TITLE.match(line)):
            title = match.group(1)
            continue
        if match := _TASK.match(line):
            close()
            number = int(match.group(1))
            task_title = match.group(2) or f"Tarefa {number}"
            boxes = checked = 0
            continue
        if _HEADING.match(line):
            close()
            number = None
            continue
        if number is not None and (match := _BOX.match(line)):
            boxes += 1
            checked += match.group(1) in "xX"
    close()
    if not tasks:
        return None
    return PlanProgress(title or fallback_title, tuple(tasks))


def looks_like_plan_path(path: str) -> bool:
    """Cheap textual check (no disk, no database) that `path` may be a plan: a `.md`
    with `docs/superpowers/plans/` in it. Only `is_plan_path` decides."""
    return path.lower().endswith(".md") and "/".join(PLAN_DIR) + "/" in path


def is_plan_path(path: str | Path, project_roots: Iterable[Path]) -> Path | None:
    """The resolved plan path when it is a `.md` directly inside a
    `docs/superpowers/plans/` folder of a registered project; None otherwise."""
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved.suffix.lower() != ".md" or tuple(resolved.parent.parts[-3:]) != PLAN_DIR:
        return None
    for root in project_roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def _plan_tool_paths(blocks: Iterable[Any]) -> Iterable[str]:
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("name") in PLAN_TOOLS
            and isinstance(block.get("input"), dict)
            and isinstance(block["input"].get("file_path"), str)
            and looks_like_plan_path(block["input"]["file_path"])
        ):
            yield block["input"]["file_path"]


def last_plan_ref(entries: Iterable[Any]) -> str | None:
    """The last plan-looking `file_path` a plan tool (`PLAN_TOOLS`) used among saved
    conversation entries (`SessionMessage`-like, `message.content` in the API format)."""
    last: str | None = None
    for entry in entries:
        message = getattr(entry, "message", None)
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for path in _plan_tool_paths(content):
                last = path
    return last


def scan_plan_refs(lines: Iterable[str]) -> str | None:
    """The last plan-looking `file_path` (see `looks_like_plan_path`) of a plan tool
    call in JSONL lines of a session file (main chain or `isSidechain`), so a later
    edit of another file does not hide the plan. Invalid lines are ignored."""
    last: str | None = None
    for line in lines:
        if '"tool_use"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for path in _plan_tool_paths(content):
                last = path
    return last


def read_new_lines(
    path: Path, offset: int | None, *, tail: int = 256 * 1024
) -> tuple[list[str], int]:
    """Complete lines of `path` from `offset`, and the offset after the last one.

    With no offset (or one past the end, after a truncation) only the last `tail`
    bytes are read and a partial first line is dropped. A last line without a
    newline (still being written) is left for the next call.
    """
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        fresh = offset is None or offset > size
        start = max(0, size - tail) if fresh else offset
        partial_first = False
        if fresh and start > 0:
            handle.seek(start - 1)
            partial_first = handle.read(1) != b"\n"
        handle.seek(start)
        data = handle.read(size - start)
    end = data.rfind(b"\n")
    if end < 0:
        return [], start
    lines = data[: end + 1].decode("utf-8", errors="replace").splitlines()
    if partial_first and lines:
        lines = lines[1:]
    return lines, start + end + 1


def _read_limited(path: Path) -> str | None:
    """Text of a regular file of at most `MAX_PLAN_BYTES`; None for anything else
    (FIFO, device, too big, unreadable, not UTF-8). The open never blocks on a FIFO
    and at most `MAX_PLAN_BYTES + 1` bytes are read, whatever the file grew to."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat_module.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks: list[bytes] = []
        remaining = MAX_PLAN_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining <= 0:
            return None  # more than the limit
        return b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)


class PlanCache:
    """Parsed plans by path, re-read only when size or mtime changes. Thread-safe."""

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[tuple[int, int], PlanProgress | None]] = {}
        self._lock = threading.Lock()

    def read(self, path: Path) -> PlanProgress | None:
        try:
            stat = path.stat()
        except OSError:
            with self._lock:
                self._entries.pop(path, None)
            return None
        key = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get(path)
        if entry is not None and entry[0] == key:
            return entry[1]
        progress: PlanProgress | None = None
        if stat_module.S_ISREG(stat.st_mode) and stat.st_size <= MAX_PLAN_BYTES:
            text = _read_limited(path)
            if text is not None:
                progress = parse_plan(text, path.stem)
        with self._lock:
            self._entries[path] = (key, progress)
        return progress

    def forget(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(path, None)
