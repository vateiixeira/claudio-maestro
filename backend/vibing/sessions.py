"""Active sessions: one agent client per session, turn counting and permission prompts.

`SessionManager` (one per app) creates sessions and keeps the active ones in
memory. `ActiveSession` owns the conversation, the agent client (created on the
first message), the pending-turn counter and the pending permission prompts.
Every change is published as an envelope `{session_id, seq, type, data}`.
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ResultMessage,
    ToolPermissionContext,
)

from vibing import db
from vibing.agent.base import AgentClient, AgentError, AgentFactory, AgentOptions
from vibing.conversation import ConversationBuilder, Event
from vibing.projects import Project

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "Nova sessão"
TITLE_MAX_LENGTH = 80
DENY_MESSAGE = "O usuário recusou."
CANCELLED_MESSAGE = "O pedido foi cancelado."

SessionState = Literal["closed", "connecting", "running", "awaiting_decision", "idle", "error"]
Decision = Literal["allow_once", "allow_always", "deny"]
DECISIONS: tuple[str, ...] = ("allow_once", "allow_always", "deny")

DisplayState = Literal["running", "waiting", "finished"]
DISPLAY_STATES: tuple[str, ...] = ("running", "waiting", "finished")

Publish = Callable[[dict[str, Any]], None]
HistoryExists = Callable[[str, str], bool]
# rename_session(session_id, title, directory): writes the title to the SDK history.
RenameSession = Callable[[str, str, str], None]

DEFAULT_IDLE_TIMEOUT = 30 * 60  # seconds
DEFAULT_FINISHED_AFTER_DAYS = 3.0
DAY_SECONDS = 86_400


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


@dataclass
class SessionSummary:
    record: SessionRecord
    state: SessionState
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self.record), "state": self.state, "error": self.error}


_COLUMNS = (
    "session_id, project_id, cwd, title, created_at, last_activity_at, last_seen_at, finished"
)


def _record(row: sqlite3.Row) -> SessionRecord:
    fields = {key: row[key] for key in row.keys()}
    fields["finished"] = bool(fields["finished"])
    return SessionRecord(**fields)


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


def describe(
    record: SessionRecord,
    state: SessionState,
    error: str | None,
    seq: int,
    *,
    finished_after: float,
    now: float | None = None,
) -> dict[str, Any]:
    """Session as sent to the frontend by listings, PATCH and `session.updated`."""
    now = time.time() if now is None else now
    return {
        **asdict(record),
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

    def to_dict(self) -> dict[str, Any]:
        return {
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
    ) -> None:
        self.record = record
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
        if self.pending_turns > 0:
            return "running"
        return "idle"

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
        return {
            **self.summary(),
            "items": self.builder.snapshot(),
            "prompts": [prompt.to_dict() for prompt in self.prompts.values()],
            "init": asdict(init) if init is not None else None,
        }

    def summary(self) -> dict[str, Any]:
        if self._describe is not None:
            return self._describe(self)
        return describe(
            self.record, self.state, self.error, self.seq,
            finished_after=DEFAULT_FINISHED_AFTER_DAYS * DAY_SECONDS,
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

    async def send(self, text: str) -> None:
        """Record the message, connect if needed and send it.

        Agent failures do not raise: they move the session to `error`.
        """
        if not text or not text.strip():
            raise EmptyMessageError("A mensagem está vazia.")
        if self._final:
            raise SessionClosedError("O servidor está encerrando. A mensagem não foi enviada.")
        # The user's message is recorded first so it is never lost.
        self._emit_events(self.builder.add_user_message(text))
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
            client = self.client
            assert client is not None
            self.pending_turns += 1
            self._refresh_state()
            try:
                await client.send(text)
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
            resume = self._has_connected or await self._check_history()
            client = self._new_client(resume)
            try:
                await client.connect()
            except AgentError as error:
                if resume or not (error.session_in_use or await self._check_history()):
                    raise
                logger.info("Sessão %s já existe; reconectando com resume", self.session_id)
                await self._close_quietly(client)
                client = self._new_client(resume=True)
                await client.connect()
        except asyncio.CancelledError:
            self._connecting = False
            if client is not None:
                with suppress(asyncio.CancelledError):
                    await asyncio.shield(self._close_quietly(client))
            self._refresh_state()
            raise
        except Exception as error:  # AgentError or anything unexpected
            self._connecting = False
            if generation != self._generation:
                # Closed while connecting: nothing to report.
                if client is not None:
                    await self._close_quietly(client)
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
            await self._close_quietly(client)
            self._refresh_state()
            return False
        self.client = client
        self._has_connected = True
        self._reader = asyncio.create_task(self._read(client))
        return True

    def _new_client(self, resume: bool) -> AgentClient:
        return self._agent_factory(
            AgentOptions(
                cwd=Path(self.record.cwd),
                session_id=self.session_id,
                resume=resume,
                can_use_tool=self._can_use_tool,
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
                self._emit_events(self.builder.handle(message))
                if isinstance(message, ResultMessage):
                    self.pending_turns = max(0, self.pending_turns - 1)
                    self._touch()
                    self.emit_updated()
                self._refresh_state()
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

    def _touch(self) -> None:
        self.save(last_activity_at=_now())

    # Interruption and failure ---------------------------------------------

    async def interrupt(self) -> None:
        client = self.client
        if client is None or (self.pending_turns == 0 and not self.prompts):
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

    async def _fail(self, message: str, client: AgentClient | None = None) -> None:
        client = client or self.client
        reader = self._reader
        self._generation += 1
        self.client = None
        self._reader = None
        self.error = message
        self.pending_turns = 0
        self._emit_events(self.builder.close_open_items())
        self._emit_events(self.builder.add_notice("error", message))
        self._cancel_prompts()
        self._refresh_state()
        await self._dispose(client, reader)

    async def close(self, *, final: bool = False) -> None:
        """Close the client, if any. The session goes back to `closed`.

        An in-flight send or connect notices it through `_generation` and stops
        without touching the discarded client. With `final`, later sends are refused.
        """
        if final:
            self._final = True
        client, reader = self.client, self._reader
        self._generation += 1
        self.client = None
        self._reader = None
        self.pending_turns = 0
        self._cancel_prompts()
        self._refresh_state()
        await self._dispose(client, reader)

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
        self.prompts[prompt.prompt_id] = prompt
        self._emit("prompt.request", prompt.to_dict())
        self._refresh_state()
        try:
            return await prompt.future
        except asyncio.CancelledError:
            # The SDK cancels this task when the turn is interrupted.
            if self.prompts.pop(prompt.prompt_id, None) is not None:
                self._emit_resolved(prompt.prompt_id, "cancelled")
                self._refresh_state()
            raise

    def resolve_prompt(self, prompt_id: str, decision: str) -> None:
        if decision not in DECISIONS:
            raise InvalidDecisionError("Decisão inválida.")
        prompt = self.prompts.get(prompt_id)
        if prompt is None or prompt.future.done():
            raise PromptNotFoundError("Este pedido já foi respondido ou não existe mais.")
        result: PermissionResultAllow | PermissionResultDeny
        if decision == "allow_once":
            result = PermissionResultAllow()
        elif decision == "allow_always":
            if not prompt.suggestions:
                raise AlwaysNotAvailableError("Este pedido não oferece a opção de permitir sempre.")
            result = PermissionResultAllow(updated_permissions=list(prompt.suggestions))
        else:
            result = PermissionResultDeny(message=DENY_MESSAGE)
        del self.prompts[prompt_id]
        prompt.future.set_result(result)
        self._emit_resolved(prompt_id, decision)
        self._refresh_state()

    def _cancel_prompts(self) -> None:
        for prompt_id in list(self.prompts):
            prompt = self.prompts.pop(prompt_id)
            if not prompt.future.done():
                prompt.future.set_result(
                    PermissionResultDeny(message=CANCELLED_MESSAGE, interrupt=True)
                )
            self._emit_resolved(prompt_id, "cancelled")

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
    ) -> None:
        self._db_path = db_path
        self._publish = publish
        self._agent_factory = agent_factory or default_agent_factory
        self._history_exists = history_exists or sdk_history_exists
        self._rename_session = rename_session or sdk_rename_session
        self._idle_timeout = idle_timeout
        self._finished_after_days = finished_after_days
        self._sessions: dict[str, ActiveSession] = {}

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
        )
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                f"INSERT INTO sessions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.project_id,
                    record.cwd,
                    record.title,
                    record.created_at,
                    record.last_activity_at,
                    record.last_seen_at,
                    int(record.finished),
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
        )
        self._sessions[session_id] = session
        return session

    def active_ids(self) -> set[str]:
        return set(self._sessions)

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

    def _describe_active(self, session: ActiveSession) -> dict[str, Any]:
        return describe(
            session.record, session.state, session.error, session.seq,
            finished_after=self.finished_after(),
        )

    def describe_record(self, record: SessionRecord) -> dict[str, Any]:
        """A session without an active client (e.g. just created)."""
        return describe(record, "closed", None, 0, finished_after=self.finished_after())

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
        self, *, project_id: int | None = None, display_state: str | None = None
    ) -> list[dict[str, Any]]:
        """Sessions of every project (or one), newest activity first, with the current seq."""
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
                )
            else:
                item = describe(_record(row), "closed", None, 0,
                                finished_after=finished_after, now=now)
            if display_state is None or item["display_state"] == display_state:
                result.append(item)
        return result

    # Changes -----------------------------------------------------------------

    async def update(
        self, session_id: str, *, finished: bool | None = None, title: str | None = None
    ) -> dict[str, Any]:
        """Finish, reopen or rename. Emits `session.updated` when something changed."""
        session = self.get(session_id)
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
        if not changes:
            return session.summary()
        session.save(**changes)
        if "title" in changes and await session.has_history():
            try:
                await asyncio.to_thread(
                    self._rename_session, session_id, changes["title"], session.record.cwd
                )
            except Exception:
                logger.exception("Falha ao renomear a sessão %s no SDK", session_id)
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
        for session_id, session in list(self._sessions.items()):
            if session.record.project_id == project_id:
                await session.close(final=True)
                self._sessions.pop(session_id, None)

    async def close_idle(self) -> None:
        """Close clients idle longer than the timeout. They resume on the next message."""
        now = time.monotonic()
        for session in list(self._sessions.values()):
            if (
                session.state == "idle"
                and not session.busy
                and session.idle_since is not None
                and now - session.idle_since >= self._idle_timeout
            ):
                logger.info("Sessão %s ociosa; fechando o cliente", session.session_id)
                await session.close()

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
