"""Database access of the digest agent."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from vibing import db
from vibing.digest import store
from vibing.digest.store import Digest


@pytest.fixture
def conn(tmp_path: Path):
    path = tmp_path / "vibing.db"
    db.init_db(path)
    with closing(db.connect(path)) as c:
        c.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'app', '/tmp/app', '#fff', 0, 0)"
        )
        for sid in ("s1", "s2"):
            c.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, '/tmp/app', 't', 0, 0)",
                (sid,),
            )
        yield c


def test_tables_exist(conn: sqlite3.Connection) -> None:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"session_digests", "digest_runs"} <= names


def test_save_and_get_round_trip(conn: sqlite3.Connection) -> None:
    phase = {"title": "Plano X", "kind": "plan", "status": "done", "done": ["a"],
             "pending": [], "ref": None}
    store.save_digest(conn, Digest("s1", cursor="u9", read_at=100, short="Faz X",
                                   phases=[phase], plan_done=True, plan_ref="/p.md"))
    got = store.get_digest(conn, "s1")
    assert got == Digest("s1", cursor="u9", read_at=100, short="Faz X", phases=[phase],
                         plan_done=True, plan_ref="/p.md")
    assert store.get_digest(conn, "s2") is None


def test_to_dict_hides_internal_fields() -> None:
    data = Digest("s1", cursor="u1", plan_ref="/p.md", short="x").to_dict()
    assert "cursor" not in data and "plan_ref" not in data
    assert data == {"session_id": "s1", "read_at": None, "short": "x", "phases": [],
                    "plan_done": False, "error": None, "error_at": None}


def test_save_error_keeps_the_summary(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="Faz X", read_at=5))
    got = store.save_error(conn, "s1", "Falhou.", 10)
    assert got is not None and got.short == "Faz X" and got.error == "Falhou." and got.error_at == 10
    fresh = store.save_error(conn, "s2", "Sem resumo.", 11)
    assert fresh is not None and fresh.short is None and fresh.error == "Sem resumo."


def test_save_error_for_unknown_session_returns_none(conn: sqlite3.Connection) -> None:
    assert store.save_error(conn, "nope", "x", 1) is None


def test_save_digest_for_unknown_session_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.save_digest(conn, Digest("nope"))


def test_digest_goes_away_with_the_session(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="x"))
    conn.execute("DELETE FROM sessions WHERE session_id = 's1'")
    assert store.get_digest(conn, "s1") is None


def test_briefs(conn: sqlite3.Connection) -> None:
    store.save_digest(conn, Digest("s1", short="Faz X", plan_done=True))
    assert store.briefs(conn) == {"s1": ("Faz X", True)}


def test_runs_are_logged_newest_first_and_trimmed(conn: sqlite3.Connection) -> None:
    for i in range(store.MAX_RUNS + 5):
        run_id = store.start_run(conn, "auto", i)
        store.finish_run(conn, run_id, at=i + 1, read_count=1, skipped_count=2,
                         errors=[{"session_id": "s1", "title": "t", "message": "m"}],
                         stopped=None)
    runs = store.list_runs(conn)
    assert len(runs) == store.MAX_RUNS
    assert runs[0]["started_at"] == store.MAX_RUNS + 4
    assert runs[0] == {
        "id": runs[0]["id"], "started_at": store.MAX_RUNS + 4, "finished_at": store.MAX_RUNS + 5,
        "trigger": "auto", "read_count": 1, "skipped_count": 2,
        "errors": [{"session_id": "s1", "title": "t", "message": "m"}], "stopped": None,
    }


def test_finish_run_returns_the_run(conn: sqlite3.Connection) -> None:
    run_id = store.start_run(conn, "manual_all", 7)
    run = store.finish_run(conn, run_id, at=9, read_count=0, skipped_count=0, errors=[],
                           stopped="Desligado.")
    assert run["stopped"] == "Desligado." and run["trigger"] == "manual_all"
