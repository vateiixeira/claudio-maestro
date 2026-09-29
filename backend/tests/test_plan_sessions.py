"""Plan of a conversation: link to `docs/superpowers/plans/*.md` and progress in the summary.

Uses the scripted fake agent; nothing here starts the `claude` process.
"""

import threading
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ToolUseBlock
from test_sessions import Recorder, by_session, fake_history, session_row, wait_until

from vibing import db
from vibing.agent.fake import (
    PauseStep,
    init_message,
    response_messages,
    result_message,
    status_message,
    text_turn,
    tool_result_message,
    tool_turn,
)
from vibing.plans import PLAN_TOOLS, PlanCache, looks_like_plan_path
from vibing.sessions import SessionManager

PLAN_TEXT = "# P\n\n### Tarefa 1: A\n- [x] a\n\n### Tarefa 2: B\n- [ ] b\n"
PLAN_DONE_TEXT = "# P\n\n### Tarefa 1: A\n- [x] a\n\n### Tarefa 2: B\n- [x] b\n"


@pytest.fixture
def make_env(tmp_path: Path):
    from test_sessions import Env

    from vibing.agent.fake import FakeAgentFactory

    def build(script=None) -> Env:
        return Env(tmp_path, FakeAgentFactory(script=script))

    return build


@pytest.fixture
async def env_cleanup():
    managers: list[SessionManager] = []
    yield managers
    for manager in managers:
        await manager.shutdown()


def write_plan(folder: Path, name: str = "p.md", text: str = PLAN_TEXT) -> Path:
    plans = folder / "docs" / "superpowers" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / name
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def plan_of(updates: list[dict[str, Any]]) -> list[Any]:
    return [u["data"].get("plan") for u in updates]


def expected_plan(path: Path, done: int = 1) -> dict[str, Any]:
    current = None if done == 2 else {"number": 2, "title": "B"}
    return {"path": str(path), "title": "P", "total": 2, "done": done, "current": current}


async def settle(session) -> None:
    """Wait for the turn to end and for the scheduled plan refreshes to finish."""
    await wait_until(lambda: session.state == "idle")
    await wait_until(lambda: not session._plan_tasks)


def use_turn(sid: str, name: str, path: Path | str, **kwargs):
    return tool_turn(sid, tool_name=name, tool_input={"file_path": str(path)}, **kwargs)


# Migration ---------------------------------------------------------------------


def test_new_database_has_plan_columns(tmp_path):
    path = tmp_path / "data" / "vibing.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert {"plan_path", "plan_link"} <= columns


def test_previous_schema_migrates_without_losing_rows(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    full = list(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", full[:-1])
    monkeypatch.setattr(db, "SCHEMA_VERSION", len(full) - 1)
    with closing(db.connect(path)) as conn:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES ('app', '/x', '#fff', 0, 0)"
        )
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
            " last_activity_at) VALUES ('s1', 1, '/x', 'Antiga', 1, 2)"
        )
    monkeypatch.setattr(db, "MIGRATIONS", full)
    monkeypatch.setattr(db, "SCHEMA_VERSION", len(full))
    with closing(db.connect(path)) as conn:
        db.migrate(conn)
        row = conn.execute("SELECT * FROM sessions WHERE session_id = 's1'").fetchone()
    assert row["title"] == "Antiga"
    assert row["plan_path"] is None and row["plan_link"] is None


def test_plan_tools_constant():
    assert PLAN_TOOLS == {"Read", "Edit", "MultiEdit", "Write"}


# Live link ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_read_of_a_plan_links_the_session_and_publishes_progress(make_env, env_cleanup):
    script, ids = by_session(lambda sid: use_turn(sid, "Read", plan))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("execute o plano")
    await settle(session)

    assert session.record.plan_path == str(plan)
    assert session.record.plan_link == "auto"
    row = session_row(env.db_path, session.session_id)
    assert (row["plan_path"], row["plan_link"]) == (str(plan), "auto")
    updates = env.recorder.of(session.session_id, "session.updated")
    assert expected_plan(plan) in plan_of(updates)
    assert session.summary()["plan"] == expected_plan(plan)


@pytest.mark.anyio
async def test_subagent_edit_of_a_plan_links_the_session(make_env, env_cleanup):
    def turn(sid):
        steps = text_turn(sid, "ok")
        sub = response_messages(
            sid,
            [ToolUseBlock(id="toolu_sub", name="Edit", input={"file_path": str(plan)})],
            parent_tool_use_id="toolu_parent",
            stop_reason="tool_use",
        )
        return [*steps[:-1], *sub, steps[-1]]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("oi")
    await settle(session)

    assert session.record.plan_path == str(plan)
    assert session.summary()["plan"] == expected_plan(plan)


@pytest.mark.anyio
async def test_the_last_plan_touched_wins(make_env, env_cleanup):
    script, ids = by_session(
        lambda sid: use_turn(sid, "Read", first),
        lambda sid: use_turn(sid, "Read", second),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    first = write_plan(Path(env.project.path), "a.md")
    second = write_plan(Path(env.project.path), "b.md")
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("um")
    await settle(session)
    assert session.record.plan_path == str(first)
    await session.send("dois")
    await settle(session)

    assert session.record.plan_path == str(second)
    assert session.summary()["plan"]["path"] == str(second)


@pytest.mark.anyio
async def test_manual_link_is_never_replaced_by_the_automatic_one(make_env, env_cleanup):
    script, ids = by_session(lambda sid: use_turn(sid, "Read", other))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    chosen = write_plan(Path(env.project.path), "a.md")
    other = write_plan(Path(env.project.path), "b.md")
    session = env.new_session()
    ids.append(session.session_id)
    assert env.manager.link_plan(session.session_id, str(chosen), source="manual") is True

    await session.send("leia")
    await settle(session)

    assert session.record.plan_path == str(chosen)
    assert session.record.plan_link == "manual"


@pytest.mark.anyio
async def test_off_link_is_never_turned_back_on_by_a_read(make_env, env_cleanup):
    script, ids = by_session(lambda sid: use_turn(sid, "Read", plan))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)
    env.manager.unlink_plan(session.session_id)
    assert (session.record.plan_path, session.record.plan_link) == (None, "off")

    await session.send("leia")
    await settle(session)

    assert session.record.plan_path is None
    assert session.record.plan_link == "off"
    assert session.summary()["plan"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("where", ["outside", "wrong-folder", "symlink", "dotdot"])
async def test_paths_that_are_not_plans_of_a_project_are_not_linked(
    make_env, env_cleanup, tmp_path, where
):
    env = make_env(script=lambda content: [])
    env_cleanup.append(env.manager)
    project = Path(env.project.path)
    outside = write_plan(tmp_path / "outside")
    if where == "outside":
        target: Path | str = outside
    elif where == "wrong-folder":
        (project / "docs").mkdir(exist_ok=True)
        target = project / "docs" / "p.md"
        target.write_text(PLAN_TEXT, encoding="utf-8")
    elif where == "symlink":
        write_plan(project, "real.md")
        link = project / "docs" / "superpowers" / "plans" / "link.md"
        link.symlink_to(outside)
        target = link
    else:
        target = f"{project}/docs/superpowers/plans/../../../../../outside/docs/superpowers/plans/p.md"

    script, ids = by_session(lambda sid: use_turn(sid, "Read", target))
    env.factory.script = script
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("leia")
    await settle(session)

    assert session.record.plan_path is None
    assert session.record.plan_link is None
    assert session.summary()["plan"] is None


# Refresh -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_edit_result_on_the_linked_plan_refreshes_progress_before_the_turn_ends(
    make_env, env_cleanup
):
    holds: list[PauseStep] = []

    def turn(sid):
        first, second = PauseStep(), PauseStep()
        holds.extend([first, second])
        return [
            init_message(sid),
            status_message(sid),
            *response_messages(
                sid,
                [ToolUseBlock(id="toolu_edit", name="Edit", input={"file_path": str(plan)})],
                stop_reason="tool_use",
            ),
            first,
            tool_result_message("toolu_edit", "ok"),
            second,  # the turn stays open: no ResultMessage yet
            result_message(sid),
        ]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("edite")
    await wait_until(lambda: holds and holds[0].reached.is_set())
    await wait_until(lambda: session.summary()["plan"] == expected_plan(plan))
    plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")
    holds[0].release.set()
    await wait_until(lambda: holds[1].reached.is_set())
    await wait_until(lambda: session.summary()["plan"] == expected_plan(plan, done=2))

    updates = env.recorder.of(session.session_id, "session.updated")
    assert expected_plan(plan, done=2) in plan_of(updates)
    assert session.state != "idle"
    holds[1].release.set()
    await settle(session)


@pytest.mark.anyio
async def test_end_of_turn_refreshes_the_linked_plan(make_env, env_cleanup):
    holds: list[PauseStep] = []

    def turn(sid):
        pause = PauseStep()
        holds.append(pause)
        steps = use_turn(sid, "Read", plan)
        return [*steps[:-1], pause, steps[-1]]

    script, ids = by_session(turn)
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)

    await session.send("leia")
    await wait_until(lambda: holds and holds[0].reached.is_set())
    await wait_until(lambda: session.summary()["plan"] == expected_plan(plan))
    plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")  # someone else ticks the box
    assert session.summary()["plan"] == expected_plan(plan)  # still the cached one
    holds[0].release.set()
    await settle(session)

    assert session.summary()["plan"] == expected_plan(plan, done=2)
    updates = env.recorder.of(session.session_id, "session.updated")
    assert expected_plan(plan, done=2) in plan_of(updates)


@pytest.mark.anyio
async def test_plan_that_disappears_becomes_null_and_emits(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    assert await env.manager.refresh_plan(session.session_id) is True
    assert session.summary()["plan"] == expected_plan(plan)
    before = len(env.recorder.of(session.session_id, "session.updated"))

    plan.unlink()
    assert await env.manager.refresh_plan(session.session_id) is True

    assert session.summary()["plan"] is None
    assert len(env.recorder.of(session.session_id, "session.updated")) > before
    assert await env.manager.refresh_plan(session.session_id) is False


@pytest.mark.anyio
async def test_refresh_without_change_emits_nothing(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    assert await env.manager.refresh_plan(session.session_id) is True
    count = len(env.recorder.of(session.session_id, "session.updated"))

    assert await env.manager.refresh_plan(session.session_id) is False

    assert len(env.recorder.of(session.session_id, "session.updated")) == count


@pytest.mark.anyio
async def test_progress_change_reaches_every_session_on_the_same_plan(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    first, second = env.new_session(), env.new_session()
    for session in (first, second):
        env.manager.link_plan(session.session_id, str(plan), source="manual")
    await env.manager.refresh_plan(first.session_id)
    plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")

    await env.manager.refresh_plan(first.session_id)

    for session in (first, second):
        last = env.recorder.of(session.session_id, "session.updated")[-1]["data"]["plan"]
        assert last == expected_plan(plan, done=2)


# Link management ---------------------------------------------------------------


@pytest.mark.anyio
async def test_link_plan_validates_and_reports_change(make_env, env_cleanup, tmp_path):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    outside = write_plan(tmp_path / "outside")
    session = env.new_session()

    assert env.manager.link_plan(session.session_id, str(outside), source="manual") is False
    assert session.record.plan_path is None
    assert env.manager.link_plan(session.session_id, str(plan), source="auto") is True
    assert env.manager.link_plan(session.session_id, str(plan), source="auto") is False
    assert session.record.plan_link == "auto"
    assert env.manager.link_plan(session.session_id, str(plan), source="manual") is True
    assert session.record.plan_link == "manual"


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["auto", "manual"])
async def test_link_plan_refuses_a_relative_path(make_env, env_cleanup, monkeypatch, source):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    # The process runs inside a registered project: a relative path would resolve there.
    monkeypatch.chdir(env.project.path)
    relative = str(plan.relative_to(Path(env.project.path)))
    assert (Path(env.project.path) / relative).is_file()

    assert env.manager.link_plan(session.session_id, relative, source=source) is False
    assert env.manager.link_plan(session.session_id, "./" + relative, source=source) is False
    assert session.record.plan_path is None
    assert env.manager.link_plan(session.session_id, str(plan), source=source) is True


@pytest.mark.anyio
async def test_a_relative_path_is_never_the_linked_plan(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    monkeypatch.chdir(env.project.path)
    relative = str(plan.relative_to(Path(env.project.path)))

    assert session._on_linked_plan(str(plan)) is True
    assert session._on_linked_plan(relative) is False


@pytest.mark.anyio
async def test_auto_plan_keeps_the_path_and_unlink_clears_it(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")

    env.manager.auto_plan(session.session_id)
    assert (session.record.plan_path, session.record.plan_link) == (str(plan), "auto")

    env.manager.unlink_plan(session.session_id)
    assert (session.record.plan_path, session.record.plan_link) == (None, "off")
    row = session_row(env.db_path, session.session_id)
    assert (row["plan_path"], row["plan_link"]) == (None, "off")


@pytest.mark.anyio
async def test_project_roots_lists_registered_projects(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    assert env.manager.project_roots() == [Path(env.project.path)]


# Listings do not read plan files ------------------------------------------------


@pytest.mark.anyio
async def test_listings_never_read_plan_files(make_env, env_cleanup, monkeypatch):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    active = env.new_session()
    closed = env.manager.create_session(env.project)
    env.manager.link_plan(active.session_id, str(plan), source="manual")
    with closing(db.connect(env.db_path)) as conn:
        conn.execute(
            "UPDATE sessions SET plan_path = ?, plan_link = 'auto' WHERE session_id = ?",
            (str(plan), closed.session_id),
        )
    reads: list[Path] = []
    original = PlanCache.read

    def spy(self, path):
        reads.append(path)
        return original(self, path)

    monkeypatch.setattr(PlanCache, "read", spy)

    listed = {s["session_id"]: s for s in env.manager.list_sessions()}
    env.manager.search("nova")
    env.manager.list_for_project(env.project.id)
    env.manager.list_sessions(project_id=env.project.id)

    assert reads == []
    assert listed[active.session_id]["plan"] is None
    assert listed[closed.session_id]["plan"] is None

    await env.manager.refresh_plan(active.session_id)
    assert len(reads) == 1
    listed = {s["session_id"]: s for s in env.manager.list_sessions()}
    assert listed[active.session_id]["plan"] == expected_plan(plan)
    # The same plan linked to a closed session: from the memory cache, no file read.
    assert listed[closed.session_id]["plan"] == expected_plan(plan)
    assert len(reads) == 1


# Restart -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_link_survives_recreating_the_manager(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="auto")

    restarted = SessionManager(
        env.db_path, Recorder(), agent_factory=env.factory,
        history_exists=fake_history(env.factory),
    )
    env_cleanup.append(restarted)
    record = restarted.get(session.session_id).record

    assert (record.plan_path, record.plan_link) == (str(plan), "auto")
    assert restarted.get(session.session_id).summary()["plan"] is None
    assert await restarted.refresh_plan(session.session_id) is True
    assert restarted.get(session.session_id).summary()["plan"] == expected_plan(plan)


# API ---------------------------------------------------------------------------


def test_session_out_carries_the_plan_progress(home, data_dir):
    from fastapi.testclient import TestClient
    from test_sessions_api import APP_ORIGIN, BACKEND_URL
    from test_sessions_api import make_project as api_project

    from vibing.agent.fake import FakeAgentFactory
    from vibing.app import create_app
    from vibing.config import Settings

    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir), agent_factory=FakeAgentFactory()
    )
    headers = {"origin": APP_ORIGIN, "x-vibing": "1"}
    with TestClient(app, base_url=BACKEND_URL, headers=headers) as api:
        project = api_project(api, home)
        session = api.post(f"/api/projects/{project['id']}/sessions").json()
        assert session["plan"] is None
        plan = write_plan(home / "app")
        manager = app.state.sessions
        assert manager.link_plan(session["session_id"], str(plan), source="manual") is True
        assert api.get(f"/api/sessions/{session['session_id']}").json()["plan"] is None

        assert api.portal.call(manager.refresh_plan, session["session_id"]) is True

        listed = {s["session_id"]: s for s in api.get("/api/sessions").json()}
        assert listed[session["session_id"]]["plan"] == expected_plan(plan)
        one = api.get(f"/api/sessions/{session['session_id']}").json()
        assert one["plan"] == expected_plan(plan)
        assert "plan_path" not in one and "plan_link" not in one


# Cheap filter, failures, concurrency and cancellation ---------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/p/app/docs/superpowers/plans/x.md", True),
        ("/p/app/docs/superpowers/plans/X.MD", True),
        ("/p/app/docs/superpowers/plans/x.txt", False),
        ("/p/app/docs/superpowers/specs/x.md", False),
        ("/p/app/README.md", False),
        ("/p/app/main.py", False),
    ],
)
def test_looks_like_plan_path_is_a_cheap_textual_filter(path, expected):
    assert looks_like_plan_path(path) is expected


@pytest.mark.anyio
async def test_reads_of_other_files_do_not_touch_the_database_or_the_disk(make_env, env_cleanup):
    project = None

    def turn(sid):
        first = tool_turn(sid, tool_name="Read", tool_input={"file_path": f"{project}/main.py"})
        return first

    script, ids = by_session(
        turn,
        lambda sid: tool_turn(sid, tool_name="Edit", tool_input={"file_path": f"{project}/README.md"}),
    )
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    project = Path(env.project.path)
    session = env.new_session()
    ids.append(session.session_id)
    calls: list[int] = []
    original = env.manager.project_roots
    env.manager.project_roots = lambda: (calls.append(1), original())[1]

    await session.send("leia")
    await settle(session)
    await session.send("edite")
    await settle(session)

    assert calls == []
    assert session.record.plan_path is None


@pytest.mark.anyio
async def test_a_failure_linking_the_plan_does_not_break_the_turn(make_env, env_cleanup, caplog):
    script, ids = by_session(lambda sid: use_turn(sid, "Read", plan))
    env = make_env(script=script)
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    ids.append(session.session_id)

    def broken(session_id, path, *, source):
        raise RuntimeError("banco travado")

    env.manager.link_plan = broken

    await session.send("leia")
    await settle(session)

    assert session.state == "idle"
    assert session.error is None
    assert "Falha ao vincular o plano" in caplog.text


class BlockingRead:
    """`PlanCache.read` stand-in: each call reads the file at once (like the real
    one), then the first `blocked` calls wait for `release` before returning."""

    def __init__(self, cache: PlanCache, blocked: int = 1) -> None:
        self.cache = cache
        self.blocked = blocked
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, path):
        result = PlanCache.read(self.cache, path)
        with self._lock:
            self.calls += 1
            waits = self.calls <= self.blocked
        if waits:
            self.entered.set()
            assert self.release.wait(5)
        return result


@pytest.mark.anyio
async def test_concurrent_refreshes_of_a_plan_never_publish_an_older_summary(
    make_env, env_cleanup
):
    import asyncio

    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    gate = BlockingRead(env.manager.plan_cache)
    env.manager.plan_cache.read = gate  # type: ignore[method-assign]

    first = asyncio.create_task(env.manager.refresh_plan(session.session_id))
    await wait_until(gate.entered.is_set)  # it read the old text and is held
    plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")
    second = asyncio.create_task(env.manager.refresh_plan(session.session_id))
    await asyncio.sleep(0.05)  # the second one gets its chance to read and finish first
    gate.release.set()
    await asyncio.gather(first, second)

    assert session.summary()["plan"] == expected_plan(plan, done=2)
    assert env.manager.plan_summary(session.record) == expected_plan(plan, done=2)


@pytest.mark.anyio
async def test_close_cancels_pending_plan_refreshes(make_env, env_cleanup):
    env = make_env()
    env_cleanup.append(env.manager)
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    gate = BlockingRead(env.manager.plan_cache)
    env.manager.plan_cache.read = gate  # type: ignore[method-assign]
    session._schedule_plan_refresh()
    [task] = session._plan_tasks
    await wait_until(gate.entered.is_set)

    try:
        await session.close()
        await wait_until(task.done)
    finally:
        gate.release.set()

    assert task.cancelled()
    assert session._plan_tasks == set()
    assert env.manager.plan_summary(session.record) is None
