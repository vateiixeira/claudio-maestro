"""Worktree detection from transcripts and `.git` markers (no git process)."""

import json
from pathlib import Path

from claudio_maestro.worktree import (
    Worktree, current_worktree, last_cwd, parse_worktree_list, worktree_of,
)


def _jsonl(path: Path, *entries: dict) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def _linked(root: Path, name: str) -> Path:
    """A folder that looks like a linked worktree of `root`."""
    wt = root / ".claude" / "worktrees" / name
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {root}/.git/worktrees/{name}\n")
    return wt


def test_last_cwd_returns_the_newest_entry(tmp_path: Path):
    f = _jsonl(tmp_path / "s.jsonl", {"cwd": "/a"}, {"type": "x"}, {"cwd": "/b/c d"})
    assert last_cwd(f) == "/b/c d"


def test_last_cwd_reads_only_the_tail_and_survives_a_cut_line(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    big = json.dumps({"cwd": "/old", "pad": "x" * 200_000}) + "\n"
    f.write_text(big + json.dumps({"cwd": "/new"}) + "\n" + '{"cwd": "/par')
    assert last_cwd(f, tail_bytes=1024) == "/new"


def test_last_cwd_unescapes_json(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text('{"cwd": "/a/\\u00e7\\"q"}\n')
    assert last_cwd(f) == '/a/ç"q'


def test_last_cwd_missing_file_or_no_cwd(tmp_path: Path):
    assert last_cwd(tmp_path / "nada.jsonl") is None
    assert last_cwd(_jsonl(tmp_path / "s.jsonl", {"type": "x"})) is None


def test_worktree_of_linked_worktree_and_subfolder(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    wt = _linked(tmp_path, "melhorias")
    (wt / "backend").mkdir()
    expected = Worktree(name="melhorias", path=str(wt))
    assert worktree_of(str(wt)) == expected
    assert worktree_of(str(wt / "backend")) == expected


def test_worktree_of_main_checkout_is_none(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src").mkdir()
    assert worktree_of(str(tmp_path / "src")) is None


def test_worktree_of_submodule_is_not_a_worktree(tmp_path: Path):
    sub = tmp_path / "lib"
    sub.mkdir()
    (sub / ".git").write_text(f"gitdir: {tmp_path}/.git/modules/lib\n")
    assert worktree_of(str(sub)) is None


def test_worktree_of_outside_git_is_none(tmp_path: Path):
    assert worktree_of(str(tmp_path)) is None


def test_current_worktree_decides_only_for_existing_folders(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    wt = _linked(tmp_path, "x")
    f = _jsonl(tmp_path / "a.jsonl", {"cwd": str(tmp_path)}, {"cwd": str(wt)})
    assert current_worktree(f) == (True, Worktree(name="x", path=str(wt)))
    g = _jsonl(tmp_path / "b.jsonl", {"cwd": str(tmp_path)})
    assert current_worktree(g) == (True, None)
    h = _jsonl(tmp_path / "c.jsonl", {"cwd": str(tmp_path / "apagada")})
    assert current_worktree(h) == (False, None)
    assert current_worktree(tmp_path / "nenhum.jsonl") == (False, None)


def test_parse_worktree_list():
    out = (
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
        "worktree /repo/.worktrees/a b\nHEAD def\ndetached\n\n"
    )
    assert parse_worktree_list(out) == ["/repo", "/repo/.worktrees/a b"]
    assert parse_worktree_list("") == []
