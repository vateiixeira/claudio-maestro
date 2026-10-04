"""Database access of the closure check."""

import sqlite3
from contextlib import closing

import pytest

from claudio_maestro import db
from claudio_maestro.digest.closure_store import (
    Closure,
    closure_briefs,
    get_closure,
    save_closure,
    save_closure_error,
)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "maestro.db"
    db.init_db(path)
    with closing(db.connect(path)) as c:
        c.execute("INSERT INTO projects (id, name, path, color, position, created_at)"
                  " VALUES (1, 'app', '/tmp/app', '#fff', 0, 0)")
        c.execute("INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                  " last_activity_at) VALUES ('s1', 1, '/tmp/app', 'S', 0, 100)")
        yield c


def test_round_trip(conn) -> None:
    closure = Closure("s1", verdict="user_action", user_actions=["Reiniciar"], missing=[],
                      evidence="Falta reiniciar", resolved=["Rodar migração"],
                      fingerprint="abc", checked_at=200)
    save_closure(conn, closure)
    assert get_closure(conn, "s1") == closure


def test_missing_session_raises(conn) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        save_closure(conn, Closure("nope", verdict="can_close", checked_at=1))


def test_error_keeps_last_verdict(conn) -> None:
    save_closure(conn, Closure("s1", verdict="can_close", checked_at=200))
    after = save_closure_error(conn, "s1", "Tempo esgotado.", 300)
    assert after is not None
    assert (after.verdict, after.error, after.error_at) == ("can_close", "Tempo esgotado.", 300)
    assert save_closure_error(conn, "nope", "x", 1) is None


def test_stale_hides_verdict(conn) -> None:
    closure = Closure("s1", verdict="user_action", user_actions=["A"], evidence="e", checked_at=200)
    assert closure.to_dict(150)["verdict"] == "user_action"
    stale = closure.to_dict(250)
    assert (stale["verdict"], stale["user_actions"], stale["evidence"]) == (None, [], None)
    assert Closure("s1").to_dict(0)["verdict"] is None  # never checked


def test_briefs(conn) -> None:
    save_closure(conn, Closure("s1", verdict="incomplete", checked_at=200))
    assert closure_briefs(conn) == {"s1": ("incomplete", 200)}


def test_cascade_on_session_delete(conn) -> None:
    save_closure(conn, Closure("s1", verdict="can_close", checked_at=1))
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    assert get_closure(conn, "s1") is None
