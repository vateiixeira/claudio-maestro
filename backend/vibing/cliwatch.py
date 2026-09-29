"""Real-time CLI sessions: watch the folder where the CLI saves conversations.

Each session is `<root>/<sanitized cwd>/<session id>.jsonl`. When one changes,
its project is synced again (index, `project.synced`, `session.updated`) and an
open column reloads the conversation (`conversation.reset`). Deeper files
(subagents, memory) are ignored. The periodic sync remains as a fallback.
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import closing, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vibing import db
from vibing.history import HistoryIndex, ListSessions
from vibing.sessions import SessionManager

logger = logging.getLogger(__name__)

# session_info(session_id, directory) -> SDKSessionInfo-like or None.
SessionInfo = Callable[[str, str], Any]
# watch(root) -> async iterator of {(change, path)} batches (watchfiles.awatch).
Watch = Callable[[Path], AsyncIterator[set[tuple[Any, str]]]]

DEFAULT_FIRST_DELAY = 0.3
DEFAULT_INTERVAL = 1.0
DEFAULT_RELOAD_INTERVAL = 1.0
DEFAULT_LIST_TTL = 0.5
DEFAULT_CONCURRENCY = 2
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9]")


def history_folder_name(path: str) -> str:
    """Folder name the CLI uses for a cwd (the SDK's `_sanitize_path`)."""
    try:
        from claude_agent_sdk._internal.sessions import _sanitize_path
    except ImportError:
        return _SANITIZE_RE.sub("-", path)
    return _sanitize_path(path)


def _jsonl_only(change: Any, path: str) -> bool:
    return path.endswith(".jsonl")


def default_watch(root: Path) -> AsyncIterator[set[tuple[Any, str]]]:
    from watchfiles import awatch

    # watchfiles groups changes for 1.6 s by default; the target is ~1 s end to end.
    return awatch(root, watch_filter=_jsonl_only, debounce=100, step=50, recursive=True)


@dataclass
class _Burst:
    folder: str
    dirty: bool = True
    # A reload was skipped by the throttle and is still owed.
    reload_owed: bool = False
    task: asyncio.Task[None] | None = None


class CliWatcher:
    """Throttled per session: first pass `first_delay` after a change, then at
    most one per `interval` while changes keep coming, and always a final pass
    after the last one. Open columns reload at most once per `reload_interval`,
    with a final reload guaranteed."""

    def __init__(
        self,
        root: Path,
        history: HistoryIndex,
        sessions: SessionManager,
        *,
        first_delay: float = DEFAULT_FIRST_DELAY,
        interval: float = DEFAULT_INTERVAL,
        reload_interval: float = DEFAULT_RELOAD_INTERVAL,
        list_ttl: float = DEFAULT_LIST_TTL,
        concurrency: int = DEFAULT_CONCURRENCY,
        watch: Watch | None = None,
        list_sessions: ListSessions | None = None,
        session_info: SessionInfo | None = None,
        clock: Callable[[], float] = time.monotonic,
        on_processed: Callable[[str], None] | None = None,
    ) -> None:
        self._root = root
        self._history = history
        self._sessions = sessions
        self._first_delay = first_delay
        self._interval = interval
        self._reload_interval = reload_interval
        self._list_ttl = list_ttl
        self._watch = watch or default_watch
        self._list_sessions = list_sessions or history.list_sessions
        # Reads only the changed session. Without it, the folder is listed (TTL cache).
        self._session_info = session_info
        self._clock = clock
        self._limit = asyncio.Semaphore(concurrency)
        self._on_processed = on_processed
        self._bursts: dict[str, _Burst] = {}
        self._last_reload: dict[str, float] = {}
        # directory -> (clock time, {session_id: info})
        self._listings: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def pending(self) -> int:
        return len(self._bursts)

    async def run(self) -> None:
        """Watch until cancelled. A missing folder or a failing watcher is logged
        and the periodic sync carries on alone."""
        if not self._root.is_dir():
            logger.warning(
                "Pasta de sessões do CLI %s não existe; só a sincronização periódica vale",
                self._root,
            )
            return
        try:
            async for changes in self._watch(self._root):
                for _change, path in changes:
                    self._schedule(Path(path))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao observar %s; só a sincronização periódica vale", self._root)
        finally:
            await self._cancel_pending()

    async def _cancel_pending(self) -> None:
        tasks = [b.task for b in self._bursts.values() if b.task is not None]
        self._bursts.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    def _schedule(self, path: Path) -> None:
        if path.suffix != ".jsonl" or path.parent.parent != self._root:
            return  # subagents, memory and anything not a session file
        session_id = path.stem
        burst = self._bursts.get(session_id)
        if burst is not None:
            burst.dirty = True
            return
        burst = _Burst(folder=path.parent.name)
        self._bursts[session_id] = burst
        burst.task = asyncio.create_task(self._drive(session_id, path, burst))

    async def _drive(self, session_id: str, path: Path, burst: _Burst) -> None:
        try:
            await asyncio.sleep(self._first_delay)
            while True:
                started = self._clock()
                burst.dirty = False
                try:
                    async with self._limit:
                        done = await self._process(session_id, path, burst)
                except Exception:
                    logger.exception("Falha ao atualizar a sessão %s do CLI", session_id)
                    done = True
                if done and self._on_processed is not None:
                    self._on_processed(session_id)
                # Changes during this wait are handled by the next pass.
                await asyncio.sleep(max(0.0, self._interval - (self._clock() - started)))
                if burst.dirty:
                    continue
                if not burst.reload_owed:
                    break
                # Quiet now: wait just for the owed reload, then a final pass.
                since = self._clock() - self._last_reload.get(session_id, -1e9)
                await asyncio.sleep(max(0.0, self._reload_interval - since))
        finally:
            if self._bursts.get(session_id) is burst:
                del self._bursts[session_id]

    async def _process(self, session_id: str, path: Path, burst: _Burst) -> bool:
        """One pass. False when skipped because the app is writing the session."""
        if self._sessions.app_writing(session_id):
            burst.reload_owed = False
            return False  # the app itself is writing it
        known = await asyncio.to_thread(self._indexed_session, session_id)
        if known is None:
            burst.reload_owed = False
            for owner in await asyncio.to_thread(self._projects_for_folder, burst.folder):
                await self._history.sync_project(owner)
            return True
        project_id, cwd = known
        mtime = await asyncio.to_thread(_file_mtime, path)
        if mtime is None:
            # Gone (or unreadable): the sync removes it only if confirmed missing.
            burst.reload_owed = False
            await self._history.sync_project(project_id)
            return True
        info = await self._listed_info(session_id, cwd)
        if self._sessions.app_writing(session_id):
            burst.reload_owed = False
            return True
        await asyncio.to_thread(self._history.update_session, session_id, int(mtime), info)
        now = self._clock()
        reload = now - self._last_reload.get(session_id, -1e9) >= self._reload_interval
        burst.reload_owed = not reload
        if await self._sessions.apply_external_change(session_id, reload=reload):
            self._last_reload[session_id] = now
        return True

    async def _listed_info(self, session_id: str, cwd: str) -> Any | None:
        if self._session_info is not None:
            try:
                return await asyncio.to_thread(self._session_info, session_id, cwd)
            except Exception:
                logger.exception("Falha ao ler a sessão %s do histórico", session_id)
                return None
        cached = self._listings.get(cwd)
        if cached is None or self._clock() - cached[0] >= self._list_ttl:
            try:
                infos = await asyncio.to_thread(self._list_sessions, cwd)
            except Exception:
                logger.exception("Falha ao listar o histórico de %s", cwd)
                infos = []
            cached = (self._clock(), {i.session_id: i for i in infos})
            self._listings[cwd] = cached
        return cached[1].get(session_id)

    def _indexed_session(self, session_id: str) -> tuple[int, str] | None:
        with closing(db.connect(self._history.db_path)) as conn:
            row = conn.execute(
                "SELECT project_id, cwd FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else (row["project_id"], row["cwd"])

    def _projects_for_folder(self, folder: str) -> list[int]:
        """Projects whose folder, or a folder inside it, maps to this history folder."""
        with closing(db.connect(self._history.db_path)) as conn:
            projects = conn.execute("SELECT id, path FROM projects").fetchall()
        found = []
        for project in projects:
            name = history_folder_name(project["path"])
            if folder == name or folder.startswith(name + "-"):
                found.append(project["id"])
        return found


def _file_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None
