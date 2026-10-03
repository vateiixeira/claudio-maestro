"""Marcações de sessão: dados, PATCH, regras de envio, inatividade e acordar."""

import pytest
from test_sessions import env_cleanup, make_env, session_row  # noqa: F401


@pytest.mark.anyio
async def test_new_session_has_no_mark(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    summary = env.manager.summary(session.session_id)
    assert summary["mark"] is None
    assert summary["mark_note"] is None
    assert summary["mark_until"] is None
    assert summary["priority"] is False
    row = session_row(env.db_path, session.session_id)
    assert row["mark"] is None and row["priority"] == 0
