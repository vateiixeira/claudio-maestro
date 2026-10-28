"""Active sessions: one agent client per session, turn counting and permission prompts.

`SessionManager` (one per app) creates sessions and keeps the active ones in
memory. `ActiveSession` owns the conversation, the agent client (created on the
first message), the pending-turn counter and the pending permission prompts.
Every change is published as an envelope `{session_id, seq, type, data}`.
"""

import asyncio
import base64
import binascii
import json
import logging
import re
import sqlite3
import time
import unicodedata
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection
from contextlib import closing, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import EllipsisType
from typing import Any, Literal, Protocol

from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro import db, groups, labels
from claudio_maestro import history as history_module
from claudio_maestro.agent.agentd_client import AgentdUnavailable
from claudio_maestro.agent.base import (
    AgentClient,
    AgentError,
    AgentFactory,
    AgentOptions,
    AttachInfo,
)
from claudio_maestro.config import claude_projects_dir, read_user_claude_settings
from claudio_maestro.contextprobe import delete_fork_files, probe_context
from claudio_maestro.contextusage import context_breakdown
from claudio_maestro.conversation import (
    INTERRUPTED_REASONS,
    ConversationBuilder,
    Event,
    cap_items,
    rate_limit_text,
    result_error_text,
)
from claudio_maestro.digest import store as digest_store
from claudio_maestro.digest.closure_store import closure_briefs
from claudio_maestro.foreign import foreign_reply_uuids
from claudio_maestro.plans import (
    PLAN_TOOLS,
    PlanCache,
    is_plan_path,
    last_plan_ref,
    looks_like_plan_path,
    read_new_lines,
)
from claudio_maestro.procinfo import process_started_at
from claudio_maestro.projects import Project
from claudio_maestro.projects import project_roots as registered_project_roots
from claudio_maestro.termformat import terminal_title_text
from claudio_maestro.textindex import Match

logger = logging.getLogger(__name__)


class TextSearch(Protocol):
    """The content index the manager asks (see `textindex.TextIndex`)."""

    def matching(self, query: str) -> dict[str, int]: ...

    def match_for(self, query: str, rowid: int) -> Match | None: ...


DEFAULT_TITLE = history_module.DEFAULT_APP_TITLE
TITLE_MAX_LENGTH = 80
LAST_ACTION_MAX = 80
_FILE_TOOLS = frozenset({"Read", "Edit", "MultiEdit", "Write", "NotebookEdit"})
# Tools shown as "Name: argument", with the input key holding the argument.
_ARGUMENT_KEYS = {"Bash": "command", "Grep": "pattern", "Glob": "pattern",
                  "Agent": "description", "Task": "description"}


def last_action_text(name: str, tool_input: dict[str, Any]) -> str:
    """One short line for the dashboard: `Edit sessions.py`, `Bash: pnpm test`."""
    text = name
    if name in _FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if isinstance(path, str) and path.strip():
            text = f"{name} {Path(path).name}"
    elif name in _ARGUMENT_KEYS:
        value = tool_input.get(_ARGUMENT_KEYS[name])
        if isinstance(value, str) and value.strip():
            text = f"{name}: {value}"
    text = " ".join(text.split())
    if len(text) > LAST_ACTION_MAX:
        text = text[: LAST_ACTION_MAX - 1] + "…"
    return text
DENY_MESSAGE = "O usuário recusou."
BLOCKED_TOOL_MESSAGE = "Esta ferramenta está bloqueada para este agente e não pode ser usada."
CANCELLED_MESSAGE = "O pedido foi cancelado."

SessionState = Literal["closed", "connecting", "running", "awaiting_decision", "idle", "error"]
# What is true of the session's Remote Control now: "off" (no process has it), "connecting"
# (asked, the bridge is not up yet), "on", "failed" (see `remote_error`) or "elsewhere"
# (another process holds the conversation).
RemoteState = Literal["off", "connecting", "on", "failed", "elsewhere"]
# Wait before each automatic attempt to turn Remote Control on again after a failure
# (seconds); the last one repeats.
REMOTE_RETRY_DELAYS: tuple[float, ...] = (30, 60, 120, 300, 600)
REMOTE_NAME_MAX = 60  # characters of the name the session has in the Claude app
REMOTE_NAME_FALLBACK = "Cláudio Maestro"
REMOTE_FAILED_PREFIX = "Não foi possível ligar o Remote Control: "
REMOTE_OFF_FAILED_PREFIX = "Não foi possível desligar o Remote Control: "
REMOTE_BRIDGE_FAILED_TEXT = "O Remote Control perdeu a conexão."
# Processes started with `--replay-user-messages` (every one this version creates). A
# `claude` the agentd kept from an older version lacks it: its Remote Control would not
# echo the messages typed on the phone, so that process is replaced first.
SPAWN_VERSION = 1
# Sessions marked for Remote Control that are connected at the same time on startup.
REMOTE_STARTUP_PARALLEL = 3
REMOTE_CLI_BUSY_TEXT = "A conversa parece estar em uso em outro lugar. Tentando de novo em instantes."
REMOTE_UNEXPECTED_TEXT = "Falha inesperada ao ligar o Remote Control."
REMOTE_POLICY_TEXT = "O Remote Control está desativado pela política da organização."
Decision = Literal["allow_once", "allow_always", "deny", "answer", "approve", "reject"]
DECISIONS: tuple[str, ...] = ("allow_once", "allow_always", "deny", "answer", "approve", "reject")
PromptKind = Literal["tool", "question", "plan"]
# Decisions accepted by each kind of prompt.
KIND_DECISIONS: dict[str, tuple[str, ...]] = {
    "tool": ("allow_once", "allow_always", "deny"),
    "question": ("answer", "deny"),
    "plan": ("approve", "reject"),
}
QUESTION_TOOL = "AskUserQuestion"
PLAN_TOOL = "ExitPlanMode"
# How a multiSelect answer (a list of labels) is sent to the model.
MULTI_ANSWER_SEPARATOR = ", "
MAX_ANSWER_LENGTH = 2000

EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
PERMISSION_MODES: tuple[str, ...] = (
    "default", "acceptEdits", "plan", "bypassPermissions", "auto", "dontAsk"
)
# Model ids and aliases, e.g. "opus", "claude-opus-5-5", "opus[1m]".
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._\[\]-]{1,100}$")
# How long an agent's policy may take to decide a tool call before the user is asked.
POLICY_TIMEOUT = 10.0
AGENT_SETUP_FAILED_TEXT = "Não foi possível preparar a sessão do agente."
AGENT_MODE_TEXT = "Sessões de agente só rodam no modo padrão de permissões."
# Modes the CLI may report for a session of an agent (it enters plan mode by itself).
AGENT_CLI_MODES = ("default", "plan")
DEFAULT_MODEL_VALUE = "default"
# Entrypoint written to the transcripts of the app's sessions. The editor extension
# hides `sdk-cli`, `sdk-ts` and `sdk-py`, and the CLI turns `cli` into `sdk-cli`
# when not interactive, so the app uses its own value.
SESSION_ENTRYPOINT = "claudio-maestro"
MODE_AUTO_UNAVAILABLE = "O modo Automático não está disponível para este modelo."
MODEL_FIELDS = ("value", "displayName", "description", "supportsEffort", "supportedEffortLevels")
# The stored models list is asked again after this long (3 times a day).
MODELS_MAX_AGE = 8 * 3600
MODELS_CACHE_KEY = "models_cache"
# After the last background subagent ends, the CLI opens a turn by itself. The
# session keeps showing the subagent as running this long, waiting for that turn, so
# the state does not flash "waiting" in between. Past it, the session settles.
SUBAGENT_END_GRACE_SECONDS = 3.0
# Shown by GET /api/models while no list is stored yet.
FALLBACK_MODELS: list[dict[str, Any]] = [
    {
        "value": value,
        "displayName": name,
        "description": description,
        "supportsEffort": True,
        "supportedEffortLevels": list(EFFORTS),
    }
    for value, name, description in (
        ("default", "Padrão", "Modelo recomendado da conta"),
        ("opus", "Opus", "O mais capaz"),
        ("sonnet", "Sonnet", "Equilíbrio entre velocidade e capacidade"),
        ("haiku", "Haiku", "O mais rápido"),
    )
]

IMAGE_MEDIA_TYPES: tuple[str, ...] = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES = 10
MAX_IMAGES_TOTAL_BYTES = 30 * 1024 * 1024

DisplayState = Literal["running", "waiting", "finished"]
# States in which the session has a client of the app.
_WITH_CLIENT: tuple[str, ...] = ("idle", "running", "awaiting_decision")
DISPLAY_STATES: tuple[str, ...] = ("running", "waiting", "finished")
MARKS: tuple[str, ...] = ("on_hold", "blocked", "review", "discarded")
MARK_NOTE_MAX = 80

Publish = Callable[[dict[str, Any]], None]
HistoryExists = Callable[[str, str], bool]
# rename_session(session_id, title, directory): writes the title to the SDK history.
RenameSession = Callable[[str, str, str], None]

# get_session_messages(session_id, directory) and list_sessions(directory), from the SDK.
GetSessionMessages = history_module.GetSessionMessages
ListSessions = history_module.ListSessions
ReadToolResults = history_module.ReadToolResults
# file_mtime(session_id, directory): modification time of the session file, or None.
FileMtime = Callable[[str, str], float | None]

DEFAULT_IDLE_TIMEOUT = 30 * 60  # seconds
DEFAULT_HISTORY_LIMIT = 500  # messages loaded when opening an old session
# A history file modified this recently by someone else counts as external activity.
EXTERNAL_ACTIVITY_WINDOW = 60  # seconds
HISTORY_LOAD_FAILED = "Não foi possível carregar a conversa salva desta sessão."
HISTORY_LINES_SKIPPED = "Parte do histórico não pôde ser lida."
INTERRUPTED_TEXT = "Interrompido: o app reiniciou enquanto o turno rodava."
CHILD_EXITED_TEXT = "O agente encerrou enquanto o app reiniciava: {detail}"
EXIT_DETAIL_LIMIT = 300  # characters of the last stderr line shown
# Size of the items of a snapshot (JSON); older items beyond it are left out.
SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024
# A file written this long after the app's own last write still counts as the app's.
APP_WRITE_TOLERANCE = 2  # seconds
# How long removing a project waits for a send or connect still running.
PROJECT_CLOSE_WAIT = 30.0  # seconds
DEFAULT_FINISHED_AFTER_DAYS = 3.0
DAY_SECONDS = 86_400
# Farthest wake time accepted for a session on hold.
MARK_UNTIL_MAX = 365 * DAY_SECONDS
# Context window of a model; ids ending in "[1m]" have the large one.
DEFAULT_CONTEXT_WINDOW = 200_000
LARGE_CONTEXT_WINDOW = 1_000_000
# How long a context read holds its slot; a call that takes longer is abandoned.
CONTEXT_READ_LIMIT = 10.0  # seconds
# How long a temporary process may take to measure a closed conversation, from its start
# (connect included) to its answer.
CONTEXT_PROBE_LIMIT = 30.0  # seconds
# How many ids of temporary conversation copies are remembered (see `mark_throwaway`).
THROWAWAY_ID_LIMIT = 1024
# An error of the CLI that tells it does not know the `get_context_usage` request.
_UNSUPPORTED_CONTEXT = re.compile(
    r"unsupported control request|unknown control|unrecognized.*subtype", re.IGNORECASE
)
# After an autonomous turn ends with a message sent meanwhile, how long to wait for
# the turn that answers it before deciding the CLI answered inside the autonomous one.
AUTONOMOUS_FOLLOWUP_GRACE = 3.0  # seconds
# Entries of the cache of contexts read from history files.
CONTEXT_CACHE_SIZE = 512
# Last context breakdowns kept for sessions forgotten from memory (oldest dropped first).
KEPT_BREAKDOWN_LIMIT = 200
PERMISSION_SUMMARY_MAX = 200  # characters
PLAN_EDITS_MAX = 64  # edit calls on plans waiting for their result, per session
PR_CREATES_MAX = 16  # `gh pr create` calls waiting for their result, per session
PR_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
# A CLI turn signal older than this (since the last write of the session file or of a
# subagent file) is dropped: the CLI probably died in the middle of the turn.
CLI_TURN_STALE_SECONDS = 20 * 60
# A session kept by the agentd must attach within this long at startup (seconds).
REATTACH_TIMEOUT = 5.0
REATTACH_TOTAL_TIMEOUT = 10.0
KILL_TIMEOUT = 2.0  # one `kill` to the agentd while reattaching (seconds)
# read_context(session_id, directory): {used_tokens, model} of the last assistant message.
ReadContext = Callable[[str, str], dict[str, Any] | None]


# Errors --------------------------------------------------------------------


class SessionError(Exception):
    """Base error. The message is shown to the user."""


class ProcessAdmissionDenied(SessionError):
    """A pre-factory control refusal; it is not a failed SDK turn."""


class SessionNotFoundError(SessionError):
    pass


class ProjectUnavailableError(SessionError):
    pass


class EmptyMessageError(SessionError):
    pass


class PromptNotFoundError(SessionError):
    pass


class AlwaysNotAvailableError(SessionError):
    pass


class InvalidDecisionError(SessionError):
    pass


class SessionClosedError(SessionError):
    """The app is shutting down; the session accepts nothing else."""


class BypassNotConfirmedError(SessionError):
    pass


class InvalidAnswerError(SessionError):
    pass


class RejectMessageRequiredError(SessionError):
    pass


class InvalidImageError(SessionError):
    pass


class InvalidMarkError(SessionError):
    pass


REMOTE_UNAVAILABLE_TEXT = "Reabra a sessão para ligar o Remote Control."


class RemoteControlUnavailable(SessionError):
    pass


CONTINUED_ELSEWHERE_TEXT = (
    "Esta conversa continuou em outro processo enquanto uma tarefa em segundo plano "
    "rodava aqui. Pare as tarefas em segundo plano para o app retomar a conversa do disco."
)


class ContinuedElsewhereError(SessionError):
    pass


# Records -------------------------------------------------------------------


@dataclass
class SessionRecord:
    session_id: str
    project_id: int
    cwd: str
    title: str
    created_at: int
    last_activity_at: int
    last_seen_at: int | None = None
    finished: bool = False
    summary: str | None = None
    first_prompt: str | None = None
    # Title set by the user in the app: the history sync never replaces it.
    title_custom: bool = False
    # Title set before the conversation existed on disk: written to the SDK later.
    rename_pending: bool = False
    # Last modification of the history file (SDK `last_modified`), in seconds.
    file_modified_at: int | None = None
    # Modification time of the history file as the app itself last left it
    # (end of a turn, close, failure), in seconds. Survives restarts.
    app_modified_at: int | None = None
    # Options used when connecting; None lets the CLI decide.
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None
    # When the user finished the session (seconds); None when open or finished by inactivity.
    finished_at: int | None = None
    # Plan in docs/superpowers/plans the conversation executes (resolved path) and
    # how it was linked: "auto", "manual" or "off" (None = auto without a plan).
    plan_path: str | None = None
    plan_link: str | None = None
    # Group of related sessions (only the app knows it); None when loose.
    group_id: int | None = None
    # Folder whose CLI history holds the transcript, when it differs from `cwd` (the
    # CLI moves the file when a session enters a worktree). SDK reads use it.
    history_dir: str | None = None
    # Linked worktree the session works in now (from the transcript's last cwd).
    worktree_name: str | None = None
    worktree_path: str | None = None
    # Newest branch recorded in the transcript.
    git_branch: str | None = None
    # A turn was running when the app last left this session (see INTERRUPTED_TEXT).
    turn_open: bool = False
    # What the user plans to do with the session: "on_hold", "blocked", "review", "discarded" or None.
    mark: str | None = None
    # Short note of a blocked session.
    mark_note: str | None = None
    # When a session on hold wakes up (seconds); None without a date.
    mark_until: int | None = None
    # Pinned above the others.
    priority: bool = False
    # When the backend let go of this session's process on shutdown (the agentd kept
    # it); cleared once reattached. Where writes by other processes are judged from.
    detached_at: float | None = None
    # The user wants Remote Control on: kept across restarts, and the session gets it
    # back by itself whenever it has a process.
    remote_control: bool = False
    # Id of the Remote Control bridge, so a new process of this conversation keeps the
    # same entry in the Claude app.
    remote_control_bridge: str | None = None
    # Version of the code that spawned the process (what its arguments contain).
    spawn_version: int = 0
    # Agente that started this session; None for a regular one or when the
    # agent was removed.
    agent_id: int | None = None

    @property
    def history_directory(self) -> str:
        """Directory to hand the SDK when reading or renaming this session."""
        return self.history_dir or self.cwd

    def work_dir(self) -> str:
        """Folder the session works in: its worktree while it exists and the transcript
        lives in that worktree's history folder, else `cwd`. Resuming elsewhere than
        where the file is would split the conversation."""
        # cliwatch imports this module, so the import cannot be at the top.
        from claudio_maestro.cliwatch import history_folder_name

        if (
            self.worktree_path
            and self.history_dir
            and Path(self.worktree_path).is_dir()
            and history_folder_name(self.history_dir) == history_folder_name(self.worktree_path)
        ):
            return self.worktree_path
        return self.cwd


@dataclass
class SessionSummary:
    record: SessionRecord
    state: SessionState
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self.record), "state": self.state, "error": self.error}


_INSERT_COLUMNS = (
    "session_id, project_id, cwd, title, created_at, last_activity_at, last_seen_at, finished"
)
_COLUMNS = (
    _INSERT_COLUMNS
    + ", summary, first_prompt, title_custom, rename_pending, file_modified_at, app_modified_at"
    + ", model, effort, permission_mode, finished_at, plan_path, plan_link, group_id"
    + ", history_dir, worktree_name, worktree_path, git_branch, turn_open"
    + ", mark, mark_note, mark_until, priority, detached_at"
    + ", remote_control, remote_control_bridge, spawn_version, agent_id"
)
# Record fields kept out of what the frontend receives.
_INTERNAL_FIELDS = (
    "title_custom", "rename_pending", "file_modified_at", "app_modified_at",
    "plan_path", "plan_link", "history_dir", "turn_open", "detached_at",
    "remote_control_bridge", "spawn_version",
)
_BOOL_FIELDS = (
    "finished", "title_custom", "rename_pending", "turn_open", "priority", "remote_control"
)


def _record(row: sqlite3.Row) -> SessionRecord:
    fields = {key: row[key] for key in row.keys()}
    for key in _BOOL_FIELDS:
        fields[key] = bool(fields[key])
    return SessionRecord(**fields)


def remote_name(record: SessionRecord) -> str:
    """Name the session has in the Claude app: its title (or first prompt) on one line,
    cut at REMOTE_NAME_MAX characters."""
    for text in (record.title if record.title != DEFAULT_TITLE else "", record.first_prompt):
        name = " ".join((text or "").split())[:REMOTE_NAME_MAX].rstrip()
        if name:
            return name
    return REMOTE_NAME_FALLBACK


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def display_state(
    state: SessionState,
    *,
    finished: bool,
    last_activity_at: int,
    last_seen_at: int | None,
    now: float,
    finished_after: float,
    cli_running: bool = False,
    subagents_running: bool = False,
    marked: bool = False,
) -> DisplayState:
    """State shown to the user: running, waiting for them, or finished.

    `finished_after` is in seconds: a session without activity for longer counts
    as finished. A pending decision always waits for the user. A session without a
    client (`closed`) whose CLI is mid-turn is running, and so is an idle one whose
    client still runs a subagent (in the background, after the main turn ended).
    A marked session (`marked`) never finishes by inactivity.
    """
    if state in ("connecting", "running"):
        return "running"
    if state == "awaiting_decision":
        return "waiting"
    if cli_running and state == "closed":
        return "running"
    if subagents_running and state == "idle":
        return "running"
    if finished:
        return "finished"
    if not marked and now - last_activity_at > finished_after:
        return "finished"
    return "waiting"


def resolve_mark(
    record: SessionRecord,
    *,
    mark: str | None | EllipsisType,
    mark_note: str | None | EllipsisType,
    mark_until: int | None | EllipsisType,
    now: int,
) -> dict[str, Any]:
    """Record fields a mark request changes; `...` keeps the current value.

    Changing `mark` drops the note and the wake time not sent along. A note needs
    `blocked`, a wake time `on_hold`; a wake time sent must be in the future and at
    most MARK_UNTIL_MAX away; a note (spaces collapsed) has at most MARK_NOTE_MAX
    characters. Raises InvalidMarkError."""
    if mark is ... and mark_note is ... and mark_until is ...:
        return {}
    new_mark = record.mark if mark is ... else mark
    if new_mark is not None and new_mark not in MARKS:
        raise InvalidMarkError("Marcação inválida.")
    switched = mark is not ... and mark != record.mark
    if mark_note is ...:
        note = None if switched else record.mark_note
    else:
        note = " ".join((mark_note or "").split()) or None
        if note is not None and len(note) > MARK_NOTE_MAX:
            raise InvalidMarkError(f"A nota pode ter até {MARK_NOTE_MAX} caracteres.")
    until = (None if switched else record.mark_until) if mark_until is ... else mark_until
    if note is not None and new_mark != "blocked":
        raise InvalidMarkError("A nota só vale para sessões bloqueadas.")
    if until is not None and new_mark != "on_hold":
        raise InvalidMarkError("A data só vale para sessões em espera.")
    if mark_until is not ... and until is not None and not now < until <= now + MARK_UNTIL_MAX:
        raise InvalidMarkError("Escolha uma data no futuro, em até um ano.")
    wanted = {"mark": new_mark, "mark_note": note, "mark_until": until}
    return {key: value for key, value in wanted.items() if getattr(record, key) != value}


def context_window(*models: str | None) -> int:
    """Context window of the model: the large one when any id ends in `[1m]`."""
    if any(model and model.endswith("[1m]") for model in models):
        return LARGE_CONTEXT_WINDOW
    return DEFAULT_CONTEXT_WINDOW


def _percent(used: int, limit: int) -> float:
    return round(min(used / limit * 100, 100.0), 1)


def context_from_usage(
    used_tokens: int, *models: str | None
) -> dict[str, Any] | None:
    """`{used_tokens, max_tokens, percent}` from the tokens of the last message.

    Without `[1m]` in any model id, more than 200k tokens can only fit the large window.
    """
    if used_tokens <= 0:
        return None
    limit = context_window(*models)
    if used_tokens > limit:
        limit = LARGE_CONTEXT_WINDOW
    return {"used_tokens": used_tokens, "max_tokens": limit, "percent": _percent(used_tokens, limit)}


def context_from_sdk(usage: Any) -> dict[str, Any] | None:
    """Context of a `get_context_usage()` response; None when it is unusable."""

    def integer(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    if not isinstance(usage, dict):
        return None
    used = integer(usage.get("totalTokens"))
    limit = integer(usage.get("rawMaxTokens")) or integer(usage.get("maxTokens"))
    if used is None or used < 0 or limit is None or limit <= 0:
        return None
    # The SDK's `percentage` is over `maxTokens` (smaller than `rawMaxTokens`): it would
    # not match the maximum shown, so the percent is computed over the same base.
    return {"used_tokens": used, "max_tokens": limit, "percent": _percent(used, limit)}


def describe(
    record: SessionRecord,
    state: SessionState,
    error: str | None,
    seq: int,
    *,
    finished_after: float,
    now: float | None = None,
    effort_pending: bool = False,
    model_resolved: str | None = None,
    context: dict[str, Any] | None = None,
    pending_permission: dict[str, Any] | None = None,
    last_action: str | None = None,
    pending_kind: str | None = None,
    plan: dict[str, Any] | None = None,
    cli_running: bool = False,
    digest_short: str | None = None,
    plan_done: bool = False,
    closure_verdict: str | None = None,
    subagents_running: bool = False,
    label_ids: list[int] | None = None,
    remote_state: RemoteState = "off",
    remote_url: str | None = None,
    remote_error: str | None = None,
) -> dict[str, Any]:
    """Session as sent to the frontend by listings, PATCH and `session.updated`.

    `cli_running` (the CLI is in the middle of a turn) only counts for a session
    without a client (`closed`): with one, the app itself knows what is going on.
    `subagents_running` (a subagent of the app's client has not finished) only
    counts with a client."""
    now = time.time() if now is None else now
    subagents_running = subagents_running and state in _WITH_CLIENT
    fields = asdict(record)
    for key in _INTERNAL_FIELDS:
        del fields[key]
    return {
        **fields,
        "state": state,
        "error": error,
        "seq": seq,
        "display_state": display_state(
            state,
            finished=record.finished,
            last_activity_at=record.last_activity_at,
            last_seen_at=record.last_seen_at,
            now=now,
            finished_after=finished_after,
            cli_running=cli_running,
            subagents_running=subagents_running,
            marked=record.mark is not None,
        ),
        "unread": record.last_activity_at > (record.last_seen_at or 0),
        "awaiting_decision": state == "awaiting_decision",
        "effort_pending": effort_pending,
        "model_resolved": model_resolved,
        "context": context,
        "pending_permission": pending_permission,
        "last_action": last_action,
        "pending_kind": pending_kind,
        "plan": plan,
        "cli_running": cli_running and state == "closed",
        "subagents_running": subagents_running,
        "digest_short": digest_short,
        "plan_done": plan_done,
        "closure_verdict": closure_verdict,
        "label_ids": list(label_ids or []),
        "interrupted": bool(record.turn_open) and state in ("closed", "error"),
        # `remote_control` (in the record) is what the user asked for; the state is
        # what is true now.
        "remote_control_state": remote_state,
        "remote_control_url": remote_url,
        "remote_control_error": remote_error,
    }


@dataclass
class PendingPrompt:
    prompt_id: str
    future: asyncio.Future[PermissionResultAllow | PermissionResultDeny]
    tool_name: str
    input: dict[str, Any]
    display_name: str | None
    description: str | None
    title: str | None
    tool_use_id: str | None
    suggestions: list[PermissionUpdate]

    @property
    def kind(self) -> PromptKind:
        if self.tool_name == QUESTION_TOOL:
            return "question"
        if self.tool_name == PLAN_TOOL:
            return "plan"
        return "tool"

    def subject(self) -> str:
        """One readable line: the command, file, path or URL the tool works on."""
        for key in ("command", "file_path", "path", "url"):
            value = self.input.get(key)
            if isinstance(value, str) and value.strip():
                text = value
                break
        else:
            try:
                text = json.dumps(self.input, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(self.input)
        text = " ".join(text.split())
        if len(text) > PERMISSION_SUMMARY_MAX:
            text = text[: PERMISSION_SUMMARY_MAX - 1] + "…"
        return text

    def pending_dict(self) -> dict[str, Any]:
        """What the session summary shows for a pending tool permission."""
        return {
            "prompt_id": self.prompt_id,
            "tool_name": self.tool_name,
            "summary": self.subject(),
            "can_allow_always": bool(self.suggestions),
        }

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if self.kind == "question":
            questions = self.input.get("questions")
            extra["questions"] = questions if isinstance(questions, list) else []
        elif self.kind == "plan":
            plan = self.input.get("plan")
            extra["plan"] = plan if isinstance(plan, str) else ""
        return {
            "kind": self.kind,
            **extra,
            "prompt_id": self.prompt_id,
            "tool_name": self.tool_name,
            "input": self.input,
            "display_name": self.display_name,
            "description": self.description,
            "title": self.title,
            "tool_use_id": self.tool_use_id,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "can_always": bool(self.suggestions),
        }


def validate_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check format, size and count of base64 images. Returns their markers
    ({type, media_type, size}); raises InvalidImageError with a pt-BR message."""
    if len(images) > MAX_IMAGES:
        raise InvalidImageError(f"Envie no máximo {MAX_IMAGES} imagens por mensagem.")
    markers = []
    for position, image in enumerate(images, start=1):
        media_type = image.get("media_type")
        if media_type not in IMAGE_MEDIA_TYPES:
            raise InvalidImageError(
                f"Imagem {position}: formato não aceito. Use PNG, JPEG, GIF ou WebP."
            )
        data = image.get("data")
        try:
            if not isinstance(data, str) or not data:
                raise ValueError
            size = len(base64.b64decode(data, validate=True))
        except (ValueError, binascii.Error):
            raise InvalidImageError(f"Imagem {position}: conteúdo inválido.") from None
        if size > MAX_IMAGE_BYTES:
            raise InvalidImageError(f"Imagem {position}: maior que 5 MB.")
        markers.append({"type": "image", "media_type": media_type, "size": size})
    if sum(marker["size"] for marker in markers) > MAX_IMAGES_TOTAL_BYTES:
        raise InvalidImageError("As imagens somam mais de 30 MB. Envie menos imagens.")
    return markers


def build_answers(tool_input: dict[str, Any], answers: Any) -> dict[str, str]:
    """Answers of an AskUserQuestion in the format the SDK expects.

    Every question must be answered with non-blank text (one of its labels or
    free text, up to 2000 characters); `multiSelect` takes a list, sent joined
    by ", ". Raises InvalidAnswerError.
    """
    questions = tool_input.get("questions")
    if not isinstance(answers, dict) or not isinstance(questions, list):
        raise InvalidAnswerError("Responda a todas as perguntas.")
    texts = [q.get("question") for q in questions if isinstance(q, dict)]
    if set(answers) != set(texts):
        raise InvalidAnswerError("As respostas não correspondem às perguntas.")

    def clean(value: Any, question: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidAnswerError(f"Resposta vazia para: {question}")
        value = value.strip()
        if len(value) > MAX_ANSWER_LENGTH:
            raise InvalidAnswerError(f"Resposta longa demais para: {question}")
        return value

    result: dict[str, str] = {}
    for question in questions:
        text = question["question"]
        answer = answers[text]
        if question.get("multiSelect"):
            if not isinstance(answer, list) or not answer:
                raise InvalidAnswerError(f"Escolha ao menos uma opção em: {text}")
            result[text] = MULTI_ANSWER_SEPARATOR.join(clean(a, text) for a in answer)
        else:
            if isinstance(answer, list):
                raise InvalidAnswerError(f"Escolha só uma opção em: {text}")
            result[text] = clean(answer, text)
    return result


def normalize_models(info: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """The models of `get_server_info()`, only with the fields the app uses."""
    models = info.get("models") if isinstance(info, dict) else None
    if not isinstance(models, list):
        return None
    result = [
        {key: model.get(key) for key in MODEL_FIELDS}
        for model in models
        if isinstance(model, dict) and isinstance(model.get("value"), str)
    ]
    return result or None


def new_session_defaults(conn: sqlite3.Connection) -> tuple[str | None, str | None, str | None]:
    """Saved model, effort and mode for new sessions, as `(model, effort, mode)`.

    They come from `preferences` in `app_state`. A missing, unreadable or invalid
    value is None, which leaves the decision to the CLI.
    """
    row = conn.execute("SELECT value FROM app_state WHERE key = 'preferences'").fetchone()
    if row is None:
        return None, None, None
    try:
        preferences = json.loads(row["value"])
    except ValueError:
        return None, None, None
    if not isinstance(preferences, dict):
        return None, None, None
    model = preferences.get("new_session_model")
    effort = preferences.get("new_session_effort")
    mode = preferences.get("new_session_mode")
    model = model.strip() if isinstance(model, str) else None
    if not model or len(model) > 100:
        model = None
    if not isinstance(effort, str) or effort not in EFFORTS:
        effort = None
    if not isinstance(mode, str) or mode not in PERMISSION_MODES:
        mode = None
    return model, effort, mode


def user_default_permission_mode() -> str | None:
    """`permissions.defaultMode` of the user's CLI settings, used by new sessions.

    The SDK does not inherit it (verified with `auto`). Unknown values are
    ignored, and so is `bypassPermissions`: "Sem perguntas" only applies to new
    sessions when it was chosen (with a confirmation) in the app's Preferências.
    """
    permissions = read_user_claude_settings().get("permissions")
    mode = permissions.get("defaultMode") if isinstance(permissions, dict) else None
    if mode == "bypassPermissions":
        logger.warning(
            "defaultMode bypassPermissions do settings.json ignorado: sessões novas"
            " começam no modo padrão"
        )
        return None
    return mode if isinstance(mode, str) and mode in PERMISSION_MODES else None


def sdk_history_exists(session_id: str, cwd: str) -> bool:
    """Production check: the SDK has a conversation on disk for this session.

    `get_session_info` returns None for a session without an extractable
    summary (e.g. interrupted before any text), so messages are checked too.
    """
    import claude_agent_sdk

    if claude_agent_sdk.get_session_info(session_id, directory=cwd) is not None:
        return True
    return bool(claude_agent_sdk.get_session_messages(session_id, directory=cwd, limit=1))


def sdk_rename_session(session_id: str, title: str, directory: str) -> None:
    import claude_agent_sdk

    claude_agent_sdk.rename_session(session_id, title, directory=directory)


def default_agent_factory(options: AgentOptions) -> AgentClient:
    from claudio_maestro.agent.sdk_client import SdkAgentClient

    return SdkAgentClient(options)


def _stored_details(
    breakdown: dict[str, Any], measured_at: float, context: dict[str, Any] | None
) -> dict[str, Any]:
    """Answer of the context route from the last breakdown kept in memory (no process).

    Without a known context, the breakdown's own total stands in for it (same limit and
    percent as `context_from_sdk`)."""
    if context is None:
        context = {
            "used_tokens": breakdown["total_tokens"],
            "max_tokens": breakdown["max_tokens"],
            "percent": breakdown["percent"],
        }
    return {
        "available": True,
        "live": False,
        "measured_at": measured_at,
        "context": context,
        "breakdown": breakdown,
    }


def _tool_result_text(content: str | list[dict[str, Any]] | None) -> str:
    """The text of a tool result, whether it came as a string or as content blocks."""
    if isinstance(content, str):
        return content
    if not content:
        return ""
    return "\n".join(
        part["text"] for part in content
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    )


def _now() -> int:
    return int(time.time())


async def _deny_all(
    tool_name: str, tool_input: dict[str, Any], context: Any
) -> PermissionResultDeny:
    """Permission callback of the throwaway client that only lists the models."""
    return PermissionResultDeny(message="Cliente só de consulta.")


@dataclass
class _Probe:
    """A measurement of a closed conversation by a temporary process, shared by every
    request for that session. `started` turns true once it has the app-wide slot (before
    that it is only waiting in line and nothing is running)."""

    task: "asyncio.Task[tuple[dict[str, Any], float] | None] | None" = None
    waiters: int = 0
    started: bool = False


@dataclass
class _CliTurn:
    """A session file left mid-turn: `activity_at` (epoch seconds) is the latest write of
    the session file or of one of its subagent files. `announced` is whether clients
    were told it is running, so only the expiry of a signal they saw is announced."""

    activity_at: float
    announced: bool


# What the agents feature adds to a session --------------------


@dataclass
class SessionExtras:
    """What a session of an agent adds to the options of its client: the agent's prompt
    (appended to the system prompt), extra folders, environment, in-process MCP servers,
    the permission mode and the tools the definition blocks, and `decide`, the agent's
    policy that answers `allow` (no prompt), `ask` (a pending prompt in the Inbox) or `deny`
    (the tool is refused, no prompt, reported as blocked) per tool call."""

    system_prompt_append: str
    add_dirs: list[Path]
    env: dict[str, str]
    mcp_servers: dict[str, Any]
    decide: Callable[[str, dict[str, Any]], Awaitable[Literal["allow", "ask", "deny"]]]
    permission_mode: str = "default"
    disallowed_tools: list[str] = field(default_factory=list)


# Called by every new client of a session with a `agent_id`; None: no extras.
SessionSetup = Callable[[SessionRecord], SessionExtras | None]


@dataclass
class SessionContext:
    """Work context for a normal project session, without a tool policy.

    The SDK still loads the project's settings, MCPs, hooks and permission mode.
    Only the work instructions and in-process orchestration server are added.
    """

    system_prompt_append: str
    mcp_servers: dict[str, Any]


ContextSetup = Callable[[SessionRecord], SessionContext | None]
# What the manager asks of the agents feature before a message is recorded: the text that
# really goes in (the main conversation of an agent gets its announcements in front), and
# a `commit` to call once that text is recorded.
PrepareMessage = Callable[[SessionRecord, str], tuple[str, Callable[[], None]]]


def _no_commit() -> None:
    return None


# Active session ------------------------------------------------------------


class ActiveSession:
    def __init__(
        self,
        record: SessionRecord,
        *,
        db_path: Path,
        publish: Publish,
        agent_factory: AgentFactory,
        history_exists: HistoryExists,
        describe: Callable[["ActiveSession"], dict[str, Any]] | None = None,
        get_session_messages: GetSessionMessages | None = None,
        rename_session: RenameSession | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        read_tool_results: ReadToolResults | None = None,
        file_mtime: FileMtime | None = None,
        session_file: Callable[[str, str], Path | None] | None = None,
        on_turn_end: Callable[[int], None] | None = None,
        on_connected: Callable[[AgentClient], Any] | None = None,
        read_transcript: history_module.ReadTranscript | None = None,
        link_plan: Callable[[str, str], bool] | None = None,
        refresh_plan: Callable[[str], Awaitable[bool]] | None = None,
        agentd: Any | None = None,
        agentd_any: Any | None = None,
        cli_running: Callable[[str], bool] | None = None,
        agentd_held: set[str] | None = None,
        session_setup: SessionSetup | None = None,
        context_setup: ContextSetup | None = None,
        connection_admission: Callable[[SessionRecord], None] | None = None,
        on_process_close: Callable[..., None] | None = None,
        on_process_start: Callable[[str], None] | None = None,
        on_session_turn_start: Callable[..., None] | None = None,
        remote_reconnect_allowed: Callable[[SessionRecord], bool] | None = None,
        on_session_turn_end: Callable[[str], None] | None = None,
        on_session_result: Callable[[str, dict[str, Any]], None] | None = None,
        on_session_error: Callable[[str, str], None] | None = None,
        on_session_init: Callable[[str, list[dict[str, str]]], None] | None = None,
        on_session_pr_created: Callable[[str, str], None] | None = None,
        on_turn_error: Callable[[str, str], None] | None = None,
        on_init: Callable[[str, list[dict[str, str]]], None] | None = None,
        on_pr_created: Callable[[str, str], None] | None = None,
        prepare_message: PrepareMessage | None = None,
    ) -> None:
        self.record = record
        # Hooks of the agents feature, called only for the sessions of an agent: a turn
        # or the session ended in error (session id, text), and an init arrived (session
        # id, the MCP servers it reports), and a PR that its `gh pr create` opened (session
        # id, URL).
        self._on_turn_error = on_turn_error
        self._on_init = on_init
        self._on_pr_created = on_pr_created
        # Rewrites the text of a message before it is recorded (agents only).
        self._prepare_message = prepare_message
        # Extras of the agent this session belongs to, rebuilt with every client (attached
        # ones too, since the MCP server lives in this process); None for ordinary sessions.
        self._session_setup = session_setup
        self._context_setup = context_setup
        self._connection_admission = connection_admission
        self._on_process_close = on_process_close
        self._on_process_start = on_process_start
        self._on_session_turn_start = on_session_turn_start
        self._remote_reconnect_allowed = remote_reconnect_allowed
        self._on_session_turn_end = on_session_turn_end
        self._on_session_result = on_session_result
        self._on_session_error = on_session_error
        self._on_session_init = on_session_init
        self._on_session_pr_created = on_session_pr_created
        self._extras: SessionExtras | None = None
        # The manager's signals for the automatic Remote Control reconnect: a terminal
        # `claude` is running in this conversation, and the sessions whose process the
        # agentd may still hold after the last startup (shared set; connecting removes us).
        self._cli_running = cli_running
        self._agentd_held = agentd_held if agentd_held is not None else set()
        # AgentdClient for new processes (None: children of this process) and the one
        # used to attach to processes the agentd kept (whenever the manager has one).
        self._agentd = agentd
        self._agentd_any = agentd_any
        self._read_transcript = read_transcript
        # The manager links a plan the conversation touches and rereads its progress.
        self._link_plan = link_plan
        self._refresh_plan = refresh_plan
        # Plan refreshes scheduled by this session; cancelled when the client goes away.
        self._plan_tasks: set[asyncio.Task[bool]] = set()
        # Edit-like plan-tool calls waiting for their result: tool_use_id -> file_path.
        self._plan_edits: dict[str, str] = {}
        # Bash calls of `gh pr create` waiting for their result (agent sessions only).
        self._pr_creates: set[str] = set()
        # The last load failed: the next open tries again.
        self._history_failed = False
        # Why the process kept by the agentd died while the app was down (its last stderr
        # line), shown with the interrupted-turn notice.
        self._exit_note: str | None = None
        self._on_turn_end = on_turn_end
        # Awaited after each successful connect (the manager caches the models).
        self._on_connected = on_connected
        # A new effort waits for a reconnect between turns.
        self.effort_pending = False
        # The process came from an older version (see SPAWN_VERSION) and is replaced
        # between turns, the way a pending effort is, so Remote Control can start on one
        # that echoes the phone's messages. Not an effort change: nothing is announced.
        self.respawn_pending = False
        # Context usage read from the connected client at the end of each turn.
        self.context: dict[str, Any] | None = None
        # Last normalized context breakdown and when it was measured (epoch seconds), from
        # the per-turn `summary` read or the on-demand `full` one, whichever came last.
        # Memory only: it answers the context panel while there is no client.
        self.last_breakdown: dict[str, Any] | None = None
        self.last_breakdown_at: float | None = None
        # Model id the CLI resolved (from the last init); not saved.
        self.model_resolved: str | None = None
        # Last tool used by the main conversation, for the dashboard; memory only.
        self.last_action: str | None = None
        self._effort_task: asyncio.Task[None] | None = None
        self._context_task: asyncio.Task[None] | None = None
        self._context_again = False
        # Every `get_context_usage()` call still running, including abandoned ones.
        self._context_calls: set[asyncio.Future[Any]] = set()
        # The on-demand `full` read in flight (shared by simultaneous requests).
        self._details_task: asyncio.Task[dict[str, Any]] | None = None
        # A turn the CLI opened by itself (no send pending) is running.
        self._autonomous_turn = False
        # When the open turn began (epoch seconds), None while no turn is open. It is the
        # moment the session went from idle to running, by a message or by the CLI itself; a
        # message sent in the middle of the turn does not restart it, but a queued message
        # whose own turn begins after the result does (see `_read`). After the backend
        # restarts and reattaches to a turn still running, it counts from the reattachment.
        self.turn_started_at: int | None = None
        # Wall clock, in epoch seconds (a test replaces it).
        self._wall_clock: Callable[[], float] = time.time
        # Messages sent during an autonomous turn: the CLI answers them in the turn
        # that follows it (`_followup_owed`), or, if none starts within the grace
        # period (`_followup_task`), it answered them inside the autonomous one.
        self._followup_owed = 0
        self._followup_task: asyncio.Task[None] | None = None
        self.builder = ConversationBuilder()
        self.pending_turns = 0
        self._dispatch_receipt: dict[str, Any] | None = None
        self._opening_dispatch_id: str | None = None
        self.prompts: dict[str, PendingPrompt] = {}
        self.client: AgentClient | None = None
        self.process_closed = False
        self.process_close_failed = False
        self._last_admission_error: ProcessAdmissionDenied | None = None
        self._unclosed_clients: list[AgentClient] = []
        # Uuids of the main-chain messages the current client's stream delivered, and
        # when that client started (wall clock): what tells the app's own writes apart.
        self.own_uuids: set[str] = set()
        self.client_since: float | None = None
        # Uuids of replies written by another process while the app held a client that
        # was not idle (the client is released as soon as it is, or by the next send).
        # Kept apart from `own_uuids`: the app's own reply can reach the file before
        # the stream, and stops counting once the stream delivers it.
        self.foreign_candidates: set[str] = set()
        self.error: str | None = None
        self.seq = 0

        self._db_path = db_path
        self._publish = publish
        self._agent_factory = agent_factory
        self._history_exists = history_exists
        self._connecting = False
        # The automatic reconnect of a failed session keeps showing `error` meanwhile, so
        # each attempt is not a new "stopped with an error" for the clients.
        self._quiet_connect = False
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._message_lock = asyncio.Lock()
        self._sent_messages = 0
        # How many times `finished` changed in this instance (finish, reopen).
        self._finish_changes = 0
        # True once a client connected: the conversation then exists on disk.
        self._has_connected = False
        # A client connected in an earlier instance of this session (forgotten from
        # memory): the next connect resumes, but the history still loads from disk.
        self._connected_before = False
        # Bumped whenever the client is discarded (close or failure), so an
        # in-flight connect or send notices it lost its client.
        self._generation = 0
        self._final = False  # set by shutdown: nothing else is accepted
        self._published_state: tuple[str, str | None] = (self.state, None)
        self._describe = describe
        # Monotonic time the session last became idle; None while not idle.
        self.idle_since: float | None = None
        # Disposal of a discarded client still in progress.
        self._disposal: asyncio.Task[None] | None = None

        self._get_session_messages = get_session_messages
        self._read_tool_results = read_tool_results
        self._rename_session = rename_session
        self._history_limit = history_limit
        self._history_loaded = False
        self._history_lock = asyncio.Lock()
        self.history_truncated = False
        self._file_mtime = file_mtime
        # session_file(session_id, directory): path of the conversation's `.jsonl`, or None.
        self._session_file = session_file
        # Modification time of the session file at the last load (None: unknown).
        self._loaded_mtime: float | None = None
        # Operations of the manager in progress (open, send): not forgotten meanwhile.
        self.users = 0
        # Wall time of the app's own last activity in this session (seconds).
        self._app_activity_at = 0.0
        # `subagents_running` as last announced in a `session.updated`.
        self._subagents_announced = False
        # Timer of the grace period after the last subagent ended (see
        # SUBAGENT_END_GRACE_SECONDS); while it is set, the session still counts as
        # having a subagent running. Only ever set while idle.
        self._subagent_hold: asyncio.TimerHandle | None = None
        # The app asked the client to stop its tasks and has not seen them end yet:
        # their end is not one the CLI follows with a turn of its own.
        self._stop_requested = False
        # Remote Control as it is now (the record only holds what the user asked for).
        self.remote_state: RemoteState = "off"
        self.remote_url: str | None = None
        self.remote_error: str | None = None
        # Seconds to wait before each automatic attempt after a failure (a test replaces it).
        self.remote_retry_delays: tuple[float, ...] = REMOTE_RETRY_DELAYS
        self._remote_retry_task: asyncio.Task[None] | None = None
        # The task above is inside the call to the agent (not waiting for its turn).
        self._remote_calling = False
        # A `failed` of the bridge came while that call was in flight (see `_schedule_remote_retry`).
        self._remote_retry_wanted = False
        # Automatic attempts since the last time it worked or the user changed it.
        self._remote_attempts = 0

    @property
    def session_id(self) -> str:
        return self.record.session_id

    # State -----------------------------------------------------------------

    @property
    def extra_dirs(self) -> list[Path]:
        """The extra folders the live process was opened with (empty without a process)."""
        return list(self._extras.add_dirs) if self._extras is not None else []

    @property
    def state(self) -> SessionState:
        if self._connecting and not self._quiet_connect:
            return "connecting"
        if self.client is None:
            return "error" if self.error is not None else "closed"
        if self.prompts:
            return "awaiting_decision"
        if self.pending_turns > 0 or self._autonomous_turn:
            return "running"
        return "idle"

    @property
    def pending_permission(self) -> dict[str, Any] | None:
        """The oldest tool permission still pending (questions and plans do not count)."""
        for prompt in self.prompts.values():
            if prompt.kind == "tool":
                return prompt.pending_dict()
        return None

    @property
    def pending_kind(self) -> str | None:
        """Kind of the oldest pending prompt: tool, question or plan."""
        for prompt in self.prompts.values():
            return prompt.kind
        return None

    def _pending_view(self) -> tuple[dict[str, Any] | None, str | None]:
        return (self.pending_permission, self.pending_kind)

    @property
    def subagents_running(self) -> bool:
        """A subagent or a Bash command (usually in the background) is still running in
        the client, or the last one just ended and the turn the CLI opens for it has not started."""
        return self.builder.subagents_running or (
            self._subagent_hold is not None and self.client is not None
        )

    def _hold_subagent_end(self) -> None:
        """The last subagent just ended while idle: hold the "running" display for
        the autonomous turn that follows. A turn start, close or the timer ends it."""
        self._release_subagent_hold(announce=False)
        self._subagent_hold = asyncio.get_running_loop().call_later(
            SUBAGENT_END_GRACE_SECONDS, self._release_subagent_hold
        )

    def _release_subagent_hold(self, announce: bool = True) -> None:
        hold, self._subagent_hold = self._subagent_hold, None
        if hold is not None:
            hold.cancel()
        if announce:
            self.sync_subagents()

    @property
    def busy(self) -> bool:
        """A send or connect holds the lock."""
        return self._lock.locked()

    @property
    def foreign_pending(self) -> bool:
        """Another process continued the conversation (candidates the stream did not deliver)."""
        return bool(self.foreign_candidates - self.own_uuids)

    @property
    def idle_client_only(self) -> bool:
        """The app holds a client but is doing nothing with it: the condition under
        which it would also close it for idleness, and no follow-up turn is owed."""
        return (
            self.state == "idle"
            and not self.busy
            and not self.subagents_running
            and self._followup_owed == 0
        )

    async def release_for_external(self) -> bool:
        """Another process continued this conversation: drop the idle client, so the
        next message resumes from the file. Does nothing if the app started working."""
        if not self.idle_client_only:
            return False
        logger.info("Sessão %s alterada por outro processo; cliente solto", self.session_id)
        # The file's mtime now includes the other process's write: keep it out of
        # `app_modified_at`, so the "modificada fora do app" notice stays.
        await self.close(record_mtime=False)
        if self.record.remote_control:
            # The mark stays and the chip says so; the next send resumes and turns it on.
            self._set_remote("elsewhere")
        return True

    def _refresh_state(self) -> None:
        turn_open = self.pending_turns > 0 or self._autonomous_turn
        if turn_open:
            self._exit_note = None  # a new turn: the old death is history
            if self.turn_started_at is None:
                self.turn_started_at = int(self._wall_clock())
                if self._on_session_turn_start:
                    self._on_session_turn_start(self.session_id,
                        self._dispatch_receipt['id'] if self._dispatch_receipt else None)
                self._emit("turn.started", {"started_at": self.turn_started_at})
        else:
            self.turn_started_at = None
        if not self._final and turn_open != self.record.turn_open:
            try:
                self.save(turn_open=turn_open)
            except Exception:
                logger.exception("Falha ao gravar o turno da sessão %s", self.session_id)
        if self.state == "idle":
            if self.idle_since is None:
                self.idle_since = time.monotonic()
        else:
            self.idle_since = None
        current = (self.state, self.error)
        if current != self._published_state:
            self._published_state = current
            self._emit("session.state", {"state": current[0], "error": current[1]})

    # Events ----------------------------------------------------------------

    def _emit(self, type_: str, data: dict[str, Any]) -> None:
        self.seq += 1
        self._publish(
            {"session_id": self.session_id, "seq": self.seq, "type": type_, "data": data}
        )

    def _emit_events(self, events: list[Event]) -> None:
        for event in events:
            self._emit(event.type, event.data)

    def snapshot(self) -> dict[str, Any]:
        init = self.builder.init
        items, cut = cap_items(self.builder.snapshot(), SNAPSHOT_MAX_BYTES)
        return {
            **self.summary(),
            "items": items,
            "prompts": [prompt.to_dict() for prompt in self.prompts.values()],
            "init": asdict(init) if init is not None else None,
            "history_truncated": self.history_truncated or cut,
            "external_activity": self.external_activity,
            "turn_output_tokens": self.builder.turn_output_tokens,
            "turn_started_at": self.turn_started_at,
        }

    @property
    def active(self) -> bool:
        """A client is connected or connecting in this app."""
        return self.client is not None or self._connecting

    @property
    def external_activity(self) -> bool:
        """The history file changed in the last minute while the app was not using it.

        What the app itself wrote does not count: `app_modified_at` (the file's
        mtime saved at the end of each turn, close or failure) survives restarts.
        """
        modified = self.record.file_modified_at
        if self.active or modified is None:
            return False
        own = max(self._app_activity_at, self.record.app_modified_at or 0)
        return (
            time.time() - modified <= EXTERNAL_ACTIVITY_WINDOW
            and modified > own + APP_WRITE_TOLERANCE
        )

    async def _record_app_mtime(self) -> None:
        """Save the file's mtime as the app leaves it (not external activity)."""
        current = await self._current_mtime()
        if current is None:
            return
        try:
            self.save(app_modified_at=int(current))
        except Exception:
            logger.exception("Falha ao gravar a data do arquivo da sessão %s", self.session_id)

    # History ---------------------------------------------------------------

    @property
    def forgettable(self) -> bool:
        """Closed, without client, prompts, turns or operations in progress."""
        return (
            self.state == "closed"
            and self.users == 0
            and self.pending_turns == 0
            and not self.busy
            and not self._history_lock.locked()
            and (self._disposal is None or self._disposal.done())
            # Only memory says another process holds the conversation.
            and self.remote_state != "elsewhere"
        )

    async def _current_mtime(self) -> float | None:
        if self._file_mtime is None:
            return None
        try:
            return await asyncio.to_thread(self._file_mtime, self.session_id, self.record.history_directory)
        except Exception:
            logger.exception("Falha ao consultar o arquivo da sessão %s", self.session_id)
            return None

    async def reload_if_modified(self) -> None:
        """Without a client, reload the conversation if its file changed since the last load."""
        if (
            self.active or self.prompts or self.pending_turns
            or (self._get_session_messages is None and self._read_transcript is None)
            # Another operation (a send holding the lock, a second open) is running:
            # replacing the builder now could drop a message just sent.
            or self.busy or self.users > 1
        ):
            return
        current = await self._current_mtime()
        if current is None or (self._loaded_mtime is not None and current <= self._loaded_mtime):
            return
        if self._loaded_mtime is None and not self._history_loaded:
            return  # never loaded: ensure_history reads it
        async with self._history_lock:
            if self.active:
                return
            self.builder = ConversationBuilder()
            self.history_truncated = False
            self._history_loaded = False
            self._has_connected = False
            # The frontend drops what it shows and fetches the snapshot again.
            self._emit("conversation.reset", {})
        await self.ensure_history()

    async def ensure_history(
        self, *, live: bool = False, process_started_at: float | None = None
    ) -> None:
        """Load the saved conversation once, before anything else is shown or sent.

        Only the last `history_limit` messages are kept (`history_truncated`).
        No client is created. A failed load leaves a warning and is tried again
        on the next call. With `live`, a process still runs the open turn (reattach):
        the unanswered tool calls stay open and there is no "interrupted" notice.
        """
        if self._history_loaded:
            return
        async with self._history_lock:
            if self._history_loaded:
                return
            if self._history_failed and self._only_failure_notice():
                # Drop the warning of the failed attempt and try again.
                self.builder = ConversationBuilder()
            if (
                (self._get_session_messages is None and self._read_transcript is None)
                or self._has_connected
                or self.builder.items
            ):
                self._history_loaded = True
                return
            retry = self._history_failed
            self._loaded_mtime = await self._current_mtime()
            try:
                loaded = await self._load_entries()
            except Exception:
                logger.exception("Falha ao carregar o histórico da sessão %s", self.session_id)
                self.builder.add_notice("warning", HISTORY_LOAD_FAILED)
                self._history_failed = True
                return
            (entries, tool_results, skipped, compact, tool_times, entry_times,
             task_endings, task_resumes, subagent_models, background_launches) = loaded
            self._history_failed = False
            self._link_history_plan(entries)
            background_entries = None
            if len(entries) > self._history_limit:
                self.history_truncated = True
                # Scan launches beyond the display window without rendering old messages.
                background_entries = entries if live else None
                entries = entries[-self._history_limit:]
            self.builder.load_history(
                entries, tool_results, compact, live=live, tool_times=tool_times,
                entry_times=entry_times, task_endings=task_endings, task_resumes=task_resumes,
                subagent_models=subagent_models, process_started_at=process_started_at,
                background_entries=background_entries, background_launches=background_launches,
            )
            if self.record.turn_open and not self.active and not live:
                self.builder.add_notice("warning", INTERRUPTED_TEXT)
                if self._exit_note:
                    self.builder.add_notice("warning", self._exit_note)
            if skipped:
                self.builder.add_notice("warning", HISTORY_LINES_SKIPPED)
            self._history_loaded = True
            if retry:
                # Other tabs still show the warning: they fetch the snapshot again.
                self._emit("conversation.reset", {})

    def _only_failure_notice(self) -> bool:
        items = self.builder.items
        return all(getattr(item, "text", None) == HISTORY_LOAD_FAILED for item in items)

    async def _load_entries(
        self,
    ) -> tuple[
        list[Any], dict[str, dict[str, Any]], int, set[str], dict[str, dict[str, int]],
        dict[str, int], dict[str, dict[str, Any]], dict[str, int], dict[str, str], dict[str, str]
    ]:
        """(entries, tool results, skipped lines, compact summary uuids, subagent times,
        entry times, task endings, task resumes, subagent models, background launches)."""
        if self._read_transcript is not None:
            transcript = await asyncio.to_thread(
                self._read_transcript, self.session_id, self.record.history_directory
            )
            if transcript is None:
                return [], {}, 0, set(), {}, {}, {}, {}, {}, {}
            return (
                list(transcript.messages), transcript.tool_results,
                transcript.skipped_lines, set(transcript.compact_uuids),
                dict(getattr(transcript, "tool_times", None) or {}),
                dict(getattr(transcript, "entry_times", None) or {}),
                dict(getattr(transcript, "task_endings", None) or {}),
                dict(getattr(transcript, "task_resumes", None) or {}),
                dict(getattr(transcript, "subagent_models", None) or {}),
                dict(getattr(transcript, "background_launches", None) or {}),
            )
        assert self._get_session_messages is not None
        entries = list(
            await asyncio.to_thread(self._get_session_messages, self.session_id, self.record.history_directory)
            or []
        )
        tool_results: dict[str, dict[str, Any]] = {}
        if self._read_tool_results is not None and entries:
            try:
                tool_results = await asyncio.to_thread(
                    self._read_tool_results, self.session_id, self.record.history_directory
                )
            except Exception:
                logger.exception(
                    "Falha ao ler os resultados de ferramentas da sessão %s", self.session_id
                )
        return entries, tool_results, 0, set(), {}, {}, {}, {}, {}, {}

    async def _apply_pending_rename(self) -> None:
        """Write a title chosen before the conversation existed on disk."""
        if not self.record.rename_pending or self._rename_session is None:
            return
        try:
            await asyncio.to_thread(
                self._rename_session, self.session_id, self.record.title, self.record.history_directory
            )
        except Exception:
            logger.exception("Falha ao aplicar o nome pendente da sessão %s", self.session_id)
            return
        self.save(rename_pending=False)

    def summary(self) -> dict[str, Any]:
        if self._describe is not None:
            return self._describe(self)
        return describe(
            self.record, self.state, self.error, self.seq,
            finished_after=DEFAULT_FINISHED_AFTER_DAYS * DAY_SECONDS,
            effort_pending=self.effort_pending,
            model_resolved=self.model_resolved,
            context=self.context,
            pending_permission=self.pending_permission,
            last_action=self.last_action,
            pending_kind=self.pending_kind,
            subagents_running=self.subagents_running,
            remote_state=self.remote_state,
            remote_url=self.remote_url,
            remote_error=self.remote_error,
        )

    def emit_updated(self) -> None:
        data = self.summary()
        data["seq"] = self.seq + 1  # the seq of this very event
        self._subagents_announced = bool(data.get("subagents_running"))
        self._emit("session.updated", data)

    def sync_subagents(self) -> None:
        """Announce the session when `subagents_running` differs from what the
        clients last saw: a subagent started or ended without the state changing
        (an idle session shows as running while one works), or the last one
        outlived SUBAGENT_MAX_SECONDS and no longer counts. The cards of those lost
        subagents are announced as stopped first."""
        self._emit_events(self.builder.expire_lost_subagents())
        if self.subagents_running != self._subagents_announced:
            self.emit_updated()

    def save(self, **changes: Any) -> None:
        """Write record fields to the database and memory."""
        if "finished" in changes and changes["finished"] != self.record.finished:
            self._finish_changes += 1
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                (*changes.values(), self.session_id),
            )
        for key, value in changes.items():
            setattr(self.record, key, value)

    @property
    def activity_marker(self) -> tuple[int, int]:
        """Changes when the person writes (a message sent) or finishes/reopens the
        session. The agents feature compares it before finishing a concluded session."""
        return (self._sent_messages, self._finish_changes)

    async def has_history(self) -> bool:
        return self._has_connected or await self._check_history()

    # Sending ---------------------------------------------------------------

    async def send(self, text: str, images: list[dict[str, Any]] | None = None, *, dispatch_id: str | None = None) -> bool:
        # Preparing announcements and committing their receipt share the same lock:
        # concurrent messages cannot pick up the same pending announcements.
        async with self._message_lock:
            self._opening_dispatch_id = dispatch_id
            try:
                return await self._send_message(text, images, dispatch_id=dispatch_id)
            finally:
                self._opening_dispatch_id = None

    async def _send_message(self, text: str, images: list[dict[str, Any]] | None = None, *, dispatch_id: str | None = None) -> bool:
        """Record the message, connect if needed and send it.

        `images` are `{media_type, data}` in base64; they go as content blocks and
        the item keeps only markers. Agent failures do not raise: they move the
        session to `error`.
        """
        images = list(images or [])
        markers = validate_images(images)
        text = text or ""
        if not text.strip() and not images:
            raise EmptyMessageError("A mensagem está vazia.")
        if self._final:
            raise SessionClosedError("O servidor está encerrando. A mensagem não foi enviada.")
        # The saved conversation comes first, so the new message goes after it.
        await self.ensure_history()
        # The user's message is recorded first so it is never lost.
        sent_text, commit = self._prepare(text)
        self._emit_events(self.builder.add_user_message(sent_text, markers, message_id=dispatch_id))
        self._touch()
        self._reopen_if_finished()
        self.emit_updated()
        first = self._sent_messages == 0
        self._sent_messages += 1
        if first and self.record.title == DEFAULT_TITLE:
            self._set_title(terminal_title_text(text))

        async with self._lock:
            # A close still disposing of the old client must finish first, or
            # two processes would run the same session.
            await self._wait_disposal()
            if self._final:
                return False
            if self.client is None and not await self._connect():
                return False
            # A new effort still pending is applied before this turn.
            if not await self._reconnect_for_effort():
                return False
            client = self.client
            assert client is not None
            if dispatch_id is not None:
                self._dispatch_receipt = {'id': dispatch_id, 'client': client, 'generation': self._generation,
                    'echo': False, 'ambiguous': bool(self.pending_turns or self._autonomous_turn or self.record.remote_control)}
            elif self._dispatch_receipt is not None:
                self._dispatch_receipt['ambiguous'] = True
            self.pending_turns += 1
            self._refresh_state()
            content: str | list[dict[str, Any]] = sent_text
            if images:
                content = [{"type": "text", "text": sent_text}] if sent_text.strip() else []
                content += [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image["media_type"],
                            "data": image["data"],
                        },
                    }
                    for image in images
                ]
            try:
                if dispatch_id is None:
                    await client.send(content)
                else:
                    await client.send(content, message_id=dispatch_id)
                try:
                    commit()
                except Exception:
                    logger.exception("Falha ao confirmar os anúncios da sessão %s", self.session_id)
            except AgentError as error:
                # If close() discarded this client meanwhile, the error is expected.
                if self.client is client:
                    await self._fail(error.message_pt)
            # True means client.send was entered. An error there may have happened
            # after delivery; callers must not blindly retry that uncertain send.
            return True

    def _prepare(self, text: str) -> tuple[str, Callable[[], None]]:
        """The text to record and send, and what to call once its send is acknowledged. Whatever
        goes wrong here, the person's own message goes through as written."""
        if self._prepare_message is None or self.record.agent_id is None:
            return text, _no_commit
        try:
            return self._prepare_message(self.record, text)
        except Exception:
            logger.exception("Falha ao preparar a mensagem da sessão %s", self.session_id)
            return text, _no_commit

    def _reopen_if_finished(self) -> bool:
        """Writing to a session (here, or from the phone) means working on it again:
        a finished session reopens and a mark goes; the priority stays. Returns whether
        anything changed (the caller announces it)."""
        changed = False
        if self.record.finished:
            self.save(finished=False, finished_at=None)
            changed = True
        if self.record.mark is not None:
            self.save(mark=None, mark_note=None, mark_until=None)
            changed = True
        return changed

    def _set_title(self, text: str) -> None:
        title = " ".join(text.split())[:TITLE_MAX_LENGTH].rstrip()
        if not title:
            return
        self.record.title = title
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET title = ? WHERE session_id = ?", (title, self.session_id)
            )
        self._emit("session.title", {"title": title})

    async def _connect(self, *, enable_remote: bool = True, quiet: bool = False) -> bool:
        """Create and connect a client. Called with the lock held.

        A session marked for Remote Control turns it on in the new process, in the
        background (the message that caused the connect does not wait for the bridge);
        a caller that wants to wait for it passes `enable_remote=False` and does it.

        `resume` comes from memory (connected before) or from the disk check.
        A fresh connect that fails is retried once with `resume=True` when the
        error says the session is in use or the history now shows up.

        `quiet` (the automatic reconnect of a failed session): the state stays `error`
        while connecting and a new failure adds no notice to the chat.
        """
        generation = self._generation
        self._connecting = True
        self._quiet_connect = quiet
        if not quiet:
            self.error = None
        self._refresh_state()
        client: AgentClient | None = None
        self._last_admission_error = None
        try:
            missing = self._missing_folder_text()
            if missing is not None:
                raise AgentError(missing)
            resume = (
                self._has_connected or self._connected_before or await self._check_history()
            )
            options = self._client_options()
            client = self._new_client(resume)
            try:
                await client.connect()
            except AgentError as error:
                if resume or not (error.session_in_use or await self._check_history()):
                    raise
                logger.info("Sessão %s já existe; reconectando com resume", self.session_id)
                failed, client = client, None
                await self._dispose(failed, None)
                client = self._new_client(resume=True)
                await client.connect()
        except ProcessAdmissionDenied as error:
            self._connecting = False
            self._quiet_connect = False
            self._last_admission_error = error
            if not quiet:
                self._emit_events(self.builder.add_notice('warning', str(error)))
            if self.record.remote_control:
                self._set_remote('failed', error=str(error))
            self._refresh_state()
            return False
        except asyncio.CancelledError:
            self._connecting = False
            self._quiet_connect = False
            if client is not None:
                # Tracked in `_disposal`: a later send or forget waits for it
                # even if this task is cancelled again.
                with suppress(asyncio.CancelledError):
                    await self._dispose(client, None)
            self._refresh_state()
            raise
        except Exception as error:  # AgentError or anything unexpected
            self._connecting = False
            self._quiet_connect = False
            if generation != self._generation:
                # Closed while connecting: nothing to report.
                if client is not None:
                    await self._dispose(client, None)
                self._refresh_state()
                return False
            if isinstance(error, AgentError):
                message = error.message_pt
            else:
                logger.exception("Falha ao conectar a sessão %s", self.session_id)
                message = f"Falha inesperada ao iniciar o agente: {error}"
            await self._fail(message, client, notice=not quiet)
            return False
        self._connecting = False
        self._quiet_connect = False
        if quiet:
            self.error = None
        if generation != self._generation:
            # close() ran while connecting: discard the new client.
            await self._dispose(client, None)
            self._refresh_state()
            return False
        self._start_reader(client)
        if not await self._reconcile_options(client, options):
            return False
        if self._on_connected is not None:
            try:
                await self._on_connected(client)
            except Exception:
                logger.exception("Falha após conectar a sessão %s", self.session_id)
        if enable_remote and self.record.remote_control and self.client is client:
            self._start_remote(client)
        return True

    def _client_options(self) -> tuple[str | None, str | None, str | None]:
        return self.record.model, self.record.permission_mode, self.record.effort

    async def _reconcile_options(
        self, client: AgentClient, used: tuple[str | None, str | None, str | None]
    ) -> bool:
        """Model, mode or effort changed while connecting: apply them live now.
        Returns False when the client failed meanwhile."""
        model, mode, effort = (
            self.record.model, self.record.permission_mode, self.record.effort
        )
        return await self._apply_live(
            client,
            model=(model, used[0]) if model != used[0] else None,
            mode=(mode, used[1]) if mode != used[1] and mode is not None else None,
            effort=(effort, used[2]) if effort != used[2] and effort is not None else None,
        )

    async def _apply_live(
        self,
        client: AgentClient,
        *,
        model: tuple[str | None, str | None] | None,
        mode: tuple[str, str | None] | None,
        effort: tuple[str, str | None] | None = None,
    ) -> bool:
        """Send a model, mode and/or effort change to the client; each is
        `(new, previous)`.

        An error the agent answered (`AgentError.refused`, its process is alive)
        does not end the session: the option goes back to the previous value and a
        notice says why. Any other error means the client is gone and fails the
        session. Effort is the exception to the revert: a refusal (an older CLI that
        does not know the live change) leaves it saved and falls back to reconnecting
        between turns, with no notice. Returns False when the session failed or lost
        this client."""
        if model is not None:
            new, previous = model
            self.builder.expect_local_echo(f"Set model to {new}")
            try:
                await client.set_model(None if new in (None, DEFAULT_MODEL_VALUE) else new)
            except AgentError as error:
                if not await self._control_failed(client, error):
                    return False
                self.builder.cancel_local_echo(f"Set model to {new}")
                self._revert_option(
                    "model", new, previous, f"Não foi possível trocar o modelo: {error.message_pt}"
                )
        if mode is not None:
            new, previous = mode
            try:
                # Verified with the real SDK: this one sends no echo.
                await client.set_permission_mode(new)
            except AgentError as error:
                if not await self._control_failed(client, error):
                    return False
                text = (
                    MODE_AUTO_UNAVAILABLE
                    if "auto mode unavailable" in error.message_pt.lower()
                    else f"Não foi possível trocar o modo: {error.message_pt}"
                )
                self._revert_option("permission_mode", new, previous, text)
        if effort is not None:
            try:
                await client.set_effort(effort[0])
            except AgentError as error:
                if not await self._control_failed(client, error):
                    return False
                self.effort_pending = True
                self._emit_options()
                self._schedule_effort()
            else:
                if self.effort_pending and self.client is client:
                    # An earlier refused change was waiting for a swap; this one went
                    # through live and replaces it, so nothing is left to swap for.
                    self.effort_pending = False
                    self._emit_options()
        return True

    async def _control_failed(self, client: AgentClient, error: AgentError) -> bool:
        """True when the change was only refused and the session goes on."""
        if self.client is not client:
            return False
        if error.refused:
            return True
        await self._fail(error.message_pt)
        return False

    def _revert_option(self, field: str, attempted: Any, previous: Any, text: str) -> None:
        # Something else (e.g. the CLI's init) may have set it meanwhile: leave that.
        if getattr(self.record, field) == attempted:
            self.save(**{field: previous})
        self._emit_events(self.builder.add_notice("warning", text))
        self._emit_options()

    def _new_client(self, resume: bool, attach: AttachInfo | None = None) -> AgentClient:
        if attach is None and (self.process_close_failed or self._unclosed_clients):
            raise ProcessAdmissionDenied('O processo anterior não tem encerramento confirmado. Concilie antes de iniciar outro.')
        if attach is None and self._on_process_start is not None:
            try:
                self._on_process_start(self.session_id, self._opening_dispatch_id)
            except Exception as error:
                raise ProcessAdmissionDenied(str(error)) from None
        if attach is None and self._connection_admission is not None:
            try:
                self._connection_admission(self.record)
            except Exception:
                logger.exception("Admissão de nova conexão recusada: %s", self.session_id)
                raise ProcessAdmissionDenied("Não foi possível iniciar a sessão neste contexto.") from None
        model = self.record.model
        if attach is None and self.record.spawn_version != SPAWN_VERSION:
            # A process started now has what Remote Control needs from this version on.
            self.save(spawn_version=SPAWN_VERSION)
        extras = None
        agent_session = self.record.agent_id is not None
        if self._session_setup is not None and agent_session:
            try:
                extras = self._session_setup(self.record)
            except Exception as error:
                # The error may quote the agent's secrets: the log gets it, the screen not.
                logger.exception(
                    "Falha ao preparar a sessão de agente %s: %s", self.session_id, error
                )
                raise AgentError(AGENT_SETUP_FAILED_TEXT) from None
        self._extras = extras
        context = None
        if self._context_setup is not None and not agent_session:
            try:
                context = self._context_setup(self.record)
            except Exception:
                # Provider errors can include private task material: screen gets a fixed text.
                logger.exception("Falha ao preparar o contexto da sessão %s", self.session_id)
                raise AgentError("Não foi possível preparar o contexto da sessão.") from None
        return self._agent_factory(
            AgentOptions(
                cwd=Path(self.record.work_dir()),
                session_id=self.session_id,
                resume=resume,
                can_use_tool=self._can_use_tool,
                model=None if model == DEFAULT_MODEL_VALUE else model,
                effort=self.record.effort,
                # A session of an agent runs in the mode its definition says, whatever the
                # record says (without extras, in the default mode). The process is able to
                # switch to bypassPermissions only when the definition asked for that mode.
                permission_mode=(
                    (extras.permission_mode if extras is not None else "default")
                    if agent_session
                    else self.record.permission_mode
                ),
                allow_bypass=(
                    extras.permission_mode == "bypassPermissions"
                    if agent_session and extras is not None
                    else not agent_session
                ),
                entrypoint=SESSION_ENTRYPOINT,
                # New processes go through the agentd only when the manager allows it;
                # attaching always uses it (MAESTRO_AGENTD=0 still reattaches).
                agentd=self._agentd if attach is None else self._agentd_any,
                attach=attach,
                **({} if extras is None else {
                    "system_prompt_append": extras.system_prompt_append,
                    "add_dirs": extras.add_dirs,
                    "env": extras.env,
                    "mcp_servers": extras.mcp_servers,
                    "disallowed_tools": list(extras.disallowed_tools),
                }),
                **({} if context is None else {
                    "system_prompt_append": context.system_prompt_append,
                    "mcp_servers": context.mcp_servers,
                }),
            )
        )

    async def _check_history(self) -> bool:
        try:
            return await asyncio.to_thread(
                self._history_exists, self.session_id, self.record.history_directory
            )
        except Exception:
            logger.exception("Falha ao consultar o histórico da sessão %s", self.session_id)
            return False

    def _start_reader(self, client: AgentClient, since: float | None = None) -> None:
        """Adopt a connected client: a new stream, so new own uuids and start time
        (`since`, when the stream really began earlier than now)."""
        self.client = client
        self.process_closed = False
        self._has_connected = True
        self.own_uuids = set()
        self.client_since = time.time() if since is None else since
        self.foreign_candidates = set()
        if self.record.detached_at is not None:
            # Whatever shutdown left it is history now: never reused by a later reattach.
            try:
                self.save(detached_at=None)
            except Exception:
                logger.exception("Falha ao limpar o desligamento da sessão %s", self.session_id)
        self._reader = asyncio.create_task(self._read(client))

    async def _read(self, client: AgentClient) -> None:
        try:
            async for message in client.messages():
                result_dispatch_id = None
                receipt = self._dispatch_receipt
                if receipt and isinstance(message, UserMessage) and message.parent_tool_use_id is None:
                    if message.uuid == receipt['id']:
                        receipt['echo'] = True
                    elif (isinstance(message.content, str) or not message.content
                          or any(not isinstance(block, ToolResultBlock) for block in message.content)):
                        receipt['ambiguous'] = True
                if isinstance(message, ResultMessage):
                    self._dispatch_receipt = None  # The first result consumes this client generation's proof.
                    if (receipt and receipt['echo'] and not receipt['ambiguous']
                            and receipt['client'] is client and receipt['generation'] == self._generation
                            and self.pending_turns == 1 and not self._autonomous_turn
                            and not self.record.remote_control
                            and (message.origin is None or message.origin.get('kind') == 'human')):
                        result_dispatch_id = receipt['id']
                if self._starts_turn(message):
                    # The turn the hold waited for (or another one) has begun.
                    self._release_subagent_hold(announce=False)
                    self._stop_requested = False
                    if self.pending_turns == 0:
                        # The CLI opened a turn by itself (a background subagent finished).
                        self._autonomous_turn = True
                    else:
                        # The turn that answers a message sent during an autonomous one.
                        self._clear_followup()
                elif (
                    self._followup_owed
                    and isinstance(message, SystemMessage)
                    and message.subtype == "init"
                ):
                    # The follow-up turn opens with an init ~0.6 s after the autonomous
                    # one ends; the first stream event only comes after the time to
                    # the first byte, which can outlast the grace period. A debt only
                    # exists right after an autonomous result, so this init is that turn's.
                    self._clear_followup()
                had_subagents = self.builder.subagents_running
                self._emit_events(self.builder.handle(message))
                if (
                    had_subagents
                    and self._announces_task_end(message)
                    and not self.builder.subagents_running
                    and self.state == "idle"
                ):
                    # The CLI is about to open a turn for this: do not announce yet.
                    self._hold_subagent_end()
                if (
                    isinstance(message, (AssistantMessage, UserMessage))
                    and message.parent_tool_use_id is None
                    and message.uuid
                    and self.client is client
                ):
                    self.own_uuids.add(message.uuid)
                if isinstance(message, AssistantMessage):
                    if message.parent_tool_use_id is None:
                        self._note_tool_use(message)
                    self._note_plan_use(message)
                    self._note_pr_use(message)
                elif isinstance(message, UserMessage):
                    self._note_plan_result(message)
                    self._note_pr_result(message)
                    if (
                        message.parent_tool_use_id is None
                        and (message.origin or {}).get("kind") == "human"
                        and self._reopen_if_finished()
                    ):
                        # Typed in the phone: it reopens the session as a send would.
                        self.emit_updated()
                if (
                    isinstance(message, RateLimitEvent)
                    and message.rate_limit_info.status == "rejected"
                ):
                    # The builder already showed the notice with the release time.
                    if self.client is client:
                        await self._fail(
                            rate_limit_text(message.rate_limit_info.resets_at), notice=False
                        )
                    return
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    self._apply_init()
                elif isinstance(message, SystemMessage) and message.subtype == "bridge_state":
                    self._on_bridge_state(message.data)
                if isinstance(message, ResultMessage):
                    if message.is_error and message.terminal_reason not in INTERRUPTED_REASONS:
                        self._report_turn_error(result_error_text(message))
                    # Read in the background: the turn does not wait for it.
                    self._request_context(client)
                    self._schedule_plan_refresh()
                    if self._autonomous_turn:
                        # It started with no message pending, so it does not answer
                        # any: those sent since get a turn of their own (or, if none
                        # starts, the grace period settles the count).
                        self._autonomous_turn = False
                    else:
                        self.pending_turns = max(0, self.pending_turns - 1)
                    # A message still queued gets a turn of its own: its clock starts anew.
                    self.turn_started_at = None
                    # Whatever is still pending may have been folded into the turn that
                    # just ended (the CLI sends no result of its own for those), or may
                    # get a turn of its own: the grace period tells them apart.
                    self._expect_followup(client)
                    self._touch()
                    self.emit_updated()
                    # The conversation is on disk after the first turn.
                    await self._apply_pending_rename()
                    if self._on_turn_end is not None:
                        self._on_turn_end(self.record.project_id)
                    # Last: the reconnect it may start cancels this reader.
                    self._schedule_effort()
                self._refresh_state()
                self.sync_subagents()
                if isinstance(message, ResultMessage):
                    self._notify_session_hook(self._on_session_result, {
                        "is_error": message.is_error,
                        "terminal_reason": message.terminal_reason,
                        **({'dispatch_id': result_dispatch_id} if result_dispatch_id else {}),
                    })
                    self._notify_session_hook(self._on_session_turn_end)
                    # After every event of the turn: this only writes the database.
                    await self._record_app_mtime()
        except asyncio.CancelledError:
            raise
        except AgentError as error:
            if self.client is client:
                await self._fail(error.message_pt)
            return
        except Exception as error:
            logger.exception("Falha ao ler mensagens da sessão %s", self.session_id)
            if self.client is client:
                await self._fail(f"Falha inesperada ao ler a resposta do agente: {error}")
            return
        # The stream ended without close() from us: the process went away.
        if self.client is client:
            await self._fail("O agente encerrou a conexão.")

    def _expect_followup(self, client: AgentClient) -> None:
        """A turn ended while messages sent during it still wait for an answer."""
        self._clear_followup()
        if self.pending_turns == 0:
            return
        self._followup_owed = self.pending_turns
        self._followup_task = asyncio.create_task(self._followup_expired(client))

    def _clear_followup(self) -> None:
        task, self._followup_task = self._followup_task, None
        self._followup_owed = 0
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _followup_expired(self, client: AgentClient) -> None:
        await asyncio.sleep(AUTONOMOUS_FOLLOWUP_GRACE)
        if self.client is not client or self._followup_task is not asyncio.current_task():
            return
        # No turn came: the CLI answered those messages inside the autonomous turn.
        self.pending_turns = max(0, self.pending_turns - self._followup_owed)
        self._followup_task = None
        self._followup_owed = 0
        self._refresh_state()
        self.emit_updated()
        # No `_schedule_effort()` here: a reconnect could still lose an answer the CLI
        # is preparing. A pending effort is applied by the next send.

    def _request_context(self, client: AgentClient) -> None:
        """Read the context usage in the background; the turn does not wait for it.

        One read at a time, for at most `CONTEXT_READ_LIMIT`: a turn that ends while
        one is running makes it read again when it finishes. A call that does not
        answer in time is abandoned (its late result is discarded) but not cancelled,
        which would leave its control request orphaned in the SDK: it ends on its own
        or when the client goes away (`_cancel_context_read`)."""
        if self._context_task is not None and not self._context_task.done():
            self._context_again = True
            return
        self._context_task = asyncio.create_task(self._read_context_usage(client))

    async def _read_context_usage(self, client: AgentClient) -> None:
        """Read until no turn ended meanwhile; a failure keeps the last value."""
        while self.client is client:
            self._context_again = False
            call = asyncio.ensure_future(client.get_context_usage("summary"))
            self._context_calls.add(call)
            call.add_done_callback(self._context_call_done)
            await asyncio.wait([call], timeout=CONTEXT_READ_LIMIT)
            usage = None
            if not call.done():
                logger.warning(
                    "Leitura do uso de contexto da sessão %s passou do limite", self.session_id
                )
            elif call.cancelled():
                return
            elif call.exception() is not None:
                logger.warning(
                    "Falha ao ler o uso de contexto da sessão %s",
                    self.session_id,
                    exc_info=call.exception(),
                )
            else:
                usage = call.result()
            context = context_from_sdk(usage)
            if self.client is not client:
                return
            self._keep_breakdown(usage)
            if context is not None and context != self.context:
                self.context = context
                self.emit_updated()
            if not self._context_again:
                return

    def _keep_breakdown(self, usage: Any) -> dict[str, Any] | None:
        """Remember the breakdown of a read that came from the current client."""
        breakdown = context_breakdown(usage)
        if breakdown is not None:
            self.last_breakdown = breakdown
            self.last_breakdown_at = time.time()
        return breakdown

    async def read_context_details(self) -> dict[str, Any]:
        """The `full` context usage, read on demand (the route behind the context panel).

        Simultaneous requests share one read. Like the per-turn read, a call that
        does not answer within `CONTEXT_READ_LIMIT` is abandoned, not cancelled (it stays
        in `_context_calls` until it ends or the client goes away), and the request is
        answered with `timeout`. Never raises: a failure is an `available: False` answer."""
        client = self.client
        if client is None:
            if self.last_breakdown is None or self.last_breakdown_at is None:
                return {"available": False, "reason": "no_process", "context": self.context}
            return _stored_details(self.last_breakdown, self.last_breakdown_at, self.context)
        task = self._details_task
        if task is None or task.done():
            task = asyncio.create_task(self._read_context_details(client))
            self._details_task = task
        # `wait` does not cancel the read when this caller goes away.
        await asyncio.wait([task])
        if task.cancelled():
            # The session closed (or its client went away) during the read.
            return self._details_gone()
        if task.exception() is not None:
            return self._details_failure("failed")
        return task.result()

    def _details_failure(self, reason: str) -> dict[str, Any]:
        return {"available": False, "reason": reason, "context": self.context}

    def _details_gone(self) -> dict[str, Any]:
        """The client that was reading went away (closed, replaced): the last breakdown
        kept still answers, as it does for a session with no client; without one, `failed`."""
        if self.last_breakdown is None or self.last_breakdown_at is None:
            return self._details_failure("failed")
        return _stored_details(self.last_breakdown, self.last_breakdown_at, self.context)

    async def _read_context_details(self, client: AgentClient) -> dict[str, Any]:
        call = asyncio.ensure_future(client.get_context_usage("full"))
        self._context_calls.add(call)
        call.add_done_callback(self._context_call_done)
        try:
            await asyncio.wait([call], timeout=CONTEXT_READ_LIMIT)
        finally:
            if self._details_task is asyncio.current_task():
                self._details_task = None
        if not call.done():
            logger.warning(
                "Leitura completa do contexto da sessão %s passou do limite", self.session_id
            )
            return self._details_failure("timeout")
        if call.cancelled():
            return self._details_gone()
        error = call.exception()
        if error is not None:
            if _UNSUPPORTED_CONTEXT.search(str(error)):
                return self._details_failure("unsupported")
            logger.warning(
                "Falha ao ler o contexto completo da sessão %s",
                self.session_id,
                exc_info=error,
            )
            return self._details_failure("failed")
        if self.client is not client:
            # The client went away meanwhile: its answer is not for the current one.
            return self._details_gone()
        usage = call.result()
        context, breakdown = context_from_sdk(usage), self._keep_breakdown(usage)
        if context is None or breakdown is None:
            return self._details_failure("failed")
        if context != self.context:
            self.context = context
            self.emit_updated()
        return {
            "available": True,
            "live": True,
            "measured_at": self.last_breakdown_at,
            "context": context,
            "breakdown": breakdown,
        }

    def _context_call_done(self, call: asyncio.Future[Any]) -> None:
        self._context_calls.discard(call)
        if not call.cancelled():
            call.exception()  # an abandoned call that fails: nobody else reads it

    def _cancel_context_read(self) -> None:
        """The client is going away: nothing pending or abandoned is left running."""
        task, self._context_task = self._context_task, None
        self._context_again = False
        if task is not None and not task.done():
            task.cancel()
        details, self._details_task = self._details_task, None
        if details is not None and not details.done():
            details.cancel()
        for call in list(self._context_calls):
            call.cancel()
        self._context_calls.clear()

    def _announces_task_end(self, message: Any) -> bool:
        """The message tells that the last background task ended, and the CLI then
        opens a turn to tell the model: a `task_notification`, or the empty
        `background_tasks_changed` a background Bash sends before its notification
        (unless the app itself stopped the tasks)."""
        if isinstance(message, TaskNotificationMessage):
            return True
        if (
            isinstance(message, SystemMessage)
            and message.subtype == "background_tasks_changed"
            and message.data.get("tasks") == []
        ):
            stopped, self._stop_requested = self._stop_requested, False
            return not stopped
        return False

    @staticmethod
    def _starts_turn(message: Any) -> bool:
        # Not the init: it also arrives right after connecting, outside any turn.
        return (
            isinstance(message, StreamEvent)
            and message.parent_tool_use_id is None
            and message.event.get("type") == "message_start"
        )

    # Remote Control --------------------------------------------------------

    def remote_retry_delay(self, attempt: int) -> float:
        """Seconds before automatic attempt number `attempt` (from 0); the last repeats."""
        delays = self.remote_retry_delays
        return delays[min(attempt, len(delays) - 1)]

    def _set_remote(
        self, state: RemoteState, *, url: str | None = None, error: str | None = None
    ) -> None:
        """Change what is known of Remote Control and tell the clients if it differs."""
        if (self.remote_state, self.remote_url, self.remote_error) == (state, url, error):
            return
        self.remote_state, self.remote_url, self.remote_error = state, url, error
        self._emit_options()

    def _remote_down(self) -> None:
        """No client holds Remote Control now (closed, failed, replaced): the saved mark
        stays, the state goes back to off and no attempt is pending."""
        self._cancel_remote_retry()
        self._remote_attempts = 0
        self._set_remote("off")

    def _missing_folder_text(self) -> str | None:
        work_dir = self.record.work_dir()
        if Path(work_dir).is_dir():
            return None
        return f"A pasta do projeto não existe mais: {work_dir}"

    def _remote_lost(self, reason: str) -> None:
        """The session failed and lost its process (usage limit, login, the CLI died, a
        failed connect). A marked session shows `failed` with the reason and the backend
        tries to bring it back by itself, with the growing intervals of the retries;
        without the mark it is just `off`."""
        if not self.record.remote_control or self._final or self.record.finished:
            self._remote_down()
            return
        self._cancel_remote_retry()
        # A folder that is gone does not come back by waiting: say so and stop trying.
        missing = self._missing_folder_text()
        self._set_remote("failed", error=missing or reason)
        if missing is None:
            self._schedule_remote_reconnect()

    def _schedule_remote_reconnect(self) -> None:
        """No process holds a marked session: connect again (resuming the conversation)
        and turn Remote Control on after the next interval."""
        task = self._remote_retry_task
        if (
            not self.record.remote_control
            or self.record.finished
            or self.client is not None
            or self._final
            or (task is not None and not task.done() and task is not asyncio.current_task())
        ):
            return
        delay = self.remote_retry_delay(self._remote_attempts)
        self._remote_attempts += 1
        self._remote_retry_task = asyncio.create_task(self._remote_reconnect(delay))

    async def _remote_reconnect(self, delay: float) -> None:
        await asyncio.sleep(delay)
        # Checks the mark, the state of the session and whether another program took the
        # conversation meanwhile; a failure is in the state and schedules the next try.
        await self.reconnect_remote(automatic=True)

    def _cancel_remote_retry(self, *, unless_calling: bool = False) -> None:
        """Cancel the pending attempt (or the one in the middle of its call: closing,
        detaching and turning it off need that; a good report from the bridge does not,
        with `unless_calling`). The task that is running this keeps its own reference,
        so what comes after it can still cancel it."""
        task = self._remote_retry_task
        if task is None or task is asyncio.current_task():
            return
        if unless_calling and self._remote_calling:
            return
        self._remote_retry_task = None
        if not task.done():
            task.cancel()

    def _schedule_remote_retry(self) -> None:
        """After a failure, try again on its own while the mark is on and the client lives."""
        task = self._remote_retry_task
        if (
            not self.record.remote_control
            or self.client is None
            or self.remote_state != "failed"
            or self._final
        ):
            return
        if task is not None and not task.done() and task is not asyncio.current_task():
            # Another task is waiting to try, or is in the middle of its call: in the
            # second case its end looks at this flag, so the failure it did not see
            # coming is not left without a new attempt.
            self._remote_retry_wanted = True
            return
        delay = self.remote_retry_delay(self._remote_attempts)
        self._remote_attempts += 1
        self._remote_retry_task = asyncio.create_task(self._remote_retry(delay))

    async def _remote_retry(self, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            client = self.client
            if (
                client is None
                or self._final
                or not self.record.remote_control
                or self.remote_state != "failed"
            ):
                return
            await self._enable_remote(client)

    def _start_remote(self, client: AgentClient, *, attached: bool = False) -> None:
        """Turn Remote Control on in the background, once the lock is free: a process
        that was just connected or reattached. The task is the retry task, so closing,
        detaching and turning it off reach it."""
        self._cancel_remote_retry()
        self._remote_retry_task = asyncio.create_task(self._remote_start(client, attached))

    async def _remote_start(self, client: AgentClient, attached: bool) -> None:
        async with self._lock:
            if self._final or self.client is not client:
                return
            await self._enable_remote(client, attached=attached)

    def _on_bridge_state(self, data: dict[str, Any]) -> None:
        """The CLI reports the state of the Remote Control bridge."""
        if not self.record.remote_control:
            return  # a late report after the user turned it off
        state = data.get("state")
        detail = data.get("detail")
        detail = detail.strip() if isinstance(detail, str) and detail.strip() else None
        if state == "connected":
            self._remote_attempts = 0
            self._cancel_remote_retry(unless_calling=True)
            self._set_remote("on", url=self.remote_url)
        elif state == "ready":
            self._set_remote("connecting", url=self.remote_url)
        elif state == "failed":
            self._set_remote(
                "failed", url=self.remote_url, error=detail or REMOTE_BRIDGE_FAILED_TEXT
            )
            self._schedule_remote_retry()
        elif state == "policy_disabled":
            # The organization forbids it: trying again changes nothing. It waits for the
            # user (turn it off and on) and drops an attempt that was already waiting.
            self._cancel_remote_retry(unless_calling=True)
            self._remote_retry_wanted = False
            self._set_remote("failed", url=self.remote_url, error=detail or REMOTE_POLICY_TEXT)

    def _remote_failed(self, text: str) -> None:
        """Turning it on failed but the session goes on: the mark stays, the chip says why
        (one warning in the chat per run of failures) and a new attempt is scheduled."""
        first = self._remote_attempts == 0
        self._set_remote("failed", error=text)
        if first:
            self._emit_events(self.builder.add_notice("warning", REMOTE_FAILED_PREFIX + text))
        self._schedule_remote_retry()

    async def set_remote_control(self, enabled: bool) -> bool:
        """Turn Remote Control on or off for this session; the choice is saved and comes
        back after restarts. Returns True when something was done: the saved choice
        changed, or it was on already but not working (`failed`, or no process holds it)
        and an attempt was made at once.

        Turning it on connects the client first when there is none (resuming the
        conversation). A finished session cannot turn it on. Turning it off takes
        effect at once (mark, bridge and state); the request to the client follows
        under the lock, after an `enable` still in flight."""
        if enabled == self.record.remote_control and not (
            enabled
            and self.remote_state in ("failed", "off")
            and not self.record.finished
            and not self._final
        ):
            return False
        # Asking for what is already saved while it is not working: try now instead of
        # waiting for the next automatic attempt.
        if enabled:
            if self.record.finished:
                raise RemoteControlUnavailable(REMOTE_UNAVAILABLE_TEXT)
            if self._final:
                raise SessionClosedError("O servidor está encerrando.")
            self._cancel_remote_retry()
            self._remote_attempts = 0
            self.save(remote_control=True)
            self._set_remote("connecting")
            async with self._lock:
                await self._wait_disposal()
                if self._final or not self.record.remote_control:
                    return True
                if self.client is None and not await self._connect(enable_remote=False):
                    if self._last_admission_error is not None:
                        raise self._last_admission_error
                    if self.record.remote_control and self.error is not None:
                        self._set_remote("failed", error=self.error)
                    return True
                if self.client is not None and self.record.spawn_version < SPAWN_VERSION:
                    # A process kept from an older version does not echo the phone's
                    # messages: replace it (now, or once the turn running ends) and
                    # turn Remote Control on in the new one.
                    self.respawn_pending = True
                    swapped = await self._reconnect_for_effort(enable_remote=False)
                    if self.respawn_pending:
                        return True  # a turn is running: the swap (and the request) follow it
                    if not swapped:
                        if self.record.remote_control and self.error is not None:
                            self._set_remote("failed", error=self.error)
                        return True
                client = self.client
                if client is not None:
                    await self._enable_remote(client)
            return True
        self._cancel_remote_retry()
        self._remote_attempts = 0
        self.save(remote_control=False, remote_control_bridge=None)
        self._set_remote("off")
        async with self._lock:
            client = self.client
            if client is None or self.record.remote_control:
                return True
            try:
                await client.set_remote_control(False)
            except AgentError as error:
                if await self._control_failed(client, error):
                    self._emit_events(
                        self.builder.add_notice("warning", REMOTE_OFF_FAILED_PREFIX + error.message_pt)
                    )
        return True

    def _automatic_remote_allowed(self) -> bool:
        if self._remote_reconnect_allowed is None:
            return True
        try:
            return self._remote_reconnect_allowed(self.record)
        except Exception:
            logger.exception('Falha ao conferir a admissão da reconexão da sessão %s', self.session_id)
            return False

    async def reconnect_remote(self, *, automatic: bool = False) -> bool:
        """Startup: the session is marked, nothing holds its conversation and it is not
        finished. Start a process (resuming the conversation) and turn Remote Control on,
        so the session shows in the phone without the user opening the app. Returns
        whether it connected; a failure is in the session's state, never raised.

        `automatic`: the attempt after a failure, which makes no noise when it fails
        again (see `_connect`). Neither runs when the agentd may still hold the process
        or when a terminal `claude` is running in the conversation (`elsewhere`)."""
        if not self.record.remote_control or self.record.finished or self._final:
            return False
        if not self._automatic_remote_allowed():
            return False
        async with self._lock:
            await self._wait_disposal()
            if (
                self.client is not None
                or self._final
                or not self.record.remote_control
                or self.record.finished
            ):
                return False
            if self.session_id in self._agentd_held:
                logger.warning(
                    "Remote Control da sessão %s não religado: o agentd ainda segura o processo",
                    self.session_id,
                )
                return False
            if await self._written_elsewhere():
                # Another process (terminal, editor) continued the conversation after the
                # app left it: starting a second one would write to the same file.
                self._set_remote("elsewhere")
                return False
            if self._cli_running is not None and self._cli_running(self.session_id):
                # The watcher sees a turn open in the file. It may be a terminal, but also
                # the app's own process that died mid-turn: only a reply of another
                # process in the file (above) is proof. Wait and look again.
                self._set_remote("failed", error=REMOTE_CLI_BUSY_TEXT)
                self._schedule_remote_reconnect()
                return False
            # Before the connect: once it ran, the saved conversation is not read (the
            # live stream is taken as the whole of it) and the chat would open empty.
            await self.ensure_history()
            if not self._automatic_remote_allowed():
                return False
            if not await self._connect(enable_remote=False, quiet=automatic):
                if self.record.remote_control and self.error is not None:
                    self._set_remote("failed", error=self.error)
                return False
            self._agentd_held.discard(self.session_id)
            client = self.client
            if client is not None:
                await self._enable_remote(client)
            return client is not None and self.client is client

    async def _written_elsewhere(self) -> bool:
        """Another program continued the conversation after the app left it: the file
        holds an assistant reply of the main chain written after `app_modified_at` (the
        mtime saved at the app's last turn, close or failure; `release_for_external`
        leaves it untouched). The CLI also appends metadata entries after the last turn
        (`bridge-session`, `cost-state`, `last-prompt`, `ai-title`...), so the file's mtime
        says nothing; only replies count. Unknown dates or an unreadable file count as
        not written."""
        own = self.record.app_modified_at
        if own is None or self._session_file is None:
            return False
        try:
            path = await asyncio.to_thread(
                self._session_file, self.session_id, self.record.history_directory
            )
            if path is None:
                return False
            lines, _ = await asyncio.to_thread(read_new_lines, path, None)
        except Exception:
            logger.exception("Falha ao ler o arquivo da sessão %s", self.session_id)
            return False
        return bool(foreign_reply_uuids(lines, set(), own + APP_WRITE_TOLERANCE))

    async def _enable_remote(self, client: AgentClient, *, attached: bool = False) -> None:
        """Ask `client` to turn Remote Control on (the mark is on). Called with the lock
        held: by `set_remote_control`, by the automatic retries and, on new processes, by
        the connect.

        The saved bridge id goes as `reattach_session_id` so the Claude app keeps the
        same entry; if the CLI refuses it, the request is made once more without it. Any
        other refusal leaves the session as it is, with the failed state and a notice;
        an error that kills the client fails the session.

        `attached`: the process is one the agentd kept, so its bridge may be up already.
        The CLI then answers at once with the bridge's data and sends no `bridge_state`
        again: when the answer names the bridge saved before the request, it is `on`."""
        if self.client is not client or not self.record.remote_control:
            return
        self._cancel_remote_retry()
        self._remote_retry_wanted = False
        if self.remote_state != "on":
            self._set_remote("connecting", url=self.remote_url)
        name = remote_name(self.record)
        bridge = saved_bridge = self.record.remote_control_bridge
        self._remote_calling = True
        try:
            try:
                response = await client.set_remote_control(
                    True, name=name, reattach_session_id=bridge
                )
            except AgentError as error:
                if bridge is None or not error.refused or self.client is not client:
                    raise
                logger.info("Ponte %s recusada na sessão %s; ligando sem ela", bridge, self.session_id)
                # The bridge is dead: forget it now, so a failure of the call below does
                # not leave it to be offered again at every attempt.
                self.save(remote_control_bridge=None)
                bridge = None
                response = await client.set_remote_control(True, name=name)
        except AgentError as error:
            if not await self._control_failed(client, error):
                return
            if self.record.remote_control:
                self._remote_failed(error.message_pt)
            return
        except Exception:
            # Not something the agent answered: the session goes on, the chip says so.
            logger.exception("Falha ao ligar o Remote Control da sessão %s", self.session_id)
            if self.client is client and self.record.remote_control:
                self._remote_failed(REMOTE_UNEXPECTED_TEXT)
            return
        finally:
            self._remote_calling = False
        if self.client is not client or not self.record.remote_control:
            return  # closed or turned off meanwhile; the off request follows
        answer = response if isinstance(response, dict) else {}
        bridge_id = answer.get("bridge_session_id")
        if isinstance(bridge_id, str) and bridge_id and bridge_id != bridge:
            self.save(remote_control_bridge=bridge_id)
        url = answer.get("session_url")
        url = url if isinstance(url, str) and url else self.remote_url
        if self.remote_state in ("on", "failed"):
            # The bridge reported while the request was in flight: keep what it said.
            self._set_remote(self.remote_state, url=url, error=self.remote_error)
            if self.remote_state == "failed" and self._remote_retry_wanted:
                self._remote_retry_wanted = False
                self._schedule_remote_retry()
        elif attached and saved_bridge is not None and bridge_id == saved_bridge:
            self._remote_attempts = 0
            self._set_remote("on", url=url)
        else:
            self._set_remote("connecting", url=url)

    # Options ---------------------------------------------------------------

    def options(self) -> dict[str, Any]:
        return {
            "model": self.record.model,
            "effort": self.record.effort,
            "permission_mode": self.record.permission_mode,
            "effort_pending": self.effort_pending,
            "model_resolved": self.model_resolved,
            "remote_control": self.record.remote_control,
            "remote_control_state": self.remote_state,
            "remote_control_url": self.remote_url,
            "remote_control_error": self.remote_error,
        }

    def _emit_options(self) -> None:
        self._emit("session.options", self.options())

    def _apply_init(self) -> None:
        """The CLI reports model and mode on each init (the mode changes by itself
        from `plan` to `default` when a plan is approved)."""
        init = self.builder.init
        if init is None:
            return
        changes = {}
        emit = False
        if init.model and init.model != self.model_resolved:
            # The resolved id; `model` keeps the alias the user chose.
            self.model_resolved = init.model
            emit = True
        if (
            init.permission_mode
            and init.permission_mode != self.record.permission_mode
            and (
                self.record.agent_id is None
                or init.permission_mode in AGENT_CLI_MODES
                # The mode the definition asked for (e.g. bypassPermissions).
                or (self._extras is not None and init.permission_mode == self._extras.permission_mode)
            )
        ):
            changes["permission_mode"] = init.permission_mode
        if changes:
            self.save(**changes)
        if changes or emit:
            self._emit_options()
        if self._on_init is not None and self.record.agent_id is not None:
            try:
                self._on_init(self.session_id, list(init.mcp_servers))
            except Exception:
                logger.exception("Falha ao registrar os MCPs da sessão de agente %s", self.session_id)
        self._notify_session_hook(self._on_session_init, list(init.mcp_servers))

    async def set_options(
        self,
        *,
        model: str | None = None,
        effort: str | None = None,
        permission_mode: str | None = None,
    ) -> bool:
        """Save new options and apply them to the client, if any. Returns True when
        something changed. Model, mode and effort change live; only when the CLI
        refuses the effort change does it wait for a reconnect between turns."""
        if (
            permission_mode is not None
            and permission_mode != "default"
            and self.record.agent_id is not None
        ):
            raise InvalidDecisionError(AGENT_MODE_TEXT)
        changes: dict[str, Any] = {}
        if model is not None and model != self.record.model:
            changes["model"] = model
        if effort is not None and effort != self.record.effort:
            changes["effort"] = effort
        if permission_mode is not None and permission_mode != self.record.permission_mode:
            changes["permission_mode"] = permission_mode
        if not changes:
            return False
        previous = {
            "model": self.record.model,
            "effort": self.record.effort,
            "permission_mode": self.record.permission_mode,
        }
        self.save(**changes)
        client = self.client
        self._emit_options()
        if client is not None:
            applied = await self._apply_live(
                client,
                model=(changes["model"], previous["model"]) if "model" in changes else None,
                mode=(
                    (changes["permission_mode"], previous["permission_mode"])
                    if "permission_mode" in changes
                    else None
                ),
                effort=(changes["effort"], previous["effort"]) if "effort" in changes else None,
            )
            if not applied:
                return True
        self._schedule_effort()
        return True

    def _schedule_effort(self) -> None:
        """Reconnect with the new effort (or replace an old process, see `respawn_pending`)
        once the session is between turns."""
        if (
            not (self.effort_pending or self.respawn_pending)
            or self.client is None
            or self.pending_turns
            or self._autonomous_turn
            or self.prompts
            or self.subagents_running
            or (self._effort_task is not None and not self._effort_task.done())
        ):
            return
        self._effort_task = asyncio.create_task(self._effort_reconnect())

    async def _effort_reconnect(self) -> None:
        async with self._lock:
            await self._reconnect_for_effort()

    async def _reconnect_for_effort(self, *, enable_remote: bool = True) -> bool:
        """With the lock held: replace the client by one resumed with the new
        effort (or, for `respawn_pending`, by one of this version). Returns False when the
        session ended up without a client."""
        if not (self.effort_pending or self.respawn_pending):
            return True
        if self.client is None:
            self.effort_pending = False
            self.respawn_pending = False
            self._emit_options()
            return True
        if self.pending_turns or self._autonomous_turn or self.prompts or self.subagents_running:
            return True  # a turn or subagent is running: tried again when it ends
        client, reader = self.client, self._reader
        self._generation += 1
        generation = self._generation
        self.client = None
        self._reader = None
        self.builder.clear_local_echo()
        self._remote_down()
        self._release_subagent_hold(announce=False)
        self._emit_events(self.builder.stop_running_subagents())
        self.sync_subagents()
        await self._dispose(client, reader)
        if self._final or generation != self._generation:
            # close() ran meanwhile: no new client.
            self.effort_pending = False
            self.respawn_pending = False
            return False
        connected = await self._connect(enable_remote=enable_remote)
        self.effort_pending = False
        self.respawn_pending = False
        self._emit_options()
        self._refresh_state()
        return connected

    def _note_tool_use(self, message: AssistantMessage) -> None:
        """Keep the last tool of the main conversation and publish it when it changes."""
        uses = [block for block in message.content if isinstance(block, ToolUseBlock)]
        if not uses:
            return
        action = last_action_text(uses[-1].name, uses[-1].input or {})
        if action != self.last_action:
            self.last_action = action
            self.emit_updated()

    # Plan of the conversation ------------------------------------------

    def _on_linked_plan(self, file_path: str) -> bool:
        """`file_path` is the plan this session is linked to."""
        linked = self.record.plan_path
        if not linked or not Path(file_path).is_absolute():
            return False  # a relative path would resolve against the server's directory
        try:
            return str(Path(file_path).expanduser().resolve()) == linked
        except (OSError, RuntimeError, ValueError):
            return False

    def _note_plan_use(self, message: AssistantMessage) -> None:
        """Link the conversation to a plan it reads or edits (subagents included)."""
        if self._link_plan is None:
            return
        for block in message.content:
            if not isinstance(block, ToolUseBlock) or block.name not in PLAN_TOOLS:
                continue
            file_path = (block.input or {}).get("file_path")
            if not isinstance(file_path, str) or not file_path:
                continue
            if not looks_like_plan_path(file_path):
                continue  # cheap filter: no database and no disk for other files
            try:
                changed = self._link_plan(self.session_id, file_path)
            except Exception:
                logger.exception("Falha ao vincular o plano da sessão %s", self.session_id)
                continue
            on_plan = self._on_linked_plan(file_path)
            if changed or on_plan:
                self._schedule_plan_refresh()
            if block.name != "Read" and on_plan:
                if len(self._plan_edits) >= PLAN_EDITS_MAX:
                    self._plan_edits.clear()
                self._plan_edits[block.id] = file_path

    def _link_history_plan(self, entries: list[Any]) -> None:
        """Resuming: link the last plan the saved conversation touched (all of it, even
        what the history limit will cut), and read its progress when the link changed.
        A link that was already there keeps its cached progress: the sweep refreshes it."""
        if self._link_plan is None:
            return
        try:
            ref = last_plan_ref(entries)
            changed = self._link_plan(self.session_id, ref) if ref else False
        except Exception:
            logger.exception("Falha ao vincular o plano da sessão %s", self.session_id)
            return
        if changed:
            self._schedule_plan_refresh()

    def _note_plan_result(self, message: UserMessage) -> None:
        """The result of an edit of the linked plan: its progress may have changed."""
        if not self._plan_edits or isinstance(message.content, str):
            return
        for block in message.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id in self._plan_edits:
                file_path = self._plan_edits.pop(block.tool_use_id)
                if self._on_linked_plan(file_path):
                    self._schedule_plan_refresh()

    # PR opened by an agent ----------------------------------------------

    def _note_pr_use(self, message: AssistantMessage) -> None:
        """Keep the Bash calls that run `gh pr create` until their result arrives."""
        if (
            (self._on_pr_created is None or self.record.agent_id is None)
            and self._on_session_pr_created is None
        ):
            return
        for block in message.content:
            if not isinstance(block, ToolUseBlock) or block.name != "Bash":
                continue
            command = (block.input or {}).get("command")
            if not isinstance(command, str) or "gh pr create" not in command:
                continue
            if len(self._pr_creates) >= PR_CREATES_MAX:
                self._pr_creates.clear()
            self._pr_creates.add(block.id)

    def _note_pr_result(self, message: UserMessage) -> None:
        """The result of a `gh pr create`: the first PR URL in it is the PR just opened."""
        if not self._pr_creates or isinstance(message.content, str):
            return
        for block in message.content:
            if not isinstance(block, ToolResultBlock) or block.tool_use_id not in self._pr_creates:
                continue
            self._pr_creates.discard(block.tool_use_id)
            if block.is_error:
                continue
            found = PR_URL_RE.search(_tool_result_text(block.content))
            if found is None:
                continue
            if self._on_pr_created is not None and self.record.agent_id is not None:
                try:
                    self._on_pr_created(self.session_id, found.group(0))
                except Exception:
                    logger.exception("Falha ao registrar o PR da sessão de agente %s", self.session_id)
            self._notify_session_hook(self._on_session_pr_created, found.group(0))

    def _schedule_plan_refresh(self) -> None:
        if self._refresh_plan is None or not self.record.plan_path:
            return
        task = asyncio.create_task(self._refresh_plan(self.session_id))
        self._plan_tasks.add(task)
        task.add_done_callback(self._plan_refresh_done)

    def _plan_refresh_done(self, task: asyncio.Task[bool]) -> None:
        self._plan_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Falha ao atualizar o plano da sessão %s", self.session_id,
                exc_info=task.exception(),
            )

    def _cancel_plan_tasks(self) -> None:
        for task in list(self._plan_tasks):
            task.cancel()
        self._plan_edits.clear()
        self._pr_creates.clear()

    def _touch(self) -> None:
        self._app_activity_at = time.time()
        self.save(last_activity_at=_now())

    # Interruption and failure ---------------------------------------------

    async def interrupt(self) -> None:
        """Interrupt the turn; without a turn, stop the background subagents."""
        client = self.client
        if client is None:
            return
        if self.pending_turns == 0 and not self.prompts and not self._autonomous_turn:
            await self._stop_subagents(client)
            return
        try:
            await client.interrupt()
        except AgentError as error:
            if self.client is client:
                await self._fail(error.message_pt)
            return
        # The SDK cancels the callback of a pending prompt; this catches any left.
        self._cancel_prompts()
        self._refresh_state()

    async def stop_subagents(self) -> None:
        """Stop every running subagent, in any state, without touching the main turn.
        Without a client or a running subagent it does nothing."""
        client = self.client
        if client is not None:
            await self._stop_subagents(client)

    async def _stop_subagents(self, client: AgentClient) -> None:
        # A task that cannot be stopped (e.g. it just ended) must not end the
        # session: logged, and the others are still stopped.
        for task_id in self.builder.running_task_ids():
            self._stop_requested = True
            try:
                await client.stop_task(task_id)
            except Exception:
                logger.exception(
                    "Falha ao parar o subagente %s da sessão %s", task_id, self.session_id
                )

    async def _fail(
        self, message: str, client: AgentClient | None = None, *, notice: bool = True
    ) -> None:
        client = client or self.client
        reader = self._reader
        self._generation += 1
        self.client = None
        self._reader = None
        self.error = message
        self.pending_turns = 0
        self._dispatch_receipt = None
        self._autonomous_turn = False
        self._clear_followup()
        self._release_subagent_hold(announce=False)
        self.builder.clear_local_echo()
        self._remote_lost(message)
        self._emit_events(self.builder.close_open_items())
        self._emit_events(self.builder.stop_running_subagents())
        if notice:
            self._emit_events(self.builder.add_notice("error", message))
        self._cancel_prompts()
        self._refresh_state()
        self.sync_subagents()
        self._report_turn_error(message)
        await self._dispose(client, reader)
        if client is not None:
            await self._record_app_mtime()

    def _report_turn_error(self, text: str) -> None:
        """Tell the agents feature that this agent's turn or session ended in error."""
        if self._on_turn_error is not None and self.record.agent_id is not None:
            try:
                self._on_turn_error(self.session_id, text)
            except Exception:
                logger.exception("Falha ao registrar o erro da sessão de agente %s", self.session_id)
        self._notify_session_hook(self._on_session_error, text)

    def _notify_session_hook(self, callback: Callable[..., None] | None, *args: Any) -> None:
        """Lifecycle observers cannot interrupt the session's reader or error handling."""
        if callback is not None:
            try:
                callback(self.session_id, *args)
            except Exception:
                logger.exception("Falha ao registrar a atividade da sessão %s", self.session_id)

    async def close(self, *, final: bool = False, record_mtime: bool = True) -> None:
        """Close the client, if any. The session goes back to `closed`.

        An in-flight send or connect notices it through `_generation` and stops
        without touching the discarded client. With `final`, later sends are refused.
        With `record_mtime` false the file's mtime is not saved as the app's own.
        """
        if final:
            self._final = True
        effort_task = self._effort_task
        if (
            effort_task is not None and not effort_task.done()
            and effort_task is not asyncio.current_task()
        ):
            effort_task.cancel()
            with suppress(asyncio.CancelledError):
                await effort_task
        if self.effort_pending:
            # Without a client, the new effort is simply used on the next connect.
            self.effort_pending = False
            self._emit_options()
        self.respawn_pending = False  # the next connect starts a process of this version
        client, reader = self.client, self._reader
        self._generation += 1
        self.client = None
        self._reader = None
        self.own_uuids = set()
        self.client_since = None
        self.foreign_candidates = set()
        self.pending_turns = 0
        self._dispatch_receipt = None
        self._autonomous_turn = False
        self._clear_followup()
        self._release_subagent_hold(announce=False)
        self.builder.clear_local_echo()
        self._remote_down()
        if client is not None:
            self._emit_events(self.builder.stop_running_subagents())
        self._cancel_prompts()
        self._refresh_state()
        self.sync_subagents()
        await self._dispose(client, reader)
        if client is not None and record_mtime:
            await self._record_app_mtime()

    async def detach(self) -> None:
        """Backend shutdown: let the agentd keep the process running. Without an agentd
        (or a client that cannot detach) this is close(final=True)."""
        self._final = True
        # A connect or reattach still running notices it through `_generation` and
        # discards what it created; waiting for the lock leaves no untracked child.
        self._generation += 1
        effort_task = self._effort_task
        if (
            effort_task is not None and not effort_task.done()
            and effort_task is not asyncio.current_task()
        ):
            effort_task.cancel()
            with suppress(asyncio.CancelledError):
                await effort_task
        self._cancel_remote_retry()
        await self.wait_settled()
        self._clear_followup()
        self._release_subagent_hold(announce=False)
        self._cancel_context_read()
        self._cancel_plan_tasks()
        client = self.client
        if client is None:
            return
        # The reader goes first: once the client lets go, its stream ends and the reader
        # would take that for the process dying and kill it through `_fail`.
        reader, self._reader = self._reader, None
        if reader is not None and not reader.done():
            reader.cancel()
            with suppress(asyncio.CancelledError):
                await reader
        try:
            detached = await client.detach()
        except Exception:
            logger.exception("Falha ao soltar a sessão %s", self.session_id)
            detached = False
        if not detached:
            await self.close(final=True)
            return
        try:
            # Where the next reattach starts judging writes by other processes from.
            self.save(detached_at=time.time())
        except Exception:
            logger.exception("Falha ao gravar o desligamento da sessão %s", self.session_id)
        self._generation += 1
        self.client = None

    def note_child_exit(self, stderr: list[str]) -> None:
        """The process the agentd kept for this session died while the app was down:
        remember the last line it wrote, so the cause (login expired, crash) is not lost."""
        detail = next((line.strip() for line in reversed(stderr) if line.strip()), "")
        if not detail:
            return
        if len(detail) > EXIT_DETAIL_LIMIT:
            detail = detail[:EXIT_DETAIL_LIMIT] + "…"
        self._exit_note = CHILD_EXITED_TEXT.format(detail=detail)
        if self._history_loaded and self.record.turn_open and not self.active:
            self._emit_events(self.builder.add_notice("warning", self._exit_note))

    async def reattach(self, child: Any) -> bool:
        """Attach to a process the agentd kept across a backend restart.

        Returns False when it could not (the session is then failed or closed and the
        caller kills the child); a cancellation disposes the client and propagates."""
        async with self._lock:
            if self.client is not None:
                return False  # already attached: never replace a client that is in use
            started = await asyncio.to_thread(process_started_at, child.pid)
            await self.ensure_history(live=True, process_started_at=started)
            was_open = self.record.turn_open
            client: AgentClient | None = None
            generation = self._generation
            # Before connect: a pending permission delivered during connect refreshes
            # the state, and turn_open must not flip to 0 meanwhile.
            self._autonomous_turn = bool(was_open)
            try:
                # Inside the try: the setup of an agent session can fail here too.
                client = self._new_client(
                    resume=True,
                    attach=AttachInfo(agentd_id=child.id, from_pos=child.ack,
                                      init_response=child.init),
                )
                await client.connect()
            except asyncio.CancelledError:
                self._autonomous_turn = False
                if client is not None:
                    with suppress(asyncio.CancelledError):
                        await self._dispose(client, None)
                self._mark_interrupted(was_open)
                self._refresh_state()
                raise
            except Exception as error:  # AgentError or anything unexpected
                if isinstance(error, AgentError):
                    message = error.message_pt
                else:
                    logger.exception("Falha ao religar a sessão %s", self.session_id)
                    message = f"Falha inesperada ao religar o agente: {error}"
                await self._fail(message, client)
                self._mark_interrupted(was_open)
                return False
            if generation != self._generation:
                if self._final:
                    # The backend is shutting down: the process keeps running.
                    with suppress(Exception):
                        await client.detach()
                    return True
                self._autonomous_turn = False
                await self._dispose(client, None)
                self._refresh_state()
                return False
            # What other processes wrote while the backend was away counts too.
            detached_at = self.record.detached_at
            self._start_reader(client, since=detached_at)  # which clears it
            self._refresh_state()
            self.emit_updated()
            self._resume_remote(client)
            return True

    def _resume_remote(self, client: AgentClient) -> None:
        """A process the agentd kept is attached again and the session is marked: its
        Remote Control is still up, but the state is lost with the old backend, so ask
        again (the CLI answers with the same entry). A process from an older version is
        replaced between turns first, the way a pending effort is."""
        if not self.record.remote_control or self.record.finished or self._final:
            return
        self._set_remote("connecting")
        if self.record.spawn_version >= SPAWN_VERSION:
            self._start_remote(client, attached=True)
        else:
            self.respawn_pending = True
            self._schedule_effort()

    def _mark_interrupted(self, was_open: bool) -> None:
        """The turn that was open when the backend went away has no process to finish it."""
        if was_open:
            self._emit_events(self.builder.add_notice("warning", INTERRUPTED_TEXT))

    async def wait_settled(self) -> None:
        """Wait for a send or connect still holding the lock and for any disposal."""
        async with self._lock:
            pass
        await self._wait_disposal()

    async def _close_quietly(self, client: AgentClient) -> None:
        try:
            if self._on_process_close:
                self._on_process_close(self.session_id, 'closing', client)
            await client.close()
            if self._on_process_close:
                self._on_process_close(self.session_id, 'closed', client)
            self._unclosed_clients = [old for old in self._unclosed_clients if old is not client]
            self.process_closed = not self._unclosed_clients
            self.process_close_failed = bool(self._unclosed_clients)
        except BaseException as error:
            self.process_closed = False
            self.process_close_failed = True
            if not any(old is client for old in self._unclosed_clients):
                self._unclosed_clients.append(client)
            if self._on_process_close:
                try:
                    self._on_process_close(self.session_id, 'uncertain', client)
                except Exception:
                    logger.exception('Falha ao persistir o fechamento incerto da sessão %s', self.session_id)
            if isinstance(error, asyncio.CancelledError):
                raise
            logger.exception("Falha ao fechar o cliente da sessão %s", self.session_id)

    async def retry_failed_process_closes(self) -> bool:
        """Retry only exact client references retained after a failed close."""
        await self._wait_disposal()
        if self.client is not None or not self._unclosed_clients:
            return False
        for client in list(self._unclosed_clients):
            await self._close_quietly(client)
        return self.process_closed and not self.process_close_failed

    async def _wait_disposal(self) -> None:
        disposal = self._disposal
        if disposal is not None and disposal is not asyncio.current_task():
            await asyncio.wait([disposal])

    async def _dispose(
        self, client: AgentClient | None, reader: asyncio.Task[None] | None
    ) -> None:
        if reader is asyncio.current_task():
            reader = None  # the reader is failing itself: it must not be cancelled
        self._cancel_context_read()
        self._cancel_plan_tasks()
        task = asyncio.create_task(self._do_dispose(client, reader))
        self._disposal = task
        try:
            await asyncio.shield(task)
        finally:
            if self._disposal is task and task.done():
                self._disposal = None

    async def _do_dispose(
        self, client: AgentClient | None, reader: asyncio.Task[None] | None
    ) -> None:
        if client is not None:
            await self._close_quietly(client)
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.wait([reader])

    # Permissions -----------------------------------------------------------

    async def _can_use_tool(
        self, tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        extras = self._extras
        if extras is not None:
            decision = await self._policy_decision(extras, tool_name, tool_input)
            if decision == "allow":
                return PermissionResultAllow()
            if decision == "deny":
                return PermissionResultDeny(message=BLOCKED_TOOL_MESSAGE)
        prompt = PendingPrompt(
            prompt_id=uuid.uuid4().hex,
            future=asyncio.get_running_loop().create_future(),
            tool_name=tool_name,
            input=tool_input,
            display_name=context.display_name,
            description=context.description,
            title=context.title,
            tool_use_id=context.tool_use_id,
            suggestions=list(context.suggestions),
        )
        before = self._pending_view()
        self.prompts[prompt.prompt_id] = prompt
        self._emit("prompt.request", prompt.to_dict())
        self._refresh_state()
        self._emit_pending_change(before)
        try:
            return await prompt.future
        except asyncio.CancelledError:
            # The SDK cancels this task when the turn is interrupted.
            before = self._pending_view()
            if self.prompts.pop(prompt.prompt_id, None) is not None:
                self._emit_resolved(prompt.prompt_id, "cancelled")
                self._refresh_state()
                self._emit_pending_change(before)
            raise

    async def _policy_decision(
        self, extras: SessionExtras, tool_name: str, tool_input: dict[str, Any]
    ) -> Literal["allow", "ask", "deny"]:
        """What the agent's policy says about this tool call. Anything but `allow` or
        `deny`, and any failure of the policy, means "ask": the user decides."""
        try:
            decision = await asyncio.wait_for(
                extras.decide(tool_name, tool_input), POLICY_TIMEOUT
            )
            return decision if decision in ("allow", "deny") else "ask"
        except TimeoutError:
            logger.warning(
                "A política do agente da sessão %s demorou mais de %s s em %s; perguntando",
                self.session_id, POLICY_TIMEOUT, tool_name,
            )
            return "ask"
        except Exception:
            logger.exception("Falha na política do agente da sessão %s", self.session_id)
            return "ask"

    def _emit_pending_change(self, before: tuple[dict[str, Any] | None, str | None]) -> None:
        """Update the summary when the pending permission or prompt kind it shows changed."""
        if self._pending_view() != before:
            self.emit_updated()

    def resolve_prompt(
        self,
        prompt_id: str,
        decision: str,
        *,
        answers: Any = None,
        message: str | None = None,
    ) -> None:
        """Answer a pending prompt. `answers` goes with `answer` (questions) and
        `message` with `reject` (plans)."""
        if decision not in DECISIONS:
            raise InvalidDecisionError("Decisão inválida.")
        prompt = self.prompts.get(prompt_id)
        if prompt is None or prompt.future.done():
            raise PromptNotFoundError("Este pedido já foi respondido ou não existe mais.")
        if decision not in KIND_DECISIONS[prompt.kind]:
            raise InvalidDecisionError("Esta decisão não vale para este pedido.")
        result: PermissionResultAllow | PermissionResultDeny
        if decision == "answer":
            result = PermissionResultAllow(
                updated_input={**prompt.input, "answers": build_answers(prompt.input, answers)}
            )
        elif decision == "approve":
            result = PermissionResultAllow()
        elif decision == "reject":
            if not message or not message.strip():
                raise RejectMessageRequiredError("Diga o que mudar no plano.")
            result = PermissionResultDeny(message=message.strip())
        elif decision == "allow_once":
            result = PermissionResultAllow()
        elif decision == "allow_always":
            if not prompt.suggestions:
                raise AlwaysNotAvailableError("Este pedido não oferece a opção de permitir sempre.")
            result = PermissionResultAllow(updated_permissions=list(prompt.suggestions))
        else:
            result = PermissionResultDeny(message=DENY_MESSAGE)
        before = self._pending_view()
        del self.prompts[prompt_id]
        prompt.future.set_result(result)
        self._emit_resolved(prompt_id, decision)
        if decision == "approve" and self.record.permission_mode != "default":
            # The CLI leaves plan mode on approval; the init that confirms it may come late.
            self.save(permission_mode="default")
            self._emit_options()
        self._refresh_state()
        self._emit_pending_change(before)
        self._schedule_effort()

    def _cancel_prompts(self) -> None:
        before = self._pending_view()
        for prompt_id in list(self.prompts):
            prompt = self.prompts.pop(prompt_id)
            if not prompt.future.done():
                prompt.future.set_result(
                    PermissionResultDeny(message=CANCELLED_MESSAGE, interrupt=True)
                )
            self._emit_resolved(prompt_id, "cancelled")
        self._emit_pending_change(before)

    def _emit_resolved(self, prompt_id: str, decision: str) -> None:
        self._emit("prompt.resolved", {"prompt_id": prompt_id, "decision": decision})


# Manager -------------------------------------------------------------------


class SessionManager:
    def __init__(
        self,
        db_path: Path,
        publish: Publish,
        *,
        agent_factory: AgentFactory | None = None,
        history_exists: HistoryExists | None = None,
        rename_session: RenameSession | None = None,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        finished_after_days: float = DEFAULT_FINISHED_AFTER_DAYS,
        list_sessions: ListSessions | None = None,
        get_session_messages: GetSessionMessages | None = None,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        read_tool_results: ReadToolResults | None = None,
        file_mtime: FileMtime | None = None,
        session_file: Callable[[str, str], Path | None] | None = None,
        on_turn_end: Callable[[int], None] | None = None,
        on_finished: Callable[[str, int], None] | None = None,
        default_permission_mode: Callable[[], str | None] | None = None,
        read_transcript: history_module.ReadTranscript | None = None,
        read_edits: history_module.ReadEdits | None = None,
        clock: Callable[[], float] = time.time,
        read_context: ReadContext | None = None,
        agentd: Any | None = None,
        agentd_new_sessions: bool = True,
        cli_identity: Callable[[], dict[str, Any]] | None = None,
        text_index: TextSearch | None = None,
        session_setup: SessionSetup | None = None,
        context_setup: ContextSetup | None = None,
        connection_admission: Callable[[SessionRecord], None] | None = None,
        remote_reconnect_allowed: Callable[[SessionRecord], bool] | None = None,
        on_session_turn_end: Callable[[str], None] | None = None,
        on_session_result: Callable[[str, dict[str, Any]], None] | None = None,
        on_session_error: Callable[[str, str], None] | None = None,
        on_session_init: Callable[[str, list[dict[str, str]]], None] | None = None,
        on_session_pr_created: Callable[[str, str], None] | None = None,
        on_turn_error: Callable[[str, str], None] | None = None,
        on_init: Callable[[str, list[dict[str, str]]], None] | None = None,
        on_pr_created: Callable[[str, str], None] | None = None,
        prepare_message: PrepareMessage | None = None,
        claude_projects: Path | None = None,
    ) -> None:
        # The CLI's projects folder (None: `claude_projects_dir()` when needed).
        self._claude_projects = claude_projects
        # Ids of the temporary copies context measurements open, oldest first. Kept after
        # the measurement too (bounded), so a file the CLI writes late is still ignored.
        self._throwaway_ids: OrderedDict[str, None] = OrderedDict()
        # Gives the sessions of an agent their skill, folders, MCP server and policy.
        self._session_setup = session_setup
        self._context_setup = context_setup
        self._connection_admission = connection_admission
        self._on_process_close = None
        self._on_process_start = None
        self._on_session_turn_start = None
        self._remote_reconnect_allowed = remote_reconnect_allowed
        self._on_session_turn_end = on_session_turn_end
        self._on_session_result = on_session_result
        self._on_session_error = on_session_error
        self._on_session_init = on_session_init
        self._on_session_pr_created = on_session_pr_created
        # Errors and inits of the sessions of an agent (see `ActiveSession`).
        self._on_turn_error = on_turn_error
        self._on_init = on_init
        self._on_pr_created = on_pr_created
        self._prepare_message = prepare_message
        # `{"path", "version"}` of the `claude` in use now. The models list is saved with
        # the one it came from and is stale when they differ (None: not checked).
        self._cli_identity = cli_identity
        self._text_index = text_index
        # Keeps `claude` processes across restarts; None runs them as children of this process.
        self._agentd = agentd
        self._agentd_new_sessions = agentd_new_sessions
        self._clock = clock
        # Context usage of sessions without a client, from the last assistant message.
        self._read_context = read_context or history_module.sdk_read_context
        # session_id -> (file modification it was read at, read result); see `_history_context`.
        self._history_contexts: OrderedDict[str, tuple[int, dict[str, Any] | None]] = OrderedDict()
        # Mode of new sessions (the user's CLI `defaultMode`).
        self._default_permission_mode = default_permission_mode or user_default_permission_mode
        # One pass over the transcript file. Only by default: tests that inject
        # get_session_messages or read_tool_results keep using them.
        if read_transcript is None and get_session_messages is None and read_tool_results is None:
            read_transcript = history_module.sdk_read_transcript
        self._read_transcript = read_transcript
        self._read_edits = read_edits or history_module.sdk_read_edits
        # Called with the project id after each turn (e.g. to refresh git).
        self._on_turn_end = on_turn_end
        # Called with (session_id, finished_at) when a session goes from open to finished.
        self._on_finished = on_finished
        self._db_path = db_path
        self._file_mtime = file_mtime or history_module.sdk_session_file_mtime
        # session_file(session_id, directory): path of the session's `.jsonl`, or None.
        self._session_file = session_file or history_module.sdk_session_file
        # State of sessions forgotten from memory (seq, connected before, app
        # activity), so events keep increasing and they resume as before.
        self._forgotten: dict[str, tuple[int, bool, float, float | None]] = {}
        # session_id -> (last context breakdown, when it was measured) of forgotten sessions,
        # so the context panel still has something to show; memory only, bounded.
        self._kept_breakdowns: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()
        self._read_tool_results = read_tool_results or history_module.sdk_read_tool_results
        self._list_sessions = list_sessions or history_module.sdk_list_sessions
        self._get_session_messages = (
            get_session_messages or history_module.sdk_get_session_messages
        )
        self._history_limit = history_limit
        self._publish = publish
        self._agent_factory = agent_factory or default_agent_factory
        self._history_exists = history_exists or sdk_history_exists
        self._rename_session = rename_session or sdk_rename_session
        self._idle_timeout = idle_timeout
        self._finished_after_days = finished_after_days
        self._sessions: dict[str, ActiveSession] = {}
        # Parsed plans by file (reread only when the file changes) and the last
        # progress known per plan path, kept in memory: listings only read the latter.
        self.plan_cache = PlanCache()
        self._plan_progress: dict[str, dict[str, Any] | None] = {}
        self._plan_locks: dict[str, asyncio.Lock] = {}
        # Sessions whose CLI is in the middle of a turn, from the CLI watcher (memory only).
        self._cli_turns: dict[str, _CliTurn] = {}
        # Sessions whose process the agentd may still hold (from the last `reattach_all`),
        # shared with the sessions: their automatic Remote Control reconnect waits.
        self._agentd_held: set[str] = set()
        # Temporary-process context measurements of closed conversations, by session id,
        # and the slot that lets only one of them run in the whole app.
        self._probes: dict[str, _Probe] = {}
        self._probe_slot = asyncio.Semaphore(1)
        # Models of `get_server_info()`, kept in `app_state` so a restart starts
        # with the last list. `_models_fetched_at` is when it was last confirmed.
        self._models: list[dict[str, Any]] | None = None
        self._models_fetched_at = 0.0
        self._models_cli: dict[str, Any] | None = None
        self._load_models()
        # Short sentence and plan seal of the digest agent, by session (memory copy).
        self._digest_briefs: dict[str, tuple[str | None, bool]] = {}
        # Closure verdict and check time of the digest agent, by session (memory copy).
        self._closure_briefs: dict[str, tuple[str | None, int | None]] = {}
        self._load_digest_briefs()
        # Label ids of each session, kept in memory so listings and events never query them.
        self._label_ids: dict[str, list[int]] = {}
        self._load_label_ids()

    def list_models(self) -> list[dict[str, Any]]:
        return [dict(m) for m in (self._models or FALLBACK_MODELS)]

    def _load_models(self) -> None:
        try:
            with closing(db.connect(self._db_path)) as conn:
                row = conn.execute(
                    "SELECT value FROM app_state WHERE key = ?", (MODELS_CACHE_KEY,)
                ).fetchone()
            stored = json.loads(row["value"]) if row is not None else None
            models = normalize_models(stored)
            fetched_at = stored.get("fetched_at") if isinstance(stored, dict) else None
            cli = stored.get("cli") if isinstance(stored, dict) else None
        except (sqlite3.Error, ValueError):
            logger.exception("Falha ao ler a lista de modelos guardada")
            return
        if models is not None and isinstance(fetched_at, int | float):
            self._models = models
            self._models_fetched_at = float(fetched_at)
            self._models_cli = cli if isinstance(cli, dict) else None

    def _save_models(self) -> None:
        value = json.dumps(
            {"models": self._models, "fetched_at": self._models_fetched_at, "cli": self._models_cli},
            ensure_ascii=False,
        )
        try:
            with closing(db.connect(self._db_path)) as conn:
                conn.execute(
                    "INSERT INTO app_state (key, value) VALUES (?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (MODELS_CACHE_KEY, value),
                )
        except sqlite3.Error:
            logger.exception("Falha ao guardar a lista de modelos")

    def _models_stale(self) -> bool:
        if self._models is None or self._clock() - self._models_fetched_at >= MODELS_MAX_AGE:
            return True
        # Another `claude` than the one that gave the list (the terminal's updated itself,
        # it was installed or removed, or MAESTRO_CLAUDE_CLI changed across a restart).
        return self._cli_identity is not None and self._models_cli != self._cli_identity()

    async def _fetch_models(self, client: AgentClient) -> bool:
        """Ask the client for the models. True when a valid list was received."""
        try:
            info = await client.get_server_info()
        except Exception:
            logger.exception("Falha ao consultar os modelos do agente")
            return False
        models = normalize_models(info)
        if models is None:
            return False
        changed = models != self._models
        self._models = models
        self._models_fetched_at = self._clock()
        self._models_cli = self._cli_identity() if self._cli_identity is not None else None
        self._save_models()
        if changed:
            self._publish({
                "session_id": None, "seq": 0, "type": "models.updated",
                "data": {"models": self.list_models()},
            })
        return True

    async def _on_connected(self, client: AgentClient) -> None:
        if self._models_stale():
            await self._fetch_models(client)

    async def refresh_models_if_stale(self, force: bool = False) -> bool:
        """Ask the SDK for the models with a throwaway client, when the stored
        list is missing or old (or always, with `force`). True when a new list
        was received; failures are logged and leave the stored list as it is."""
        if not force and not self._models_stale():
            return False
        client: AgentClient | None = None
        try:
            client = self._agent_factory(
                AgentOptions(
                    cwd=Path.home(),
                    session_id=str(uuid.uuid4()),
                    resume=False,
                    can_use_tool=_deny_all,
                    setting_sources=[],
                )
            )
            await client.connect()
            return await self._fetch_models(client)
        except Exception:
            logger.exception("Falha ao atualizar a lista de modelos")
            return False
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()

    async def run_models_refresh(
        self, interval: float, sleep: Callable[[float], Any] = asyncio.sleep
    ) -> None:
        """At startup and every `interval` seconds, refreshes a stale models list."""
        while True:
            try:
                await self.refresh_models_if_stale()
            except Exception:
                logger.exception("Falha na atualização periódica dos modelos")
            await sleep(interval)

    def set_work_lifecycle_observers(self, *, process_close, process_start, turn_start):
        """Observe governed identities without changing normal project policy."""
        self._on_process_close = process_close
        self._on_process_start = process_start
        self._on_session_turn_start = turn_start
        for session in self._sessions.values():
            session._on_process_close = process_close
            session._on_process_start = process_start
            session._on_session_turn_start = turn_start

    def create_session(
        self,
        project: Project,
        group_id: int | None = None,
        *,
        agent_id: int | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> SessionRecord:
        """A new session. For an agent (`agent_id`) it always starts in the default
        permission mode, whatever the saved preference: its policy needs the CLI to ask."""
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            return self.create_session_in_transaction(conn, project, group_id,
                agent_id=agent_id, model=model, effort=effort)

    def create_session_in_transaction(
        self,
        conn: sqlite3.Connection,
        project: Project,
        group_id: int | None = None,
        *,
        agent_id: int | None = None,
        model: str | None = None,
        effort: str | None = None,
    ) -> SessionRecord:
        """A new session. For an agent (`agent_id`) it always starts in the default
        permission mode, whatever the saved preference: its policy needs the CLI to ask."""
        if not conn.in_transaction:
            raise RuntimeError('Criar sessão exige uma transação ativa.')
        if effort is not None and effort not in EFFORTS:
            raise InvalidDecisionError("Nível de raciocínio inválido.")
        if model is not None and not MODEL_PATTERN.match(model):
            raise InvalidDecisionError("Modelo inválido.")
        if not project.available:
            raise ProjectUnavailableError("A pasta do projeto não está disponível.")
        now = _now()
        default_model, default_effort, mode = new_session_defaults(conn)
        record = SessionRecord(
            session_id=str(uuid.uuid4()),
            project_id=project.id,
            cwd=project.path,
            title=DEFAULT_TITLE,
            created_at=now,
            last_activity_at=now,
            last_seen_at=now,
            finished=False,
            model=model or default_model,
            effort=effort or default_effort,
            # Saved preference, then the user's CLI `defaultMode`, then None.
            permission_mode=(
                "default" if agent_id is not None
                else mode or self._default_permission_mode()
            ),
            group_id=group_id,
            agent_id=agent_id,
        )
        # Same transaction: the group cannot vanish between the check and the insert.
        if group_id is not None:
            groups.get_group(conn, group_id)
        conn.execute(
            f"INSERT INTO sessions ({_INSERT_COLUMNS}, model, effort, permission_mode, group_id,"
            " agent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.session_id,
                record.project_id,
                record.cwd,
                record.title,
                record.created_at,
                record.last_activity_at,
                record.last_seen_at,
                int(record.finished),
                record.model,
                record.effort,
                record.permission_mode,
                record.group_id,
                record.agent_id,
            ),
        )
        return record

    @property
    def agent_factory(self) -> AgentFactory:
        """The factory sessions use; throwaway clients (command catalog) share it."""
        return self._agent_factory

    def find_record(self, session_id: str) -> SessionRecord:
        """The session's record, from memory or the database, without loading the
        session into memory."""
        session = self._sessions.get(session_id)
        if session is not None:
            return session.record
        row = self._read_row(session_id)
        if row is None:
            raise SessionNotFoundError("Sessão não encontrada.")
        return _record(row)

    def get(self, session_id: str) -> ActiveSession:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionNotFoundError("Sessão não encontrada.")
        session = ActiveSession(
            _record(row),
            db_path=self._db_path,
            publish=self._publish,
            agent_factory=self._agent_factory,
            history_exists=self._history_exists,
            describe=self._describe_active,
            get_session_messages=self._get_session_messages,
            rename_session=self._rename_session,
            history_limit=self._history_limit,
            read_tool_results=self._read_tool_results,
            file_mtime=self._file_mtime,
            session_file=self._session_file,
            on_turn_end=self._on_turn_end,
            on_connected=self._on_connected,
            read_transcript=self._read_transcript,
            link_plan=lambda sid, path: self.link_plan(sid, path, source="auto"),
            refresh_plan=self.refresh_plan,
            agentd=self._agentd if self._agentd_new_sessions else None,
            agentd_any=self._agentd,
            cli_running=self._cli_running,
            agentd_held=self._agentd_held,
            session_setup=self._session_setup,
            context_setup=self._context_setup,
            connection_admission=self._connection_admission,
            on_process_close=self._on_process_close,
            on_process_start=self._on_process_start,
            on_session_turn_start=self._on_session_turn_start,
            remote_reconnect_allowed=self._remote_reconnect_allowed,
            on_session_turn_end=self._on_session_turn_end,
            on_session_result=self._on_session_result,
            on_session_error=self._on_session_error,
            on_session_init=self._on_session_init,
            on_session_pr_created=self._on_session_pr_created,
            on_turn_error=self._on_turn_error,
            on_init=self._on_init,
            on_pr_created=self._on_pr_created,
            prepare_message=self._prepare_message,
        )
        forgotten = self._forgotten.pop(session_id, None)
        if forgotten is not None:
            (session.seq, session._connected_before,
             session._app_activity_at, session._loaded_mtime) = forgotten
            # Recreated empty: the conversation comes from disk, and the frontend
            # drops what it shows before any other event of this session.
            session._emit("conversation.reset", {})
        kept = self._kept_breakdowns.pop(session_id, None)
        if kept is not None:
            session.last_breakdown, session.last_breakdown_at = kept
        self._sessions[session_id] = session
        return session

    def active_ids(self) -> set[str]:
        return set(self._sessions)

    def live_count(self) -> int:
        """Sessions with a client connected or connecting in this app."""
        return sum(1 for session in self._sessions.values() if session.active)

    # History -----------------------------------------------------------------

    async def open(self, session_id: str) -> dict[str, Any]:
        """Snapshot of a session, loading its saved conversation if needed."""
        session = self.get(session_id)
        session.users += 1
        try:
            await session.reload_if_modified()
            await session.ensure_history()
            await self.refresh_file_info(session)
            if session.client is None or session.context is None:
                # No value from a connected client: the last message of the history.
                before = session.context
                history = await self._history_context(session)
                # A turn that ended during the read already set a newer value.
                if history is not None and session.context is before:
                    session.context = history
            return session.snapshot()
        finally:
            session.users -= 1

    async def context_details(self, session_id: str) -> dict[str, Any]:
        """Context breakdown of a session, read on demand from its client.

        A session without a client has no process to ask: it answers the last breakdown
        kept in memory. With none kept (and nothing using the conversation), a temporary
        process measures a copy of it (`_probe_details`), so the answer is `live: False`
        with the time of that measurement. Without anything to show, `no_process`."""
        record = self.find_record(session_id)  # SessionNotFoundError for an unknown id
        session = self._sessions.get(session_id)
        if session is None:
            kept = self._kept_breakdowns.get(session_id)
            if kept is not None:
                breakdown, measured_at = kept
                return _stored_details(breakdown, measured_at, None)
        elif session.client is not None or session.last_breakdown is not None:
            return await session.read_context_details()
        context = session.context if session is not None else None
        if (
            self.app_writing(session_id)
            # The agentd may still hold a process on this conversation (restart): a second
            # one, even a fork, is not wanted next to it.
            or session_id in self._agentd_held
            or not await self._has_history(record)
        ):
            return {"available": False, "reason": "no_process", "context": context}
        measured = await self._probe_details(session_id, record)
        if measured is None:
            return {"available": False, "reason": "no_process", "context": context}
        breakdown, measured_at = measured
        return _stored_details(breakdown, measured_at, context)

    async def _has_history(self, record: SessionRecord) -> bool:
        """The conversation exists on disk: without it there is nothing to resume."""
        try:
            return await asyncio.to_thread(
                self._history_exists, record.session_id, record.history_directory
            )
        except Exception:
            logger.exception("Falha ao consultar o histórico da sessão %s", record.session_id)
            return False

    async def _probe_details(
        self, session_id: str, record: SessionRecord
    ) -> tuple[dict[str, Any], float] | None:
        """(breakdown, measured_at) from a temporary process, or None when it failed.

        Requests for the same session share one measurement. A caller that goes away does
        not cancel it once its process started: it ends on its own within
        `CONTEXT_PROBE_LIMIT` and its result is kept for the next request. A measurement
        still waiting in line with nobody left to answer is dropped instead. A caller
        "goes away" when its task is cancelled: the route cancels it when the HTTP client
        hangs up (the server does not do that by itself)."""
        probe = self._probes.get(session_id)
        if probe is None or probe.task is None or probe.task.done():
            probe = _Probe()
            task = asyncio.create_task(self._run_probe(session_id, record, probe))
            probe.task = task
            self._probes[session_id] = probe

            def forget(_done: asyncio.Future[Any], probe: _Probe = probe) -> None:
                if self._probes.get(session_id) is probe:
                    del self._probes[session_id]

            task.add_done_callback(forget)
        task = probe.task
        assert task is not None
        probe.waiters += 1
        try:
            # `wait` does not cancel the measurement when this caller goes away.
            await asyncio.wait([task])
        finally:
            probe.waiters -= 1
            if probe.waiters == 0 and not probe.started and not task.done():
                task.cancel()
                # A request arriving before the cancel lands starts a new measurement.
                if self._probes.get(session_id) is probe:
                    del self._probes[session_id]
        if task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    async def _run_probe(
        self, session_id: str, record: SessionRecord, probe: _Probe
    ) -> tuple[dict[str, Any], float] | None:
        async with self._probe_slot:
            probe.started = True
            started_at = time.time()
            try:
                options = self._probe_options(record)
                fork_id = options.fork_session_id
                loop = asyncio.get_running_loop()
                usage = await probe_context(
                    self._agent_factory,
                    options,
                    CONTEXT_PROBE_LIMIT,
                    after_close=lambda: self._discard_fork(fork_id, loop) if fork_id else None,
                )
            except Exception as error:
                # An `AgentError` (connect, read, a factory that refuses) or the timeout.
                logger.warning(
                    "Não foi possível medir o contexto da sessão %s: %s",
                    session_id,
                    str(error) or type(error).__name__,
                )
                return None
            breakdown = context_breakdown(usage)
            if breakdown is None:
                return None
            # The conversation was read when the process opened, so that is its time.
            self._keep_probed(session_id, breakdown, started_at)
            return breakdown, started_at

    def _probe_options(self, record: SessionRecord) -> AgentOptions:
        """A resumed copy of the conversation that sends nothing and runs no tool or hook.

        It loads the folder's settings (MCP, skills, CLAUDE.md, agents), so the breakdown
        is the real one; the SDK starts it directly, not through the agentd.

        The copy is not always invisible: when the conversation had a background subagent
        alive (the machine froze), the CLI queues a notification about it on loading, and
        that makes it save the copy as `<new id>.jsonl`, with the whole history and the
        same title, under the folder of the original conversation's cwd. So the copy gets
        an id chosen here: it is marked throwaway before the process starts (the history
        sync, the CLI watcher and the search index never register it) and its files are
        deleted when the process is gone (`_discard_fork`)."""
        fork_id = str(uuid.uuid4())
        self.mark_throwaway(fork_id)
        return AgentOptions(
            cwd=Path(record.work_dir()),
            session_id=record.session_id,
            resume=True,
            fork_session=True,
            fork_session_id=fork_id,
            can_use_tool=_deny_all,
            model=None if record.model == DEFAULT_MODEL_VALUE else record.model,
            settings='{"disableAllHooks": true}',
            setting_sources=None,
            agentd=None,
        )

    def mark_throwaway(self, session_id: str) -> None:
        """Never register this id as a session (a temporary copy of a conversation)."""
        self._throwaway_ids[session_id] = None
        self._throwaway_ids.move_to_end(session_id)
        while len(self._throwaway_ids) > THROWAWAY_ID_LIMIT:
            self._throwaway_ids.popitem(last=False)

    def is_throwaway(self, session_id: str) -> bool:
        return session_id in self._throwaway_ids

    def _discard_fork(self, fork_id: str, loop: asyncio.AbstractEventLoop) -> None:
        """Delete what a measurement's copy left (its files, and its row if some path
        registered it anyway). Blocking: runs in a thread, once the process is gone;
        the event is published on `loop`."""
        try:
            delete_fork_files(self._claude_projects or claude_projects_dir(), fork_id)
        except OSError:
            logger.warning("Não foi possível apagar a cópia temporária %s", fork_id, exc_info=True)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            row = conn.execute(
                "SELECT project_id FROM sessions WHERE session_id = ?", (fork_id,)
            ).fetchone()
            if row is None:
                return
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (fork_id,))
        loop.call_soon_threadsafe(
            self._publish,
            {"session_id": None, "seq": 0, "type": "project.synced",
             "data": {"project_id": row["project_id"]}},
        )

    def _keep_probed(self, session_id: str, breakdown: dict[str, Any], measured_at: float) -> None:
        """Keep what a probe measured, unless something newer is already kept (a live
        client may have measured the session while the probe ran)."""
        session = self._sessions.get(session_id)
        if session is not None:
            if session.last_breakdown_at is None or session.last_breakdown_at < measured_at:
                session.last_breakdown, session.last_breakdown_at = breakdown, measured_at
            return
        kept = self._kept_breakdowns.get(session_id)
        if kept is None or kept[1] < measured_at:
            self._kept_breakdowns[session_id] = (breakdown, measured_at)
            self._kept_breakdowns.move_to_end(session_id)
            while len(self._kept_breakdowns) > KEPT_BREAKDOWN_LIMIT:
                self._kept_breakdowns.popitem(last=False)

    async def send(
        self, session_id: str, text: str, images: list[dict[str, Any]] | None = None,
        *, dispatch_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message. `external_activity` tells whether the resumed history was
        modified in the last minute by another process."""
        session = self.get(session_id)
        session.users += 1
        try:
            await self._note_foreign_writes(session)
            if session.foreign_pending and session.client is not None:
                # Another process continued the conversation while the app was busy:
                # this client's view is stale and a send would fork the history.
                if session.subagents_running:
                    raise ContinuedElsewhereError(CONTINUED_ELSEWHERE_TEXT)
                await session.release_for_external()
            external = False
            if not session.active:
                await session.reload_if_modified()
                await self.refresh_file_info(session)
                external = session.external_activity
            send_started = (await session.send(text, images, dispatch_id=dispatch_id)
                            if dispatch_id is not None else await session.send(text, images))
            return {"state": session.state, "external_activity": external, "send_started": send_started}
        finally:
            session.users -= 1

    async def _note_foreign_writes(self, session: ActiveSession) -> None:
        """Read the end of the session's file, as the watcher's first pass does, and
        remember replies another process wrote that no watcher pass judged (the write
        happened with the backend down, or a pass was lost). Only for an idle session,
        where the stream has delivered every uuid the process emitted. Never fails the
        send."""
        if session.client is None or session.state != "idle":
            # Not idle: an app turn or prompt may have its own reply in the file before
            # the stream delivers it (the watcher covers that case).
            return
        try:
            path = await asyncio.to_thread(
                self._session_file, session.session_id, session.record.history_directory
            )
            if path is None:
                return
            try:
                lines, _ = await asyncio.to_thread(read_new_lines, path, None)
            except OSError:
                return  # missing or unreadable: nothing to judge
            session.foreign_candidates |= foreign_reply_uuids(
                lines, session.own_uuids, session.client_since
            )
        except Exception:
            logger.exception(
                "Falha ao checar escrita de outro processo na sessão %s", session.session_id
            )

    async def refresh_file_info(self, session: ActiveSession) -> None:
        """Read the history file's mtime (one `stat`) for a session not active in the app."""
        if session.active:
            return
        current = await session._current_mtime()
        if current is None:
            return
        modified = int(current)
        if modified != session.record.file_modified_at:
            session.save(file_modified_at=modified)

    async def transcript_edits(self, session_id: str) -> list[dict[str, Any]]:
        """Every edit tool call in the session's whole transcript (name, path, counts)."""
        session = self.get(session_id)
        try:
            return await asyncio.to_thread(self._read_edits, session_id, session.record.history_directory)
        except Exception:
            logger.exception("Falha ao ler as edições da sessão %s", session_id)
            return []

    def reconcile_label_ids(self) -> None:
        """Make the in-memory labels match the database after `sessions` rows went away.

        Removing a project or a conversation whose file vanished deletes `session_labels`
        by cascade, behind this cache's back. Sessions whose labels changed are announced
        (when they still exist), so no screen keeps a label nobody applied.
        """
        try:
            with closing(db.connect(self._db_path)) as conn:
                fresh = labels.session_label_ids(conn)
        except sqlite3.Error:
            logger.exception("Falha ao ler as etiquetas das sessões")
            return
        stale = self._label_ids
        self._label_ids = fresh
        outside = []
        for session_id in stale.keys() | fresh.keys():
            if stale.get(session_id) == fresh.get(session_id):
                continue
            session = self._sessions.get(session_id)
            if session is None:
                outside.append(session_id)
            else:
                session.emit_updated()
        if outside:
            marks = ", ".join("?" * len(outside))
            with closing(db.connect(self._db_path)) as conn:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM sessions WHERE session_id IN ({marks})", outside
                ).fetchall()
            for row in rows:
                self._publish_closed_update(_record(row))

    def refresh_records(self, session_ids: set[str]) -> None:
        """Reload records changed by the history sync for sessions kept in memory."""
        # Only a session that has labels can leave a stale cache behind when its row goes.
        if not session_ids.isdisjoint(self._label_ids):
            self.reconcile_label_ids()
        cached = [self._sessions[sid] for sid in session_ids if sid in self._sessions]
        if not cached:
            return
        with closing(db.connect(self._db_path)) as conn:
            for session in cached:
                row = conn.execute(
                    f"SELECT {_COLUMNS} FROM sessions WHERE session_id = ?",
                    (session.session_id,),
                ).fetchone()
                if row is None:
                    continue
                fresh = _record(row)
                if fresh != session.record:
                    session.record = fresh
                    session.emit_updated()

    def remove_group(self, group_id: int) -> groups.Group:
        """Delete a group; its sessions become loose, and each gets a `session.updated`."""
        with closing(db.connect(self._db_path)) as conn:
            group, released = groups.delete_group(conn, group_id)
        self.announce_group_released(released)
        return group

    def announce_group_released(self, session_ids: list[str]) -> None:
        """Announce sessions whose group is gone (the database already dropped it).

        Loaded sessions drop it in memory; the others are read back and announced as closed."""
        outside = []
        for session_id in session_ids:
            session = self._sessions.get(session_id)
            if session is None:
                outside.append(session_id)
                continue
            session.record.group_id = None
            session.emit_updated()
        if outside:
            marks = ", ".join("?" * len(outside))
            with closing(db.connect(self._db_path)) as conn:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM sessions WHERE session_id IN ({marks})", outside
                ).fetchall()
            for row in rows:
                self._publish_closed_update(_record(row))

    async def set_labels(self, session_id: str, label_ids: list[int]) -> dict[str, Any]:
        """Make `label_ids` the labels of the session and announce it."""
        session = self.get(session_id)
        try:
            with closing(db.connect(self._db_path)) as conn:
                final = labels.set_session_labels(conn, session_id, label_ids)
        except sqlite3.IntegrityError as exc:
            # The session was deleted between the check above and the write.
            raise SessionNotFoundError("Sessão não encontrada.") from exc
        if final:
            self._label_ids[session_id] = final
        else:
            self._label_ids.pop(session_id, None)
        session.emit_updated()
        return session.summary()

    def remove_label(self, label_id: int) -> labels.Label:
        """Delete a label; every session that had it is announced without it."""
        with closing(db.connect(self._db_path)) as conn:
            label, released = labels.delete_label(conn, label_id)
        outside = []
        for session_id in released:
            remaining = [i for i in self._label_ids.get(session_id, []) if i != label_id]
            if remaining:
                self._label_ids[session_id] = remaining
            else:
                self._label_ids.pop(session_id, None)
            session = self._sessions.get(session_id)
            if session is None:
                outside.append(session_id)
            else:
                session.emit_updated()
        if outside:
            marks = ", ".join("?" * len(outside))
            with closing(db.connect(self._db_path)) as conn:
                rows = conn.execute(
                    f"SELECT {_COLUMNS} FROM sessions WHERE session_id IN ({marks})", outside
                ).fetchall()
            for row in rows:
                self._publish_closed_update(_record(row))
        return label

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Sessions whose title, summary, first prompt, group name or label slug contain `query`,
        then those whose messages do (with a `match` snippet), ignoring case and accents. Includes
        finished ones, not discarded ones; each group newest first, `limit` for both together."""
        needle = _strip_accents(" ".join(query.split()))
        if not needle:
            return []
        with closing(db.connect(self._db_path)) as conn:
            group_names = {group.id: group.name for group in groups.list_groups(conn)}
            label_slugs = {label.id: label.slug for label in labels.list_labels(conn)}
        by_content: dict[str, int] = {}
        if self._text_index is not None:
            try:
                by_content = self._text_index.matching(query)
            except Exception:
                # No message text in the log: only that the index failed.
                logger.exception("Falha ao procurar no conteúdo das conversas")
        by_metadata: list[dict[str, Any]] = []
        by_text: list[dict[str, Any]] = []
        for item in self.list_sessions():
            if item.get("mark") == "discarded":
                continue
            haystack = " ".join(
                [item.get(key) or "" for key in ("title", "summary", "first_prompt")]
                + [group_names.get(item.get("group_id"), "")]
                + [label_slugs.get(label_id, "") for label_id in item.get("label_ids", [])]
            )
            if needle in _strip_accents(haystack):
                by_metadata.append(item)
            elif item["session_id"] in by_content:
                by_text.append(item)
        result = [*by_metadata, *by_text][:limit]
        for item in result:
            rowid = by_content.get(item["session_id"])
            if rowid is None or self._text_index is None:
                continue
            try:
                match = self._text_index.match_for(query, rowid)
            except Exception:
                logger.exception("Falha ao montar o trecho da sessão %s", item["session_id"])
                continue
            if match is not None:
                item["match"] = asdict(match)
        return result

    def hidden_counts(self) -> dict[int, int]:
        """Per project, sessions finished by inactivity (not marked finished)."""
        counts: dict[int, int] = {}
        for item in self.list_sessions():
            if item["display_state"] == "finished" and not item["finished"]:
                counts[item["project_id"]] = counts.get(item["project_id"], 0) + 1
        return counts

    # Descriptions ------------------------------------------------------------

    def finished_after(self) -> float:
        """Seconds without activity after which a session counts as finished.

        `preferences.finished_after_days` in `app_state` overrides the default.
        """
        days = self._finished_after_days
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = 'preferences'").fetchone()
        if row is not None:
            try:
                value = json.loads(row["value"]).get("finished_after_days")
            except (ValueError, AttributeError):
                value = None
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
                days = float(value)
        return days * DAY_SECONDS

    async def _history_context(self, session: ActiveSession) -> dict[str, Any] | None:
        """Context of a session from its last assistant message in the history file.

        The file is read in a thread, once per modification of the history file
        (`file_modified_at`, bounded cache); a session whose file is not indexed
        yet is read every time. Only the snapshot calls this: listings, search
        and events never read history files.
        """
        record = session.record
        key = record.file_modified_at
        cached = self._history_contexts.get(record.session_id)
        if key is not None and cached is not None and cached[0] == key:
            self._history_contexts.move_to_end(record.session_id)
            found = cached[1]
        else:
            try:
                found = await asyncio.to_thread(self._read_context, record.session_id, record.history_directory)
            except Exception:
                logger.exception("Falha ao ler o contexto da sessão %s", record.session_id)
                found = None
            if key is not None:
                self._history_contexts[record.session_id] = (key, found)
                self._history_contexts.move_to_end(record.session_id)
                while len(self._history_contexts) > CONTEXT_CACHE_SIZE:
                    self._history_contexts.popitem(last=False)
        if found is None:
            return None
        return context_from_usage(
            found["used_tokens"], record.model, session.model_resolved, found.get("model")
        )

    def _extras(
        self, record: SessionRecord, active: ActiveSession | None = None
    ) -> dict[str, Any]:
        """In-memory fields of a session (context, pending prompt, last action, plan
        progress, CLI turn signal), for `describe`."""
        plan = self.plan_summary(record)
        cli_running = self._cli_running(record.session_id)
        short, plan_done = self._digest_briefs.get(record.session_id, (None, False))
        verdict, checked_at = self._closure_briefs.get(record.session_id, (None, None))
        if record.finished or checked_at is None or record.last_activity_at > checked_at:
            verdict = None
        if active is None:
            return {"context": None, "pending_permission": None, "last_action": None,
                    "pending_kind": None, "plan": plan, "cli_running": cli_running,
                    "digest_short": short, "plan_done": plan_done,
                    "closure_verdict": verdict, "subagents_running": False,
                    "label_ids": self._label_ids.get(record.session_id, [])}
        return {
            "context": active.context,
            "pending_permission": active.pending_permission,
            "last_action": active.last_action,
            "pending_kind": active.pending_kind,
            "plan": plan,
            "cli_running": cli_running,
            "digest_short": short,
            "plan_done": plan_done,
            "closure_verdict": verdict,
            "subagents_running": active.subagents_running,
            "label_ids": self._label_ids.get(record.session_id, []),
            "remote_state": active.remote_state,
            "remote_url": active.remote_url,
            "remote_error": active.remote_error,
        }

    def _load_digest_briefs(self) -> None:
        try:
            with closing(db.connect(self._db_path)) as conn:
                self._digest_briefs = digest_store.briefs(conn)
                self._closure_briefs = closure_briefs(conn)
        except sqlite3.Error:
            logger.exception("Falha ao ler os resumos do agente")

    def _load_label_ids(self) -> None:
        try:
            with closing(db.connect(self._db_path)) as conn:
                self._label_ids = labels.session_label_ids(conn)
        except sqlite3.Error:
            logger.exception("Falha ao ler as etiquetas das sessões")

    async def set_digest_brief(self, session_id: str, short: str | None, plan_done: bool) -> None:
        """The digest agent wrote a new summary: show its sentence and seal in the lists."""
        brief = (short, plan_done)
        if self._digest_briefs.get(session_id) == brief:
            return
        self._digest_briefs[session_id] = brief
        await self._announce_session(session_id)

    async def set_closure_brief(
        self, session_id: str, verdict: str | None, checked_at: int | None
    ) -> None:
        """The digest agent checked the session: show its closure verdict in the lists."""
        brief = (verdict, checked_at)
        if self._closure_briefs.get(session_id) == brief:
            return
        self._closure_briefs[session_id] = brief
        await self._announce_session(session_id)

    def _describe_active(self, session: ActiveSession) -> dict[str, Any]:
        return describe(
            session.record, session.state, session.error, session.seq,
            finished_after=self.finished_after(), effort_pending=session.effort_pending,
            model_resolved=session.model_resolved, **self._extras(session.record, session),
        )

    def describe_record(self, record: SessionRecord) -> dict[str, Any]:
        """A session without an active client (e.g. just created)."""
        return describe(
            record, "closed", None, 0, finished_after=self.finished_after(),
            **self._extras(record),
        )

    def summary(self, session_id: str) -> dict[str, Any]:
        return self.get(session_id).summary()

    def list_for_project(self, project_id: int) -> list[SessionSummary]:
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE project_id = ?"
                " ORDER BY last_activity_at DESC, created_at DESC",
                (project_id,),
            ).fetchall()
        summaries = []
        for row in rows:
            active = self._sessions.get(row["session_id"])
            if active is not None:
                summaries.append(SessionSummary(active.record, active.state, active.error))
            else:
                summaries.append(SessionSummary(_record(row), "closed", None))
        return summaries

    def list_sessions(
        self,
        *,
        project_id: int | None = None,
        display_state: str | None = None,
    ) -> list[dict[str, Any]]:
        """Sessions of every project (or one), newest activity first, with the current seq.

        The context is only the in-memory value of active sessions: no history file is read.
        """
        try:
            self.wake_marks()
        except Exception:
            logger.exception("Falha ao acordar sessões em espera")
        query = f"SELECT {_COLUMNS} FROM sessions"
        params: tuple[Any, ...] = ()
        if project_id is not None:
            query += " WHERE project_id = ?"
            params = (project_id,)
        query += " ORDER BY last_activity_at DESC, created_at DESC"
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(query, params).fetchall()
        finished_after = self.finished_after()
        now = time.time()
        result = []
        for row in rows:
            active = self._sessions.get(row["session_id"])
            if active is not None:
                item = describe(
                    active.record, active.state, active.error, active.seq,
                    finished_after=finished_after, now=now,
                    effort_pending=active.effort_pending,
                    model_resolved=active.model_resolved,
                    **self._extras(active.record, active),
                )
            else:
                record = _record(row)
                item = describe(record, "closed", None, 0,
                                finished_after=finished_after, now=now,
                                **self._extras(record))
            if display_state is None or item["display_state"] == display_state:
                result.append(item)
        return result

    # Plans -------------------------------------------------------------------

    def project_roots(self) -> list[Path]:
        """Folders of the registered projects."""
        with closing(db.connect(self._db_path)) as conn:
            return registered_project_roots(conn)

    def plan_summary(self, record: SessionRecord) -> dict[str, Any] | None:
        """Last known progress of the record's plan. Memory only: never reads a file."""
        if not record.plan_path:
            return None
        return self._plan_progress.get(record.plan_path)

    async def refresh_plan(self, session_id: str) -> bool:
        """Reread the session's plan (the file only when it changed) and announce a
        new progress. Returns whether the progress changed."""
        try:
            record = self.get(session_id).record
        except SessionNotFoundError:
            return False
        if not record.plan_path:
            return False
        return await self._refresh_plan_path(record.plan_path)

    async def _refresh_plan_path(self, path: str) -> bool:
        """Reread a plan file (only when it changed) and announce a new progress."""
        # One refresh per plan at a time: a read that started earlier must not
        # publish its older summary after a later one.
        async with self._plan_locks.setdefault(path, asyncio.Lock()):
            progress = await asyncio.to_thread(self.plan_cache.read, Path(path))
            summary = progress.summary(path) if progress is not None else None
            if path in self._plan_progress and self._plan_progress[path] == summary:
                return False
            self._plan_progress[path] = summary
        await self._emit_plan_change(path)
        return True

    async def _emit_plan_change(self, path: str) -> None:
        """`session.updated` for every unfinished session linked to this plan: the ones in
        memory and, from the database, the ones that are not."""
        for session in list(self._sessions.values()):
            if session.record.plan_path == path:
                session.emit_updated()
        rows = await asyncio.to_thread(self._unfinished_rows_for_plan, path)
        for row in rows:
            if row["session_id"] not in self._sessions:
                self._publish_closed_update(_record(row))

    def _unfinished_rows_for_plan(self, path: str) -> list[sqlite3.Row]:
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE plan_path = ? AND finished = 0", (path,)
            ).fetchall()

    def link_plan(
        self, session_id: str, path: str, *, source: Literal["auto", "manual"]
    ) -> bool:
        """Link a session to a plan file. The path must be a plan of a registered
        project. The automatic source never replaces a `manual` or `off` link.
        Returns whether the link changed."""
        if not Path(path).is_absolute():
            return False  # a relative path would resolve against the server's directory
        session = self.get(session_id)
        record = session.record
        if source == "auto" and record.plan_link in ("manual", "off"):
            return False
        resolved = is_plan_path(path, self.project_roots())
        if resolved is None:
            return False
        if record.plan_path == str(resolved) and record.plan_link == source:
            return False
        session.save(plan_path=str(resolved), plan_link=source)
        session.emit_updated()
        return True

    def unlink_plan(self, session_id: str) -> None:
        """Turn the plan off: no plan and no automatic link."""
        session = self.get(session_id)
        session.save(plan_path=None, plan_link="off")
        session.emit_updated()

    def auto_plan(self, session_id: str) -> None:
        """Back to the automatic link, keeping the current plan if any."""
        session = self.get(session_id)
        session.save(plan_link="auto")
        session.emit_updated()

    # Changes -----------------------------------------------------------------

    async def update(
        self,
        session_id: str,
        *,
        finished: bool | None = None,
        title: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        permission_mode: str | None = None,
        confirm_bypass: bool = False,
        group_id: int | None | EllipsisType = ...,
        mark: str | None | EllipsisType = ...,
        mark_note: str | None | EllipsisType = ...,
        mark_until: int | None | EllipsisType = ...,
        priority: bool | None = None,
        remote_control: bool | None = None,
    ) -> dict[str, Any]:
        """Finish, reopen, rename or change options (model, effort, permission mode).

        `group_id` moves the session to a group (of any project); `None` takes it out,
        `...` keeps it. `bypassPermissions` needs `confirm_bypass`. Emits `session.updated` when
        something changed, and `session.options` when an option changed. `mark`,
        `mark_note` and `mark_until` follow `resolve_mark`; finishing drops them and the
        priority, and marking a finished session reopens it. `remote_control` turns Remote
        Control on or off (`RemoteControlUnavailable` for a finished session that stays so).
        """
        session = self.get(session_id)
        if remote_control and (finished is True or (session.record.finished and finished is not False)):
            raise RemoteControlUnavailable(REMOTE_UNAVAILABLE_TEXT)
        if group_id is not ... and group_id is not None:
            with closing(db.connect(self._db_path)) as conn:
                groups.get_group(conn, group_id)
        if effort is not None and effort not in EFFORTS:
            raise InvalidDecisionError("Nível de raciocínio inválido.")
        if model is not None and not MODEL_PATTERN.match(model):
            raise InvalidDecisionError("Modelo inválido.")
        if permission_mode is not None and permission_mode not in PERMISSION_MODES:
            raise InvalidDecisionError("Modo de permissão inválido.")
        if (
            permission_mode is not None
            and permission_mode != "default"
            and session.record.agent_id is not None
        ):
            raise InvalidDecisionError(AGENT_MODE_TEXT)
        if (
            permission_mode == "bypassPermissions"
            and not confirm_bypass
            and session.record.permission_mode != "bypassPermissions"
        ):
            raise BypassNotConfirmedError(
                "Confirme que quer rodar sem perguntas antes de ativar este modo."
            )
        mark_changes = resolve_mark(
            session.record, mark=mark, mark_note=mark_note, mark_until=mark_until, now=_now()
        )
        options_changed = await session.set_options(
            model=model, effort=effort, permission_mode=permission_mode
        )
        changes: dict[str, Any] = {}
        if finished is not None and finished != session.record.finished:
            changes["finished"] = finished
        if finished is False and session.summary()["display_state"] == "finished":
            # Finished by inactivity: fresh activity brings it back.
            changes["finished"] = False
            changes["last_activity_at"] = _now()
        if title is not None:
            title = title.strip()
            if title and title != session.record.title:
                changes["title"] = title
                changes["title_custom"] = True
        if group_id is not ... and group_id != session.record.group_id:
            changes["group_id"] = group_id
        changes.update(mark_changes)
        if (
            "mark" in mark_changes
            and mark_changes["mark"] is None
            and finished is not True
            and _now() - session.record.last_activity_at > self.finished_after()
        ):
            # Taking off a long-standing mark must not finish the session by inactivity on the spot.
            changes["last_activity_at"] = _now()
        if priority is not None and priority != session.record.priority:
            changes["priority"] = priority
        if finished is True:
            # Finishing (even a session already finished) drops the mark and the priority.
            changes.update(mark=None, mark_note=None, mark_until=None, priority=False)
        elif (changes.get("mark") not in (None, "discarded") or changes.get("priority")) and finished is not True:
            # Marking a finished session reopens it, like "Reabrir". Discarding does not: it only hides.
            if session.record.finished:
                changes["finished"] = False
            if session.summary()["display_state"] == "finished":
                changes["last_activity_at"] = _now()
        if "finished" in changes:
            changes["finished_at"] = _now() if changes["finished"] else None
        if not changes:
            remote_changed = remote_control is not None and await session.set_remote_control(
                remote_control
            )
            if options_changed or remote_changed:
                session.emit_updated()
            return session.summary()
        try:
            session.save(**changes)
        except sqlite3.IntegrityError as exc:
            # The group was removed between the check and the write.
            raise groups.GroupNotFoundError("Agrupador não encontrado.") from exc
        if changes.get("finished") is True and self._on_finished is not None:
            # "Entregas": each open-to-finished passage becomes a delivery record.
            try:
                self._on_finished(session_id, changes["finished_at"])
            except Exception:
                logger.exception("Falha ao registrar a entrega da sessão %s", session_id)
        if "title" in changes:
            if await session.has_history():
                try:
                    await asyncio.to_thread(
                        self._rename_session, session_id, changes["title"], session.record.history_directory
                    )
                except Exception:
                    logger.exception("Falha ao renomear a sessão %s no SDK", session_id)
                    session.save(rename_pending=True)
                else:
                    if session.record.rename_pending:
                        session.save(rename_pending=False)
            else:
                # No conversation on disk yet: applied after the first turn.
                session.save(rename_pending=True)
        if finished is True or changes.get("mark") == "discarded":
            # Only finishing or discarding ends it (inactivity and "Em espera" do not).
            remote_control = False
        if remote_control is not None:
            # After the changes above: reopening and turning it on can come together.
            await session.set_remote_control(remote_control)
        session.emit_updated()
        return session.summary()

    async def mark_seen(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        session.save(last_seen_at=max(_now(), session.record.last_activity_at))
        session.emit_updated()
        return session.summary()

    async def mark_seen_many(self, session_ids: list[str]) -> int:
        """Mark each known session as seen (one `session.updated` each); unknown ids are skipped.

        One transaction in a worker thread, so a failure writes nothing and the
        event loop is not held by up to hundreds of updates.
        """
        now = _now()
        unique = list(dict.fromkeys(session_ids))
        # Memory may be ahead of the database (activity not yet saved): honour it too.
        marks = [
            (session_id, max(now, self._sessions[session_id].record.last_activity_at)
             if session_id in self._sessions else now)
            for session_id in unique
        ]
        # The thread hands back the value it really wrote per session, so memory
        # ends up equal to the database even if a `_touch()` ran meanwhile.
        write = asyncio.ensure_future(asyncio.to_thread(self._write_seen, marks))
        try:
            written = await asyncio.shield(write)
        except asyncio.CancelledError:
            # The transaction may still commit after the caller is gone (shutdown,
            # client disconnect): apply memory and events when the thread finishes,
            # without holding the cancellation back.
            write.add_done_callback(self._apply_seen_after_cancel)
            raise
        self._apply_seen(written)
        return len(written)

    def _apply_seen_after_cancel(self, write: "asyncio.Future[dict[str, int]]") -> None:
        if write.cancelled() or write.exception() is not None:
            return  # nothing committed (or the error was already the caller's to see)
        self._apply_seen(write.result())

    def _apply_seen(self, written: dict[str, int]) -> None:
        for session_id, seen_at in written.items():
            try:
                session = self.get(session_id)
            except SessionNotFoundError:
                continue  # removed while writing
            session.record.last_seen_at = seen_at
            session.emit_updated()

    def _write_seen(self, marks: list[tuple[str, int]]) -> dict[str, int]:
        """Set `last_seen_at` of every existing session in one transaction.

        Returns the value written per session found (`MAX(mark, last_activity_at)`
        as the database computed it).
        """
        written: dict[str, int] = {}
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            for session_id, mark in marks:
                row = conn.execute(
                    "UPDATE sessions SET last_seen_at = MAX(?, last_activity_at)"
                    " WHERE session_id = ? RETURNING last_seen_at",
                    (mark, session_id),
                ).fetchone()
                if row is not None:
                    written[session_id] = row[0]
        return written

    # Closing -----------------------------------------------------------------

    async def close_project(self, project_id: int) -> None:
        """Close and forget every active session of a project being removed."""
        targets = [
            (session_id, session) for session_id, session in list(self._sessions.items())
            if session.record.project_id == project_id
        ]
        for _session_id, session in targets:
            await session.close(final=True)
        # A send still connecting would otherwise leave its process behind.
        # One deadline for the whole project, the sessions waited in parallel.
        waits = [asyncio.create_task(session.wait_settled()) for _, session in targets]
        if waits:
            _done, pending = await asyncio.wait(waits, timeout=PROJECT_CLOSE_WAIT)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending)
                logger.warning(
                    "%d sessão(ões) ainda conectando ao remover o projeto %s",
                    len(pending), project_id,
                )
        for session_id, _session in targets:
            self._sessions.pop(session_id, None)

    def wake_marks(self, now: int | None = None) -> list[str]:
        """Sessions on hold whose wake time came: drop the mark, count the wake as fresh
        activity (unread, back in the queue) and announce each one. Returns their ids."""
        now = _now() if now is None else now
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT session_id FROM sessions"
                " WHERE mark = 'on_hold' AND mark_until IS NOT NULL AND mark_until <= ?"
                " ORDER BY mark_until",
                (now,),
            ).fetchall()
        woken: list[str] = []
        for row in rows:
            # One session failing must not hold back the ones after it (the sweep retries every minute).
            try:
                session = self.get(row["session_id"])
                record = session.record
                if record.mark != "on_hold" or record.mark_until is None or record.mark_until > now:
                    continue
                session.save(
                    mark=None, mark_until=None, last_activity_at=max(record.last_activity_at, now)
                )
                session.emit_updated()
            except SessionNotFoundError:
                continue
            except Exception:
                logger.exception("Falha ao acordar a sessão %s", row["session_id"])
                continue
            woken.append(record.session_id)
        return woken

    async def close_idle(self) -> None:
        """Close clients idle longer than the timeout. They resume on the next message."""
        now = time.monotonic()
        for session in list(self._sessions.values()):
            # A subagent that outlived its limit has its card stopped and stops counting:
            # tell the clients, so the session stops showing as running.
            session.sync_subagents()
            if session.foreign_pending and session.idle_client_only:
                await session.release_for_external()
                continue
            if (
                session.state == "idle"
                and not session.busy
                and not session.subagents_running
                and session.idle_since is not None
                and now - session.idle_since >= self._idle_timeout
                # Closing would end the access from the phone while the user is away.
                and not session.record.remote_control
            ):
                logger.info("Sessão %s ociosa; fechando o cliente", session.session_id)
                await session.close()
        self.forget_closed()

    def forget_closed(self) -> None:
        """Drop from memory sessions that are closed and not in use."""
        for session_id, session in list(self._sessions.items()):
            if session.forgettable:
                self._forgotten[session_id] = (
                    session.seq, session._has_connected or session._connected_before,
                    session._app_activity_at, session._loaded_mtime,
                )
                if session.last_breakdown is not None and session.last_breakdown_at is not None:
                    self._kept_breakdowns[session_id] = (
                        session.last_breakdown, session.last_breakdown_at,
                    )
                    self._kept_breakdowns.move_to_end(session_id)
                    while len(self._kept_breakdowns) > KEPT_BREAKDOWN_LIMIT:
                        self._kept_breakdowns.popitem(last=False)
                del self._sessions[session_id]

    def app_writing(self, session_id: str) -> bool:
        """The app has a client, a turn or an operation on this session's file."""
        session = self._sessions.get(session_id)
        return session is not None and (
            session.active or session.pending_turns > 0 or bool(session.prompts) or session.busy
        )

    async def release_if_foreign(self, session_id: str, lines: list[str]) -> bool:
        """`lines` (new lines of the session's file) hold a reply written by another
        process: with only an idle client the app releases it. With a client that is
        busy (a turn, a prompt, background work) the reply is remembered in
        `foreign_pending`, to release the client once it can."""
        session = self._sessions.get(session_id)
        if session is None or session.client is None:
            return False
        found = foreign_reply_uuids(lines, session.own_uuids, session.client_since)
        if not found:
            return False
        if not session.idle_client_only:
            if found - session.foreign_candidates:
                logger.info(
                    "Sessão %s alterada por outro processo com o app ocupado; soltura adiada",
                    session_id,
                )
            session.foreign_candidates |= found
            return False
        return await session.release_for_external()

    async def apply_external_change(self, session_id: str, *, reload: bool = True) -> bool:
        """The CLI changed a session's file (its row is already updated): refresh
        the record, announce it and, with `reload`, reload an open column.

        Emits nothing while the app is writing the session. Returns whether a
        reload was attempted.
        """
        if self.app_writing(session_id):
            return False
        with closing(db.connect(self._db_path)) as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return False
        record = _record(row)
        session = self._sessions.get(session_id)
        if session is None:
            forgotten = self._forgotten.get(session_id)
            seq = self._publish_closed_update(record)
            if forgotten is None or not reload:
                return False
            # Forgotten from memory, but a column may still show it: it drops what
            # it shows and fetches the snapshot again (which reloads from disk).
            seq += 1
            self._forgotten[session_id] = (seq, *forgotten[1:])
            self._publish(
                {"session_id": session_id, "seq": seq, "type": "conversation.reset", "data": {}}
            )
            return True
        session.record = record
        session.emit_updated()
        # An open() in progress reloads by itself.
        if not reload or session.users > 0:
            return False
        # Emits `conversation.reset` and reloads when the file changed since the last load.
        await session.reload_if_modified()
        return True

    def _publish_closed_update(self, record: SessionRecord) -> int:
        """`session.updated` of a session that is not in memory (no client). Returns
        the seq it went out with."""
        forgotten = self._forgotten.get(record.session_id)
        seq = forgotten[0] if forgotten is not None else 0
        data = describe(
            record, "closed", None, seq, finished_after=self.finished_after(),
            **self._extras(record),
        )
        self._publish(
            {"session_id": record.session_id, "seq": seq, "type": "session.updated", "data": data}
        )
        return seq

    # CLI turns ---------------------------------------------------------------

    def note_cli_turn(self, session_id: str, *, open: bool, activity_at: float) -> None:
        """The CLI watcher read the end of a session file: the turn is `open` or not, and
        `activity_at` (epoch seconds) is the latest write of the file or of a subagent
        file. The caller announces the session afterwards."""
        if not open:
            self._cli_turns.pop(session_id, None)
            return
        turn = _CliTurn(activity_at, False)
        self._cli_turns[session_id] = turn
        turn.announced = self._turn_running(turn)

    def forget_cli_turn(self, session_id: str) -> None:
        """The app took over the session (or its file is gone): no CLI signal."""
        self._cli_turns.pop(session_id, None)

    def cli_activity_is_fresh(self, activity_at: float) -> bool:
        """A write at `activity_at` (epoch seconds) is at most `CLI_TURN_STALE_SECONDS` old,
        by the manager's own wall clock."""
        return self._clock() - activity_at <= CLI_TURN_STALE_SECONDS

    def _turn_running(self, turn: _CliTurn) -> bool:
        return self.cli_activity_is_fresh(turn.activity_at)

    def _cli_running(self, session_id: str) -> bool:
        """The session's CLI is mid-turn and wrote within `CLI_TURN_STALE_SECONDS`.
        `describe` only reports it for sessions without a client."""
        turn = self._cli_turns.get(session_id)
        return turn is not None and self._turn_running(turn)

    async def _announce_session(self, session_id: str) -> None:
        """`session.updated` for a session without a client, in memory or not."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.emit_updated()
            return
        row = await asyncio.to_thread(self._read_row, session_id)
        if row is not None:
            self._publish_closed_update(_record(row))

    def _read_row(self, session_id: str) -> sqlite3.Row | None:
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                f"SELECT {_COLUMNS} FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()

    async def sweep_cli_turns(self) -> None:
        """Announce the signals that expired since the last round, so a CLI that died in
        the middle of a turn stops showing as running. One failure does not stop the rest."""
        for session_id, turn in list(self._cli_turns.items()):
            if self._turn_running(turn):
                continue
            if self._cli_turns.get(session_id) is turn:
                del self._cli_turns[session_id]
            if not turn.announced:
                continue  # clients were never told it was running
            try:
                await self._announce_session(session_id)
            except Exception:
                logger.exception("Falha ao anunciar o fim do turno do CLI da sessão %s", session_id)

    def in_use(self, session_id: str) -> bool:
        """The app is using the session (client, prompts, turns or an operation)."""
        session = self._sessions.get(session_id)
        return session is not None and not session.forgettable

    def _plan_link_rows(self) -> list[sqlite3.Row]:
        """Sessions linked to a plan and not finished by the user. Database only: it runs
        in a thread, so it must not touch anything the event loop owns."""
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                "SELECT session_id, plan_path, last_activity_at FROM sessions"
                " WHERE plan_path IS NOT NULL AND finished = 0"
            ).fetchall()

    def _sweepable_plan_paths(self, rows: list[sqlite3.Row]) -> list[str]:
        """Plans of sessions not finished (by the user or by inactivity), each once.
        Runs in the event loop: it reads the sessions in memory."""
        cutoff = time.time() - self.finished_after()
        paths: dict[str, None] = {}
        for row in rows:
            active = self._sessions.get(row["session_id"])
            busy = active is not None and active.state != "closed"
            if busy or row["last_activity_at"] >= cutoff:
                paths[row["plan_path"]] = None
        return list(paths)

    async def sweep_plans(self) -> None:
        """One round: reread each plan of an unfinished session once. A plan that
        fails is logged and does not stop the others."""
        rows = await asyncio.to_thread(self._plan_link_rows)
        for path in self._sweepable_plan_paths(rows):
            try:
                await self._refresh_plan_path(path)
            except Exception:
                logger.exception("Falha ao atualizar o plano %s", path)

    async def run_plan_sweep(
        self, interval: float, sleep: Callable[[float], Any] = asyncio.sleep
    ) -> None:
        """At startup and every `interval` seconds, refresh the progress of plans linked
        to unfinished sessions (file reads happen outside the event loop) and announce
        the CLI turn signals that expired."""
        while True:
            try:
                await self.sweep_plans()
            except Exception:
                logger.exception("Falha na varredura de planos")
            try:
                await self.sweep_cli_turns()
            except Exception:
                logger.exception("Falha na varredura dos turnos do CLI")
            await sleep(interval)

    async def run_idle_sweep(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.close_idle()
            except Exception:
                logger.exception("Falha na varredura de sessões ociosas")
            try:
                self.wake_marks()
            except Exception:
                logger.exception("Falha ao acordar sessões em espera")

    async def shutdown(self) -> None:
        # Temporary measurement processes go away with the app (the task closes its client).
        probes = [probe.task for probe in self._probes.values() if probe.task is not None]
        for task in probes:
            task.cancel()
        if probes:
            await asyncio.wait(probes)
        for session in list(self._sessions.values()):
            await session.detach()

    async def reconnect_remote_sessions(
        self, held: Collection[str] | None = frozenset()
    ) -> None:
        """Startup, after `reattach_all`: connect each session marked for Remote Control
        that is open and has no process (the machine rebooted, the agentd was gone), so it
        shows in the phone again. A few at a time; one failing never stops the others.

        `held` is what `reattach_all` returned: the sessions whose process the agentd may
        still hold. Those are skipped, and with `None` (the agentd could not be asked)
        nothing is connected: a `--resume` next to a process that is still alive would put
        two on the same conversation. Without the argument nothing is held."""
        if held is None:
            logger.warning("Remote Control não religado: o agentd não pôde ser consultado")
            return
        self._agentd_held.update(held)
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute(
                "SELECT s.session_id FROM sessions s JOIN projects p ON p.id = s.project_id"
                " WHERE s.remote_control = 1 AND s.finished = 0"
                " AND (s.mark IS NULL OR s.mark != 'discarded') ORDER BY s.last_activity_at DESC"
            ).fetchall()
        gate = asyncio.Semaphore(REMOTE_STARTUP_PARALLEL)

        async def one(session_id: str) -> None:
            if session_id in held:
                logger.warning(
                    "Remote Control da sessão %s não religado: o agentd ainda segura o processo",
                    session_id,
                )
                return
            async with gate:
                try:
                    session = self.get(session_id)
                    if not session._automatic_remote_allowed():
                        return
                    if session.client is None and not session.active:
                        await session.reconnect_remote()
                except SessionNotFoundError:
                    return
                except Exception:
                    logger.exception("Falha ao religar o Remote Control da sessão %s", session_id)

        await asyncio.gather(*(one(row["session_id"]) for row in rows))

    async def reattach_all(self) -> set[str] | None:
        """Startup: attach to every session the agentd kept running. Never raises: a
        child that does not attach in time is killed and its session closed.

        Returns the sessions whose process may still be alive in the agentd (a kill that
        failed), or `None` when the agentd could not be asked what it holds. Nothing held
        (no agentd, or none running) is an empty set. Whoever opens processes at startup
        (`reconnect_remote_sessions`) needs it: a second process on the same conversation
        writes to the same file."""
        if self._agentd is None:
            return set()
        try:
            children = await asyncio.wait_for(self._agentd.list(), REATTACH_TOTAL_TIMEOUT)
        except AgentdUnavailable:
            logger.info("Nenhum agentd rodando; nada a religar")
            return set()
        except Exception as error:  # includes TimeoutError
            logger.warning("Não foi possível listar as sessões do agentd: %r", error)
            return None
        held: set[str] = set()
        if not children:
            return held  # asyncio.wait below refuses an empty set

        async def kill(child: Any) -> None:
            try:
                await asyncio.wait_for(self._agentd.kill(child.id), KILL_TIMEOUT)
            except Exception as error:
                logger.warning("Falha ao encerrar o processo da sessão %s: %r",
                               child.session_id, error)
                if child.exit_code is None:
                    held.add(child.session_id)

        # Two live children for one session (a leftover of a failed kill): keep the one
        # that has produced the most, kill the rest. Attaching both would replace a client.
        newest: dict[str, Any] = {}
        for child in children:
            if child.exit_code is None:
                best = newest.get(child.session_id)
                if best is None or child.next_pos >= best.next_pos:
                    newest[child.session_id] = child
        extra = {c.id for c in children if c.exit_code is None
                 and newest[c.session_id].id != c.id}

        async def one(child: Any) -> None:
            try:
                known = self._read_row(child.session_id) is not None
                session = self.get(child.session_id) if known else None
            except Exception as error:
                # Leaving it alone would keep an unattached process for the session.
                logger.warning("Falha ao ler a sessão %s: %r", child.session_id, error)
                await kill(child)
                return
            if session is None or child.exit_code is not None or child.id in extra:
                if session is not None and child.exit_code is not None:
                    session.note_child_exit(child.stderr)
                await kill(child)
                return
            try:
                attached = await asyncio.wait_for(session.reattach(child), REATTACH_TIMEOUT)
            except Exception as error:  # includes TimeoutError
                logger.warning("Falha ao religar a sessão %s: %r", child.session_id, error)
                attached = False
            if not attached:
                await kill(child)

        tasks = {asyncio.create_task(one(child)): child for child in children}
        _done, pending = await asyncio.wait(tasks, timeout=REATTACH_TOTAL_TIMEOUT)
        for task in pending:
            task.cancel()  # the session disposes its half-made client
        if pending:
            await asyncio.wait(pending)
            logger.warning("Tempo esgotado ao religar %d sessão(ões)", len(pending))
            for task in pending:
                await kill(tasks[task])
        for task, child in tasks.items():
            if task not in pending and not task.cancelled() and task.exception() is not None:
                logger.warning("Falha ao religar a sessão %s: %r", child.session_id,
                               task.exception())
                if child.exit_code is None:
                    held.add(child.session_id)  # unknown what became of the process
        return held
