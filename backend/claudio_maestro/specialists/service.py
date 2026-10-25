"""Runs of the agents (specialists): starts them and records how each one ended.

`SpecialistService` is the host of the Maestro tools (`ToolHost`) and the hook target of
the sessions (`session_setup`, `on_finished`, `on_turn_error`, `on_init`) and of the
closure check (`on_closure`). It never keeps secrets in an exception, a log or a prompt:
they only travel in the `env` of the session.
"""

import asyncio
import json
import logging
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from claudio_maestro import db, projects
from claudio_maestro.digest.closure_store import Closure
from claudio_maestro.sessions import (
    BLOCKED_TOOL_MESSAGE,
    ActiveSession,
    InvalidDecisionError,
    ProjectUnavailableError,
    SessionExtras,
    SessionManager,
    SessionNotFoundError,
    SessionRecord,
)
from claudio_maestro.specialists import store
from claudio_maestro.specialists.files import SpecialistFiles, parse_skill
from claudio_maestro.specialists.policy import (
    COMMENT_COMMANDS,
    COMMENT_DENIED,
    ask_rules,
    classify,
    denies_tool,
    is_blocked,
    read_git_context,
)
from claudio_maestro.specialists.prompt import build_append
from claudio_maestro.specialists.store import normalize_pr_url
from claudio_maestro.specialists.tools import SERVER_NAME, TOOL_PREFIX, build_server

logger = logging.getLogger(__name__)

PROJECT_MISSING = "O projeto do agente não existe mais."
PROJECT_UNAVAILABLE = "A pasta do projeto não está disponível."
SESSION_NOT_CREATED = "Não foi possível criar a sessão do agente."
FINISHED_BY_USER = "Finalizada por você"
# Tools that always need a person, whatever the agent's autonomy: nobody is at the screen
# to answer in the CLI, and approving them without a screen would skip the question.
ALWAYS_ASK_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})
# Outcomes of a run still in flight.
OPEN_OUTCOMES = ("starting", "running", "waiting")
# A failed run can still end well: the agent went on after the error and concluded, or
# the closure check found the work done or the person's turn.
RECOVERABLE_OUTCOMES = (*OPEN_OUTCOMES, "failed")
# States of a session with a turn in progress (a pending permission or question is part
# of the turn).
TURN_OPEN_STATES = ("connecting", "running", "awaiting_decision")
# Outcomes of a run whose session is finished by this service once its turn ends.
FINISHING_OUTCOMES = ("concluded", "closed")
PROBLEM_OUTCOMES = ("failed", "skipped")
REASON_MAX_CHARS = 500
# Outcomes that tell the main conversation how a run went (once per run), and how each
# one reads in the announcement.
ANNOUNCED_OUTCOMES = {
    "concluded": "concluída",
    "closed": "fechada pela verificação",
    "failed": "falhou",
}
ANNOUNCEMENT_MAX_CHARS = 4000
ANNOUNCEMENTS_OPEN = "<maestro-anuncios>"
ANNOUNCEMENTS_CLOSE = "</maestro-anuncios>"
# A concluded session is finished when its turn ends. The wait has no limit (a session is
# never finished with its turn open); past this long it is only logged.
FINISH_POLL_SECONDS = 0.25
FINISH_WARN_SECONDS = 300.0

class CommentNotSentError(RuntimeError):
    """The provider was not called: the queued comments can safely be tried again."""


class CommentDeferredError(CommentNotSentError):
    """The agent is busy or paused; defer silently without attempting delivery."""


Trigger = Literal["schedule", "manual"]
Publish = Callable[[dict[str, Any]], None]
MAX_QUEUED_RUNS = 50
UNCERTAIN_SEND = "O envio foi interrompido. Confira a conversa antes de retomar a fila ou rodar de novo."


class QueueFullError(store.SpecialistError):
    def __init__(self) -> None:
        super().__init__("A fila já tem 50 execuções. Cancele uma pendência antes de adicionar outra.")


def _cut(text: str, limit: int = REASON_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# The tag that wraps the announcements in a message, opening or closing, in any case and
# with spaces: a text that carried one could end the block early.
_BLOCK_TAG = re.compile(r"<(?=\s*/?\s*maestro-anuncios)", re.IGNORECASE)


def _announcement_text(text: str, limit: int) -> str:
    """One line, cut to `limit` characters, that cannot close the announcements block nor
    fake the `[dd/mm HH:MM]` start of another announcement."""
    text = _BLOCK_TAG.sub("‹", " ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


COMMENT_ASK_ORIGIN = (
    "Resolva o que foi pedido. Não comente no GitHub; ao terminar, chame concluir com o resumo."
)
COMMENT_ASK_MAIN = "Resolva o que foi pedido e responda aqui."


def _comment_message(pr: store.Pr, comments: list[store.PrComment], *, main: bool) -> str:
    """What an agent's session receives for a batch of the owner's comments on a PR."""
    lines = [f"Comentário de @{comments[0].author} no PR {pr.url}:"]
    for comment in comments:
        if comment.path:
            where = f"{comment.path}:{comment.line}" if comment.line else comment.path
            lines.append(f"[{where}] {comment.body}")
        else:
            lines.append(comment.body)
    lines.append(COMMENT_ASK_MAIN if main else COMMENT_ASK_ORIGIN)
    return "\n".join(lines)


def _noop() -> None:
    return None


class SpecialistService:
    def __init__(
        self,
        db_path: Path,
        *,
        files: SpecialistFiles,
        sessions: SessionManager,
        publish: Publish,
        clock: Callable[[], float] = time.time,
        finish_poll: float = FINISH_POLL_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._files = files
        self._sessions = sessions
        self._publish = publish
        self._clock = clock
        self._finish_poll = finish_poll
        self._tasks: set[asyncio.Task[None]] = set()
        self._queue_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._queue_task: asyncio.Task[None] | None = None
        self._queue_dispatches: dict[int, asyncio.Task[None]] = {}
        self._queue_wake = asyncio.Event()
        self._stopping = False
        # The scheduler supplies the usage/disabled gate; manual requests remain available.
        self.queue_gate: Callable[[store.Run], bool] = lambda run: True
        # session id -> text of the last "needs you" alert, so the same check does not
        # warn twice. Memory only: after a restart the same alert may come once more.
        self._last_alert: dict[str, str] = {}
        # agent id -> lock of `ensure_main`, so two callers never create two conversations.
        self._main_locks: dict[int, asyncio.Lock] = {}

    async def shutdown(self) -> None:
        self._stopping = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # Session setup and policy ------------------------------------------------------

    def session_setup(self, record: SessionRecord) -> SessionExtras | None:
        """What an agent's session adds to its client; None for an ordinary session.
        Errors here never quote the contents of `secrets.env`."""
        if record.specialist_id is None:
            return None
        main = self.is_main(record.session_id)
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, record.specialist_id)
            extra = self._extra_projects(conn, specialist)
        skill = parse_skill(self._files.read_skill(specialist.slug))
        prompt = build_append(
            name=specialist.name,
            skill_body=skill.body,
            learnings=self._files.read_learnings(specialist.slug),
            extra_projects=[(project.name, project.path) for project in extra],
            main=main,
            conversation=self.is_conversation(record.session_id),
        )
        rules = ask_rules(specialist.outward_patterns, specialist.always_ask_patterns)
        return SessionExtras(
            system_prompt_append=prompt,
            add_dirs=[Path(project.path) for project in extra],
            env=self._files.read_secrets(specialist.slug),
            mcp_servers={
                SERVER_NAME: build_server(
                    self, specialist_id=specialist.id, session_id=record.session_id, main=main
                )
            },
            settings=json.dumps(
                {
                    "permissions": {
                        "ask": rules,
                        "deny": [
                            *specialist.denied_tools,
                            *(f"Bash({pattern}:*)" for pattern in COMMENT_COMMANDS),
                        ],
                    }
                }
            ),
            decide=self._decider(record.session_id, list(specialist.denied_tools)),
            deny_message=self._deny_message(record.session_id, list(specialist.denied_tools)),
        )

    @staticmethod
    def _extra_projects(
        conn: sqlite3.Connection, specialist: store.Specialist
    ) -> list[projects.Project]:
        """The additional projects that still exist and are available, once each."""
        found: list[projects.Project] = []
        for project_id in specialist.extra_project_ids:
            if project_id == specialist.project_id or any(p.id == project_id for p in found):
                continue
            try:
                project = projects.get_project(conn, project_id)
            except projects.ProjectNotFoundError:
                continue
            if project.available:
                found.append(project)
        return found

    def _decider(self, session_id: str, denied_at_start: list[str]):
        async def decide(
            tool_name: str, tool_input: dict[str, Any]
        ) -> Literal["allow", "ask", "deny"]:
            # The `deny` rules of the session settings already stop a blocked tool in the
            # CLI; this is the second wall. It reads the list now, so a tool blocked after
            # the process started is refused too, but only if the call reaches this callback.
            # What the CLI allows by itself (Read, Glob, Grep...) never does, and the
            # `--settings` of a running process is not redone: such a tool is only blocked
            # for good once the session gets a new process.
            if is_blocked(tool_name, self._denied_tools(session_id, denied_at_start)):
                return "deny"
            if denies_tool(tool_name):
                return "deny"
            if tool_name.startswith(TOOL_PREFIX):
                return "allow"
            if tool_name in ALWAYS_ASK_TOOLS:
                return "ask"
            # Bash, Monitor, PowerShell...: whatever runs a shell command, by its input.
            if tool_name != "Bash" and "command" not in tool_input:
                return "allow"
            command = tool_input.get("command")
            if not isinstance(command, str):
                return "ask"
            # Both are read now: the history sync and external changes put a new record
            # in the session (it may have moved into a worktree), and the person may have
            # changed the agent's autonomy or patterns since the session started.
            try:
                record = self._sessions.find_record(session_id)
            except SessionNotFoundError:
                return "ask"
            specialist = self._specialist_by_id(record.specialist_id)
            if specialist is None:
                return "ask"
            return await classify(
                command,
                autonomy=specialist.autonomy,
                outward=list(specialist.outward_patterns),
                always=list(specialist.always_ask_patterns),
                work_dir=Path(record.work_dir()),
                read_git=read_git_context,
            )

        return decide

    def _deny_message(self, session_id: str, denied_at_start: list[str]):
        """Why the decider refused a call: the decider refuses only a blocked tool or a
        comment on GitHub, so anything not blocked now is a comment."""

        def message(tool_name: str, tool_input: dict[str, Any]) -> str:
            if is_blocked(tool_name, self._denied_tools(session_id, denied_at_start)):
                return BLOCKED_TOOL_MESSAGE
            return COMMENT_DENIED

        return message

    def _denied_tools(self, session_id: str, at_start: list[str]) -> list[str]:
        """The tools blocked for the session's agent now; the ones from the start of the
        session when the agent can no longer be read."""
        try:
            record = self._sessions.find_record(session_id)
            specialist = self._specialist_by_id(record.specialist_id)
        except Exception:
            logger.exception("Falha ao ler as ferramentas bloqueadas da sessão %s", session_id)
            return at_start
        if specialist is None:
            return at_start
        return [*specialist.denied_tools, *at_start]

    # Main conversation -------------------------------------------------------------

    async def ensure_main(self, specialist_id: int) -> str:
        """The id of the agent's main conversation: the permanent session where its owner
        talks to it. Created on first use, and again if it was deleted. A finished one is
        kept: sending to it reopens it. It is not a run, so it records none."""
        lock = self._main_locks.setdefault(specialist_id, asyncio.Lock())
        async with lock:
            with closing(db.connect(self._db_path)) as conn:
                specialist = store.get_specialist(conn, specialist_id)
                try:
                    project = projects.get_project(conn, specialist.project_id)
                except projects.ProjectNotFoundError:
                    project = None
            if specialist.main_session_id is not None:
                try:
                    self._sessions.find_record(specialist.main_session_id)
                    return specialist.main_session_id
                except SessionNotFoundError:
                    pass  # deleted: a new one takes its place
            if project is None:
                raise ProjectUnavailableError(PROJECT_MISSING)
            if not project.available:
                raise ProjectUnavailableError(PROJECT_UNAVAILABLE)
            record = self._sessions.create_session(
                project, specialist_id=specialist.id, model=specialist.model, effort=specialist.effort
            )
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                store.set_main_session(conn, specialist.id, record.session_id)
            self._publish(
                {"session_id": None, "seq": 0, "type": "specialist.changed",
                 "data": {"id": specialist.id}}
            )
            try:
                await self._sessions.update(record.session_id, title=f"{specialist.name} · conversa")
            except Exception:
                logger.exception("Falha ao dar título à conversa principal de %s", specialist.slug)
            return record.session_id

    def is_main(self, session_id: str) -> bool:
        """Whether the session is some agent's main conversation."""
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute(
                "SELECT 1 FROM specialists WHERE main_session_id = ?", (session_id,)
            ).fetchone() is not None

    # Announcements -----------------------------------------------------------------

    def prepare_message(
        self, record: SessionRecord, text: str
    ) -> tuple[str, Callable[[], None]]:
        """What the main conversation really receives: the announcements still pending
        go in a marked block before the message, and the returned `commit` marks them
        delivered (the session calls it once the message is recorded). Anywhere else the
        text is untouched and `commit` does nothing."""
        if record.specialist_id is None or not self.is_main(record.session_id):
            return text, _noop
        specialist_id = record.specialist_id
        with closing(db.connect(self._db_path)) as conn:
            pending = store.pending_announcements(conn, specialist_id)
        if not pending:
            return text, _noop
        lines = [
            f"[{datetime.fromtimestamp(a.created_at):%d/%m %H:%M}] {a.text}"
            + (f" (sessão {a.session_id})" if a.session_id else "")
            for a in pending
        ]
        block = "\n".join([ANNOUNCEMENTS_OPEN, *lines, ANNOUNCEMENTS_CLOSE])
        ids = [a.id for a in pending]

        def commit() -> None:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                store.mark_announcements_delivered(conn, ids, self._now())
            self._publish(
                {"session_id": None, "seq": 0, "type": "specialist.changed",
                 "data": {"id": specialist_id}}
            )

        return f"{block}\n\n{text}", commit

    def unseen(self, specialist_id: int) -> int:
        """What the agent's main conversation has for its owner: the announcements not
        delivered yet, plus one while that conversation waits for an answer (a
        permission or a question)."""
        with closing(db.connect(self._db_path)) as conn:
            count = len(store.pending_announcements(conn, specialist_id))
            row = conn.execute(
                "SELECT main_session_id FROM specialists WHERE id = ?", (specialist_id,)
            ).fetchone()
        main = row["main_session_id"] if row else None
        if main is not None and main in self._sessions.active_ids():
            try:
                if self._sessions.get(main).pending_kind is not None:
                    count += 1
            except SessionNotFoundError:
                pass
        return count

    # Starting a run ----------------------------------------------------------------

    def is_conversation(self, session_id: str) -> bool:
        if self.is_main(session_id):
            return True
        with closing(db.connect(self._db_path)) as conn:
            return conn.execute("SELECT 1 FROM specialist_chats WHERE session_id = ?", (session_id,)).fetchone() is not None

    def conversations(self, specialist_id: int) -> list[dict[str, Any]]:
        with closing(db.connect(self._db_path)) as conn:
            store.get_specialist(conn, specialist_id)
            rows = conn.execute(
                "SELECT session_id, title, finished, created_at, last_activity_at FROM sessions"
                " WHERE specialist_id = ? ORDER BY last_activity_at DESC, session_id DESC LIMIT 100",
                (specialist_id,),
            ).fetchall()
        return [{**dict(row), "finished": bool(row["finished"])} for row in rows]

    def pending_messages(self, specialist_id: int, session_id: str) -> list[dict[str, Any]]:
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError as error:
            raise store.SpecialistNotFoundError("Conversa não encontrada.") from error
        if record.specialist_id != specialist_id:
            raise store.SpecialistNotFoundError("Conversa não encontrada.")
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
            pending = store.list_pending_runs(conn, specialist_id)
        result = []
        for run in pending:
            if run.message and run.session_id == session_id:
                try:
                    preview = self._files.message_preview(specialist.slug, run.id)
                except (OSError, ValueError):
                    preview = "Mensagem indisponível."
                result.append({"id": run.id, "text": preview})
        return result

    async def open_conversation(
        self, specialist_id: int, *, session_id: str | None = None, new: bool = False
    ) -> SessionRecord:
        if session_id is None and not new:
            session_id = await self.ensure_main(specialist_id)
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
            if session_id is None:
                project = projects.get_project(conn, specialist.project_id)
                record = self._sessions.create_session(
                    project, specialist_id=specialist_id, model=specialist.model, effort=specialist.effort
                )
            else:
                try:
                    record = self._sessions.find_record(session_id)
                except SessionNotFoundError as error:
                    raise store.SpecialistNotFoundError("Conversa não encontrada.") from error
                if record.specialist_id != specialist_id:
                    raise store.SpecialistNotFoundError("Conversa não encontrada.")
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            conn.execute("INSERT OR IGNORE INTO specialist_chats VALUES (?, ?)", (record.session_id, specialist_id))
            store.clear_finish_pending(conn, record.session_id)
        self._publish({"session_id": None, "seq": 0, "type": "specialist.changed", "data": {"id": specialist_id}})
        return record

    async def send_message(
        self, session_id: str, text: str, images: list[dict[str, Any]] | None = None
    ) -> store.Run:
        from claudio_maestro.sessions import EmptyMessageError, validate_images

        record = self._sessions.find_record(session_id)
        if record.specialist_id is None:
            raise store.SpecialistNotFoundError("Esta conversa não pertence a um agente.")
        images = list(images or [])
        validate_images(images)
        if not text.strip() and not images:
            raise EmptyMessageError("A mensagem está vazia.")
        if len(text) > 100_000:
            raise EmptyMessageError("A mensagem pode ter até 100.000 caracteres.")
        await self.open_conversation(record.specialist_id, session_id=session_id)
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            specialist = store.get_specialist(conn, record.specialist_id)
            if len(store.list_pending_runs(conn, specialist.id)) >= MAX_QUEUED_RUNS:
                raise QueueFullError
            run = store.insert_run(conn, specialist_id=specialist.id, trigger="manual",
                                   started_at=self._now(), outcome="queued", session_id=session_id, message=True)
            try:
                self._files.write_message(specialist.slug, run.id, text, images)
            except OSError as error:
                raise store.SpecialistError("Não foi possível guardar a mensagem na fila.") from error
        self._publish_run(run)
        # Enqueue immediately, including while a session is starting or waiting for input.
        self.wake_queue()
        return run

    def _complete_messages(self) -> None:
        with closing(db.connect(self._db_path)) as conn:
            rows = conn.execute("SELECT id, session_id FROM specialist_runs WHERE message = 1 AND outcome = 'running'").fetchall()
        for row in rows:
            try:
                if row["session_id"] is None:
                    raise SessionNotFoundError("Conversa não encontrada.")
                session = self._sessions.get(row["session_id"])
            except SessionNotFoundError:
                with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                    store.finish_run(conn, row["id"], outcome="failed", ended_at=self._now(), reason="A conversa não está mais disponível.")
                    run = store.get_run(conn, row["id"])
                self._publish_run(run)
                continue
            if session.client is not None:
                if session.state != "idle":
                    continue
            elif session.record.turn_open:
                continue
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                conn.execute("UPDATE specialist_runs SET outcome = 'concluded', ended_at = ? WHERE id = ? AND outcome = 'running'",
                             (self._now(), row["id"]))
                run = store.get_run(conn, row["id"])
            self._publish_run(run)

    async def start_run(
        self,
        specialist_id: int,
        *,
        trigger: Trigger,
        text: str | None = None,
        scheduled_for: int | None = None,
        schedule_id: int | None = None,
        defer_dispatch: bool = False,
    ) -> store.Run:
        """Persist a request before delivery. Manual and scheduled work share this FIFO.

        The private pending file holds the input; SQLite holds only delivery metadata.
        A scheduled occurrence and its queue entry commit together. Enqueueing has
        no await; only delivery takes the per-agent lock. The scheduler defers
        delivery to the worker so session startup never holds up a later tick.
        """
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            specialist = store.get_specialist(conn, specialist_id)
            if schedule_id is not None:
                schedule = next((s for s in store.list_schedules(conn, specialist_id)
                                 if s.id == schedule_id), None)
                if schedule is None or not specialist.enabled:
                    raise store.SpecialistNotFoundError("O horário foi removido ou desligado.")
                if schedule.last_fired_at is not None and scheduled_for is not None and (
                    schedule.last_fired_at >= scheduled_for
                ):
                    raise store.SpecialistError("Este horário já foi registrado.")
                store.mark_fired(conn, schedule_id, self._now())
            pending = store.list_pending_runs(conn, specialist_id)
            # Several missed occurrences must not become a burst of identical routines.
            previous = next((r for r in pending if r.trigger == "schedule"), None)
            if trigger == "schedule" and previous is not None:
                return previous
            if len(pending) >= MAX_QUEUED_RUNS:
                raise QueueFullError
            run = store.insert_run(
                conn, specialist_id=specialist_id, trigger=trigger,
                started_at=self._now(), outcome="queued", scheduled_for=scheduled_for,
            )
            try:
                self._files.write_run_text(specialist.slug, run.id, text or specialist.run_text)
            except OSError as error:
                raise store.SpecialistError("Não foi possível guardar a execução na fila.") from error
        self._publish_run(run)
        if not defer_dispatch:
            async with self._queue_locks[specialist_id]:
                await self._drain_agent(specialist_id)
                with closing(db.connect(self._db_path)) as conn:
                    run = store.get_run(conn, run.id)
        self.wake_queue()
        return run

    def wake_queue(self) -> None:
        """Wake one service-wide worker, only while there are pending requests."""
        if self._stopping:
            return
        with closing(db.connect(self._db_path)) as conn:
            if not store.list_pending_runs(conn) and not conn.execute(
                "SELECT 1 FROM specialist_runs WHERE message = 1 AND outcome = 'running' LIMIT 1"
            ).fetchone():
                return
        self._queue_wake.set()
        if self._queue_task is None or self._queue_task.done():
            self._queue_task = asyncio.create_task(self._watch_queue())
            self._tasks.add(self._queue_task)
            self._queue_task.add_done_callback(self._tasks.discard)

    async def _watch_queue(self) -> None:
        while not self._stopping:
            self._queue_wake.clear()
            try:
                self._complete_messages()
                with closing(db.connect(self._db_path)) as conn:
                    pending = store.list_pending_runs(conn)
                    messages_open = conn.execute("SELECT 1 FROM specialist_runs WHERE message = 1 AND outcome = 'running' LIMIT 1").fetchone()
                if not pending and not messages_open:
                    return
                for agent_id in dict.fromkeys(run.specialist_id for run in pending):
                    active = self._queue_dispatches.get(agent_id)
                    if active is not None and not active.done():
                        continue
                    # A slow session start must not hold the next delivery of other agents.
                    task = asyncio.create_task(self.drain_queue(agent_id))
                    self._queue_dispatches[agent_id] = task
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Falha ao acompanhar a fila dos agentes")
            try:
                await asyncio.wait_for(self._queue_wake.wait(), max(0.02, self._finish_poll * 4))
            except TimeoutError:
                pass

    async def drain_queue(self, specialist_id: int | None = None) -> None:
        with closing(db.connect(self._db_path)) as conn:
            agent_ids = list(dict.fromkeys(
                r.specialist_id for r in store.list_pending_runs(conn, specialist_id)
            ))
        results = await asyncio.gather(
            *(self._drain_locked(agent_id) for agent_id in agent_ids), return_exceptions=True
        )
        for agent_id, result in zip(agent_ids, results, strict=True):
            if isinstance(result, Exception):
                logger.error("Falha ao disparar a fila do agente %s", agent_id,
                             exc_info=(type(result), result, result.__traceback__))

    async def _drain_locked(self, specialist_id: int) -> None:
        async with self._queue_locks[specialist_id]:
            if self._specialist_by_id(specialist_id) is not None:
                await self._drain_agent(specialist_id)

    @staticmethod
    def _waiting_sessions(conn: sqlite3.Connection, specialist_id: int) -> set[str]:
        return {
            row["session_id"] for row in conn.execute(
                "SELECT r.session_id FROM specialist_runs r"
                " JOIN sessions s ON s.session_id = r.session_id"
                " WHERE r.specialist_id = ? AND r.outcome = 'waiting' AND s.finished = 0"
                " AND r.id = (SELECT rr.id FROM specialist_runs rr WHERE rr.session_id = r.session_id"
                " AND rr.outcome NOT IN ('queued', 'cancelled')"
                " ORDER BY rr.started_at DESC, rr.id DESC LIMIT 1)",
                (specialist_id,),
            )
        }

    async def _drain_agent(self, specialist_id: int) -> None:
        """Under the queue lock: bind before sending, and never replay a bound request."""
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
            pending = store.list_pending_runs(conn, specialist_id)
            waiting_sessions = self._waiting_sessions(conn, specialist_id)
        if specialist.queue_paused or self.is_busy(specialist_id):
            return
        # An uncertain dispatch must be recovered before anything else can start.
        if any(run.outcome == "starting" for run in pending):
            return
        # Keep FIFO among eligible requests. A reply can resolve a waiting session even
        # with routines ahead of it; a held schedule must not lock manual work behind it.
        run = next((
            candidate for candidate in pending
            if self.queue_gate(candidate)
            and (not waiting_sessions or (
                candidate.message and candidate.session_id in waiting_sessions
            ))
        ), None)
        if run is None:
            return
        try:
            images: list[dict[str, Any]] = []
            if run.message:
                text, images = self._files.read_message(specialist.slug, run.id)
            else:
                text = self._files.read_run_text(specialist.slug, run.id)
        except (OSError, ValueError):
            self._fail_queued(run, specialist, "O texto da execução não está disponível. Adicione o pedido novamente.")
            return
        with closing(db.connect(self._db_path)) as conn:
            try:
                project = projects.get_project(conn, specialist.project_id)
            except projects.ProjectNotFoundError:
                project = None
        if project is None or not project.available:
            self._fail_queued(run, specialist, PROJECT_MISSING if project is None else PROJECT_UNAVAILABLE)
            return
        try:
            if run.session_id is not None:
                record = self._sessions.find_record(run.session_id)
                if record.specialist_id != specialist.id:
                    raise ProjectUnavailableError("Conversa não encontrada.")
            else:
                record = self._sessions.create_session(
                    project, specialist_id=specialist.id, model=specialist.model, effort=specialist.effort
                )
        except (InvalidDecisionError, ProjectUnavailableError):
            self._fail_queued(run, specialist, PROJECT_UNAVAILABLE)
            return
        except Exception:
            logger.exception("Falha ao criar a sessão do agente %s", specialist.slug)
            self._fail_queued(run, specialist, SESSION_NOT_CREATED)
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            if not store.claim_run(conn, run.id, record.session_id, self._now()):
                return
            self._publish_run(store.get_run(conn, run.id))
        title = f"{specialist.name} · {datetime.fromtimestamp(self._now()):%d/%m %H:%M}"
        try:
            if not run.message:
                await self._sessions.update(record.session_id, title=title)
        except Exception:
            logger.exception("Falha ao dar título à sessão do agente %s", specialist.slug)
        try:
            if run.message:
                result = await self._sessions.send(record.session_id, text, images)
            else:
                result = await self._sessions.send(record.session_id, text)
        except asyncio.CancelledError:
            # A lost acknowledgement cannot prove that the provider did not start work.
            raise
        except Exception:
            self._uncertain_run(run, specialist)
            return
        if isinstance(result, dict):
            if result.get("send_started") is False:
                self._restore_unsent(run, specialist)
                return
            if result.get("state") == "error":
                self._uncertain_run(run, specialist)
                return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE specialist_runs SET outcome = 'running' WHERE id = ? AND outcome = 'starting'", (run.id,))
            current = store.get_run(conn, run.id)
        self._publish_run(current)
        self._files.delete_run_text(specialist.slug, run.id)

    def _restore_unsent(self, run: store.Run, specialist: store.Specialist) -> None:
        reason = "Não foi possível conectar ao agente. O pedido foi preservado; retome a fila para tentar novamente."
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            conn.execute(
                "UPDATE specialist_runs SET outcome = 'queued', ended_at = NULL, reason = ? WHERE id = ?",
                (reason, run.id),
            )
            store.update_specialist(conn, specialist.id, now=self._now(), queue_paused=True)
            current = store.get_run(conn, run.id)
        self._publish_run(current)
        self._add_notice(specialist.id, current.session_id, "alert", reason)
        self._publish({"session_id": None, "seq": 0, "type": "specialist.changed", "data": {"id": specialist.id}})

    def _fail_queued(self, run: store.Run, specialist: store.Specialist, reason: str) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.finish_run(conn, run.id, outcome="failed", ended_at=self._now(), reason=reason)
            current = store.get_run(conn, run.id)
            announcement = self._announce(conn, current, reason)
        self._publish_run(current)
        self._publish_announcement(announcement)
        self._files.delete_run_text(specialist.slug, run.id)
        self._check_streak(specialist)

    def _uncertain_run(self, run: store.Run, specialist: store.Specialist) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.get_run(conn, run.id)
            store.update_specialist(conn, specialist.id, now=self._now(), queue_paused=True)
        self._fail_queued(run, specialist, UNCERTAIN_SEND)
        self._add_notice(specialist.id, run.session_id, "alert", UNCERTAIN_SEND)
        self._publish({"session_id": None, "seq": 0, "type": "specialist.changed", "data": {"id": specialist.id}})

    async def cancel_run(self, specialist_id: int, run_id: int) -> store.Run:
        async with self._queue_locks[specialist_id]:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                specialist = store.get_specialist(conn, specialist_id)
                run = store.get_run(conn, run_id)
                if run.specialist_id != specialist_id:
                    raise store.SpecialistNotFoundError("Execução não encontrada.")
                if run.outcome == "cancelled":
                    return run
                if run.outcome != "queued":
                    raise store.RunNotQueuedError
                store.finish_run(conn, run_id, outcome="cancelled", ended_at=self._now())
                run = store.get_run(conn, run_id)
            self._files.delete_run_text(specialist.slug, run_id)
            self._publish_run(run)
            return run

    async def start_comment_run(
        self, pr: store.Pr, comments: list[store.PrComment]
    ) -> store.Run | None:
        lock = self._queue_locks[pr.specialist_id]
        if lock.locked():
            raise CommentDeferredError("O comentário aguarda a fila do agente.")
        async with lock:
            specialist = self._specialist_by_id(pr.specialist_id)
            if specialist is None:
                raise store.SpecialistNotFoundError("Agente não encontrado.")
            if specialist.queue_paused or self.is_busy(pr.specialist_id):
                raise CommentDeferredError("O comentário aguarda a fila do agente.")
            with closing(db.connect(self._db_path)) as conn:
                waiting = self._waiting_sessions(conn, pr.specialist_id)
            target = self._comment_target(pr) or specialist.main_session_id
            if waiting and target not in waiting:
                raise CommentDeferredError("O comentário aguarda a resposta à conversa pendente.")
            return await self._start_comment_run(pr, comments)

    async def _start_comment_run(
        self, pr: store.Pr, comments: list[store.PrComment]
    ) -> store.Run | None:
        """Send the owner's comments on `pr` to the session that opened it, which a new
        `comment` run follows (unless it is still on an open run: then it is a message of
        that run). When that session is gone (never known, or deleted), or is
        itself the main conversation, they go to the main conversation, which has no run.
        A message that cannot be sent raises and leaves nothing behind: the caller keeps
        the comments queued and tries again."""
        target = self._comment_target(pr)
        if target is None or self.is_main(target):
            main_id = target or await self.ensure_main(pr.specialist_id)
            await self._send_comment_message(main_id, _comment_message(pr, comments, main=True))
            return None
        with closing(db.connect(self._db_path)) as conn:
            open_run = store.run_for_session(conn, target)
        if open_run is not None and open_run.outcome in OPEN_OUTCOMES:
            # The session is still on a run (a schedule, a manual one or an earlier batch):
            # the comments are one more message of it, and it keeps being the only open run
            # (the whole life cycle follows the newest run of a session).
            await self._send_comment_message(target, _comment_message(pr, comments, main=False))
            return open_run
        # The run is recorded before the send (the agent may conclude at once), but only
        # announced once the send worked: a send that fails leaves nothing on the screen.
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.insert_run(
                conn,
                specialist_id=pr.specialist_id,
                trigger="comment",
                started_at=self._now(),
                outcome="running",
                session_id=target,
            )
        try:
            await self._send_comment_message(target, _comment_message(pr, comments, main=False))
        except BaseException as error:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                if isinstance(error, CommentNotSentError):
                    store.delete_run(conn, run.id)
                else:
                    # The agent may still finish work after cancellation or a lost
                    # acknowledgement. Keep its run so conclude/recovery can track it.
                    conn.execute(
                        "UPDATE specialist_runs SET reason = ? WHERE id = ?",
                        ("Envio sem confirmação; confira a conversa antes de reenviar.", run.id),
                    )
                    current = store.get_run(conn, run.id)
            if not isinstance(error, CommentNotSentError):
                self._publish_run(current)
            raise
        self._publish_run(run)
        with closing(db.connect(self._db_path)) as conn:
            return store.get_run(conn, run.id)

    async def _send_comment_message(self, session_id: str, text: str) -> None:
        result = await self._sessions.send(session_id, text)
        if result.get("send_started") is False:
            raise CommentNotSentError("Não foi possível conectar ao agente antes de enviar.")
        if result.get("state") == "error":
            raise RuntimeError("O envio não foi confirmado; confira a conversa antes de reenviar.")

    def _comment_target(self, pr: store.Pr) -> str | None:
        """The session that opened the PR, if it still exists."""
        if pr.session_id is None:
            return None
        try:
            self._sessions.find_record(pr.session_id)
        except SessionNotFoundError:
            return None
        return pr.session_id

    def record_skipped(
        self, specialist_id: int, reason: str, *, scheduled_for: int | None = None
    ) -> store.Run:
        """A scheduled run that did not start (for the scheduler); it counts toward the
        alert on runs in a row without success."""
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
        return self._record_without_session(specialist, "schedule", "skipped", reason, scheduled_for)

    def record_missed(self, specialist_id: int, reason: str, *, scheduled_for: int) -> store.Run:
        """A scheduled run whose time passed without the scheduler seeing it (the app was
        off or late). It never counts toward the alert on runs in a row without success."""
        now = self._now()
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.get_specialist(conn, specialist_id)
            run = store.insert_run(
                conn,
                specialist_id=specialist_id,
                trigger="schedule",
                started_at=now,
                outcome="missed",
                scheduled_for=scheduled_for,
                reason=_cut(reason),
                ended_at=now,
            )
        self._publish_run(run)
        return run

    def add_alert(self, specialist_id: int, text: str) -> store.Notice:
        """An `alert` notice from outside a run (the scheduler's usage warning)."""
        return self._add_notice(specialist_id, None, "alert", text)

    def is_busy(self, specialist_id: int) -> bool:
        """Every active turn, including the main and PR comments, holds this agent's queue."""
        with closing(db.connect(self._db_path)) as conn:
            if any(r.outcome == "starting" for r in store.list_pending_runs(conn, specialist_id)):
                return True
        for session_id in self._sessions.active_ids():
            try:
                session = self._sessions.get(session_id)
            except SessionNotFoundError:
                continue
            if (
                session.record.specialist_id == specialist_id
                and session.state in TURN_OPEN_STATES
            ):
                return True
        return False

    def _record_without_session(
        self,
        specialist: store.Specialist,
        trigger: Trigger,
        outcome: store.Outcome,
        reason: str,
        scheduled_for: int | None,
    ) -> store.Run:
        now = self._now()
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.insert_run(
                conn,
                specialist_id=specialist.id,
                trigger=trigger,
                started_at=now,
                outcome=outcome,
                scheduled_for=scheduled_for,
                reason=_cut(reason),
                ended_at=now,
            )
            announcement = self._announce(conn, run, run.reason or "")
        self._publish_run(run)
        self._publish_announcement(announcement)
        self._check_streak(specialist)
        return run

    # ToolHost ----------------------------------------------------------------------

    async def conclude(self, session_id: str, summary: str) -> None:
        """The agent's `concluir` tool. It runs inside the agent's turn, so it must not
        wait for the end of that turn: it records everything now and finishes the session
        in the background, once the turn is over."""
        specialist = self._specialist_of(session_id)
        if specialist is None:
            return
        self._add_notice(specialist.id, session_id, "summary", summary)
        self._set_outcome(
            session_id, "concluded", None, only_from=RECOVERABLE_OUTCOMES, announce=summary
        )
        if not self.is_conversation(session_id):
            self._finish_later(session_id)

    async def notify(self, session_id: str, text: str) -> None:
        specialist = self._specialist_of(session_id)
        if specialist is None:
            return
        self._add_notice(specialist.id, session_id, "notice", text)

    def lookup(self, specialist_id: int, keys: list[str]) -> list[store.Item]:
        with closing(db.connect(self._db_path)) as conn:
            return store.get_items(conn, specialist_id, keys)

    def record(
        self, specialist_id: int, key: str, status: str, link: str | None, note: str | None
    ) -> store.Item:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.get_specialist(conn, specialist_id)  # an unknown id must not hit the FK
            return store.upsert_item(
                conn, specialist_id, key=key, status=status, link=link, note=note, now=self._now()
            )

    def rewrite_learnings(self, specialist_id: int, text: str) -> None:
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
        self._files.write_learnings(specialist.slug, text)

    # Hooks of the sessions and of the closure check ------------------------------------

    async def on_closure(self, closure: Closure) -> None:
        """What the closure check found in an agent's session. A verdict older than the
        session's last activity is ignored, like the screen does. Once the run ended, the
        only thing left is a finish still pending (lost in a restart of the backend)."""
        if self.is_conversation(closure.session_id):
            return
        if closure.verdict not in ("can_close", "user_action", "incomplete"):
            return
        if self.is_main(closure.session_id):
            return  # the main conversation never closes by itself, nor alerts
        try:
            record = self._sessions.find_record(closure.session_id)
        except SessionNotFoundError:
            return
        if closure.is_stale(record.last_activity_at):
            return
        specialist = self._specialist_by_id(record.specialist_id)
        if specialist is None:
            return
        with closing(db.connect(self._db_path)) as conn:
            run = store.run_for_session(conn, closure.session_id)
        if run is not None and run.outcome in FINISHING_OUTCOMES:
            await self._finish_if_pending(closure.session_id, record)
            return
        if run is not None and run.outcome not in RECOVERABLE_OUTCOMES:
            return
        if closure.verdict == "can_close":
            if not specialist.close_by_check:
                return
            evidence = closure.evidence or "sem pendências"
            self._add_notice(
                specialist.id, closure.session_id, "summary", f"Fechada pela verificação: {evidence}"
            )
            self._set_outcome(
                closure.session_id, "closed", None, only_from=RECOVERABLE_OUTCOMES,
                announce=evidence,
            )
            self._finish_later(closure.session_id)
            return
        self._set_outcome(
            closure.session_id, "waiting", None, only_from=("running", "failed")
        )
        heading = (
            f"{specialist.name} precisa de você:"
            if closure.verdict == "user_action"
            else f"{specialist.name} deixou pendências:"
        )
        items = [*closure.missing, *closure.user_actions]
        text = "\n".join([heading, *(f"- {item}" for item in items)])
        if self._last_alert.get(closure.session_id) != text:
            self._last_alert[closure.session_id] = text
            self._add_notice(specialist.id, closure.session_id, "alert", text)

    async def recover(self) -> None:
        """At startup, after the sessions kept by the agentd are attached again: finish,
        once their turn ends, the sessions whose run ended but whose finish was lost
        (the backend went down before the turn ended)."""
        with closing(db.connect(self._db_path)) as conn:
            deliveries = store.list_pending_runs(conn)
        for pending_run in deliveries:
            if pending_run.outcome != "starting":
                continue
            async with self._queue_locks[pending_run.specialist_id]:
                with closing(db.connect(self._db_path)) as conn:
                    run = store.get_run(conn, pending_run.id)
                if run.outcome != "starting":
                    continue
                specialist = self._specialist_by_id(run.specialist_id)
                if specialist is None:
                    continue
                if not run.message and run.session_id in self._sessions.active_ids() and (
                    self._sessions.get(run.session_id).client is not None
                ) and (
                    self._sessions.get(run.session_id).state in (*TURN_OPEN_STATES, "idle")
                ):
                    with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                        conn.execute("UPDATE specialist_runs SET outcome = 'running' WHERE id = ?", (run.id,))
                        self._publish_run(store.get_run(conn, run.id))
                    self._files.delete_run_text(specialist.slug, run.id)
                else:
                    self._uncertain_run(run, specialist)
        with closing(db.connect(self._db_path)) as conn:
            pending = store.pending_finishes(conn)
            interrupted = conn.execute(
                "SELECT r.id, r.session_id FROM specialist_runs r"
                " JOIN sessions s ON s.session_id = r.session_id"
                " WHERE r.outcome IN ('running', 'failed') AND s.turn_open = 1 AND s.finished = 0"
                " AND r.id = (SELECT rr.id FROM specialist_runs rr WHERE rr.session_id = r.session_id"
                " AND rr.outcome NOT IN ('queued', 'cancelled')"
                " ORDER BY rr.started_at DESC, rr.id DESC LIMIT 1)"
            ).fetchall()
        for row in interrupted:
            session_id = row["session_id"]
            if session_id in self._sessions.active_ids() and (
                self._sessions.get(session_id).client is not None
                and self._sessions.get(session_id).state in (*TURN_OPEN_STATES, "idle")
            ):
                continue
            run = self._set_outcome(
                session_id, "waiting", UNCERTAIN_SEND, only_from=("running", "failed")
            )
            if run is not None:
                self._add_notice(run.specialist_id, session_id, "alert", UNCERTAIN_SEND)
        for session_id in pending:
            try:
                record = self._sessions.find_record(session_id)
            except SessionNotFoundError:
                self._clear_pending(session_id)
                continue
            with closing(db.connect(self._db_path)) as conn:
                run = store.run_for_session(conn, session_id)
            if record.finished or run is None or run.outcome not in FINISHING_OUTCOMES:
                self._clear_pending(session_id)
                continue
            self._finish_later(session_id)
        self.wake_queue()

    def on_finished(self, session_id: str, finished_at: int) -> None:
        """The session was finished (by the person or by this service): a run still open
        counts as concluded, and no finish is pending any more."""
        self._clear_pending(session_id)
        self._set_outcome(
            session_id, "concluded", FINISHED_BY_USER, only_from=OPEN_OUTCOMES, ended_at=finished_at,
            announce=False,
        )

    def on_turn_error(self, session_id: str, error: str) -> None:
        """A turn or the session ended in error: a run still `running` failed."""
        run = self._set_outcome(session_id, "failed", _cut(error), only_from=("starting", "running"))
        if run is not None:
            specialist = self._specialist_of(session_id)
            if specialist is not None:
                self._check_streak(specialist)

    def on_init(self, session_id: str, mcp_servers: list[dict[str, str]]) -> None:
        """Remember the MCP servers of the agent's last run (saved only when they change)."""
        specialist = self._specialist_of(session_id)
        if specialist is None or specialist.last_mcp == mcp_servers:
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.update_specialist(conn, specialist.id, now=self._now(), last_mcp=mcp_servers)

    def on_pr_created(self, session_id: str, url: str) -> None:
        """The agent's session opened a PR: remember which session did, so the owner's
        comments on it can be sent back to that conversation."""
        specialist = self._specialist_of(session_id)
        if specialist is None:
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.upsert_pr(
                conn, url=normalize_pr_url(url), specialist_id=specialist.id,
                session_id=session_id, created_at=self._now(),
            )
        self._publish(
            {"session_id": None, "seq": 0, "type": "specialist.changed",
             "data": {"id": specialist.id}}
        )

    def is_agent_pr(self, url: str) -> int | None:
        """The agent a PR belongs to: one that opened it, or that has it as the link of an
        item of its registry. None when no agent does."""
        wanted = normalize_pr_url(url)
        with closing(db.connect(self._db_path)) as conn:
            pr = store.get_pr(conn, wanted)
            if pr is not None:
                return pr.specialist_id
            for row in conn.execute(
                "SELECT specialist_id, link FROM specialist_items WHERE link IS NOT NULL"
            ):
                if normalize_pr_url(row["link"]) == wanted:
                    return row["specialist_id"]
        return None

    # Internals ---------------------------------------------------------------------

    def _now(self) -> int:
        return int(self._clock())

    def _specialist_of(self, session_id: str) -> store.Specialist | None:
        """The agent a session belongs to; None for an ordinary or unknown session."""
        try:
            record = self._sessions.find_record(session_id)
        except SessionNotFoundError:
            return None
        return self._specialist_by_id(record.specialist_id)

    def _specialist_by_id(self, specialist_id: int | None) -> store.Specialist | None:
        if specialist_id is None:
            return None
        with closing(db.connect(self._db_path)) as conn:
            try:
                return store.get_specialist(conn, specialist_id)
            except store.SpecialistNotFoundError:
                return None

    def _set_outcome(
        self,
        session_id: str,
        outcome: store.Outcome,
        reason: str | None,
        *,
        only_from: tuple[str, ...],
        ended_at: int | None = None,
        announce: str | Literal[False] | None = None,
    ) -> store.Run | None:
        """Move the session's run to `outcome` when it is in one of `only_from`; a final
        outcome gets an end time. The first `concluded`, `closed` or `failed` of a run is
        announced to the main conversation, with `announce` (default: the reason) as the
        text; `announce=False` announces nothing. Returns the run changed, or None."""
        final = outcome != "waiting"
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.run_for_session(conn, session_id)
            if run is None or run.outcome not in only_from:
                return None
            store.finish_run(
                conn,
                run.id,
                outcome=outcome,
                ended_at=(self._now() if ended_at is None else ended_at) if final else None,
                reason=reason,
            )
            run = store.get_run(conn, run.id)
            announcement = (
                None
                if announce is False
                else self._announce(conn, run, reason if announce is None else announce)
            )
        self._publish_run(run)
        self._publish_announcement(announcement)
        return run

    def _add_notice(
        self, specialist_id: int, session_id: str | None, kind: store.NoticeKind, text: str
    ) -> store.Notice:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            notice = store.add_notice(
                conn,
                specialist_id=specialist_id,
                session_id=session_id,
                kind=kind,
                text=text,
                now=self._now(),
            )
        self._publish(
            {"session_id": None, "seq": 0, "type": "specialist.notice", "data": asdict(notice)}
        )
        return notice

    def _announce(
        self, conn: sqlite3.Connection, run: store.Run, text: str | None
    ) -> store.Announcement | None:
        """Record the run's announcement, in the transaction that changed its outcome. A
        run has one: a later outcome (a failed run that concluded) rewrites it while it is
        still pending, and leaves it alone once delivered. None when nothing changed."""
        if run.message or run.outcome not in ANNOUNCED_OUTCOMES:
            return None
        body = _announcement_text(text or "", ANNOUNCEMENT_MAX_CHARS)
        full = f"{self._run_label(conn, run)} {ANNOUNCED_OUTCOMES[run.outcome]}: {body}"
        existing = store.announcement_for_run(conn, run.id)
        if existing is not None:
            if existing.delivered_at is not None or existing.text == full:
                return None
            return store.update_announcement_text(conn, existing.id, full)
        return store.add_announcement(
            conn,
            specialist_id=run.specialist_id,
            run_id=run.id,
            session_id=run.session_id,
            text=full,
            created_at=self._now(),
        )

    @staticmethod
    def _run_label(conn: sqlite3.Connection, run: store.Run) -> str:
        if run.trigger == "comment":
            row = conn.execute(
                "SELECT url FROM specialist_prs WHERE session_id = ?"
                " ORDER BY created_at DESC, url DESC LIMIT 1",
                (run.session_id,),
            ).fetchone() if run.session_id is not None else None
            number = row["url"].rsplit("/", 1)[-1] if row else ""
            return f"Comentário no PR #{number}" if number.isdigit() else "Comentário no PR"
        at = run.scheduled_for if run.scheduled_for is not None else run.started_at
        return f"Execução das {datetime.fromtimestamp(at):%H:%M}"

    def _publish_announcement(self, announcement: store.Announcement | None) -> None:
        if announcement is None:
            return
        self._publish(
            {"session_id": None, "seq": 0, "type": "specialist.announcement",
             "data": asdict(announcement)}
        )

    def _publish_run(self, run: store.Run) -> None:
        self._publish(
            {"session_id": None, "seq": 0, "type": "specialist.run", "data": asdict(run)}
        )

    def _check_streak(self, specialist: store.Specialist) -> None:
        """Alert once when the two newest counted runs are `failed`/`skipped`: a third
        in a row belongs to the same sequence and stays quiet."""
        with closing(db.connect(self._db_path)) as conn:
            recent = store.last_runs(conn, specialist.id, 3)
        if len(recent) < 2 or any(run.outcome not in PROBLEM_OUTCOMES for run in recent[:2]):
            return
        if len(recent) == 3 and recent[2].outcome in PROBLEM_OUTCOMES:
            return
        last = recent[0]
        reason = (last.reason or "motivo desconhecido").rstrip(".")
        self._add_notice(
            specialist.id,
            last.session_id,
            "alert",
            f"{specialist.name}: duas execuções seguidas sem sucesso. Última: {reason}.",
        )

    def _finish_later(self, session_id: str) -> None:
        """Finish the session once its turn is over, in the background (the caller may be
        a tool running inside that very turn). Nothing is finished if the person wrote,
        or finished and reopened the session, after this point. The task lives in memory;
        a mark in the database survives a restart of the backend, and `recover` (or the
        next closure verdict) finishes the session then."""
        try:
            session = self._sessions.get(session_id)
        except SessionNotFoundError:
            self._clear_pending(session_id)
            return
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.mark_finish_pending(conn, session_id)
        task = asyncio.get_running_loop().create_task(
            self._finish_when_turn_ends(session_id, session, session.activity_marker)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finish_when_turn_ends(
        self, session_id: str, session: ActiveSession, marker: tuple[int, int]
    ) -> None:
        try:
            waited = 0.0
            warned = False
            while True:
                if self.is_conversation(session_id):
                    self._clear_pending(session_id)
                    return
                try:
                    current = self._sessions.get(session_id)
                except SessionNotFoundError:
                    self._clear_pending(session_id)
                    return
                if current is not session:
                    return  # forgotten from memory: the mark stays for `recover`
                if session.activity_marker != marker:
                    self._clear_pending(session_id)
                    return  # the person took the session back
                if session.state not in TURN_OPEN_STATES:
                    break
                await asyncio.sleep(self._finish_poll)
                waited += self._finish_poll
                if waited >= FINISH_WARN_SECONDS and not warned:
                    warned = True
                    logger.warning(
                        "A sessão de agente %s ainda espera o fim do turno para ser finalizada",
                        session_id,
                    )
            await self._sessions.update(session_id, finished=True)
            self._clear_pending(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Falha ao finalizar a sessão de agente %s", session_id)

    async def _finish_if_pending(self, session_id: str, record: SessionRecord) -> None:
        """Finish now a session whose finish is still pending, when its turn is closed
        (no turn running, no permission or question waiting)."""
        if record.finished:
            return
        with closing(db.connect(self._db_path)) as conn:
            if not store.is_finish_pending(conn, session_id):
                return
        if session_id in self._sessions.active_ids():
            try:
                if self._sessions.get(session_id).state in TURN_OPEN_STATES:
                    return
            except SessionNotFoundError:
                return
        await self._sessions.update(session_id, finished=True)
        self._clear_pending(session_id)

    def _clear_pending(self, session_id: str) -> None:
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            store.clear_finish_pending(conn, session_id)
