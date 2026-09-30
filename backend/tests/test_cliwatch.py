"""Real-time CLI sessions: watching the Claude projects folder."""

import asyncio
import os
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from history_fakes import FakeHistory, assistant_entry, info, now_ms, user_entry
from watchfiles import Change

from vibing import db
from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app, publish_synced
from vibing.cliwatch import CliWatcher, history_folder_name
from vibing.config import Settings
from vibing.history import HistoryIndex
from vibing.sessions import SessionManager

WAIT = 3


async def wait_until(predicate) -> None:
    deadline = time.monotonic() + WAIT
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condição não atingida")
        await asyncio.sleep(0.005)


class FakeWatch:
    """Stands in for `watchfiles.awatch`: yields the batches pushed to it."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[set[tuple[Change, str]]] = asyncio.Queue()

    def __call__(self, root: Path):
        async def gen():
            while True:
                yield await self.queue.get()

        return gen()

    def push(self, *changes: tuple[Change, Path]) -> None:
        self.queue.put_nowait({(change, str(path)) for change, path in changes})


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "data" / "vibing.db"
        db.init_db(self.db_path)
        self.folder = tmp_path / "home" / "app"
        self.folder.mkdir(parents=True)
        self.root = tmp_path / "claude" / "projects"
        self.history_dir = self.root / history_folder_name(str(self.folder))
        self.history_dir.mkdir(parents=True)
        with closing(db.connect(self.db_path)) as conn:
            self.project_id = conn.execute(
                "INSERT INTO projects (name, path, color, position, created_at)"
                " VALUES ('app', ?, '#ff8800', 0, 0)",
                (str(self.folder),),
            ).lastrowid
        self.fake = FakeHistory()
        self.events: list[dict[str, Any]] = []
        self.mtimes: dict[str, float] = {}
        self.manager = SessionManager(
            self.db_path,
            self.events.append,
            agent_factory=FakeAgentFactory(),
            history_exists=lambda sid, cwd: sid in self.fake.messages,
            rename_session=self.fake.rename_session,
            list_sessions=self.fake.list_sessions,
            get_session_messages=self.fake.get_session_messages,
            read_tool_results=self.fake.read_tool_results,
            file_mtime=lambda sid, cwd: self.mtimes.get(sid),
        )
        self.index = HistoryIndex(
            self.db_path,
            self.fake.list_sessions,
            on_change=self.manager.refresh_records,
            on_projects_changed=lambda ids: publish_synced(self.events.append, ids),
            is_in_use=self.manager.in_use,
        )
        self.watch = FakeWatch()
        self.processed: list[str] = []
        self.watcher = CliWatcher(
            self.root, self.index, self.manager,
            first_delay=0.03, interval=0.1, reload_interval=0.25,
            watch=self.watch, on_processed=self.processed.append,
        )
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.watcher.run())

    def types(self, session_id: str | None = None) -> list[str]:
        return [e["type"] for e in self.events if session_id is None or e["session_id"] == session_id]

    def file(self, session_id: str) -> Path:
        return self.history_dir / f"{session_id}.jsonl"

    def touch(self, session_id: str, mtime: float) -> Path:
        path = self.file(session_id)
        path.write_text("{}\n")
        os.utime(path, (mtime, mtime))
        return path


@pytest.fixture
async def env(tmp_path: Path):
    e = Env(tmp_path)
    yield e
    if e.task is not None:
        e.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await e.task
    await e.manager.shutdown()


def row(db_path: Path, session_id: str) -> dict[str, Any] | None:
    with closing(db.connect(db_path)) as conn:
        r = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(r) if r else None


@pytest.mark.anyio
async def test_new_file_becomes_indexed_session_with_project_synced(env):
    env.fake.add(str(env.folder), info("new-1", str(env.folder), first_prompt="Oi do CLI",
                                       modified_ms=now_ms()))
    env.start()
    env.watch.push((Change.added, env.file("new-1")))

    await wait_until(lambda: env.processed == ["new-1"])
    assert row(env.db_path, "new-1")["title"] == "Oi do CLI"
    synced = [e for e in env.events if e["type"] == "project.synced"]
    assert synced and synced[0]["data"] == {"project_id": env.project_id}


@pytest.mark.anyio
async def test_new_file_in_repository_inside_project_is_indexed(env):
    repo = env.folder / "lib"
    (repo / ".git").mkdir(parents=True)
    env.fake.add(str(repo), info("repo-1", str(repo), first_prompt="No repo"))
    other = env.root / history_folder_name(str(repo))
    other.mkdir()
    env.start()
    env.watch.push((Change.added, other / "repo-1.jsonl"))

    await wait_until(lambda: env.processed == ["repo-1"])
    assert row(env.db_path, "repo-1")["project_id"] == env.project_id


@pytest.mark.anyio
async def test_modified_known_session_updates_row_and_emits_session_updated(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder), first_prompt="Antes",
                                       modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.events.clear()
    env.fake.by_directory[str(env.folder)] = [
        info("s1", str(env.folder), custom_title="Nome do CLI", modified_ms=1_700_000_000_000)
    ]
    env.touch("s1", 1_700_000_500)
    env.fake.list_calls.clear()
    env.start()
    env.watch.push((Change.modified, env.file("s1")))

    await wait_until(lambda: env.processed == ["s1"])
    # Only the session's own folder is listed: no project sync.
    assert env.fake.list_calls == [str(env.folder)]
    assert not any(e["type"] == "project.synced" for e in env.events)
    assert row(env.db_path, "s1")["file_modified_at"] == 1_700_000_500
    assert row(env.db_path, "s1")["last_activity_at"] == 1_700_000_500
    assert row(env.db_path, "s1")["title"] == "Nome do CLI"
    updated = [e for e in env.events if e["type"] == "session.updated"]
    assert updated and updated[-1]["session_id"] == "s1"
    assert updated[-1]["data"]["session_id"] == "s1"


@pytest.mark.anyio
async def test_open_column_is_reset_and_reloaded(env):
    sid = "s1"
    env.fake.add(str(env.folder), info(sid, str(env.folder), first_prompt="oi",
                                       modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.fake.messages[sid] = [user_entry("oi", sid)]
    env.mtimes[sid] = 100.0
    await env.manager.open(sid)
    env.events.clear()

    env.fake.messages[sid] = [
        user_entry("oi", sid),
        assistant_entry({"type": "text", "text": "feito pelo CLI"}, "m1", sid),
    ]
    env.mtimes[sid] = 200.0
    env.touch(sid, 1_700_000_500)
    env.start()
    env.watch.push((Change.modified, env.file(sid)))

    await wait_until(lambda: env.processed == [sid])
    types = env.types(sid)
    assert types.count("session.updated") == 1
    assert types.index("session.updated") < types.index("conversation.reset")
    snapshot = env.manager.get(sid).snapshot()
    assert [i["type"] for i in snapshot["items"]] == ["user", "text"]
    assert snapshot["items"][-1]["text"] == "feito pelo CLI"


@pytest.mark.anyio
async def test_burst_of_writes_is_processed_once(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    env.start()
    for _ in range(10):
        env.watch.push((Change.modified, env.file("s1")))

    await wait_until(lambda: env.processed == ["s1"])
    await asyncio.sleep(0.15)
    assert env.processed == ["s1"]


@pytest.mark.anyio
async def test_session_active_in_app_is_ignored(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    session = env.manager.get("s1")
    session._connecting = True  # the app is writing this session
    env.fake.list_calls.clear()
    env.events.clear()
    env.start()
    env.watch.push((Change.modified, env.file("s1")))

    await asyncio.sleep(0.2)
    session._connecting = False
    assert env.processed == []
    assert env.fake.list_calls == []
    assert env.events == []


@pytest.mark.anyio
async def test_memory_and_stray_files_are_ignored(env):
    # Subagent files (`subagents/agent-*.jsonl`) are handled: see test_cli_turn.py.
    env.start()
    env.watch.push(
        (Change.added, env.history_dir / "s1" / "subagents" / "notes.jsonl"),
        (Change.added, env.history_dir / "s1" / "other" / "agent-1.jsonl"),
        (Change.added, env.history_dir / "memory" / "MEMORY.md"),
        (Change.added, env.history_dir / "notes.txt"),
        (Change.added, env.root / "loose.jsonl"),
    )
    await asyncio.sleep(0.2)
    assert env.processed == []
    assert env.fake.list_calls == []


@pytest.mark.anyio
async def test_deleted_file_removes_session_only_when_confirmed(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    await env.index.sync_all()
    env.fake.by_directory[str(env.folder)] = []
    env.index._file_exists = lambda sid, cwd: False
    env.start()
    env.watch.push((Change.deleted, env.file("s1")))

    await wait_until(lambda: env.processed == ["s1"])
    assert row(env.db_path, "s1") is None


@pytest.mark.anyio
async def test_folder_of_unregistered_project_is_ignored(env):
    other = env.root / history_folder_name("/somewhere/else")
    env.start()
    env.watch.push((Change.added, other / "x.jsonl"))
    await wait_until(lambda: env.processed == ["x"])
    assert env.fake.list_calls == []


@pytest.mark.anyio
async def test_missing_folder_does_not_raise(tmp_path: Path):
    e = Env(tmp_path)
    e.watcher = CliWatcher(tmp_path / "nope", e.index, e.manager)
    await asyncio.wait_for(e.watcher.run(), 1)  # returns, logging a warning
    await e.manager.shutdown()


@pytest.mark.anyio
async def test_failing_watch_is_logged_and_returns(env, caplog):
    def broken(root):
        async def gen():
            raise OSError("inotify esgotado")
            yield  # pragma: no cover

        return gen()

    env.watcher = CliWatcher(env.root, env.index, env.manager, watch=broken)
    await asyncio.wait_for(env.watcher.run(), 1)
    assert "inotify esgotado" in caplog.text


@pytest.mark.anyio
async def test_cancel_stops_pending_work(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    env.watcher = CliWatcher(env.root, env.index, env.manager, first_delay=5, watch=env.watch)
    env.start()
    env.watch.push((Change.modified, env.file("s1")))
    await asyncio.sleep(0.05)
    env.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await env.task
    env.task = None
    assert env.watcher.pending == 0


@pytest.mark.anyio
async def test_real_awatch_sees_new_file(env):
    env.fake.add(str(env.folder), info("real-1", str(env.folder), first_prompt="Real"))
    env.watcher = CliWatcher(env.root, env.index, env.manager, first_delay=0.05,
                             on_processed=env.processed.append)
    env.start()
    await asyncio.sleep(0.3)  # let inotify register
    env.file("real-1").write_text("{}\n")

    await wait_until(lambda: env.processed == ["real-1"])
    assert row(env.db_path, "real-1") is not None


async def write_continuously(env, sid: str, seconds: float, every: float = 0.02) -> float:
    """Pushes a change every `every` seconds; returns when the last one was pushed."""
    end = time.monotonic() + seconds
    mtime = 1_700_000_000
    while time.monotonic() < end:
        mtime += 1
        env.mtimes[sid] = float(mtime)
        env.touch(sid, mtime)
        env.watch.push((Change.modified, env.file(sid)))
        await asyncio.sleep(every)
    return time.monotonic()


@pytest.mark.anyio
async def test_continuous_writing_updates_during_and_after_the_burst(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    await env.index.sync_all()
    times: list[float] = []
    env.watcher._on_processed = lambda sid: times.append(time.monotonic())
    env.start()

    last_push = await write_continuously(env, "s1", 0.6)
    during = len(times)
    await wait_until(lambda: times and times[-1] > last_push)
    await asyncio.sleep(0.3)

    # First pass after ~first_delay, then at most one per interval while writing.
    assert 3 <= during <= 8
    assert times[-1] > last_push  # final pass after the burst
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= 0.09
    assert row(env.db_path, "s1")["file_modified_at"] == int(env.mtimes["s1"])


@pytest.mark.anyio
async def test_three_seconds_of_writing_with_default_timing(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    await env.index.sync_all()
    times: list[float] = []
    env.watcher = CliWatcher(env.root, env.index, env.manager, watch=env.watch,
                             on_processed=lambda sid: times.append(time.monotonic()))
    env.start()
    started = time.monotonic()

    last_push = await write_continuously(env, "s1", 3.0, every=0.1)
    during = list(times)
    await wait_until(lambda: times and times[-1] > last_push)

    assert during[0] - started < 0.5  # first pass ~0.3 s after the first write
    assert 3 <= len(during) <= 4  # then one per second while writing
    assert times[-1] - last_push <= 1.1  # final pass after the last write


@pytest.mark.anyio
async def test_open_column_reload_is_throttled_with_final_reload(env):
    sid = "s1"
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.fake.messages[sid] = [user_entry("oi", sid)]
    env.mtimes[sid] = 1.0
    await env.manager.open(sid)
    env.events.clear()
    env.start()

    counter = {"n": 0}

    def grow(session_id, directory):
        counter["n"] += 1
        return [user_entry(f"m{counter['n']}", sid)]

    env.manager._get_session_messages = grow
    env.manager.get(sid)._get_session_messages = grow
    last_push = await write_continuously(env, sid, 0.6)
    await asyncio.sleep(0.6)

    resets = env.types(sid).count("conversation.reset")
    passes = len(env.processed)
    assert passes >= 4
    assert 2 <= resets <= 4  # reload_interval 0.25 s over ~0.6 s, plus the final one
    snapshot = env.manager.get(sid).snapshot()
    # The final reload reads the file after the last write.
    assert snapshot["items"][-1]["text"] == f"m{counter['n']}"
    assert env.manager.get(sid)._loaded_mtime == env.mtimes[sid]
    assert last_push


@pytest.mark.anyio
async def test_app_starting_to_write_during_the_pass_emits_nothing(env):
    sid = "s1"
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.fake.messages[sid] = [user_entry("oi", sid)]
    env.mtimes[sid] = 1.0
    await env.manager.open(sid)
    session = env.manager.get(sid)
    env.touch(sid, 1_700_000_500)
    env.mtimes[sid] = 2.0
    listed = env.fake.list_sessions

    def list_then_connect(directory):
        session._connecting = True  # the user sent a message while we listed
        return listed(directory)

    env.watcher._list_sessions = list_then_connect
    env.events.clear()
    env.start()
    env.watch.push((Change.modified, env.file(sid)))

    await wait_until(lambda: env.processed == [sid])
    session._connecting = False
    assert env.events == []


@pytest.mark.anyio
async def test_session_opened_during_the_pass_is_not_reloaded(env):
    sid = "s1"
    env.fake.add(str(env.folder), info(sid, str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.fake.messages[sid] = [user_entry("oi", sid)]
    env.mtimes[sid] = 1.0
    await env.manager.open(sid)
    session = env.manager.get(sid)
    env.touch(sid, 1_700_000_500)
    env.mtimes[sid] = 2.0
    listed = env.fake.list_sessions

    def list_then_open(directory):
        session.users += 1  # an open() is running and will reload by itself
        return listed(directory)

    env.watcher._list_sessions = list_then_open
    env.events.clear()
    env.start()
    env.watch.push((Change.modified, env.file(sid)))

    await wait_until(lambda: env.processed == [sid])
    session.users -= 1
    assert "conversation.reset" not in env.types(sid)


@pytest.mark.anyio
async def test_app_writing_covers_turns_and_prompts(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder)))
    await env.index.sync_all()
    session = env.manager.get("s1")
    assert env.manager.app_writing("s1") is False
    session.pending_turns = 1
    assert env.manager.app_writing("s1") is True
    session.pending_turns = 0
    session.prompts["p"] = object()
    assert env.manager.app_writing("s1") is True
    session.prompts.clear()
    assert env.manager.app_writing("unknown") is False


# Worktrees -------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_session_receives_the_transcript_path(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    path = env.touch("s1", 1_700_000_500)
    calls: list[tuple[Any, ...]] = []

    def spy(session_id, mtime, info_, path_=None):
        calls.append((session_id, mtime, path_))
        return False

    env.index.update_session = spy
    env.start()
    env.watch.push((Change.modified, path))

    await wait_until(lambda: env.processed == ["s1"])
    assert calls == [("s1", 1_700_000_500, path)]


@pytest.mark.anyio
async def test_session_of_a_worktree_is_listed_from_its_history_dir(env):
    wt = env.folder / ".claude" / "worktrees" / "x"
    wt_history = env.root / history_folder_name(str(wt))
    wt_history.mkdir()
    env.fake.add(str(env.folder), info("s1", str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    with closing(db.connect(env.db_path)) as conn, conn:
        conn.execute("UPDATE sessions SET history_dir = ? WHERE session_id = 's1'", (str(wt),))
    env.fake.by_directory[str(env.folder)] = []
    env.fake.add(str(wt), info("s1", str(env.folder), custom_title="Na worktree",
                               modified_ms=1_700_000_000_000))
    path = wt_history / "s1.jsonl"
    path.write_text("{}\n")
    os.utime(path, (1_700_000_500, 1_700_000_500))
    env.fake.list_calls.clear()
    env.events.clear()
    env.start()
    env.watch.push((Change.modified, path))

    await wait_until(lambda: env.processed == ["s1"])
    assert env.fake.list_calls == [str(wt)]  # no project sync: the file is where it was
    assert not any(e["type"] == "project.synced" for e in env.events)
    assert row(env.db_path, "s1")["title"] == "Na worktree"


@pytest.mark.anyio
async def test_transcript_in_another_history_folder_triggers_project_sync(env):
    env.fake.add(str(env.folder), info("s1", str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    moved = env.root / history_folder_name(str(env.folder / ".claude" / "worktrees" / "x"))
    moved.mkdir()
    path = moved / "s1.jsonl"
    path.write_text("{}\n")
    os.utime(path, (1_700_000_500, 1_700_000_500))
    synced: list[int] = []
    real_sync = env.index.sync_project

    async def spy(project_id):
        synced.append(project_id)
        return await real_sync(project_id)

    env.index.sync_project = spy
    env.start()
    env.watch.push((Change.modified, path))
    await wait_until(lambda: env.processed == ["s1"])
    assert synced == [env.project_id]

    os.utime(path, (1_700_000_600, 1_700_000_600))
    env.watch.push((Change.modified, path))
    await wait_until(lambda: env.processed == ["s1", "s1"])
    assert synced == [env.project_id]  # the same (session, folder) is synced once


# App -------------------------------------------------------------------------


def test_app_starts_and_stops_with_missing_claude_folder(home: Path, data_dir: Path, tmp_path):
    settings = Settings(home_dir=home, data_dir=data_dir,
                        claude_projects_dir=tmp_path / "no-claude" / "projects")
    fake = FakeHistory()
    app = create_app(settings=settings, agent_factory=FakeAgentFactory(),
                     list_sessions=fake.list_sessions)
    with TestClient(app, base_url="http://127.0.0.1:6660",
                    headers={"x-vibing": "1"}) as client:
        assert client.get("/api/health").status_code == 200
        watcher_task = app.state.cli_watch_task
    assert watcher_task.done()


def test_app_watcher_is_cancelled_on_shutdown(home: Path, data_dir: Path, tmp_path):
    root = tmp_path / "claude" / "projects"
    root.mkdir(parents=True)
    settings = Settings(home_dir=home, data_dir=data_dir, claude_projects_dir=root)
    fake = FakeHistory()
    app = create_app(settings=settings, agent_factory=FakeAgentFactory(),
                     list_sessions=fake.list_sessions)
    with TestClient(app, base_url="http://127.0.0.1:6660"):
        watcher_task = app.state.cli_watch_task
        assert not watcher_task.done()
    assert watcher_task.cancelled()


def test_settings_claude_projects_dir_follows_env(monkeypatch, tmp_path):
    from vibing.config import load_settings

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert load_settings().claude_projects_dir == tmp_path / "cfg" / "projects"
