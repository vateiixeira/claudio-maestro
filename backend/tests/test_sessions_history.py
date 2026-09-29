"""Old sessions: open without a process, resume on send, external activity, pending rename."""

import asyncio
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from history_fakes import FakeHistory, assistant_entry, info, now_ms, user_entry

from vibing import db, projects
from vibing.agent.fake import FakeAgentFactory, text_turn
from vibing.sessions import SessionManager

WAIT = 2


async def wait_until(predicate) -> None:
    deadline = time.monotonic() + WAIT
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condição não atingida")
        await asyncio.sleep(0.005)


class Env:
    def __init__(self, tmp_path: Path, script=None, history_limit: int = 500) -> None:
        self.db_path = tmp_path / "data" / "vibing.db"
        db.init_db(self.db_path)
        self.folder = tmp_path / "home" / "app"
        self.folder.mkdir(parents=True)
        with closing(db.connect(self.db_path)) as conn:
            self.project_id = conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at)"
                " VALUES ('app', ?, '#ff8800', 0, 0)",
                (str(self.folder),),
            ).lastrowid
        self.fake = FakeHistory()
        self.factory = FakeAgentFactory(script=script)
        self.events: list[dict[str, Any]] = []
        self.manager = SessionManager(
            self.db_path,
            self.events.append,
            agent_factory=self.factory,
            history_exists=lambda sid, cwd: sid in self.fake.messages,
            rename_session=self.fake.rename_session,
            list_sessions=self.fake.list_sessions,
            get_session_messages=self.fake.get_session_messages,
            read_tool_results=self.fake.read_tool_results,
            history_limit=history_limit,
            file_mtime=lambda sid, cwd: self.mtimes.get(sid),
        )
        self.mtimes: dict[str, float] = {}

    def add_old_session(self, session_id: str = "old-1", cwd: str | None = None) -> str:
        cwd = cwd or str(self.folder)
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, last_seen_at, finished) VALUES (?, ?, ?, 'Antiga', 1, 2, 2, 0)",
                (session_id, self.project_id, cwd),
            )
        self.fake.messages[session_id] = [
            user_entry("oi", session_id),
            assistant_entry({"type": "text", "text": "olá"}, "m1", session_id),
        ]
        return session_id


@pytest.fixture
async def make_env(tmp_path: Path):
    envs: list[Env] = []

    def build(**kwargs) -> Env:
        env = Env(tmp_path, **kwargs)
        envs.append(env)
        return env

    yield build
    for env in envs:
        await env.manager.shutdown()


@pytest.mark.anyio
async def test_open_old_session_loads_conversation_without_client(make_env):
    env = make_env()
    sid = env.add_old_session(cwd=str(env.folder / "sub"))

    snapshot = await env.manager.open(sid)

    assert [i["type"] for i in snapshot["items"]] == ["user", "text"]
    assert snapshot["history_truncated"] is False
    assert snapshot["state"] == "closed"
    assert env.factory.clients == []
    assert env.fake.message_calls == [(sid, str(env.folder / "sub"))]

    await env.manager.open(sid)
    assert len(env.fake.message_calls) == 1  # loaded once


@pytest.mark.anyio
async def test_history_is_truncated_to_the_last_messages(make_env):
    env = make_env(history_limit=3)
    sid = env.add_old_session()
    env.fake.messages[sid] = [user_entry(f"m{n}", sid) for n in range(5)]

    snapshot = await env.manager.open(sid)

    assert [i["text"] for i in snapshot["items"]] == ["m2", "m3", "m4"]
    assert snapshot["history_truncated"] is True


@pytest.mark.anyio
async def test_failing_history_load_shows_notice(make_env):
    env = make_env()
    sid = env.add_old_session()

    def broken(session_id, directory):
        raise RuntimeError("quebrou")

    env.manager._get_session_messages = broken
    snapshot = await env.manager.open(sid)

    assert snapshot["items"][-1]["type"] == "notice"


@pytest.mark.anyio
async def test_send_resumes_and_does_not_duplicate_items(make_env):
    sessions: list[str] = []
    env = make_env(script=lambda content: text_turn(sessions[0], "resposta"))
    sid = env.add_old_session()
    sessions.append(sid)

    await env.manager.open(sid)
    result = await env.manager.send(sid, "continua")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")

    assert result["external_activity"] is False
    client = env.factory.clients[0]
    assert client.options.resume is True
    assert client.options.cwd == Path(env.folder)
    texts = [i.get("text") for i in session.snapshot()["items"]]
    assert texts == ["oi", "olá", "continua", "resposta"]


@pytest.mark.anyio
async def test_send_without_opening_loads_history_first(make_env):
    sessions: list[str] = []
    env = make_env(script=lambda content: text_turn(sessions[0], "resposta"))
    sid = env.add_old_session()
    sessions.append(sid)

    await env.manager.send(sid, "continua")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")

    texts = [i.get("text") for i in session.snapshot()["items"]]
    assert texts == ["oi", "olá", "continua", "resposta"]


@pytest.mark.anyio
async def test_external_activity_when_file_modified_recently(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=now_ms() - 10_000))

    snapshot = await env.manager.open(sid)

    assert snapshot["external_activity"] is True


@pytest.mark.anyio
async def test_no_external_activity_for_old_file(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=now_ms() - 120_000))

    snapshot = await env.manager.open(sid)

    assert snapshot["external_activity"] is False


@pytest.mark.anyio
async def test_send_reports_external_activity_on_resume(make_env):
    sessions: list[str] = []
    env = make_env(script=lambda content: text_turn(sessions[0], "r"))
    sid = env.add_old_session()
    sessions.append(sid)
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=now_ms()))

    result = await env.manager.send(sid, "oi de novo")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")

    assert result["external_activity"] is True
    # Active in the app now: no longer external.
    assert session.snapshot()["external_activity"] is False


@pytest.mark.anyio
async def test_rename_before_history_is_applied_after_first_connection(make_env):
    sessions: list[str] = []
    env = make_env(script=lambda content: text_turn(sessions[0], "r"))
    with closing(db.connect(env.db_path)) as conn:
        project = projects.get_project(conn, env.project_id)
    record = env.manager.create_session(project)
    sid = record.session_id
    sessions.append(sid)

    await env.manager.update(sid, title="Meu nome")
    assert env.fake.renames == []

    await env.manager.send(sid, "primeira")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle" and env.fake.renames)

    assert env.fake.renames == [(sid, "Meu nome", str(env.folder))]
    with closing(db.connect(env.db_path)) as conn:
        row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()
    assert row["rename_pending"] == 0
    assert row["title_custom"] == 1
    assert row["title"] == "Meu nome"  # the first message does not replace it


@pytest.mark.anyio
async def test_rename_with_history_is_applied_immediately(make_env):
    env = make_env()
    sid = env.add_old_session()

    await env.manager.update(sid, title="Outro")

    assert env.fake.renames == [(sid, "Outro", str(env.folder))]


@pytest.mark.anyio
async def test_open_fills_results_from_raw_transcript(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.fake.messages[sid] = [
        assistant_entry({"type": "tool_use", "id": "t1", "name": "Edit", "input": {}}, "m1", sid),
    ]
    env.fake.raw_results[sid] = {
        "t1": {"content": "ok", "is_error": False, "details": {"structuredPatch": []}}
    }

    snapshot = await env.manager.open(sid)

    tool = snapshot["items"][0]
    assert tool["result"]["details"] == {"structuredPatch": []}
    assert tool["result_missing"] is False


@pytest.mark.anyio
async def test_file_info_is_cached_per_cwd(make_env):
    env = make_env()
    a = env.add_old_session("old-a")
    b = env.add_old_session("old-b")

    await env.manager.open(a)
    await env.manager.open(a)
    await env.manager.open(b)

    assert env.fake.list_calls == [str(env.folder)]


@pytest.mark.anyio
async def test_reopening_reloads_conversation_modified_outside(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    first = await env.manager.open(sid)
    assert [i["type"] for i in first["items"]] == ["user", "text"]

    env.fake.messages[sid] += [
        user_entry("mais", sid, uuid="u2"),
        assistant_entry({"type": "text", "text": "de novo"}, "m2", sid),
    ]
    again = await env.manager.open(sid)
    assert len(again["items"]) == 2  # file unchanged: cache kept

    env.mtimes[sid] = 200.0
    reloaded = await env.manager.open(sid)
    assert [i["type"] for i in reloaded["items"]] == ["user", "text", "user", "text"]
    assert reloaded["seq"] >= again["seq"]


@pytest.mark.anyio
async def test_send_reloads_modified_history_before_connecting(make_env):
    env = make_env(script=lambda content: text_turn("old-1", "ok"))
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    env.fake.messages[sid] += [user_entry("fora", sid, uuid="u2")]
    env.mtimes[sid] = 200.0

    await env.manager.send(sid, "nova")

    texts = [i.get("text") for i in env.manager.get(sid).builder.snapshot() if i["type"] == "user"]
    assert texts[:3] == ["oi", "fora", "nova"]


@pytest.mark.anyio
async def test_idle_sweep_forgets_closed_sessions_and_keeps_seq(make_env):
    env = make_env()
    sid = env.add_old_session()
    snapshot = await env.manager.open(sid)
    session = env.manager.get(sid)
    session._emit("session.updated", {})
    seq = session.seq

    await env.manager.close_idle()

    assert sid not in env.manager.active_ids()
    assert env.manager.get(sid).seq == seq + 1  # conversation.reset
    assert snapshot is not None


@pytest.mark.anyio
async def test_reload_emits_reset_before_new_items_on_open(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    env.events.clear()
    env.mtimes[sid] = 200.0

    snapshot = await env.manager.open(sid)

    resets = [e for e in env.events if e["type"] == "conversation.reset"]
    assert len(resets) == 1 and resets[0]["session_id"] == sid
    assert snapshot["seq"] >= resets[0]["seq"]


@pytest.mark.anyio
async def test_reload_on_send_emits_reset_before_user_message(make_env):
    env = make_env(script=lambda content: text_turn("old-1", "ok"))
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    env.events.clear()
    env.mtimes[sid] = 200.0

    await env.manager.send(sid, "nova")

    types = [e["type"] for e in env.events]
    assert "conversation.reset" in types
    first_upsert = next(
        i for i, e in enumerate(env.events)
        if e["type"] == "item.upsert" and e["data"].get("text") == "nova"
    )
    assert types.index("conversation.reset") < first_upsert
    seqs = [e["seq"] for e in env.events if e["session_id"] == sid]
    assert seqs == sorted(seqs)


@pytest.mark.anyio
async def test_no_reload_while_another_operation_runs(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    session = env.manager.get(sid)
    env.mtimes[sid] = 200.0

    async with session._lock:
        await env.manager.open(sid)
    session.users += 1
    await env.manager.open(sid)
    session.users -= 1

    assert not [e for e in env.events if e["type"] == "conversation.reset"]


@pytest.mark.anyio
async def test_forgotten_connected_session_reopens_with_disk_items(make_env):
    env = make_env(script=lambda content: text_turn("old-1", "resposta"))
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.send(sid, "oi de novo")
    session = env.manager.get(sid)
    await wait_until(lambda: session.state == "idle")
    await session.close()
    env.manager.forget_closed()
    assert sid not in env.manager.active_ids()
    env.fake.messages[sid] += [
        user_entry("oi de novo", sid, uuid="u2"),
        assistant_entry({"type": "text", "text": "resposta"}, "m2", sid),
    ]
    env.events.clear()

    snapshot = await env.manager.open(sid)

    assert [i["type"] for i in snapshot["items"]] == ["user", "text", "user", "text"]
    assert env.events[0]["type"] == "conversation.reset"
    assert env.events[0]["seq"] > 0


@pytest.mark.anyio
async def test_forgotten_session_send_emits_reset_before_message(make_env):
    env = make_env(script=lambda content: text_turn("old-1", "ok"))
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    seq = env.manager.get(sid).seq
    env.manager.forget_closed()
    env.fake.messages[sid] += [user_entry("fora", sid, uuid="u2")]
    env.mtimes[sid] = 200.0
    env.events.clear()

    await env.manager.send(sid, "nova")

    types = [e["type"] for e in env.events]
    assert types[0] == "conversation.reset" and env.events[0]["seq"] > seq
    first_upsert = next(
        i for i, e in enumerate(env.events)
        if e["type"] == "item.upsert" and e["data"].get("text") == "nova"
    )
    assert 0 < first_upsert
    texts = [i.get("text") for i in env.manager.get(sid).builder.snapshot() if i["type"] == "user"]
    assert texts[:3] == ["oi", "fora", "nova"]


@pytest.mark.anyio
async def test_external_change_on_forgotten_session_resets_column(make_env):
    env = make_env()
    sid = env.add_old_session()
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    seq = env.manager.get(sid).seq
    await env.manager.close_idle()
    env.manager.forget_closed()
    assert sid not in env.manager.active_ids()
    env.events.clear()

    assert await env.manager.apply_external_change(sid) is True

    resets = [e for e in env.events if e["type"] == "conversation.reset"]
    assert len(resets) == 1 and resets[0]["session_id"] == sid
    assert resets[0]["seq"] > seq
    # Reopening continues after the reset.
    await env.manager.open(sid)
    assert env.manager.get(sid).seq > resets[0]["seq"]
