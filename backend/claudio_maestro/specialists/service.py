"""Runs of the agents (specialists): starts them and records how each one ended.

`SpecialistService` is the host of the Maestro tools (`ToolHost`) and the hook target of
the sessions (`session_setup`, `on_finished`, `on_turn_error`, `on_init`) and of the
closure check (`on_closure`). It never keeps secrets in an exception, a log or a prompt:
they only travel in the `env` of the session.
"""

import asyncio
import json
import logging
import sqlite3
import time
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
OPEN_OUTCOMES = ("running", "waiting")
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
# A concluded session is finished when its turn ends. The wait has no limit (a session is
# never finished with its turn open); past this long it is only logged.
FINISH_POLL_SECONDS = 0.25
FINISH_WARN_SECONDS = 300.0

Trigger = Literal["schedule", "manual"]
Publish = Callable[[dict[str, Any]], None]


def _cut(text: str, limit: int = REASON_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_pr_url(url: str) -> str:
    """A PR URL without query, fragment or trailing slash: the one form the registry
    keeps and compares, so a PR is never stored twice."""
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


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
        # session id -> text of the last "needs you" alert, so the same check does not
        # warn twice. Memory only: after a restart the same alert may come once more.
        self._last_alert: dict[str, str] = {}

    async def shutdown(self) -> None:
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
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, record.specialist_id)
            extra = self._extra_projects(conn, specialist)
        skill = parse_skill(self._files.read_skill(specialist.slug))
        prompt = build_append(
            name=specialist.name,
            skill_body=skill.body,
            learnings=self._files.read_learnings(specialist.slug),
            extra_projects=[(project.name, project.path) for project in extra],
        )
        rules = ask_rules(specialist.outward_patterns, specialist.always_ask_patterns)
        return SessionExtras(
            system_prompt_append=prompt,
            add_dirs=[Path(project.path) for project in extra],
            env=self._files.read_secrets(specialist.slug),
            mcp_servers={
                SERVER_NAME: build_server(
                    self, specialist_id=specialist.id, session_id=record.session_id
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

    # Starting a run ----------------------------------------------------------------

    async def start_run(
        self,
        specialist_id: int,
        *,
        trigger: Trigger,
        text: str | None = None,
        scheduled_for: int | None = None,
    ) -> store.Run:
        """Create the agent's session, record the run and send it the run text. A project
        that is gone or a failure to send ends the run as `failed` with the reason."""
        with closing(db.connect(self._db_path)) as conn:
            specialist = store.get_specialist(conn, specialist_id)
            try:
                project = projects.get_project(conn, specialist.project_id)
            except projects.ProjectNotFoundError:
                project = None
        if project is None:
            return self._record_without_session(
                specialist, trigger, "failed", PROJECT_MISSING, scheduled_for
            )
        if not project.available:
            return self._record_without_session(
                specialist, trigger, "failed", PROJECT_UNAVAILABLE, scheduled_for
            )
        try:
            record = self._sessions.create_session(
                project, specialist_id=specialist.id, model=specialist.model, effort=specialist.effort
            )
        except (InvalidDecisionError, ProjectUnavailableError) as error:
            return self._record_without_session(
                specialist, trigger, "failed", str(error), scheduled_for
            )
        except Exception:
            logger.exception("Falha ao criar a sessão do agente %s", specialist.slug)
            return self._record_without_session(
                specialist, trigger, "failed", SESSION_NOT_CREATED, scheduled_for
            )
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            run = store.insert_run(
                conn,
                specialist_id=specialist.id,
                trigger=trigger,
                started_at=self._now(),
                outcome="running",
                session_id=record.session_id,
                scheduled_for=scheduled_for,
            )
        self._publish_run(run)
        title = f"{specialist.name} · {datetime.fromtimestamp(self._now()):%d/%m %H:%M}"
        try:
            await self._sessions.update(record.session_id, title=title)
        except Exception:
            logger.exception("Falha ao dar título à sessão do agente %s", specialist.slug)
        try:
            await self._sessions.send(record.session_id, text or specialist.run_text)
        except Exception as error:
            logger.exception("Falha ao enviar a execução ao agente %s", specialist.slug)
            self._set_outcome(
                record.session_id, "failed", _cut(f"Não foi possível enviar a mensagem: {error}"),
                only_from=("running",),
            )
            self._check_streak(specialist)
        with closing(db.connect(self._db_path)) as conn:
            return store.get_run(conn, run.id)

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
        """Whether an unfinished session of the agent has a turn open or a pending
        permission or question."""
        for session_id in self._sessions.active_ids():
            try:
                session = self._sessions.get(session_id)
            except SessionNotFoundError:
                continue
            if (
                session.record.specialist_id == specialist_id
                and not session.record.finished
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
        self._publish_run(run)
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
        self._set_outcome(session_id, "concluded", None, only_from=RECOVERABLE_OUTCOMES)
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
        if closure.verdict not in ("can_close", "user_action", "incomplete"):
            return
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
            self._set_outcome(closure.session_id, "closed", None, only_from=RECOVERABLE_OUTCOMES)
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
            pending = store.pending_finishes(conn)
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

    def on_finished(self, session_id: str, finished_at: int) -> None:
        """The session was finished (by the person or by this service): a run still open
        counts as concluded, and no finish is pending any more."""
        self._clear_pending(session_id)
        self._set_outcome(
            session_id, "concluded", FINISHED_BY_USER, only_from=OPEN_OUTCOMES, ended_at=finished_at
        )

    def on_turn_error(self, session_id: str, error: str) -> None:
        """A turn or the session ended in error: a run still `running` failed."""
        run = self._set_outcome(session_id, "failed", _cut(error), only_from=("running",))
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
    ) -> store.Run | None:
        """Move the session's run to `outcome` when it is in one of `only_from`; a final
        outcome gets an end time. Returns the run changed, or None."""
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
        self._publish_run(run)
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
