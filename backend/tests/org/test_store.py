"""Org store: agents, routines, wakeup queue, runs and the tables copied from specialists."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.org import store


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


def add_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
        " last_activity_at) VALUES (?, 1, '/tmp', 't', 0, 0)",
        (session_id,),
    )


def make(conn, slug: str = "cto", project_id: int = 1, reports_to: int | None = None):
    return store.create_agent(
        conn, slug=slug, name=slug.upper(), project_id=project_id, reports_to=reports_to, now=100
    )


# Agents ----------------------------------------------------------------------------


def test_create_and_get_agent_round_trip(conn):
    created = make(conn)
    assert created == store.get_agent(conn, created.id)
    assert (created.slug, created.name, created.project_id) == ("cto", "CTO", 1)
    assert created.reports_to is None and created.enabled is True
    assert created.main_session_id is None and created.legacy is None
    assert store.get_agent_by_slug(conn, "cto") == created
    assert store.get_agent_by_slug(conn, "nada") is None


def test_get_agent_missing_raises(conn):
    with pytest.raises(store.NotFoundError, match="Agente não encontrado"):
        store.get_agent(conn, 99)


def test_create_agent_rejects_duplicate_slug(conn):
    make(conn)
    with pytest.raises(store.DuplicateSlugError, match="Já existe um agente com esse identificador"):
        make(conn, project_id=2)


def test_reports_to_must_be_same_project(conn):
    boss = make(conn, "cto", project_id=1)
    with pytest.raises(store.ReportsToOtherProjectError, match="mesmo projeto"):
        make(conn, "dev", project_id=2, reports_to=boss.id)
    other = make(conn, "ops", project_id=2)
    with pytest.raises(store.ReportsToOtherProjectError):
        store.update_agent(conn, other.id, reports_to=boss.id, now=200)


def test_reports_to_unknown_agent_is_not_found(conn):
    with pytest.raises(store.NotFoundError):
        make(conn, reports_to=99)


def test_reports_to_rejects_cycle(conn):
    a = make(conn, "a")
    b = make(conn, "b", reports_to=a.id)
    with pytest.raises(store.ReportsToCycleError, match="subordinado"):
        store.update_agent(conn, a.id, reports_to=b.id, now=200)
    with pytest.raises(store.ReportsToCycleError):
        store.update_agent(conn, a.id, reports_to=a.id, now=200)
    assert store.get_agent(conn, a.id).reports_to is None


def test_update_agent_changes_only_what_was_passed(conn):
    boss = make(conn, "boss")
    agent = make(conn, "dev", reports_to=boss.id)
    renamed = store.update_agent(conn, agent.id, name="Dev", now=300)
    assert (renamed.name, renamed.reports_to, renamed.updated_at) == ("Dev", boss.id, 300)
    off = store.update_agent(conn, agent.id, enabled=False, definition_hash="abc", now=400)
    assert off.enabled is False and off.definition_hash == "abc" and off.name == "Dev"
    top = store.update_agent(conn, agent.id, reports_to=None, now=500)
    assert top.reports_to is None


def test_update_missing_agent_raises(conn):
    with pytest.raises(store.NotFoundError):
        store.update_agent(conn, 99, name="x", now=1)


def test_set_main_session_and_clear_legacy(conn):
    agent = make(conn)
    add_session(conn, "s1")
    store.set_main_session(conn, agent.id, "s1")
    assert store.get_agent(conn, agent.id).main_session_id == "s1"
    store.set_main_session(conn, agent.id, None)
    assert store.get_agent(conn, agent.id).main_session_id is None
    with pytest.raises(store.NotFoundError):
        store.set_main_session(conn, 99, None)
    conn.execute("UPDATE agents SET legacy_json = '{\"model\": \"opus\"}'")
    assert store.get_agent(conn, agent.id).legacy == {"model": "opus"}
    store.clear_legacy(conn, agent.id)
    assert store.get_agent(conn, agent.id).legacy is None


def test_list_agents_filters_by_project(conn):
    a = make(conn, "a", project_id=1)
    b = make(conn, "b", project_id=2)
    assert [x.id for x in store.list_agents(conn)] == [a.id, b.id]
    assert [x.id for x in store.list_agents(conn, 2)] == [b.id]


def test_delete_agent_orphans_reports(conn):
    boss = make(conn, "boss")
    worker = make(conn, "worker", reports_to=boss.id)
    store.delete_agent(conn, boss.id)
    assert store.get_agent(conn, worker.id).reports_to is None
    with pytest.raises(store.NotFoundError):
        store.get_agent(conn, boss.id)
    with pytest.raises(store.NotFoundError):
        store.delete_agent(conn, boss.id)


def test_delete_agent_removes_its_data_and_keeps_sessions(conn):
    agent = make(conn)
    add_session(conn, "s1")
    routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="R", instruction="x", now=1
    )
    store.replace_schedules(conn, routine.id, [("12345", "09:00")], now=1)
    run = store.insert_run(
        conn, agent_id=agent.id, source="manual", started_at=1, outcome="running", session_id="s1"
    )
    store.enqueue_wakeup(conn, agent_id=agent.id, source="manual", payload=None, now=1)
    store.upsert_item(conn, agent.id, key="k", status="ok", link=None, note=None, now=1)
    store.add_notice(conn, agent_id=agent.id, run_id=run.id, kind="notice", text="t", now=1)
    conn.execute("UPDATE sessions SET agent_id = ? WHERE session_id = 's1'", (agent.id,))
    store.delete_agent(conn, agent.id)
    assert conn.execute("SELECT agent_id FROM sessions").fetchone()[0] is None
    for table in ("routines", "routine_schedules", "runs", "wakeups", "registry", "notices"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_subtree_returns_descendants(conn):
    root = make(conn, "root")
    a = make(conn, "a", reports_to=root.id)
    b = make(conn, "b", reports_to=root.id)
    a1 = make(conn, "a1", reports_to=a.id)
    other = make(conn, "other")
    assert store.subtree(conn, root.id) == [root.id, a.id, b.id, a1.id]
    assert store.subtree(conn, a.id) == [a.id, a1.id]
    assert store.subtree(conn, a1.id) == [a1.id]
    assert other.id not in store.subtree(conn, root.id)


def test_subtree_terminates_on_a_cycle_written_by_hand(conn):
    a = make(conn, "a")
    b = make(conn, "b", reports_to=a.id)
    conn.execute("UPDATE agents SET reports_to = ? WHERE id = ?", (b.id, a.id))  # A -> B -> A
    assert store.subtree(conn, a.id) == [a.id, b.id]
    assert store.subtree(conn, b.id) == [b.id, a.id]
    # Updating through the API still refuses to build on such a table without hanging.
    c = make(conn, "c")
    with pytest.raises(store.ReportsToCycleError):
        store.update_agent(conn, c.id, reports_to=c.id, now=1)


# Routines --------------------------------------------------------------------------


def test_routine_crud_and_limits(conn):
    agent = make(conn)
    routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="Sentry", instruction="Olhe o Sentry.", now=10
    )
    assert routine.enabled is True and routine.created_at == 10
    changed = store.update_routine(conn, routine.id, name="Sentry 2", enabled=False, now=20)
    assert (changed.name, changed.instruction, changed.enabled, changed.updated_at) == (
        "Sentry 2", "Olhe o Sentry.", False, 20,
    )
    with pytest.raises(store.OrgError, match="nome da rotina"):
        store.update_routine(conn, routine.id, name="", now=30)
    with pytest.raises(store.OrgError, match="instrução da rotina"):
        store.create_routine(
            conn, project_id=1, agent_id=agent.id, name="x", instruction="y" * 5001, now=30
        )
    other = make(conn, "other", project_id=2)
    theirs = store.create_routine(
        conn, project_id=2, agent_id=other.id, name="o", instruction="o", now=1
    )
    assert len(store.list_routines(conn)) == 2
    assert [r.id for r in store.list_routines(conn, project_id=1)] == [routine.id]
    assert [r.id for r in store.list_routines(conn, agent_id=other.id)] == [theirs.id]
    store.delete_routine(conn, routine.id)
    with pytest.raises(store.NotFoundError):
        store.get_routine(conn, routine.id)
    with pytest.raises(store.NotFoundError):
        store.delete_routine(conn, routine.id)


def test_replace_schedules_and_mark_fired(conn):
    agent = make(conn)
    routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="r", instruction="x", now=1
    )
    first = store.replace_schedules(conn, routine.id, [("12345", "09:00"), ("67", "10:30")], now=50)
    assert [(s.days, s.time, s.last_fired_at) for s in first] == [
        ("12345", "09:00", 50), ("67", "10:30", 50),
    ]
    second = store.replace_schedules(conn, routine.id, [("1", "08:00")], now=60)
    assert len(second) == 1 and len(store.list_schedules(conn)) == 1
    store.mark_fired(conn, second[0].id, 99)
    assert store.list_schedules(conn, routine.id)[0].last_fired_at == 99


# Wakeup queue ----------------------------------------------------------------------


def test_priority_order():
    ordered = sorted(store.PRIORITY, key=store.PRIORITY.__getitem__)
    assert ordered == ["manual", "message", "decision", "comment", "assignment", "routine"]


def test_enqueue_coalesces_same_routine(conn):
    agent = make(conn)
    routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="r", instruction="x", now=1
    )
    first = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=routine.id, now=10
    )
    again = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=routine.id, now=11
    )
    assert again.id == first.id
    assert len(store.pending_wakeups(conn, agent.id)) == 1
    # Another routine, another agent or no routine is a different wakeup.
    other_routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="r2", instruction="y", now=1
    )
    store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=other_routine.id, now=12
    )
    store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=None, now=12
    )
    other = make(conn, "other")
    store.enqueue_wakeup(
        conn, agent_id=other.id, source="routine", payload=None, routine_id=routine.id, now=12
    )
    assert len(store.pending_wakeups(conn)) == 4
    # Once taken, a new one of the same routine queues again.
    store.take_wakeup(conn, first.id, None, now=13)
    fresh = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=routine.id, now=14
    )
    assert fresh.id != first.id


@pytest.mark.parametrize("source", ["manual", "message", "assignment", "comment", "decision"])
def test_enqueue_does_not_coalesce_other_sources(conn, source):
    agent = make(conn)
    first = store.enqueue_wakeup(
        conn, agent_id=agent.id, source=source, payload={"n": 1}, now=1
    )
    second = store.enqueue_wakeup(
        conn, agent_id=agent.id, source=source, payload={"n": 2}, now=2
    )
    assert first.id != second.id
    assert [w.payload for w in store.pending_wakeups(conn, agent.id)] == [{"n": 1}, {"n": 2}]


def test_enqueue_stores_payload_as_json_and_limits_size(conn):
    agent = make(conn)
    wake = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="comment", payload={"session_id": "s", "n": [1]}, now=1
    )
    assert store.next_wakeup(conn, agent.id).payload == {"session_id": "s", "n": [1]}
    assert wake.priority == store.PRIORITY["comment"] and wake.state == "pending"
    with pytest.raises(store.OrgError, match="despertar"):
        store.enqueue_wakeup(
            conn, agent_id=agent.id, source="message", payload={"text": "x" * 20001}, now=2
        )


def test_next_wakeup_prefers_manual_over_routine(conn):
    agent = make(conn)
    assert store.next_wakeup(conn, agent.id) is None
    routine = store.enqueue_wakeup(conn, agent_id=agent.id, source="routine", payload=None, now=1)
    assignment = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="assignment", payload=None, now=2
    )
    manual = store.enqueue_wakeup(conn, agent_id=agent.id, source="manual", payload=None, now=3)
    assert store.next_wakeup(conn, agent.id).id == manual.id
    assert [w.id for w in store.pending_wakeups(conn, agent.id)] == [
        manual.id, assignment.id, routine.id,
    ]
    store.drop_wakeup(conn, manual.id, now=4)
    assert store.next_wakeup(conn, agent.id).id == assignment.id


def test_next_wakeup_breaks_ties_by_age(conn):
    agent = make(conn)
    routine = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="r", instruction="x", now=1
    )
    first = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=None, now=1
    )
    store.enqueue_wakeup(
        conn, agent_id=agent.id, source="routine", payload=None, routine_id=routine.id, now=2
    )
    assert store.next_wakeup(conn, agent.id).id == first.id


def test_take_and_drop_only_act_on_pending(conn):
    agent = make(conn)
    run = store.insert_run(conn, agent_id=agent.id, source="manual", started_at=1, outcome="starting")
    wake = store.enqueue_wakeup(conn, agent_id=agent.id, source="manual", payload=None, now=1)
    assert store.take_wakeup(conn, wake.id, run.id, now=5) is True
    assert store.take_wakeup(conn, wake.id, run.id, now=6) is False
    assert store.drop_wakeup(conn, wake.id, now=7) is False
    row = conn.execute("SELECT state, run_id, taken_at FROM wakeups WHERE id = ?", (wake.id,)).fetchone()
    assert (row["state"], row["run_id"], row["taken_at"]) == ("taken", run.id, 5)
    assert store.next_wakeup(conn, agent.id) is None
    gone = store.enqueue_wakeup(conn, agent_id=agent.id, source="routine", payload=None, now=8)
    assert store.drop_wakeup(conn, gone.id, now=9) is True
    assert store.pending_wakeups(conn) == []


# Runs ------------------------------------------------------------------------------


def test_active_run_only_counts_open_outcomes(conn):
    agent = make(conn)
    for outcome in ("concluded", "closed", "failed", "skipped", "missed", "cancelled"):
        store.insert_run(
            conn, agent_id=agent.id, source="manual", started_at=1, outcome=outcome, ended_at=2
        )
    assert store.active_run(conn, agent.id) is None
    for outcome in ("starting", "running", "waiting"):
        run = store.insert_run(conn, agent_id=agent.id, source="manual", started_at=5, outcome="running")
        store.update_run(conn, run.id, outcome=outcome)
        assert store.active_run(conn, agent.id).id == run.id
        store.update_run(conn, run.id, outcome="concluded", ended_at=9)
        assert store.active_run(conn, agent.id) is None


def test_run_for_session_returns_latest(conn):
    agent = make(conn)
    add_session(conn, "s1")
    assert store.run_for_session(conn, "s1") is None
    first = store.insert_run(
        conn, agent_id=agent.id, source="routine", started_at=1, outcome="concluded",
        session_id="s1", ended_at=2,
    )
    assert store.run_for_session(conn, "s1") == first
    # A session may serve several runs (a comment on the PR session, a task resumed).
    second = store.insert_run(
        conn, agent_id=agent.id, source="comment", started_at=5, outcome="running", session_id="s1"
    )
    tie = store.insert_run(
        conn, agent_id=agent.id, source="comment", started_at=5, outcome="running", session_id="s1"
    )
    assert store.run_for_session(conn, "s1") == tie and tie.id > second.id
    assert store.run_for_session(conn, "nope") is None
    store.insert_run(conn, agent_id=agent.id, source="manual", started_at=3, outcome="skipped")
    store.insert_run(conn, agent_id=agent.id, source="manual", started_at=4, outcome="skipped")


def test_update_run_sets_and_clears_fields(conn):
    agent = make(conn)
    add_session(conn, "s1")
    run = store.insert_run(
        conn, agent_id=agent.id, source="routine", started_at=1, outcome="starting"
    )
    updated = store.update_run(conn, run.id, session_id="s1", outcome="running", reason="ok")
    assert (updated.session_id, updated.outcome, updated.reason) == ("s1", "running", "ok")
    cleared = store.update_run(conn, run.id, reason=None, session_id=None)
    assert cleared.reason is None and cleared.session_id is None and cleared.outcome == "running"
    assert store.update_run(conn, run.id) == cleared
    with pytest.raises(store.NotFoundError):
        store.update_run(conn, 99, outcome="failed")
    with pytest.raises(store.NotFoundError):
        store.get_run(conn, 99)


def test_list_runs_and_last_runs(conn):
    agent = make(conn)
    for i, outcome in enumerate(("concluded", "running", "missed", "failed", "skipped"), start=1):
        store.insert_run(
            conn, agent_id=agent.id, source="routine", started_at=i * 10, outcome=outcome
        )
    other = make(conn, "other")
    store.insert_run(conn, agent_id=other.id, source="manual", started_at=99, outcome="failed")
    assert [r.started_at for r in store.list_runs(conn, agent.id)] == [50, 40, 30, 20, 10]
    assert [r.started_at for r in store.list_runs(conn, agent.id, limit=2)] == [50, 40]
    counted = store.last_runs(conn, agent.id, 2)
    assert [r.outcome for r in counted] == ["skipped", "failed"]


def test_run_check_rejects_unknown_outcome_and_source(conn):
    agent = make(conn)
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_run(conn, agent_id=agent.id, source="manual", started_at=1, outcome="queued")  # type: ignore[arg-type]
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_run(conn, agent_id=agent.id, source="schedule", started_at=1, outcome="running")  # type: ignore[arg-type]


# Registry, notices, announcements, PRs and chats ---------------------------------------


def test_registry_upsert_list_delete(conn):
    agent = make(conn)
    first = store.upsert_item(conn, agent.id, key="SENTRY-1", status="ignored", link=None, note="n", now=1)
    again = store.upsert_item(conn, agent.id, key="SENTRY-1", status="handled", link="u", note=None, now=5)
    assert (again.status, again.link, again.created_at, again.updated_at) == ("handled", "u", 1, 5)
    assert first.created_at == 1
    store.upsert_item(conn, agent.id, key="A", status="ok", link=None, note=None, now=2)
    assert [i.key for i in store.list_items(conn, agent.id)] == ["A", "SENTRY-1"]
    assert [i.key for i in store.get_items(conn, agent.id, ["A", "Z"])] == ["A"]
    assert store.get_items(conn, agent.id, []) == []
    store.delete_item(conn, agent.id, "A")
    assert [i.key for i in store.list_items(conn, agent.id)] == ["SENTRY-1"]


def test_notices_read_flow(conn):
    agent = make(conn)
    run = store.insert_run(conn, agent_id=agent.id, source="manual", started_at=1, outcome="concluded")
    n1 = store.add_notice(conn, agent_id=agent.id, run_id=run.id, kind="summary", text="a", now=1)
    n2 = store.add_notice(conn, agent_id=agent.id, run_id=None, kind="alert", text="b", now=2)
    assert n1.run_id == run.id and n2.run_id is None
    assert [n.id for n in store.list_notices(conn)] == [n2.id, n1.id]
    assert store.mark_notices_read(conn, [n1.id, 999], now=5) == 1
    assert store.mark_notices_read(conn, [n1.id], now=6) == 0
    assert store.mark_notices_read(conn, [], now=6) == 0
    assert [n.id for n in store.list_notices(conn, unread_only=True)] == [n2.id]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE notices SET kind = 'x' WHERE id = ?", (n1.id,))


def test_notice_survives_run_removal(conn):
    agent = make(conn)
    run = store.insert_run(conn, agent_id=agent.id, source="manual", started_at=1, outcome="concluded")
    notice = store.add_notice(conn, agent_id=agent.id, run_id=run.id, kind="notice", text="a", now=1)
    conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))
    assert store.list_notices(conn)[0].id == notice.id
    assert store.list_notices(conn)[0].run_id is None


def test_announcements_flow(conn):
    agent = make(conn)
    run = store.insert_run(conn, agent_id=agent.id, source="routine", started_at=1, outcome="concluded")
    first = store.add_announcement(conn, agent_id=agent.id, run_id=run.id, session_id=None, text="a", created_at=1)
    second = store.add_announcement(conn, agent_id=agent.id, run_id=None, session_id=None, text="b", created_at=2)
    assert [a.id for a in store.pending_announcements(conn, agent.id)] == [first.id, second.id]
    assert store.announcement_for_run(conn, run.id) == first
    assert store.announcement_for_run(conn, 999) is None
    edited = store.update_announcement_text(conn, first.id, "novo")
    assert edited.text == "novo"
    store.mark_announcements_delivered(conn, [first.id], at=9)
    assert [a.id for a in store.pending_announcements(conn, agent.id)] == [second.id]
    assert [a.id for a in store.list_announcements(conn, agent.id)] == [second.id, first.id]
    store.mark_announcements_delivered(conn, [], at=9)


def test_prs_and_comments(conn):
    agent = make(conn)
    add_session(conn, "s1")
    store.upsert_pr(conn, url="https://github.com/o/r/pull/1/", agent_id=agent.id, session_id="s1", created_at=1)
    store.upsert_pr(conn, url="https://github.com/o/r/pull/1?x=1", agent_id=agent.id, session_id=None, created_at=2)
    pr = store.get_pr(conn, "https://github.com/o/r/pull/1#frag")
    assert pr is not None and pr.session_id == "s1" and pr.closed is False
    assert store.get_pr(conn, "https://github.com/o/r/pull/2") is None
    store.mark_pr_polled(conn, pr.url, 7)
    assert store.get_pr(conn, pr.url).polled_at == 7
    assert [p.url for p in store.open_prs(conn)] == [pr.url]

    def comment(cid: str, created: int) -> store.PrComment:
        return store.PrComment(
            comment_id=cid, pr_url=pr.url, agent_id=agent.id, author="vi", body="b", path=None,
            line=None, html_url="u", created_at=created, received_at=created, status="queued",
            batch_at=None,
        )

    assert store.insert_comment(conn, comment("issue:2", 20)) is True
    assert store.insert_comment(conn, comment("issue:1", 10)) is True
    assert store.insert_comment(conn, comment("issue:1", 10)) is False
    assert [c.comment_id for c in store.queued_comments(conn)] == ["issue:1", "issue:2"]
    store.mark_comments(conn, ["issue:1"], "dispatching", 100)
    store.mark_comments(conn, [], "delivered", 100)
    assert [c.comment_id for c in store.queued_comments(conn)] == ["issue:2"]
    assert store.turns_today(conn, pr.url, 50) == 1
    assert store.turns_today(conn, pr.url, 150) == 0
    store.close_pr(conn, pr.url)
    assert store.open_prs(conn) == []


def test_chats(conn):
    agent = make(conn)
    add_session(conn, "s1")
    add_session(conn, "s2")
    store.add_chat(conn, "s1", agent.id)
    store.add_chat(conn, "s1", agent.id)
    store.add_chat(conn, "s2", agent.id)
    assert store.get_chat(conn, "s1") == store.Chat(session_id="s1", agent_id=agent.id)
    assert store.get_chat(conn, "x") is None
    assert [c.session_id for c in store.list_chats(conn, agent.id)] == ["s1", "s2"]
