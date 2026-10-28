"""DecisionService: decisions an agent asks of the person, with receipt and wakeup. `wake` is
spied: nothing here starts an agent."""

import logging
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.decisions import DECISION_TTL_SECONDS, DecisionService
from claudio_maestro.org.tasks import TaskService

pytestmark = pytest.mark.anyio

NOW = 1_700_000_000


class FakeOrg:
    def __init__(self) -> None:
        self.wakes: list[dict[str, Any]] = []
        self.wake_error: Exception | None = None

    async def wake(self, agent_id: int, **kwargs: Any) -> None:
        if self.wake_error is not None:
            raise self.wake_error
        self.wakes.append({"agent_id": agent_id, **kwargs})

    def _describe(self, agent: store.Agent) -> tuple[str, str]:
        return agent.name, ""

    def schedule_worktree_removal(self, task: store.Task) -> None:
        pass


class Desk:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "maestro.db"
        db.init_db(self.db_path)
        self.now = NOW
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.org = FakeOrg()
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (1, 'p', ?, '#fff', 0, 0)",
                (str(tmp_path / "p1"),),
            )
            self.agent = store.create_agent(
                conn, slug="cto", name="CTO", project_id=1, reports_to=None, now=1
            ).id
        self.session("s-task")
        self.session("s-chat")
        self.session("s-plain", agent_id=None)
        publish = lambda type_, data: self.events.append((type_, data))  # noqa: E731
        self.tasks = TaskService(
            self.db_path, org=self.org, publish=publish, clock=lambda: self.now  # type: ignore[arg-type]
        )
        self.decisions = DecisionService(
            self.db_path,
            org=self.org,  # type: ignore[arg-type]
            tasks=self.tasks,
            publish=publish,
            clock=lambda: self.now,
        )

    def session(self, session_id: str, agent_id: int | None = -1) -> None:
        owner = self.agent if agent_id == -1 else agent_id
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, agent_id) VALUES (?, 1, '/tmp', 't', 0, 0, ?)",
                (session_id, owner),
            )

    async def task_run(self, session_id: str = "s-task") -> tuple[int, int]:
        """A task assigned to the agent with a running run on `session_id`: (task, run)."""
        task = await self.tasks.create_task(
            project_id=1, title="Fazer", assignee_agent_id=self.agent, actor_agent_id=None
        )
        self.org.wakes.clear()
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            run = store.insert_run(
                conn, agent_id=self.agent, session_id=session_id, source="assignment",
                routine_id=None, scheduled_for=None, started_at=NOW, task_id=task.id,
                outcome="running",
            )
        return task.id, run.id

    def texts(self, task_id: int) -> list[tuple[str, str]]:
        with closing(db.connect(self.db_path)) as conn:
            return [(c.author_kind, c.text) for c in store.list_comments(conn, task_id)]

    def notices(self) -> list[store.Notice]:
        with closing(db.connect(self.db_path)) as conn:
            return store.list_notices(conn)

    def get(self, decision_id: int) -> store.Decision:
        with closing(db.connect(self.db_path)) as conn:
            return store.get_decision(conn, decision_id)


@pytest.fixture
def desk(tmp_path: Path) -> Desk:
    return Desk(tmp_path)


# Asking -----------------------------------------------------------------------------


async def test_request_binds_to_active_task_run(desk):
    task_id, run_id = await desk.task_run()
    decision = desk.decisions.request("s-task", question="Qual banco?", options=["A", "B"])
    assert (decision.task_id, decision.run_id, decision.agent_id) == (task_id, run_id, desk.agent)
    assert (decision.project_id, decision.session_id) == (1, "s-task")
    assert (decision.status, decision.options) == ("pending", ["A", "B"])
    assert ("app", "Decisão pedida: Qual banco?") in desk.texts(task_id)
    notices = desk.notices()
    assert len(notices) == 1 and "Qual banco?" in notices[0].text
    assert notices[0].agent_id == desk.agent
    assert any(type_ == "agent.notice" for type_, _ in desk.events)
    assert any(type_ == "task" and data["id"] == task_id for type_, data in desk.events)
    # The app comment is not the run's closing comment.
    with closing(db.connect(desk.db_path)) as conn:
        assert store.get_run(conn, run_id).commented is False


async def test_request_without_task_is_allowed(desk):
    decision = desk.decisions.request("s-chat", question="Posso seguir?", options=None)
    assert (decision.task_id, decision.run_id) == (None, None)
    assert (decision.agent_id, decision.session_id, decision.options) == (
        desk.agent, "s-chat", [],
    )
    assert len(desk.notices()) == 1


async def test_request_ignores_a_finished_run(desk):
    task_id, run_id = await desk.task_run()
    with closing(db.connect(desk.db_path)) as conn, db.transaction(conn):
        store.update_run(conn, run_id, outcome="concluded", ended_at=NOW)
    decision = desk.decisions.request("s-task", question="E agora?", options=None)
    assert (decision.task_id, decision.run_id) == (None, None)
    assert all("Decisão pedida" not in text for _, text in desk.texts(task_id))


async def test_request_from_a_session_of_no_agent_is_refused(desk):
    with pytest.raises(store.OrgError, match="agente"):
        desk.decisions.request("s-plain", question="Oi?", options=None)
    with pytest.raises(store.OrgError, match="agente"):
        desk.decisions.request("nao-existe", question="Oi?", options=None)


async def test_request_validates_question_and_options(desk):
    for question in ("", "x" * 2001):
        with pytest.raises(store.OrgError):
            desk.decisions.request("s-chat", question=question, options=None)
    with pytest.raises(store.OrgError):
        desk.decisions.request("s-chat", question="ok", options=[str(i) for i in range(9)])
    with pytest.raises(store.OrgError):
        desk.decisions.request("s-chat", question="ok", options=["x" * 201])
    with pytest.raises(store.OrgError):
        desk.decisions.request("s-chat", question="ok", options=[""])
    assert desk.decisions.list(pending_only=False) == []


async def test_duplicate_pending_returns_same_or_errors(desk):
    task_id, _ = await desk.task_run()
    first = desk.decisions.request("s-task", question="Qual banco?", options=["A"])
    again = desk.decisions.request("s-task", question="Qual banco?", options=["A"])
    assert again.id == first.id
    assert sum(text.startswith("Decisão pedida") for _, text in desk.texts(task_id)) == 1
    assert len(desk.notices()) == 1
    with pytest.raises(store.OrgError, match="Já há uma decisão pendente desta tarefa."):
        desk.decisions.request("s-task", question="Outra coisa?", options=None)
    # Without a task the rule is per agent.
    free = desk.decisions.request("s-chat", question="Livre?", options=None)
    assert desk.decisions.request("s-chat", question="Livre?", options=None).id == free.id
    with pytest.raises(store.OrgError):
        desk.decisions.request("s-chat", question="Livre 2?", options=None)


async def test_new_request_allowed_once_the_pending_one_is_answered(desk):
    await desk.task_run()
    first = desk.decisions.request("s-task", question="Qual banco?", options=None)
    await desk.decisions.answer(first.id, answer="A")
    second = desk.decisions.request("s-task", question="E o cache?", options=None)
    assert second.id != first.id


# Answering --------------------------------------------------------------------------


async def test_answer_wakes_agent_with_receipt(desk):
    task_id, _ = await desk.task_run()
    decision = desk.decisions.request("s-task", question="Qual banco?", options=["A", "B"])
    with closing(db.connect(desk.db_path)) as conn:
        before = store.last_comment_id(conn, task_id)
    desk.now += 60
    answered = await desk.decisions.answer(decision.id, answer="A")
    assert answered.status == "answered" and answered.answer == "A"
    assert answered.receipt and answered.answered_at == desk.now
    assert desk.get(decision.id).receipt == answered.receipt
    texts = desk.texts(task_id)
    assert texts[-1] == ("human", "Decisão: A")
    assert [t for t in texts if t[0] == "human"] == [("human", "Decisão: A")]
    assert desk.org.wakes == [
        {
            "agent_id": desk.agent,
            "source": "decision",
            "task_id": task_id,
            "payload": {
                "decision_id": decision.id,
                "receipt": answered.receipt,
                "session_id": "s-task",
                "task_id": task_id,
                "since_comment_id": before,
                "reason": "decision",
            },
        }
    ]
    assert any(type_ == "decision" and data["id"] == decision.id for type_, data in desk.events)


async def test_answer_without_task_wakes_with_session_only(desk):
    decision = desk.decisions.request("s-chat", question="Posso?", options=None)
    answered = await desk.decisions.answer(decision.id, answer="Pode")
    assert desk.org.wakes == [
        {
            "agent_id": desk.agent,
            "source": "decision",
            "task_id": None,
            "payload": {
                "decision_id": decision.id, "receipt": answered.receipt, "session_id": "s-chat",
            },
        }
    ]


async def test_answer_twice_or_after_expiry_is_refused(desk):
    first = desk.decisions.request("s-chat", question="Posso?", options=None)
    await desk.decisions.answer(first.id, answer="Sim")
    with pytest.raises(store.OrgError, match="já foi respondida ou expirou"):
        await desk.decisions.answer(first.id, answer="Não")
    assert len(desk.org.wakes) == 1
    second = desk.decisions.request("s-chat", question="Outra?", options=None)
    desk.now += DECISION_TTL_SECONDS + 1
    await desk.decisions.expire_stale()
    with pytest.raises(store.OrgError, match="já foi respondida ou expirou"):
        await desk.decisions.answer(second.id, answer="Sim")
    with pytest.raises(store.OrgError):
        await desk.decisions.answer(9999, answer="Sim")


async def test_answer_validates_text(desk):
    decision = desk.decisions.request("s-chat", question="Posso?", options=None)
    for text in ("", "x" * 20000):
        with pytest.raises(store.OrgError):
            await desk.decisions.answer(decision.id, answer=text)
    assert desk.get(decision.id).status == "pending"


async def test_wake_failure_keeps_the_answer(desk, caplog):
    task_id, _ = await desk.task_run()
    decision = desk.decisions.request("s-task", question="Qual banco?", options=None)
    desk.org.wake_error = store.OrgError("Fila cheia.")
    with caplog.at_level(logging.WARNING):
        answered = await desk.decisions.answer(decision.id, answer="A")
    assert answered.status == "answered"
    assert desk.get(decision.id).status == "answered"
    texts = desk.texts(task_id)
    assert ("human", "Decisão: A") in texts
    assert any(kind == "app" and "Fila cheia." in text for kind, text in texts)
    assert "Fila cheia." in caplog.text


async def test_wake_failure_without_task_leaves_a_notice(desk):
    decision = desk.decisions.request("s-chat", question="Posso?", options=None)
    desk.org.wake_error = RuntimeError("boom")
    answered = await desk.decisions.answer(decision.id, answer="Sim")
    assert answered.status == "answered"
    assert any(n.kind == "alert" for n in desk.notices())


# Listing ----------------------------------------------------------------------------


async def test_list_filters_and_returns_plain_data(desk):
    task_id, _ = await desk.task_run()
    on_task = desk.decisions.request("s-task", question="Na tarefa?", options=["A"])
    free = desk.decisions.request("s-chat", question="Livre?", options=None)
    await desk.decisions.answer(free.id, answer="Sim")
    pending = desk.decisions.list()
    assert [d["id"] for d in pending] == [on_task.id]
    assert pending[0]["options"] == ["A"] and pending[0]["status"] == "pending"
    everything = desk.decisions.list(pending_only=False)
    assert [d["id"] for d in everything] == [on_task.id, free.id]
    assert [d["id"] for d in desk.decisions.list(task_id=task_id, pending_only=False)] == [
        on_task.id
    ]
    assert desk.decisions.list(project_id=2, pending_only=False) == []


# Expiring ---------------------------------------------------------------------------


async def test_expire_stale_marks_and_comments(desk):
    task_id, _ = await desk.task_run()
    old = desk.decisions.request("s-task", question="Qual banco?", options=None)
    free = desk.decisions.request("s-chat", question="Livre?", options=None)
    desk.now += DECISION_TTL_SECONDS - 10
    assert await desk.decisions.expire_stale() == 0
    desk.now += 20
    assert await desk.decisions.expire_stale() == 2
    assert desk.get(old.id).status == "expired" and desk.get(free.id).status == "expired"
    assert any(
        kind == "app" and "expirou" in text and "Qual banco?" in text
        for kind, text in desk.texts(task_id)
    )
    assert any(type_ == "decision" and data["id"] == old.id for type_, data in desk.events)
    assert await desk.decisions.expire_stale() == 0
    assert desk.org.wakes == []


async def test_expire_stale_keeps_answered_and_fresh(desk):
    answered = desk.decisions.request("s-chat", question="Posso?", options=None)
    await desk.decisions.answer(answered.id, answer="Sim")
    desk.now += DECISION_TTL_SECONDS + 1
    fresh = desk.decisions.request("s-chat", question="Nova?", options=None)
    assert await desk.decisions.expire_stale() == 0
    assert desk.get(answered.id).status == "answered"
    assert desk.get(fresh.id).status == "pending"
