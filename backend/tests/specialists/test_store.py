"""Specialists store: CRUD, schedules, runs, items and notices over SQLite."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.specialists import store


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "t.db")) as c:
        db.migrate(c)
        for pid in (1, 2):
            c.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (?, 'p', ?, '#fff', 0, 0)",
                (pid, f"/tmp/p{pid}"),
            )
        yield c


def add_session(conn, session_id: str, agent_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, agent_id) VALUES (?, 1, '/tmp', 't', 0, 0, ?)",
        (session_id, agent_id),
    )


def make(conn, slug: str = "revisor", project_id: int = 1) -> store.Specialist:
    return store.create_specialist(conn, slug=slug, name="Revisor", project_id=project_id, now=100)


def test_create_and_get_round_trip(conn):
    created = make(conn)
    loaded = store.get_specialist(conn, created.id)
    assert loaded == created
    assert loaded.slug == "revisor" and loaded.name == "Revisor"
    assert loaded.project_id == 1
    assert loaded.extra_project_ids == [] and isinstance(loaded.extra_project_ids, list)
    assert loaded.outward_patterns == [] and loaded.always_ask_patterns == []
    assert loaded.last_mcp == []
    assert loaded.denied_tools == [] and isinstance(loaded.denied_tools, list)
    assert loaded.autonomy == "ask"
    assert loaded.close_by_check is True
    assert loaded.run_text == "Execute a rotina agendada."
    assert loaded.enabled is True
    assert loaded.model is None and loaded.effort is None
    assert loaded.created_at == 100 and loaded.updated_at == 100
    assert store.list_specialists(conn) == [created]


def test_queue_pause_is_independent_of_schedules(conn):
    created = make(conn)
    assert created.queue_paused is False
    paused = store.update_specialist(conn, created.id, now=200, queue_paused=True)
    assert paused.queue_paused is True and paused.enabled is True
    assert store.get_specialist(conn, created.id).queue_paused is True


def test_pending_runs_are_in_fifo_order_and_claim_once(conn):
    agent = make(conn)
    other = make(conn, slug="outro")
    add_session(conn, "session", agent.id)
    first = store.insert_run(conn, specialist_id=agent.id, trigger="manual", started_at=200, outcome="queued")
    second = store.insert_run(conn, specialist_id=agent.id, trigger="schedule", started_at=100, outcome="queued")
    third = store.insert_run(conn, specialist_id=other.id, trigger="manual", started_at=100, outcome="queued")
    assert [r.id for r in store.list_pending_runs(conn, agent.id)] == [first.id, second.id]
    assert [r.id for r in store.list_pending_runs(conn)] == [first.id, second.id, third.id]
    assert store.claim_run(conn, first.id, "session", 300)
    assert not store.claim_run(conn, first.id, "session", 400)
    claimed = store.get_run(conn, first.id)
    assert (claimed.outcome, claimed.session_id, claimed.started_at) == ("starting", "session", 300)


def test_run_history_always_includes_old_pending_deliveries(conn):
    agent = make(conn)
    old = store.insert_run(conn, specialist_id=agent.id, trigger="manual", started_at=1, outcome="queued")
    for index in range(60):
        store.insert_run(conn, specialist_id=agent.id, trigger="schedule", started_at=100 + index, outcome="skipped")
    rows = store.list_runs(conn, agent.id, limit=50)
    assert len(rows) == 51
    assert rows[-1] == old
    assert len({run.id for run in rows}) == len(rows)


def test_run_not_queued_error_has_a_portuguese_message():
    assert "fila" in str(store.RunNotQueuedError()).lower()


def test_update_specialist_round_trips_lists_and_flags(conn):
    created = make(conn)
    updated = store.update_specialist(
        conn,
        created.id,
        now=200,
        name="Outro",
        extra_project_ids=[2],
        autonomy="full",
        outward_patterns=["Bash(git push:*)"],
        always_ask_patterns=["Bash(rm:*)"],
        denied_tools=["mcp__kbgen-issues__editar_issue"],
        close_by_check=False,
        enabled=False,
        model="haiku",
        last_mcp=[{"name": "x", "status": "ok"}],
    )
    assert store.get_specialist(conn, created.id) == updated
    assert updated.name == "Outro" and updated.extra_project_ids == [2]
    assert updated.autonomy == "full"
    assert updated.outward_patterns == ["Bash(git push:*)"]
    assert updated.always_ask_patterns == ["Bash(rm:*)"]
    assert updated.denied_tools == ["mcp__kbgen-issues__editar_issue"]
    assert updated.close_by_check is False and updated.enabled is False
    assert updated.model == "haiku"
    assert updated.last_mcp == [{"name": "x", "status": "ok"}]
    assert updated.created_at == 100 and updated.updated_at == 200


def test_update_rejects_unknown_field(conn):
    created = make(conn)
    with pytest.raises(ValueError):
        store.update_specialist(conn, created.id, now=1, id=99)


def test_update_missing_specialist_raises(conn):
    with pytest.raises(store.SpecialistNotFoundError):
        store.update_specialist(conn, 999, now=1, name="x")


def test_get_missing_specialist_raises(conn):
    with pytest.raises(store.SpecialistNotFoundError):
        store.get_specialist(conn, 999)


def test_duplicate_slug_raises(conn):
    make(conn)
    with pytest.raises(store.DuplicateSlugError):
        make(conn)


def test_update_to_duplicate_slug_raises(conn):
    make(conn)
    other = make(conn, slug="outro")
    with pytest.raises(store.DuplicateSlugError):
        store.update_specialist(conn, other.id, now=2, slug="revisor")


def test_delete_project_cascades_specialist(conn):
    created = make(conn, project_id=2)
    conn.execute("DELETE FROM projects WHERE id = 2")
    with pytest.raises(store.SpecialistNotFoundError):
        store.get_specialist(conn, created.id)


def test_delete_specialist_keeps_session_with_null_link(conn):
    created = make(conn)
    add_session(conn, "s1", created.id)
    store.delete_specialist(conn, created.id)
    row = conn.execute("SELECT agent_id FROM sessions WHERE session_id = 's1'").fetchone()
    assert row is not None and row["agent_id"] is None
    with pytest.raises(store.SpecialistNotFoundError):
        store.delete_specialist(conn, created.id)


def test_delete_specialist_removes_children(conn):
    created = make(conn)
    store.replace_schedules(conn, created.id, [("1234567", "08:00")], now=1)
    store.insert_run(conn, specialist_id=created.id, trigger="manual", started_at=1, outcome="running")
    store.upsert_item(conn, created.id, key="k", status="open", link=None, note=None, now=1)
    store.add_notice(conn, specialist_id=created.id, session_id=None, kind="notice", text="oi", now=1)
    store.delete_specialist(conn, created.id)
    for table in ("specialist_schedules", "specialist_runs", "specialist_items", "specialist_notices"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_replace_schedules_starts_with_last_fired_now(conn):
    created = make(conn)
    first = store.replace_schedules(conn, created.id, [("12345", "08:00"), ("67", "10:30")], now=500)
    assert [(s.days, s.time, s.last_fired_at) for s in first] == [
        ("12345", "08:00", 500),
        ("67", "10:30", 500),
    ]
    assert all(s.specialist_id == created.id for s in first)
    store.mark_fired(conn, first[0].id, 900)
    assert store.list_schedules(conn, created.id)[0].last_fired_at == 900

    second = store.replace_schedules(conn, created.id, [("1", "09:00")], now=1000)
    assert [(s.days, s.time, s.last_fired_at) for s in second] == [("1", "09:00", 1000)]
    assert store.list_schedules(conn, created.id) == second
    assert store.list_schedules(conn) == second


def test_list_schedules_filters_by_specialist(conn):
    a = make(conn)
    b = make(conn, slug="outro")
    store.replace_schedules(conn, a.id, [("1", "08:00")], now=1)
    store.replace_schedules(conn, b.id, [("2", "09:00")], now=1)
    assert [s.days for s in store.list_schedules(conn, a.id)] == ["1"]
    assert len(store.list_schedules(conn)) == 2


def test_insert_and_finish_run(conn):
    created = make(conn)
    add_session(conn, "s1")
    run = store.insert_run(
        conn, specialist_id=created.id, trigger="schedule", started_at=10, outcome="running",
        session_id="s1", scheduled_for=9,
    )
    assert run.outcome == "running" and run.ended_at is None and run.reason is None
    assert run.session_id == "s1" and run.scheduled_for == 9
    store.finish_run(conn, run.id, outcome="failed", ended_at=20, reason="quebrou")
    [loaded] = store.list_runs(conn, created.id)
    assert (loaded.outcome, loaded.ended_at, loaded.reason) == ("failed", 20, "quebrou")
    assert store.run_for_session(conn, "s1") == loaded
    assert store.run_for_session(conn, "nope") is None
    assert store.get_run(conn, run.id) == loaded


def test_get_run_missing_raises(conn):
    with pytest.raises(store.SpecialistNotFoundError):
        store.get_run(conn, 999)


def test_run_for_session_returns_most_recent(conn):
    created = make(conn)
    add_session(conn, "s1")
    for started in (10, 30, 20):
        store.insert_run(
            conn, specialist_id=created.id, trigger="manual", started_at=started,
            outcome="concluded", session_id="s1",
        )
    assert store.run_for_session(conn, "s1").started_at == 30


def test_deleting_session_keeps_run_with_null_session(conn):
    created = make(conn)
    add_session(conn, "s1")
    store.insert_run(
        conn, specialist_id=created.id, trigger="manual", started_at=1, outcome="concluded",
        session_id="s1",
    )
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    [run] = store.list_runs(conn, created.id)
    assert run.session_id is None


def test_list_runs_newest_first_with_limit(conn):
    created = make(conn)
    for started in (1, 2, 3):
        store.insert_run(
            conn, specialist_id=created.id, trigger="manual", started_at=started, outcome="concluded"
        )
    assert [r.started_at for r in store.list_runs(conn, created.id)] == [3, 2, 1]
    assert [r.started_at for r in store.list_runs(conn, created.id, limit=2)] == [3, 2]


def test_last_runs_skips_outcomes_that_do_not_count(conn):
    created = make(conn)
    plan = [
        (1, "failed"), (2, "missed"), (3, "concluded"), (4, "running"),
        (5, "skipped"), (6, "waiting"), (7, "closed"),
    ]
    for started, outcome in plan:
        store.insert_run(
            conn, specialist_id=created.id, trigger="schedule", started_at=started, outcome=outcome
        )
    runs = store.last_runs(conn, created.id, 3)
    assert [(r.started_at, r.outcome) for r in runs] == [(7, "closed"), (6, "waiting"), (5, "skipped")]
    everything = store.last_runs(conn, created.id, 10)
    assert {r.outcome for r in everything} == {"failed", "skipped", "concluded", "closed", "waiting"}


def test_invalid_run_outcome_is_rejected(conn):
    created = make(conn)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_run(
            conn, specialist_id=created.id, trigger="manual", started_at=1, outcome="bogus"
        )


def test_items_get_only_requested_keys(conn):
    created = make(conn)
    for key in ("k1", "k2", "k3"):
        store.upsert_item(conn, created.id, key=key, status="open", link=None, note=None, now=1)
    found = store.get_items(conn, created.id, ["k1", "inexistente"])
    assert [i.key for i in found] == ["k1"]
    assert store.get_items(conn, created.id, []) == []
    assert [i.key for i in store.list_items(conn, created.id)] == ["k1", "k2", "k3"]


def test_items_are_scoped_per_specialist(conn):
    a = make(conn)
    b = make(conn, slug="outro")
    store.upsert_item(conn, a.id, key="k", status="open", link=None, note=None, now=1)
    assert store.get_items(conn, b.id, ["k"]) == []


def test_upsert_item_updates_and_keeps_created_at(conn):
    created = make(conn)
    first = store.upsert_item(
        conn, created.id, key="k", status="open", link="http://x", note="a", now=10
    )
    assert (first.created_at, first.updated_at) == (10, 10)
    second = store.upsert_item(conn, created.id, key="k", status="done", link=None, note="b", now=20)
    assert (second.status, second.link, second.note) == ("done", None, "b")
    assert (second.created_at, second.updated_at) == (10, 20)
    assert store.list_items(conn, created.id) == [second]


def test_delete_item(conn):
    created = make(conn)
    store.upsert_item(conn, created.id, key="k", status="open", link=None, note=None, now=1)
    store.delete_item(conn, created.id, "k")
    assert store.list_items(conn, created.id) == []


def test_notices_unread_and_mark_read(conn):
    created = make(conn)
    n1 = store.add_notice(conn, specialist_id=created.id, session_id=None, kind="notice", text="a", now=1)
    n2 = store.add_notice(conn, specialist_id=created.id, session_id=None, kind="alert", text="b", now=2)
    n3 = store.add_notice(conn, specialist_id=created.id, session_id=None, kind="summary", text="c", now=3)
    assert n1.read_at is None
    assert [n.id for n in store.list_notices(conn)] == [n3.id, n2.id, n1.id]
    assert [n.id for n in store.list_notices(conn, limit=2)] == [n3.id, n2.id]

    assert store.mark_notices_read(conn, [n1.id, n2.id], now=50) == 2
    assert [n.id for n in store.list_notices(conn, unread_only=True)] == [n3.id]
    # Already read: not counted again, and read_at keeps the first date.
    assert store.mark_notices_read(conn, [n1.id], now=60) == 0
    read = {n.id: n.read_at for n in store.list_notices(conn)}
    assert read[n1.id] == 50 and read[n3.id] is None
    assert store.mark_notices_read(conn, [], now=70) == 0


def test_notice_survives_session_deletion(conn):
    created = make(conn)
    add_session(conn, "s1")
    store.add_notice(conn, specialist_id=created.id, session_id="s1", kind="notice", text="a", now=1)
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    [notice] = store.list_notices(conn)
    assert notice.session_id is None


def test_pending_finishes_round_trip(conn):
    assert store.pending_finishes(conn) == []

    store.mark_finish_pending(conn, "s1")
    store.mark_finish_pending(conn, "s2")
    store.mark_finish_pending(conn, "s1")
    conn.execute("INSERT INTO app_state (key, value) VALUES ('outra', 'x')")

    assert sorted(store.pending_finishes(conn)) == ["s1", "s2"]
    assert store.is_finish_pending(conn, "s1")
    store.clear_finish_pending(conn, "s1")
    store.clear_finish_pending(conn, "nao-existe")
    assert store.pending_finishes(conn) == ["s2"]
    assert not store.is_finish_pending(conn, "s1")
    assert conn.execute("SELECT value FROM app_state WHERE key = 'outra'").fetchone()[0] == "x"


def test_remove_extra_project_from_every_agent(conn):
    first = make(conn, "um")
    second = make(conn, "dois")
    third = make(conn, "tres")
    store.update_specialist(conn, first.id, now=1, extra_project_ids=[2, 7])
    store.update_specialist(conn, second.id, now=1, extra_project_ids=[7])

    changed = store.remove_extra_project(conn, 2, now=50)

    assert changed == [first.id]
    assert store.get_specialist(conn, first.id).extra_project_ids == [7]
    assert store.get_specialist(conn, first.id).updated_at == 50
    assert store.get_specialist(conn, second.id).extra_project_ids == [7]
    assert store.get_specialist(conn, third.id).updated_at == 100


# Main conversation, announcements, PRs and PR comments ---------------------------------


def make_comment(comment_id: str = "issue:1", **overrides) -> store.PrComment:
    fields = dict(
        comment_id=comment_id, pr_url="https://github.com/o/r/pull/1", specialist_id=1,
        author="ana", body="corrija", path=None, line=None,
        html_url="https://github.com/o/r/pull/1#issuecomment-1", created_at=50,
        received_at=60, status="queued", batch_at=None,
    )
    fields.update(overrides)
    return store.PrComment(**fields)


def test_set_main_session_is_not_updatable(conn):
    created = make(conn)
    add_session(conn, "m1")
    assert created.main_session_id is None
    store.set_main_session(conn, created.id, "m1")
    assert store.get_specialist(conn, created.id).main_session_id == "m1"
    store.set_main_session(conn, created.id, None)
    assert store.get_specialist(conn, created.id).main_session_id is None
    with pytest.raises(ValueError):
        store.update_specialist(conn, created.id, now=1, main_session_id="m1")


def test_deleting_main_session_clears_the_link(conn):
    created = make(conn)
    add_session(conn, "m1")
    store.set_main_session(conn, created.id, "m1")
    conn.execute("DELETE FROM sessions WHERE session_id = 'm1'")
    assert store.get_specialist(conn, created.id).main_session_id is None


def test_run_accepts_comment_trigger(conn):
    created = make(conn)
    run = store.insert_run(
        conn, specialist_id=created.id, trigger="comment", started_at=1, outcome="running"
    )
    assert store.get_run(conn, run.id).trigger == "comment"


def test_pending_announcements_in_order_and_delivered(conn):
    created = make(conn)
    other = make(conn, slug="outro")
    add_session(conn, "s1")
    first = store.add_announcement(
        conn, specialist_id=created.id, run_id=None, session_id="s1", text="um", created_at=10
    )
    second = store.add_announcement(
        conn, specialist_id=created.id, run_id=None, session_id=None, text="dois", created_at=20
    )
    store.add_announcement(
        conn, specialist_id=other.id, run_id=None, session_id=None, text="alheio", created_at=15
    )
    assert first.delivered_at is None and first.session_id == "s1" and first.text == "um"

    assert [a.text for a in store.pending_announcements(conn, created.id)] == ["um", "dois"]

    store.mark_announcements_delivered(conn, [first.id], at=99)

    assert [a.text for a in store.pending_announcements(conn, created.id)] == ["dois"]
    listed = store.list_announcements(conn, created.id)
    assert {a.id: a.delivered_at for a in listed} == {first.id: 99, second.id: None}
    store.mark_announcements_delivered(conn, [], at=100)


def test_announcement_keeps_run_and_unlinks_on_run_delete(conn):
    created = make(conn)
    run = store.insert_run(
        conn, specialist_id=created.id, trigger="manual", started_at=1, outcome="concluded"
    )
    note = store.add_announcement(
        conn, specialist_id=created.id, run_id=run.id, session_id=None, text="t", created_at=1
    )
    assert note.run_id == run.id
    conn.execute("DELETE FROM specialist_runs WHERE id = ?", (run.id,))
    assert store.list_announcements(conn, created.id)[0].run_id is None


def test_list_announcements_newest_first_with_limit(conn):
    created = make(conn)
    for at in (1, 2, 3):
        store.add_announcement(
            conn, specialist_id=created.id, run_id=None, session_id=None, text=str(at),
            created_at=at,
        )
    assert [a.text for a in store.list_announcements(conn, created.id, limit=2)] == ["3", "2"]


def test_upsert_pr_keeps_known_session(conn):
    created = make(conn)
    add_session(conn, "s1")
    url = "https://github.com/o/r/pull/1"
    store.upsert_pr(conn, url=url, specialist_id=created.id, session_id="s1", created_at=5)
    store.upsert_pr(conn, url=url, specialist_id=created.id, session_id=None, created_at=9)
    pr = store.get_pr(conn, url)
    assert pr is not None
    assert (pr.session_id, pr.created_at, pr.closed, pr.polled_at) == ("s1", 5, False, None)
    assert store.get_pr(conn, "https://github.com/o/r/pull/2") is None


def test_upsert_pr_fills_missing_session(conn):
    created = make(conn)
    add_session(conn, "s2")
    url = "https://github.com/o/r/pull/1"
    store.upsert_pr(conn, url=url, specialist_id=created.id, session_id=None, created_at=5)
    store.upsert_pr(conn, url=url, specialist_id=created.id, session_id="s2", created_at=9)
    assert store.get_pr(conn, url).session_id == "s2"


def test_upsert_pr_normalizes_the_url(conn):
    created = make(conn)
    url = "https://github.com/o/r/pull/1"
    for spelled in (url + "/", url + "#issuecomment-5", url + "?x=1", url):
        store.upsert_pr(conn, url=spelled, specialist_id=created.id, session_id=None, created_at=5)
    assert [p.url for p in store.open_prs(conn)] == [url]
    assert store.get_pr(conn, url + "/") is not None
    store.mark_pr_polled(conn, url + "/", at=9)
    assert store.get_pr(conn, url).polled_at == 9
    store.close_pr(conn, url + "/")
    assert store.get_pr(conn, url).closed is True


def test_delete_run_removes_only_that_run(conn):
    created = make(conn)
    first = store.insert_run(
        conn, specialist_id=created.id, trigger="comment", started_at=1, outcome="running"
    )
    second = store.insert_run(
        conn, specialist_id=created.id, trigger="manual", started_at=2, outcome="running"
    )
    store.delete_run(conn, first.id)
    assert [r.id for r in store.list_runs(conn, created.id)] == [second.id]


def test_pr_poll_and_close(conn):
    created = make(conn)
    a, b = "https://github.com/o/r/pull/1", "https://github.com/o/r/pull/2"
    for url in (a, b):
        store.upsert_pr(conn, url=url, specialist_id=created.id, session_id=None, created_at=1)
    assert [p.url for p in store.open_prs(conn)] == [a, b]
    store.mark_pr_polled(conn, a, at=77)
    assert store.get_pr(conn, a).polled_at == 77
    store.close_pr(conn, a)
    assert store.get_pr(conn, a).closed is True
    assert [p.url for p in store.open_prs(conn)] == [b]


def test_deleting_session_unlinks_pr(conn):
    created = make(conn)
    add_session(conn, "s1")
    url = "https://github.com/o/r/pull/1"
    store.upsert_pr(conn, url=url, specialist_id=created.id, session_id="s1", created_at=1)
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    assert store.get_pr(conn, url).session_id is None


def test_insert_comment_is_idempotent(conn):
    created = make(conn)
    comment = make_comment(specialist_id=created.id)
    assert store.insert_comment(conn, comment) is True
    assert store.insert_comment(conn, comment) is False
    assert store.queued_comments(conn) == [comment]


def test_comment_status_and_queue(conn):
    created = make(conn)
    for n in (1, 2, 3):
        store.insert_comment(
            conn, make_comment(f"line:{n}", specialist_id=created.id, path="a.py", line=n,
                               received_at=60 + n)
        )
    assert [c.comment_id for c in store.queued_comments(conn)] == ["line:1", "line:2", "line:3"]
    store.mark_comments(conn, ["line:1", "line:2"], "delivered", batch_at=1000)
    store.mark_comments(conn, ["line:3"], "dropped", batch_at=None)
    assert store.queued_comments(conn) == []
    store.mark_comments(conn, [], "delivered", batch_at=1)
    row = conn.execute(
        "SELECT status, batch_at, path, line FROM specialist_pr_comments"
        " WHERE comment_id = 'line:1'"
    ).fetchone()
    assert tuple(row) == ("delivered", 1000, "a.py", 1)


def test_turns_today_counts_batches(conn):
    created = make(conn)
    url = "https://github.com/o/r/pull/1"
    day_start = 1000
    batches = {"issue:1": 1500, "issue:2": 1500, "issue:3": 1500, "issue:4": 1800, "issue:5": 900}
    for comment_id in batches:
        store.insert_comment(conn, make_comment(comment_id, specialist_id=created.id))
    for comment_id, batch_at in batches.items():
        store.mark_comments(conn, [comment_id], "delivered", batch_at=batch_at)
    store.insert_comment(
        conn, make_comment("issue:6", specialist_id=created.id, pr_url="https://github.com/o/r/pull/2")
    )
    store.mark_comments(conn, ["issue:6"], "delivered", batch_at=2000)

    assert store.turns_today(conn, url, day_start) == 2
    assert store.turns_today(conn, url, 1600) == 1
    assert store.turns_today(conn, url, 5000) == 0
