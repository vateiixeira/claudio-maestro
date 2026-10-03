"""Marco 6 (finishing): transcript reading, sync cost, migration, CLI watcher, git.

Transcripts are temporary `.jsonl` files; nothing touches the real SDK history.
"""

import asyncio
import json
import os
import time
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ToolUseBlock
from git_helpers import make_repo
from history_fakes import FakeHistory, info
from test_git_api import add_project, api, factory, spawn  # noqa: F401

from claudio_maestro import db, gitinfo, history
from claudio_maestro.cliwatch import DEFAULT_RELOAD_INTERVAL, CliWatcher
from claudio_maestro.conversation import ConversationBuilder, cap_items
from claudio_maestro.history import HistoryIndex, read_edits_file, read_transcript_file

# Taken before the autouse fixture replaces it with a stub.
from claudio_maestro.history import sdk_folder_signature as real_folder_signature
from claudio_maestro.history import sdk_read_transcript as real_read_transcript

# Transcript files ------------------------------------------------------------


def line(entry: dict[str, Any]) -> str:
    return json.dumps(entry) + "\n"


def user(uuid: str, parent: str | None, content: Any, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "uuid": uuid, "parentUuid": parent, "sessionId": "s",
            "message": {"role": "user", "content": content}, **extra}


def assistant(uuid: str, parent: str, block: dict[str, Any]) -> dict[str, Any]:
    return {"type": "assistant", "uuid": uuid, "parentUuid": parent, "sessionId": "s",
            "message": {"id": f"m-{uuid}", "role": "assistant", "content": [block]}}


def write_transcript(path: Path, *, tail: str = "") -> Path:
    edit = {"type": "tool_use", "id": "toolu_edit", "name": "Edit",
            "input": {"file_path": "/p/a.py", "old_string": "a", "new_string": "b"}}
    path.write_text(
        line(user("u1", None, "oi"))
        + line(assistant("a1", "u1", edit))
        + line(user("u2", "a1", [{"type": "tool_result", "tool_use_id": "toolu_edit",
                                  "content": "ok"}],
                    toolUseResult={"filePath": "/p/a.py", "structuredPatch": [
                        {"lines": [" x", "-a", "+b", "+c"]}]}))
        + "{isto não é json\n"
        + line(user("c1", "u2", "This session is being continued from a previous"
                    " conversation. Resumo.", isCompactSummary=True))
        + line(assistant("a2", "c1", {"type": "text", "text": "seguindo"}))
        + tail
    )
    return path


def test_transcript_is_read_in_one_pass(tmp_path, monkeypatch):
    path = write_transcript(tmp_path / "s.jsonl")
    opened: list[Path] = []
    original = Path.open

    def counting_open(self, *args, **kwargs):
        opened.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("read_text"))

    transcript = read_transcript_file(path)

    assert opened == [path]
    assert [m.uuid for m in transcript.messages] == ["u1", "a1", "u2", "c1", "a2"]
    assert transcript.skipped_lines == 1
    assert transcript.compact_uuids == {"c1"}
    assert transcript.tool_results["toolu_edit"]["content"] == "ok"
    assert transcript.tool_results["toolu_edit"]["details"]["filePath"] == "/p/a.py"


def test_partial_last_line_is_not_counted_as_corrupt(tmp_path):
    path = write_transcript(tmp_path / "s.jsonl", tail='{"type": "user", "uu')
    assert read_transcript_file(path).skipped_lines == 1


def test_clean_transcript_has_no_skipped_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(line(user("u1", None, "oi")))
    assert read_transcript_file(path).skipped_lines == 0


def test_read_transcript_at_missing_path_returns_none(tmp_path):
    assert history.read_transcript_at(tmp_path / "nao.jsonl") is None
    assert history.read_transcript_at(None) is None


def test_edits_are_read_from_the_whole_file(tmp_path):
    path = write_transcript(tmp_path / "s.jsonl")

    assert read_edits_file(path) == [
        {"tool_use_id": "toolu_edit", "name": "Edit", "file_path": "/p/a.py",
         "added": 2, "removed": 1},
    ]


def test_edit_without_result_has_no_counts(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text(line(assistant("a1", "u1", {
        "type": "tool_use", "id": "t1", "name": "NotebookEdit",
        "input": {"notebook_path": "/p/n.ipynb"}})))

    assert read_edits_file(path) == [
        {"tool_use_id": "t1", "name": "NotebookEdit", "file_path": "/p/n.ipynb",
         "added": None, "removed": None},
    ]


# Snapshot size -----------------------------------------------------------------


def test_cap_items_keeps_the_newest():
    items = [{"type": "user", "id": str(n), "text": "x" * 100} for n in range(10)]

    kept, cut = cap_items(items, 500)

    assert cut is True
    assert kept == items[-len(kept):]
    assert len(json.dumps(kept)) <= 500
    assert cap_items(items, 10_000_000) == (items, False)


def test_long_tool_input_strings_are_cut():
    builder = ConversationBuilder()
    builder.handle(AssistantMessage(
        content=[ToolUseBlock(id="t1", name="Write",
                              input={"file_path": "/a", "content": "y" * 30_000})],
        model="haiku", message_id="m1",
    ))

    tool = builder.items[0]
    assert tool.input["file_path"] == "/a"
    assert len(tool.input["content"]) < 20_100
    assert "cortado" in tool.input["content"]


# 6. Periodic sync only relists changed folders ----------------------------------


def make_index(tmp_path: Path, signatures: dict[str, Any]):
    db_path = tmp_path / "data" / "maestro.db"
    db.init_db(db_path)
    folder = tmp_path / "home" / "app"
    folder.mkdir(parents=True)
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES ('app', ?, '#ff8800', 0, 0)", (str(folder),),
        )
    fake = FakeHistory()
    fake.add(str(folder), info("s1", str(folder)))
    index = HistoryIndex(db_path, fake.list_sessions,
                         folder_signature=lambda directory: signatures.get(directory))
    return index, fake, folder, db_path


@pytest.mark.anyio
async def test_sync_skips_folders_whose_signature_did_not_change(tmp_path):
    signatures: dict[str, Any] = {}
    index, fake, folder, db_path = make_index(tmp_path, signatures)
    signatures[str(folder)] = (1, 1)

    await index.sync_all()
    await index.sync_all()
    assert fake.list_calls == [str(folder)]

    signatures[str(folder)] = (2, 1)
    await index.sync_all()
    assert fake.list_calls == [str(folder), str(folder)]
    with closing(db.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


@pytest.mark.anyio
async def test_sync_always_lists_without_signature(tmp_path):
    index, fake, folder, _ = make_index(tmp_path, {})

    await index.sync_all()
    await index.sync_all()

    assert fake.list_calls == [str(folder), str(folder)]


def test_folder_signature_changes_when_a_file_is_appended(tmp_path, monkeypatch):
    folder = tmp_path / "hist"
    folder.mkdir()
    file = folder / "s.jsonl"
    file.write_text("a\n")
    os.utime(file, (1_000, 1_000))
    monkeypatch.setattr(history, "_history_folder", lambda directory: folder)

    before = real_folder_signature("/x")
    with file.open("a") as handle:
        handle.write("b\n")
    os.utime(file, (2_000, 2_000))

    assert before is not None
    assert real_folder_signature("/x") != before


def test_folder_signature_missing_folder_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_history_folder", lambda directory: None)
    assert real_folder_signature("/x") is None


# 9. Names given before the marco 3 migration ------------------------------------


def test_migration_marks_titles_that_differ_from_automatic_ones(tmp_path):
    path = tmp_path / "v.db"
    with closing(db.connect(path)) as conn:
        for statements in db.MIGRATIONS[:2]:
            for statement in statements:
                conn.execute(statement)
        conn.execute("PRAGMA user_version = 2")
        conn.execute("INSERT INTO projects (id, name, path, color, position, created_at)"
                     " VALUES (1, 'p', '/p', '#fff', 0, 0)")
        rows = [
            ("renomeada", "Meu nome", "faça   o\nlogin", None),
            ("automatica", "faça o login", "faça   o\nlogin", None),
            ("pelo-resumo", "resumo aqui", None, "resumo aqui"),
            ("sem-dados", "Qualquer", None, None),
            ("nova", "Nova sessão", "algo", None),
            ("sem-titulo", "Sessão sem título", "algo", None),
        ]
        for sid, title, first_prompt, summary in rows:
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at, first_prompt, summary) VALUES (?, 1, '/p', ?, 0, 0, ?, ?)",
                (sid, title, first_prompt, summary),
            )

        db.migrate(conn)

        custom = {row["session_id"]: row["title_custom"]
                  for row in conn.execute("SELECT session_id, title_custom FROM sessions")}
    assert custom == {"renomeada": 1, "automatica": 0, "pelo-resumo": 0, "sem-dados": 0,
                      "nova": 0, "sem-titulo": 0}


def test_new_columns_exist_after_migration(tmp_path):
    path = tmp_path / "v.db"
    db.init_db(path)
    with closing(db.connect(path)) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    assert "app_modified_at" in columns
    assert "detached_at" in columns


# 12. CLI watcher ----------------------------------------------------------------


def test_reload_interval_is_one_second():
    assert DEFAULT_RELOAD_INTERVAL <= 1.0


@pytest.mark.anyio
async def test_watcher_reads_only_the_changed_session(tmp_path):
    from test_cliwatch import Env

    env = Env(tmp_path)
    env.fake.add(str(env.folder), info("s1", str(env.folder), modified_ms=1_700_000_000_000))
    await env.index.sync_all()
    calls: list[tuple[str, str]] = []

    def session_info(session_id, directory):
        calls.append((session_id, directory))
        return info(session_id, str(env.folder), custom_title="Novo nome",
                    modified_ms=1_700_000_500_000)

    watcher = CliWatcher(env.root, env.index, env.manager, first_delay=0.01, interval=0.05,
                         watch=env.watch, session_info=session_info,
                         on_processed=env.processed.append)
    env.fake.list_calls.clear()
    env.touch("s1", 1_700_000_500)
    task = asyncio.create_task(watcher.run())
    try:
        env.watch.push((1, env.file("s1")))
        deadline = time.monotonic() + 3
        while env.processed != ["s1"]:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.005)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await env.manager.shutdown()

    assert calls == [("s1", str(env.folder))]
    assert env.fake.list_calls == []
    with closing(db.connect(env.db_path)) as conn:
        title = conn.execute("SELECT title FROM sessions WHERE session_id = 's1'").fetchone()[0]
    assert title == "Novo nome"


# 11. Git: waiting for a slot and files that vanish ---------------------------------


@pytest.mark.anyio
async def test_waiting_for_a_git_slot_does_not_count_in_the_timeout(tmp_path):
    repo = make_repo(tmp_path / "r")
    slots = gitinfo._slots()
    for _ in range(gitinfo.MAX_GIT_PROCESSES):
        await slots.acquire()
    task = asyncio.create_task(gitinfo.repo_status(repo, timeout=0.3))
    await asyncio.sleep(0.5)
    for _ in range(gitinfo.MAX_GIT_PROCESSES):
        slots.release()

    status = await asyncio.wait_for(task, 5)

    assert status.error is None
    assert status.branch == "main"


@pytest.mark.anyio
async def test_git_operation_still_times_out_when_git_is_slow(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    original = gitinfo._exec_now

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await original(*args, **kwargs)

    monkeypatch.setattr(gitinfo, "_exec_now", slow)
    with pytest.raises(gitinfo.GitError, match="tempo limite"):
        await gitinfo.file_diff(repo, "README.md", timeout=0.3)


@pytest.mark.anyio
async def test_diff_of_file_that_vanishes_raises_file_gone(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    (repo / "novo.txt").write_text("x\n")
    original = gitinfo.run_git

    async def vanishing(repo_path, *args, **kwargs):
        if "--no-index" in args:
            (repo / "novo.txt").unlink(missing_ok=True)
        return await original(repo_path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", vanishing)
    with pytest.raises(gitinfo.FileGoneError):
        await gitinfo.file_diff(repo, "novo.txt")


def test_diff_route_answers_404_for_vanished_file(api, home, monkeypatch):  # noqa: F811
    root = home / "proj"
    make_repo(root)
    (root / "novo.txt").write_text("x\n")
    project = add_project(api, root)

    async def gone(repo, file, **kwargs):
        raise gitinfo.FileGoneError("O arquivo não existe mais.")

    monkeypatch.setattr(gitinfo, "file_diff", gone)
    response = api.get(f"/api/projects/{project['id']}/diff",
                       params={"repo": str(root), "file": "novo.txt"})

    assert response.status_code == 404
    assert response.json()["detail"] == "O arquivo não existe mais."


# 10. Session changes beyond the loaded history -------------------------------------


def test_session_changes_include_edits_outside_the_snapshot(api, home, monkeypatch):  # noqa: F811
    root = home / "proj"
    make_repo(root)
    (root / "velho.py").write_text("v\n")
    (root / "README.md").write_text("mudou\n")
    project = add_project(api, root)
    sid = api.post(f"/api/projects/{project['id']}/sessions").json()["session_id"]
    manager = api.app.state.sessions

    async def fake_open(session_id):
        return {"items": [{
            "type": "tool", "name": "Edit", "tool_use_id": "t2",
            "input": {"file_path": str(root / "README.md")},
            "result": {"details": {"structuredPatch": [{"lines": ["-linha 1", "+mudou"]}]}},
        }]}

    async def fake_edits(session_id):
        return [
            {"tool_use_id": "t1", "name": "Write", "file_path": str(root / "velho.py"),
             "added": 1, "removed": 0},
            {"tool_use_id": "t2", "name": "Edit", "file_path": str(root / "README.md"),
             "added": 1, "removed": 1},
        ]

    monkeypatch.setattr(manager, "open", fake_open)
    monkeypatch.setattr(manager, "transcript_edits", fake_edits)
    (group,) = api.get(f"/api/sessions/{sid}/changes").json()["repos"]
    files = {f["rel_path"]: (f["added"], f["removed"]) for f in group["files"]}

    assert files == {"README.md": (1, 1), "velho.py": (1, 0)}


@pytest.mark.parametrize("failure", ["missing", "raises"])
def test_sdk_read_transcript_falls_back_to_public_functions(monkeypatch, failure):
    from history_fakes import user_entry
    if failure == "missing":
        monkeypatch.setattr(history, "_session_file", lambda sid, d: None)
    else:
        def broken(sid, d):
            raise RuntimeError("mudou")

        monkeypatch.setattr(history, "_session_file", broken)
    monkeypatch.setattr(history, "sdk_get_session_messages",
                        lambda sid, d: [user_entry("oi", sid)])
    monkeypatch.setattr(history, "sdk_read_tool_results", lambda sid, d: {"t": {"content": 1}})

    transcript = real_read_transcript("s", "/p")

    assert [m.message["content"] for m in transcript.messages] == ["oi"]
    assert transcript.tool_results == {"t": {"content": 1}}
