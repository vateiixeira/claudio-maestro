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


def add_session(conn, session_id: str, specialist_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at, specialist_id) VALUES (?, 1, '/tmp', 't', 0, 0, ?)",
        (session_id, specialist_id),
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
    assert loaded.autonomy == "ask"
    assert loaded.close_by_check is True
    assert loaded.run_text == "Execute a rotina agendada."
    assert loaded.enabled is True
    assert loaded.model is None and loaded.effort is None
    assert loaded.created_at == 100 and loaded.updated_at == 100
    assert store.list_specialists(conn) == [created]


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
    row = conn.execute("SELECT specialist_id FROM sessions WHERE session_id = 's1'").fetchone()
    assert row is not None and row["specialist_id"] is None
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
