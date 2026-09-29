"""Progress of implementation plans (`docs/superpowers/plans/*.md`).

A task starts at a `### Tarefa N: title` (or `### Task N: title`) heading and
runs until the next heading of level 1 to 3. It is done when it has at least
one checkbox and all are checked. Fenced code blocks are ignored.
"""

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_PLAN_BYTES = 2 * 1024 * 1024
PLAN_DIR = ("docs", "superpowers", "plans")
# Tools whose `file_path` input links a conversation to the plan it touches.
PLAN_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write"})

_TASK = re.compile(r"^###\s+(?:Tarefa|Task)\s+(\d+)\s*[:.\-—]\s*(.+?)\s*$", re.IGNORECASE)
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
        if title is None and (match := _TITLE.match(line)):
            title = match.group(1)
            continue
        if match := _TASK.match(line):
            close()
            number, task_title = int(match.group(1)), match.group(2)
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
        if stat.st_size <= MAX_PLAN_BYTES:
            try:
                progress = parse_plan(path.read_text(encoding="utf-8"), path.stem)
            except (OSError, UnicodeDecodeError):
                progress = None
        with self._lock:
            self._entries[path] = (key, progress)
        return progress

    def forget(self, path: Path) -> None:
        with self._lock:
            self._entries.pop(path, None)
