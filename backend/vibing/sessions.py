"""Active sessions: one agent client per session, turn counting and permission prompts.

`SessionManager` (one per app) creates sessions and keeps the active ones in
memory. `ActiveSession` owns the conversation, the agent client (created on the
first message), the pending-turn counter and the pending permission prompts.
Every change is published as an envelope `{session_id, seq, type, data}`.
"""

import asyncio
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

Publish = Callable[[dict[str, Any]], None]
HistoryExists = Callable[[str, str], bool]


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


@dataclass
class SessionSummary:
    record: SessionRecord
    state: SessionState
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self.record), "state": self.state, "error": self.error}


_COLUMNS = "session_id, project_id, cwd, title, created_at, last_activity_at"


def _record(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(**{key: row[key] for key in row.keys()})


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

    def _refresh_state(self) -> None:
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
            "session_id": self.session_id,
            "project_id": self.record.project_id,
            "title": self.record.title,
            "cwd": self.record.cwd,
            "state": self.state,
            "error": self.error,
            "seq": self.seq,
            "items": self.builder.snapshot(),
            "prompts": [prompt.to_dict() for prompt in self.prompts.values()],
            "init": asdict(init) if init is not None else None,
        }

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
        first = self._sent_messages == 0
        self._sent_messages += 1
        if first and self.record.title == DEFAULT_TITLE:
            self._set_title(text)

        async with self._lock:
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
        self.record.last_activity_at = _now()
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                "UPDATE sessions SET last_activity_at = ? WHERE session_id = ?",
                (self.record.last_activity_at, self.session_id),
            )

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

    async def _dispose(
        self, client: AgentClient | None, reader: asyncio.Task[None] | None
    ) -> None:
        if client is not None:
            await self._close_quietly(client)
        if reader is not None and reader is not asyncio.current_task() and not reader.done():
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
    ) -> None:
        self._db_path = db_path
        self._publish = publish
        self._agent_factory = agent_factory or default_agent_factory
        self._history_exists = history_exists or sdk_history_exists
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
        )
        with closing(db.connect(self._db_path)) as conn:
            conn.execute(
                f"INSERT INTO sessions ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.session_id,
                    record.project_id,
                    record.cwd,
                    record.title,
                    record.created_at,
                    record.last_activity_at,
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
        )
        self._sessions[session_id] = session
        return session

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

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.close(final=True)
