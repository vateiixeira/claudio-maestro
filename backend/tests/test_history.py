"""History index: sync from the SDK's `list_sessions`, repositories inside the project."""

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


def test_title_prefers_custom_then_summary_then_first_prompt():
    assert session_title(info("a", "/x", custom_title="Meu", summary="Resumo")) == "Meu"
    assert session_title(info("a", "/x", summary="Resumo", first_prompt="p")) == "Resumo"
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
    assert row["title"] == "Resumo"
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
async def test_sync_updates_title_not_renamed_by_app(env):
    db_path, fake, index, changed, home = env
    folder = home / "app"
    add_project(db_path, folder)
    fake.add(str(folder), info("s1", str(folder), first_prompt="primeiro"))
    await index.sync_all()
    fake.by_directory[str(folder)] = [info("s1", str(folder), summary="Resumo gerado")]

    await index.sync_all()

    assert rows(db_path)["s1"]["title"] == "Resumo gerado"


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
    assert sessions.sdk_history_exists("s", "/x") is False
    with pytest.raises(RuntimeError):
        sessions.default_agent_factory(None)
