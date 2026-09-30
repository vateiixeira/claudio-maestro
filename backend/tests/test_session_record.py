from pathlib import Path

from vibing.sessions import SessionRecord, describe


def _record(**extra) -> SessionRecord:
    return SessionRecord(
        session_id="s", project_id=1, cwd="/p", title="t", created_at=1, last_activity_at=1, **extra,
    )


def test_describe_exposes_worktree_but_not_history_dir():
    out = describe(
        _record(history_dir="/p/.wt/a", worktree_name="a", worktree_path="/p/.wt/a", git_branch="feat"),
        "closed", None, 0, finished_after=3600, now=2,
    )
    assert out["worktree_name"] == "a"
    assert out["worktree_path"] == "/p/.wt/a"
    assert out["git_branch"] == "feat"
    assert "history_dir" not in out


def test_history_directory_and_work_dir(tmp_path: Path):
    assert _record().history_directory == "/p"
    assert _record(history_dir="/h").history_directory == "/h"
    wt = tmp_path / "wt"
    wt.mkdir()
    assert _record(worktree_path=str(wt)).work_dir() == str(wt)
    assert _record(worktree_path=str(tmp_path / "gone")).work_dir() == "/p"
    assert _record().work_dir() == "/p"
