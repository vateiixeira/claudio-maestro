"""Decisions: a question an agent puts to the person, with a receipt and a wakeup.

An agent asks through `request` (the `decidir` tool). The question is bound to the task of the
run that asked, when there is one, and shows up on the task and as a notice. The person answers
through `answer`: the answer gets a receipt, a `human` comment on the task and, after the commit,
a wakeup of the agent with `source="decision"`. A decision nobody answers expires after
`DECISION_TTL_SECONDS` (`expire_stale`, called by the scheduler on each tick).

`AskUserQuestion` is unchanged: it is the session's own pending question. This is the structured
form tied to a task.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claudio_maestro import db
from claudio_maestro.org import store

if TYPE_CHECKING:
    from claudio_maestro.org.service import OrgService
    from claudio_maestro.org.tasks import TaskService

logger = logging.getLogger(__name__)

Publish = Callable[[str, dict[str, Any]], None]

DECISION_TTL_SECONDS = 7 * 24 * 3600

PENDING_ON_TASK = "Já há uma decisão pendente desta tarefa."
PENDING_WITHOUT_TASK = "Já há uma decisão pendente deste agente."
NOT_AN_AGENT_SESSION = "Esta sessão não é de um agente."
_ANSWER_PREFIX = "Decisão: "
_REMOVED_AGENT = "agente removido"


class DecisionService:
    def __init__(
        self,
        db_path: Path,
        *,
        org: "OrgService",
        tasks: "TaskService",
        publish: Publish,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._org = org
        self._tasks = tasks
        self._publish = publish
        self._clock = clock

    # Asking -------------------------------------------------------------------------------

    def request(
        self, session_id: str, *, question: str, options: list[str] | None
    ) -> store.Decision:
        """Open a decision for the agent that owns `session_id`. It belongs to the task of the
        session's active run, when there is one. One pending decision per agent and task:
        asking the same question again returns it, asking another one is refused."""
        options = list(options or [])
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            agent_id = self._session_agent(conn, session_id)
            if agent_id is None:
                raise store.OrgError(NOT_AN_AGENT_SESSION)
            agent = store.get_agent(conn, agent_id)
            run = store.run_for_session(conn, session_id)
            if run is not None and (
                run.agent_id != agent_id or run.outcome not in store.ACTIVE_OUTCOMES
            ):
                run = None
            task_id = run.task_id if run is not None else None
            pending = self._pending_of(conn, agent_id, task_id)
            if pending is not None:
                if pending.question == question:
                    return pending
                raise store.OrgError(PENDING_ON_TASK if task_id else PENDING_WITHOUT_TASK)
            decision = store.create_decision(
                conn, project_id=agent.project_id, task_id=task_id, agent_id=agent_id,
                run_id=run.id if run is not None else None, question=question, options=options,
                session_id=session_id, now=self._now(),
            )
            task = None
            if task_id is not None:
                self._app(conn, task_id, f"Decisão pedida: {question}")
                task = store.get_task(conn, task_id)
            notice = store.add_notice(
                conn, agent_id=agent_id, run_id=decision.run_id, kind="notice",
                text=f"{self._name(agent)} pediu uma decisão: {question}", now=self._now(),
            )
        self._publish("decision", dataclasses.asdict(decision))
        self._publish("agent.notice", dataclasses.asdict(notice))
        if task is not None:
            self._task_changed(task)
        return decision

    # Answering ----------------------------------------------------------------------------

    async def answer(self, decision_id: int, *, answer: str) -> store.Decision:
        """Record the answer (with a receipt), leave a `human` comment on the task and wake the
        agent. A wake that fails does not undo the answer."""
        if not isinstance(answer, str) or not 1 <= len(answer) <= store.COMMENT_MAX - len(
            _ANSWER_PREFIX
        ):
            raise store.OrgError(
                f"A resposta precisa ter de 1 a {store.COMMENT_MAX - len(_ANSWER_PREFIX)}"
                " caracteres."
            )
        since = 0
        task = None
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            decision = store.answer_decision(
                conn, decision_id, answer=answer, receipt=str(uuid.uuid4()), now=self._now()
            )
            if decision.task_id is not None:
                since = store.last_comment_id(conn, decision.task_id)
                store.add_comment(
                    conn, task_id=decision.task_id, author_kind="human", author_agent_id=None,
                    run_id=None, text=f"{_ANSWER_PREFIX}{answer}", now=self._now(),
                )
                task = store.get_task(conn, decision.task_id)
        self._publish("decision", dataclasses.asdict(decision))
        if task is not None:
            self._task_changed(task)
        await self._wake(decision, since)
        return decision

    async def _wake(self, decision: store.Decision, since_comment_id: int) -> None:
        payload: dict[str, Any] = {"decision_id": decision.id, "receipt": decision.receipt}
        if decision.session_id is not None:
            payload["session_id"] = decision.session_id
        if decision.task_id is not None:
            payload.update(
                task_id=decision.task_id, since_comment_id=since_comment_id, reason="decision"
            )
        try:
            await self._org.wake(
                decision.agent_id, source="decision", task_id=decision.task_id, payload=payload
            )
        except Exception as error:
            self._wake_failed(decision, error)

    def _wake_failed(self, decision: store.Decision, error: Exception) -> None:
        """The answer is saved: say where the agent was not woken (the task or a notice)."""
        if isinstance(error, store.OrgError):
            reason = str(error)
            logger.warning("Não foi possível acordar o agente %s: %s", decision.agent_id, reason)
        else:
            reason = "erro inesperado (veja o log do Maestro)"
            logger.exception("Falha ao acordar o agente %s", decision.agent_id)
        task = None
        notice = None
        try:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                name = self._agent_name(conn, decision.agent_id)
                text = f"Não foi possível acordar {name} com a decisão: {reason}"
                if decision.task_id is not None:
                    self._app(conn, decision.task_id, text)
                    task = store.get_task(conn, decision.task_id)
                else:
                    notice = store.add_notice(
                        conn, agent_id=decision.agent_id, run_id=decision.run_id, kind="alert",
                        text=text, now=self._now(),
                    )
        except Exception:
            logger.exception("Não foi possível registrar a falha de despertar da decisão")
            return
        if task is not None:
            self._task_changed(task)
        if notice is not None:
            self._publish("agent.notice", dataclasses.asdict(notice))

    # Reading ------------------------------------------------------------------------------

    def list(
        self,
        *,
        project_id: int | None = None,
        task_id: int | None = None,
        pending_only: bool = True,
    ) -> list[dict[str, Any]]:
        with closing(db.connect(self._db_path)) as conn:
            return [
                dataclasses.asdict(d)
                for d in store.list_decisions(
                    conn, project_id=project_id, task_id=task_id, pending_only=pending_only
                )
            ]

    # Expiring -----------------------------------------------------------------------------

    async def expire_stale(self) -> int:
        """Close the pending decisions older than `DECISION_TTL_SECONDS`; returns how many."""
        limit = self._now() - DECISION_TTL_SECONDS
        with closing(db.connect(self._db_path)) as conn:
            stale = [d for d in store.list_decisions(conn) if d.created_at < limit]
        expired = 0
        for decision in stale:
            task = None
            try:
                with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                    if not store.expire_decision(conn, decision.id):
                        continue
                    if decision.task_id is not None:
                        self._app(
                            conn, decision.task_id,
                            f"A decisão pedida expirou sem resposta: {decision.question}",
                        )
                        task = store.get_task(conn, decision.task_id)
            except Exception:
                logger.exception("Não foi possível expirar a decisão %s", decision.id)
                continue
            expired += 1
            self._publish(
                "decision", dataclasses.asdict(dataclasses.replace(decision, status="expired"))
            )
            if task is not None:
                self._task_changed(task)
        return expired

    # Helpers ------------------------------------------------------------------------------

    def _now(self) -> int:
        return int(self._clock())

    @staticmethod
    def _session_agent(conn: sqlite3.Connection, session_id: str) -> int | None:
        row = conn.execute(
            "SELECT agent_id FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["agent_id"] if row else None

    @staticmethod
    def _pending_of(
        conn: sqlite3.Connection, agent_id: int, task_id: int | None
    ) -> store.Decision | None:
        """The pending decision of the agent on that task (or off any task)."""
        for decision in store.list_decisions(conn, task_id=task_id):
            if decision.agent_id == agent_id and decision.task_id == task_id:
                return decision
        return None

    def _app(self, conn: sqlite3.Connection, task_id: int, text: str) -> None:
        store.add_comment(
            conn, task_id=task_id, author_kind="app", author_agent_id=None, run_id=None,
            text=text, now=self._now(),
        )

    def _task_changed(self, task: store.Task) -> None:
        self._publish(
            "task",
            {
                "id": task.id, "project_id": task.project_id, "status": task.status,
                "revision": task.revision, "change": "comment",
            },
        )

    def _name(self, agent: store.Agent) -> str:
        try:
            return self._org._describe(agent)[0]
        except Exception:
            return agent.name

    def _agent_name(self, conn: sqlite3.Connection, agent_id: int) -> str:
        try:
            return self._name(store.get_agent(conn, agent_id))
        except store.NotFoundError:
            return _REMOVED_AGENT
