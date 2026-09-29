"""History index: sync from the SDK's `list_sessions`, repositories inside the project."""

import os
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from history_fakes import FakeHistory, info

from vibing import db
from vibing.history import HistoryIndex, find_repositories, session_title


def add_project(db_path: Path, folder: Path, name: str = "app") -> int:
    folder.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(db_path)) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES (?, ?, '#ff8800', 0, 0)",
            (name, str(folder)),
        )
        return cursor.lastrowid


def rows(db_path: Path) -> dict[str, dict[str, Any]]:
    with closing(db.connect(db_path)) as conn:
        return {
            row["session_id"]: dict(row)
            for row in conn.execute("SELECT * FROM sessions").fetchall()
        }


@pytest.fixture
def env(tmp_path: Path):
    db_path = tmp_path / "data" / "vibing.db"
    db.init_db(db_path)
    fake = FakeHistory()
    changed: list[set[str]] = []
    index = HistoryIndex(db_path, fake.list_sessions, on_change=changed.append)
    return db_path, fake, index, changed, tmp_path / "home"


# Titles --------------------------------------------------------------------


def test_title_prefers_custom_then_first_prompt_then_summary():
    assert session_title(info("a", "/x", custom_title="Meu", summary="Resumo")) == "Meu"
    assert session_title(info("a", "/x", summary="Resumo", first_prompt="p")) == "p"
    assert session_title(info("a", "/x", summary="Resumo")) == "Resumo"
    long = "palavra " * 30
    title = session_title(info("a", "/x", first_prompt=long))
    assert len(title) <= 80 and title.startswith("palavra palavra")
    assert session_title(info("a", "/x")) == "Sessão sem título"


# Sync ----------------------------------------------------------------------


@pytest.mark.anyio
async def test_sync_inserts_sessions_seen_and_in_seconds(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    project_id = add_project(db_path, folder)
    fake.add(str(folder), info(
        "s1", str(folder), summary="Resumo", first_prompt="Faça X",
        created_ms=1_700_000_000_000, modified_ms=1_700_000_100_500,
    ))

    await index.sync_all()

    row = rows(db_path)["s1"]
    assert row["project_id"] == project_id
    assert row["cwd"] == str(folder)
    assert row["title"] == "Faça X"
    assert row["summary"] == "Resumo"
    assert row["first_prompt"] == "Faça X"
    assert row["created_at"] == 1_700_000_000
    assert row["last_activity_at"] == 1_700_000_100
    assert row["last_seen_at"] == 1_700_000_100
    assert row["file_modified_at"] == 1_700_000_100
    assert row["finished"] == 0
    assert changed and "s1" in changed[-1]


@pytest.mark.anyio
async def test_sync_is_idempotent(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder), summary="A"), info("s2", str(folder), summary="B"))

    await index.sync_all()
    first = rows(db_path)
    await index.sync_all()

    assert rows(db_path) == first
    assert len(first) == 2


@pytest.mark.anyio
async def test_sync_preserves_app_title_finished_and_seen(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder), summary="Antigo", modified_ms=1_000_000_000))
    await index.sync_all()
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "UPDATE sessions SET title = 'Renomeada', title_custom = 1, finished = 1,"
            " last_seen_at = 5 WHERE session_id = 's1'"
        )
    fake.by_directory[str(folder)] = [
        info("s1", str(folder), summary="Novo resumo", modified_ms=2_000_000_000)
    ]

    await index.sync_all()

    row = rows(db_path)["s1"]
    assert row["title"] == "Renomeada"
    assert row["summary"] == "Novo resumo"
    assert row["finished"] == 1
    assert row["last_seen_at"] == 5
    assert row["last_activity_at"] == 2_000_000


@pytest.mark.anyio
async def test_sync_keeps_title_unless_new_custom_title(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder), first_prompt="primeiro", summary="p1"))
    await index.sync_all()
    assert rows(db_path)["s1"]["title"] == "primeiro"
    # In SDK 0.2.161 `summary` may be the last prompt: it changes every turn.
    fake.by_directory[str(folder)] = [info("s1", str(folder), first_prompt="primeiro", summary="p2")]
    await index.sync_all()
    assert rows(db_path)["s1"]["title"] == "primeiro"

    fake.by_directory[str(folder)] = [
        info("s1", str(folder), first_prompt="primeiro", summary="p3", custom_title="Do CLI")
    ]
    await index.sync_all()
    assert rows(db_path)["s1"]["title"] == "Do CLI"


@pytest.mark.anyio
async def test_sync_truncates_summary_and_first_prompt(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder), first_prompt="a" * 2000, summary="b" * 2000))

    await index.sync_all()

    row = rows(db_path)["s1"]
    assert len(row["summary"]) == 500 and len(row["first_prompt"]) == 500
    assert len(row["title"]) <= 80


@pytest.mark.anyio
async def test_sync_failure_in_one_project_does_not_stop_others(env):
    db_path, fake, index, changed, home = env
    bad, good = home / "bad", home / "good"
    add_project(db_path, bad, "bad")
    good_id = add_project(db_path, good, "good")
    fake.failing.add(str(bad))
    fake.add(str(good), info("s1", str(good), summary="ok"))

    await index.sync_all()

    assert rows(db_path)["s1"]["project_id"] == good_id


@pytest.mark.anyio
async def test_sync_project_only_lists_that_project(env):
    db_path, fake, index, changed, home = env
    a = add_project(db_path, home / "a", "a")
    add_project(db_path, home / "b", "b")

    await index.sync_project(a)

    assert fake.list_calls == [str(home / "a")]


@pytest.mark.anyio
async def test_missing_project_folder_is_skipped(env):
    db_path, fake, index, changed, home = env
    folder = home / "gone"
    add_project(db_path, folder)
    folder.rmdir()

    await index.sync_all()

    assert fake.list_calls == []


# Repositories inside the project ------------------------------------------


def make_repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


def test_find_repositories_depth_and_ignored_folders(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    a = make_repo(root / "a")
    deep = make_repo(root / "x" / "y" / "z")
    make_repo(root / "x" / "y" / "z" / "w" / "too-deep")
    make_repo(root / "node_modules" / "lib")
    make_repo(root / ".hidden" / "repo")
    make_repo(root / "vendor" / "dep")
    make_repo(root / "build" / "out")
    nested = make_repo(root / "a" / "sub")

    found = find_repositories(root)

    assert sorted(found) == sorted([a, deep, nested])


@pytest.mark.anyio
async def test_sessions_of_subrepositories_keep_their_cwd(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    project_id = add_project(db_path, folder)
    repo = make_repo(folder / "api")
    make_repo(folder / "node_modules" / "pkg")
    fake.add(str(repo), info("s1", str(repo), summary="no repo"))
    fake.add(str(folder / "node_modules" / "pkg"), info("s2", "x", summary="ignorada"))

    await index.sync_all()

    found = rows(db_path)
    assert found["s1"]["project_id"] == project_id
    assert found["s1"]["cwd"] == str(repo)
    assert "s2" not in found
    assert str(folder / "node_modules" / "pkg") not in fake.list_calls


@pytest.mark.anyio
async def test_session_belongs_to_most_specific_project(env):
    db_path, fake, index, changed, home = env
    outer = home / "outer"
    add_project(db_path, outer, "outer")
    repo = make_repo(outer / "inner")
    inner_id = add_project(db_path, repo, "inner")
    fake.add(str(repo), info("s1", str(repo), summary="x"))

    await index.sync_all()
    assert rows(db_path)["s1"]["project_id"] == inner_id

    # Syncing only the outer project keeps it in the inner one.
    outer_id = rows(db_path)["s1"]["project_id"]
    with closing(db.connect(db_path)) as conn:
        outer_pid = conn.execute("SELECT id FROM projects WHERE name='outer'").fetchone()[0]
    await index.sync_project(outer_pid)
    assert rows(db_path)["s1"]["project_id"] == outer_id == inner_id


# Raw transcript reading ----------------------------------------------------


def test_read_tool_results_file_takes_every_branch(tmp_path: Path):
    import json

    from vibing.history import read_tool_results_file

    lines = [
        {"type": "assistant", "uuid": "a", "message": {"content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
        {"type": "user", "uuid": "b", "parentUuid": "a", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "um", "is_error": False}]},
         "toolUseResult": {"stdout": "um"}},
        {"type": "user", "uuid": "c", "parentUuid": "x", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "dois", "is_error": True}]},
         "toolUseResult": "Error: texto"},
    ]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n{quebrada\n")

    results = read_tool_results_file(path)

    assert results == {
        "t1": {"content": "um", "is_error": False, "details": {"stdout": "um"}},
        "t2": {"content": "dois", "is_error": True, "details": None},
    }


def test_repository_scan_is_capped(tmp_path: Path, caplog):
    root = tmp_path / "many"
    for n in range(60):
        make_repo(root / f"r{n:02d}")

    found = find_repositories(root)

    assert len(found) == 50
    assert "50" in caplog.text


def test_tests_never_reach_the_real_sdk():
    from vibing import history, sessions

    assert history.sdk_list_sessions("/x") == []
    assert history.sdk_get_session_messages("s", "/x") == []
    assert history.sdk_read_tool_results("s", "/x") == {}
    assert history.sdk_session_file_mtime("s", "/x") is None
    assert history.sdk_session_file_exists("s", "/x") is None
    assert sessions.sdk_history_exists("s", "/x") is False
    with pytest.raises(RuntimeError):
        sessions.default_agent_factory(None)


def test_read_tool_results_file_omits_images_and_caps_while_reading(tmp_path: Path):
    import json

    from vibing.conversation import CONTENT_LIMIT
    from vibing.history import read_tool_results_file

    big = "x" * (CONTENT_LIMIT + 10)
    line = {"type": "user", "uuid": "b", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
            {"type": "text", "text": big},
        ]}]}}
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(line) + "\n")

    content = read_tool_results_file(path)["t1"]["content"]

    assert "AAAA" not in json.dumps(content)
    assert content[0].get("omitted") is True
    assert len(content[1]["text"]) <= CONTENT_LIMIT + 100


# Review fixes ----------------------------------------------------------------


@pytest.mark.anyio
async def test_session_outside_registered_projects_is_dropped(env):
    """`my_app` is not inside `my-app`, even if the SDK folder names coincide."""
    db_path, fake, index, changed, home = env
    folder = home / "my-app"
    add_project(db_path, folder)
    other = home / "my_app"
    other.mkdir(parents=True)
    fake.add(str(folder), info("inside", str(folder)), info("outside", str(other)))

    await index.sync_all()

    assert set(rows(db_path)) == {"inside"}


@pytest.mark.anyio
async def test_sync_reports_changed_projects(tmp_path: Path):
    db_path = tmp_path / "data" / "vibing.db"
    db.init_db(db_path)
    fake = FakeHistory()
    synced: list[set[int]] = []
    index = HistoryIndex(db_path, fake.list_sessions, on_projects_changed=synced.append)
    folder = tmp_path / "home" / "app"
    project_id = add_project(db_path, folder)
    add_project(db_path, tmp_path / "home" / "quiet", "quiet")

    await index.sync_all()
    assert synced == []
    fake.add(str(folder), info("s1", str(folder)))
    await index.sync_all()
    assert synced == [{project_id}]
    await index.sync_all()
    assert synced == [{project_id}]


@pytest.mark.anyio
async def test_project_removed_during_sync_is_skipped(env):
    db_path, fake, index, changed, home = env
    a, b = home / "a", home / "b"
    a_id = add_project(db_path, a, "a")
    b_id = add_project(db_path, b, "b")
    fake.add(str(a), info("sa", str(a)))
    fake.add(str(b), info("sb", str(b)))
    original = fake.list_sessions

    def list_and_remove(directory: str):
        result = original(directory)
        if directory == str(b):
            with closing(db.connect(db_path)) as conn:
                conn.execute("DELETE FROM projects WHERE id = ?", (a_id,))
        return result

    index._list_sessions = list_and_remove
    await index.sync_all()

    stored = rows(db_path)
    assert set(stored) == {"sb"}
    assert stored["sb"]["project_id"] == b_id


@pytest.mark.anyio
async def test_session_deleted_on_disk_leaves_the_index(tmp_path: Path):
    db_path = tmp_path / "data" / "vibing.db"
    db.init_db(db_path)
    fake = FakeHistory()
    synced: list[set[int]] = []
    in_use = {"busy"}
    index = HistoryIndex(
        db_path, fake.list_sessions,
        on_projects_changed=synced.append, is_in_use=lambda sid: sid in in_use,
        file_exists=lambda sid, cwd: False,
    )
    folder = tmp_path / "home" / "app"
    project_id = add_project(db_path, folder)
    fake.add(str(folder), info("gone", str(folder)), info("busy", str(folder)),
             info("kept", str(folder)))
    await index.sync_all()
    with closing(db.connect(db_path)) as conn:
        # Created in the app, never written to disk: stays.
        conn.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
            " last_activity_at, last_seen_at, finished) VALUES ('new', ?, ?, 'Nova', 1, 1, 1, 0)",
            (project_id, str(folder)),
        )
    synced.clear()
    fake.by_directory[str(folder)] = [info("kept", str(folder))]

    await index.sync_all()

    assert set(rows(db_path)) == {"kept", "busy", "new"}
    assert synced == [{project_id}]


@pytest.mark.anyio
async def test_listing_failure_does_not_delete_sessions(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder)))
    await index.sync_all()
    fake.failing.add(str(folder))

    await index.sync_all()

    assert set(rows(db_path)) == {"s1"}


def deleting_env(tmp_path: Path, exists):
    db_path = tmp_path / "data" / "vibing.db"
    db.init_db(db_path)
    fake = FakeHistory()
    index = HistoryIndex(db_path, fake.list_sessions, file_exists=exists)
    folder = tmp_path / "home" / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder)))
    return db_path, fake, index, folder


@pytest.mark.anyio
@pytest.mark.parametrize("exists", [True, None])
async def test_session_missing_from_listing_but_file_present_or_unknown_stays(tmp_path, exists):
    db_path, fake, index, folder = deleting_env(tmp_path, lambda sid, cwd: exists)
    await index.sync_all()
    fake.by_directory[str(folder)] = []

    await index.sync_all()

    assert set(rows(db_path)) == {"s1"}


@pytest.mark.anyio
async def test_session_with_file_really_gone_is_removed(tmp_path):
    checked: list[tuple[str, str]] = []

    def exists(sid, cwd):
        checked.append((sid, cwd))
        return False

    db_path, fake, index, folder = deleting_env(tmp_path, exists)
    await index.sync_all()
    fake.by_directory[str(folder)] = []

    await index.sync_all()

    assert rows(db_path) == {}
    assert checked == [("s1", str(folder))]


@pytest.mark.anyio
async def test_repository_limit_reached_does_not_delete(tmp_path, monkeypatch):
    db_path, fake, index, folder = deleting_env(tmp_path, lambda sid, cwd: False)
    await index.sync_all()
    fake.by_directory[str(folder)] = []
    monkeypatch.setattr("vibing.history.REPO_MAX_COUNT", 1)
    make_repo(folder / "r1")
    make_repo(folder / "r2")

    await index.sync_all()

    assert set(rows(db_path)) == {"s1"}


@pytest.mark.anyio
async def test_repository_scan_error_does_not_delete(tmp_path, monkeypatch):
    db_path, fake, index, folder = deleting_env(tmp_path, lambda sid, cwd: False)
    await index.sync_all()
    fake.by_directory[str(folder)] = []

    def boom(*args, **kwargs):
        raise OSError("falhou")

    monkeypatch.setattr("vibing.history.scan_repositories", boom)
    await index.sync_all()

    assert set(rows(db_path)) == {"s1"}


def test_scan_repositories_reports_unreadable_folder(tmp_path, monkeypatch):
    from vibing import history

    real = os.scandir

    def scandir(path):
        if Path(path).name == "locked":
            raise PermissionError("negado")
        return real(path)

    (tmp_path / "locked").mkdir()
    monkeypatch.setattr(history.os, "scandir", scandir)
    found, complete = history.scan_repositories(tmp_path)
    assert found == [] and complete is False
    found, complete = history.scan_repositories(tmp_path / "nada")
    assert complete is False


@pytest.mark.anyio
async def test_file_checks_run_before_the_transaction(tmp_path, monkeypatch):
    from vibing import history

    inside = {"value": False}
    real = history.db.transaction
    from contextlib import contextmanager

    @contextmanager
    def tracking(conn):
        inside["value"] = True
        try:
            with real(conn) as c:
                yield c
        finally:
            inside["value"] = False

    seen: list[bool] = []

    def exists(sid, cwd):
        seen.append(inside["value"])
        return False

    db_path, fake, index, folder = deleting_env(tmp_path, exists)
    await index.sync_all()
    fake.by_directory[str(folder)] = []
    monkeypatch.setattr(history.db, "transaction", tracking)

    await index.sync_all()

    assert seen == [False]
    assert rows(db_path) == {}
