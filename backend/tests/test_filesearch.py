"""File suggestions for @ mentions."""

from pathlib import Path

import pytest
from git_helpers import git, make_repo

from claudio_maestro.filesearch import FileIndex, FileMatch, is_excluded, match_files


def touch(root: Path, *paths: str) -> None:
    for rel in paths:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("rel", [
    "node_modules/a.js", "src/.git/x", "dist/a.js", "a/build/b.js", ".next/x", ".nuxt/x",
    ".DS_Store", "a/Thumbs.db", "debug.log", ".env", "a/.env.local", "yarn-error.log",
    "npm-debug.log.1",
])
def test_fixed_exclusions(rel):
    assert is_excluded(rel)


@pytest.mark.parametrize("rel", ["src/build.py", "envs/a.py", "logs/a.txt", "a/.envrc"])
def test_not_excluded(rel):
    assert not is_excluded(rel)


PATHS = sorted([
    "backend/claudio_maestro/fs.py",
    "backend/claudio_maestro/api/fs.py",
    "backend/claudio_maestro/FsHelper.py",
    "frontend/src/App.vue",
    "README.md",
])


def test_term_without_slash_matches_the_file_name_ignoring_case():
    result = match_files(PATHS, "fs")
    files = [m.path for m in result if m.type == "file"]
    assert files == ["backend/claudio_maestro/FsHelper.py", "backend/claudio_maestro/api/fs.py", "backend/claudio_maestro/fs.py"]


def test_term_with_slash_matches_across_one_folder_boundary():
    result = match_files(PATHS, "api/fs")
    assert [m.path for m in result if m.type == "file"] == ["backend/claudio_maestro/api/fs.py"]
    assert match_files(PATHS, "backend/fs") == []  # `*` does not cross `/`


def test_folders_of_the_matches_whose_path_contains_the_term_end_with_slash():
    result = match_files(["backend/claudio_maestro/claudio_maestro_cfg.py", "backend/other.py"], "claudio_maestro")
    assert FileMatch("backend/claudio_maestro/", "claudio_maestro", "directory") in result
    assert FileMatch("backend/claudio_maestro/claudio_maestro_cfg.py", "claudio_maestro_cfg.py", "file") in result
    assert all(m.path != "backend/" for m in result)


def test_everything_is_sorted_by_path():
    result = match_files(PATHS, "fs")
    assert [m.path for m in result] == sorted(m.path for m in result)


def test_empty_term_lists_the_first_files_and_their_folders():
    many = [f"f{i:03}.txt" for i in range(150)]
    result = match_files(many, "")
    assert len(result) == 100
    assert result[0].path == "f000.txt" and result[-1].path == "f099.txt"


def test_at_most_100_files():
    many = [f"a{i:03}.py" for i in range(150)]
    assert len(match_files(many, "a")) == 100


@pytest.mark.anyio
async def test_git_repo_lists_tracked_and_untracked_not_ignored(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("segredo.txt\n.venv/\n")
    touch(repo, "novo.py", "segredo.txt", ".venv/lib/x.py", "node_modules/y.js", "app.log")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    result = await FileIndex().search(repo, "")
    paths = [m.path for m in result if m.type == "file"]
    assert "novo.py" in paths and "README.md" in paths and ".gitignore" in paths
    assert "segredo.txt" not in paths
    assert not any(p.startswith((".venv/", "node_modules/")) or p.endswith(".log") for p in paths)


@pytest.mark.anyio
async def test_folder_without_git_is_walked_with_exclusions(tmp_path: Path):
    touch(tmp_path, "a/b.py", "node_modules/x.js", "dist/y.js", ".env")
    result = await FileIndex().search(tmp_path, "")
    assert [m.path for m in result] == ["a/", "a/b.py"]


@pytest.mark.anyio
async def test_walk_stops_at_the_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("claudio_maestro.filesearch.WALK_LIMIT", 5)
    touch(tmp_path, *[f"f{i}.txt" for i in range(20)])
    result = await FileIndex().search(tmp_path, "")
    assert len(result) == 5


@pytest.mark.anyio
async def test_folder_with_several_repositories_uses_git_in_each(tmp_path: Path):
    front = make_repo(tmp_path / "front")
    back = make_repo(tmp_path / "back")
    (back / ".gitignore").write_text(".venv/\n")
    touch(back, ".venv/lib/pesado.py", "api.py")
    touch(tmp_path, "notas.md")
    result = await FileIndex().search(tmp_path, "")
    paths = [m.path for m in result if m.type == "file"]
    assert "front/README.md" in paths and "back/api.py" in paths and "notas.md" in paths
    assert not any(".venv" in p for p in paths)
    assert not any(p.startswith(("front/.git/", "back/.git/")) for p in paths)
    assert front and back


@pytest.mark.anyio
async def test_project_inside_a_repository_respects_the_repository_gitignore(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("segredo.txt\n")
    touch(repo, "backend/app.py", "backend/segredo.txt", "outro/fora.py")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    result = await FileIndex().search(repo / "backend", "")
    assert [m.path for m in result if m.type == "file"] == ["app.py"]


@pytest.mark.anyio
async def test_walk_skips_cache_and_hidden_folders_so_the_limit_keeps_project_files(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.filesearch.WALK_LIMIT", 10)
    touch(tmp_path, *[f".venv/lib/f{i}.py" for i in range(30)])
    touch(tmp_path, *[f"__pycache__/c{i}.pyc" for i in range(30)])
    touch(tmp_path, ".mypy_cache/x.json", ".hidden/y.py", "target/z.py", "app/main.py")
    result = await FileIndex().search(tmp_path, "main")
    assert [m.path for m in result if m.type == "file"] == ["app/main.py"]
    everything = [m.path for m in await FileIndex().search(tmp_path, "")]
    assert everything == ["app/", "app/main.py"]


@pytest.mark.anyio
async def test_nested_repository_does_not_produce_a_nameless_entry(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    make_repo(repo / "inner")
    result = await FileIndex().search(repo, "")
    assert all(m.name for m in result)
    assert not any(m.path == "inner/" for m in result)


@pytest.mark.anyio
async def test_listing_is_cached_for_30_seconds(tmp_path: Path):
    clock = Clock()
    index = FileIndex(clock=clock)
    touch(tmp_path, "a.py")
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py"]
    touch(tmp_path, "b.py")
    clock.now = 29.9
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py"]
    clock.now = 30.0
    assert [m.path for m in await index.search(tmp_path, "")] == ["a.py", "b.py"]
