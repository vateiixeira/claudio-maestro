"""SessionManager tells who is listening when a session goes from open to finished."""

import pytest
from test_sessions import fake_history, make_project

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.sessions import SessionManager


@pytest.mark.anyio
async def test_on_finished_runs_once_per_open_to_finished(tmp_path) -> None:
    db_path = tmp_path / "data" / "maestro.db"
    db.init_db(db_path)
    project = make_project(db_path, tmp_path / "home" / "app")
    calls: list[tuple[str, int]] = []
    factory = FakeAgentFactory()
    manager = SessionManager(db_path, lambda e: None, agent_factory=factory,
                             history_exists=fake_history(factory),
                             on_finished=lambda sid, at: calls.append((sid, at)))
    try:
        sid = manager.create_session(project).session_id
        summary = await manager.update(sid, finished=True)
        assert calls == [(sid, summary["finished_at"])]
        await manager.update(sid, finished=True)  # already finished: no new call
        assert len(calls) == 1
        await manager.update(sid, finished=False)
        await manager.update(sid, finished=True)
        assert len(calls) == 2
    finally:
        await manager.shutdown()


@pytest.mark.anyio
async def test_a_failing_listener_does_not_break_finishing(tmp_path) -> None:
    db_path = tmp_path / "data" / "maestro.db"
    db.init_db(db_path)
    project = make_project(db_path, tmp_path / "home" / "app")
    factory = FakeAgentFactory()

    def boom(sid: str, at: int) -> None:
        raise RuntimeError("x")

    manager = SessionManager(db_path, lambda e: None, agent_factory=factory,
                             history_exists=fake_history(factory), on_finished=boom)
    try:
        sid = manager.create_session(project).session_id
        assert (await manager.update(sid, finished=True))["finished"] is True
    finally:
        await manager.shutdown()
