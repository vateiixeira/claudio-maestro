"""Delivery records: one per "Finalizar" click and day."""

import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from claudio_maestro import db, deliveries


def at(text: str) -> int:
    """Local timestamp of 'YYYY-MM-DD HH:MM'."""
    return int(time.mktime(datetime.strptime(text, "%Y-%m-%d %H:%M").timetuple()))


@pytest.fixture
def conn(tmp_path: Path):
    path = tmp_path / "data" / "maestro.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at)"
                     " VALUES (1, 'app', '/app', '#fff', 0, 0)")
        for sid in ("s1", "s2"):
            conn.execute("INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                         " last_activity_at) VALUES (?, 1, '/app', 'T', 0, 0)", (sid,))
        yield conn


def finish(conn, sid="s1", when="2026-10-06 10:00", cursor="c1", status="pending", title="Tela X"):
    return deliveries.record_finish(conn, session_id=sid, project_id=1, project_name="app",
                                    title=title, finished_at=at(when), to_cursor=cursor,
                                    status=status)


def test_first_finish_creates_a_record(conn) -> None:
    d = finish(conn)
    assert d.day == "2026-10-06" and d.from_cursor is None and d.to_cursor == "c1"
    assert d.status == "pending" and d.bullets == [] and d.summary_title is None
    assert d.to_dict() == {
        "id": d.id, "session_id": "s1", "project_id": 1, "project_name": "app",
        "title": "Tela X", "finished_at": at("2026-10-06 10:00"), "status": "pending",
        "summary_title": None, "bullets": [], "error": None,
    }


def test_refinish_same_day_renews_the_record(conn) -> None:
    first = finish(conn, cursor="c1")
    deliveries.save_summary(conn, first.id, summary_title="Feito", bullets=["a"], at=1)
    second = finish(conn, when="2026-10-06 18:00", cursor="c9", title="Tela X v2")
    assert second.id == first.id
    assert second.from_cursor is None and second.to_cursor == "c9"
    assert second.title == "Tela X v2" and second.finished_at == at("2026-10-06 18:00")
    assert second.status == "pending" and second.bullets == [] and second.summary_title is None
    assert len(deliveries.list_day(conn, "2026-10-06")) == 1


def test_refinish_after_midnight_creates_a_new_record(conn) -> None:
    first = finish(conn, when="2026-10-06 23:59", cursor="c1")
    second = finish(conn, when="2026-10-07 00:01", cursor="c5")
    assert second.id != first.id
    assert (second.day, second.from_cursor, second.to_cursor) == ("2026-10-07", "c1", "c5")


def test_list_day_orders_by_project_and_time(conn) -> None:
    conn.execute("INSERT INTO projects (id, name, path, color, position, created_at)"
                 " VALUES (2, 'Beta', '/b', '#fff', 1, 0)")
    b = deliveries.record_finish(conn, session_id="s2", project_id=2, project_name="Beta",
                                 title="B", finished_at=at("2026-10-06 09:00"), to_cursor=None,
                                 status="title_only")
    late = finish(conn, when="2026-10-06 15:00")
    assert [d.id for d in deliveries.list_day(conn, "2026-10-06")] == [late.id, b.id]
    assert deliveries.list_day(conn, "2026-10-05") == []


def test_status_changes(conn) -> None:
    d = finish(conn)
    done = deliveries.save_summary(conn, d.id, summary_title="T", bullets=["x", "y"], at=5)
    assert (done.status, done.summary_title, done.bullets, done.error) == ("done", "T", ["x", "y"], None)
    failed = deliveries.mark_error(conn, d.id, "Falhou.", at=6)
    assert (failed.status, failed.error, failed.bullets) == ("error", "Falhou.", ["x", "y"])
    again = deliveries.mark_pending(conn, d.id, at=7)
    assert (again.status, again.error) == ("pending", None)
    plain = deliveries.mark_title_only(conn, d.id, at=8)
    assert (plain.status, plain.summary_title, plain.bullets) == ("title_only", None, [])
    assert deliveries.mark_error(conn, 999, "x", at=9) is None


def test_pending_ids(conn) -> None:
    a = finish(conn, sid="s1")
    finish(conn, sid="s2", status="title_only")
    assert deliveries.pending_ids(conn) == [a.id]


def test_deleting_the_session_keeps_the_record(conn) -> None:
    d = finish(conn)
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    conn.execute("DELETE FROM projects WHERE id = 1")
    kept = deliveries.get(conn, d.id)
    assert kept.session_id is None and kept.project_id is None
    assert kept.project_name == "app" and kept.title == "Tela X"


def test_local_day() -> None:
    assert deliveries.local_day(at("2026-10-06 23:59")) == "2026-10-06"
    assert deliveries.local_day(at("2026-10-07 00:00")) == "2026-10-07"
