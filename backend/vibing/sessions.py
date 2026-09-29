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
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    ToolPermissionContext,
)

from vibing import db
from vibing import history as history_module
from vibing.agent.base import AgentClient, AgentError, AgentFactory, AgentOptions
from vibing.config import read_user_claude_settings
from vibing.conversation import ConversationBuilder, Event, cap_items, rate_limit_text
from vibing.projects import Project

logger = logging.getLogger(__name__)

DEFAULT_TITLE = history_module.DEFAULT_APP_TITLE
TITLE_MAX_LENGTH = 80
DENY_MESSAGE = "O usuário recusou."
CANCELLED_MESSAGE = "O pedido foi cancelado."

SessionState = Literal["closed", "connecting", "running", "awaiting_decision", "idle", "error"]
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
DEFAULT_MODEL_VALUE = "default"
MODEL_FIELDS = ("value", "displayName", "description", "supportsEffort", "supportedEffortLevels")
# The stored models list is asked again after this long (3 times a day).
MODELS_MAX_AGE = 8 * 3600
MODELS_CACHE_KEY = "models_cache"
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
DISPLAY_STATES: tuple[str, ...] = ("running", "waiting", "finished")

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
# Size of the items of a snapshot (JSON); older items beyond it are left out.
SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024
# A file written this long after the app's own last write still counts as the app's.
APP_WRITE_TOLERANCE = 2  # seconds
# How long removing a project waits for a send or connect still running.
PROJECT_CLOSE_WAIT = 30.0  # seconds
DEFAULT_FINISHED_AFTER_DAYS = 3.0
DAY_SECONDS = 86_400
# Context window of a model; ids ending in "[1m]" have the large one.
DEFAULT_CONTEXT_WINDOW = 200_000
LARGE_CONTEXT_WINDOW = 1_000_000
# How long the end of a turn waits for `get_context_usage()`.
CONTEXT_USAGE_TIMEOUT = 2.0  # seconds
# Entries of the cache of contexts read from history files.
CONTEXT_CACHE_SIZE = 512
PERMISSION_SUMMARY_MAX = 200  # characters
# read_context(session_id, directory): {used_tokens, model} of the last assistant message.
ReadContext = Callable[[str, str], dict[str, Any] | None]


# Errors --------------------------------------------------------------------


class SessionError(Exception):
    """Base error. The message is shown to the user."""


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
    + ", model, effort, permission_mode"
)
# Record fields kept out of what the frontend receives.
_INTERNAL_FIELDS = ("title_custom", "rename_pending", "file_modified_at", "app_modified_at")
_BOOL_FIELDS = ("finished", "title_custom", "rename_pending")


def _record(row: sqlite3.Row) -> SessionRecord:
    fields = {key: row[key] for key in row.keys()}
    for key in _BOOL_FIELDS:
        fields[key] = bool(fields[key])
    return SessionRecord(**fields)


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
) -> DisplayState:
    """State shown to the user: running, waiting for them, or finished.

    `finished_after` is in seconds: a session without activity for longer counts
    as finished. A pending decision always waits for the user.
    """
    if state in ("connecting", "running"):
        return "running"
    if state == "awaiting_decision":
        return "waiting"
    if finished or now - last_activity_at > finished_after:
        return "finished"
    return "waiting"


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
    percentage = usage.get("percentage")
    if isinstance(percentage, int | float) and not isinstance(percentage, bool):
        percent = round(min(max(float(percentage), 0.0), 100.0), 1)
    else:
        percent = _percent(used, limit)
    return {"used_tokens": used, "max_tokens": limit, "percent": percent}


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
) -> dict[str, Any]:
    """Session as sent to the frontend by listings, PATCH and `session.updated`."""
    now = time.time() if now is None else now
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
        ),
        "unread": record.last_activity_at > (record.last_seen_at or 0),
        "awaiting_decision": state == "awaiting_decision",
        "effort_pending": effort_pending,
        "model_resolved": model_resolved,
        "context": context,
        "pending_permission": pending_permission,
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


def user_default_permission_mode() -> str | None:
    """`permissions.defaultMode` of the user's CLI settings, used by new sessions.

    The SDK does not inherit it (verified with `auto`). Unknown values are
    ignored, and so is `bypassPermissions`: the app only enables it after an
    explicit confirmation.
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
    from vibing.agent.sdk_client import SdkAgentClient

    return SdkAgentClient(options)


def _now() -> int:
    return int(time.time())


async def _deny_all(
    tool_name: str, tool_input: dict[str, Any], context: Any
) -> PermissionResultDeny:
    """Permission callback of the throwaway client that only lists the models."""
    return PermissionResultDeny(message="Cliente só de consulta.")


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
        on_turn_end: Callable[[int], None] | None = None,
        on_connected: Callable[[AgentClient], Any] | None = None,
        read_transcript: history_module.ReadTranscript | None = None,
    ) -> None:
        self.record = record
        self._read_transcript = read_transcript
        # The last load failed: the next open tries again.
        self._history_failed = False
        self._on_turn_end = on_turn_end
        # Awaited after each successful connect (the manager caches the models).
        self._on_connected = on_connected
        # A new effort waits for a reconnect between turns.
        self.effort_pending = False
        # Context usage read from the connected client at the end of each turn.
        self.context: dict[str, Any] | None = None
        # Model id the CLI resolved (from the last init); not saved.
        self.model_resolved: str | None = None
        self._effort_task: asyncio.Task[None] | None = None
        # A turn the CLI opened by itself (no send pending) is running.
        self._autonomous_turn = False
        self.builder = ConversationBuilder()
        self.pending_turns = 0
        self.prompts: dict[str, PendingPrompt] = {}
        self.client: AgentClient | None = None
        self.error: str | None = None
        self.seq = 0

        self._db_path = db_path
        self._publish = publish
        self._agent_factory = agent_factory
        self._history_exists = history_exists
        self._connecting = False
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._sent_messages = 0
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
        # Modification time of the session file at the last load (None: unknown).
        self._loaded_mtime: float | None = None
        # Operations of the manager in progress (open, send): not forgotten meanwhile.
        self.users = 0
        # Wall time of the app's own last activity in this session (seconds).
        self._app_activity_at = 0.0

    @property
    def session_id(self) -> str:
        return self.record.session_id

    # State -----------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        if self._connecting:
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
    def subagents_running(self) -> bool:
        """A subagent (usually in the background) is still running in the client."""
        return self.builder.subagents_running

    @property
    def busy(self) -> bool:
        """A send or connect holds the lock."""
        return self._lock.locked()

    def _refresh_state(self) -> None:
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
        )

    async def _current_mtime(self) -> float | None:
        if self._file_mtime is None:
            return None
        try:
            return await asyncio.to_thread(self._file_mtime, self.session_id, self.record.cwd)
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

    async def ensure_history(self) -> None:
        """Load the saved conversation once, before anything else is shown or sent.

        Only the last `history_limit` messages are kept (`history_truncated`).
        No client is created. A failed load leaves a warning and is tried again
        on the next call.
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
            entries, tool_results, skipped, compact = loaded
            self._history_failed = False
            if len(entries) > self._history_limit:
                self.history_truncated = True
                entries = entries[-self._history_limit:]
            self.builder.load_history(entries, tool_results, compact)
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
    ) -> tuple[list[Any], dict[str, dict[str, Any]], int, set[str]]:
        """(entries, tool results, skipped lines, compact summary uuids)."""
        if self._read_transcript is not None:
            transcript = await asyncio.to_thread(
                self._read_transcript, self.session_id, self.record.cwd
            )
            if transcript is None:
                return [], {}, 0, set()
            return (
                list(transcript.messages), transcript.tool_results,
                transcript.skipped_lines, set(transcript.compact_uuids),
            )
        assert self._get_session_messages is not None
        entries = list(
            await asyncio.to_thread(self._get_session_messages, self.session_id, self.record.cwd)
            or []
        )
        tool_results: dict[str, dict[str, Any]] = {}
        if self._read_tool_results is not None and entries:
            try:
                tool_results = await asyncio.to_thread(
                    self._read_tool_results, self.session_id, self.record.cwd
                )
            except Exception:
                logger.exception(
                    "Falha ao ler os resultados de ferramentas da sessão %s", self.session_id
                )
        return entries, tool_results, 0, set()

    async def _apply_pending_rename(self) -> None:
        """Write a title chosen before the conversation existed on disk."""
        if not self.record.rename_pending or self._rename_session is None:
            return
        try:
            await asyncio.to_thread(
                self._rename_session, self.session_id, self.record.title, self.record.cwd
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
        )

    def emit_updated(self) -> None:
        data = self.summary()
        data["seq"] = self.seq + 1  # the seq of this very event
        self._emit("session.updated", data)

    def save(self, **changes: Any) -> None:
        """Write record fields to the database and memory."""
        assignments = ", ".join(f"{column} = ?" for column in changes)
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                (*changes.values(), self.session_id),
            )
        for key, value in changes.items():
            setattr(self.record, key, value)

    async def has_history(self) -> bool:
        return self._has_connected or await self._check_history()

    # Sending ---------------------------------------------------------------

    async def send(self, text: str, images: list[dict[str, Any]] | None = None) -> None:
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
        self._emit_events(self.builder.add_user_message(text, markers))
        self._touch()
        if self.record.finished:
            self.save(finished=False)
        self.emit_updated()
        first = self._sent_messages == 0
        self._sent_messages += 1
        if first and self.record.title == DEFAULT_TITLE:
            self._set_title(text)

        async with self._lock:
            # A close still disposing of the old client must finish first, or
            # two processes would run the same session.
            await self._wait_disposal()
            if self._final:
                return
            if self.client is None and not await self._connect():
                return
            # A new effort still pending is applied before this turn.
            if not await self._reconnect_for_effort():
                return
            client = self.client
            assert client is not None
            self.pending_turns += 1
            self._refresh_state()
            content: str | list[dict[str, Any]] = text
            if images:
                content = [{"type": "text", "text": text}] if text.strip() else []
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
                await client.send(content)
            except AgentError as error:
                # If close() discarded this client meanwhile, the error is expected.
                if self.client is client:
                    await self._fail(error.message_pt)

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

    async def _connect(self) -> bool:
        """Create and connect a client. Called with the lock held.

        `resume` comes from memory (connected before) or from the disk check.
        A fresh connect that fails is retried once with `resume=True` when the
        error says the session is in use or the history now shows up.
        """
        generation = self._generation
        self._connecting = True
        self.error = None
        self._refresh_state()
        client: AgentClient | None = None
        try:
            if not Path(self.record.cwd).is_dir():
                raise AgentError(f"A pasta do projeto não existe mais: {self.record.cwd}")
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
        except asyncio.CancelledError:
            self._connecting = False
            if client is not None:
                # Tracked in `_disposal`: a later send or forget waits for it
                # even if this task is cancelled again.
                with suppress(asyncio.CancelledError):
                    await self._dispose(client, None)
            self._refresh_state()
            raise
        except Exception as error:  # AgentError or anything unexpected
            self._connecting = False
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
            await self._fail(message, client)
            return False
        self._connecting = False
        if generation != self._generation:
            # close() ran while connecting: discard the new client.
            await self._dispose(client, None)
            self._refresh_state()
            return False
        self.client = client
        self._has_connected = True
        self._reader = asyncio.create_task(self._read(client))
        if not await self._reconcile_options(client, options):
            return False
        if self._on_connected is not None:
            try:
                await self._on_connected(client)
            except Exception:
                logger.exception("Falha após conectar a sessão %s", self.session_id)
        return True

    def _client_options(self) -> tuple[str | None, str | None]:
        return self.record.model, self.record.permission_mode

    async def _reconcile_options(
        self, client: AgentClient, used: tuple[str | None, str | None]
    ) -> bool:
        """Model or mode changed while connecting: apply them live now.
        Returns False when the client failed meanwhile."""
        model, mode = self.record.model, self.record.permission_mode
        try:
            if model != used[0]:
                self.builder.expect_local_echo(f"Set model to {model}")
                await client.set_model(None if model in (None, DEFAULT_MODEL_VALUE) else model)
            if mode != used[1] and mode is not None:
                await client.set_permission_mode(mode)
        except AgentError as error:
            if self.client is client:
                await self._fail(error.message_pt)
            return False
        return True

    def _new_client(self, resume: bool) -> AgentClient:
        model = self.record.model
        return self._agent_factory(
            AgentOptions(
                cwd=Path(self.record.cwd),
                session_id=self.session_id,
                resume=resume,
                can_use_tool=self._can_use_tool,
                model=None if model == DEFAULT_MODEL_VALUE else model,
                effort=self.record.effort,
                permission_mode=self.record.permission_mode,
            )
        )

    async def _check_history(self) -> bool:
        try:
            return await asyncio.to_thread(
                self._history_exists, self.session_id, self.record.cwd
            )
        except Exception:
            logger.exception("Falha ao consultar o histórico da sessão %s", self.session_id)
            return False

    async def _read(self, client: AgentClient) -> None:
        try:
            async for message in client.messages():
                if self.pending_turns == 0 and self._starts_turn(message):
                    # The CLI opened a turn by itself (a background subagent finished).
                    self._autonomous_turn = True
                self._emit_events(self.builder.handle(message))
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
                if isinstance(message, ResultMessage):
                    # Before the turn counts as over, so the state does not flicker to idle.
                    await self._refresh_context(client)
                    # An autonomous turn may also have answered a message sent meanwhile.
                    self._autonomous_turn = False
                    self.pending_turns = max(0, self.pending_turns - 1)
                    self._touch()
                    self.emit_updated()
                    # The conversation is on disk after the first turn.
                    await self._apply_pending_rename()
                    if self._on_turn_end is not None:
                        self._on_turn_end(self.record.project_id)
                    # Last: the reconnect it may start cancels this reader.
                    self._schedule_effort()
                self._refresh_state()
                if isinstance(message, ResultMessage):
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

    async def _refresh_context(self, client: AgentClient) -> None:
        """Read the context usage from the client; a failure keeps the last value."""
        try:
            usage = await asyncio.wait_for(client.get_context_usage(), CONTEXT_USAGE_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Falha ao ler o uso de contexto da sessão %s", self.session_id, exc_info=True
            )
            return
        context = context_from_sdk(usage)
        if context is not None and self.client is client:
            self.context = context

    @staticmethod
    def _starts_turn(message: Any) -> bool:
        # Not the init: it also arrives right after connecting, outside any turn.
        return (
            isinstance(message, StreamEvent)
            and message.parent_tool_use_id is None
            and message.event.get("type") == "message_start"
        )

    # Options ---------------------------------------------------------------

    def options(self) -> dict[str, Any]:
        return {
            "model": self.record.model,
            "effort": self.record.effort,
            "permission_mode": self.record.permission_mode,
            "effort_pending": self.effort_pending,
            "model_resolved": self.model_resolved,
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
        if init.permission_mode and init.permission_mode != self.record.permission_mode:
            changes["permission_mode"] = init.permission_mode
        if changes:
            self.save(**changes)
        if changes or emit:
            self._emit_options()

    async def set_options(
        self,
        *,
        model: str | None = None,
        effort: str | None = None,
        permission_mode: str | None = None,
    ) -> bool:
        """Save new options and apply them to the client, if any. Returns True when
        something changed. Model and mode change live; effort needs a reconnect,
        done now if no turn is running, otherwise when the turn ends."""
        changes: dict[str, Any] = {}
        if model is not None and model != self.record.model:
            changes["model"] = model
        if effort is not None and effort != self.record.effort:
            changes["effort"] = effort
        if permission_mode is not None and permission_mode != self.record.permission_mode:
            changes["permission_mode"] = permission_mode
        if not changes:
            return False
        self.save(**changes)
        client = self.client
        if client is not None or self._connecting:
            if "effort" in changes:
                self.effort_pending = True
        self._emit_options()
        if client is not None:
            try:
                if "model" in changes:
                    self.builder.expect_local_echo(f"Set model to {model}")
                    await client.set_model(None if model == DEFAULT_MODEL_VALUE else model)
                if "permission_mode" in changes:
                    # Verified with the real SDK: this one sends no echo.
                    await client.set_permission_mode(changes["permission_mode"])
            except AgentError as error:
                if self.client is client:
                    await self._fail(error.message_pt)
                return True
        self._schedule_effort()
        return True

    def _schedule_effort(self) -> None:
        """Reconnect with the new effort once the session is between turns."""
        if (
            not self.effort_pending
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

    async def _reconnect_for_effort(self) -> bool:
        """With the lock held: replace the client by one resumed with the new
        effort. Returns False when the session ended up without a client."""
        if not self.effort_pending:
            return True
        if self.client is None:
            self.effort_pending = False
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
        self._emit_events(self.builder.stop_running_subagents())
        await self._dispose(client, reader)
        if self._final or generation != self._generation:
            # close() ran meanwhile: no new client.
            self.effort_pending = False
            return False
        connected = await self._connect()
        self.effort_pending = False
        self._emit_options()
        self._refresh_state()
        return connected

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

    async def _stop_subagents(self, client: AgentClient) -> None:
        # A task that cannot be stopped (e.g. it just ended) must not end the
        # session: logged, and the others are still stopped.
        for task_id in self.builder.running_task_ids():
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
        self._autonomous_turn = False
        self.builder.clear_local_echo()
        self._emit_events(self.builder.close_open_items())
        self._emit_events(self.builder.stop_running_subagents())
        if notice:
            self._emit_events(self.builder.add_notice("error", message))
        self._cancel_prompts()
        self._refresh_state()
        await self._dispose(client, reader)
        if client is not None:
            await self._record_app_mtime()

    async def close(self, *, final: bool = False) -> None:
        """Close the client, if any. The session goes back to `closed`.

        An in-flight send or connect notices it through `_generation` and stops
        without touching the discarded client. With `final`, later sends are refused.
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
        client, reader = self.client, self._reader
        self._generation += 1
        self.client = None
        self._reader = None
        self.pending_turns = 0
        self._autonomous_turn = False
        self.builder.clear_local_echo()
        if client is not None:
            self._emit_events(self.builder.stop_running_subagents())
        self._cancel_prompts()
        self._refresh_state()
        await self._dispose(client, reader)
        if client is not None:
            await self._record_app_mtime()

    async def wait_settled(self) -> None:
        """Wait for a send or connect still holding the lock and for any disposal."""
        async with self._lock:
            pass
        await self._wait_disposal()

    async def _close_quietly(self, client: AgentClient) -> None:
        try:
            await client.close()
        except Exception:
            logger.exception("Falha ao fechar o cliente da sessão %s", self.session_id)

    async def _wait_disposal(self) -> None:
        disposal = self._disposal
        if disposal is not None and disposal is not asyncio.current_task():
            await asyncio.wait([disposal])

    async def _dispose(
        self, client: AgentClient | None, reader: asyncio.Task[None] | None
    ) -> None:
        if reader is asyncio.current_task():
            reader = None  # the reader is failing itself: it must not be cancelled
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
        before = self.pending_permission
        self.prompts[prompt.prompt_id] = prompt
        self._emit("prompt.request", prompt.to_dict())
        self._refresh_state()
        self._emit_pending_change(before)
        try:
            return await prompt.future
        except asyncio.CancelledError:
            # The SDK cancels this task when the turn is interrupted.
            before = self.pending_permission
            if self.prompts.pop(prompt.prompt_id, None) is not None:
                self._emit_resolved(prompt.prompt_id, "cancelled")
                self._refresh_state()
                self._emit_pending_change(before)
            raise

    def _emit_pending_change(self, before: dict[str, Any] | None) -> None:
        """Update the summary when the pending permission it shows changed."""
        if self.pending_permission != before:
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
        before = self.pending_permission
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
        before = self.pending_permission
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
        on_turn_end: Callable[[int], None] | None = None,
        default_permission_mode: Callable[[], str | None] | None = None,
        read_transcript: history_module.ReadTranscript | None = None,
        read_edits: history_module.ReadEdits | None = None,
        clock: Callable[[], float] = time.time,
        read_context: ReadContext | None = None,
    ) -> None:
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
        self._db_path = db_path
        self._file_mtime = file_mtime or history_module.sdk_session_file_mtime
        # State of sessions forgotten from memory (seq, connected before, app
        # activity), so events keep increasing and they resume as before.
        self._forgotten: dict[str, tuple[int, bool, float, float | None]] = {}
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
        # Models of `get_server_info()`, kept in `app_state` so a restart starts
        # with the last list. `_models_fetched_at` is when it was last confirmed.
        self._models: list[dict[str, Any]] | None = None
        self._models_fetched_at = 0.0
        self._load_models()

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
        except (sqlite3.Error, ValueError):
            logger.exception("Falha ao ler a lista de modelos guardada")
            return
        if models is not None and isinstance(fetched_at, int | float):
            self._models = models
            self._models_fetched_at = float(fetched_at)

    def _save_models(self) -> None:
        value = json.dumps(
            {"models": self._models, "fetched_at": self._models_fetched_at}, ensure_ascii=False
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
        return (
            self._models is None
            or self._clock() - self._models_fetched_at >= MODELS_MAX_AGE
        )

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

    async def refresh_models_if_stale(self) -> bool:
        """Ask the SDK for the models with a throwaway client, when the stored
        list is missing or old. True when a new list was received; failures are
        logged and leave the stored list as it is."""
        if not self._models_stale():
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

    def create_session(self, project: Project) -> SessionRecord:
        if not project.available:
            raise ProjectUnavailableError("A pasta do projeto não está disponível.")
        now = _now()
        record = SessionRecord(
            session_id=str(uuid.uuid4()),
            project_id=project.id,
            cwd=project.path,
            title=DEFAULT_TITLE,
            created_at=now,
            last_activity_at=now,
            last_seen_at=now,
            finished=False,
            permission_mode=self._default_permission_mode(),
        )
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                f"INSERT INTO sessions ({_INSERT_COLUMNS}, permission_mode)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.project_id,
                    record.cwd,
                    record.title,
                    record.created_at,
                    record.last_activity_at,
                    record.last_seen_at,
                    int(record.finished),
                    record.permission_mode,
                ),
            )
        return record

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
            on_turn_end=self._on_turn_end,
            on_connected=self._on_connected,
            read_transcript=self._read_transcript,
        )
        forgotten = self._forgotten.pop(session_id, None)
        if forgotten is not None:
            (session.seq, session._connected_before,
             session._app_activity_at, session._loaded_mtime) = forgotten
            # Recreated empty: the conversation comes from disk, and the frontend
            # drops what it shows before any other event of this session.
            session._emit("conversation.reset", {})
        self._sessions[session_id] = session
        return session

    def active_ids(self) -> set[str]:
        return set(self._sessions)

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

    async def send(
        self, session_id: str, text: str, images: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Send a message. `external_activity` tells whether the resumed history was
        modified in the last minute by another process."""
        session = self.get(session_id)
        session.users += 1
        try:
            external = False
            if not session.active:
                await session.reload_if_modified()
                await self.refresh_file_info(session)
                external = session.external_activity
            await session.send(text, images)
            return {"state": session.state, "external_activity": external}
        finally:
            session.users -= 1

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
            return await asyncio.to_thread(self._read_edits, session_id, session.record.cwd)
        except Exception:
            logger.exception("Falha ao ler as edições da sessão %s", session_id)
            return []

    def refresh_records(self, session_ids: set[str]) -> None:
        """Reload records changed by the history sync for sessions kept in memory."""
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

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Sessions whose title, summary or first prompt contain `query`, ignoring
        case and accents. Includes finished and hidden ones; newest first."""
        needle = _strip_accents(" ".join(query.split()))
        if not needle:
            return []
        result = []
        for item in self.list_sessions():
            haystack = " ".join(
                item.get(key) or "" for key in ("title", "summary", "first_prompt")
            )
            if needle in _strip_accents(haystack):
                result.append(item)
                if len(result) >= limit:
                    break
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
                found = await asyncio.to_thread(self._read_context, record.session_id, record.cwd)
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

    @staticmethod
    def _extras(active: ActiveSession | None = None) -> dict[str, Any]:
        """Context (in memory only) and pending permission of a session, for `describe`."""
        if active is None:
            return {"context": None, "pending_permission": None}
        return {"context": active.context, "pending_permission": active.pending_permission}

    def _describe_active(self, session: ActiveSession) -> dict[str, Any]:
        return describe(
            session.record, session.state, session.error, session.seq,
            finished_after=self.finished_after(), effort_pending=session.effort_pending,
            model_resolved=session.model_resolved, **self._extras(session),
        )

    def describe_record(self, record: SessionRecord) -> dict[str, Any]:
        """A session without an active client (e.g. just created)."""
        return describe(
            record, "closed", None, 0, finished_after=self.finished_after(),
            **self._extras(),
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
                    **self._extras(active),
                )
            else:
                record = _record(row)
                item = describe(record, "closed", None, 0,
                                finished_after=finished_after, now=now,
                                **self._extras())
            if display_state is None or item["display_state"] == display_state:
                result.append(item)
        return result

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
    ) -> dict[str, Any]:
        """Finish, reopen, rename or change options (model, effort, permission mode).

        `bypassPermissions` needs `confirm_bypass`. Emits `session.updated` when
        something changed, and `session.options` when an option changed.
        """
        session = self.get(session_id)
        if effort is not None and effort not in EFFORTS:
            raise InvalidDecisionError("Nível de raciocínio inválido.")
        if model is not None and not MODEL_PATTERN.match(model):
            raise InvalidDecisionError("Modelo inválido.")
        if permission_mode is not None and permission_mode not in PERMISSION_MODES:
            raise InvalidDecisionError("Modo de permissão inválido.")
        if (
            permission_mode == "bypassPermissions"
            and not confirm_bypass
            and session.record.permission_mode != "bypassPermissions"
        ):
            raise BypassNotConfirmedError(
                "Confirme que quer rodar sem perguntas antes de ativar este modo."
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
        if not changes:
            if options_changed:
                session.emit_updated()
            return session.summary()
        session.save(**changes)
        if "title" in changes:
            if await session.has_history():
                try:
                    await asyncio.to_thread(
                        self._rename_session, session_id, changes["title"], session.record.cwd
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
        session.emit_updated()
        return session.summary()

    async def mark_seen(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        session.save(last_seen_at=max(_now(), session.record.last_activity_at))
        session.emit_updated()
        return session.summary()

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

    async def close_idle(self) -> None:
        """Close clients idle longer than the timeout. They resume on the next message."""
        now = time.monotonic()
        for session in list(self._sessions.values()):
            if (
                session.state == "idle"
                and not session.busy
                and not session.subagents_running
                and session.idle_since is not None
                and now - session.idle_since >= self._idle_timeout
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
                del self._sessions[session_id]

    def app_writing(self, session_id: str) -> bool:
        """The app has a client, a turn or an operation on this session's file."""
        session = self._sessions.get(session_id)
        return session is not None and (
            session.active or session.pending_turns > 0 or bool(session.prompts) or session.busy
        )

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
            seq = forgotten[0] if forgotten is not None else 0
            data = describe(
                record, "closed", None, seq, finished_after=self.finished_after(),
                **self._extras(),
            )
            self._publish(
                {"session_id": session_id, "seq": seq, "type": "session.updated", "data": data}
            )
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

    def in_use(self, session_id: str) -> bool:
        """The app is using the session (client, prompts, turns or an operation)."""
        session = self._sessions.get(session_id)
        return session is not None and not session.forgettable

    async def run_idle_sweep(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self.close_idle()
            except Exception:
                logger.exception("Falha na varredura de sessões ociosas")

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.close(final=True)
