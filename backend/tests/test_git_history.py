"""History, commit details and branches read by `gitinfo`."""

from pathlib import Path

import pytest
from git_helpers import commit_file, git, git_home, make_repo  # noqa: F401 (fixture)
from test_git_details import clone_to, make_clone

from claudio_maestro import gitinfo


@pytest.mark.anyio
async def test_log_paginates_thirty_at_a_time(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    for index in range(34):
        commit_file(repo, f"f{index}.txt")
    first = await gitinfo.repo_log(repo)
    assert len(first["commits"]) == 30 and first["has_more"] is True
    assert first["commits"][0]["subject"] == "add f33.txt"
    assert first["ref"] == "refs/heads/main" and first["branch"] == "main"
    second = await gitinfo.repo_log(repo, skip=30)
    assert [c["subject"] for c in second["commits"]][-1] == "inicial"
    assert len(second["commits"]) == 5 and second["has_more"] is False


@pytest.mark.anyio
async def test_log_limit_reloads_more_than_a_page(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    for index in range(40):
        commit_file(repo, f"f{index}.txt")
    log = await gitinfo.repo_log(repo, limit=60)
    assert len(log["commits"]) == 41 and log["has_more"] is False


@pytest.mark.anyio
async def test_log_fields(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "Assunto do commit", "-m", "Corpo da mensagem\ncom duas linhas")
    commit = (await gitinfo.repo_log(repo))["commits"][0]
    assert commit["subject"] == "Assunto do commit"
    assert commit["body"] == "Corpo da mensagem\ncom duas linhas"
    assert commit["author"] == "Teste" and commit["email"] == "teste@example.com"
    assert len(commit["full_hash"]) == 40 and commit["hash"] == commit["full_hash"][:7]
    assert len(commit["parents"]) == 1
    assert commit["pushed"] is None  # no upstream


@pytest.mark.anyio
async def test_log_upstream_outgoing_and_incoming(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    pushed_tip = git(clone, "rev-parse", "HEAD").strip()
    other = tmp_path / "other"
    clone_to(remote, other)
    commit_file(other, "remoto.txt")
    git(other, "push", "-q")
    commit_file(clone, "local1.txt")
    commit_file(clone, "local2.txt")
    git(clone, "fetch", "-q")
    log = await gitinfo.repo_log(clone)
    assert log["upstream"] == "origin/main"
    assert log["upstream_sha"] == git(clone, "rev-parse", "origin/main").strip()
    assert log["outgoing_count"] == 2 and log["incoming_count"] == 1
    assert [c["subject"] for c in log["incoming"]] == ["add remoto.txt"]
    pushed = {c["subject"]: c["pushed"] for c in log["commits"]}
    assert pushed == {"add local2.txt": False, "add local1.txt": False, "inicial": True}
    assert pushed_tip in {c["full_hash"] for c in log["commits"]}


@pytest.mark.anyio
async def test_log_other_branch_without_checkout(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "feat.txt")
    git(repo, "switch", "-q", "main")
    log = await gitinfo.repo_log(repo, "refs/heads/feat")
    assert log["commits"][0]["subject"] == "add feat.txt" and log["branch"] == "feat"
    assert git(repo, "symbolic-ref", "HEAD").strip() == "refs/heads/main"


@pytest.mark.anyio
@pytest.mark.parametrize("ref", [
    "main", "refs/heads/nao-existe", "refs/tags/v1", "HEAD", "--all", "refs/heads/main\n",
    "refs/heads/main..refs/heads/main", "refs/heads/main^{tree}",
])
async def test_log_refuses_refs_that_are_not_existing_branches(tmp_path: Path, ref):
    repo = make_repo(tmp_path / "r")
    git(repo, "tag", "v1")
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitinfo.repo_log(repo, ref)


@pytest.mark.anyio
async def test_log_of_repository_without_commits(tmp_path: Path):
    repo = make_repo(tmp_path / "r", commit=False)
    log = await gitinfo.repo_log(repo)
    assert log["commits"] == [] and log["has_more"] is False
    assert log["ref"] == "refs/heads/main"


@pytest.mark.anyio
async def test_log_detached_head(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "checkout", "-q", "--detach")
    log = await gitinfo.repo_log(repo)
    head = git(repo, "rev-parse", "HEAD").strip()
    assert log["ref"] is None and log["branch"] == head[:7]
    assert log["commits"][0]["full_hash"] == head


@pytest.mark.anyio
async def test_commit_detail_lists_files_with_status_and_counts(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    commit_file(repo, "apagar.txt", "1\n")
    commit_file(repo, "mover.txt", "um\ndois\ntres\nquatro\n")
    (repo / "README.md").write_text("linha 1\nmudou\nnova\n")
    (repo / "novo.txt").write_text("n\n")
    git(repo, "rm", "-q", "apagar.txt")
    git(repo, "mv", "mover.txt", "movido.txt")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "varios")
    sha = git(repo, "rev-parse", "HEAD").strip()
    detail = await gitinfo.commit_detail(repo, sha[:10])
    by_path = {f["path"]: f for f in detail["files"]}
    assert by_path["README.md"]["status"] == "M"
    assert (by_path["README.md"]["added"], by_path["README.md"]["removed"]) == (2, 1)
    assert by_path["novo.txt"]["status"] == "A"
    assert by_path["apagar.txt"]["status"] == "D"
    assert by_path["movido.txt"]["status"] == "R" and by_path["movido.txt"]["old_path"] == "mover.txt"
    assert detail["full_hash"] == sha and detail["files_truncated"] is False


@pytest.mark.anyio
async def test_root_commit_is_compared_with_the_empty_tree(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    root = git(repo, "rev-parse", "HEAD").strip()
    detail = await gitinfo.commit_detail(repo, root)
    assert [(f["path"], f["status"]) for f in detail["files"]] == [("README.md", "A")]
    diff = await gitinfo.commit_file_diff(repo, root, "README.md")
    assert "+linha 1" in diff.diff and "--- /dev/null" in diff.diff


@pytest.mark.anyio
async def test_merge_commit_is_compared_with_its_first_parent(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "feat.txt")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "main.txt")
    git(repo, "merge", "-q", "--no-edit", "feat")
    merge = git(repo, "rev-parse", "HEAD").strip()
    detail = await gitinfo.commit_detail(repo, merge)
    assert len(detail["parents"]) == 2
    assert [f["path"] for f in detail["files"]] == ["feat.txt"]


@pytest.mark.anyio
async def test_commit_file_diff_refuses_a_file_outside_the_commit(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    sha = commit_file(repo, "a.txt")
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitinfo.commit_file_diff(repo, sha, "README.md")


@pytest.mark.anyio
@pytest.mark.parametrize("sha", ["0000000", "zzzzzzz", "abc", "HEAD", "--all"])
async def test_unknown_or_invalid_sha(tmp_path: Path, sha):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(gitinfo.RefNotFoundError):
        await gitinfo.commit_detail(repo, sha)


@pytest.mark.anyio
async def test_branches_lists_local_and_remote(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    git(clone, "switch", "-q", "-c", "feat")
    commit_file(clone, "feat.txt")
    git(clone, "push", "-q", "origin", "feat")
    git(clone, "switch", "-q", "main")
    git(clone, "remote", "set-head", "origin", "main")
    result = await gitinfo.branches(clone)
    assert result["current"] == "refs/heads/main"
    local = {b["name"]: b for b in result["local"]}
    assert set(local) == {"main", "feat"}
    assert local["main"]["upstream"] == "origin/main" and local["main"]["ref"] == "refs/heads/main"
    assert local["feat"]["upstream"] is None
    assert {b["name"] for b in result["remote"]} == {"origin/main", "origin/feat"}  # no origin/HEAD
    assert all(len(b["sha"]) == 7 and b["date"] for b in result["local"])


@pytest.mark.anyio
async def test_count_between(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "a.txt")
    commit_file(repo, "b.txt")
    git(repo, "switch", "-q", "main")
    assert await gitinfo.count_between(repo, "HEAD", "refs/heads/feat") == 2
    assert await gitinfo.count_between(repo, "refs/heads/feat", "HEAD") == 0


@pytest.mark.anyio
async def test_branch_names_with_unicode_line_separators(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    for name in ("a b", "c\u0085d"):
        git(repo, "branch", name)
    result = await gitinfo.branches(repo)
    assert {b["name"] for b in result["local"]} == {"main", "a b", "c\u0085d"}
