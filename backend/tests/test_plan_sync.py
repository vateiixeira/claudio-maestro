"""Plan link from the CLI watcher and from resumed history, and the periodic sweep.

Nothing here starts the `claude` process or touches the real SDK.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from history_fakes import assistant_entry, info, user_entry
from test_cliwatch import Env as CliEnv
from test_cliwatch import wait_until as wait_until_real
from test_plan_sessions import PLAN_DONE_TEXT, expected_plan, plan_of, write_plan
from watchfiles import Change

from vibing.agent.fake import FakeAgentFactory
from vibing.app import create_app
from vibing.config import Settings
from vibing.plans import read_new_lines, scan_plan_refs
from vibing.sessions import SessionManager

BACKEND_URL = "http://127.0.0.1:6660"
HEADERS = {"origin": "http://localhost:6600", "x-vibing": "1"}


def tool_line(name: str, path: str, *, sidechain: bool = False, block_type: str = "tool_use") -> str:
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain,
        "message": {"content": [
            {"type": block_type, "id": "t", "name": name, "input": {"file_path": path}}
        ]},
    })


# scan_plan_refs ----------------------------------------------------------------


def test_scan_returns_the_last_plan_tool_path():
    lines = [
        tool_line("Read", "/p/docs/superpowers/plans/a.md"),
        "{ quebrada",
        tool_line("Bash", "/p/docs/superpowers/plans/ignored.md"),
        tool_line("Edit", "/p/docs/superpowers/plans/b.md", sidechain=True),
        json.dumps({"type": "user", "message": {"content": "tool_use"}}),
    ]

    assert scan_plan_refs(lines) == "/p/docs/superpowers/plans/b.md"


def test_scan_skips_later_calls_on_files_that_are_not_plans():
    lines = [
        tool_line("Read", "/p/docs/superpowers/plans/a.md"),
        tool_line("Edit", "/p/backend/app.py"),
        tool_line("Read", "/p/docs/notes.md"),
    ]

    assert scan_plan_refs(lines) == "/p/docs/superpowers/plans/a.md"


def test_scan_without_references_returns_none():
    assert scan_plan_refs([]) is None
    assert scan_plan_refs(["", "[]", '{"tool_use": 1}', tool_line("Grep", "/x.md")]) is None
    assert scan_plan_refs([tool_line("Read", "/x.md", block_type="tool_result")]) is None


def test_scan_ignores_blocks_with_a_bad_shape():
    bad = json.dumps({"message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": 3}},
        {"type": "tool_use", "name": "Read", "input": "x"},
        "text",
    ]}})

    assert scan_plan_refs([bad, '"tool_use"', '{"message": 1, "x": "tool_use"}']) is None


# read_new_lines ----------------------------------------------------------------


def test_read_new_lines_reads_only_complete_new_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"um\ndois\ntres\n")

    lines, offset = read_new_lines(path, None)
    assert lines == ["um", "dois", "tres"]
    assert offset == len(b"um\ndois\ntres\n")

    with path.open("ab") as file:
        file.write(b"quatro\ncinco")
    lines, offset2 = read_new_lines(path, offset)
    assert lines == ["quatro"]
    assert offset2 == offset + len(b"quatro\n")

    with path.open("ab") as file:
        file.write(b" e meio\n")
    assert read_new_lines(path, offset2) == (["cinco e meio"], offset2 + len(b"cinco e meio\n"))
    assert read_new_lines(path, offset2 + len(b"cinco e meio\n"))[0] == []


def test_read_new_lines_truncated_file_rereads_the_tail(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"a\nb\nc\n")
    _, offset = read_new_lines(path, None)

    path.write_bytes(b"x\n")
    assert read_new_lines(path, offset) == (["x"], 2)


def test_read_new_lines_large_file_reads_only_the_tail_without_the_partial_line(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"0123456789\nabcdefghij\nklmnopqrst\n")

    lines, offset = read_new_lines(path, None, tail=15)

    assert lines == ["klmnopqrst"]
    assert offset == path.stat().st_size


def test_read_new_lines_tail_starting_on_a_line_boundary_keeps_the_first_line(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"0123456789\nabcdefghij\n")

    lines, _ = read_new_lines(path, None, tail=11)

    assert lines == ["abcdefghij"]


def test_read_new_lines_empty_and_unterminated_files(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_bytes(b"")
    assert read_new_lines(path, None) == ([], 0)
    path.write_bytes(b"parcial")
    assert read_new_lines(path, None) == ([], 0)
    assert read_new_lines(path, 0) == ([], 0)


# CLI watcher -------------------------------------------------------------------


@pytest.fixture
async def cli(tmp_path: Path):
    env = CliEnv(tmp_path)
    yield env
    if env.task is not None:
        env.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await env.task
    await env.manager.shutdown()


def append_line(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


async def process(env: CliEnv, session_id: str, mtime: float) -> None:
    """One watcher pass over the session file, waiting for it to finish."""
    done = len(env.processed)
    os.utime(env.file(session_id), (mtime, mtime))
    env.watch.push((Change.modified, env.file(session_id)))
    await wait_until_real(lambda: len(env.processed) > done)


async def index_session(env: CliEnv, session_id: str = "s1") -> Path:
    env.fake.add(str(env.folder), info(session_id, str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    env.events.clear()
    return env.file(session_id)


@pytest.mark.anyio
async def test_cli_change_with_a_plan_read_links_the_session(cli):
    plan = write_plan(cli.folder)
    path = await index_session(cli)
    path.write_text(tool_line("Read", str(plan)) + "\n", encoding="utf-8")
    cli.start()

    await process(cli, "s1", 1_700_000_500)

    await wait_until_real(lambda: cli.manager.plan_summary(cli.manager.get("s1").record) is not None)
    record = cli.manager.get("s1").record
    assert (record.plan_path, record.plan_link) == (str(plan), "auto")
    updates = [e for e in cli.events if e["type"] == "session.updated"]
    assert expected_plan(plan) in plan_of(updates)
    assert updates[-1]["data"]["plan"] == expected_plan(plan)


@pytest.mark.anyio
async def test_cli_second_change_reads_only_the_new_lines(cli, monkeypatch):
    plan = write_plan(cli.folder)
    path = await index_session(cli)
    path.write_text(tool_line("Read", str(plan)) + "\n", encoding="utf-8")
    calls: list[int | None] = []
    real = read_new_lines

    def spy(file: Path, offset: int | None, **kwargs: Any):
        calls.append(offset)
        return real(file, offset, **kwargs)

    monkeypatch.setattr("vibing.cliwatch.read_new_lines", spy)
    cli.start()
    await process(cli, "s1", 1_700_000_500)
    first_size = path.stat().st_size

    append_line(path, json.dumps({"type": "user", "message": {"content": "oi"}}))
    await process(cli, "s1", 1_700_000_600)

    assert calls == [None, first_size]
    assert cli.manager.get("s1").record.plan_path == str(plan)


@pytest.mark.anyio
async def test_cli_edit_of_the_linked_plan_refreshes_its_progress(cli):
    plan = write_plan(cli.folder)
    path = await index_session(cli)
    path.write_text(tool_line("Read", str(plan)) + "\n", encoding="utf-8")
    cli.start()
    await process(cli, "s1", 1_700_000_500)
    await wait_until_real(lambda: cli.manager.plan_summary(cli.manager.get("s1").record) is not None)

    plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")
    append_line(path, tool_line("Edit", str(plan)))
    await process(cli, "s1", 1_700_000_600)

    await wait_until_real(lambda: cli.manager.plan_summary(cli.manager.get("s1").record)["done"] == 2)
    assert cli.manager.plan_summary(cli.manager.get("s1").record) == expected_plan(plan, done=2)


@pytest.mark.anyio
async def test_cli_reference_outside_a_project_or_manual_link_is_not_linked(cli, tmp_path):
    outside = write_plan(tmp_path / "other", "o.md")
    mine = write_plan(cli.folder, "mine.md")
    path = await index_session(cli)
    path.write_text(tool_line("Read", str(outside)) + "\n", encoding="utf-8")
    cli.start()

    await process(cli, "s1", 1_700_000_500)
    assert cli.manager.get("s1").record.plan_path is None

    cli.manager.get("s1").save(plan_link="off")
    append_line(path, tool_line("Read", str(mine)))
    await process(cli, "s1", 1_700_000_600)
    assert cli.manager.get("s1").record.plan_path is None


@pytest.mark.anyio
async def test_cli_change_without_references_never_loads_the_session(cli):
    path = await index_session(cli)
    path.write_text(json.dumps({"type": "user", "message": {"content": "oi"}}) + "\n")
    cli.start()

    await process(cli, "s1", 1_700_000_500)

    assert "s1" not in cli.manager.active_ids()


@pytest.mark.anyio
async def test_cli_plan_failure_does_not_break_the_pass(cli, monkeypatch):
    plan = write_plan(cli.folder)
    path = await index_session(cli)
    path.write_text(tool_line("Read", str(plan)) + "\n", encoding="utf-8")

    def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("falha")

    monkeypatch.setattr("vibing.cliwatch.scan_plan_refs", boom)
    cli.start()

    await process(cli, "s1", 1_700_000_500)

    assert cli.processed == ["s1"]
    assert [e for e in cli.events if e["type"] == "session.updated"]


@pytest.mark.anyio
async def test_cli_forgets_the_offset_when_the_file_is_gone(cli):
    path = await index_session(cli)
    path.write_text(json.dumps({"type": "user", "message": {"content": "oi"}}) + "\n")
    cli.start()
    await process(cli, "s1", 1_700_000_500)
    assert "s1" in cli.watcher._plan_offsets

    path.unlink()
    cli.watch.push((Change.deleted, path))
    await wait_until_real(lambda: len(cli.processed) > 1)

    assert "s1" not in cli.watcher._plan_offsets


# Resumed history ---------------------------------------------------------------


def plan_read_entry(plan: Path, message_id: str, name: str = "Read", session_id: str = "s1"):
    return assistant_entry(
        {"type": "tool_use", "id": f"tu-{message_id}", "name": name,
         "input": {"file_path": str(plan)}},
        message_id, session_id,
    )


@pytest.mark.anyio
async def test_opening_a_session_links_the_last_plan_in_its_history(cli):
    first = write_plan(cli.folder, "first.md")
    second = write_plan(cli.folder, "second.md", PLAN_DONE_TEXT)
    await index_session(cli)
    cli.fake.messages["s1"] = [
        user_entry("execute", "s1"),
        plan_read_entry(first, "m1"),
        plan_read_entry(second, "m2", "Edit"),
        plan_read_entry(cli.folder / "app.py", "m3", "Edit"),
    ]

    await cli.manager.open("s1")

    record = cli.manager.get("s1").record
    assert (record.plan_path, record.plan_link) == (str(second), "auto")
    await wait_until_real(lambda: cli.manager.plan_summary(record) is not None)
    assert cli.manager.plan_summary(record)["done"] == 2
    assert expected_plan(second, done=2) in plan_of(
        [e for e in cli.events if e["type"] == "session.updated"]
    )


@pytest.mark.anyio
async def test_opening_respects_manual_and_off_links(cli):
    mine = write_plan(cli.folder, "mine.md")
    other = write_plan(cli.folder, "other.md")
    await index_session(cli)
    cli.manager.get("s1").save(plan_path=str(mine), plan_link="manual")
    cli.fake.messages["s1"] = [plan_read_entry(other, "m1")]

    await cli.manager.open("s1")

    record = cli.manager.get("s1").record
    assert (record.plan_path, record.plan_link) == (str(mine), "manual")


@pytest.mark.anyio
async def test_opening_scans_the_whole_history_even_when_it_is_truncated(cli):
    plan = write_plan(cli.folder)
    await index_session(cli)
    cli.manager.get("s1")._history_limit = 2
    cli.fake.messages["s1"] = [
        plan_read_entry(plan, "m0"),
        *[user_entry(f"msg {i}", "s1", uuid=f"u{i}") for i in range(5)],
    ]

    await cli.manager.open("s1")

    assert cli.manager.get("s1").record.plan_path == str(plan)


@pytest.mark.anyio
async def test_opening_a_session_already_linked_reads_no_plan(cli, monkeypatch):
    plan = write_plan(cli.folder)
    await index_session(cli)
    cli.manager.get("s1").save(plan_path=str(plan), plan_link="auto")
    cli.fake.messages["s1"] = [user_entry("oi", "s1"), plan_read_entry(plan, "m1")]
    reads = spy_reads(cli.manager, monkeypatch)

    await cli.manager.open("s1")
    await asyncio.sleep(0.05)

    assert reads == []  # the sweep, not the open, warms the cache of an existing link


# Sweep -------------------------------------------------------------------------


class Rounds:
    """Injected `sleep`: runs one hook after each round and stops after the last."""

    def __init__(self, *hooks) -> None:
        self.hooks = list(hooks)
        self.count = 0

    async def __call__(self, interval: float) -> None:
        self.count += 1
        if not self.hooks:
            raise asyncio.CancelledError
        hook = self.hooks.pop(0)
        if hook is not None:
            hook()


async def run_sweep(manager: SessionManager, *hooks) -> Rounds:
    rounds = Rounds(*hooks)
    with pytest.raises(asyncio.CancelledError):
        await manager.run_plan_sweep(30, sleep=rounds)
    return rounds


def spy_reads(manager: SessionManager, monkeypatch) -> list[Path]:
    reads: list[Path] = []
    real = manager.plan_cache.read

    def read(path: Path):
        reads.append(path)
        return real(path)

    monkeypatch.setattr(manager.plan_cache, "read", read)
    return reads


@pytest.fixture
def sweep_env(tmp_path: Path):
    from test_sessions import Env

    def build() -> Env:
        return Env(tmp_path, FakeAgentFactory())

    return build


@pytest.mark.anyio
async def test_sweep_reads_each_plan_once_and_skips_finished_sessions(sweep_env, monkeypatch):
    env = sweep_env()
    live = write_plan(Path(env.project.path), "live.md")
    done = write_plan(Path(env.project.path), "done.md")
    a, b, finished = env.new_session(), env.new_session(), env.new_session()
    env.manager.link_plan(a.session_id, str(live), source="manual")
    env.manager.link_plan(b.session_id, str(live), source="manual")
    env.manager.link_plan(finished.session_id, str(done), source="manual")
    finished.save(finished=True, finished_at=int(time.time()))
    reads = spy_reads(env.manager, monkeypatch)
    env.recorder.envelopes.clear()

    rounds = await run_sweep(env.manager, None)

    assert rounds.count == 2
    # Two rounds, one read of the shared plan per round, none of the finished one's.
    assert reads == [live, live]
    for session in (a, b):
        assert session.summary()["plan"] == expected_plan(live)
        assert len(env.recorder.of(session.session_id, "session.updated")) == 1
    assert finished.summary()["plan"] is None
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_skips_sessions_finished_by_inactivity(sweep_env, monkeypatch):
    env = sweep_env()
    plan = write_plan(Path(env.project.path))
    stale = env.new_session()
    env.manager.link_plan(stale.session_id, str(plan), source="manual")
    stale.save(last_activity_at=int(time.time()) - 30 * 24 * 3600)
    reads = spy_reads(env.manager, monkeypatch)

    await run_sweep(env.manager, None)

    assert reads == []
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_announces_a_plan_that_changed_between_rounds(sweep_env):
    env = sweep_env()
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")

    def edit() -> None:
        plan.write_text(PLAN_DONE_TEXT, encoding="utf-8")
        stat = plan.stat()
        os.utime(plan, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        env.recorder.envelopes.clear()

    await run_sweep(env.manager, None, edit, None)

    updates = env.recorder.of(session.session_id, "session.updated")
    assert plan_of(updates) == [expected_plan(plan, done=2)]
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_turns_a_deleted_plan_into_null_without_failing(sweep_env):
    env = sweep_env()
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")

    def delete() -> None:
        plan.unlink()
        env.recorder.envelopes.clear()

    await run_sweep(env.manager, None, delete, None)

    assert plan_of(env.recorder.of(session.session_id, "session.updated")) == [None]
    assert session.summary()["plan"] is None
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_survives_failures_and_keeps_going(sweep_env, monkeypatch, caplog):
    env = sweep_env()
    bad = write_plan(Path(env.project.path), "bad.md")
    good = write_plan(Path(env.project.path), "good.md")
    one, two = env.new_session(), env.new_session()
    env.manager.link_plan(one.session_id, str(bad), source="manual")
    env.manager.link_plan(two.session_id, str(good), source="manual")
    real = env.manager.plan_cache.read

    def flaky(path: Path):
        if path == bad:
            raise RuntimeError("leitura falhou")
        return real(path)

    monkeypatch.setattr(env.manager.plan_cache, "read", flaky)

    rounds = await run_sweep(env.manager, None, None)

    assert rounds.count == 3
    assert two.summary()["plan"] == expected_plan(good)
    assert "leitura falhou" in caplog.text
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_survives_a_failing_database_read(sweep_env, monkeypatch):
    env = sweep_env()
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    calls = {"n": 0}
    real = env.manager._sweepable_plan_paths

    def flaky() -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("banco indisponível")
        return real()

    monkeypatch.setattr(env.manager, "_sweepable_plan_paths", flaky)

    await run_sweep(env.manager, None, None)

    assert session.summary()["plan"] == expected_plan(plan)
    await env.manager.shutdown()


@pytest.mark.anyio
async def test_sweep_does_not_load_database_only_sessions_into_memory(sweep_env):
    env = sweep_env()
    plan = write_plan(Path(env.project.path))
    session = env.new_session()
    env.manager.link_plan(session.session_id, str(plan), source="manual")
    env.manager._sessions.pop(session.session_id)

    await run_sweep(env.manager, None)

    assert session.session_id not in env.manager.active_ids()
    record = env.manager.get(session.session_id).record
    assert env.manager.plan_summary(record) == expected_plan(plan)
    await env.manager.shutdown()


# Lifespan ----------------------------------------------------------------------


@pytest.fixture
def sweep_calls(monkeypatch) -> list[float]:
    calls: list[float] = []

    async def fake_sweep(self, interval, sleep=asyncio.sleep):
        calls.append(interval)
        await asyncio.Event().wait()

    async def no_models(self, interval, sleep=asyncio.sleep):
        await asyncio.Event().wait()

    monkeypatch.setattr(SessionManager, "run_plan_sweep", fake_sweep)
    monkeypatch.setattr(SessionManager, "run_models_refresh", no_models)
    return calls


def settings(home: Path, data_dir: Path) -> Settings:
    return Settings(home_dir=home, data_dir=data_dir, plan_sweep_interval_seconds=7)


def test_settings_default_sweep_interval_is_30_seconds(home, data_dir):
    assert Settings(home_dir=home, data_dir=data_dir).plan_sweep_interval_seconds == 30


def test_lifespan_skips_the_sweep_with_a_fake_factory(home, data_dir, sweep_calls):
    app = create_app(settings=settings(home, data_dir), agent_factory=FakeAgentFactory())
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        pass
    assert sweep_calls == []


def test_lifespan_starts_the_sweep_when_asked(home, data_dir, sweep_calls):
    app = create_app(
        settings=settings(home, data_dir), agent_factory=FakeAgentFactory(), plan_sweep=True
    )
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        deadline = time.monotonic() + 3
        while not sweep_calls and time.monotonic() < deadline:
            time.sleep(0.01)
    assert sweep_calls == [7]


def test_lifespan_starts_the_sweep_with_the_real_agent_by_default(home, data_dir, sweep_calls):
    app = create_app(settings=settings(home, data_dir))
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        deadline = time.monotonic() + 3
        while not sweep_calls and time.monotonic() < deadline:
            time.sleep(0.01)
    assert sweep_calls == [7]


def test_lifespan_sweep_can_be_turned_off(home, data_dir, sweep_calls):
    app = create_app(settings=settings(home, data_dir), plan_sweep=False)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS):
        time.sleep(0.1)
    assert sweep_calls == []
