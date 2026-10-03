"""History index: keeps the `sessions` table in sync with the SDK's saved conversations.

For each project, `list_sessions(directory=...)` is called for the project folder
and for every git repository found inside it (up to 3 levels). Each session is
attached to the registered project whose folder most specifically contains its
`cwd`. The history folders of each repository's git worktrees are listed too: the CLI
moves a transcript there when the session enters a worktree. For each session the table
records where its file lives (`history_dir`), its current worktree and its newest git
branch. Besides those, it only adds what the history lacks (project, finished, last
seen); the conversations themselves stay in `~/.claude/projects`.
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claudio_maestro import db
from claudio_maestro.conversation import cap_content, omit_images
from claudio_maestro.worktree import Worktree, current_worktree, parse_worktree_list

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
# folder_signature(directory): changes when the directory's history folder changes; None: unknown.
FolderSignature = Callable[[str], Any]


@dataclass
class Transcript:
    """A session's `.jsonl` read in one pass."""

    # SessionMessage-like entries of the main chain, as `get_session_messages` returns.
    messages: list[Any]
    # Tool results of every branch, by tool_use_id (see `read_tool_results_file`).
    tool_results: dict[str, dict[str, Any]]
    # Lines that could not be parsed (a partial last line being written does not count).
    skipped_lines: int = 0
    # uuids of `isCompactSummary` entries (the summary written when compacting).
    compact_uuids: set[str] = field(default_factory=set)
    # {tool_use_id: {started_at, ended_at}} in epoch seconds, from the entry timestamps, for
    # Agent/Task calls only. A moment the transcript does not say is left out.
    tool_times: dict[str, dict[str, int]] = field(default_factory=dict)
    # {uuid: epoch seconds} of the user and assistant entries that have a timestamp.
    entry_times: dict[str, int] = field(default_factory=dict)


# read_transcript(session_id, directory) -> Transcript, or None when there is no file.
ReadTranscript = Callable[[str, str], Transcript | None]
# read_edits(session_id, directory) -> [{tool_use_id, name, file_path, added, removed}].
ReadEdits = Callable[[str, str], list[dict[str, Any]]]

EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})
_TRANSCRIPT_TYPES = frozenset({"user", "assistant", "progress", "system", "attachment"})

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

    # Worktrees are listed by the index itself (through run_git), folder by folder.
    return claude_agent_sdk.list_sessions(directory=directory, include_worktrees=False)


def worktree_probe(directory: str) -> tuple[bool, int | None]:
    """(ask git, cache key) for a directory's worktree list. Blocking: two `stat`s.

    No `.git`, or a `.git` folder without `worktrees/`: there is none, git is not
    asked. A `.git` folder with `worktrees/`: git adds and removes entries there
    when worktrees are added, removed or pruned, so its mtime is the cache key. A
    `.git` file (the directory is itself a linked worktree): asked every time.
    """
    git = Path(directory) / ".git"
    try:
        if git.is_dir():
            return True, (git / "worktrees").stat().st_mtime_ns
        return git.exists(), None
    except FileNotFoundError:
        return False, None
    except OSError:
        return True, None


async def git_worktrees(repo: Path) -> list[str] | None:
    """Linked worktrees of `repo`, its own folder left out. None on any git failure
    (an empty list means git answered and there are none)."""
    from claudio_maestro import gitinfo  # gitinfo imports this module

    try:
        code, out, _ = await gitinfo.run_git(repo, "worktree", "list", "--porcelain")
    except gitinfo.GitError:
        logger.warning("Não foi possível listar as worktrees de %s", repo)
        return None
    if code != 0:
        return None
    own = os.path.realpath(repo)
    return [path for path in parse_worktree_list(out) if os.path.realpath(path) != own]


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


def sdk_session_file(session_id: str, directory: str) -> Path | None:
    """Path of the session's `.jsonl`, resolved as the SDK reads it (None if unknown)."""
    return _session_file(session_id, directory)


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
            _collect_tool_results(entry, results)
    return results


def _tool_result_blocks(entry: Any) -> tuple[list[dict[str, Any]], Any]:
    """(tool_result blocks, toolUseResult) of a user entry."""
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return [], None
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return [], None
    blocks = [
        b for b in content
        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")
    ]
    return blocks, entry.get("toolUseResult")


def _collect_tool_results(entry: Any, results: dict[str, dict[str, Any]]) -> None:
    blocks, details = _tool_result_blocks(entry)
    for block in blocks:
        results[block["tool_use_id"]] = {
            "content": cap_content(omit_images(block.get("content"))),
            "is_error": block.get("is_error"),
            # One entry per result in practice; with several, details are ambiguous.
            "details": details if isinstance(details, dict) and len(blocks) == 1 else None,
        }


_TIMED_TOOLS = frozenset({"Agent", "Task"})


def _epoch_seconds(value: Any) -> int | None:
    """An entry's ISO `timestamp` as epoch seconds; None when missing or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp())


def _collect_tool_times(entry: dict[str, Any], times: dict[str, dict[str, int]]) -> None:
    """Note when an Agent/Task call was made (assistant entry) and when its result came back."""
    stamp = _epoch_seconds(entry.get("timestamp"))
    if stamp is None:
        return
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if (
            entry.get("type") == "assistant"
            and block.get("type") == "tool_use"
            and block.get("name") in _TIMED_TOOLS
            and isinstance(block.get("id"), str)
        ):
            times.setdefault(block["id"], {})["started_at"] = stamp
        elif entry.get("type") == "user" and block.get("type") == "tool_result":
            tool_use_id = block.get("tool_use_id")
            if tool_use_id in times:
                times[tool_use_id]["ended_at"] = stamp


def _lines(path: Path):
    """(line, complete) for each non-blank line; `complete` is False for a last
    line without newline (possibly still being written)."""
    with path.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            complete = line.endswith("\n")
            line = line.strip()
            if line:
                yield line, complete


def read_transcript_file(path: Path) -> Transcript:
    """Messages, tool results, corrupt lines and compact summaries in one pass.

    The main chain is built with the SDK's own helpers, so the messages match
    `get_session_messages`.
    """
    from claude_agent_sdk._internal.sessions import (
        _build_conversation_chain,
        _is_visible_message,
        _to_session_message,
    )

    entries: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    times: dict[str, dict[str, int]] = {}
    entry_times: dict[str, int] = {}
    skipped = 0
    for line, complete in _lines(path):
        try:
            entry = json.loads(line)
        except ValueError:
            if complete:
                skipped += 1
            continue
        if not isinstance(entry, dict):
            continue
        if '"tool_result"' in line:
            _collect_tool_results(entry, results)
        if '"tool_use"' in line or '"tool_result"' in line:
            _collect_tool_times(entry, times)
        if entry.get("type") in _TRANSCRIPT_TYPES and isinstance(entry.get("uuid"), str):
            entries.append(entry)
            stamp = _epoch_seconds(entry.get("timestamp"))
            if stamp is not None and entry["type"] in ("user", "assistant"):
                entry_times[entry["uuid"]] = stamp
    chain = [e for e in _build_conversation_chain(entries) if _is_visible_message(e)]
    return Transcript(
        messages=[_to_session_message(e) for e in chain],
        tool_results=results,
        skipped_lines=skipped,
        compact_uuids={e["uuid"] for e in chain if e.get("isCompactSummary")},
        tool_times=times,
        entry_times=entry_times,
    )


def read_transcript_at(path: Path | None) -> Transcript | None:
    if path is None:
        return None
    try:
        return read_transcript_file(path)
    except FileNotFoundError:
        return None


def sdk_read_transcript(session_id: str, directory: str) -> Transcript | None:
    """The session's transcript read in one pass; falls back to the public SDK
    functions (two reads) if its private helpers go away or fail."""
    try:
        from claude_agent_sdk._internal.sessions import (  # noqa: F401
            _build_conversation_chain,
            _is_visible_message,
            _to_session_message,
        )

        path = _session_file(session_id, directory)
    except Exception:
        logger.exception("Leitura direta do histórico indisponível; usando o SDK público")
        path = None
    if path is None:
        return _public_transcript(session_id, directory)
    return read_transcript_at(path)


def _public_transcript(session_id: str, directory: str) -> Transcript:
    return Transcript(
        messages=sdk_get_session_messages(session_id, directory),
        tool_results=sdk_read_tool_results(session_id, directory),
    )


def _patch_counts(details: Any) -> tuple[int, int] | None:
    patch = details.get("structuredPatch") if isinstance(details, dict) else None
    if not isinstance(patch, list):
        return None
    added = removed = 0
    for hunk in patch:
        lines = hunk.get("lines") if isinstance(hunk, dict) else None
        for text in lines or []:
            if isinstance(text, str) and text.startswith("+"):
                added += 1
            elif isinstance(text, str) and text.startswith("-"):
                removed += 1
    return added, removed


def read_edits_file(path: Path) -> list[dict[str, Any]]:
    """Edit tool calls of the whole transcript: name, path and +/- line counts
    (None without a patch). Only lines that can hold them are parsed."""
    edits: dict[str, dict[str, Any]] = {}
    counts: dict[str, tuple[int, int]] = {}
    for line, _complete in _lines(path):
        has_use = '"tool_use"' in line
        has_patch = '"structuredPatch"' in line
        if not has_use and not has_patch:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if has_patch:
            blocks, details = _tool_result_blocks(entry)
            found = _patch_counts(details)
            if found is not None and len(blocks) == 1:
                counts[blocks[0]["tool_use_id"]] = found
        message = entry.get("message") if entry.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if (
                not isinstance(block, dict) or block.get("type") != "tool_use"
                or block.get("name") not in EDIT_TOOLS or not block.get("id")
            ):
                continue
            data = block.get("input") if isinstance(block.get("input"), dict) else {}
            file_path = data.get("file_path") or data.get("notebook_path")
            if isinstance(file_path, str) and file_path:
                edits[block["id"]] = {"tool_use_id": block["id"], "name": block["name"],
                                      "file_path": file_path}
    return [
        {**edit, "added": counts[tid][0] if tid in counts else None,
         "removed": counts[tid][1] if tid in counts else None}
        for tid, edit in edits.items()
    ]


def sdk_read_edits(session_id: str, directory: str) -> list[dict[str, Any]]:
    path = _session_file(session_id, directory)
    if path is None:
        return []
    try:
        return read_edits_file(path)
    except FileNotFoundError:
        return []


# The tail of a session file is read in growing steps until an assistant line with usage shows up.
CONTEXT_TAIL_START = 64 * 1024
CONTEXT_TAIL_MAX = 4 * 1024 * 1024
_USAGE_TOKEN_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _context_from_line(line: str) -> dict[str, Any] | None:
    """`{used_tokens, model}` from one transcript line, or None if it has no usable usage."""
    if '"assistant"' not in line:
        return None
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    if entry.get("isSidechain"):
        return None  # a subagent's context, not the session's
    message = entry.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    model = message.get("model")
    if model == "<synthetic>":
        return None  # messages written by the CLI itself, with zeroed usage
    total = 0
    for name in _USAGE_TOKEN_FIELDS:
        value = usage.get(name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        total += value
    if total <= 0:
        return None
    return {"used_tokens": total, "model": model if isinstance(model, str) else None}


def read_context_file(path: Path) -> dict[str, Any] | None:
    """Context size at the last assistant message of a `.jsonl` transcript.

    `used_tokens` is input + cache creation + cache read tokens of that message
    (what the model received). Only the tail of the file is read. None when the
    file is missing or has no such message.
    """
    try:
        with path.open("rb") as file:
            size = file.seek(0, os.SEEK_END)
            window = CONTEXT_TAIL_START
            while True:
                start = max(0, size - window)
                file.seek(start)
                data = file.read(size - start)
                lines = data.decode("utf-8", errors="replace").split("\n")
                if start > 0:
                    lines = lines[1:]  # the first line is probably cut in the middle
                for line in reversed(lines):
                    found = _context_from_line(line.strip()) if line.strip() else None
                    if found is not None:
                        return found
                if start == 0 or window >= CONTEXT_TAIL_MAX:
                    return None
                window *= 4
    except OSError:
        return None


def sdk_read_context(session_id: str, directory: str) -> dict[str, Any] | None:
    path = _session_file(session_id, directory)
    return None if path is None else read_context_file(path)


def sdk_get_session_info(session_id: str, directory: str) -> Any | None:
    import claude_agent_sdk

    return claude_agent_sdk.get_session_info(session_id, directory=directory)


def _history_folder(directory: str) -> Path | None:
    """The CLI history folder of a directory, resolved like the SDK does."""
    try:
        from claude_agent_sdk._internal.sessions import (
            _canonicalize_path,
            _find_project_dir,
        )
    except ImportError:
        return None
    return _find_project_dir(_canonicalize_path(directory))


def sdk_folder_signature(directory: str) -> Any:
    """Changes whenever a session file of the directory is added, removed or
    written: (folder mtime, file count, newest file mtime). One `scandir` with
    `stat`s, no file read. None when the folder is unknown."""
    folder = _history_folder(directory)
    if folder is None:
        return None
    try:
        count = 0
        newest = 0
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.endswith(".jsonl"):
                    count += 1
                    newest = max(newest, entry.stat().st_mtime_ns)
        return (folder.stat().st_mtime_ns, count, newest)
    except OSError:
        return None


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
        folder_signature: FolderSignature | None = None,
        list_worktrees: Callable[[Path], Awaitable[list[str] | None]] | None = None,
        session_file: Callable[[str, str], Path | None] | None = None,
        detect_worktree: Callable[[Path], tuple[bool, Worktree | None]] | None = None,
        ignored_dirs: Iterable[Path] = (),
    ) -> None:
        self._db_path = db_path
        # Sessions whose cwd is inside one of these folders never enter the index.
        self._ignored = tuple(str(Path(d).resolve()) for d in ignored_dirs)
        # A directory whose history folder did not change is not listed again.
        self._folder_signature = folder_signature or (lambda d: sdk_folder_signature(d))
        self._listings: dict[str, tuple[Any, list[Any]]] = {}
        self._list_sessions = list_sessions
        self._on_change = on_change
        self._on_projects_changed = on_projects_changed
        self._is_in_use = is_in_use or (lambda session_id: False)
        # Only a session whose file is confirmed gone leaves the index.
        self._file_exists = file_exists or sdk_session_file_exists
        self._list_worktrees = list_worktrees or git_worktrees
        # directory -> (`.git/worktrees` mtime, its linked worktrees)
        self._worktree_lists: dict[str, tuple[int, list[str]]] = {}
        self._session_file = session_file or sdk_session_file
        self._detect_worktree = detect_worktree or current_worktree
        # session id -> (last_modified seen, detection result): a file read once per change.
        self._worktree_cache: dict[str, tuple[Any, tuple[bool, Worktree | None]]] = {}
        self._lock = asyncio.Lock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def list_sessions(self) -> ListSessions:
        return self._list_sessions

    def update_session(
        self, session_id: str, mtime: int, info: Any | None, path: Path | None = None
    ) -> bool:
        """Refresh one indexed session from its file's mtime and, when given, its
        listing entry (title, summary) and its file (current worktree). Blocking:
        run it in a thread. True if the row changed."""
        worktree = self._detect_worktree(path) if path is not None else (False, None)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            row = conn.execute(
                "SELECT project_id, cwd, history_dir, last_activity_at, file_modified_at,"
                " worktree_name, worktree_path FROM sessions WHERE session_id = ?", (session_id,),
            ).fetchone()
            if row is None:
                return False
            if info is not None:
                info = replace(info, last_modified=mtime * 1000)
                return self._upsert(
                    conn, info, row["project_id"], row["cwd"], row["history_dir"], worktree
                ) is not False
            changed = False
            decided, found = worktree
            if decided:
                name, wpath = (found.name, found.path) if found else (None, None)
                if (row["worktree_name"], row["worktree_path"]) != (name, wpath):
                    conn.execute(
                        "UPDATE sessions SET worktree_name = ?, worktree_path = ?"
                        " WHERE session_id = ?",
                        (name, wpath, session_id),
                    )
                    changed = True
            if row["file_modified_at"] == mtime and row["last_activity_at"] >= mtime:
                return changed
            conn.execute(
                "UPDATE sessions SET file_modified_at = ?,"
                " last_activity_at = MAX(last_activity_at, ?) WHERE session_id = ?",
                (mtime, mtime, session_id),
            )
            return True

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
            # session_id -> (info, directory, fallback project for a cwd outside every project)
            listed: dict[str, tuple[Any, str, int | None]] = {}
            complete: set[int] = set()  # projects listed without failures
            for project_id, path in targets:
                entries, ok = await self._list_project(path)
                if ok:
                    complete.add(project_id)
                for info, directory, from_worktree in entries:
                    listed.setdefault(
                        info.session_id, (info, directory, project_id if from_worktree else None)
                    )
            candidates = self._missing_candidates(listed, complete)
            gone = await asyncio.to_thread(self._confirm_gone, candidates) if candidates else []
            worktrees = await asyncio.to_thread(self._worktree_details, listed, only is None)
            changed, projects_changed = self._store(listed, gone, worktrees)
        if changed and self._on_change is not None:
            self._on_change(changed)
        if projects_changed and self._on_projects_changed is not None:
            self._on_projects_changed(projects_changed)
        return changed

    async def _list_project(self, path: str) -> tuple[list[tuple[Any, str, bool]], bool]:
        """Sessions listed for the project and whether every listing succeeded.

        The third item is True for sessions found in a worktree's history folder:
        when their cwd is outside every project, they belong to this one.
        """
        folder = Path(path)
        if not folder.is_dir():
            return [], False
        try:
            repos, ok = await asyncio.to_thread(scan_repositories, folder)
        except Exception:
            logger.exception("Falha ao procurar repositórios em %s", path)
            repos, ok = [], False
        directories = [str(folder), *(str(repo) for repo in repos)]
        worktrees: list[str] = []
        for directory in directories:
            try:
                found = await self._worktrees_of(directory)
            except Exception:
                logger.exception("Falha ao listar as worktrees de %s", directory)
                continue  # without worktrees; the project stays complete
            worktrees.extend(w for w in found if w not in directories and w not in worktrees)
        result: list[tuple[Any, str, bool]] = []
        for directory, from_worktree in [
            *((d, False) for d in directories), *((w, True) for w in worktrees)
        ]:
            try:
                infos = await asyncio.to_thread(self._list_cached, directory)
            except Exception:
                logger.exception("Falha ao listar o histórico de %s", directory)
                if not from_worktree:
                    ok = False
                continue
            result.extend((info, directory, from_worktree) for info in infos)
        return result, ok

    async def _worktrees_of(self, directory: str) -> list[str]:
        """Linked worktrees of a directory; git is asked only when it can have any and,
        while `.git/worktrees` is unchanged, the last answer is reused."""
        ask, key = await asyncio.to_thread(worktree_probe, directory)
        if not ask:
            self._worktree_lists.pop(directory, None)
            return []
        cached = self._worktree_lists.get(directory)
        if key is not None and cached is not None and cached[0] == key:
            return cached[1]
        listed = await self._list_worktrees(Path(directory))
        if listed is None:  # git failed: none this time, and asked again next time
            self._worktree_lists.pop(directory, None)
            return []
        found = list(listed)
        if key is None:
            self._worktree_lists.pop(directory, None)
        else:
            self._worktree_lists[directory] = (key, found)
        return found

    def _list_cached(self, directory: str) -> list[Any]:
        """`list_sessions(directory)`, reused while the folder signature is the same."""
        try:
            signature = self._folder_signature(directory)
        except Exception:
            logger.exception("Falha ao conferir a pasta do histórico de %s", directory)
            signature = None
        cached = self._listings.get(directory)
        if signature is not None and cached is not None and cached[0] == signature:
            return cached[1]
        infos = list(self._list_sessions(directory))
        if signature is None:
            self._listings.pop(directory, None)
        else:
            self._listings[directory] = (signature, infos)
        return infos

    def _missing_candidates(
        self, listed: dict[str, tuple[Any, str, int | None]], complete: set[int]
    ) -> list[tuple[str, int, str]]:
        """Indexed sessions of `complete` projects absent from the listing."""
        if not complete:
            return []
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id, project_id, COALESCE(history_dir, cwd) AS cwd FROM sessions"
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

    def _worktree_details(
        self, listed: dict[str, tuple[Any, str, int | None]], prune: bool = False
    ) -> dict[str, tuple[bool, Worktree | None]]:
        """Worktree of each listed session, reading a file only when it changed.
        Runs in a thread.

        `prune` (a sync of every project) forgets the sessions that are no longer
        listed. A single-project sync lists only part of them, so it leaves the rest.
        """
        out: dict[str, tuple[bool, Worktree | None]] = {}
        for session_id, (info, directory, _) in listed.items():
            cached = self._worktree_cache.get(session_id)
            if cached is not None and cached[0] == info.last_modified:
                out[session_id] = cached[1]
                continue
            try:
                path = self._session_file(session_id, directory)
                result = self._detect_worktree(path) if path is not None else (False, None)
            except Exception:
                logger.exception("Falha ao ler a worktree da sessão %s", session_id)
                result = (False, None)
            self._worktree_cache[session_id] = (info.last_modified, result)
            out[session_id] = result
        if prune:
            for session_id in self._worktree_cache.keys() - listed.keys():
                del self._worktree_cache[session_id]
        return out

    def _store(
        self,
        listed: dict[str, tuple[Any, str, int | None]],
        gone: list[tuple[str, int]],
        worktrees: dict[str, tuple[bool, Worktree | None]] | None = None,
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
            current = {project_id for project_id, _ in projects}
            for session_id, (info, directory, fallback) in listed.items():
                cwd = info.cwd or directory
                if any(_is_within(cwd, ignored) for ignored in self._ignored):
                    continue  # the digest agent's own throwaway sessions
                # The session's own cwd decides; a worktree outside every project
                # belongs to the project whose repository listed it.
                project_id = owner_project(cwd, projects)
                if project_id is None and fallback in current:
                    project_id = fallback
                if project_id is None:
                    continue
                history_dir = directory if directory != cwd else None
                worktree = (worktrees or {}).get(session_id, (False, None))
                previous = self._upsert(conn, info, project_id, cwd, history_dir, worktree)
                if previous is not False:
                    changed.add(session_id)
                    projects_changed.add(project_id)
                    if isinstance(previous, int) and previous != project_id:
                        projects_changed.add(previous)
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
        conn: sqlite3.Connection,
        info: Any,
        project_id: int,
        cwd: str,
        history_dir: str | None = None,
        worktree: tuple[bool, Worktree | None] = (False, None),
    ) -> bool | int | None:
        """False when nothing changed; otherwise the previous project id (None if new)."""
        modified = _seconds(info.last_modified) or int(time.time())
        created = _seconds(info.created_at) or modified
        summary = truncate_text(info.summary)
        first_prompt = truncate_text(info.first_prompt)
        title = session_title(info)
        branch = getattr(info, "git_branch", None)
        decided, found = worktree
        row = conn.execute(
            "SELECT project_id, group_id, title, title_custom, summary, first_prompt,"
            " last_activity_at, file_modified_at, history_dir, git_branch, worktree_name,"
            " worktree_path FROM sessions WHERE session_id = ?",
            (info.session_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, last_seen_at, finished, summary, first_prompt,"
                " file_modified_at, history_dir, git_branch, worktree_name, worktree_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (info.session_id, project_id, cwd, title, created, modified, modified,
                 summary, first_prompt, modified, history_dir, branch,
                 found.name if found else None, found.path if found else None),
            )
            return None
        changes: dict[str, Any] = {
            "project_id": project_id,
            "summary": summary,
            "first_prompt": first_prompt,
            "file_modified_at": modified,
            "last_activity_at": max(row["last_activity_at"], modified),
            "history_dir": history_dir,
        }
        if row["project_id"] != project_id:
            # A group belongs to one project: moving to another one leaves it.
            changes["group_id"] = None
        if branch:
            changes["git_branch"] = branch
        if decided:
            changes["worktree_name"] = found.name if found else None
            changes["worktree_path"] = found.path if found else None
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
