"""Stable, independently paged history snapshots, using disposable repositories."""

from pathlib import Path

import pytest
from git_helpers import commit_file, git, git_home, make_repo  # noqa: F401

from claudio_maestro import gitinfo


def diverged(repo: Path, outgoing: int, incoming: int) -> None:
    base = git(repo, "rev-parse", "HEAD").strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    for ref, count, prefix in (("refs/heads/main", outgoing, "local"),
                               ("refs/remotes/origin/main", incoming, "remote")):
        parent = base
        for i in range(count):
            parent = git(repo, "commit-tree", tree, "-p", parent, "-m", f"{prefix} {i}").strip()
        git(repo, "update-ref", ref, parent)
    git(repo, "config", "remote.origin.url", "/not-contacted")
    git(repo, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    git(repo, "config", "branch.main.remote", "origin")
    git(repo, "config", "branch.main.merge", "refs/heads/main")


@pytest.mark.anyio
async def test_page_snapshot_does_not_move_with_head_or_upstream(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 4, 2)
    first = await gitinfo.repo_log(repo, limit=2)
    original = git(repo, "rev-list", "HEAD").splitlines()
    commit_file(repo, "new.txt")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    second = await gitinfo.repo_log(
        repo, skip=first["next_skip"], limit=2,
        snapshot_head=first["head_sha"], snapshot_upstream=first["upstream_sha"],
    )
    assert [c["full_hash"] for c in second["commits"]] == original[2:4]
    assert second["head_sha"] == first["head_sha"]
    assert (second["outgoing_count"], second["incoming_count"]) == (4, 2)


@pytest.mark.anyio
async def test_snapshot_without_upstream_stays_without_one(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    commit_file(repo, "a.txt")
    first = await gitinfo.repo_log(repo, limit=1)
    diverged(repo, 2, 1)
    second = await gitinfo.repo_log(
        repo, skip=1, limit=1, snapshot_head=first["head_sha"], snapshot_upstream="-",
    )
    assert second["upstream_sha"] is None
    assert second["commits"][0]["subject"] == "inicial"
    assert second["commits"][0]["pushed"] is None


@pytest.mark.anyio
async def test_incoming_and_outgoing_have_complete_independent_pagination(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 1101, 101)
    first = await gitinfo.repo_log(repo, direction="incoming", limit=100)
    assert len(first["commits"]) == 100 and first["has_more"]
    assert first["incoming_count"] == 101 and first["outgoing_count"] == 1101
    last = await gitinfo.repo_log(
        repo, direction="incoming", skip=first["next_skip"], limit=100,
        snapshot_head=first["head_sha"], snapshot_upstream=first["upstream_sha"],
    )
    assert len(last["commits"]) == 1 and last["next_skip"] is None
    assert all(c["pushed"] is True for c in first["commits"] + last["commits"])
    outgoing = await gitinfo.repo_log(repo, direction="outgoing", skip=1000, limit=101)
    assert len(outgoing["commits"]) == 101 and not outgoing["has_more"]
    assert all(c["pushed"] is False for c in outgoing["commits"])
    all_page = await gitinfo.repo_log(repo, skip=1000, limit=101)
    assert all(c["pushed"] is False for c in all_page["commits"])


@pytest.mark.anyio
async def test_failed_pushed_query_does_not_claim_commits_are_sent(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 2, 1)
    original = gitinfo.run_git

    async def fail_membership(path, *args, **kwargs):
        if args[0] == "rev-list" and "--count" not in args:
            return 1, "", "membership failed"
        return await original(path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", fail_membership)
    result = await gitinfo.repo_log(repo)
    assert all(c["pushed"] is None for c in result["commits"])


@pytest.mark.anyio
async def test_details_can_skip_legacy_commits(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")

    async def forbidden(*args, **kwargs):
        pytest.fail("SCM details must not load history")

    monkeypatch.setattr(gitinfo, "repo_commits", forbidden)
    details = await gitinfo.repo_details(repo, include_commits=False)
    assert details["commits"] == [] and details["error"] is None
    assert details["head_sha"]


@pytest.mark.anyio
@pytest.mark.parametrize("head,upstream", [("HEAD", "-"), ("a" * 40, "--all"),
                                         ("a" * 40, None), (None, "-")])
async def test_snapshot_rejects_arbitrary_refs_and_partial_pairs(tmp_path: Path, head, upstream):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitinfo.repo_log(repo, snapshot_head=head, snapshot_upstream=upstream)


@pytest.mark.anyio
async def test_ref_signature_changes_for_non_head_branch_and_remote_rewrite(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 2, 1)
    before = await gitinfo.repo_status(repo)
    git(repo, "branch", "another")
    after = await gitinfo.repo_status(repo)
    assert before.refs_signature != after.refs_signature
    assert before.head == after.head
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    base = git(repo, "rev-parse", "HEAD~2").strip()
    replacement = git(repo, "commit-tree", tree, "-p", base, "-m", "remote replacement").strip()
    git(repo, "update-ref", "refs/remotes/origin/main", replacement)
    rewritten = await gitinfo.repo_status(repo)
    assert after.refs_signature != rewritten.refs_signature
    assert (after.ahead, after.behind) == (rewritten.ahead, rewritten.behind)
    assert (await gitinfo.repo_details(repo, include_commits=False))["refs_signature"] == rewritten.refs_signature


@pytest.mark.anyio
async def test_truncated_membership_is_unknown_instead_of_sent(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 4, 1)
    original = gitinfo.run_git

    async def truncated(path, *args, **kwargs):
        if args[0] == "rev-list" and "--count" not in args:
            return 0, "x" * (gitinfo.FILES_READ_LIMIT + 1), ""
        return await original(path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", truncated)
    result = await gitinfo.repo_log(repo)
    assert all(c["pushed"] is None for c in result["commits"])


@pytest.mark.anyio
async def test_refs_signature_unknown_on_error_or_truncation(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")

    async def fail(*args, **kwargs):
        return 1, "", "error"

    monkeypatch.setattr(gitinfo, "run_git", fail)
    assert await gitinfo.refs_signature(repo) is None

    async def truncated(*args, **kwargs):
        return 0, "x" * (gitinfo.FILES_READ_LIMIT + 1), ""

    monkeypatch.setattr(gitinfo, "run_git", truncated)
    assert await gitinfo.refs_signature(repo) is None


@pytest.mark.anyio
async def test_all_page_can_leave_incoming_unloaded(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    diverged(repo, 2, 3)
    original = gitinfo.run_git
    log_calls = []

    async def counted(path, *args, **kwargs):
        if args[0] == "log":
            log_calls.append(args)
        return await original(path, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", counted)
    result = await gitinfo.repo_log(repo, include_incoming=False)
    assert result["incoming"] == [] and result["incoming_count"] == 3
    assert result["incoming_has_more"] is True and len(log_calls) == 1
    incoming = await gitinfo.repo_log(repo, direction="incoming", include_incoming=False)
    assert len(incoming["commits"]) == 3
