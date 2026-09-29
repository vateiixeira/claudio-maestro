"""History index: keeps the `sessions` table in sync with the SDK's saved conversations.

For each project, `list_sessions(directory=...)` is called for the project folder
and for every git repository found inside it (up to 3 levels). Each session is
attached to the registered project whose folder most specifically contains its
`cwd`. The table only adds what the history lacks (project, finished, last seen);
the conversations themselves stay in `~/.claude/projects`.
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from vibing import db
from vibing.conversation import cap_content, omit_images

logger = logging.getLogger(__name__)

# list_sessions(directory) -> list of SDKSessionInfo-like objects.
ListSessions = Callable[[str], list[Any]]
# get_session_messages(session_id, directory) -> list of SessionMessage-like objects.
GetSessionMessages = Callable[[str, str], list[Any]]
# read_tool_results(session_id, directory) -> {tool_use_id: {content, is_error, details}}.
ReadToolResults = Callable[[str, str], dict[str, dict[str, Any]]]
OnChange = Callable[[set[str]], None]
# Called after a sync with the ids of projects whose sessions were added, changed or removed.
OnProjectsChanged = Callable[[set[int]], None]
# True when the app is using the session (it must not leave the index).
IsInUse = Callable[[str], bool]

TITLE_MAX_LENGTH = 80
TEXT_MAX_LENGTH = 500
UNTITLED = "Sessão sem título"
# Title of a session created in the app before its first message (sessions.DEFAULT_TITLE).
DEFAULT_APP_TITLE = "Nova sessão"
REPO_MAX_DEPTH = 3
REPO_MAX_COUNT = 50
IGNORED_DIRS = frozenset({"node_modules", ".venv", "venv", "vendor", "dist", "build", "target"})
DEFAULT_SYNC_INTERVAL = 60.0


def sdk_list_sessions(directory: str) -> list[Any]:
    import claude_agent_sdk

    # Worktrees are left out: their sessions would carry a cwd outside the project.
    return claude_agent_sdk.list_sessions(directory=directory, include_worktrees=False)


def sdk_get_session_messages(session_id: str, directory: str) -> list[Any]:
    import claude_agent_sdk

    return claude_agent_sdk.get_session_messages(session_id, directory=directory)


def _session_file(session_id: str, directory: str) -> Path | None:
    try:
        from claude_agent_sdk._internal.sessions import _resolve_session_file_path
    except ImportError:
        logger.warning("SDK sem _resolve_session_file_path")
        return None
    return _resolve_session_file_path(session_id, directory)


def sdk_session_file_mtime(session_id: str, directory: str) -> float | None:
    """Modification time of the session's `.jsonl`, resolved as the SDK reads it."""
    path = _session_file(session_id, directory)
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def sdk_session_file_exists(session_id: str, directory: str) -> bool | None:
    """Whether the session's `.jsonl` exists; None when the SDK cannot tell."""
    try:
        from claude_agent_sdk._internal.sessions import _resolve_session_file_path
    except ImportError:
        return None
    try:
        path = _resolve_session_file_path(session_id, directory)
        return path is not None and path.is_file()
    except Exception:
        logger.exception("Falha ao procurar o arquivo da sessão %s", session_id)
        return None


def sdk_read_tool_results(session_id: str, directory: str) -> dict[str, dict[str, Any]]:
    """Every tool result in the session's transcript, read-only.

    `get_session_messages` follows a single `parentUuid` chain and drops the
    results of parallel tool calls, and it does not expose `toolUseResult`. The
    file path comes from the SDK's own resolution (private helper; if it goes
    away, nothing is completed).
    """
    path = _session_file(session_id, directory)
    return {} if path is None else read_tool_results_file(path)


def read_tool_results_file(path: Path) -> dict[str, dict[str, Any]]:
    """Tool results of every branch of a `.jsonl` transcript, by `tool_use_id`."""
    results: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            if '"tool_result"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "user":
                continue
            message = entry.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            details = entry.get("toolUseResult")
            blocks = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")
            ]
            for block in blocks:
                results[block["tool_use_id"]] = {
                    "content": cap_content(omit_images(block.get("content"))),
                    "is_error": block.get("is_error"),
                    # One entry per result in practice; with several, details are ambiguous.
                    "details": details if isinstance(details, dict) and len(blocks) == 1 else None,
                }
    return results


def truncate_title(text: str) -> str:
    return " ".join(text.split())[:TITLE_MAX_LENGTH].rstrip()


def truncate_text(value: str | None) -> str | None:
    return value[:TEXT_MAX_LENGTH] if value else None


def session_title(info: Any) -> str:
    """Custom title, then the first prompt, then the summary, cut at 80 characters.

    In SDK 0.2.161 `summary` may be the last prompt, so it comes last.
    """
    for value in (info.custom_title, info.first_prompt, info.summary):
        if value and value.strip():
            return truncate_title(value)
    return UNTITLED


def find_repositories(
    root: Path, max_depth: int = REPO_MAX_DEPTH, max_count: int | None = None
) -> list[Path]:
    """Subfolders of `root` (not `root` itself) that contain `.git`, up to `max_depth`
    below and at most `max_count` of them."""
    return scan_repositories(root, max_depth, max_count)[0]


def scan_repositories(
    root: Path, max_depth: int = REPO_MAX_DEPTH, max_count: int | None = None
) -> tuple[list[Path], bool]:
    """Like `find_repositories`, plus whether the scan was complete (no limit
    reached, no unreadable folder)."""
    if max_count is None:
        max_count = REPO_MAX_COUNT
    found: list[Path] = []
    complete = True

    def walk(folder: Path, depth: int) -> None:
        nonlocal complete
        if len(found) >= max_count:
            return
        try:
            children = sorted(os.scandir(folder), key=lambda entry: entry.name)
        except OSError:
            complete = False
            return
        for entry in children:
            name = entry.name
            if name.startswith(".") or name in IGNORED_DIRS:
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            child = Path(entry.path)
            if len(found) >= max_count:
                return
            if (child / ".git").exists():
                found.append(child)
            if depth < max_depth:
                walk(child, depth + 1)

    walk(root, 1)
    if len(found) >= max_count:
        complete = False
        logger.warning(
            "Limite de %d repositórios atingido em %s; os demais ficam fora do histórico",
            max_count, root,
        )
    return found, complete


def _is_within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def owner_project(cwd: str, projects: list[tuple[int, str]]) -> int | None:
    """Project whose folder most specifically contains `cwd`."""
    best: tuple[int, int] | None = None  # (path length, id)
    for project_id, path in projects:
        if _is_within(cwd, path) and (best is None or len(path) > best[0]):
            best = (len(path), project_id)
    return None if best is None else best[1]


def _seconds(ms: int | None) -> int | None:
    return None if ms is None else int(ms) // 1000


class HistoryIndex:
    def __init__(
        self,
        db_path: Path,
        list_sessions: ListSessions,
        *,
        on_change: OnChange | None = None,
        on_projects_changed: OnProjectsChanged | None = None,
        is_in_use: IsInUse | None = None,
        file_exists: Callable[[str, str], bool | None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._list_sessions = list_sessions
        self._on_change = on_change
        self._on_projects_changed = on_projects_changed
        self._is_in_use = is_in_use or (lambda session_id: False)
        # Only a session whose file is confirmed gone leaves the index.
        self._file_exists = file_exists or sdk_session_file_exists
        self._lock = asyncio.Lock()

    async def sync_all(self) -> set[str]:
        return await self._sync(None)

    async def sync_project(self, project_id: int) -> set[str]:
        return await self._sync(project_id)

    async def run_periodic(self, interval: float) -> None:
        """Sync now, then every `interval` seconds."""
        while True:
            try:
                await self.sync_all()
            except Exception:
                logger.exception("Falha na sincronização do histórico")
            await asyncio.sleep(interval)

    async def _sync(self, only: int | None) -> set[str]:
        async with self._lock:
            with closing(db.connect(self._db_path)) as conn:
                projects = [
                    (row["id"], row["path"])
                    for row in conn.execute("SELECT id, path FROM projects")
                ]
            targets = [p for p in projects if only is None or p[0] == only]
            listed: dict[str, tuple[Any, str]] = {}  # session_id -> (info, directory)
            complete: set[int] = set()  # projects listed without failures
            for project_id, path in targets:
                entries, ok = await self._list_project(path)
                if ok:
                    complete.add(project_id)
                for info, directory in entries:
                    listed.setdefault(info.session_id, (info, directory))
            candidates = self._missing_candidates(listed, complete)
            gone = await asyncio.to_thread(self._confirm_gone, candidates) if candidates else []
            changed, projects_changed = self._store(listed, gone)
        if changed and self._on_change is not None:
            self._on_change(changed)
        if projects_changed and self._on_projects_changed is not None:
            self._on_projects_changed(projects_changed)
        return changed

    async def _list_project(self, path: str) -> tuple[list[tuple[Any, str]], bool]:
        """Sessions listed for the project and whether every listing succeeded."""
        folder = Path(path)
        if not folder.is_dir():
            return [], False
        try:
            repos, ok = await asyncio.to_thread(scan_repositories, folder)
        except Exception:
            logger.exception("Falha ao procurar repositórios em %s", path)
            repos, ok = [], False
        result: list[tuple[Any, str]] = []
        for directory in [str(folder), *(str(repo) for repo in repos)]:
            try:
                infos = await asyncio.to_thread(self._list_sessions, directory)
            except Exception:
                logger.exception("Falha ao listar o histórico de %s", directory)
                ok = False
                continue
            result.extend((info, directory) for info in infos)
        return result, ok

    def _missing_candidates(
        self, listed: dict[str, tuple[Any, str]], complete: set[int]
    ) -> list[tuple[str, int, str]]:
        """Indexed sessions of `complete` projects absent from the listing."""
        if not complete:
            return []
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id, project_id, cwd FROM sessions"
                " WHERE file_modified_at IS NOT NULL"
            ).fetchall()
        return [
            (row["session_id"], row["project_id"], row["cwd"])
            for row in rows
            if row["project_id"] in complete
            and row["session_id"] not in listed
            and not self._is_in_use(row["session_id"])
        ]

    def _confirm_gone(self, candidates: list[tuple[str, int, str]]) -> list[tuple[str, int]]:
        """Candidates whose file is confirmed missing. Runs in a thread."""
        gone = []
        for session_id, project_id, cwd in candidates:
            try:
                exists = self._file_exists(session_id, cwd)
            except Exception:
                logger.exception("Falha ao conferir o arquivo da sessão %s", session_id)
                exists = None
            if exists is False:
                gone.append((session_id, project_id))
        return gone

    def _store(
        self,
        listed: dict[str, tuple[Any, str]],
        gone: list[tuple[str, int]],
    ) -> tuple[set[str], set[int]]:
        """Write the listing. Returns changed session ids and changed project ids.

        Projects are read again inside the transaction: one removed meanwhile is
        skipped instead of failing the whole round. `gone` sessions (file confirmed
        missing before the transaction) leave the index.
        """
        changed: set[str] = set()
        projects_changed: set[int] = set()
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            projects = [
                (row["id"], row["path"]) for row in conn.execute("SELECT id, path FROM projects")
            ]
            for session_id, (info, directory) in listed.items():
                cwd = info.cwd or directory
                # Only the session's own cwd counts: a folder outside every
                # registered project is never stored.
                project_id = owner_project(cwd, projects)
                if project_id is None:
                    continue
                previous = self._upsert(conn, info, project_id, cwd)
                if previous is not False:
                    changed.add(session_id)
                    projects_changed.add(project_id)
                    if isinstance(previous, int) and previous != project_id:
                        projects_changed.add(previous)
            current = {project_id for project_id, _ in projects}
            for session_id, project_id in gone:
                # It may have been opened while the files were checked.
                if project_id not in current or self._is_in_use(session_id):
                    continue
                cursor = conn.execute(
                    "DELETE FROM sessions WHERE session_id = ? AND project_id = ?",
                    (session_id, project_id),
                )
                if cursor.rowcount:
                    changed.add(session_id)
                    projects_changed.add(project_id)
        return changed, projects_changed

    @staticmethod
    def _upsert(
        conn: sqlite3.Connection, info: Any, project_id: int, cwd: str
    ) -> bool | int | None:
        """False when nothing changed; otherwise the previous project id (None if new)."""
        modified = _seconds(info.last_modified) or int(time.time())
        created = _seconds(info.created_at) or modified
        summary = truncate_text(info.summary)
        first_prompt = truncate_text(info.first_prompt)
        title = session_title(info)
        row = conn.execute(
            "SELECT project_id, title, title_custom, summary, first_prompt, last_activity_at,"
            " file_modified_at FROM sessions WHERE session_id = ?",
            (info.session_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, last_seen_at, finished, summary, first_prompt,"
                " file_modified_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (info.session_id, project_id, cwd, title, created, modified, modified,
                 summary, first_prompt, modified),
            )
            return None
        changes: dict[str, Any] = {
            "project_id": project_id,
            "summary": summary,
            "first_prompt": first_prompt,
            "file_modified_at": modified,
            "last_activity_at": max(row["last_activity_at"], modified),
        }
        # A title already set only changes for a new custom title from the CLI.
        if not row["title_custom"]:
            custom = info.custom_title and info.custom_title.strip()
            if custom:
                changes["title"] = truncate_title(custom)
            elif row["title"] in (UNTITLED, DEFAULT_APP_TITLE):
                changes["title"] = title
        changes = {key: value for key, value in changes.items() if row[key] != value}
        if not changes:
            return False
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE sessions SET {assignments} WHERE session_id = ?",
            (*changes.values(), info.session_id),
        )
        return row["project_id"]
