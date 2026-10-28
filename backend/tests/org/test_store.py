"""Org store: agents, routines, wakeup queue, runs and the tables copied from the old agents."""

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
    # Sends that did not leave count as turns too; only the first of a sequence is "new".
    assert store.comments_down(conn, pr.url, 120) is False
    assert store.note_comment_send_failed(conn, pr.url, 7, 120) is False
    assert store.note_comment_send_failed(conn, pr.url, 8, 130) is True
    assert store.turns_today(conn, pr.url, 50) == 3
    assert store.turns_today(conn, pr.url, 125) == 1
    assert store.turns_today(conn, pr.url + "/other", 50) == 0
    assert store.comments_down(conn, pr.url, 130 + store.COMMENT_DOWN_SECONDS - 1) is True
    # A mark left behind does not hide a failure of another day.
    assert store.comments_down(conn, pr.url, 130 + store.COMMENT_DOWN_SECONDS) is False
    assert store.note_comment_send_failed(conn, pr.url, 9, 130 + store.COMMENT_DOWN_SECONDS) is False
    assert store.set_comments_down(conn, pr.url, False, 140) is True
    assert store.comments_down(conn, pr.url, 140) is False
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


# Tasks -----------------------------------------------------------------------------


def make_task(conn, title: str = "Tarefa", project_id: int = 1, **kwargs):
    return store.create_task(conn, project_id=project_id, title=title, now=100, **kwargs)


def test_create_task_defaults(conn):
    task = make_task(conn)

    assert task == store.get_task(conn, task.id)
    assert (task.title, task.description, task.status, task.priority) == ("Tarefa", "", "todo", "normal")
    assert (task.assignee_agent_id, task.reviewer_agent_id, task.parent_task_id) == (None, None, None)
    assert (task.created_by, task.created_by_agent_id, task.routine_id) == ("human", None, None)
    assert (task.revision, task.run_count, task.max_runs) == (1, 0, store.DEFAULT_MAX_RUNS)
    assert (task.worktree_path, task.branch, task.blocked_reason, task.legacy) == (None, None, None, None)
    assert (task.created_at, task.updated_at, task.closed_at) == (100, 100, None)
    assert store.DEFAULT_MAX_RUNS == 20
    assert store.TASK_STATUSES == ("todo", "in_progress", "in_review", "blocked", "done", "cancelled")
    assert store.TASK_PRIORITIES == ("urgent", "high", "normal", "low")


def test_create_task_with_people_and_parent(conn):
    boss, worker = make(conn, "boss"), make(conn, "worker", reports_to=None)
    parent = make_task(conn, "Mãe")

    child = make_task(
        conn, "Filha", description="texto", assignee_agent_id=worker.id, reviewer_agent_id=boss.id,
        parent_task_id=parent.id, priority="urgent", created_by="agent", created_by_agent_id=boss.id,
    )

    assert (child.assignee_agent_id, child.reviewer_agent_id, child.parent_task_id) == (worker.id, boss.id, parent.id)
    assert (child.priority, child.created_by, child.created_by_agent_id) == ("urgent", "agent", boss.id)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"title": ""}, "título"),
        ({"title": "x" * 161}, "título"),
        ({"description": "x" * 20001}, "descrição"),
        ({"priority": "meh"}, "(?i)prioridade"),
        ({"created_by": "robot"}, "(?i)autor"),
        ({"parent_task_id": 999}, "tarefa-mãe"),
    ],
)
def test_create_task_validates_fields(conn, kwargs, message):
    with pytest.raises(store.TaskValidationError, match=message):
        make_task(conn, **{"title": "ok", **kwargs})


def test_create_task_rejects_parent_of_another_project(conn):
    other = make_task(conn, "Outra", project_id=2)
    with pytest.raises(store.TaskValidationError, match="mesmo projeto"):
        make_task(conn, "Filha", parent_task_id=other.id)


def test_get_task_missing_raises(conn):
    with pytest.raises(store.TaskNotFoundError, match="Tarefa não encontrada."):
        store.get_task(conn, 99)
    assert issubclass(store.TaskNotFoundError, store.NotFoundError)


def test_update_task_checks_revision(conn):
    task = make_task(conn)

    updated = store.update_task(conn, task.id, expected_revision=1, now=150, title="Novo", status="in_progress")

    assert (updated.title, updated.status, updated.revision, updated.updated_at) == ("Novo", "in_progress", 2, 150)
    with pytest.raises(store.TaskRevisionError, match="A tarefa mudou; recarregue e tente de novo."):
        store.update_task(conn, task.id, expected_revision=1, now=160, title="Velho")
    assert store.get_task(conn, task.id).title == "Novo"
    with pytest.raises(store.TaskNotFoundError):
        store.update_task(conn, 99, expected_revision=1, now=160, title="x")


def test_update_task_clears_with_none_and_rejects_unknown(conn):
    worker = make(conn, "worker")
    task = make_task(conn, assignee_agent_id=worker.id)

    updated = store.update_task(conn, task.id, expected_revision=1, now=110, assignee_agent_id=None)

    assert updated.assignee_agent_id is None
    with pytest.raises(ValueError, match="id"):
        store.update_task(conn, task.id, expected_revision=2, now=120, id=5)


def test_update_task_validates_fields(conn):
    task = make_task(conn)
    for fields, message in (
        ({"title": ""}, "título"), ({"status": "backlog"}, "(?i)estado"), ({"priority": "x"}, "(?i)prioridade"),
        ({"description": "x" * 20001}, "descrição"), ({"parent_task_id": task.id}, "tarefa-mãe"),
    ):
        with pytest.raises(store.TaskValidationError, match=message):
            store.update_task(conn, task.id, expected_revision=1, now=110, **fields)
    assert store.get_task(conn, task.id).revision == 1


def test_update_task_refuses_a_parent_cycle(conn):
    top = make_task(conn, "Topo")
    middle = make_task(conn, "Meio", parent_task_id=top.id)
    with pytest.raises(store.TaskValidationError, match="tarefa-mãe"):
        store.update_task(conn, top.id, expected_revision=1, now=110, parent_task_id=middle.id)


def test_update_task_sets_closed_at_on_done(conn):
    task = make_task(conn)

    done = store.update_task(conn, task.id, expected_revision=1, now=200, status="done")
    assert (done.status, done.closed_at) == ("done", 200)
    # Staying closed keeps the first closing time; reopening clears it.
    same = store.update_task(conn, task.id, expected_revision=2, now=210, status="cancelled")
    assert same.closed_at == 200
    reopened = store.update_task(conn, task.id, expected_revision=3, now=220, status="todo")
    assert (reopened.status, reopened.closed_at) == ("todo", None)
    cancelled = store.update_task(conn, task.id, expected_revision=4, now=230, status="cancelled")
    assert cancelled.closed_at == 230


def test_list_tasks_filters_by_assignee_and_status(conn):
    a, b = make(conn, "a"), make(conn, "b")
    t1 = make_task(conn, "t1", assignee_agent_id=a.id)
    t2 = make_task(conn, "t2", assignee_agent_id=a.id)
    t3 = make_task(conn, "t3", assignee_agent_id=b.id)
    t4 = make_task(conn, "t4", project_id=2)
    store.update_task(conn, t2.id, expected_revision=1, now=110, status="in_progress")
    store.update_task(conn, t3.id, expected_revision=1, now=110, status="done")

    def ids(**kw):
        return [task.id for task in store.list_tasks(conn, **kw)]

    assert ids() == [t1.id, t2.id, t3.id, t4.id]
    assert ids(project_id=1) == [t1.id, t2.id, t3.id]
    assert ids(assignee_agent_id=a.id) == [t1.id, t2.id]
    assert ids(assignee_agent_id=a.id, statuses=["in_progress"]) == [t2.id]
    assert ids(statuses=["todo", "done"]) == [t1.id, t3.id, t4.id]
    assert ids(statuses=[]) == []
    assert ids(limit=2) == [t1.id, t2.id]
    assert ids(limit=2, offset=2) == [t3.id, t4.id]


def test_list_tasks_order_recent_puts_the_newest_change_first(conn):
    t1, t2, t3, t4 = (make_task(conn, name) for name in ("t1", "t2", "t3", "t4"))
    store.update_task(conn, t2.id, expected_revision=1, now=110, status="in_progress")
    store.update_task(conn, t3.id, expected_revision=1, now=110, status="in_progress")

    def ids(**kw):
        return [task.id for task in store.list_tasks(conn, **kw)]

    assert ids() == [t1.id, t2.id, t3.id, t4.id]
    assert ids(order="id") == [t1.id, t2.id, t3.id, t4.id]
    # Same `updated_at`: the higher id first.
    assert ids(order="recent") == [t3.id, t2.id, t4.id, t1.id]
    assert ids(order="recent", limit=2) == [t3.id, t2.id]
    assert ids(order="recent", statuses=["in_progress"], limit=1) == [t3.id]


def test_count_open_children(conn):
    parent = make_task(conn, "Mãe")
    c1 = make_task(conn, "c1", parent_task_id=parent.id)
    c2 = make_task(conn, "c2", parent_task_id=parent.id)
    make_task(conn, "c3", parent_task_id=parent.id)
    assert store.count_open_children(conn, parent.id) == 3
    store.update_task(conn, c1.id, expected_revision=1, now=110, status="done")
    store.update_task(conn, c2.id, expected_revision=1, now=110, status="cancelled")
    assert store.count_open_children(conn, parent.id) == 1
    assert store.count_open_children(conn, c1.id) == 0


def test_deleting_the_parent_task_keeps_the_children(conn):
    parent = make_task(conn, "Mãe")
    child = make_task(conn, "Filha", parent_task_id=parent.id)
    conn.execute("DELETE FROM tasks WHERE id = ?", (parent.id,))
    assert store.get_task(conn, child.id).parent_task_id is None


# Comments --------------------------------------------------------------------------


def make_run(conn, agent, task_id=None, outcome="running", started_at=100, **kwargs):
    return store.insert_run(
        conn, agent_id=agent.id, source="assignment", started_at=started_at, outcome=outcome,
        task_id=task_id, **kwargs,
    )


def test_add_comment_and_list(conn):
    agent = make(conn)
    task = make_task(conn)

    first = store.add_comment(
        conn, task_id=task.id, author_kind="human", author_agent_id=None, run_id=None, text="Oi", now=110
    )
    second = store.add_comment(
        conn, task_id=task.id, author_kind="agent", author_agent_id=agent.id, run_id=None, text="Olá", now=120
    )

    assert (first.task_id, first.author_kind, first.author_agent_id, first.run_id) == (task.id, "human", None, None)
    assert (first.text, first.created_at) == ("Oi", 110)
    assert second.id > first.id
    assert store.list_comments(conn, task.id) == [first, second]
    assert store.list_comments(conn, task.id, after_id=first.id) == [second]
    assert store.list_comments(conn, task.id, limit=1) == [first]
    assert store.list_comments(conn, task.id, limit=1, latest=True) == [second]
    assert store.last_comment_id(conn, task.id) == second.id


def test_last_comment_id_is_zero_without_comments(conn):
    assert store.last_comment_id(conn, make_task(conn).id) == 0


def test_add_comment_validates(conn):
    task = make_task(conn)
    for text in ("", "x" * 20001):
        with pytest.raises(store.TaskValidationError, match="comentário"):
            store.add_comment(conn, task_id=task.id, author_kind="human", author_agent_id=None, run_id=None, text=text, now=1)
    with pytest.raises(store.TaskValidationError, match="(?i)autor"):
        store.add_comment(conn, task_id=task.id, author_kind="robot", author_agent_id=None, run_id=None, text="x", now=1)
    with pytest.raises(store.TaskNotFoundError):
        store.add_comment(conn, task_id=99, author_kind="human", author_agent_id=None, run_id=None, text="x", now=1)


def test_add_comment_marks_run_commented_when_run_given(conn):
    agent = make(conn)
    task = make_task(conn)
    run = make_run(conn, agent, task.id)
    other = make_run(conn, agent, task.id, started_at=101)
    assert (run.commented, run.rewoken, run.task_id) == (False, False, task.id)

    comment = store.add_comment(
        conn, task_id=task.id, author_kind="agent", author_agent_id=agent.id, run_id=run.id, text="Feito", now=120
    )

    assert comment.run_id == run.id
    assert store.get_run(conn, run.id).commented is True
    assert store.get_run(conn, other.id).commented is False
    # A comment without a run (a human's) marks nothing.
    store.add_comment(conn, task_id=task.id, author_kind="human", author_agent_id=None, run_id=None, text="Ok", now=130)
    assert store.get_run(conn, other.id).commented is False


def test_mark_run_commented_and_rewoken(conn):
    agent = make(conn)
    run = make_run(conn, agent)
    store.mark_run_commented(conn, run.id)
    store.mark_run_rewoken(conn, run.id)
    done = store.get_run(conn, run.id)
    assert (done.commented, done.rewoken) == (True, True)


def test_deleting_a_task_deletes_its_comments(conn):
    task = make_task(conn)
    store.add_comment(conn, task_id=task.id, author_kind="app", author_agent_id=None, run_id=None, text="x", now=1)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
    assert conn.execute("SELECT COUNT(*) FROM task_comments").fetchone()[0] == 0


# Task sessions ----------------------------------------------------------------------


def test_task_session_roundtrip(conn):
    agent = make(conn)
    task = make_task(conn)
    add_session(conn, "s1")
    add_session(conn, "s2")
    assert store.get_task_session(conn, agent.id, task.id) is None

    store.set_task_session(conn, agent.id, task.id, session_id="s1", cwd="/tmp/p1", now=100)
    first = store.get_task_session(conn, agent.id, task.id)
    assert first == store.TaskSession(agent_id=agent.id, task_id=task.id, session_id="s1", cwd="/tmp/p1", created_at=100)

    store.set_task_session(conn, agent.id, task.id, session_id="s2", cwd="/tmp/p1/wt", now=200)
    second = store.get_task_session(conn, agent.id, task.id)
    assert (second.session_id, second.cwd, second.created_at) == ("s2", "/tmp/p1/wt", 200)

    store.clear_task_session(conn, agent.id, task.id)
    assert store.get_task_session(conn, agent.id, task.id) is None
    store.clear_task_session(conn, agent.id, task.id)  # nothing there: no error


def test_task_session_survives_without_session_row(conn):
    agent = make(conn)
    task = make_task(conn)
    add_session(conn, "s1")
    store.set_task_session(conn, agent.id, task.id, session_id="s1", cwd="/tmp/p1", now=100)
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    found = store.get_task_session(conn, agent.id, task.id)
    assert found is not None and found.session_id is None


# Runs of tasks ---------------------------------------------------------------------


def test_active_run_for_task(conn):
    agent, other = make(conn, "a"), make(conn, "b")
    task = make_task(conn)
    elsewhere = make_task(conn, "outra")
    assert store.active_run_for_task(conn, task.id) is None
    make_run(conn, agent, task.id, outcome="concluded", started_at=100)
    make_run(conn, other, elsewhere.id, outcome="running", started_at=101)
    assert store.active_run_for_task(conn, task.id) is None

    older = make_run(conn, agent, task.id, outcome="waiting", started_at=110)
    newer = make_run(conn, other, task.id, outcome="starting", started_at=120)

    assert store.active_run_for_task(conn, task.id) == newer
    store.update_run(conn, newer.id, outcome="failed")
    assert store.active_run_for_task(conn, task.id) == older


def test_list_task_runs_and_prs(conn):
    agent = make(conn)
    task = store.create_task(conn, project_id=1, title="t", now=100)
    other = store.create_task(conn, project_id=1, title="o", now=100)
    first = store.insert_run(
        conn, agent_id=agent.id, source="assignment", started_at=1, outcome="concluded",
        task_id=task.id,
    )
    store.insert_run(
        conn, agent_id=agent.id, source="assignment", started_at=2, outcome="running",
        task_id=other.id,
    )
    second = store.insert_run(
        conn, agent_id=agent.id, source="comment", started_at=3, outcome="running",
        task_id=task.id,
    )
    for url, task_id in (("https://github.com/o/r/pull/1", task.id),
                         ("https://github.com/o/r/pull/2", other.id)):
        store.upsert_pr(conn, url=url, agent_id=agent.id, session_id=None, created_at=5)
        conn.execute("UPDATE agent_prs SET task_id = ? WHERE url = ?", (task_id, url))

    assert [run.id for run in store.list_task_runs(conn, task.id)] == [first.id, second.id]
    assert [pr.url for pr in store.list_task_prs(conn, task.id)] == [
        "https://github.com/o/r/pull/1"
    ]
    assert store.list_task_runs(conn, 999) == [] and store.list_task_prs(conn, 999) == []


def test_bump_run_count(conn):
    task = make_task(conn)
    assert store.bump_run_count(conn, task.id, now=110) == 1
    assert store.bump_run_count(conn, task.id, now=120) == 2
    fresh = store.get_task(conn, task.id)
    assert (fresh.run_count, fresh.updated_at, fresh.revision) == (2, 120, 1)
    with pytest.raises(store.TaskNotFoundError):
        store.bump_run_count(conn, 99, now=1)


def test_enqueue_wakeup_and_insert_run_carry_task_id(conn):
    agent = make(conn)
    task = make_task(conn)

    wakeup = store.enqueue_wakeup(
        conn, agent_id=agent.id, source="assignment", payload={"task_id": task.id}, task_id=task.id, now=100
    )
    plain = store.enqueue_wakeup(conn, agent_id=agent.id, source="manual", payload=None, now=101)
    run = make_run(conn, agent, task.id)

    assert wakeup.task_id == task.id and plain.task_id is None
    assert store.next_wakeup(conn, agent.id).task_id is None  # manual outranks assignment
    assert store.pending_wakeups(conn)[1].task_id == task.id
    assert store.get_run(conn, run.id).task_id == task.id
    assert store.list_runs(conn, agent.id)[0].task_id == task.id
    conn.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
    assert store.get_run(conn, run.id).task_id is None
    assert store.pending_wakeups(conn)[1].task_id is None


def test_routine_has_create_task_flag(conn):
    agent = make(conn)
    plain = store.create_routine(conn, project_id=1, agent_id=agent.id, name="r", instruction="i", now=100)
    flagged = store.create_routine(
        conn, project_id=1, agent_id=agent.id, name="r2", instruction="i", create_task=True, now=100
    )
    assert plain.create_task is False and flagged.create_task is True
    assert store.update_routine(conn, plain.id, now=110, create_task=True).create_task is True
    assert store.update_routine(conn, plain.id, now=120, name="novo").create_task is True
    assert store.update_routine(conn, flagged.id, now=130, create_task=False).create_task is False


# Decisions -------------------------------------------------------------------------


def make_decision(conn, agent, task=None, **kwargs):
    return store.create_decision(
        conn, project_id=1, task_id=task.id if task else None, agent_id=agent.id, run_id=None,
        question="Qual caminho?", options=["A", "B"], now=100, **kwargs,
    )


def test_create_decision_and_list(conn):
    agent = make(conn)
    task = make_task(conn)
    add_session(conn, "s1")
    run = make_run(conn, agent, task.id)

    decision = store.create_decision(
        conn, project_id=1, task_id=task.id, agent_id=agent.id, run_id=run.id, session_id="s1",
        question="Qual caminho?", options=["A", "B"], now=100,
    )

    assert decision == store.get_decision(conn, decision.id)
    assert (decision.status, decision.answer, decision.receipt, decision.answered_at) == ("pending", None, None, None)
    assert (decision.options, decision.session_id, decision.run_id, decision.task_id) == (["A", "B"], "s1", run.id, task.id)
    free = make_decision(conn, agent)
    assert free.session_id is None and free.task_id is None
    assert [d.id for d in store.list_decisions(conn)] == [decision.id, free.id]
    assert [d.id for d in store.list_decisions(conn, task_id=task.id)] == [decision.id]
    assert [d.id for d in store.list_decisions(conn, project_id=2)] == []
    with pytest.raises(store.NotFoundError, match="Decisão não encontrada"):
        store.get_decision(conn, 99)


def test_create_decision_validates(conn):
    agent = make(conn)

    def create(**kw):
        return store.create_decision(
            conn, project_id=1, task_id=None, agent_id=agent.id, run_id=None,
            **{"question": "Q?", "options": [], "now": 1, **kw},
        )

    for question in ("", "x" * 2001):
        with pytest.raises(store.OrgError, match="pergunta"):
            create(question=question)
    with pytest.raises(store.OrgError, match="opções"):
        create(options=[str(i) for i in range(9)])
    with pytest.raises(store.OrgError, match="opção"):
        create(options=["x" * 201])
    with pytest.raises(store.OrgError, match="opção"):
        create(options=[""])
    assert create(options=[str(i) for i in range(8)]).options == [str(i) for i in range(8)]
    assert create(options=["x" * 200]).options == ["x" * 200]


def test_decision_answer_sets_receipt_once(conn):
    agent = make(conn)
    decision = make_decision(conn, agent)

    answered = store.answer_decision(conn, decision.id, answer="A", receipt="rec-1", now=200)

    assert (answered.status, answered.answer, answered.receipt, answered.answered_at) == ("answered", "A", "rec-1", 200)
    with pytest.raises(store.OrgError, match="já foi respondida"):
        store.answer_decision(conn, decision.id, answer="B", receipt="rec-2", now=210)
    assert store.get_decision(conn, decision.id).receipt == "rec-1"
    other = make_decision(conn, agent)
    with pytest.raises(store.OrgError, match="recibo"):
        store.answer_decision(conn, other.id, answer="A", receipt="rec-1", now=220)
    assert store.get_decision(conn, other.id).status == "pending"
    with pytest.raises(store.NotFoundError):
        store.answer_decision(conn, 99, answer="A", receipt="x", now=1)
    assert [d.id for d in store.list_decisions(conn)] == [other.id]
    assert [d.id for d in store.list_decisions(conn, pending_only=False)] == [decision.id, other.id]


def test_expire_decision(conn):
    agent = make(conn)
    decision = make_decision(conn, agent)

    assert store.expire_decision(conn, decision.id) is True
    assert store.get_decision(conn, decision.id).status == "expired"
    assert store.expire_decision(conn, decision.id) is False
    assert store.list_decisions(conn) == []
    with pytest.raises(store.OrgError, match="já foi respondida"):
        store.answer_decision(conn, decision.id, answer="A", receipt="r", now=1)


def test_deleting_a_task_keeps_its_decisions(conn):
    agent = make(conn)
    task = make_task(conn)
    decision = make_decision(conn, agent, task)
    conn.execute("DELETE FROM tasks WHERE id = ?", (task.id,))
    assert store.get_decision(conn, decision.id).task_id is None


# CI receipts -----------------------------------------------------------------------


def test_ci_receipts_roundtrip(conn):
    agent = make(conn)
    task = make_task(conn)
    run = make_run(conn, agent, task.id)

    receipt = store.add_ci_receipt(
        conn, project_id=1, task_id=task.id, agent_id=agent.id, run_id=run.id,
        run_url="https://github.com/o/r/actions/runs/1", repository="o/r", head_sha="abc",
        conclusion="success", jobs=[{"name": "test", "conclusion": "success"}], receipt="ci-1", now=300,
    )

    assert receipt.jobs == [{"name": "test", "conclusion": "success"}]
    assert (receipt.task_id, receipt.agent_id, receipt.run_id, receipt.created_at) == (task.id, agent.id, run.id, 300)
    assert store.list_ci_receipts(conn, task.id) == [receipt]
    assert store.list_ci_receipts(conn, make_task(conn, "outra").id) == []
    with pytest.raises(store.OrgError, match="recibo"):
        store.add_ci_receipt(
            conn, project_id=1, task_id=task.id, agent_id=agent.id, run_id=None, run_url=None,
            repository=None, head_sha=None, conclusion=None, jobs=None, receipt="ci-1", now=301,
        )
    empty = store.add_ci_receipt(
        conn, project_id=1, task_id=task.id, agent_id=None, run_id=None, run_url=None, repository=None,
        head_sha=None, conclusion=None, jobs=None, receipt="ci-2", now=302,
    )
    assert empty.jobs is None


# Legacy work (handed from migration 33 to the file migration) -----------------------


def test_legacy_work_list_and_delete(conn):
    for kind, task_id in (("coordinator", None), ("decision", 5), ("pr", 6)):
        conn.execute(
            "INSERT INTO org_legacy_work (kind, project_id, task_id, data) VALUES (?, 1, ?, ?)",
            (kind, task_id, '{"k": 1}'),
        )

    everything = store.list_legacy_work(conn)

    assert [(row.kind, row.project_id, row.task_id, row.data) for row in everything] == [
        ("coordinator", 1, None, {"k": 1}), ("decision", 1, 5, {"k": 1}), ("pr", 1, 6, {"k": 1}),
    ]
    assert [row.kind for row in store.list_legacy_work(conn, kind="pr")] == ["pr"]
    store.delete_legacy_work(conn, everything[1].id)
    assert [row.kind for row in store.list_legacy_work(conn)] == ["coordinator", "pr"]
    store.delete_legacy_work(conn, everything[1].id)  # already gone: no error
