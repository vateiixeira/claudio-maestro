"""Merge state, conflicts, hooks, filters, merge drivers and signing of a repository."""

import os
from pathlib import Path

import pytest
from git_helpers import commit_file, git, git_home, make_repo  # noqa: F401 (fixture)

from claudio_maestro import gitinfo


@pytest.fixture(autouse=True)
def fresh_policy():
    gitinfo.clear_policy_cache()
    yield
    gitinfo.clear_policy_cache()


def make_conflict(tmp_path: Path) -> Path:
    repo = make_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    (repo / "README.md").write_text("da feat\n")
    git(repo, "commit", "-q", "-am", "feat muda")
    git(repo, "switch", "-q", "main")
    (repo / "README.md").write_text("da main\n")
    git(repo, "commit", "-q", "-am", "main muda")
    commit_file(repo, "so-main.txt")
    try:
        git(repo, "merge", "--no-edit", "feat")
    except Exception:
        pass  # exits 1 on conflict
    return repo


@pytest.mark.anyio
async def test_state_of_a_merge_with_conflict(tmp_path: Path, git_home):
    repo = make_conflict(tmp_path)
    state = await gitinfo.repo_state(repo)
    assert state["merging"] is True and state["merge_branch"] == "feat"
    assert state["conflicts"] == ["README.md"]
    assert state["merge_message"].startswith("Merge branch 'feat'")
    assert "#" not in state["merge_message"]  # the "# Conflicts:" comment lines are gone
    assert len(state["merge_head"]) == 40


@pytest.mark.anyio
async def test_state_without_merge(tmp_path: Path, git_home):
    state = await gitinfo.repo_state(make_repo(tmp_path / "r"))
    assert state["merging"] is False and state["conflicts"] == []
    assert state["merge_branch"] is None and state["merge_message"] is None


@pytest.mark.anyio
async def test_details_mark_conflicts_and_kinds(tmp_path: Path, git_home):
    repo = make_conflict(tmp_path)
    (repo / "novo.txt").write_text("n\n")
    details = await gitinfo.repo_details(repo)
    files = {(f["path"], f["status"]): f for f in details["files"]}
    assert files[("README.md", "conflict")]["kind"] == "U"
    assert files[("novo.txt", "untracked")]["kind"] == "A"
    assert details["changed"]["unstaged"] >= 1
    assert details["state"]["merging"] is True
    assert details["head_sha"] == git(repo, "rev-parse", "HEAD").strip()


@pytest.mark.anyio
async def test_file_kinds(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    commit_file(repo, "apagar.txt")
    commit_file(repo, "mover.txt", "a\nb\nc\nd\n")
    (repo / "README.md").write_text("mudou\n")
    git(repo, "rm", "-q", "apagar.txt")
    git(repo, "mv", "mover.txt", "movido.txt")
    (repo / "novo.txt").write_text("n\n")
    git(repo, "add", "novo.txt")
    kinds = {(f["path"], f["status"]): f["kind"] for f in (await gitinfo.repo_details(repo))["files"]}
    assert kinds[("README.md", "unstaged")] == "M"
    assert kinds[("apagar.txt", "staged")] == "D"
    assert kinds[("movido.txt", "staged")] == "R"
    assert kinds[("novo.txt", "staged")] == "A"


@pytest.mark.anyio
async def test_hooks_are_detected(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit.sample").write_text("#!/bin/sh\n")
    assert (await gitinfo.repo_policy(repo))["has_hooks"] is False
    gitinfo.clear_policy_cache()
    (hooks / "pre-commit").write_text("#!/bin/sh\n")
    assert (await gitinfo.repo_policy(repo))["has_hooks"] is True


@pytest.mark.anyio
async def test_hooks_path_of_the_repository_is_detected(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (repo / ".githooks").mkdir()
    (repo / ".githooks" / "commit-msg").write_text("#!/bin/sh\n")
    git(repo, "config", "core.hooksPath", ".githooks")
    assert (await gitinfo.repo_policy(repo))["has_hooks"] is True


@pytest.mark.anyio
async def test_lfs_used_by_the_repository_makes_it_read_only(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (git_home / ".gitconfig").write_text('[filter "lfs"]\n\tclean = git-lfs clean -- %f\n')
    assert (await gitinfo.repo_policy(repo))["read_only"] is None  # defined but not used
    gitinfo.clear_policy_cache()
    (repo / ".gitattributes").write_text("*.psd filter=lfs diff=lfs merge=lfs -text\n")
    assert (await gitinfo.repo_policy(repo))["read_only"] == gitinfo.LFS_READ_ONLY


@pytest.mark.anyio
async def test_other_filter_of_the_repository_makes_it_read_only(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "filter.cripto.smudge", "cripto -d")
    (repo / "dados").mkdir()
    (repo / "dados" / ".gitattributes").write_text("*.bin filter=cripto\n")
    policy = await gitinfo.repo_policy(repo)
    assert policy["read_only"] == gitinfo.FILTER_READ_ONLY.format(name="cripto")


@pytest.mark.anyio
async def test_attribute_without_a_defined_filter_is_not_read_only(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    # Not `lfs`: CI runners define `filter.lfs` in the system config, which the policy reads.
    (repo / ".gitattributes").write_text("*.psd filter=filtro-que-ninguem-definiu\n")
    assert (await gitinfo.repo_policy(repo))["read_only"] is None


@pytest.mark.anyio
async def test_local_merge_driver_blocks_merging(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "merge.meu.driver", "touch /tmp/nao-deve-rodar")
    policy = await gitinfo.repo_policy(repo)
    assert policy["no_merge"] == gitinfo.MERGE_DRIVER_MESSAGE.format(name="meu")
    assert policy["read_only"] is None


@pytest.mark.anyio
async def test_global_merge_driver_only_counts_when_used(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (git_home / ".gitconfig").write_text('[merge "npm"]\n\tdriver = npm-merge %A %O %B\n')
    assert (await gitinfo.repo_policy(repo))["no_merge"] is None
    gitinfo.clear_policy_cache()
    (repo / ".gitattributes").write_text("package-lock.json merge=npm\n")
    assert (await gitinfo.repo_policy(repo))["no_merge"] == gitinfo.MERGE_DRIVER_MESSAGE.format(name="npm")


@pytest.mark.anyio
async def test_gpgsign_and_email(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "user.email", "eu@example.com")
    (git_home / ".gitconfig").write_text("[commit]\n\tgpgsign = true\n")
    policy = await gitinfo.repo_policy(repo)
    assert policy["gpgsign"] is True and policy["user_email"] == "eu@example.com"


@pytest.mark.anyio
async def test_remote_names(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "remote", "add", "origin", "https://example.com/a.git")
    git(repo, "remote", "add", "fork.dois", "https://example.com/b.git")
    assert sorted(await gitinfo.remote_names(repo)) == ["fork.dois", "origin"]
    assert sorted((await gitinfo.repo_policy(repo))["remotes"]) == ["fork.dois", "origin"]


@pytest.mark.anyio
async def test_policy_is_cached_until_cleared(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    assert (await gitinfo.repo_policy(repo))["has_hooks"] is False
    (repo / ".git" / "hooks").mkdir(exist_ok=True)
    (repo / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n")
    assert (await gitinfo.repo_policy(repo))["has_hooks"] is False
    assert (await gitinfo.repo_policy(repo, cached=False))["has_hooks"] is True


@pytest.mark.anyio
async def test_policy_reads_the_app_overrides_out(tmp_path: Path, git_home):
    """`core.hooksPath=/dev/null` and `filter.lfs.*` from SAFE_CONFIG are not the repository's."""
    repo = make_repo(tmp_path / "r")
    policy = await gitinfo.repo_policy(repo)
    assert policy["has_hooks"] is False and policy["read_only"] is None
    assert os.path.exists(repo / ".git")


def enable_worktree_config(repo: Path) -> None:
    git(repo, "config", "extensions.worktreeConfig", "true")


@pytest.mark.anyio
async def test_worktree_scope_merge_driver_blocks_merging(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    enable_worktree_config(repo)
    git(repo, "config", "--worktree", "merge.evil.driver", "touch /tmp/nao-deve-rodar")
    policy = await gitinfo.repo_policy(repo, cached=False)
    assert policy["no_merge"] == gitinfo.MERGE_DRIVER_MESSAGE.format(name="evil")


@pytest.mark.anyio
async def test_worktree_scope_filter_makes_it_read_only(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    enable_worktree_config(repo)
    git(repo, "config", "--worktree", "filter.cr.smudge", "cr -d")
    (repo / ".gitattributes").write_text("*.bin filter=cr\n")
    policy = await gitinfo.repo_policy(repo, cached=False)
    assert policy["read_only"] == gitinfo.FILTER_READ_ONLY.format(name="cr")


@pytest.mark.anyio
async def test_worktree_scope_wins_over_local(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    enable_worktree_config(repo)
    git(repo, "config", "user.email", "local@example.com")
    git(repo, "config", "--worktree", "user.email", "arvore@example.com")
    assert (await gitinfo.repo_policy(repo, cached=False))["user_email"] == "arvore@example.com"


@pytest.mark.anyio
async def test_global_attributes_file_may_be_a_symlink(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (git_home / ".gitconfig").write_text('[filter "cripto"]\n\tsmudge = cripto -d\n')
    real = tmp_path / "dotfiles" / "attributes"
    real.parent.mkdir()
    real.write_text("*.bin filter=cripto\n")
    link = git_home / ".config" / "git" / "attributes"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    policy = await gitinfo.repo_policy(repo, cached=False)
    assert policy["read_only"] == gitinfo.FILTER_READ_ONLY.format(name="cripto")


@pytest.mark.anyio
async def test_attributes_file_setting_is_relative_to_the_repository(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (git_home / ".gitconfig").write_text('[filter "cripto"]\n\tsmudge = cripto -d\n')
    (repo / "regras").write_text("*.bin filter=cripto\n")
    git(repo, "config", "core.attributesFile", "regras")
    policy = await gitinfo.repo_policy(repo, cached=False)
    assert policy["read_only"] == gitinfo.FILTER_READ_ONLY.format(name="cripto")


@pytest.mark.anyio
async def test_attributes_file_setting_expands_the_home_folder(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    (git_home / "meus-atributos").write_text("*.bin filter=cripto\n")
    (git_home / ".gitconfig").write_text(
        '[filter "cripto"]\n\tsmudge = cripto -d\n[core]\n\tattributesFile = ~/meus-atributos\n'
    )
    policy = await gitinfo.repo_policy(repo, cached=False)
    assert policy["read_only"] == gitinfo.FILTER_READ_ONLY.format(name="cripto")


@pytest.mark.anyio
async def test_tracked_gitattributes_symlink_is_not_followed(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "filter.cripto.smudge", "cripto -d")
    outside = tmp_path / "fora"
    outside.write_text("*.bin filter=cripto\n")
    (repo / ".gitattributes").symlink_to(outside)
    assert (await gitinfo.repo_policy(repo, cached=False))["read_only"] is None
