"""Marcações de sessão: dados, PATCH, regras de envio, inatividade e acordar."""

import pytest
from test_sessions import env_cleanup, make_env, session_row  # noqa: F401

from claudio_maestro.sessions import InvalidMarkError, SessionRecord, resolve_mark

NOW = 1_800_000_000


def rec(**kw) -> SessionRecord:
    base = dict(session_id="s", project_id=1, cwd="/x", title="t", created_at=0, last_activity_at=0)
    return SessionRecord(**{**base, **kw})


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


def test_resolve_mark_on_hold_with_date():
    assert resolve_mark(rec(), mark="on_hold", mark_note=..., mark_until=NOW + 60, now=NOW) == {
        "mark": "on_hold",
        "mark_until": NOW + 60,
    }


def test_resolve_mark_nothing_sent_changes_nothing():
    assert resolve_mark(rec(mark="review"), mark=..., mark_note=..., mark_until=..., now=NOW) == {}


def test_changing_mark_drops_old_note():
    # blocked -> on_hold without a note must not keep the old note.
    record = rec(mark="blocked", mark_note="esperando CI")
    assert resolve_mark(record, mark="on_hold", mark_note=..., mark_until=..., now=NOW) == {
        "mark": "on_hold",
        "mark_note": None,
    }


def test_note_is_collapsed_and_empty_becomes_none():
    out = resolve_mark(rec(), mark="blocked", mark_note="  esperando\n CI  ", mark_until=..., now=NOW)
    assert out == {"mark": "blocked", "mark_note": "esperando CI"}
    out = resolve_mark(rec(), mark="blocked", mark_note="   ", mark_until=..., now=NOW)
    assert out == {"mark": "blocked"}


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(mark="review", mark_note="x", mark_until=...),  # note without blocked
        dict(mark="blocked", mark_note=..., mark_until=NOW + 60),  # date without on_hold
        dict(mark="on_hold", mark_note=..., mark_until=NOW),  # not in the future
        dict(mark="on_hold", mark_note=..., mark_until=NOW + 366 * 86_400),  # past one year
        dict(mark="other", mark_note=..., mark_until=...),
    ],
)
def test_resolve_mark_rejects(kwargs):
    with pytest.raises(InvalidMarkError):
        resolve_mark(rec(), now=NOW, **kwargs)


def test_removing_mark_clears_note_and_date():
    record = rec(mark="on_hold", mark_until=NOW + 60)
    assert resolve_mark(record, mark=None, mark_note=..., mark_until=..., now=NOW) == {
        "mark": None,
        "mark_until": None,
    }


@pytest.mark.anyio
async def test_update_sets_mark_and_announces(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    summary = await env.manager.update(session.session_id, mark="blocked", mark_note="esperando CI")
    assert summary["mark"] == "blocked" and summary["mark_note"] == "esperando CI"
    assert session_row(env.db_path, session.session_id)["mark"] == "blocked"
    [event] = env.recorder.of(session.session_id, "session.updated")
    assert event["data"] == summary


@pytest.mark.anyio
async def test_priority_toggles(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    assert (await env.manager.update(session.session_id, priority=True))["priority"] is True
    assert (await env.manager.update(session.session_id, priority=False))["priority"] is False


@pytest.mark.anyio
async def test_finishing_clears_mark_and_priority(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, mark="review", priority=True)
    summary = await env.manager.update(session.session_id, finished=True)
    assert summary["finished"] is True
    assert summary["mark"] is None and summary["priority"] is False
    reopened = await env.manager.update(session.session_id, finished=False)
    assert reopened["mark"] is None


@pytest.mark.anyio
async def test_marking_a_finished_session_reopens_it(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, finished=True)
    summary = await env.manager.update(session.session_id, mark="on_hold")
    assert summary["finished"] is False
    assert summary["finished_at"] is None
    assert summary["mark"] == "on_hold"


@pytest.mark.anyio
async def test_priority_on_a_finished_session_reopens_it(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, finished=True)
    summary = await env.manager.update(session.session_id, priority=True)
    assert summary["finished"] is False and summary["priority"] is True
