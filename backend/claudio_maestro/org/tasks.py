"""The task board: who may touch a task, which status changes are allowed, the review the app
imposes and the wakeups each change causes.

`TaskService` is the only door to the board for the API and for the agent tools. The methods
that change state are `async`: they commit first and wake the agents afterwards, so an agent
never wakes up before what woke it is saved. A wake that fails (full queue, anything else) does
not undo the change: it goes to the log and to an `app` comment on the task.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.prompt import TaskBrief

if TYPE_CHECKING:
    from claudio_maestro.org.service import OrgService

logger = logging.getLogger(__name__)

Publish = Callable[[str, dict[str, Any]], None]

BRIEF_COMMENTS = 20  # comments a wakeup lists at most (the newest)
BRIEF_CHILDREN = 50
GET_COMMENTS = 1000
BLOCKED_REASON_MAX = 500

HUMAN_NAME = "Pessoa"
APP_NAME = "Maestro"
REMOVED_AGENT = "agente removido"

NOT_YOUR_REVIEW = "Você não pode ser o revisor de uma tarefa sua."
REVIEWER_LOCKED = (
    "Só quem criou a tarefa define o revisor, e só enquanto ela está em todo: "
    "depois disso só a pessoa o muda."
)
NOT_ALLOWED = "Você não pode alterar esta tarefa: ela não é sua nem de um subordinado seu."
COMMENT_REQUIRED = "Diga o que mudou: um comentário é obrigatório ao mudar o status."

# Status changes an agent may make by itself. `done` of a task with a reviewer becomes
# `in_review` (see `_next_status`); `in_review` is left only by the reviewer; `cancelled` only
# by whoever created the task.
_AGENT_TRANSITIONS = frozenset(
    {
        ("todo", "in_progress"),
        ("in_progress", "blocked"),
        ("blocked", "in_progress"),
        ("in_progress", "done"),
    }
)


class TaskAuthorityError(store.OrgError):
    def __init__(self, message: str = NOT_ALLOWED) -> None:
        super().__init__(message)


class TaskStateError(store.OrgError):
    """A status change the board does not allow."""


@dataclass(frozen=True)
class _Wake:
    agent_id: int
    source: str
    reason: str
    since_comment_id: int


def _add_wake(wakes: list[_Wake], wake: _Wake) -> None:
    """One wake per agent and event: the first one asked for wins."""
    if all(existing.agent_id != wake.agent_id for existing in wakes):
        wakes.append(wake)


class TaskService:
    def __init__(
        self,
        db_path: Path,
        *,
        org: "OrgService",
        publish: Publish,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._org = org
        self._publish = publish
        self._clock = clock

    # Reading ------------------------------------------------------------------------

    def get(self, task_id: int) -> dict[str, Any]:
        """The task with its comments, runs, decisions, PRs and CI receipts, as plain data."""
        with closing(db.connect(self._db_path)) as conn:
            task = store.get_task(conn, task_id)
            return {
                "task": dataclasses.asdict(task),
                "comments": [
                    dataclasses.asdict(c)
                    for c in store.list_comments(conn, task_id, limit=GET_COMMENTS)
                ],
                "runs": [dataclasses.asdict(r) for r in store.list_task_runs(conn, task_id)],
                "decisions": [
                    dataclasses.asdict(d)
                    for d in store.list_decisions(conn, task_id=task_id, pending_only=False)
                ],
                "prs": [dataclasses.asdict(p) for p in store.list_task_prs(conn, task_id)],
                "ci": [dataclasses.asdict(r) for r in store.list_ci_receipts(conn, task_id)],
            }

    def list(
        self,
        *,
        project_id: int | None = None,
        assignee_agent_id: int | None = None,
        statuses: list[str] | tuple[str, ...] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[store.Task]:
        with closing(db.connect(self._db_path)) as conn:
            return store.list_tasks(
                conn, project_id=project_id, assignee_agent_id=assignee_agent_id,
                statuses=statuses, limit=limit, offset=offset,
            )

    def brief(self, task_id: int, *, since_comment_id: int = 0) -> TaskBrief:
        """The task as a wakeup shows it: the comments are the newest (at most 20) above
        `since_comment_id`."""
        with closing(db.connect(self._db_path)) as conn:
            task = store.get_task(conn, task_id)
            names: dict[int, str] = {}
            comments = store.list_comments(
                conn, task_id, after_id=since_comment_id, limit=BRIEF_COMMENTS, latest=True
            )
            parent = None
            if task.parent_task_id is not None:
                row = conn.execute(
                    "SELECT id, title FROM tasks WHERE id = ?", (task.parent_task_id,)
                ).fetchone()
                parent = (row["id"], row["title"]) if row else None
            children = conn.execute(
                "SELECT id, title, status FROM tasks WHERE parent_task_id = ? ORDER BY id LIMIT ?",
                (task_id, BRIEF_CHILDREN),
            ).fetchall()
            return TaskBrief(
                id=task.id,
                title=task.title,
                description=task.description,
                status=task.status,
                priority=task.priority,
                assignee=self._name(conn, task.assignee_agent_id, names),
                reviewer=self._name(conn, task.reviewer_agent_id, names),
                creator=self._creator(conn, task, names),
                parent=parent,
                children=[(row["id"], row["title"], row["status"]) for row in children],
                comments=[(self._author(conn, c, names), c.text) for c in comments],
                worktree=task.worktree_path,
            )

    def authority(self, actor_agent_id: int, task: store.Task) -> bool:
        """Whether the agent may change and comment the task: it is the assignee, the reviewer
        or the creator, or the assignee is one of its subordinates."""
        with closing(db.connect(self._db_path)) as conn:
            return self._authority(conn, actor_agent_id, task)

    # Creating ----------------------------------------------------------------------------

    async def create_task(
        self,
        *,
        project_id: int,
        title: str,
        description: str = "",
        assignee_agent_id: int | None = None,
        reviewer_agent_id: int | None = None,
        parent_task_id: int | None = None,
        priority: store.TaskPriority = "normal",
        actor_agent_id: int | None,
        created_by: store.TaskCreator = "human",
        routine_id: int | None = None,
    ) -> store.Task:
        """A new task. An agent creates it for itself or for one of its subordinates (and only
        in its own project); a person or a routine may assign it to anyone of the project."""
        wakes: list[_Wake] = []
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            if actor_agent_id is not None:
                actor = store.get_agent(conn, actor_agent_id)
                if actor.project_id != project_id:
                    raise TaskAuthorityError("Você só cria tarefas no seu projeto.")
                self._check_can_assign(conn, actor_agent_id, assignee_agent_id)
                if reviewer_agent_id == actor_agent_id:
                    raise TaskAuthorityError(NOT_YOUR_REVIEW)
                self._check_parent_authority(conn, actor_agent_id, parent_task_id)
                created_by = "agent"
            self._check_in_project(conn, assignee_agent_id, project_id, "responsável")
            self._check_in_project(conn, reviewer_agent_id, project_id, "revisor")
            task = store.create_task(
                conn, project_id=project_id, title=title, description=description,
                assignee_agent_id=assignee_agent_id, reviewer_agent_id=reviewer_agent_id,
                parent_task_id=parent_task_id, priority=priority, created_by=created_by,
                created_by_agent_id=actor_agent_id, routine_id=routine_id, now=self._now(),
            )
            if assignee_agent_id is not None:
                wakes.append(_Wake(assignee_agent_id, "assignment", "assignment", 0))
        self._changed(task, "created")
        await self._wake_all(task.id, wakes)
        return task

    # Updating ----------------------------------------------------------------------------

    async def update_task(
        self,
        task_id: int,
        *,
        expected_revision: int,
        actor_agent_id: int | None,
        status: str | None = None,
        assignee_agent_id: int | None | store._Unset = store.UNSET,
        reviewer_agent_id: int | None | store._Unset = store.UNSET,
        parent_task_id: int | None | store._Unset = store.UNSET,
        priority: str | None = None,
        title: str | None = None,
        description: str | None = None,
        max_runs: int | None = None,
        comment: str | None = None,
        run_id: int | None = None,
    ) -> store.Task:
        """Change the task, once, if it is still at `expected_revision`.

        A change of status or of assignee leaves an `app` comment; the `comment` of the actor
        goes right after it. An agent needs the comment for any status change and may only make
        the changes the board allows; a person may make any. `done` of a task with a reviewer
        becomes `in_review`. With nothing to change but the comment, it is just a comment (no
        new revision)."""
        text = (comment or "").strip()
        wakes: list[_Wake] = []
        close = False
        change = "updated"
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            task = store.get_task(conn, task_id)
            actor = actor_agent_id
            if actor is not None and not self._authority(conn, actor, task):
                raise TaskAuthorityError()
            if task.revision != expected_revision:
                raise store.TaskRevisionError()
            if status is not None and status not in store.TASK_STATUSES:
                raise store.TaskValidationError("Estado da tarefa inválido.")
            if max_runs is not None and actor is not None:
                raise TaskAuthorityError("Só a pessoa pode mudar o teto de execuções.")
            cursor = store.last_comment_id(conn, task_id)

            fields: dict[str, Any] = {
                key: value
                for key, value in (
                    ("priority", priority), ("title", title), ("description", description),
                    ("max_runs", max_runs),
                )
                if value is not None
            }
            assignee = task.assignee_agent_id
            reviewer = task.reviewer_agent_id
            assignee_changed = (
                assignee_agent_id is not store.UNSET and assignee_agent_id != assignee
            )
            reviewer_changed = (
                reviewer_agent_id is not store.UNSET and reviewer_agent_id != reviewer
            )
            if assignee_changed:
                assert not isinstance(assignee_agent_id, store._Unset)
                if actor is not None:
                    self._check_can_assign(conn, actor, assignee_agent_id)
                self._check_in_project(conn, assignee_agent_id, task.project_id, "responsável")
                fields["assignee_agent_id"] = assignee = assignee_agent_id
            if reviewer_changed:
                assert not isinstance(reviewer_agent_id, store._Unset)
                if actor is not None:
                    self._check_agent_reviewer(task, actor, reviewer_agent_id)
                self._check_in_project(conn, reviewer_agent_id, task.project_id, "revisor")
                fields["reviewer_agent_id"] = reviewer = reviewer_agent_id

            if parent_task_id is not store.UNSET and parent_task_id != task.parent_task_id:
                assert not isinstance(parent_task_id, store._Unset)
                if actor is not None:
                    self._check_parent_authority(conn, actor, parent_task_id)
                fields["parent_task_id"] = parent_task_id

            new_status = task.status
            status_changed = status is not None and status != task.status
            if status_changed:
                assert status is not None
                # An agent never gets a say through a reviewer it just changed: the review
                # that counts is the one the task had. A person's change counts at once.
                new_status = self._next_status(
                    task, status, actor=actor,
                    reviewer=task.reviewer_agent_id if actor is not None else reviewer,
                    text=text,
                )
                fields["status"] = new_status
                if new_status == "blocked":
                    fields["blocked_reason"] = (
                        text[:BLOCKED_REASON_MAX] if text else "Bloqueada pela pessoa."
                    )
                elif task.status == "blocked":
                    fields["blocked_reason"] = None

            if not fields:
                if not text:
                    return task
                # Nothing to change but the comment: it is a comment.
                comment_row = self._comment_in(conn, task, text, actor, run_id)
                wakes = self._comment_wakes(conn, task, actor, comment_row.id - 1)
                change = "comment"
                updated = task
            else:
                updated = store.update_task(
                    conn, task_id, expected_revision=expected_revision, now=self._now(), **fields
                )
                who = self._who(conn, actor)
                names: dict[int, str] = {}
                if status_changed:
                    self._app(
                        conn, task_id, f"Status: {task.status} → {new_status}, {who}"
                    )
                if assignee_changed:
                    self._app(
                        conn, task_id,
                        f"Responsável: {self._name(conn, task.assignee_agent_id, names) or 'ninguém'}"
                        f" → {self._name(conn, assignee, names) or 'ninguém'}, {who}",
                    )
                if reviewer_changed:
                    self._app(
                        conn, task_id,
                        f"Revisor: {self._name(conn, task.reviewer_agent_id, names) or 'ninguém'}"
                        f" → {self._name(conn, reviewer, names) or 'ninguém'}, {who}",
                    )
                if text:
                    self._comment_in(conn, updated, text, actor, run_id)
                is_closing = (
                    new_status in store.TASK_CLOSED_STATUSES
                    and task.status not in store.TASK_CLOSED_STATUSES
                )
                close = is_closing and bool(updated.worktree_path)
                wakes = self._update_wakes(
                    conn, task, updated, actor=actor, cursor=cursor,
                    assignee_changed=assignee_changed, reviewer_changed=reviewer_changed,
                    status_changed=status_changed, text=text,
                )
        if close:
            self._org.schedule_worktree_removal(updated)
        self._changed(updated, change)
        await self._wake_all(task_id, wakes)
        return updated

    async def comment(
        self, task_id: int, text: str, *, author_agent_id: int | None, run_id: int | None = None
    ) -> store.Comment:
        """A comment on the task, by an agent with authority over it or by a person."""
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            task = store.get_task(conn, task_id)
            if author_agent_id is not None and not self._authority(conn, author_agent_id, task):
                raise TaskAuthorityError()
            row = self._comment_in(conn, task, text, author_agent_id, run_id)
            wakes = self._comment_wakes(conn, task, author_agent_id, row.id - 1)
        self._changed(task, "comment")
        await self._wake_all(task_id, wakes)
        return row

    async def unblock(self, task_id: int, *, expected_revision: int) -> store.Task:
        """The person lifts a block: the task goes back to `in_progress` (and wakes its
        assignee) or, without assignee, to `todo`. The count of runs starts again."""
        wakes: list[_Wake] = []
        with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
            task = store.get_task(conn, task_id)
            if task.revision != expected_revision:
                raise store.TaskRevisionError()
            if task.status != "blocked":
                raise TaskStateError("A tarefa não está bloqueada.")
            cursor = store.last_comment_id(conn, task_id)
            new_status = "in_progress" if task.assignee_agent_id is not None else "todo"
            updated = store.update_task(
                conn, task_id, expected_revision=expected_revision, now=self._now(),
                status=new_status, run_count=0, blocked_reason=None,
            )
            self._app(
                conn, task_id,
                f"Status: blocked → {new_status}, pela pessoa (a contagem de execuções recomeça)",
            )
            if task.assignee_agent_id is not None:
                wakes.append(_Wake(task.assignee_agent_id, "assignment", "unblocked", cursor))
        self._changed(updated, "updated")
        await self._wake_all(task_id, wakes)
        return updated

    # Rules ------------------------------------------------------------------------------

    @staticmethod
    def _authority(conn: sqlite3.Connection, actor: int, task: store.Task) -> bool:
        if actor in (task.assignee_agent_id, task.reviewer_agent_id, task.created_by_agent_id):
            return True
        return task.assignee_agent_id is not None and task.assignee_agent_id in store.subtree(
            conn, actor
        )

    @staticmethod
    def _check_can_assign(
        conn: sqlite3.Connection, actor: int, assignee: int | None
    ) -> None:
        if assignee is not None and assignee not in store.subtree(conn, actor):
            raise TaskAuthorityError(
                "Você só pode atribuir uma tarefa a você mesmo ou a um subordinado seu."
            )

    @staticmethod
    def _check_agent_reviewer(
        task: store.Task, actor: int, reviewer: int | None
    ) -> None:
        """What an agent may do to the reviewer: set it (never itself) while it creates the task
        or, as its creator, while the task is `todo`. Never clear it or swap it later: the
        review is imposed by the app and an agent could not skip it."""
        if reviewer == actor:
            raise TaskAuthorityError(NOT_YOUR_REVIEW)
        if actor != task.created_by_agent_id or task.status != "todo":
            raise TaskAuthorityError(REVIEWER_LOCKED)

    def _check_parent_authority(
        self, conn: sqlite3.Connection, actor: int, parent_task_id: int | None
    ) -> None:
        """An agent hangs a task under a parent it has authority over."""
        if parent_task_id is None:
            return
        try:
            parent = store.get_task(conn, parent_task_id)
        except store.TaskNotFoundError:
            return  # the store says the parent does not exist
        if not self._authority(conn, actor, parent):
            raise TaskAuthorityError(
                "Você não pode usar esta tarefa como tarefa-mãe: ela não é sua nem de um "
                "subordinado seu."
            )

    @staticmethod
    def _check_in_project(
        conn: sqlite3.Connection, agent_id: int | None, project_id: int, label: str
    ) -> None:
        if agent_id is None:
            return
        try:
            agent = store.get_agent(conn, agent_id)
        except store.NotFoundError:
            agent = None
        if agent is None or agent.project_id != project_id:
            raise store.TaskValidationError(
                f"O {label} precisa ser um agente do mesmo projeto da tarefa."
            )

    @staticmethod
    def _next_status(
        task: store.Task, new: str, *, actor: int | None, reviewer: int | None, text: str
    ) -> str:
        """The status the task really gets when `actor` asks for `new` (`done` can become
        `in_review`), or the error that says why not."""
        old = task.status
        if actor is None:
            if new == "in_review" and reviewer is None:
                raise TaskStateError("Defina um revisor antes de pôr a tarefa em revisão.")
            return new
        if old in store.TASK_CLOSED_STATUSES:
            raise TaskStateError("A tarefa está fechada: só a pessoa pode reabri-la.")
        if new == "cancelled":
            if actor != task.created_by_agent_id:
                raise TaskAuthorityError("Só quem criou a tarefa pode cancelá-la.")
        elif old == "in_review":
            if actor != reviewer or new not in ("done", "in_progress"):
                raise TaskStateError(
                    "Esta tarefa está em revisão: só o revisor pode aprová-la (done) ou "
                    "pedir mudanças (in_progress)."
                )
        elif (old, new) not in _AGENT_TRANSITIONS:
            raise TaskStateError(f"Transição inválida: {old} → {new}.")
        if not text:
            raise TaskStateError(COMMENT_REQUIRED)
        if new == "done" and reviewer is not None and reviewer != actor:
            return "in_review"
        return new

    def _update_wakes(
        self,
        conn: sqlite3.Connection,
        before: store.Task,
        after: store.Task,
        *,
        actor: int | None,
        cursor: int,
        assignee_changed: bool,
        reviewer_changed: bool,
        status_changed: bool,
        text: str,
    ) -> list[_Wake]:
        wakes: list[_Wake] = []
        closed = after.status in store.TASK_CLOSED_STATUSES
        if assignee_changed and after.assignee_agent_id is not None and not closed:
            _add_wake(wakes, _Wake(after.assignee_agent_id, "assignment", "assignment", 0))
        if (
            after.status == "in_review"
            and after.reviewer_agent_id is not None
            and (before.status != "in_review" or reviewer_changed)
        ):
            _add_wake(wakes, _Wake(after.reviewer_agent_id, "assignment", "review", 0))
        if (
            before.status == "in_review"
            and after.status == "in_progress"
            and after.assignee_agent_id not in (None, actor)
        ):
            _add_wake(
                wakes, _Wake(after.assignee_agent_id, "assignment", "changes", cursor)  # type: ignore[arg-type]
            )
        if closed and before.status not in store.TASK_CLOSED_STATUSES:
            creator = after.created_by_agent_id
            if creator is not None and creator != actor:
                _add_wake(wakes, _Wake(creator, "comment", "closed", cursor))
        if status_changed and after.status == "blocked" and actor is not None:
            creator = after.created_by_agent_id
            if creator is not None and creator != actor:
                _add_wake(wakes, _Wake(creator, "comment", "blocked", cursor))
        if text and not status_changed:
            for wake in self._comment_wakes(conn, after, actor, cursor):
                _add_wake(wakes, wake)
        return wakes

    @staticmethod
    def _comment_wakes(
        conn: sqlite3.Connection, task: store.Task, author: int | None, cursor: int
    ) -> list[_Wake]:
        """Who a comment wakes: the assignee of what a person writes (and the reviewer while
        the task is in review); the creator and the assignee of what an agent writes. Never the
        author, and nobody on a closed task."""
        if task.status in store.TASK_CLOSED_STATUSES:
            return []
        wakes: list[_Wake] = []
        if author is None:
            targets = [task.assignee_agent_id]
            if task.status == "in_review":
                targets.append(task.reviewer_agent_id)
        else:
            targets = [task.created_by_agent_id, task.assignee_agent_id]
        for agent_id in targets:
            if agent_id is not None and agent_id != author:
                _add_wake(wakes, _Wake(agent_id, "comment", "comment", cursor))
        return wakes

    # Comments ---------------------------------------------------------------------------

    def _comment_in(
        self,
        conn: sqlite3.Connection,
        task: store.Task,
        text: str,
        author: int | None,
        run_id: int | None,
    ) -> store.Comment:
        """The comment of an agent or of a person. The run only counts as having commented
        when it is of the same agent and of this task."""
        if author is not None and run_id is not None:
            try:
                run = store.get_run(conn, run_id)
            except store.NotFoundError:
                run_id = None
            else:
                if run.agent_id != author or run.task_id != task.id:
                    run_id = None
        else:
            run_id = None
        return store.add_comment(
            conn, task_id=task.id, author_kind="human" if author is None else "agent",
            author_agent_id=author, run_id=run_id, text=text, now=self._now(),
        )

    def _app(self, conn: sqlite3.Connection, task_id: int, text: str) -> None:
        store.add_comment(
            conn, task_id=task_id, author_kind="app", author_agent_id=None, run_id=None,
            text=text, now=self._now(),
        )

    # Names ------------------------------------------------------------------------------

    def _name(
        self, conn: sqlite3.Connection, agent_id: int | None, cache: dict[int, str]
    ) -> str | None:
        if agent_id is None:
            return None
        if agent_id not in cache:
            try:
                agent = store.get_agent(conn, agent_id)
            except store.NotFoundError:
                cache[agent_id] = REMOVED_AGENT
            else:
                cache[agent_id] = self._org._describe(agent)[0]
        return cache[agent_id]

    def _who(self, conn: sqlite3.Connection, actor: int | None) -> str:
        if actor is None:
            return "pela pessoa"
        return f"por {self._name(conn, actor, {})}"

    def _author(self, conn: sqlite3.Connection, comment: store.Comment, cache: dict[int, str]) -> str:
        if comment.author_kind == "human":
            return HUMAN_NAME
        if comment.author_kind == "app":
            return APP_NAME
        return self._name(conn, comment.author_agent_id, cache) or REMOVED_AGENT

    def _creator(
        self, conn: sqlite3.Connection, task: store.Task, cache: dict[int, str]
    ) -> str | None:
        if task.created_by_agent_id is not None:
            return self._name(conn, task.created_by_agent_id, cache)
        if task.created_by == "human":
            return HUMAN_NAME
        if task.routine_id is not None:
            try:
                return f"Rotina {store.get_routine(conn, task.routine_id).name}"
            except store.NotFoundError:
                pass
        return "Rotina"

    # After the commit -----------------------------------------------------------------------

    def _now(self) -> int:
        return int(self._clock())

    def _changed(self, task: store.Task, change: str) -> None:
        self._publish(
            "task",
            {
                "id": task.id, "project_id": task.project_id, "status": task.status,
                "revision": task.revision, "change": change,
            },
        )

    async def _wake_all(self, task_id: int, wakes: list[_Wake]) -> None:
        for wake in wakes:
            payload = {
                "task_id": task_id, "since_comment_id": wake.since_comment_id,
                "reason": wake.reason,
            }
            try:
                await self._org.wake(
                    wake.agent_id, source=wake.source,  # type: ignore[arg-type]
                    task_id=task_id, payload=payload,
                )
            except Exception as error:
                self._wake_failed(task_id, wake, error)

    def _wake_failed(self, task_id: int, wake: _Wake, error: Exception) -> None:
        """The change is already saved: say on the task that the agent was not woken."""
        if isinstance(error, store.OrgError):
            reason = str(error)
            logger.warning("Não foi possível acordar o agente %s: %s", wake.agent_id, reason)
        else:
            reason = "erro inesperado (veja o log do Maestro)"
            logger.exception("Falha ao acordar o agente %s", wake.agent_id)
        try:
            with closing(db.connect(self._db_path)) as conn, db.transaction(conn):
                name = self._name(conn, wake.agent_id, {}) or REMOVED_AGENT
                self._app(conn, task_id, f"Não foi possível acordar {name}: {reason}")
                task = store.get_task(conn, task_id)
        except Exception:
            logger.exception("Não foi possível registrar a falha de despertar na tarefa %s", task_id)
            return
        self._changed(task, "comment")
