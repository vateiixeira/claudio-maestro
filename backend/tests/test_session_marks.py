"""Marcações de sessão: dados, PATCH, regras de envio, inatividade e acordar."""

import asyncio

import pytest
from test_sessions import env_cleanup, make_env, session_row, wait_until  # noqa: F401

from claudio_maestro.agent.fake import text_turn
from claudio_maestro.sessions import (
    InvalidMarkError,
    SessionRecord,
    _now,
    display_state,
    resolve_mark,
)

NOW = 1_800_000_000
DAY = 86_400


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


def test_resolve_mark_note_limit_has_a_portuguese_message():
    ok = resolve_mark(rec(), mark="blocked", mark_note="x" * 80, mark_until=..., now=NOW)
    assert ok == {"mark": "blocked", "mark_note": "x" * 80}
    with pytest.raises(InvalidMarkError, match="A nota pode ter até 80 caracteres."):
        resolve_mark(rec(), mark="blocked", mark_note="x" * 81, mark_until=..., now=NOW)


def test_resolve_mark_counts_the_note_after_collapsing_spaces():
    note = "  " + "a  " * 26  # 78 letters once collapsed, longer before
    out = resolve_mark(rec(), mark="blocked", mark_note=note, mark_until=..., now=NOW)
    assert out["mark_note"] == " ".join(["a"] * 26)


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


@pytest.mark.anyio
async def test_priority_reopens_a_session_finished_by_inactivity(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    old = _now() - 10 * DAY
    session.save(last_activity_at=old)
    assert env.manager.summary(session.session_id)["display_state"] == "finished"
    summary = await env.manager.update(session.session_id, priority=True)
    assert summary["display_state"] != "finished"
    assert summary["last_activity_at"] > old


@pytest.mark.anyio
async def test_finishing_an_already_finished_session_drops_mark_and_priority(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, finished=True)
    summary = await env.manager.update(
        session.session_id, finished=True, mark="review", priority=True
    )
    assert summary["finished"] is True
    assert summary["mark"] is None and summary["priority"] is False
    row = session_row(env.db_path, session.session_id)
    assert row["mark"] is None and row["priority"] == 0


def test_marked_session_does_not_finish_by_inactivity():
    kw = dict(finished=False, last_activity_at=0, last_seen_at=0, now=10 * DAY, finished_after=3 * DAY)
    assert display_state("closed", **kw) == "finished"
    assert display_state("closed", marked=True, **kw) == "waiting"
    assert display_state("closed", marked=True, **{**kw, "finished": True}) == "finished"


@pytest.mark.anyio
async def test_sending_clears_mark_and_keeps_priority(make_env, env_cleanup):
    env = make_env(script=lambda content: text_turn("x", "ok"))
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, mark="blocked", mark_note="CI", priority=True)
    await session.send("vamos")
    await wait_until(lambda: session.state == "idle")
    summary = env.manager.summary(session.session_id)
    assert summary["mark"] is None and summary["mark_note"] is None
    assert summary["priority"] is True
    assert session_row(env.db_path, session.session_id)["mark"] is None


@pytest.mark.anyio
async def test_wake_marks_wakes_due_sessions(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    later = env.new_session()
    now = _now()
    await env.manager.update(session.session_id, mark="on_hold", mark_until=now + 60)
    await env.manager.update(later.session_id, mark="on_hold", mark_until=now + 600)
    env.recorder.envelopes.clear()

    woken = env.manager.wake_marks(now=now + 120)

    assert woken == [session.session_id]
    summary = env.manager.summary(session.session_id)
    assert summary["mark"] is None and summary["mark_until"] is None
    assert summary["unread"] is True
    assert summary["last_activity_at"] == now + 120
    assert env.recorder.of(session.session_id, "session.updated")
    assert env.manager.summary(later.session_id)["mark"] == "on_hold"


@pytest.mark.anyio
async def test_on_hold_without_date_never_wakes(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, mark="on_hold")
    assert env.manager.wake_marks(now=_now() + 10 * DAY) == []


@pytest.mark.anyio
async def test_listing_wakes_overdue_sessions(make_env, env_cleanup):
    # An overdue wake (computer asleep) is applied by the next listing.
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    # Seen a while ago, so the wake (fresh activity) shows as unread even within the same second.
    session.save(mark="on_hold", mark_until=_now() - 5, last_seen_at=_now() - 100)
    [listed] = [s for s in env.manager.list_sessions() if s["session_id"] == session.session_id]
    assert listed["mark"] is None
    assert listed["unread"] is True


@pytest.mark.anyio
async def test_removing_a_long_standing_mark_does_not_finish_the_session(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    old = _now() - 5 * DAY
    await env.manager.update(session.session_id, mark="blocked", mark_note="CI")
    session.save(last_activity_at=old)
    assert env.manager.summary(session.session_id)["display_state"] == "waiting"

    summary = await env.manager.update(session.session_id, mark=None)

    assert summary["mark"] is None
    assert summary["display_state"] == "waiting"
    assert summary["last_activity_at"] > old
    assert session_row(env.db_path, session.session_id)["last_activity_at"] > old


@pytest.mark.anyio
async def test_removing_a_recent_mark_keeps_last_activity(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    await env.manager.update(session.session_id, mark="review")
    recent = _now() - 60
    session.save(last_activity_at=recent)
    summary = await env.manager.update(session.session_id, mark=None)
    assert summary["last_activity_at"] == recent


@pytest.mark.anyio
async def test_wake_marks_survives_a_failing_session(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    broken = env.new_session()
    healthy = env.new_session()
    now = _now()
    await env.manager.update(broken.session_id, mark="on_hold", mark_until=now + 60)
    await env.manager.update(healthy.session_id, mark="on_hold", mark_until=now + 120)
    real_get = env.manager.get

    def get(session_id):
        if session_id == broken.session_id:
            raise RuntimeError("falha")
        return real_get(session_id)

    monkeypatch.setattr(env.manager, "get", get)

    woken = env.manager.wake_marks(now=now + 300)

    assert woken == [healthy.session_id]
    assert env.manager.summary(healthy.session_id)["mark"] is None


@pytest.mark.anyio
async def test_wake_marks_survives_a_failing_save(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    broken = env.new_session()
    healthy = env.new_session()
    now = _now()
    await env.manager.update(broken.session_id, mark="on_hold", mark_until=now + 60)
    await env.manager.update(healthy.session_id, mark="on_hold", mark_until=now + 120)

    def save(**changes):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(broken, "save", save)

    assert env.manager.wake_marks(now=now + 300) == [healthy.session_id]


@pytest.mark.anyio
async def test_idle_sweep_wakes_due_marks(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    session = env.new_session()
    session.save(mark="on_hold", mark_until=_now() - 5)
    real_sleep = asyncio.sleep
    rounds = 0

    async def fast_sleep(seconds):
        nonlocal rounds
        rounds += 1
        if rounds > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    with pytest.raises(asyncio.CancelledError):
        await env.manager.run_idle_sweep(0.01)
    assert env.manager.summary(session.session_id)["mark"] is None
    assert session_row(env.db_path, session.session_id)["mark"] is None


def test_resolve_mark_discarded_takes_no_note_or_date():
    assert resolve_mark(rec(), mark="discarded", mark_note=..., mark_until=..., now=NOW) == {
        "mark": "discarded",
    }


def test_resolve_mark_discarded_drops_old_note_and_date():
    record = rec(mark="blocked", mark_note="esperando CI")
    assert resolve_mark(record, mark="discarded", mark_note=..., mark_until=..., now=NOW) == {
        "mark": "discarded",
        "mark_note": None,
    }


@pytest.mark.parametrize(
    "extra",
    [{"mark_note": "x"}, {"mark_until": NOW + 60}],
)
def test_resolve_mark_discarded_rejects_note_and_date(extra):
    kwargs = {"mark_note": ..., "mark_until": ..., **extra}
    with pytest.raises(InvalidMarkError):
        resolve_mark(rec(), mark="discarded", now=NOW, **kwargs)
