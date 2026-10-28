"""TaskService: the board (authority, transitions, enforced review, wakeups). `wake` is spied:
nothing here starts an agent."""

import json
import logging
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.tasks import TaskAuthorityError, TaskService, TaskStateError

pytestmark = pytest.mark.anyio

NOW = 1_700_000_000


class FakeOrg:
    """What `TaskService` asks of `OrgService`: wake, the name of an agent and the removal
    of a worktree."""

    def __init__(self) -> None:
        self.wakes: list[dict[str, Any]] = []
        self.removals: list[int] = []
        self.wake_error: Exception | None = None

    async def wake(self, agent_id: int, **kwargs: Any) -> None:
        if self.wake_error is not None:
            raise self.wake_error
        self.wakes.append({"agent_id": agent_id, **kwargs})

    def _describe(self, agent: store.Agent) -> tuple[str, str]:
        return agent.name, ""

    def schedule_worktree_removal(self, task: store.Task) -> None:
        self.removals.append(task.id)


class Board:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "maestro.db"
        db.init_db(self.db_path)
        self.now = NOW
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.org = FakeOrg()
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            for pid in (1, 2):
                conn.execute(
                    "INSERT INTO projects (id, name, path, color, position, created_at)"
                    " VALUES (?, 'p', ?, '#fff', 0, 0)",
                    (pid, str(tmp_path / f"p{pid}")),
                )
            self.cto = store.create_agent(
                conn, slug="cto", name="CTO", project_id=1, reports_to=None, now=1
            ).id
            self.worker = store.create_agent(
                conn, slug="trabalhador", name="Trabalhador", project_id=1,
                reports_to=self.cto, now=1,
            ).id
            self.reviewer = store.create_agent(
                conn, slug="revisor", name="Revisor", project_id=1, reports_to=self.cto, now=1
            ).id
            self.other = store.create_agent(
                conn, slug="outro", name="Outro", project_id=2, reports_to=None, now=1
            ).id
        self.tasks = TaskService(
            self.db_path,
            org=self.org,  # type: ignore[arg-type]
            publish=lambda type_, data: self.events.append((type_, data)),
            clock=lambda: self.now,
        )

    def task(self, task_id: int) -> store.Task:
        with closing(db.connect(self.db_path)) as conn:
            return store.get_task(conn, task_id)

    def comments(self, task_id: int) -> list[store.Comment]:
        with closing(db.connect(self.db_path)) as conn:
            return store.list_comments(conn, task_id)

    def texts(self, task_id: int) -> list[tuple[str, str]]:
        return [(c.author_kind, c.text) for c in self.comments(task_id)]

    def run(self, agent_id: int, task_id: int | None, outcome: str = "running") -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            return store.insert_run(
                conn, agent_id=agent_id, session_id=None, source="assignment", routine_id=None,
                scheduled_for=None, started_at=NOW, task_id=task_id, outcome=outcome,
            ).id

    def commented(self, run_id: int) -> bool:
        with closing(db.connect(self.db_path)) as conn:
            return store.get_run(conn, run_id).commented

    async def new(self, **fields: Any) -> store.Task:
        fields.setdefault("project_id", 1)
        fields.setdefault("title", "Fazer")
        fields.setdefault("actor_agent_id", None)
        task = await self.tasks.create_task(**fields)
        self.org.wakes.clear()
        return task


@pytest.fixture
def board(tmp_path: Path) -> Board:
    return Board(tmp_path)


# Creating ---------------------------------------------------------------------------


async def test_create_task_by_agent_assigns_only_subtree(board):
    mine = await board.tasks.create_task(
        project_id=1, title="Para o time", assignee_agent_id=board.worker,
        actor_agent_id=board.cto,
    )
    assert (mine.created_by, mine.created_by_agent_id) == ("agent", board.cto)
    assert mine.assignee_agent_id == board.worker
    assert board.org.wakes == [
        {
            "agent_id": board.worker, "source": "assignment", "task_id": mine.id,
            "payload": {"task_id": mine.id, "since_comment_id": 0, "reason": "assignment"},
        }
    ]
    # To oneself is fine.
    own = await board.tasks.create_task(
        project_id=1, title="Minha", assignee_agent_id=board.worker, actor_agent_id=board.worker
    )
    assert own.assignee_agent_id == board.worker
    # A peer, a boss and an agent of another project are out of reach.
    for target in (board.reviewer, board.cto, board.other):
        with pytest.raises(TaskAuthorityError, match="subordinado"):
            await board.tasks.create_task(
                project_id=1, title="Fora", assignee_agent_id=target, actor_agent_id=board.worker
            )
    with closing(db.connect(board.db_path)) as conn:
        assert len(store.list_tasks(conn)) == 2


async def test_create_task_validates_agents_belong_to_project(board):
    with pytest.raises(store.TaskValidationError, match="projeto"):
        await board.tasks.create_task(
            project_id=1, title="x", assignee_agent_id=board.other, actor_agent_id=None
        )
    with pytest.raises(store.TaskValidationError, match="projeto"):
        await board.tasks.create_task(
            project_id=1, title="x", reviewer_agent_id=board.other, actor_agent_id=None
        )
    with pytest.raises(store.TaskValidationError, match="projeto"):
        await board.tasks.create_task(
            project_id=1, title="x", assignee_agent_id=999, actor_agent_id=None
        )


async def test_create_task_by_human_and_routine(board):
    human = await board.tasks.create_task(project_id=1, title="a", actor_agent_id=None)
    assert (human.created_by, human.created_by_agent_id) == ("human", None)
    assert board.org.wakes == []  # nobody assigned, nobody woken
    routine = await board.tasks.create_task(
        project_id=1, title="b", actor_agent_id=None, created_by="routine", routine_id=None,
        assignee_agent_id=board.worker,
    )
    assert routine.created_by == "routine"
    assert [w["agent_id"] for w in board.org.wakes] == [board.worker]


async def test_create_task_without_assignee_publishes_and_does_not_wake(board):
    task = await board.tasks.create_task(project_id=1, title="solta", actor_agent_id=board.cto)
    assert board.org.wakes == []
    assert board.events[-1][0] == "task"
    assert board.events[-1][1]["id"] == task.id


# Authority ----------------------------------------------------------------------------


async def test_agent_cannot_update_task_outside_authority(board):
    task = await board.new(assignee_agent_id=board.reviewer)
    before = board.task(task.id)
    with pytest.raises(
        TaskAuthorityError,
        match="Você não pode alterar esta tarefa: ela não é sua nem de um subordinado seu.",
    ):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            priority="urgent",
        )
    with pytest.raises(TaskAuthorityError):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            assignee_agent_id=board.worker,
        )
    with pytest.raises(TaskAuthorityError):
        await board.tasks.comment(task.id, "oi", author_agent_id=board.worker)
    assert board.task(task.id) == before
    assert board.comments(task.id) == []
    assert board.org.wakes == []


async def test_authority_rules(board):
    mine = await board.new(assignee_agent_id=board.worker)
    reviewed = await board.new(assignee_agent_id=board.worker, reviewer_agent_id=board.reviewer)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        created = store.create_task(
            conn, project_id=1, title="c", assignee_agent_id=board.worker, created_by="agent",
            created_by_agent_id=board.reviewer, now=NOW,
        )
    by_peer = await board.new(assignee_agent_id=board.reviewer)
    with closing(db.connect(board.db_path)) as conn:
        get = lambda tid: store.get_task(conn, tid)  # noqa: E731
        assert board.tasks.authority(board.worker, get(mine.id))  # assignee
        assert board.tasks.authority(board.cto, get(mine.id))  # boss of the assignee
        assert board.tasks.authority(board.reviewer, get(reviewed.id))  # reviewer
        assert board.tasks.authority(board.reviewer, get(created.id))  # creator
        assert not board.tasks.authority(board.worker, get(by_peer.id))
        assert not board.tasks.authority(board.other, get(mine.id))


async def test_agent_may_comment_with_authority_boss_of_assignee(board):
    task = await board.new(assignee_agent_id=board.worker)
    comment = await board.tasks.comment(task.id, "Como está?", author_agent_id=board.cto)
    assert comment.author_kind == "agent" and comment.author_agent_id == board.cto


async def test_agent_cannot_cancel_a_task_it_did_not_create(board):
    task = await board.new(assignee_agent_id=board.worker)  # human-created
    with pytest.raises(TaskAuthorityError, match="cancel"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.cto,
            status="cancelled", comment="não precisa mais",
        )
    assert board.task(task.id).status == "todo"
    # The creator can.
    own = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.worker)
    done = await board.tasks.update_task(
        own.id, expected_revision=own.revision, actor_agent_id=board.cto, status="cancelled",
        comment="mudou o plano",
    )
    assert done.status == "cancelled" and done.closed_at == NOW


async def test_agent_cannot_change_the_run_cap(board):
    task = await board.new(assignee_agent_id=board.worker)
    with pytest.raises(TaskAuthorityError, match="teto"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker, max_runs=99
        )
    human = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, max_runs=99
    )
    assert human.max_runs == 99


async def test_agent_reassigns_only_inside_its_subtree(board):
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.cto)
    moved = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.cto,
        assignee_agent_id=board.worker,
    )
    assert moved.assignee_agent_id == board.worker
    with pytest.raises(TaskAuthorityError, match="subordinado"):
        await board.tasks.update_task(
            task.id, expected_revision=moved.revision, actor_agent_id=board.worker,
            assignee_agent_id=board.reviewer,
        )
    assert board.task(task.id).assignee_agent_id == board.worker


# Transitions -----------------------------------------------------------------------------


async def test_status_change_by_agent_requires_comment(board):
    task = await board.new(assignee_agent_id=board.worker)
    for empty in (None, "", "   "):
        with pytest.raises(TaskStateError, match="Diga o que mudou"):
            await board.tasks.update_task(
                task.id, expected_revision=task.revision, actor_agent_id=board.worker,
                status="in_progress", comment=empty,
            )
    assert board.task(task.id).status == "todo"
    updated = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="Começando",
    )
    assert updated.status == "in_progress"
    assert updated.revision == task.revision + 1


async def test_human_changes_status_without_comment(board):
    task = await board.new(assignee_agent_id=board.worker)
    updated = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="done"
    )
    assert updated.status == "done"  # a person may do any transition
    reopened = await board.tasks.update_task(
        task.id, expected_revision=updated.revision, actor_agent_id=None, status="todo"
    )
    assert reopened.status == "todo" and reopened.closed_at is None


async def test_invalid_transitions_by_agent(board):
    task = await board.new(assignee_agent_id=board.worker)
    with pytest.raises(TaskStateError, match="todo"):
        await board.tasks.update_task(  # todo -> done
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            status="done", comment="pronto",
        )
    with pytest.raises(TaskStateError):  # an agent never sets in_review by hand
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            status="in_review", comment="olhem",
        )
    with pytest.raises(store.TaskValidationError):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=None, status="voando"
        )


async def test_agent_cannot_reopen_a_closed_task(board):
    task = await board.new(assignee_agent_id=board.worker)
    closed = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="done"
    )
    with pytest.raises(TaskStateError, match="fechada"):
        await board.tasks.update_task(
            task.id, expected_revision=closed.revision, actor_agent_id=board.worker,
            status="in_progress", comment="voltei",
        )


async def test_blocked_requires_reason(board):
    task = await board.new(assignee_agent_id=board.worker, project_id=1)
    started = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou",
    )
    with pytest.raises(TaskStateError, match="comentário"):
        await board.tasks.update_task(
            task.id, expected_revision=started.revision, actor_agent_id=board.worker,
            status="blocked",
        )
    blocked = await board.tasks.update_task(
        task.id, expected_revision=started.revision, actor_agent_id=board.worker,
        status="blocked", comment="Falta acesso ao banco",
    )
    assert blocked.status == "blocked" and blocked.blocked_reason == "Falta acesso ao banco"
    resumed = await board.tasks.update_task(
        task.id, expected_revision=blocked.revision, actor_agent_id=board.worker,
        status="in_progress", comment="Acesso liberado",
    )
    assert resumed.status == "in_progress" and resumed.blocked_reason is None


async def test_app_comment_on_status_change(board):
    task = await board.new(assignee_agent_id=board.worker)
    task = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="Começando",
    )
    task = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="Entregue",
    )
    assert board.texts(task.id) == [
        ("app", "Status: todo → in_progress, por Trabalhador"),
        ("agent", "Começando"),
        ("app", "Status: in_progress → done, por Trabalhador"),
        ("agent", "Entregue"),
    ]
    assert [c.author_agent_id for c in board.comments(task.id)] == [
        None, board.worker, None, board.worker
    ]


async def test_app_comment_on_assignee_change_names_both(board):
    task = await board.new(assignee_agent_id=board.worker)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None,
        assignee_agent_id=board.reviewer,
    )
    (kind, text), = board.texts(task.id)
    assert kind == "app"
    assert "Trabalhador" in text and "Revisor" in text and "pessoa" in text
    assert [w["agent_id"] for w in board.org.wakes] == [board.reviewer]
    assert board.org.wakes[0]["payload"]["reason"] == "assignment"


async def test_update_fields_without_status_has_no_app_comment_and_bumps_revision(board):
    task = await board.new(assignee_agent_id=board.worker)
    updated = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        priority="high", title="Novo título", description="Mais detalhes",
    )
    assert (updated.priority, updated.title, updated.description) == (
        "high", "Novo título", "Mais detalhes"
    )
    assert updated.revision == task.revision + 1
    assert board.comments(task.id) == []
    assert board.org.wakes == []


async def test_stale_revision_changes_nothing(board):
    task = await board.new(assignee_agent_id=board.worker)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, priority="high"
    )
    with pytest.raises(store.TaskRevisionError):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=None, status="blocked"
        )
    assert board.task(task.id).status == "todo"
    assert board.comments(task.id) == []


async def test_update_with_only_a_comment_is_a_comment(board):
    task = await board.new(assignee_agent_id=board.worker)
    same = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, comment="Atenção"
    )
    assert same.revision == task.revision
    assert board.texts(task.id) == [("human", "Atenção")]
    assert [w["agent_id"] for w in board.org.wakes] == [board.worker]


# Review ----------------------------------------------------------------------------------


async def started(board, *, reviewer: int | None = None) -> store.Task:
    task = await board.new(
        assignee_agent_id=board.worker, reviewer_agent_id=reviewer, actor_agent_id=board.cto
    )
    return await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou",
    )


async def test_done_without_reviewer_is_final(board):
    task = await started(board)
    done = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    assert done.status == "done" and done.closed_at == NOW


async def test_done_with_reviewer_goes_in_review_and_wakes_reviewer(board):
    task = await started(board, reviewer=board.reviewer)
    board.org.wakes.clear()
    result = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="Feito, PR #1",
    )
    assert result.status == "in_review" and result.closed_at is None
    assert board.org.removals == []
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [
        (board.reviewer, "assignment")
    ]
    wake = board.org.wakes[0]
    assert wake["task_id"] == task.id
    assert wake["payload"]["reason"] == "review"
    assert wake["payload"]["task_id"] == task.id
    assert ("app", "Status: in_progress → in_review, por Trabalhador") in board.texts(task.id)


async def test_in_review_is_decided_only_by_the_reviewer(board):
    task = await started(board, reviewer=board.reviewer)
    reviewing = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    for actor in (board.worker, board.cto):
        with pytest.raises(TaskStateError, match="revisor"):
            await board.tasks.update_task(
                task.id, expected_revision=reviewing.revision, actor_agent_id=actor,
                status="done", comment="aprovo eu mesmo",
            )
    assert board.task(task.id).status == "in_review"


async def test_reviewer_done_closes_and_wakes_creator_with_comment(board):
    task = await started(board, reviewer=board.reviewer)
    reviewing = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    board.org.wakes.clear()
    last_before = board.comments(task.id)[-1].id
    done = await board.tasks.update_task(
        task.id, expected_revision=reviewing.revision, actor_agent_id=board.reviewer,
        status="done", comment="Aprovado",
    )
    assert done.status == "done" and done.closed_at == NOW
    # Only the creator (the CTO) is woken, with the comment that closes.
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [(board.cto, "comment")]
    payload = board.org.wakes[0]["payload"]
    assert payload["since_comment_id"] == last_before
    assert payload["task_id"] == task.id
    new = [c for c in board.comments(task.id) if c.id > payload["since_comment_id"]]
    assert ("agent", "Aprovado") in [(c.author_kind, c.text) for c in new]


async def test_reviewer_changes_requested_wakes_assignee(board):
    task = await started(board, reviewer=board.reviewer)
    reviewing = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    board.org.wakes.clear()
    back = await board.tasks.update_task(
        task.id, expected_revision=reviewing.revision, actor_agent_id=board.reviewer,
        status="in_progress", comment="Falta teste",
    )
    assert back.status == "in_progress" and back.assignee_agent_id == board.worker
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [
        (board.worker, "assignment")
    ]
    assert board.org.wakes[0]["payload"]["reason"] == "changes"
    assert board.org.wakes[0]["payload"]["since_comment_id"] > 0


async def test_closing_without_agent_creator_wakes_nobody(board):
    task = await board.new(assignee_agent_id=board.worker)  # created by a person
    task = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou",
    )
    board.org.wakes.clear()
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    assert board.org.wakes == []


async def test_closing_does_not_wake_the_closing_creator(board):
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.worker)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.cto,
        status="cancelled", comment="desisto",
    )
    assert board.org.wakes == []


async def test_closing_always_schedules_the_removal_of_the_worktree(board):
    task = await board.new(assignee_agent_id=board.worker)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        task = store.update_task(
            conn, task.id, expected_revision=task.revision, now=NOW,
            worktree_path="/x/.claude/worktrees/tarefa-1", branch="tarefa/1-x",
        )
    task = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="done"
    )
    assert board.org.removals == [task.id]
    # It is asked for even without a worktree recorded: one may be in the middle of its
    # creation, and the removal does nothing when there is none.
    plain = await board.new(assignee_agent_id=board.worker)
    await board.tasks.update_task(
        plain.id, expected_revision=plain.revision, actor_agent_id=None, status="cancelled"
    )
    assert board.org.removals == [task.id, plain.id]


async def test_agent_cannot_clear_the_reviewer_to_skip_the_review(board):
    task = await started(board, reviewer=board.reviewer)
    before = board.task(task.id)
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            reviewer_agent_id=None,
        )
    # Not even the boss that created the task, once it left `todo`.
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.cto,
            reviewer_agent_id=None,
        )
    assert board.task(task.id) == before
    done = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    assert done.status == "in_review"  # the review still stands


async def test_agent_cannot_make_itself_reviewer_to_close_the_review(board):
    task = await started(board, reviewer=board.reviewer)
    reviewing = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=reviewing.revision, actor_agent_id=board.worker,
            reviewer_agent_id=board.worker, status="done", comment="eu mesmo aprovo",
        )
    after = board.task(task.id)
    assert (after.status, after.reviewer_agent_id) == ("in_review", board.reviewer)
    assert after.revision == reviewing.revision


async def test_agent_never_sets_itself_as_reviewer(board):
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.create_task(
            project_id=1, title="x", assignee_agent_id=board.worker,
            reviewer_agent_id=board.cto, actor_agent_id=board.cto,
        )
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.worker)
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.cto,
            reviewer_agent_id=board.cto,
        )
    assert board.task(task.id).reviewer_agent_id is None


async def test_only_the_creator_sets_the_reviewer_and_only_in_todo(board):
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.worker)
    # The assignee is not the creator.
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=board.worker,
            reviewer_agent_id=board.reviewer,
        )
    assert board.task(task.id).reviewer_agent_id is None
    # The creator, while the task is in `todo`.
    set_ = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.cto,
        reviewer_agent_id=board.reviewer,
    )
    assert set_.reviewer_agent_id == board.reviewer
    assert board.org.wakes == []  # not in review yet: nobody to call
    # Once started, not even the creator changes it.
    started_ = await board.tasks.update_task(
        task.id, expected_revision=set_.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou",
    )
    with pytest.raises(store.OrgError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=started_.revision, actor_agent_id=board.cto,
            reviewer_agent_id=board.worker,
        )
    assert board.task(task.id).reviewer_agent_id == board.reviewer


async def test_person_changes_or_clears_the_reviewer_any_time(board):
    task = await started(board, reviewer=board.reviewer)
    cleared = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, reviewer_agent_id=None
    )
    assert cleared.reviewer_agent_id is None


async def test_status_decision_uses_the_reviewer_the_task_had(board):
    # The creator sets the reviewer and starts the task in the same call: `todo` allowed it,
    # and the new reviewer is not yet the one that decides.
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.cto)
    updated = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.cto,
        reviewer_agent_id=board.reviewer, status="in_progress", comment="começo",
    )
    assert updated.reviewer_agent_id == board.reviewer
    closed = await board.tasks.update_task(
        task.id, expected_revision=updated.revision, actor_agent_id=board.cto,
        status="done", comment="pronto",
    )
    assert closed.status == "in_review"


async def test_agent_needs_authority_over_the_parent_task(board):
    mine = await board.new(assignee_agent_id=board.worker)
    foreign = await board.new(assignee_agent_id=board.reviewer)
    child = await board.tasks.create_task(
        project_id=1, title="filha", parent_task_id=mine.id, actor_agent_id=board.worker,
        assignee_agent_id=board.worker,
    )
    assert child.parent_task_id == mine.id
    with pytest.raises(TaskAuthorityError, match="tarefa-mãe"):
        await board.tasks.create_task(
            project_id=1, title="intrusa", parent_task_id=foreign.id,
            actor_agent_id=board.worker,
        )
    with closing(db.connect(board.db_path)) as conn:
        assert [t.title for t in store.list_tasks(conn)] == ["Fazer", "Fazer", "filha"]
    # Moving a task under a foreign parent is refused too, and nothing changes.
    with pytest.raises(TaskAuthorityError, match="tarefa-mãe"):
        await board.tasks.update_task(
            child.id, expected_revision=child.revision, actor_agent_id=board.worker,
            parent_task_id=foreign.id,
        )
    assert board.task(child.id).parent_task_id == mine.id
    # A person may; so may an agent with authority over the new parent.
    moved = await board.tasks.update_task(
        child.id, expected_revision=child.revision, actor_agent_id=None,
        parent_task_id=foreign.id,
    )
    assert moved.parent_task_id == foreign.id
    own = await board.new(assignee_agent_id=board.worker)
    again = await board.tasks.update_task(
        child.id, expected_revision=moved.revision, actor_agent_id=board.cto,
        parent_task_id=own.id,
    )
    assert again.parent_task_id == own.id


async def test_human_puts_in_review_needs_a_reviewer_and_wakes_it(board):
    task = await board.new(assignee_agent_id=board.worker)
    with pytest.raises(TaskStateError, match="revisor"):
        await board.tasks.update_task(
            task.id, expected_revision=task.revision, actor_agent_id=None, status="in_review"
        )
    with_reviewer = await board.new(assignee_agent_id=board.worker, reviewer_agent_id=board.reviewer)
    await board.tasks.update_task(
        with_reviewer.id, expected_revision=with_reviewer.revision, actor_agent_id=None,
        status="in_review",
    )
    assert [w["agent_id"] for w in board.org.wakes] == [board.reviewer]


# Comments and wakeups -------------------------------------------------------------------------


async def test_human_comment_wakes_assignee(board):
    task = await board.new(assignee_agent_id=board.worker, reviewer_agent_id=board.reviewer)
    comment = await board.tasks.comment(task.id, "Pode priorizar?", author_agent_id=None)
    assert (comment.author_kind, comment.author_agent_id) == ("human", None)
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [(board.worker, "comment")]
    payload = board.org.wakes[0]["payload"]
    assert payload["since_comment_id"] == comment.id - 1  # cursor: before the event
    assert payload["reason"] == "comment" and payload["task_id"] == task.id
    assert board.org.wakes[0]["task_id"] == task.id


async def test_human_comment_wakes_reviewer_too_when_in_review(board):
    task = await started(board, reviewer=board.reviewer)
    reviewing = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="done", comment="pronto",
    )
    board.org.wakes.clear()
    await board.tasks.comment(reviewing.id, "Cuidado com o prazo", author_agent_id=None)
    assert sorted(w["agent_id"] for w in board.org.wakes) == sorted([board.worker, board.reviewer])


async def test_agent_comment_wakes_creator_not_self(board):
    task = await board.new(actor_agent_id=board.cto, assignee_agent_id=board.worker)
    await board.tasks.comment(task.id, "Dúvida sobre o escopo", author_agent_id=board.worker)
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [(board.cto, "comment")]
    board.org.wakes.clear()
    # The creator comments: the assignee is woken, not the creator itself.
    await board.tasks.comment(task.id, "Faça só o básico", author_agent_id=board.cto)
    assert [(w["agent_id"], w["source"]) for w in board.org.wakes] == [(board.worker, "comment")]


async def test_agent_comment_wakes_each_agent_once(board):
    task = await board.new(
        actor_agent_id=board.cto, assignee_agent_id=board.cto, reviewer_agent_id=board.reviewer
    )
    await board.tasks.comment(task.id, "nota", author_agent_id=board.reviewer)
    assert [w["agent_id"] for w in board.org.wakes] == [board.cto]  # creator == assignee


async def test_comment_on_closed_task_wakes_nobody(board):
    task = await board.new(assignee_agent_id=board.worker)
    closed = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="done"
    )
    board.org.wakes.clear()
    await board.tasks.comment(closed.id, "obrigado", author_agent_id=None)
    assert board.org.wakes == []
    assert board.texts(closed.id)[-1] == ("human", "obrigado")


async def test_comment_run_id_only_counts_for_the_same_agent_and_task(board):
    task = await board.new(assignee_agent_id=board.worker)
    other_task = await board.new(assignee_agent_id=board.worker)
    mine = board.run(board.worker, task.id)
    foreign_agent = board.run(board.reviewer, task.id)
    foreign_task = board.run(board.worker, other_task.id)
    await board.tasks.comment(task.id, "a", author_agent_id=board.worker, run_id=foreign_agent)
    await board.tasks.comment(task.id, "b", author_agent_id=board.worker, run_id=foreign_task)
    await board.tasks.comment(task.id, "c", author_agent_id=board.worker, run_id=424242)
    assert [board.commented(r) for r in (foreign_agent, foreign_task)] == [False, False]
    assert {c.run_id for c in board.comments(task.id)} == {None}
    comment = await board.tasks.comment(task.id, "d", author_agent_id=board.worker, run_id=mine)
    assert comment.run_id == mine and board.commented(mine)


async def test_update_comment_carries_run_id(board):
    task = await board.new(assignee_agent_id=board.worker)
    run_id = board.run(board.worker, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou", run_id=run_id,
    )
    assert board.commented(run_id)
    agent_comment = [c for c in board.comments(task.id) if c.author_kind == "agent"][0]
    assert agent_comment.run_id == run_id
    app_comment = [c for c in board.comments(task.id) if c.author_kind == "app"][0]
    assert app_comment.run_id is None


async def test_comment_validation(board):
    task = await board.new(assignee_agent_id=board.worker)
    with pytest.raises(store.TaskValidationError):
        await board.tasks.comment(task.id, "", author_agent_id=None)
    with pytest.raises(store.TaskNotFoundError):
        await board.tasks.comment(999, "oi", author_agent_id=None)
    assert board.org.wakes == []


async def test_wake_failure_keeps_the_change_and_leaves_a_comment(board, caplog):
    task = await board.new(assignee_agent_id=board.worker)
    board.org.wake_error = store.OrgError("A fila do agente está cheia.")
    with caplog.at_level(logging.WARNING):
        comment = await board.tasks.comment(task.id, "Oi", author_agent_id=None)
    assert board.comments(task.id)[0] == comment  # the comment stays
    texts = board.texts(task.id)
    assert texts[0] == ("human", "Oi")
    assert texts[-1][0] == "app"
    assert "Trabalhador" in texts[-1][1] and "fila" in texts[-1][1]
    assert "fila do agente" in caplog.text
    # The same on update and unexpected errors: nothing is raised.
    board.org.wake_error = RuntimeError("quebrou")
    updated = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None,
        assignee_agent_id=board.reviewer,
    )
    assert updated.assignee_agent_id == board.reviewer


# Unblock -------------------------------------------------------------------------------------


async def blocked_task(board, *, assignee: int | None) -> store.Task:
    task = await board.new(assignee_agent_id=assignee)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        return store.update_task(
            conn, task.id, expected_revision=task.revision, now=NOW, status="blocked",
            run_count=20, blocked_reason="Atingiu o teto de 20 execuções.",
        )


async def test_unblock_resets_run_count(board):
    task = await blocked_task(board, assignee=board.worker)
    result = await board.tasks.unblock(task.id, expected_revision=task.revision)
    assert (result.status, result.run_count, result.blocked_reason) == ("in_progress", 0, None)
    assert board.org.wakes[0]["agent_id"] == board.worker
    assert board.org.wakes[0]["source"] == "assignment"
    assert board.org.wakes[0]["task_id"] == task.id
    assert board.texts(task.id)[-1][0] == "app"
    assert "blocked → in_progress" in board.texts(task.id)[-1][1]


async def test_unblock_without_assignee_goes_to_todo_and_wakes_nobody(board):
    task = await blocked_task(board, assignee=None)
    result = await board.tasks.unblock(task.id, expected_revision=task.revision)
    assert (result.status, result.run_count) == ("todo", 0)
    assert board.org.wakes == []


async def test_unblock_requires_blocked_task_and_fresh_revision(board):
    task = await board.new(assignee_agent_id=board.worker)
    with pytest.raises(TaskStateError, match="bloqueada"):
        await board.tasks.unblock(task.id, expected_revision=task.revision)
    blocked = await blocked_task(board, assignee=board.worker)
    with pytest.raises(store.TaskRevisionError):
        await board.tasks.unblock(blocked.id, expected_revision=blocked.revision - 1)


# Reading ---------------------------------------------------------------------------------------


async def test_brief_since_cursor_lists_only_new_comments(board):
    parent = await board.new(title="Mãe", assignee_agent_id=board.cto)
    task = await board.new(
        assignee_agent_id=board.worker, reviewer_agent_id=board.reviewer,
        actor_agent_id=board.cto, parent_task_id=parent.id, title="Filha",
        description="Detalhes",
    )
    child = await board.new(title="Neta", parent_task_id=task.id)
    first = await board.tasks.comment(task.id, "primeiro", author_agent_id=None)
    await board.tasks.comment(task.id, "segundo", author_agent_id=board.worker)
    await board.tasks.comment(task.id, "terceiro", author_agent_id=board.cto)
    brief = board.tasks.brief(task.id, since_comment_id=first.id)
    assert brief.comments == [("Trabalhador", "segundo"), ("CTO", "terceiro")]
    assert (brief.id, brief.title, brief.description) == (task.id, "Filha", "Detalhes")
    assert (brief.assignee, brief.reviewer, brief.creator) == ("Trabalhador", "Revisor", "CTO")
    assert brief.parent == (parent.id, "Mãe")
    assert brief.children == [(child.id, "Neta", "todo")]
    assert brief.status == "todo" and brief.priority == "normal" and brief.worktree is None
    everything = board.tasks.brief(task.id)
    assert [text for _, text in everything.comments] == ["primeiro", "segundo", "terceiro"]
    assert everything.comments[0][0] == "Pessoa"


async def test_brief_lists_at_most_the_last_twenty_comments(board):
    task = await board.new(assignee_agent_id=board.worker)
    for number in range(25):
        await board.tasks.comment(task.id, f"c{number}", author_agent_id=None)
    brief = board.tasks.brief(task.id)
    assert [text for _, text in brief.comments] == [f"c{n}" for n in range(5, 25)]


async def test_get_returns_a_serializable_dict_with_everything(board):
    task = await board.new(assignee_agent_id=board.worker)
    run_id = board.run(board.worker, task.id, outcome="concluded")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.upsert_pr(
            conn, url="https://github.com/o/r/pull/1", agent_id=board.worker, session_id=None,
            created_at=NOW,
        )
        conn.execute(
            "UPDATE agent_prs SET task_id = ? WHERE url = ?",
            (task.id, "https://github.com/o/r/pull/1"),
        )
        store.create_decision(
            conn, project_id=1, task_id=task.id, agent_id=board.worker, run_id=run_id,
            session_id=None, question="Qual?", options=["a", "b"], now=NOW,
        )
        store.add_ci_receipt(
            conn, project_id=1, task_id=task.id, agent_id=board.worker, run_id=run_id,
            run_url="https://x", repository="o/r", head_sha="abc", conclusion="success",
            jobs=[{"name": "t"}], receipt="r1", now=NOW,
        )
    await board.tasks.comment(task.id, "oi", author_agent_id=None)
    data = board.tasks.get(task.id)
    json.dumps(data)  # serializable as is
    assert data["task"]["id"] == task.id and data["task"]["title"] == "Fazer"
    assert [c["text"] for c in data["comments"]] == ["oi"]
    assert [r["id"] for r in data["runs"]] == [run_id]
    assert [d["question"] for d in data["decisions"]] == ["Qual?"]
    assert [p["url"] for p in data["prs"]] == ["https://github.com/o/r/pull/1"]
    assert [r["receipt"] for r in data["ci"]] == ["r1"]
    with pytest.raises(store.TaskNotFoundError):
        board.tasks.get(999)


async def test_get_lists_decisions_of_any_status(board):
    task = await board.new(assignee_agent_id=board.worker)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        decision = store.create_decision(
            conn, project_id=1, task_id=task.id, agent_id=board.worker, run_id=None,
            session_id=None, question="Qual?", options=[], now=NOW,
        )
        store.answer_decision(conn, decision.id, answer="A", receipt="rc", now=NOW)
    assert [d["status"] for d in board.tasks.get(task.id)["decisions"]] == ["answered"]


async def test_list_filters(board):
    await board.new(assignee_agent_id=board.worker, title="a")
    second = await board.new(assignee_agent_id=board.reviewer, title="b")
    await board.new(project_id=2, title="c")
    assert [t.title for t in board.tasks.list(project_id=1)] == ["a", "b"]
    assert [t.title for t in board.tasks.list(assignee_agent_id=board.reviewer)] == ["b"]
    assert board.tasks.list(statuses=["done"]) == []
    assert [t.id for t in board.tasks.list(limit=1, offset=1)] == [second.id]


async def test_every_change_publishes_a_task_event(board):
    task = await board.tasks.create_task(
        project_id=1, title="a", assignee_agent_id=board.worker, actor_agent_id=None
    )
    await board.tasks.comment(task.id, "oi", author_agent_id=None)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, priority="low"
    )
    types = [type_ for type_, _ in board.events]
    assert types == ["task", "task", "task"]
    assert all(data["id"] == task.id for _, data in board.events)
    assert board.events[-1][1]["revision"] == task.revision + 1


# A change with a comment wakes who the comment alone would ----------------------------------


def woken(board) -> list[tuple[int, str, str]]:
    return [
        (w["agent_id"], w["source"], w["payload"]["reason"]) for w in board.org.wakes
    ]


async def test_person_reopening_a_closed_task_wakes_the_assignee(board):
    task = await started(board)
    done = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="done"
    )
    board.org.wakes.clear()
    await board.tasks.update_task(
        task.id, expected_revision=done.revision, actor_agent_id=None, status="in_progress",
        comment="Faltou o teste; refaça.",
    )
    assert woken(board) == [(board.worker, "assignment", "reopened")]


async def test_person_reopening_without_a_comment_wakes_the_assignee_too(board):
    task = await started(board)
    done = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="cancelled"
    )
    board.org.wakes.clear()
    await board.tasks.update_task(
        task.id, expected_revision=done.revision, actor_agent_id=None, status="todo"
    )
    assert woken(board) == [(board.worker, "assignment", "reopened")]


async def test_person_lifting_a_block_by_status_is_the_same_as_unblock(board):
    task = await blocked_task(board, assignee=board.worker)
    board.org.wakes.clear()
    result = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=None, status="in_progress",
        comment="Pode seguir.",
    )
    assert (result.status, result.run_count, result.blocked_reason) == ("in_progress", 0, None)
    assert woken(board) == [(board.worker, "assignment", "unblocked")]


async def test_boss_lifting_a_block_with_a_comment_wakes_the_assignee(board):
    task = await started(board)
    blocked = await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker, status="blocked",
        comment="Sem acesso.",
    )
    board.org.wakes.clear()
    await board.tasks.update_task(
        task.id, expected_revision=blocked.revision, actor_agent_id=board.cto,
        status="in_progress", comment="Acesso liberado.",
    )
    assert woken(board) == [(board.worker, "comment", "comment")]


async def test_assignee_moving_the_task_does_not_wake_the_creator_by_comment(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    await board.tasks.update_task(
        task.id, expected_revision=task.revision, actor_agent_id=board.worker,
        status="in_progress", comment="vou",
    )
    assert woken(board) == []


def echo_run(
    board, task_id: int, agent_id: int, since: int, reason: str = "comment", *,
    hop: int | None = None, authors: tuple[int, ...] = (),
) -> int:
    """A run of `agent_id` on the task, started by a wakeup of that reason and cursor. A
    `comment` wakeup carries the hop and the authors of the comments that caused it."""
    run_id = board.run(agent_id, task_id)
    payload: dict[str, Any] = {"task_id": task_id, "since_comment_id": since, "reason": reason}
    if hop is not None:
        payload["echo_hop"] = hop
        payload["echo_from"] = list(authors)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        wakeup = store.enqueue_wakeup(
            conn, agent_id=agent_id, source="comment", task_id=task_id, now=1, payload=payload,
        )
        assert store.take_wakeup(conn, wakeup.id, run_id, 1)
    return run_id


def echo_of(board, agent_id: int) -> tuple[Any, Any]:
    """`(echo_hop, echo_from)` of the wake the board sent to the agent."""
    [wake] = [w for w in board.org.wakes if w["agent_id"] == agent_id]
    return wake["payload"].get("echo_hop"), wake["payload"].get("echo_from")


async def test_comment_of_a_run_woken_by_another_reason_wakes_at_hop_zero(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    run_id = echo_run(board, task.id, board.worker, 0, reason="assignment")
    board.org.wakes.clear()
    await board.tasks.comment(task.id, "Uso A ou B?", author_agent_id=board.worker, run_id=run_id)
    assert woken(board) == [(board.cto, "comment", "comment")]
    assert echo_of(board, board.cto) == (0, [board.worker])


async def test_comment_of_a_run_woken_by_a_hop_zero_comment_wakes_at_hop_one(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    await board.tasks.comment(task.id, "Uso A ou B?", author_agent_id=board.worker)
    since = board.comments(task.id)[0].id - 1
    run_id = echo_run(board, task.id, board.cto, since, hop=0, authors=(board.worker,))
    board.org.wakes.clear()
    await board.tasks.comment(task.id, "Use A.", author_agent_id=board.cto, run_id=run_id)
    # The answer is not lost: the one who asked is woken, one hop further.
    assert woken(board) == [(board.worker, "comment", "comment")]
    assert echo_of(board, board.worker) == (1, [board.cto])


async def test_comment_of_a_run_woken_at_hop_one_does_not_wake_back_its_authors(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    await board.tasks.comment(task.id, "Use A.", author_agent_id=board.cto)
    since = board.comments(task.id)[0].id - 1
    run_id = echo_run(board, task.id, board.worker, since, hop=1, authors=(board.cto,))
    board.org.wakes.clear()
    await board.tasks.comment(task.id, "Ok.", author_agent_id=board.worker, run_id=run_id)
    assert woken(board) == []
    # Nor through `update_task` with nothing but the comment.
    await board.tasks.update_task(
        task.id, expected_revision=board.task(task.id).revision, actor_agent_id=board.worker,
        comment="Ok de novo.", run_id=run_id,
    )
    assert woken(board) == []


async def test_only_the_authors_that_woke_the_run_are_skipped(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    # The CTO wrote a comment that did not wake this run: it is not one of its authors.
    await board.tasks.comment(task.id, "Pensei melhor.", author_agent_id=board.cto)
    since = board.comments(task.id)[0].id - 1
    run_id = echo_run(board, task.id, board.worker, since, hop=1, authors=())
    board.org.wakes.clear()
    await board.tasks.comment(task.id, "Ok.", author_agent_id=board.worker, run_id=run_id)
    assert woken(board) == [(board.cto, "comment", "comment")]


async def test_a_sem_relato_run_keeps_the_echo_of_the_run_it_wakes_again(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    await board.tasks.comment(task.id, "Use A.", author_agent_id=board.cto)
    since = board.comments(task.id)[0].id - 1
    run_id = echo_run(
        board, task.id, board.worker, since, reason="sem_relato", hop=1, authors=(board.cto,)
    )
    board.org.wakes.clear()
    await board.tasks.comment(task.id, "Ok.", author_agent_id=board.worker, run_id=run_id)
    assert woken(board) == []


async def test_comment_outside_the_run_task_does_not_count_as_an_answer(board):
    task = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    other = await board.new(assignee_agent_id=board.worker, actor_agent_id=board.cto)
    await board.tasks.comment(task.id, "Andamento.", author_agent_id=board.worker)
    since = board.comments(task.id)[0].id - 1
    run_id = echo_run(board, task.id, board.cto, since)
    board.org.wakes.clear()
    # A comment of that run, but on another task: nothing is echoed there.
    await board.tasks.comment(other.id, "Outra.", author_agent_id=board.cto, run_id=run_id)
    assert woken(board) == [(board.worker, "comment", "comment")]
