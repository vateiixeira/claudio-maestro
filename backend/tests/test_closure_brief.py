"""closure_verdict in the session summaries."""

from contextlib import closing
from pathlib import Path

import pytest
from test_sessions import Env

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.digest.closure_store import Closure, save_closure
from claudio_maestro.sessions import SessionManager


def item(manager, sid: str) -> dict:
    return next(s for s in manager.list_sessions() if s["session_id"] == sid)


@pytest.mark.anyio
async def test_verdict_shows_until_new_activity(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    sid = record.session_id
    assert item(env.manager, sid)["closure_verdict"] is None

    await env.manager.set_closure_brief(sid, "can_close", record.last_activity_at + 10)
    assert item(env.manager, sid)["closure_verdict"] == "can_close"
    updates = [e for e in env.recorder.envelopes
               if e["type"] == "session.updated" and e["data"]["session_id"] == sid]
    assert updates[-1]["data"]["closure_verdict"] == "can_close"

    count = len(env.recorder.envelopes)
    await env.manager.set_closure_brief(sid, "can_close", record.last_activity_at + 10)
    assert len(env.recorder.envelopes) == count  # unchanged: nothing published

    env.manager.get(sid).save(last_activity_at=record.last_activity_at + 20)
    assert item(env.manager, sid)["closure_verdict"] is None  # stale
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_finished_hides_verdict(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    sid = record.session_id
    await env.manager.set_closure_brief(sid, "can_close", record.last_activity_at + 10)
    env.manager.get(sid).save(finished=True)
    assert item(env.manager, sid)["closure_verdict"] is None
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_briefs_are_loaded_at_startup(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    with closing(db.connect(env.db_path)) as conn:
        save_closure(conn, Closure(record.session_id, verdict="incomplete",
                                   checked_at=record.last_activity_at + 10))
    await env.manager.shutdown()
    restarted = SessionManager(env.db_path, env.recorder, agent_factory=FakeAgentFactory())
    assert item(restarted, record.session_id)["closure_verdict"] == "incomplete"
    await restarted.shutdown()


def test_session_out_accepts_the_field() -> None:
    from claudio_maestro.api.sessions import SessionOut

    assert "closure_verdict" in SessionOut.model_fields
