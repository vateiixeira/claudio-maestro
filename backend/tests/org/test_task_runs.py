"""Runs of a task in `OrgService`: the wakeups `assignment`, `comment` and `decision` that carry a
task, one session per (agent, task), the worktree an `AGENT.md` asks for, the cap of runs, the
comment every run owes, and the removal of the worktree after the run. Scripted fake agent only;
git is real, in `tmp_path`."""

import asyncio
import json
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from git_helpers import git, git_home, make_repo, set_identity  # noqa: F401
from test_sessions import wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import PauseStep, init_message, text_turn
from claudio_maestro.org import service as service_module
from claudio_maestro.org import store
from claudio_maestro.org.service import (
    COMMENT_ASK_MAIN,
    COMMENT_ASK_ORIGIN,
    COMMENT_ASK_TASK,
    NO_REPORT_REWOKEN,
    NOT_CONNECTED,
    TASK_RUN_LOST,
    UNCERTAIN_SEND,
)
from claudio_maestro.org.tasks import TaskService

from .test_service import fresh, world  # noqa: F401

pytestmark = pytest.mark.anyio


@pytest.fixture
async def board(world):  # noqa: F811
    """The `world` of the service tests with a `TaskService` over the same data."""
    world.tasks = TaskService(
        world.db_path,
        org=world.service,
        publish=lambda type_, data: world.events.append((type_, data)),
        clock=lambda: world.now,
    )
    world.service.tasks = world.tasks
    return world


# Helpers ----------------------------------------------------------------------------------


async def new_task(board, agent: int, title: str = "Ajustar login", **fields: Any) -> store.Task:
    fields.setdefault("description", "Corrigir o botão.")
    return await board.tasks.create_task(
        project_id=board.project.id, title=title, assignee_agent_id=agent, actor_agent_id=None,
        **fields,
    )


def get_task(board, task_id: int) -> store.Task:
    with closing(db.connect(board.db_path)) as conn:
        return store.get_task(conn, task_id)


def comments(board, task_id: int) -> list[tuple[str, str]]:
    with closing(db.connect(board.db_path)) as conn:
        return [(c.author_kind, c.text) for c in store.list_comments(conn, task_id)]


def task_runs(board, task_id: int) -> list[store.Run]:
    with closing(db.connect(board.db_path)) as conn:
        return store.list_task_runs(conn, task_id)


def wakeup_rows(board, agent: int) -> list[dict[str, Any]]:
    with closing(db.connect(board.db_path)) as conn:
        rows = conn.execute(
            "SELECT id, source, state, task_id, payload FROM wakeups WHERE agent_id = ? ORDER BY id",
            (agent,),
        ).fetchall()
    return [{**dict(row), "payload": json.loads(row["payload"] or "null")} for row in rows]


def task_session(board, agent: int, task_id: int) -> store.TaskSession | None:
    with closing(db.connect(board.db_path)) as conn:
        return store.get_task_session(conn, agent, task_id)


def set_task_fields(board, task_id: int, **fields: Any) -> None:
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        task = store.get_task(conn, task_id)
        store.update_task(
            conn, task_id, expected_revision=task.revision, now=1, **fields
        )


def scripted_pauses(board, *pause_on: int) -> dict[int, PauseStep]:
    """The sends numbered `pause_on` (0 is the first of the test) hold their turn until
    released; the others end at once, answering "turno <n>"."""
    pauses = {index: PauseStep() for index in pause_on}
    calls: list[str] = []

    def turns(session_id: str) -> list:
        index = len(calls)
        calls.append(session_id)
        if index in pauses:
            return [init_message(session_id), pauses[index], *text_turn(session_id, "ok")[1:]]
        return text_turn(session_id, f"turno {index}")

    board.turns = turns
    return pauses


async def reached(pause: PauseStep) -> None:
    await asyncio.wait_for(pause.reached.wait(), 2)


async def agent_comments(board, task_id: int, agent: int, run: store.Run, text: str) -> None:
    await board.tasks.comment(task_id, text, author_agent_id=agent, run_id=run.id)


def outcome_of(board, run_id: int) -> str:
    with closing(db.connect(board.db_path)) as conn:
        return store.get_run(conn, run_id).outcome


async def first_run(board, agent: int, pause: PauseStep, task_id: int) -> store.Run:
    await board.service.drain(agent)
    await reached(pause)
    [run] = task_runs(board, task_id)
    return run


# Opening the session ---------------------------------------------------------------------


async def test_assignment_wakeup_opens_task_session_in_project_folder(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)

    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    assert (run.source, run.outcome, run.task_id, run.agent_id) == (
        "assignment", "running", task.id, agent
    )
    session = board.manager.get(run.session_id)
    assert session.record.agent_id == agent
    assert session.record.cwd == board.project.path
    assert session.record.title == "Revisor · #1 Ajustar login"
    saved = task_session(board, agent, task.id)
    assert (saved.session_id, saved.cwd) == (run.session_id, board.project.path)
    assert board.service.is_conversation(run.session_id)  # `concluir` does not finish it
    assert get_task(board, task.id).run_count == 1
    [row] = wakeup_rows(board, agent)
    assert (row["state"], row["task_id"]) == ("taken", task.id)
    assert row["payload"] == {"task_id": task.id, "since_comment_id": 0, "reason": "assignment"}
    text = board.sent(0)[0]
    assert text.startswith("Você recebeu a tarefa #1: Ajustar login.")
    assert "Corrigir o botão." in text
    assert board.published("task")[-1]["change"] == "run"

    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    assert task_runs(board, task.id)[0].commented is True
    await asyncio.sleep(0.05)
    assert len(task_runs(board, task.id)) == 1  # it commented: nothing wakes it again


async def test_second_wakeup_reuses_task_session(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, agent)
    run1 = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run1, "Feito do agente.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run1.id) == "concluded")

    await board.tasks.comment(task.id, "Mais um detalhe.", author_agent_id=None)
    await board.service.drain(agent)
    await reached(pauses[1])

    run1, run2 = task_runs(board, task.id)
    assert run2.source == "comment" and run2.session_id == run1.session_id
    assert len(board.factory.clients) == 1  # the same process: the send resumes it by itself
    second = board.sent(0)[1]
    assert second.startswith("Há comentários novos na tarefa #1")
    assert "Pessoa: Mais um detalhe." in second
    assert "Feito do agente." not in second  # only what is new since the cursor
    assert get_task(board, task.id).run_count == 2
    await agent_comments(board, task.id, agent, run2, "Pronto.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")


async def test_new_session_when_the_old_one_is_gone(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, agent)
    run1 = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run1, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run1.id) == "concluded")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (run1.session_id,))
    board.manager._sessions.pop(run1.session_id, None)

    await board.tasks.comment(task.id, "De novo.", author_agent_id=None)
    await board.service.drain(agent)
    await reached(pauses[1])

    run2 = task_runs(board, task.id)[1]
    assert run2.session_id not in (None, run1.session_id)
    assert task_session(board, agent, task.id).session_id == run2.session_id
    await agent_comments(board, task.id, agent, run2, "Pronto.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")


# Worktree --------------------------------------------------------------------------------


def make_project_repo(board) -> Path:
    root = make_repo(Path(board.project.path))
    set_identity(root)
    return root


async def test_worktree_true_opens_session_in_task_worktree(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)

    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    expected = root.resolve() / ".claude" / "worktrees" / "tarefa-1"
    saved = get_task(board, task.id)
    assert (saved.worktree_path, saved.branch) == (str(expected), "tarefa/1-ajustar-login")
    session = board.manager.get(run.session_id)
    assert session.record.cwd == str(expected)
    assert session.record.worktree_path == str(expected)
    assert board.factory.clients[0].options.cwd == expected
    assert task_session(board, agent, task.id).cwd == str(expected)
    assert f"Pasta de trabalho desta tarefa: {expected}" in board.sent(0)[0]
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


async def test_worktree_must_be_proven_before_it_becomes_the_cwd(board, git_home, monkeypatch):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    calls: list[tuple[Any, Any]] = []

    async def refuse(path, roots):
        calls.append((path, roots))
        return None

    monkeypatch.setattr(service_module, "gitinfo", SimpleNamespace(project_worktree=refuse))
    task = await new_task(board, agent)
    await board.service.drain(agent)

    [run] = task_runs(board, task.id)
    assert run.outcome == "failed" and run.session_id is None
    assert "worktree" in (run.reason or "").lower()
    path, roots = calls[0]
    assert str(path) == str(root.resolve() / ".claude" / "worktrees" / "tarefa-1")
    assert [str(r) for r in roots] == [board.project.path]
    assert board.factory.clients == []  # no session was ever opened
    assert any(kind == "app" and "worktree" in text.lower() for kind, text in comments(board, task.id))


async def test_worktree_failure_fails_the_run_with_an_app_comment(board):
    agent = board.add_agent(worktree=True)  # the project folder is not a git repository
    task = await new_task(board, agent)
    await board.service.drain(agent)

    [run] = task_runs(board, task.id)
    assert run.outcome == "failed"
    assert run.reason == "A pasta do projeto não é a raiz de um repositório git."
    assert (
        "app",
        "Execução falhou: A pasta do projeto não é a raiz de um repositório git.",
    ) in comments(board, task.id)
    assert board.factory.clients == []
    assert board.wakeups(agent) == []  # the wakeup was taken, it is not tried again


async def test_worktree_session_is_new_when_cwd_changes(board, git_home):  # noqa: F811
    make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, agent)
    run1 = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run1, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run1.id) == "concluded")
    # An old session of this (agent, task) that was opened in the project folder.
    old = board.manager.create_session(board.project, agent_id=agent)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.set_task_session(
            conn, agent, task.id, session_id=old.session_id, cwd=board.project.path, now=1
        )

    await board.tasks.comment(task.id, "De novo.", author_agent_id=None)
    await board.service.drain(agent)
    await reached(pauses[1])

    run2 = task_runs(board, task.id)[1]
    assert run2.session_id not in (old.session_id, run1.session_id, None)
    assert board.manager.find_record(run2.session_id).cwd == get_task(board, task.id).worktree_path
    await agent_comments(board, task.id, agent, run2, "Pronto.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")


# One run per task and per folder ----------------------------------------------------------


async def test_one_run_per_task_even_for_two_agents(board):
    first = board.add_agent("primeiro")
    second = board.add_agent("segundo")
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, first, reviewer_agent_id=second)
    run1 = await first_run(board, first, pauses[0], task.id)

    await board.service.wake(
        second, source="comment", task_id=task.id,
        payload={"task_id": task.id, "since_comment_id": 0, "reason": "comment"},
    )
    await board.service.drain(second)

    assert [r.agent_id for r in task_runs(board, task.id)] == [first]
    [row] = wakeup_rows(board, second)
    assert row["state"] == "pending"  # it waits: never two runs on the same task

    await agent_comments(board, task.id, first, run1, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run1.id) == "concluded")
    await wait_until(lambda: len(task_runs(board, task.id)) == 2)
    await reached(pauses[1])

    run2 = task_runs(board, task.id)[1]
    assert run2.agent_id == second
    assert run1.ended_at is not None or outcome_of(board, run1.id) == "concluded"
    await agent_comments(board, task.id, second, run2, "Revisado.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")


async def test_one_task_run_per_project_folder_without_worktree(board):
    first = board.add_agent("primeiro")
    second = board.add_agent("segundo")
    pauses = scripted_pauses(board, 0, 1)
    task_a = await new_task(board, first, "Tarefa A")
    run_a = await first_run(board, first, pauses[0], task_a.id)

    task_b = await new_task(board, second, "Tarefa B")
    await board.service.drain(second)

    assert task_runs(board, task_b.id) == []  # the folder is taken by the run of task A
    assert wakeup_rows(board, second)[0]["state"] == "pending"
    assert get_task(board, task_b.id).run_count == 0  # a wakeup that did not start does not count

    await agent_comments(board, task_a.id, first, run_a, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run_a.id) == "concluded")
    await wait_until(lambda: len(task_runs(board, task_b.id)) == 1)
    await reached(pauses[1])
    run_b = task_runs(board, task_b.id)[0]
    await agent_comments(board, task_b.id, second, run_b, "Feito.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run_b.id) == "concluded")


# The cap of runs --------------------------------------------------------------------------


async def test_run_count_cap_blocks_task_and_alerts(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    set_task_fields(board, task.id, max_runs=1)
    run = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")

    await board.tasks.comment(task.id, "Mais uma coisa.", author_agent_id=None)
    await board.service.drain(agent)

    assert len(task_runs(board, task.id)) == 1  # no run for the second wakeup
    blocked = get_task(board, task.id)
    assert (blocked.status, blocked.blocked_reason, blocked.run_count) == (
        "blocked", "Atingiu o teto de 1 execuções.", 2,
    )
    assert [row["state"] for row in wakeup_rows(board, agent)] == ["taken", "dropped"]
    [alert] = [n for n in board.notices() if n.kind == "alert"]
    assert alert.agent_id == agent and f"#{task.id}" in alert.text and "1 execuções" in alert.text
    assert any(kind == "app" and "teto" in text for kind, text in comments(board, task.id))
    assert board.published("task")[-1]["status"] == "blocked"
    assert len(board.factory.clients) == 1


async def test_blocked_by_the_cap_ignores_comments_until_unblocked(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    set_task_fields(
        board, task.id, status="blocked", run_count=3, max_runs=3,
        blocked_reason="Atingiu o teto de 3 execuções.",
    )
    board.set_enabled(agent, True)
    await board.service.drain(agent)
    assert task_runs(board, task.id) == []
    assert [row["state"] for row in wakeup_rows(board, agent)] == ["dropped"]  # R16

    await board.tasks.comment(task.id, "Voltou?", author_agent_id=None)
    await board.service.drain(agent)
    assert task_runs(board, task.id) == []
    assert [row["state"] for row in wakeup_rows(board, agent)] == ["dropped", "dropped"]

    unblocked = await board.tasks.unblock(
        task.id, expected_revision=get_task(board, task.id).revision
    )
    assert (unblocked.run_count, unblocked.status) == (0, "in_progress")
    await board.service.drain(agent)
    await reached(pauses[0])
    [run] = task_runs(board, task.id)
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


async def test_task_blocked_by_an_agent_is_still_woken_by_a_comment(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    set_task_fields(board, task.id, status="blocked", run_count=1, blocked_reason="Sem acesso.")
    await board.tasks.comment(task.id, "Liberei o acesso.", author_agent_id=None)
    board.set_enabled(agent, True)

    await board.service.drain(agent)
    await reached(pauses[0])

    [run] = task_runs(board, task.id)  # the assignment and the comment are one run at a time
    assert run.task_id == task.id
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


# The comment every run owes ----------------------------------------------------------------


async def test_run_without_comment_rewakes_once_then_app_comment(board):
    agent = board.add_agent()
    task = await new_task(board, agent)

    await wait_until(lambda: len(task_runs(board, task.id)) == 2)
    await wait_until(lambda: outcome_of(board, task_runs(board, task.id)[1].id) == "concluded")
    await wait_until(lambda: any(n.kind == "alert" for n in board.notices()))
    await asyncio.sleep(0.1)

    run1, run2 = task_runs(board, task.id)
    assert (run1.outcome, run1.commented, run1.rewoken) == ("concluded", False, True)
    assert (run2.outcome, run2.source) == ("concluded", "comment")
    assert len(task_runs(board, task.id)) == 2  # it does not insist
    texts = comments(board, task.id)
    assert ("app", "Execução sem relato; o agente foi acordado para comentar.") in texts
    # The last text of the session, without going through the summary agent.
    assert ("app", "Execução sem relato. Último texto do agente:\nfeito") in texts
    [alert] = [n for n in board.notices() if n.kind == "alert"]
    assert (alert.agent_id, alert.run_id) == (agent, run2.id)
    assert alert.text == "A execução terminou sem relato duas vezes."
    assert board.sent(0)[1].startswith("A execução anterior terminou sem comentário")
    [first_wake, second_wake] = wakeup_rows(board, agent)
    assert second_wake["payload"]["reason"] == "sem_relato"
    assert board.wakeups(agent) == []
    assert get_task(board, task.id).status == "todo"  # the app does not decide the status


async def test_rewake_run_that_comments_ends_the_story(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 1)
    task = await new_task(board, agent)

    await reached(pauses[1])  # the first run ended without a comment, the second one is held
    run1, run2 = task_runs(board, task.id)
    assert run1.rewoken is True
    await agent_comments(board, task.id, agent, run2, "Agora sim.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")
    await asyncio.sleep(0.05)

    assert len(task_runs(board, task.id)) == 2
    assert [n for n in board.notices() if n.kind == "alert"] == []


async def test_failed_run_is_not_rewoken_and_leaves_an_app_comment(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    board.service.on_turn_error(run.session_id, "A API caiu.")
    pauses[0].release.set()
    await asyncio.sleep(0.1)

    saved = task_runs(board, task.id)
    assert len(saved) == 1 and saved[0].outcome == "failed"
    assert ("app", "Execução falhou: A API caiu.") in comments(board, task.id)


async def test_closure_ignores_task_runs(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    await board.service.on_closure(
        fresh(run.session_id, verdict="can_close", evidence="tudo pronto")
    )
    await board.service.conclude(run.session_id, "Resumo da execução.")

    assert outcome_of(board, run.id) == "running"  # a task run ends with its turn and its comment
    assert board.announcements(agent) == []
    assert [n.text for n in board.notices() if n.kind == "summary"] == ["Resumo da execução."]
    assert board.manager.find_record(run.session_id).finished is False
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    assert board.announcements(agent) == []  # the comment on the task is the report


# Closing the task and the worktree --------------------------------------------------------


async def test_closing_task_waits_run_before_removing_worktree(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    path = root.resolve() / ".claude" / "worktrees" / "tarefa-1"
    assert path.is_dir()

    current = get_task(board, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=current.revision, actor_agent_id=None, status="done"
    )
    await asyncio.sleep(0.3)
    assert path.is_dir()  # the run goes on, and so does its worktree
    assert outcome_of(board, run.id) == "running"

    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: not path.exists())

    await wait_until(lambda: get_task(board, task.id).worktree_path is None)
    assert ("app", "Worktree removida.") in comments(board, task.id)
    assert "tarefa/1-ajustar-login" not in git(root, "branch", "--format=%(refname:short)").split()
    assert len(task_runs(board, task.id)) == 1  # a closed task is not woken again


async def test_closing_task_without_run_removes_worktree_at_once(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    path = root.resolve() / ".claude" / "worktrees" / "tarefa-1"
    assert path.is_dir()

    current = get_task(board, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=current.revision, actor_agent_id=None, status="cancelled"
    )

    await wait_until(lambda: not path.exists())


async def test_worktree_with_unsaved_work_is_kept_with_a_notice(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    path = root.resolve() / ".claude" / "worktrees" / "tarefa-1"
    (path / "novo.txt").write_text("trabalho solto\n")
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")

    current = get_task(board, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=current.revision, actor_agent_id=None, status="done"
    )

    await wait_until(
        lambda: any(kind == "app" and text.startswith("Worktree mantida: ")
                    for kind, text in comments(board, task.id))
    )
    assert path.is_dir() and get_task(board, task.id).worktree_path == str(path)
    [notice] = [n for n in board.notices() if n.kind == "notice"]
    assert notice.agent_id == agent and "worktree mantida" in notice.text


# The queue ----------------------------------------------------------------------------------


async def test_pick_drops_wakeup_of_closed_task(board):
    agent = board.add_agent()
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    current = get_task(board, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=current.revision, actor_agent_id=None, status="cancelled"
    )
    board.set_enabled(agent, True)

    await board.service.drain(agent)

    assert task_runs(board, task.id) == []
    assert [row["state"] for row in wakeup_rows(board, agent)] == ["dropped"]
    assert board.factory.clients == []


async def test_closed_reason_still_wakes_the_creator_of_a_closed_task(board):
    agent = board.add_agent()
    task = await board.tasks.create_task(
        project_id=board.project.id, title="Feita", actor_agent_id=None
    )
    set_task_fields(board, task.id, status="done")

    await board.service.wake(
        agent, source="comment", task_id=task.id,
        payload={"task_id": task.id, "since_comment_id": 0, "reason": "closed"},
    )
    await board.service.drain(agent)

    [run] = task_runs(board, task.id)
    assert (run.agent_id, run.source) == (agent, "comment")
    assert board.sent(0)[0].startswith("A tarefa que você criou foi fechada #1")
    assert not (Path(board.project.path) / ".claude").exists()  # no worktree for a closed task


async def test_assignment_wakeup_without_a_task_is_dropped(board):
    agent = board.add_agent()
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.enqueue_wakeup(conn, agent_id=agent, source="assignment", payload=None, now=1)

    await board.service.drain(agent)

    assert [row["state"] for row in wakeup_rows(board, agent)] == ["dropped"]


async def test_wake_with_task_validates_origin_task_and_project(board):
    agent = board.add_agent()
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    with pytest.raises(store.OrgError):
        await board.service.wake(agent, source="routine", task_id=task.id)
    with pytest.raises(store.OrgError):
        await board.service.wake(agent, source="comment", task_id=task.id, text="x")
    with pytest.raises(store.NotFoundError):
        await board.service.wake(agent, source="comment", task_id=999)
    other = board.add_project("outro")
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        project_id = conn.execute(
            "SELECT id FROM projects WHERE path = ?", (str(other),)
        ).fetchone()[0]
        foreign = store.create_task(conn, project_id=project_id, title="X", now=1).id
    with pytest.raises(store.OrgError):
        await board.service.wake(agent, source="comment", task_id=foreign)


async def test_task_wakeups_group_by_agent_task_origin_and_reason(board):
    agent = board.add_agent()
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    base = {"task_id": task.id, "reason": "comment"}

    first = await board.service.wake(
        agent, source="comment", task_id=task.id, payload={**base, "since_comment_id": 7}
    )
    again = await board.service.wake(
        agent, source="comment", task_id=task.id, payload={**base, "since_comment_id": 3}
    )
    other_reason = await board.service.wake(
        agent, source="comment", task_id=task.id,
        payload={"task_id": task.id, "reason": "blocked", "since_comment_id": 9},
    )

    assert again.id == first.id and other_reason.id != first.id
    merged = [r for r in wakeup_rows(board, agent) if r["id"] == first.id][0]
    assert merged["payload"]["since_comment_id"] == 3  # the smallest cursor stays
    # A decision never groups.
    one = await board.service.wake(
        agent, source="decision", task_id=task.id, payload={"task_id": task.id, "reason": "decision"}
    )
    two = await board.service.wake(
        agent, source="decision", task_id=task.id, payload={"task_id": task.id, "reason": "decision"}
    )
    assert one.id != two.id


async def test_task_wakeup_defaults_payload_cursor_and_reason(board):
    agent = board.add_agent()
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    wakeup = await board.service.wake(agent, source="comment", task_id=task.id)
    assert wakeup.task_id == task.id
    assert wakeup.payload == {"task_id": task.id, "since_comment_id": 0, "reason": "comment"}
    assert list(board.files.folder("revisor").glob("wake-*")) == []  # the text is made when served


# Decisions ----------------------------------------------------------------------------------


def answered_decision(board, agent: int, task_id: int | None, session_id: str | None = None):
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        decision = store.create_decision(
            conn, project_id=board.project.id, task_id=task_id, agent_id=agent, run_id=None,
            question="Posso apagar a tabela?", options=["sim", "não"], session_id=session_id,
            now=1,
        )
        return store.answer_decision(conn, decision.id, answer="Sim", receipt="rec-123", now=2)


async def test_decision_wakeup_on_a_task_carries_question_answer_and_receipt(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, agent)
    run1 = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run1, "Preciso de uma decisão.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run1.id) == "concluded")
    decision = answered_decision(board, agent, task.id)

    await board.service.wake(
        agent, source="decision", task_id=task.id,
        payload={"task_id": task.id, "since_comment_id": 1, "reason": "decision",
                 "decision_id": decision.id, "receipt": decision.receipt},
    )
    await board.service.drain(agent)
    await reached(pauses[1])

    run2 = task_runs(board, task.id)[1]
    assert (run2.source, run2.session_id) == ("decision", run1.session_id)
    text = board.sent(0)[1]
    assert text.startswith("A pessoa respondeu sua pergunta #1")
    assert "Pergunta: Posso apagar a tabela?" in text
    assert "Resposta: Sim" in text
    assert "rec-123" in text and "use-o no comentário que fecha a questão" in text
    await agent_comments(board, task.id, agent, run2, "Apagada.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run2.id) == "concluded")


async def test_decision_wakeup_without_task_is_a_message_to_the_asking_session(board):
    agent = board.add_agent()
    asking = board.session_of(agent)
    decision = answered_decision(board, agent, None, asking.session_id)

    await board.service.wake(
        agent, source="decision",
        payload={"decision_id": decision.id, "receipt": decision.receipt,
                 "session_id": asking.session_id},
    )
    await board.service.drain(agent)

    client = next(c for c in board.factory.clients if c.options.session_id == asking.session_id)
    assert "Resposta: Sim" in client.sent[0] and "rec-123" in client.sent[0]
    assert board.runs(agent) == []  # a message, not an execution
    assert [row["state"] for row in wakeup_rows(board, agent)] == ["taken"]


async def test_decision_wakeup_without_task_or_session_goes_to_the_main_conversation(board):
    agent = board.add_agent()
    decision = answered_decision(board, agent, None, None)

    await board.service.wake(
        agent, source="decision",
        payload={"decision_id": decision.id, "receipt": decision.receipt, "session_id": "sumiu"},
    )
    await board.service.drain(agent)

    main = board.agent(agent).main_session_id
    assert main is not None
    client = next(c for c in board.factory.clients if c.options.session_id == main)
    assert "Pergunta: Posso apagar a tabela?" in client.sent[0]
    assert board.runs(agent) == []


# Failures and recovery ------------------------------------------------------------------------


async def test_send_that_provably_did_not_leave_fails_the_task_run(board, monkeypatch):
    agent = board.add_agent()

    async def not_sent(session_id, text, images=None):
        return {"send_started": False}

    monkeypatch.setattr(board.manager, "send", not_sent)
    task = await new_task(board, agent)
    await board.service.drain(agent)

    [run] = task_runs(board, task.id)
    assert (run.outcome, run.reason) == ("failed", NOT_CONNECTED)
    assert ("app", f"Execução falhou: {NOT_CONNECTED}") in comments(board, task.id)


@pytest.mark.parametrize(
    ("outcome", "reason"), [("running", TASK_RUN_LOST), ("starting", UNCERTAIN_SEND)]
)
async def test_recover_fails_task_runs_without_session(board, outcome, reason):
    agent = board.add_agent()
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    dead = board.session_of(agent)  # a session without a client: nothing keeps it alive
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        run = store.insert_run(
            conn, agent_id=agent, source="assignment", started_at=5, outcome=outcome,
            session_id=dead.session_id, task_id=task.id,
        )

    await board.service.recover()

    saved = task_runs(board, task.id)[0]
    assert (saved.id, saved.outcome, saved.reason) == (run.id, "failed", reason)
    assert saved.ended_at is not None
    assert ("app", f"Execução falhou: {reason}") in comments(board, task.id)


async def test_recover_clears_task_sessions_of_deleted_sessions(board):
    agent = board.add_agent()
    task = await new_task(board, agent)
    board.set_enabled(agent, False)
    gone = board.manager.create_session(board.project, agent_id=agent)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.set_task_session(
            conn, agent, task.id, session_id=gone.session_id, cwd=board.project.path, now=1
        )
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (gone.session_id,))

    await board.service.recover()

    assert task_session(board, agent, task.id) is None


async def test_recover_keeps_a_task_run_whose_session_is_alive_and_ends_it(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    # A new service starts over a live session (what the agentd gives back): it takes the run up
    # again and ends it when the turn ends.
    await board.service.shutdown()
    recovered = board.new_service()
    recovered.tasks = board.tasks
    try:
        await recovered.recover()
        assert outcome_of(board, run.id) == "running"
        await agent_comments(board, task.id, agent, run, "Feito.")
        pauses[0].release.set()
        await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    finally:
        await recovered.shutdown()


async def test_pr_opened_in_a_task_session_is_linked_to_the_task(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    board.service.on_pr_created(run.session_id, "https://github.com/o/r/pull/5?x=1")

    with closing(db.connect(board.db_path)) as conn:
        pr = store.get_pr(conn, "https://github.com/o/r/pull/5")
    assert pr is not None and (pr.task_id, pr.agent_id) == (task.id, agent)
    assert ("app", "PR aberto: https://github.com/o/r/pull/5") in comments(board, task.id)
    board.service.on_pr_created(run.session_id, "https://github.com/o/r/pull/5")
    assert len([c for c in comments(board, task.id) if c[1].startswith("PR aberto")]) == 1
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


async def test_pr_of_a_routine_session_has_no_task(board):
    agent = board.add_agent()
    session = board.session_of(agent)

    board.service.on_pr_created(session.session_id, "https://github.com/o/r/pull/6")

    with closing(db.connect(board.db_path)) as conn:
        pr = store.get_pr(conn, "https://github.com/o/r/pull/6")
    assert pr is not None and pr.task_id is None


async def test_cancelled_task_run_leaves_an_app_comment_and_is_not_rewoken(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    await board.service.cancel_run(agent, run.id)
    pauses[0].release.set()
    await asyncio.sleep(0.1)

    assert [r.outcome for r in task_runs(board, task.id)] == ["cancelled"]
    assert ("app", "Execução cancelada pela pessoa.") in comments(board, task.id)


async def test_task_run_finished_by_the_person_is_not_rewoken(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)

    await board.manager.update(run.session_id, finished=True)
    pauses[0].release.set()
    await asyncio.sleep(0.1)

    [saved] = task_runs(board, task.id)
    assert (saved.outcome, saved.reason) == ("concluded", "Finalizada por você")
    assert not any(kind == "app" for kind, _ in comments(board, task.id))


async def test_recover_asks_again_for_a_removal_that_was_waiting(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    path = root.resolve() / ".claude" / "worktrees" / "tarefa-1"
    # The task closed and the backend went down before the worktree was removed.
    set_task_fields(board, task.id, status="done")
    board.service._mark_removal(task.id)
    await board.service.shutdown()
    recovered = board.new_service()
    recovered.tasks = board.tasks
    try:
        await recovered.recover()
        await wait_until(lambda: not path.exists())
    finally:
        await recovered.shutdown()


# Round 1: PR comments on a task session, the folder, and the small fixes -------------------

PR_URL = "https://github.com/o/r/pull/9"


def pr_wake_text() -> str:
    return f"Comentário de @dono no PR {PR_URL}:\nTroque o nome.\n{COMMENT_ASK_ORIGIN}"


async def pr_comment_wake(board, agent: int, session_id: str):
    return await board.service.wake(
        agent, source="comment", text=pr_wake_text(),
        payload={"session_id": session_id, "pr_url": PR_URL},
    )


def pr_wakeup_state(board, agent: int) -> str:
    [row] = [r for r in wakeup_rows(board, agent) if (r["payload"] or {}).get("pr_url") == PR_URL]
    return row["state"]


async def finished_first_run(board, agent: int, pause: PauseStep, task_id: int) -> store.Run:
    """The first run of the task opens a PR, comments and ends."""
    run = await first_run(board, agent, pause, task_id)
    board.service.on_pr_created(run.session_id, PR_URL)
    await agent_comments(board, task_id, agent, run, "PR aberto.")
    pause.release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    return run


async def test_pr_comment_in_a_task_session_is_a_task_run_and_never_overlaps(board):
    worker = board.add_agent("primeiro")
    reviewer = board.add_agent("segundo")
    pauses = scripted_pauses(board, 0, 1, 2)
    task = await new_task(board, worker, reviewer_agent_id=reviewer)
    run1 = await finished_first_run(board, worker, pauses[0], task.id)
    await board.service.wake(
        reviewer, source="comment", task_id=task.id,
        payload={"task_id": task.id, "since_comment_id": 0, "reason": "review"},
    )
    await board.service.drain(reviewer)
    await reached(pauses[1])
    review = task_runs(board, task.id)[1]

    await pr_comment_wake(board, worker, run1.session_id)
    await board.service.drain(worker)
    await asyncio.sleep(0.15)

    with closing(db.connect(board.db_path)) as conn:
        assert store.active_run(conn, worker) is None  # the task is held by the reviewer
        assert [r.id for r in store.list_task_runs(conn, task.id) if r.outcome == "running"] == [review.id]
    assert pr_wakeup_state(board, worker) == "pending"

    await agent_comments(board, task.id, reviewer, review, "Revisado.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, review.id) == "concluded")
    await wait_until(lambda: len(task_runs(board, task.id)) == 3)
    await reached(pauses[2])

    run3 = task_runs(board, task.id)[2]
    assert (run3.agent_id, run3.source, run3.session_id) == (worker, "comment", run1.session_id)
    assert get_task(board, task.id).run_count == 3
    text = board.sent(0)[1]
    assert "Troque o nome." in text and text.endswith(COMMENT_ASK_TASK)
    assert COMMENT_ASK_ORIGIN not in text
    assert pr_wakeup_state(board, worker) == "taken"
    await agent_comments(board, task.id, worker, run3, "Troquei.")
    pauses[2].release.set()
    await wait_until(lambda: outcome_of(board, run3.id) == "concluded")


async def test_pr_comment_run_without_a_report_is_woken_once_more(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run1 = await finished_first_run(board, agent, pauses[0], task.id)

    await pr_comment_wake(board, agent, run1.session_id)

    await wait_until(lambda: len(task_runs(board, task.id)) == 3)  # the comment run + the rewake
    await wait_until(lambda: outcome_of(board, task_runs(board, task.id)[2].id) == "concluded")
    assert task_runs(board, task.id)[1].rewoken is True
    assert ("app", NO_REPORT_REWOKEN) in comments(board, task.id)


async def test_worktree_is_not_removed_while_a_pr_comment_run_runs(board, git_home):  # noqa: F811
    root = make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0, 1)
    task = await new_task(board, agent)
    run1 = await finished_first_run(board, agent, pauses[0], task.id)
    path = root.resolve() / ".claude" / "worktrees" / "tarefa-1"

    await pr_comment_wake(board, agent, run1.session_id)
    await board.service.drain(agent)
    await reached(pauses[1])
    run2 = task_runs(board, task.id)[1]
    assert run2.task_id == task.id and outcome_of(board, run2.id) == "running"
    current = get_task(board, task.id)
    await board.tasks.update_task(
        task.id, expected_revision=current.revision, actor_agent_id=None, status="done"
    )
    await asyncio.sleep(0.3)
    assert path.is_dir()  # the run on the PR comments still works in it

    await agent_comments(board, task.id, agent, run2, "Feito.")
    pauses[1].release.set()
    await wait_until(lambda: not path.exists())


async def test_pr_comment_on_a_closed_task_goes_to_the_main_conversation(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run1 = await finished_first_run(board, agent, pauses[0], task.id)
    set_task_fields(board, task.id, status="done")

    await pr_comment_wake(board, agent, run1.session_id)
    await board.service.drain(agent)

    main = board.agent(agent).main_session_id
    assert main is not None
    client = next(c for c in board.factory.clients if c.options.session_id == main)
    assert "Troque o nome." in client.sent[0] and client.sent[0].endswith(COMMENT_ASK_MAIN)
    assert len(task_runs(board, task.id)) == 1  # a closed task gets no run


async def test_pr_comment_on_a_task_blocked_by_the_cap_waits(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run1 = await finished_first_run(board, agent, pauses[0], task.id)
    set_task_fields(
        board, task.id, status="blocked", blocked_reason="Atingiu o teto de 1 execuções.",
        run_count=1, max_runs=1,
    )

    await pr_comment_wake(board, agent, run1.session_id)
    await board.service.drain(agent)

    assert len(task_runs(board, task.id)) == 1
    assert pr_wakeup_state(board, agent) == "pending"  # not lost


async def test_repeated_failed_comment_send_does_not_burn_the_run_cap(board, monkeypatch):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run1 = await finished_first_run(board, agent, pauses[0], task.id)
    before = get_task(board, task.id).run_count

    async def not_sent(session_id, text, images=None):
        return {"send_started": False}

    monkeypatch.setattr(board.manager, "send", not_sent)
    payload = {"session_id": run1.session_id, "pr_url": PR_URL, "comment_ids": ["issue:1"]}
    for _ in range(2):
        await board.service.wake(agent, source="comment", text=pr_wake_text(), payload=payload)
        await board.service.drain(agent)
        await asyncio.sleep(0.05)

    # The first failure is a failed run (it counts); the repeat is discarded and does not.
    assert get_task(board, task.id).run_count == before + 1


# The folder is judged by where the run really works -----------------------------------------


async def test_closed_reason_run_in_the_project_folder_holds_it_despite_a_task_worktree(board):
    worktree_agent = board.add_agent("trabalha", worktree=True)
    other = board.add_agent("outro")
    pauses = scripted_pauses(board, 0, 1)
    closed = await board.tasks.create_task(
        project_id=board.project.id, title="Feita", actor_agent_id=None
    )
    set_task_fields(
        board, closed.id, status="done", worktree_path="/nao/importa/tarefa-1",
        branch="tarefa/1-feita",
    )
    await board.service.wake(
        worktree_agent, source="comment", task_id=closed.id,
        payload={"task_id": closed.id, "since_comment_id": 0, "reason": "closed"},
    )
    await board.service.drain(worktree_agent)
    await reached(pauses[0])
    [held] = task_runs(board, closed.id)
    assert board.manager.find_record(held.session_id).cwd == board.project.path

    second = await new_task(board, other, "Outra")
    await board.service.drain(other)

    assert task_runs(board, second.id) == []  # the project folder is taken, whatever task.worktree_path says
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, held.id) == "concluded")
    await wait_until(lambda: len(task_runs(board, second.id)) == 1)
    await reached(pauses[1])
    run = task_runs(board, second.id)[0]
    await agent_comments(board, second.id, other, run, "Feito.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


async def test_task_reassigned_from_a_worktree_agent_holds_the_project_folder(board):
    without = board.add_agent("sem")
    other = board.add_agent("outro")
    pauses = scripted_pauses(board, 0, 1)
    board.set_enabled(without, False)
    first = await new_task(board, without, "Era de worktree")
    set_task_fields(board, first.id, worktree_path="/nao/importa/tarefa-1", branch="tarefa/1-x")
    board.set_enabled(without, True)
    await board.service.drain(without)
    await reached(pauses[0])
    [held] = task_runs(board, first.id)

    second = await new_task(board, other, "Outra")
    await board.service.drain(other)

    assert task_runs(board, second.id) == []
    await agent_comments(board, first.id, without, held, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, held.id) == "concluded")
    await wait_until(lambda: len(task_runs(board, second.id)) == 1)
    await reached(pauses[1])
    run = task_runs(board, second.id)[0]
    await agent_comments(board, second.id, other, run, "Feito.")
    pauses[1].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")


# Small fixes ------------------------------------------------------------------------------------


async def test_shutdown_keeps_the_removal_mark_of_a_worktree_still_being_removed(
    board, git_home, monkeypatch  # noqa: F811
):
    make_project_repo(board)
    agent = board.add_agent(worktree=True)
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    started = asyncio.Event()

    async def hang(*args, **kwargs):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(service_module.worktrees, "remove_task_worktree", hang)
    set_task_fields(board, task.id, status="done")
    board.service.schedule_worktree_removal(get_task(board, task.id))
    await asyncio.wait_for(started.wait(), 2)

    await board.service.shutdown()  # the removal is cut in the middle

    with closing(db.connect(board.db_path)) as conn:
        marks = conn.execute(
            "SELECT key FROM app_state WHERE key LIKE 'org_worktree_removal:%'"
        ).fetchall()
    assert [row[0] for row in marks] == [f"org_worktree_removal:{task.id}"]


async def test_a_decision_asked_by_the_run_counts_as_its_report(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    task = await new_task(board, agent)
    run = await first_run(board, agent, pauses[0], task.id)
    with closing(db.connect(board.db_path)) as conn, db.transaction(conn):
        store.create_decision(
            conn, project_id=board.project.id, task_id=task.id, agent_id=agent, run_id=run.id,
            question="Posso?", options=[], now=1,
        )

    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
    await asyncio.sleep(0.1)

    assert len(task_runs(board, task.id)) == 1  # no `sem_relato`: the question is the report
    assert not any(kind == "app" for kind, _ in comments(board, task.id))


async def test_task_blocked_by_an_agent_at_the_run_count_is_not_a_cap_block(board):
    agent = board.add_agent()
    pauses = scripted_pauses(board, 0)
    board.set_enabled(agent, False)
    task = await new_task(board, agent)
    # Blocked by an agent (another reason) with the count exactly at the cap.
    set_task_fields(
        board, task.id, status="blocked", run_count=19, max_runs=20, blocked_reason="Sem acesso."
    )
    board.set_enabled(agent, True)

    await board.service.drain(agent)
    await reached(pauses[0])

    [run] = task_runs(board, task.id)  # woken: only the cap's own reason drops a wakeup
    assert run.task_id == task.id
    await agent_comments(board, task.id, agent, run, "Feito.")
    pauses[0].release.set()
    await wait_until(lambda: outcome_of(board, run.id) == "concluded")
