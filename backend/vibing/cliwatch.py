"""Real-time CLI sessions: watch the folder where the CLI saves conversations.

Each session is `<root>/<sanitized cwd>/<session id>.jsonl`. When one changes,
its project is synced again (index, `project.synced`, `session.updated`) and an
open column reloads the conversation (`conversation.reset`). Subagent files
(`<session>/subagents/agent-*.jsonl`) are not sessions: a change in one only counts
as activity of the parent session and feeds the plan link. Memory and other deeper
files are ignored. The periodic sync remains as a fallback.

The lines written since the last pass also tell whether the CLI is in the middle of
a turn (`turn_open`), announced to the manager as `cli_running`.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import closing, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vibing import db
from vibing.history import HistoryIndex, ListSessions
from vibing.plans import read_new_lines, scan_plan_refs
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


_INTERRUPTED = "[Request interrupted by user"


def _is_interruption(message: Any) -> bool:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.startswith(_INTERRUPTED)
    if isinstance(content, list):
        return any(
            isinstance(block, dict)
            and block.get("type") == "text"
            and str(block.get("text", "")).startswith(_INTERRUPTED)
            for block in content
        )
    return False


def turn_open(lines: Iterable[str]) -> bool | None:
    """Whether the CLI is in the middle of a turn, from JSONL lines of a session's main
    chain; None when they say nothing about it.

    The last decisive entry wins: an `assistant` whose `message.stop_reason` is not
    `end_turn` (`tool_use`, or none yet while it is being written) or a `user` entry
    (a prompt or a tool result) means open; an `assistant` with `end_turn`, or the
    "[Request interrupted by user]" entry, means closed. Sidechain entries, meta
    entries and every other type (attachments, system, titles) are skipped.
    """
    for line in reversed(list(lines)):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("isSidechain") is True:
            continue
        message = entry.get("message")
        if entry.get("type") == "assistant" and isinstance(message, dict):
            return message.get("stop_reason") != "end_turn"
        if entry.get("type") == "user" and entry.get("isMeta") is not True:
            return not _is_interruption(message)
    return None


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
    # Subagent files that changed since the last pass.
    subagents: set[Path] = field(default_factory=set)
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
        # session id -> offset in its file up to which plan references were searched
        self._plan_offsets: dict[str, int] = {}
        # session id -> {subagent file: offset up to which it was read}
        self._subagent_offsets: dict[str, dict[Path, int]] = {}
        # session id -> whether its last main-chain lines left the turn open
        self._turn_open: dict[str, bool] = {}
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
        if path.suffix != ".jsonl":
            return
        subagent: Path | None = None
        if path.parent.parent == self._root:
            session_id, main = path.stem, path
        elif (
            path.parent.name == "subagents"
            and path.name.startswith("agent-")
            and path.parent.parent.parent.parent == self._root
        ):
            # A subagent is not a session: its change is activity of the parent.
            session_id = path.parent.parent.name
            main = path.parent.parent.parent / f"{session_id}.jsonl"
            subagent = path
        else:
            return  # memory and anything not a session file
        burst = self._bursts.get(session_id)
        if burst is None:
            burst = _Burst(folder=main.parent.name)
            self._bursts[session_id] = burst
            burst.task = asyncio.create_task(self._drive(session_id, main, burst))
        else:
            burst.dirty = True
        if subagent is not None:
            burst.subagents.add(subagent)

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
            burst.subagents.clear()
            self._forget_turn(session_id)
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
            burst.subagents.clear()
            self._plan_offsets.pop(session_id, None)
            self._subagent_offsets.pop(session_id, None)
            self._forget_turn(session_id)
            await self._history.sync_project(project_id)
            return True
        info = await self._listed_info(session_id, cwd)
        if self._sessions.app_writing(session_id):
            burst.reload_owed = False
            burst.subagents.clear()
            self._forget_turn(session_id)
            return True
        await asyncio.to_thread(self._history.update_session, session_id, int(mtime), info)
        subagents, burst.subagents = burst.subagents, set()
        await self._read_new_lines(session_id, path, subagents)
        now = self._clock()
        reload = now - self._last_reload.get(session_id, -1e9) >= self._reload_interval
        burst.reload_owed = not reload
        if await self._sessions.apply_external_change(session_id, reload=reload):
            self._last_reload[session_id] = now
        return True

    def _forget_turn(self, session_id: str) -> None:
        self._turn_open.pop(session_id, None)
        self._sessions.forget_cli_turn(session_id)

    async def _read_new_lines(self, session_id: str, path: Path, subagents: set[Path]) -> None:
        """Read what was written since the last pass (main file and the changed subagent
        files) to know whether the turn is open and to link the plan it names.
        Never fails the pass."""
        try:
            main_lines, offset = await asyncio.to_thread(
                read_new_lines, path, self._plan_offsets.get(session_id)
            )
            self._plan_offsets[session_id] = offset
            sub_lines: list[str] = []
            for sub in sorted(subagents):
                offsets = self._subagent_offsets.setdefault(session_id, {})
                try:
                    lines, offsets[sub] = await asyncio.to_thread(
                        read_new_lines, sub, offsets.get(sub)
                    )
                except OSError:
                    offsets.pop(sub, None)  # gone between the event and the read
                    continue
                sub_lines.extend(lines)
        except Exception:
            logger.exception("Falha ao ler as linhas novas da sessão %s do CLI", session_id)
            return
        await self._note_turn(session_id, path, main_lines, bool(sub_lines))
        await self._link_plan(session_id, main_lines + sub_lines)

    async def _note_turn(
        self, session_id: str, path: Path, main_lines: list[str], subagent_wrote: bool
    ) -> None:
        """Tell the manager whether the CLI is in the middle of a turn. The main chain
        decides; without a decision in the new lines, a subagent that wrote opens the
        turn and anything else keeps what was known. Never fails the pass."""
        try:
            decision = turn_open(main_lines)
            if decision is None and subagent_wrote:
                decision = True
            if decision is None:
                decision = self._turn_open.get(session_id)
            if decision is None:
                return
            self._turn_open[session_id] = decision
            activity = await asyncio.to_thread(_latest_mtime, path)
            if activity is not None:
                self._sessions.note_cli_turn(session_id, open=decision, activity_at=activity)
        except Exception:
            logger.exception("Falha ao ler o turno da sessão %s do CLI", session_id)

    async def _link_plan(self, session_id: str, lines: list[str]) -> None:
        """Link the session to the last plan named in the new lines and reread its
        progress. Never fails the pass."""
        try:
            ref = scan_plan_refs(lines)
            if ref is None:
                return
            self._sessions.link_plan(session_id, ref, source="auto")
            # Also when the plan was already linked: the session may have edited it.
            # Rereading is a `stat` unless the file changed.
            await self._sessions.refresh_plan(session_id)
        except Exception:
            logger.exception("Falha ao vincular o plano da sessão %s do CLI", session_id)

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


def _latest_mtime(path: Path) -> float | None:
    """Most recent modification among a session file and its subagent files
    (`<session>/subagents/agent-*.jsonl`)."""
    latest = _file_mtime(path)
    try:
        for entry in (path.parent / path.stem / "subagents").glob("agent-*.jsonl"):
            mtime = _file_mtime(entry)
            if mtime is not None and (latest is None or mtime > latest):
                latest = mtime
    except OSError:
        pass
    return latest
