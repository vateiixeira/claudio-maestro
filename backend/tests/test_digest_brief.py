"""Short sentence and plan seal of the digest in the session summary."""

from contextlib import closing
from pathlib import Path

import pytest
from test_sessions import Env

from claudio_maestro import db
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.digest import store
from claudio_maestro.digest.store import Digest
from claudio_maestro.sessions import SessionManager


@pytest.mark.anyio
async def test_summary_carries_the_brief_and_announces_changes(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    sid = record.session_id
    item = next(s for s in env.manager.list_sessions() if s["session_id"] == sid)
    assert item["digest_short"] is None and item["plan_done"] is False

    await env.manager.set_digest_brief(sid, "Executa o plano X", True)
    item = next(s for s in env.manager.list_sessions() if s["session_id"] == sid)
    assert item["digest_short"] == "Executa o plano X" and item["plan_done"] is True
    updates = [e for e in env.recorder.envelopes
               if e["type"] == "session.updated" and e["data"]["session_id"] == sid]
    assert updates and updates[-1]["data"]["digest_short"] == "Executa o plano X"

    count = len(env.recorder.envelopes)
    await env.manager.set_digest_brief(sid, "Executa o plano X", True)
    assert len(env.recorder.envelopes) == count  # unchanged: nothing published
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_briefs_are_loaded_at_startup(tmp_path: Path) -> None:
    env = Env(tmp_path, FakeAgentFactory())
    record = env.manager.create_session(env.project)
    with closing(db.connect(env.db_path)) as conn:
        store.save_digest(conn, Digest(record.session_id, short="Salvo", plan_done=True))
    await env.manager.shutdown()
    restarted = SessionManager(env.db_path, env.recorder, agent_factory=FakeAgentFactory())
    item = next(s for s in restarted.list_sessions() if s["session_id"] == record.session_id)
    assert item["digest_short"] == "Salvo" and item["plan_done"] is True
    await restarted.shutdown()


def test_session_out_accepts_the_fields() -> None:
    from claudio_maestro.api.sessions import SessionOut

    assert "digest_short" in SessionOut.model_fields and "plan_done" in SessionOut.model_fields
