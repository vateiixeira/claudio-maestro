"""Conversations with messages per day and project, read from the CLI history files.

Only sessions of registered projects with activity inside the period are looked
at, and a file is only read again when its modification time changes.
"""

import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from vibing import db
from vibing import history

logger = logging.getLogger(__name__)

SessionFile = Callable[[str, str], Path | None]
_MESSAGE_TYPES = frozenset({"user", "assistant"})


def message_days(path: Path) -> frozenset[date]:
    """Local dates of the user and assistant lines of a `.jsonl` history file."""
    days: set[date] = set()
    with path.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            if '"timestamp"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") not in _MESSAGE_TYPES:
                continue
            stamp = entry.get("timestamp")
            if not isinstance(stamp, str):
                continue
            try:
                moment = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            days.add(moment.astimezone().date())
    return frozenset(days)


class ActivityReader:
    def __init__(
        self,
        db_path: Path,
        session_file: SessionFile | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._session_file = session_file
        self._clock = clock
        self._cache: dict[Path, tuple[float, frozenset[date]]] = {}
        self._lock = threading.Lock()

    def _find(self, session_id: str, cwd: str) -> Path | None:
        finder = self._session_file or history.sdk_session_file
        try:
            return finder(session_id, cwd)
        except Exception:
            logger.exception("Falha ao localizar o histórico da sessão %s", session_id)
            return None

    def read(self, days: int) -> list[dict[str, Any]]:
        """`[{date, project_id, sessions}]` for the last `days` days, today included."""
        today = date.fromtimestamp(self._clock())
        first = today - timedelta(days=days - 1)
        since = datetime.combine(first, datetime.min.time()).timestamp()
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id, project_id, COALESCE(history_dir, cwd) AS cwd FROM sessions"
                " WHERE last_activity_at >= ?",
                (int(since),),
            ).fetchall()
        counts: Counter[tuple[date, int]] = Counter()
        with self._lock:
            used: set[Path] = set()
            for row in rows:
                path = self._find(row["session_id"], row["cwd"])
                if path is None:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime < since:
                    continue
                used.add(path)
                cached = self._cache.get(path)
                if cached is None or cached[0] != mtime:
                    try:
                        cached = (mtime, message_days(path))
                    except OSError:
                        continue
                    self._cache[path] = cached
                for day in cached[1]:
                    if first <= day <= today:
                        counts[(day, row["project_id"])] += 1
            for path in list(self._cache):
                if path not in used:
                    del self._cache[path]
        return [
            {"date": day.isoformat(), "project_id": project_id, "sessions": n}
            for (day, project_id), n in sorted(counts.items())
        ]
