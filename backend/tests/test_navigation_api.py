"""Marco 7: mark many sessions as seen, and activity per day and project."""

import json
import os
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_multisession_api import new_session
from test_sessions_api import APP_ORIGIN, BACKEND_URL, make_project, receive

from claudio_maestro import db
from claudio_maestro.activity import ActivityReader, message_days
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings


def local(y, m, d, hh=12, mm=0) -> str:
    """ISO timestamp with the machine's own offset."""
    return datetime(y, m, d, hh, mm).astimezone().isoformat()


def write_transcript(path: Path, stamps: list[str], kind: str = "user") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": kind, "uuid": f"u{i}", "timestamp": s}) for i, s in enumerate(stamps)]
    path.write_text("\n".join(lines) + "\n")


class Files:
    """Fake `session_file`: session id -> path."""

    def __init__(self) -> None:
        self.paths: dict[str, Path] = {}
        self.calls = 0

    def __call__(self, session_id: str, directory: str) -> Path | None:
        self.calls += 1
        return self.paths.get(session_id)


@pytest.fixture
def files() -> Files:
    return Files()


@pytest.fixture
def api(files, home, data_dir):
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir),
        agent_factory=FakeAgentFactory(),
        history_exists=lambda session_id, cwd: False,
        session_file=files,
    )
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as c:
        yield c


# message_days -----------------------------------------------------------------


def test_message_days_reads_local_dates_of_user_and_assistant_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(
        "\n".join([
            json.dumps({"type": "user", "timestamp": local(2026, 9, 28, 23, 50)}),
            json.dumps({"type": "assistant", "timestamp": local(2026, 9, 29, 0, 10)}),
            json.dumps({"type": "summary", "timestamp": local(2026, 9, 20)}),
            "não é json",
            json.dumps({"type": "user", "timestamp": "sem data"}),
            json.dumps({"type": "user"}),
        ]) + "\n"
    )
    assert message_days(path) == frozenset({date(2026, 9, 28), date(2026, 9, 29)})


def test_message_days_converts_utc_to_local_day(tmp_path):
    # 02:00 UTC on the 29th is still the 28th in UTC-3, and the 29th in UTC+2.
    moment = datetime(2026, 9, 29, 2, 0).astimezone()  # local wall clock
    utc = moment.astimezone(timezone.utc)
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps({"type": "user", "timestamp": utc.isoformat().replace("+00:00", "Z")}) + "\n")
    assert message_days(path) == frozenset({moment.date()})


# ActivityReader -------------------------------------------------------------------


def insert_session(db_path: Path, project_id: int, sid: str, last_activity: float) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
            " last_activity_at, last_seen_at, finished) VALUES (?, ?, '/p', 't', 0, ?, 0, 0)",
            (sid, project_id, int(last_activity)),
        )


def insert_project(db_path: Path, pid: int) -> None:
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (?, ?, ?, '#fff', 0, 0)",
            (pid, f"p{pid}", f"/p{pid}"),
        )


def test_reader_counts_sessions_per_day_and_project(tmp_path, files):
    db_path = tmp_path / "maestro.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    insert_project(db_path, 2)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    for sid, pid, stamps in [
        ("a", 1, [local(2026, 9, 29), local(2026, 9, 28)]),
        ("b", 1, [local(2026, 9, 29, 9)]),
        ("c", 2, [local(2026, 9, 27)]),
        ("old", 2, [local(2026, 9, 1)]),  # outside 14 days
    ]:
        path = tmp_path / "h" / f"{sid}.jsonl"
        write_transcript(path, stamps)
        files.paths[sid] = path
        insert_session(db_path, pid, sid, now)

    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    assert reader.read(14) == [
        {"date": "2026-09-27", "project_id": 2, "sessions": 1},
        {"date": "2026-09-28", "project_id": 1, "sessions": 1},
        {"date": "2026-09-29", "project_id": 1, "sessions": 2},
    ]


def test_reader_skips_sessions_without_recent_activity_and_missing_files(tmp_path, files):
    db_path = tmp_path / "maestro.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    stale = tmp_path / "h" / "stale.jsonl"
    write_transcript(stale, [local(2026, 9, 29)])
    files.paths["stale"] = stale
    insert_session(db_path, 1, "stale", now - 40 * 86400)  # last activity long ago
    insert_session(db_path, 1, "nofile", now)

    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    assert reader.read(14) == []
    assert files.calls == 1  # only "nofile" was looked up


def test_reader_caches_by_modification_time(tmp_path, files, monkeypatch):
    db_path = tmp_path / "maestro.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    path = tmp_path / "h" / "a.jsonl"
    write_transcript(path, [local(2026, 9, 29)])
    os.utime(path, (now, now))
    files.paths["a"] = path
    insert_session(db_path, 1, "a", now)
    reads = []
    import claudio_maestro.activity as activity_module
    original = activity_module.message_days
    monkeypatch.setattr(activity_module, "message_days", lambda p: reads.append(p) or original(p))
    reader = ActivityReader(db_path, session_file=files, clock=lambda: now)

    reader.read(14)
    reader.read(14)
    assert len(reads) == 1

    write_transcript(path, [local(2026, 9, 28)])
    os.utime(path, (now + 5, now + 5))
    assert reader.read(14) == [{"date": "2026-09-28", "project_id": 1, "sessions": 1}]
    assert len(reads) == 2


def test_reader_finds_file_through_history_dir(tmp_path):
    db_path = tmp_path / "maestro.db"
    db.init_db(db_path)
    insert_project(db_path, 1)
    now = datetime(2026, 9, 29, 15, 0).timestamp()
    insert_session(db_path, 1, "a", now)
    insert_session(db_path, 1, "b", now)
    with closing(db.connect(db_path)) as conn:
        conn.execute("UPDATE sessions SET history_dir = '/h' WHERE session_id = 'a'")
    seen: list[tuple[str, str]] = []

    def finder(session_id: str, directory: str) -> Path | None:
        seen.append((session_id, directory))
        return None

    ActivityReader(db_path, session_file=finder, clock=lambda: now).read(14)

    assert sorted(seen) == [("a", "/h"), ("b", "/p")]


# Routes ---------------------------------------------------------------------------


def test_activity_route_limits_days(api):
    assert api.get("/api/activity?days=0").status_code == 422
    assert api.get("/api/activity?days=32").status_code == 422
    assert api.get("/api/activity").json() == []


def test_activity_route_reads_registered_sessions(api, home, files, tmp_path):
    project = make_project(api, home)
    sid = new_session(api, project)["session_id"]
    path = tmp_path / "h" / f"{sid}.jsonl"
    write_transcript(path, [datetime.now().astimezone().isoformat()])
    files.paths[sid] = path

    body = api.get("/api/activity?days=1").json()

    assert body == [{"date": date.today().isoformat(), "project_id": project["id"], "sessions": 1}]


def test_seen_many_marks_known_sessions_and_ignores_unknown(api, home):
    project = make_project(api, home)
    a = new_session(api, project)["session_id"]
    b = new_session(api, project)["session_id"]

    with api.websocket_connect("ws://127.0.0.1:6660/ws", headers={"origin": APP_ORIGIN, "x-maestro": "1"}) as ws:
        response = api.post("/api/sessions/seen", json={"session_ids": [a, "desconhecida", b, a]})
        events = [receive(ws), receive(ws)]

    assert response.status_code == 200
    assert response.json() == {"updated": 2}
    assert sorted(e["session_id"] for e in events) == sorted([a, b])
    assert all(e["type"] == "session.updated" for e in events)


def test_seen_many_refuses_more_than_500_ids(api):
    response = api.post("/api/sessions/seen", json={"session_ids": [f"s{i}" for i in range(501)]})
    assert response.status_code == 422


def test_seen_many_requires_the_maestro_header(home, data_dir):
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=FakeAgentFactory())
    with TestClient(app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}) as c:
        assert c.post("/api/sessions/seen", json={"session_ids": []}).status_code == 403
