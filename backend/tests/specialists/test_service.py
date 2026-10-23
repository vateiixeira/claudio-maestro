"""SpecialistService: runs, outcomes, notices, the session setup and the policy. Uses the
scripted fake agent; the real SDK is never touched."""

import asyncio
import json
import logging
import shutil
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ToolPermissionContext
from test_sessions import Recorder, fake_history, make_project, wait_until

from claudio_maestro import db
from claudio_maestro.agent.fake import (
    FakeAgentFactory,
    PauseStep,
    PermissionStep,
    init_message,
    text_turn,
)
from claudio_maestro.digest.closure_store import Closure
from claudio_maestro.sessions import SessionManager
from claudio_maestro.specialists import store
from claudio_maestro.specialists.files import SpecialistFiles
from claudio_maestro.specialists.policy import GitContext
from claudio_maestro.specialists.service import SpecialistService
from claudio_maestro.specialists.tools import SERVER_NAME

pytestmark = pytest.mark.anyio

NOW = 1_700_000_000
SECRET = "SEGREDO-DO-SECRETS-ENV"


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.db_path = tmp_path / "data" / "maestro.db"
        db.init_db(self.db_path)
        self.project = make_project(self.db_path, tmp_path / "home" / "app")
        self.now = NOW
        self.recorder = Recorder()
        # The turn every send plays, from the session id of the newest client.
        self.turns: Callable[[str], list] = lambda sid: text_turn(sid, "feito")
        self.factory = FakeAgentFactory(
            script=lambda content: self.turns(self.factory.clients[-1].options.session_id)
        )
        self.files = SpecialistFiles(tmp_path / "agents")
        self.manager = SessionManager(
            self.db_path,
            self.recorder,
            agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            session_setup=lambda record: self.service.session_setup(record),
            on_finished=lambda sid, at: self.service.on_finished(sid, at),
            on_turn_error=lambda sid, error: self.service.on_turn_error(sid, error),
            on_init=lambda sid, servers: self.service.on_init(sid, servers),
        )
        self.service = SpecialistService(
            self.db_path,
            files=self.files,
            sessions=self.manager,
            publish=self.recorder,
            clock=lambda: self.now,
            finish_poll=0.005,
        )

    def add_project(self, name: str, folder: str) -> int:
        project = make_project(self.db_path, self.tmp_path / "home" / folder)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project.id))
        return project.id

    def add_specialist(self, slug: str = "revisor", name: str = "Revisor", **fields: Any) -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            created = store.create_specialist(
                conn, slug=slug, name=name, project_id=self.project.id, now=1
            )
            if fields:
                store.update_specialist(conn, created.id, now=1, **fields)
        self.files.create(slug, name)
        return created.id

    def specialist(self, specialist_id: int) -> store.Specialist:
        with closing(db.connect(self.db_path)) as conn:
            return store.get_specialist(conn, specialist_id)

    def run_of(self, session_id: str) -> store.Run:
        with closing(db.connect(self.db_path)) as conn:
            run = store.run_for_session(conn, session_id)
        assert run is not None
        return run

    def runs(self, specialist_id: int) -> list[store.Run]:
        with closing(db.connect(self.db_path)) as conn:
            return store.list_runs(conn, specialist_id)

    def notices(self) -> list[store.Notice]:
        with closing(db.connect(self.db_path)) as conn:
            return list(reversed(store.list_notices(conn)))

    def published(self, type_: str) -> list[dict[str, Any]]:
        return [e["data"] for e in self.recorder.of(None, type_)]

    def record(self, session_id: str):
        return self.manager.find_record(session_id)


@pytest.fixture
async def world(tmp_path: Path):
    built = World(tmp_path)
    yield built
    await built.service.shutdown()
    await built.manager.shutdown()


async def started(world: World, specialist_id: int, **kwargs: Any) -> store.Run:
    run = await world.service.start_run(specialist_id, trigger="manual", **kwargs)
    assert run.session_id is not None
    await wait_until(lambda: world.manager.get(run.session_id).state == "idle")
    return run


# start_run ------------------------------------------------------------------


async def test_start_run_creates_linked_session_and_sends_run_text(world):
    specialist_id = world.add_specialist(model="haiku", effort="low", run_text="Faça a ronda.")

    run = await world.service.start_run(
        specialist_id, trigger="schedule", scheduled_for=NOW - 30
    )

    assert run.outcome == "running" and run.trigger == "schedule"
    assert run.scheduled_for == NOW - 30 and run.started_at == NOW
    assert run.session_id is not None
    session = world.manager.get(run.session_id)
    assert session.record.specialist_id == specialist_id
    assert session.record.project_id == world.project.id
    assert (session.record.model, session.record.effort) == ("haiku", "low")
    assert session.record.permission_mode == "default"
    expected_title = f"Revisor · {datetime.fromtimestamp(NOW):%d/%m %H:%M}"
    assert session.record.title == expected_title
    await wait_until(lambda: world.factory.clients and world.factory.clients[0].sent)
    assert world.factory.clients[0].sent == ["Faça a ronda."]
    assert world.run_of(run.session_id) == run
    assert world.published("specialist.run")[-1]["id"] == run.id


async def test_start_run_uses_the_given_text_instead_of_the_run_text(world):
    specialist_id = world.add_specialist(run_text="Rotina.")

    await world.service.start_run(specialist_id, trigger="manual", text="Só olhe o PR 12.")

    await wait_until(lambda: world.factory.clients and world.factory.clients[0].sent)
    assert world.factory.clients[0].sent == ["Só olhe o PR 12."]


async def test_start_run_missing_project_records_failed(world):
    specialist_id = world.add_specialist()
    shutil.rmtree(world.project.path)

    run = await world.service.start_run(specialist_id, trigger="manual")

    assert run.outcome == "failed" and run.session_id is None
    assert run.reason and "projeto" in run.reason.lower()
    assert run.ended_at == NOW
    assert world.factory.clients == []
    assert world.runs(specialist_id) == [run]
    assert world.published("specialist.run")[-1]["outcome"] == "failed"


async def test_start_run_for_unknown_agent_raises(world):
    with pytest.raises(store.SpecialistNotFoundError):
        await world.service.start_run(404, trigger="manual")


async def test_start_run_send_failure_records_failed(world):
    specialist_id = world.add_specialist()

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("sem conexão")

    world.manager.send = boom  # type: ignore[method-assign]

    run = await world.service.start_run(specialist_id, trigger="manual")

    assert run.outcome == "failed" and "sem conexão" in (run.reason or "")


# conclude / notify ------------------------------------------------------------


async def test_conclude_finishes_session_and_records_summary(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)

    await world.service.conclude(run.session_id, "Tratei 3 erros.")

    await wait_until(lambda: world.record(run.session_id).finished)
    saved = world.run_of(run.session_id)
    assert saved.outcome == "concluded" and saved.ended_at == NOW
    [notice] = world.notices()
    assert (notice.kind, notice.text, notice.specialist_id, notice.session_id) == (
        "summary", "Tratei 3 erros.", specialist_id, run.session_id
    )
    assert world.published("specialist.notice")[-1]["text"] == "Tratei 3 erros."
    assert world.published("specialist.run")[-1]["outcome"] == "concluded"


async def test_conclude_in_the_middle_of_the_turn_does_not_wait_for_it(world):
    specialist_id = world.add_specialist()
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    session = world.manager.get(run.session_id)
    assert session.state == "running"

    # The tool runs inside the turn: waiting for the turn to end here would deadlock.
    await asyncio.wait_for(world.service.conclude(run.session_id, "Pronto."), 1)

    assert world.run_of(run.session_id).outcome == "concluded"
    assert [n.kind for n in world.notices()] == ["summary"]
    await asyncio.sleep(0.05)
    assert not world.record(run.session_id).finished  # waits for the turn to end
    pause.release.set()
    await wait_until(lambda: world.record(run.session_id).finished)
    assert session.state == "idle"


async def test_session_stays_finished_after_turn_that_concluded_ends(world):
    specialist_id = world.add_specialist(close_by_check=True)
    pause = PauseStep()
    world.turns = lambda sid: [init_message(sid), pause, *text_turn(sid, "ok")[1:]]
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    await world.service.conclude(run.session_id, "Pronto.")
    pause.release.set()
    session = world.manager.get(run.session_id)
    await wait_until(lambda: session.state == "idle" and world.record(run.session_id).finished)

    # A check after the end of the turn changes nothing either.
    await world.service.on_closure(Closure(run.session_id, verdict="can_close", evidence="ok"))
    await asyncio.sleep(0.05)

    assert world.record(run.session_id).finished is True
    assert world.run_of(run.session_id).outcome == "concluded"
    assert [n.kind for n in world.notices()] == ["summary"]
    assert session.summary()["display_state"] == "finished"


async def test_notify_records_a_notice(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)

    await world.service.notify(run.session_id, "Achei algo estranho.")

    [notice] = world.notices()
    assert (notice.kind, notice.text, notice.specialist_id) == (
        "notice", "Achei algo estranho.", specialist_id
    )
    assert world.run_of(run.session_id).outcome == "running"
    assert world.published("specialist.notice")[-1]["kind"] == "notice"


async def test_notify_of_a_session_without_agent_is_ignored(world):
    record = world.manager.create_session(world.project)

    await world.service.notify(record.session_id, "oi")
    await world.service.conclude(record.session_id, "fim")

    assert world.notices() == []
    assert world.record(record.session_id).finished is False


# A failed run can still end well -----------------------------------------------------


async def test_conclude_after_a_turn_error_concludes_the_run(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    world.service.on_turn_error(run.session_id, "O turno terminou com erro.")
    assert world.run_of(run.session_id).outcome == "failed"

    await world.service.conclude(run.session_id, "Terminei mesmo assim.")

    saved = world.run_of(run.session_id)
    assert saved.outcome == "concluded" and saved.ended_at == NOW
    await wait_until(lambda: world.record(run.session_id).finished)


async def test_closure_can_close_after_a_turn_error_closes_the_run(world):
    specialist_id = world.add_specialist(close_by_check=True)
    run = await started(world, specialist_id)
    world.service.on_turn_error(run.session_id, "O turno terminou com erro.")

    await world.service.on_closure(Closure(run.session_id, verdict="can_close", evidence="ok"))

    assert world.run_of(run.session_id).outcome == "closed"
    await wait_until(lambda: world.record(run.session_id).finished)


async def test_closure_user_action_after_a_turn_error_marks_waiting(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    world.service.on_turn_error(run.session_id, "O turno terminou com erro.")

    await world.service.on_closure(Closure(run.session_id, verdict="user_action", user_actions=["A"]))

    saved = world.run_of(run.session_id)
    assert saved.outcome == "waiting" and saved.ended_at is None
    assert [n.kind for n in world.notices()] == ["alert"]


# Finishing waits for the turn, and only if nothing happened meanwhile ---------------------


def paused_turn(world: World, *extra_first: Any) -> PauseStep:
    """The first turn pauses (then plays `extra_first`, then ends); later ones are plain."""
    pause = PauseStep()
    calls: list[str] = []

    def turns(sid: str) -> list:
        calls.append(sid)
        if len(calls) == 1:
            return [init_message(sid), pause, *extra_first, *text_turn(sid, "ok")[1:]]
        return text_turn(sid, "de novo")

    world.turns = turns
    return pause


async def test_finish_waits_while_the_turn_asks_for_a_decision(world):
    specialist_id = world.add_specialist()
    pause = paused_turn(world, PermissionStep("Bash", {"command": "git push origin main"}))
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    session = world.manager.get(run.session_id)
    await world.service.conclude(run.session_id, "Pronto.")

    pause.release.set()
    await wait_until(lambda: session.state == "awaiting_decision")
    await asyncio.sleep(0.1)  # many polls of the waiting task
    assert not world.record(run.session_id).finished

    [prompt] = session.prompts.values()
    session.resolve_prompt(prompt.prompt_id, "allow_once")
    await wait_until(lambda: world.record(run.session_id).finished)
    assert session.state == "idle"


async def test_finish_is_dropped_when_the_user_writes_before_it(world):
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    session = world.manager.get(run.session_id)
    await world.service.conclude(run.session_id, "Pronto.")

    await world.manager.send(run.session_id, "Na verdade, faça mais uma coisa.")
    pause.release.set()
    await wait_until(lambda: session.state == "idle" and len(world.factory.clients[0].sent) == 2)
    await asyncio.sleep(0.1)

    assert not world.record(run.session_id).finished
    assert not world.service._tasks


async def test_finish_is_dropped_when_the_user_finishes_and_reopens(world):
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    session = world.manager.get(run.session_id)
    await world.service.conclude(run.session_id, "Pronto.")

    await world.manager.update(run.session_id, finished=True)
    await world.manager.update(run.session_id, finished=False)
    assert not world.record(run.session_id).finished
    pause.release.set()
    await wait_until(lambda: session.state == "idle")
    await asyncio.sleep(0.1)

    assert not world.record(run.session_id).finished
    assert not world.service._tasks


async def test_finish_still_happens_when_nothing_else_changed(world):
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    await world.service.conclude(run.session_id, "Pronto.")
    pause.release.set()

    await wait_until(lambda: world.record(run.session_id).finished)


async def test_finish_keeps_waiting_past_the_warning_and_logs_it(world, monkeypatch, caplog):
    monkeypatch.setattr("claudio_maestro.specialists.service.FINISH_WARN_SECONDS", 0.05)
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    await world.service.conclude(run.session_id, "Pronto.")

    with caplog.at_level(logging.WARNING):
        await asyncio.sleep(0.2)
        assert not world.record(run.session_id).finished  # never finishes an open turn
        pause.release.set()
        await wait_until(lambda: world.record(run.session_id).finished)

    warnings = [r for r in caplog.records if "fim do turno" in r.getMessage()]
    assert len(warnings) == 1


async def test_shutdown_stops_a_waiting_finish(world):
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    session = world.manager.get(run.session_id)
    await world.service.conclude(run.session_id, "Pronto.")

    await world.service.shutdown()
    pause.release.set()
    await wait_until(lambda: session.state == "idle")
    await asyncio.sleep(0.05)

    assert not world.record(run.session_id).finished


async def test_finish_stops_quietly_when_the_session_is_gone(world, caplog):
    specialist_id = world.add_specialist()
    pause = paused_turn(world)
    run = await world.service.start_run(specialist_id, trigger="manual")
    await asyncio.wait_for(pause.reached.wait(), 2)
    await world.service.conclude(run.session_id, "Pronto.")

    world.manager._sessions.pop(run.session_id)
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (run.session_id,))
    with caplog.at_level(logging.ERROR):
        await wait_until(lambda: not world.service._tasks)

    assert caplog.records == []
    pause.release.set()


# Closure ----------------------------------------------------------------------


async def test_closure_can_close_finishes_when_close_by_check(world):
    specialist_id = world.add_specialist(close_by_check=True)
    run = await started(world, specialist_id)

    await world.service.on_closure(Closure(run.session_id, verdict="can_close", evidence="tudo certo"))

    await wait_until(lambda: world.record(run.session_id).finished)
    saved = world.run_of(run.session_id)
    assert saved.outcome == "closed" and saved.ended_at == NOW
    [notice] = world.notices()
    assert (notice.kind, notice.text) == ("summary", "Fechada pela verificação: tudo certo")


async def test_closure_can_close_ignored_when_close_by_check_off(world):
    specialist_id = world.add_specialist(close_by_check=False)
    run = await started(world, specialist_id)

    await world.service.on_closure(Closure(run.session_id, verdict="can_close", evidence="tudo certo"))
    await asyncio.sleep(0.05)

    assert world.run_of(run.session_id).outcome == "running"
    assert world.record(run.session_id).finished is False
    assert world.notices() == []


async def test_closure_user_action_marks_waiting_and_alerts_once(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    closure = Closure(
        run.session_id, verdict="user_action",
        user_actions=["Reiniciar o serviço"], missing=["Teste do login"],
    )

    await world.service.on_closure(closure)
    await world.service.on_closure(closure)

    assert world.run_of(run.session_id).outcome == "waiting"
    [alert] = world.notices()
    assert alert.kind == "alert" and alert.specialist_id == specialist_id
    assert "Reiniciar o serviço" in alert.text and "Teste do login" in alert.text
    assert world.record(run.session_id).finished is False


async def test_closure_incomplete_marks_waiting_and_alerts(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)

    await world.service.on_closure(
        Closure(run.session_id, verdict="incomplete", missing=["Rodar os testes"])
    )

    assert world.run_of(run.session_id).outcome == "waiting"
    [alert] = world.notices()
    assert alert.kind == "alert" and "Rodar os testes" in alert.text


async def test_closure_new_items_alert_again(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)

    await world.service.on_closure(Closure(run.session_id, verdict="user_action", user_actions=["A"]))
    await world.service.on_closure(Closure(run.session_id, verdict="user_action", user_actions=["B"]))

    assert len(world.notices()) == 2


async def test_closure_in_progress_and_without_verdict_do_nothing(world):
    specialist_id = world.add_specialist(close_by_check=True)
    run = await started(world, specialist_id)

    await world.service.on_closure(Closure(run.session_id, verdict="in_progress"))
    await world.service.on_closure(Closure(run.session_id, verdict=None, error="falhou"))

    assert world.run_of(run.session_id).outcome == "running"
    assert world.notices() == []


async def test_closure_of_an_ordinary_session_is_ignored(world):
    world.add_specialist(close_by_check=True)
    record = world.manager.create_session(world.project)

    await world.service.on_closure(Closure(record.session_id, verdict="can_close", evidence="x"))
    await world.service.on_closure(Closure("nao-existe", verdict="can_close", evidence="x"))

    assert world.notices() == []
    assert world.record(record.session_id).finished is False


async def test_closure_after_the_run_ended_is_ignored(world):
    specialist_id = world.add_specialist(close_by_check=True)
    run = await started(world, specialist_id)
    await world.service.conclude(run.session_id, "Pronto.")

    await world.service.on_closure(Closure(run.session_id, verdict="user_action", user_actions=["A"]))

    assert world.run_of(run.session_id).outcome == "concluded"
    assert [n.kind for n in world.notices()] == ["summary"]


# Finish by the user ---------------------------------------------------------------


async def test_user_finish_concludes_run(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)

    await world.manager.update(run.session_id, finished=True)

    saved = world.run_of(run.session_id)
    assert (saved.outcome, saved.reason) == ("concluded", "Finalizada por você")
    assert saved.ended_at is not None
    assert world.published("specialist.run")[-1]["reason"] == "Finalizada por você"


async def test_user_finish_of_a_waiting_run_concludes_it(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    await world.service.on_closure(Closure(run.session_id, verdict="incomplete", missing=["X"]))

    await world.manager.update(run.session_id, finished=True)

    assert world.run_of(run.session_id).outcome == "concluded"


async def test_user_finish_keeps_the_outcome_of_an_ended_run(world):
    specialist_id = world.add_specialist(close_by_check=True)
    run = await started(world, specialist_id)
    await world.service.on_closure(Closure(run.session_id, verdict="can_close", evidence="ok"))
    await wait_until(lambda: world.record(run.session_id).finished)

    world.service.on_finished(run.session_id, NOW + 5)

    saved = world.run_of(run.session_id)
    assert (saved.outcome, saved.reason) == ("closed", None)


# Turn errors ----------------------------------------------------------------------


async def test_turn_error_fails_run_and_two_in_a_row_alert_once(world):
    specialist_id = world.add_specialist()
    sessions = []
    for index in range(3):
        world.now = NOW + index * 100
        run = await started(world, specialist_id)
        sessions.append(run.session_id)

    world.service.on_turn_error(sessions[0], "O turno terminou com erro.")
    assert world.run_of(sessions[0]).outcome == "failed"
    assert world.notices() == []  # only one in a row
    world.service.on_turn_error(sessions[1], "Limite de uso atingido.")
    world.service.on_turn_error(sessions[2], "A API está com problemas.")

    saved = world.run_of(sessions[1])
    assert (saved.outcome, saved.reason) == ("failed", "Limite de uso atingido.")
    [alert] = world.notices()
    assert alert.kind == "alert" and alert.session_id == sessions[1]
    assert alert.text == (
        "Revisor: duas execuções seguidas sem sucesso. Última: Limite de uso atingido."
    )
    assert world.published("specialist.notice")[-1]["kind"] == "alert"


async def test_turn_error_only_changes_a_running_run(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    await world.service.conclude(run.session_id, "Pronto.")

    world.service.on_turn_error(run.session_id, "erro tardio")
    world.service.on_turn_error("nao-existe", "erro")

    assert world.run_of(run.session_id).outcome == "concluded"


async def test_a_success_between_failures_restarts_the_sequence(world):
    specialist_id = world.add_specialist()
    outcomes = ["failed", "concluded", "failed"]
    for index, outcome in enumerate(outcomes):
        world.now = NOW + index * 100
        run = await started(world, specialist_id)
        if outcome == "failed":
            world.service.on_turn_error(run.session_id, "erro")
        else:
            await world.service.conclude(run.session_id, "ok")

    assert [n.kind for n in world.notices()] == ["summary"]


async def test_skipped_runs_count_toward_the_alert(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    world.service.on_turn_error(run.session_id, "erro")

    skipped = world.service.record_skipped(
        specialist_id, "O projeto estava indisponível.", scheduled_for=NOW
    )

    assert (skipped.outcome, skipped.trigger) == ("skipped", "schedule")
    [alert] = world.notices()
    assert alert.text.endswith("Última: O projeto estava indisponível.")


# on_init -----------------------------------------------------------------------------


async def test_on_init_saves_the_mcp_servers_once(world):
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    servers = [{"name": "maestro", "status": "connected"}, {"name": "sentry", "status": "failed"}]

    world.service.on_init(run.session_id, servers)

    assert world.specialist(specialist_id).last_mcp == servers
    updated_at = world.specialist(specialist_id).updated_at
    world.now += 500
    world.service.on_init(run.session_id, servers)
    assert world.specialist(specialist_id).updated_at == updated_at
    world.service.on_init("nao-existe", [])
    world.service.on_init(world.manager.create_session(world.project).session_id, servers)


# session_setup --------------------------------------------------------------------


async def test_session_setup_none_for_plain_session(world):
    world.add_specialist()
    record = world.manager.create_session(world.project)

    assert world.service.session_setup(record) is None


async def test_session_setup_env_has_secrets_and_prompt_has_no_secret_values(world):
    specialist_id = world.add_specialist()
    world.files.write_secrets("revisor", {"SENTRY_TOKEN": SECRET})
    world.files.write_learnings("revisor", "Prefira commits pequenos.")
    extra_id = world.add_project("api", "api")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_specialist(
            conn, specialist_id, now=1, extra_project_ids=[extra_id, 9999],
            outward_patterns=["terraform apply"], always_ask_patterns=["rm -rf"],
        )
    record = world.manager.create_session(world.project, specialist_id=specialist_id)

    extras = world.service.session_setup(record)

    assert extras is not None
    assert extras.env == {"SENTRY_TOKEN": SECRET}
    assert SECRET not in extras.system_prompt_append
    assert SECRET not in extras.settings
    assert "# Agente: Revisor" in extras.system_prompt_append
    assert "Prefira commits pequenos." in extras.system_prompt_append
    assert "- api: " + str(world.tmp_path / "home" / "api") in extras.system_prompt_append
    assert "Quando usar" in extras.system_prompt_append  # the body of the skill
    assert "name: " not in extras.system_prompt_append  # not its frontmatter
    assert extras.add_dirs == [world.tmp_path / "home" / "api"]
    assert list(extras.mcp_servers) == [SERVER_NAME]
    rules = json.loads(extras.settings)["permissions"]["ask"]
    assert "Bash(terraform apply:*)" in rules and "Bash(rm -rf:*)" in rules


async def test_session_setup_skips_unavailable_extra_projects(world):
    specialist_id = world.add_specialist()
    gone_id = world.add_project("antigo", "antigo")
    shutil.rmtree(world.tmp_path / "home" / "antigo")
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        store.update_specialist(conn, specialist_id, now=1, extra_project_ids=[gone_id])
    record = world.manager.create_session(world.project, specialist_id=specialist_id)

    extras = world.service.session_setup(record)

    assert extras is not None and extras.add_dirs == []
    assert "- Só a pasta de origem." in extras.system_prompt_append
    assert "antigo" not in extras.system_prompt_append


async def test_session_setup_reaches_the_agent_options(world):
    specialist_id = world.add_specialist()
    world.files.write_secrets("revisor", {"TOKEN": SECRET})

    run = await started(world, specialist_id)

    [options] = [c.options for c in world.factory.clients]
    assert options.env == {"TOKEN": SECRET}
    assert SERVER_NAME in options.mcp_servers
    assert options.settings is not None
    assert run.session_id == options.session_id


async def test_session_setup_error_does_not_quote_secrets(world, tmp_path, caplog):
    specialist_id = world.add_specialist()
    world.files.write_secrets("revisor", {"TOKEN": SECRET})
    (tmp_path / "agents" / "revisor" / "SKILL.md").write_text("sem cabeçalho", encoding="utf-8")
    record = world.manager.create_session(world.project, specialist_id=specialist_id)

    with pytest.raises(Exception) as info:
        world.service.session_setup(record)

    assert SECRET not in str(info.value)


# decide --------------------------------------------------------------------------


def make_decide(world: World, **fields: Any):
    specialist_id = world.add_specialist(**fields)
    record = world.manager.create_session(world.project, specialist_id=specialist_id)
    extras = world.service.session_setup(record)
    assert extras is not None
    return extras.decide, record


async def test_decide_routes_tools(world, monkeypatch):
    async def git_on_main(work_dir: Path) -> GitContext:
        return GitContext(default_branch="main", current_branch="feature")

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", git_on_main)
    decide, _ = make_decide(world, autonomy="full")

    assert await decide("mcp__maestro__registro_gravar", {}) == "allow"
    assert await decide("mcp__maestro__concluir", {}) == "allow"
    assert await decide("AskUserQuestion", {"questions": []}) == "ask"
    assert await decide("ExitPlanMode", {}) == "ask"
    assert await decide("Bash", {"command": "git push origin main"}) == "ask"
    assert await decide("Bash", {"command": "git push origin feature"}) == "allow"
    assert await decide("Bash", {"command": "ls -la"}) == "allow"
    assert await decide("Edit", {"file_path": "a.py"}) == "allow"
    assert await decide("Read", {"file_path": "a.py"}) == "allow"


async def test_decide_in_ask_autonomy_asks_for_any_push(world, monkeypatch):
    async def git_on_main(work_dir: Path) -> GitContext:
        return GitContext(default_branch="main", current_branch="feature")

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", git_on_main)
    decide, _ = make_decide(world, autonomy="ask")

    assert await decide("Bash", {"command": "git push origin feature"}) == "ask"
    assert await decide("Bash", {"command": "ls"}) == "allow"


async def test_decide_asks_for_a_bash_call_without_a_command(world, monkeypatch):
    async def no_git(work_dir: Path) -> GitContext:
        return GitContext(None, None)

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", no_git)
    decide, _ = make_decide(world)

    assert await decide("Bash", {}) == "ask"
    assert await decide("Bash", {"command": 7}) == "ask"


async def test_decide_uses_the_autonomy_and_patterns_of_the_agent(world, monkeypatch):
    async def no_git(work_dir: Path) -> GitContext:
        return GitContext(None, None)

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", no_git)
    decide, _ = make_decide(world, autonomy="full", always_ask_patterns=["terraform destroy"])

    assert await decide("Bash", {"command": "terraform destroy"}) == "ask"
    assert await decide("Bash", {"command": "gh pr comment 1 --body oi"}) == "allow"


async def test_decide_reads_the_work_dir_at_each_call(world, monkeypatch):
    seen: list[Path] = []

    async def spy(work_dir: Path) -> GitContext:
        seen.append(work_dir)
        return GitContext(None, None)

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", spy)
    decide, record = make_decide(world)

    await decide("Bash", {"command": "git status"})
    record.cwd = "/outra/pasta"  # the session moved (a worktree, say)
    await decide("Bash", {"command": "git status"})

    assert seen == [Path(world.project.path), Path("/outra/pasta")]


async def test_decide_does_not_read_git_for_other_tools(world, monkeypatch):
    async def spy(work_dir: Path) -> GitContext:
        raise AssertionError("git context read without a Bash call")

    monkeypatch.setattr("claudio_maestro.specialists.service.read_git_context", spy)
    decide, _ = make_decide(world)

    assert await decide("Edit", {}) == "allow"
    assert await decide("mcp__maestro__avisar", {}) == "allow"


async def test_permission_callback_of_the_session_uses_the_agent_policy(world):
    # The session's permission callback uses the agent's policy end to end.
    specialist_id = world.add_specialist()
    run = await started(world, specialist_id)
    can_use_tool = world.factory.clients[0].options.can_use_tool

    result = await can_use_tool("Read", {"file_path": "a.txt"}, ToolPermissionContext(tool_use_id="t1"))

    assert type(result).__name__ == "PermissionResultAllow"
    assert world.manager.get(run.session_id).prompts == {}


# ToolHost -------------------------------------------------------------------------


async def test_tool_host_registry_round_trip(world):
    specialist_id = world.add_specialist()

    saved = world.service.record(specialist_id, "erro-1", "feito", "http://x", "nota")
    [found] = world.service.lookup(specialist_id, ["erro-1", "outro"])

    assert saved.key == "erro-1" == found.key
    assert (found.status, found.link, found.note) == ("feito", "http://x", "nota")
    assert found.updated_at == NOW


async def test_tool_host_refuses_an_unknown_agent_before_writing(world):
    with pytest.raises(store.SpecialistNotFoundError):
        world.service.record(404, "k", "feito", None, None)
    with pytest.raises(store.SpecialistNotFoundError):
        world.service.rewrite_learnings(404, "texto")


async def test_tool_host_rewrites_learnings(world):
    specialist_id = world.add_specialist()

    world.service.rewrite_learnings(specialist_id, "Aprendi X.")

    assert world.files.read_learnings("revisor") == "Aprendi X."
