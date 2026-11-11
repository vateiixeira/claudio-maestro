"""Read-only comparison of two branch snapshots."""

from pathlib import Path

import pytest
from git_helpers import commit_file, git, git_home, make_repo  # noqa: F401

from claudio_maestro import gitcompare, gitinfo


def diverged(repo: Path) -> tuple[str, str, str]:
    ancestor = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "switch", "-qc", "feature")
    head = commit_file(repo, "feature.txt", "feature\n")
    git(repo, "switch", "-q", "main")
    base = commit_file(repo, "main.txt", "main\n")
    git(repo, "switch", "-q", "feature")
    return ancestor, head, base


@pytest.mark.anyio
async def test_comparison_metadata_and_direction_do_not_change_checkout(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    ancestor, head, base = diverged(repo)
    result = await gitcompare.comparison(repo, "refs/heads/main")
    assert result == {
        "head_ref": "refs/heads/feature", "base_ref": "refs/heads/main",
        "head_sha": head, "base_sha": base, "merge_base": ancestor,
        "ahead_count": 1, "behind_count": 1, "unrelated": False, "notice": None,
    }
    ahead = await gitcompare.commits(repo, head, base, "ahead")
    behind = await gitcompare.commits(repo, head, base, "behind")
    assert [c["subject"] for c in ahead["commits"]] == ["add feature.txt"]
    assert [c["subject"] for c in behind["commits"]] == ["add main.txt"]
    assert ahead["commits"][0]["pushed"] is None
    assert git(repo, "symbolic-ref", "HEAD").strip() == "refs/heads/feature"
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.anyio
async def test_commits_keep_snapshot_after_new_commit_and_page_both_directions(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    _, _, base = diverged(repo)
    head = commit_file(repo, "second.txt")
    first = await gitcompare.commits(repo, head, base, "ahead", limit=1)
    assert first["has_more"] and first["next_skip"] == 1
    commit_file(repo, "new.txt")
    second = await gitcompare.commits(repo, head, base, "ahead", skip=1, limit=1)
    assert second["commits"][0]["subject"] == "add feature.txt"
    assert not second["has_more"] and second["next_skip"] is None


@pytest.mark.anyio
async def test_files_and_diff_compare_each_side_from_common_ancestor(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    ancestor, head, base = diverged(repo)
    ahead = await gitcompare.files(repo, head, base, "ahead")
    behind = await gitcompare.files(repo, head, base, "behind")
    assert [f["path"] for f in ahead["files"]] == ["feature.txt"]
    assert [f["path"] for f in behind["files"]] == ["main.txt"]
    assert ahead["base_sha"] == ancestor and ahead["target_sha"] == head
    diff = await gitcompare.file_diff(repo, head, base, "ahead", "feature.txt")
    assert "+feature" in diff.diff and "main.txt" not in diff.diff
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitcompare.file_diff(repo, head, base, "ahead", "main.txt")


@pytest.mark.anyio
async def test_rename_preserves_old_path_and_literal_pathspec(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "mv", "README.md", "[special].md")
    git(repo, "commit", "-qm", "Renomear")
    head = git(repo, "rev-parse", "HEAD").strip()
    listed = await gitcompare.files(repo, head, base, "ahead")
    assert listed["files"][0]["old_path"] == "README.md"
    diff = await gitcompare.file_diff(repo, head, base, "ahead", "[special].md")
    assert "rename from README.md" in diff.diff
    assert "rename to [special].md" in diff.diff


@pytest.mark.anyio
async def test_unrelated_branches_report_recoverable_state(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "checkout", "--orphan", "other")
    git(repo, "rm", "-rf", ".")
    commit_file(repo, "other.txt")
    meta = await gitcompare.comparison(repo, "refs/heads/main")
    assert meta["unrelated"] and meta["merge_base"] is None
    assert "ancestral" in meta["notice"]
    with pytest.raises(gitcompare.UnrelatedHistoryError):
        await gitcompare.files(repo, meta["head_sha"], meta["base_sha"], "ahead")


@pytest.mark.anyio
async def test_invalid_and_deleted_refs_are_not_silently_replaced(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    for ref in ["--all", "refs/heads/missing", "refs/heads/main~1"]:
        with pytest.raises(gitinfo.RefNotFoundError):
            await gitcompare.comparison(repo, ref)
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitcompare.commits(repo, "HEAD", "0" * 40, "ahead")


@pytest.mark.anyio
async def test_file_limit_is_explicit(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD").strip()
    commit_file(repo, "a.txt")
    head = commit_file(repo, "b.txt")
    monkeypatch.setattr(gitinfo, "MAX_FILES", 1)
    result = await gitcompare.files(repo, head, base, "ahead")
    assert len(result["files"]) == 1 and result["files_truncated"]


@pytest.mark.anyio
async def test_comparison_reads_selected_ref_without_checkout(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    _, head, base = diverged(repo)
    meta = await gitcompare.comparison(repo, "refs/heads/feature", "refs/heads/main")
    assert meta["head_sha"] == base and meta["base_sha"] == head
    assert meta["head_ref"] == "refs/heads/main"
    assert git(repo, "symbolic-ref", "HEAD").strip() == "refs/heads/feature"


@pytest.mark.anyio
async def test_binary_deletion_and_large_diff_are_explicit(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    base = git(repo, "rev-parse", "HEAD").strip()
    (repo / "binary.dat").write_bytes(b"\0binary")
    git(repo, "rm", "README.md")
    git(repo, "add", "--", "binary.dat")
    git(repo, "commit", "-qm", "Alterar arquivos")
    head = git(repo, "rev-parse", "HEAD").strip()
    result = await gitcompare.files(repo, head, base, "ahead")
    by_name = {item["path"]: item for item in result["files"]}
    assert by_name["README.md"]["status"] == "D"
    assert by_name["binary.dat"]["added"] is None
    binary = await gitcompare.file_diff(repo, head, base, "ahead", "binary.dat")
    assert "Binary files" in binary.diff
    monkeypatch.setattr(gitinfo, "DIFF_LIMIT", 20)
    deletion = await gitcompare.file_diff(repo, head, base, "ahead", "README.md")
    assert deletion.truncated and len(deletion.diff) == 20


@pytest.mark.anyio
@pytest.mark.parametrize("tail", ["A\0", "R100\0old.txt\0", "R100\0old.txt\0partial"])
async def test_clipped_names_drop_incomplete_records(tmp_path: Path, monkeypatch, tail: str):
    repo = make_repo(tmp_path / "r")
    _, head, base = diverged(repo)
    original = gitinfo.run_git
    names = "A\0complete.txt\0" + tail
    monkeypatch.setattr(gitinfo, "FILES_READ_LIMIT", len(names.encode()) - 1)

    async def bounded_output(path, *args, **kwargs):
        if "--name-status" in args:
            return 0, names, ""
        if "--numstat" in args:
            return 0, "", ""
        return await original(path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", bounded_output)
    result = await gitcompare.files(repo, head, base, "ahead")
    assert result["files_truncated"]
    assert [item["path"] for item in result["files"]] == ["complete.txt"]
