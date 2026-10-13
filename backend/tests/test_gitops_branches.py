"""Branches and merge of `gitops`, on real repositories."""

import stat
from pathlib import Path

import pytest
from git_helpers import (  # noqa: F401 (fixture)
    commit_file,
    git,
    git_home,
    make_repo,
    set_identity,
)
from test_git_details import clone_to, make_clone

from claudio_maestro import gitinfo, gitops


@pytest.fixture(autouse=True)
def fresh_policy():
    gitinfo.clear_policy_cache()
    yield
    gitinfo.clear_policy_cache()


def writable_repo(path: Path, **kwargs) -> Path:
    repo = make_repo(path, **kwargs)
    set_identity(repo)
    return repo


def executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def head(repo: Path) -> str:
    return git(repo, "symbolic-ref", "--short", "HEAD").strip()


def diverged(repo: Path) -> None:
    """`feat` and `main` both change README.md from the same commit: merging conflicts."""
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "README.md", "feat\n", "Mudar na feat")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "README.md", "main\n", "Mudar na main")


# Branch names ------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["", "   ", "-f", "a..b", "a~1", "x@{1}", "HEAD", "a\tb", "fim.lock", "a" * 256])
async def test_invalid_branch_names(tmp_path: Path, name):
    repo = writable_repo(tmp_path / "r")
    with pytest.raises(gitops.InvalidRequestError):
        await gitops.check_branch_name(repo, name)


@pytest.mark.anyio
async def test_branch_name_with_space_suggests_dashes(tmp_path: Path):
    repo = writable_repo(tmp_path / "r")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.check_branch_name(repo, "fix carrinho vazio")
    assert str(caught.value) == "Nome de branch não pode ter espaço. Por exemplo: fix-carrinho-vazio."


@pytest.mark.anyio
async def test_valid_branch_name_is_trimmed(tmp_path: Path):
    repo = writable_repo(tmp_path / "r")
    assert await gitops.check_branch_name(repo, "  feat/relatórios ") == "feat/relatórios"


# Switch --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_switch_to_a_local_branch_carries_changes(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "branch", "feat")
    (repo / "novo.txt").write_text("novo\n")
    await gitops.switch(repo, "refs/heads/feat")
    assert head(repo) == "feat"
    assert (repo / "novo.txt").read_text() == "novo\n"


@pytest.mark.anyio
async def test_switch_refuses_when_changes_would_be_overwritten(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    (repo / "README.md").write_text("sujo\n")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.switch(repo, "refs/heads/feat")
    assert str(caught.value).startswith("O git não trocou para feat: suas alterações em README.md")
    assert head(repo) == "main" and (repo / "README.md").read_text() == "sujo\n"


@pytest.mark.anyio
async def test_switch_to_a_remote_branch_creates_the_tracking_branch(tmp_path: Path, git_home):
    remote, clone = make_clone(tmp_path)
    other = tmp_path / "outro"
    clone_to(remote, other)
    set_identity(other)
    git(other, "switch", "-q", "-c", "feat/relatorios")
    commit_file(other, "r.txt", "r\n", "Relatório")
    git(other, "push", "-q", "origin", "feat/relatorios")
    set_identity(clone)
    git(clone, "fetch", "-q", "origin")
    await gitops.switch(clone, "refs/remotes/origin/feat/relatorios")
    assert head(clone) == "feat/relatorios"
    assert git(clone, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == "origin/feat/relatorios"
    # A second time, the local branch exists: just switch to it.
    git(clone, "switch", "-q", "main")
    await gitops.switch(clone, "refs/remotes/origin/feat/relatorios")
    assert head(clone) == "feat/relatorios"


@pytest.mark.anyio
async def test_switch_uses_the_longest_remote_name(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    sha = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "remote", "add", "o", "https://example.com/o.git")
    # `git remote add` refuses overlapping names, but a config can have them. Only the
    # longer one keeps a fetch refspec, or git cannot tell which remote the branch tracks.
    git(repo, "config", "--unset-all", "remote.o.fetch")
    git(repo, "config", "remote.o/fork.url", "https://example.com/f.git")
    git(repo, "config", "remote.o/fork.fetch", "+refs/heads/*:refs/remotes/o/fork/*")
    git(repo, "update-ref", "refs/remotes/o/fork/topico", sha)
    await gitops.switch(repo, "refs/remotes/o/fork/topico")
    assert head(repo) == "topico"


@pytest.mark.anyio
async def test_switch_refuses_unknown_refs(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    for ref in ("refs/heads/nao-existe", "refs/tags/v1", "main", "HEAD"):
        with pytest.raises(gitops.NotFoundError):
            await gitops.switch(repo, ref)


@pytest.mark.anyio
async def test_branch_named_like_an_option_is_never_an_option(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "update-ref", "refs/heads/-f", git(repo, "rev-parse", "HEAD").strip())
    (repo / "README.md").write_text("sujo\n")
    await gitops.switch(repo, "refs/heads/-f")
    assert head(repo) == "-f"
    assert (repo / "README.md").read_text() == "sujo\n"  # not a forced switch


@pytest.mark.anyio
async def test_switch_runs_no_checkout_hook(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "branch", "feat")
    mark = tmp_path / "marca"
    executable(repo / ".git" / "hooks" / "post-checkout", f"#!/bin/sh\ntouch {mark}\n")
    await gitops.switch(repo, "refs/heads/feat")
    assert not mark.exists()


# Create branch ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_branch_switches_to_it_with_the_changes(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "README.md").write_text("sujo\n")
    assert await gitops.create_branch(repo, "fix/frete") == "fix/frete"
    assert head(repo) == "fix/frete"
    assert (repo / "README.md").read_text() == "sujo\n"


@pytest.mark.anyio
async def test_create_branch_refuses_an_existing_one(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "branch", "feat")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.create_branch(repo, "feat")
    assert str(caught.value) == "Já existe uma branch feat."


@pytest.mark.anyio
async def test_create_branch_without_commits(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r", commit=False)
    assert await gitops.create_branch(repo, "comeco") == "comeco"
    assert head(repo) == "comeco"


# Merge -----------------------------------------------------------------------------


@pytest.mark.anyio
async def test_merge_without_conflict(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "f.txt", "f\n", "Feat")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "Main")
    result = await gitops.merge(repo, "refs/heads/feat")
    assert result == gitops.MergeResult(conflicts=False)
    assert git(repo, "log", "-1", "--format=%s").strip() == "Merge branch 'feat'"
    assert (repo / "f.txt").exists()


@pytest.mark.anyio
async def test_merge_with_conflict_stays_in_the_merge(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    result = await gitops.merge(repo, "refs/heads/feat")
    assert result.conflicts is True
    state = await gitinfo.repo_state(repo, cached=False)
    assert state["merging"] and state["conflicts"] == ["README.md"]
    assert state["merge_branch"] == "feat"
    assert "<<<<<<< " in (repo / "README.md").read_text()


@pytest.mark.anyio
async def test_merge_of_a_remote_branch_names_it(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "remote", "add", "origin", "https://example.com/r.git")
    git(repo, "switch", "-q", "-c", "outra")
    commit_file(repo, "o.txt", "o\n", "Outra")
    git(repo, "update-ref", "refs/remotes/origin/outra", "HEAD")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "Main")
    await gitops.merge(repo, "refs/remotes/origin/outra")
    assert git(repo, "log", "-1", "--format=%s").strip() == "Merge remote-tracking branch 'origin/outra'"


@pytest.mark.anyio
async def test_merge_refuses_while_merging_and_with_overwrite(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    (repo / "README.md").write_text("sujo\n")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.merge(repo, "refs/heads/feat")
    assert str(caught.value).startswith("O git não mesclou feat: suas alterações em README.md")
    assert not await gitops._merging(repo)
    git(repo, "checkout", "--", "README.md")
    await gitops.merge(repo, "refs/heads/feat")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.merge(repo, "refs/heads/feat")
    assert str(caught.value) == gitops.MERGING_MESSAGE


@pytest.mark.anyio
async def test_merge_refuses_a_merge_driver_in_use(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    mark = tmp_path / "marca"
    git(repo, "config", "merge.meu.driver", f"touch {mark}; false")
    commit_file(repo, ".gitattributes", "*.txt merge=meu\n", "Atributos")
    diverged(repo)
    with pytest.raises(gitops.ReadOnlyError) as caught:
        await gitops.merge(repo, "refs/heads/feat")
    assert str(caught.value) == gitinfo.MERGE_DRIVER_MESSAGE.format(name="meu")
    assert not mark.exists() and not await gitops._merging(repo)


@pytest.mark.anyio
async def test_merge_runs_no_hook_or_editor(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    marks = tmp_path / "marcas"
    marks.mkdir()
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "f.txt", "f\n", "Feat")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "Main")
    # Installed only now: the commits above are the test's own, made by plain git.
    for name in ("pre-merge-commit", "commit-msg", "post-merge", "prepare-commit-msg"):
        executable(repo / ".git" / "hooks" / name, f"#!/bin/sh\ntouch {marks / name}\n")
    editor = executable(tmp_path / "editor", f"#!/bin/sh\ntouch {marks / 'editor'}\n")
    git(repo, "config", "core.editor", str(editor))
    await gitops.merge(repo, "refs/heads/feat")
    assert list(marks.iterdir()) == []


@pytest.mark.anyio
async def test_merge_abort(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.merge_abort(repo)
    assert str(caught.value) == gitops.NOT_MERGING
    await gitops.merge(repo, "refs/heads/feat")
    await gitops.merge_abort(repo)
    assert not await gitops._merging(repo)
    assert (repo / "README.md").read_text() == "main\n"


# Resolve and finish -----------------------------------------------------------------


@pytest.mark.anyio
async def test_mark_resolved_refuses_files_with_markers_or_not_in_conflict(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    commit_file(repo, "outro.txt", "o\n", "Outro")
    await gitops.merge(repo, "refs/heads/feat")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.mark_resolved(repo, ["README.md"])
    assert str(caught.value) == gitops.MARKERS_LEFT.format(path="README.md")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.mark_resolved(repo, ["outro.txt"])
    assert str(caught.value) == gitops.NOT_CONFLICTED.format(path="outro.txt")


@pytest.mark.anyio
async def test_resolve_and_finish_the_merge(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    await gitops.merge(repo, "refs/heads/feat")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.merge_continue(repo, "Merge branch 'feat'")
    assert str(caught.value) == gitops.STILL_CONFLICTED
    (repo / "README.md").write_text("main e feat\n=======\n")  # a lone ======= is not a marker
    await gitops.mark_resolved(repo, ["README.md"])
    assert (await gitinfo.repo_state(repo, cached=False))["conflicts"] == []
    sha = await gitops.merge_continue(repo, "  #12 Merge branch 'feat'  ")
    assert len(git(repo, "log", "-1", "--format=%P").split()) == 2
    assert git(repo, "log", "-1", "--format=%B").strip() == "#12 Merge branch 'feat'"
    assert sha == git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(gitops.InvalidRequestError):
        await gitops.merge_continue(repo, "De novo")


@pytest.mark.anyio
async def test_resolve_a_file_deleted_on_one_side(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    git(repo, "rm", "-q", "README.md")
    git(repo, "commit", "-q", "-m", "Apagar")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "README.md", "main\n", "Mudar")
    assert (await gitops.merge(repo, "refs/heads/feat")).conflicts
    (repo / "README.md").unlink()
    await gitops.mark_resolved(repo, ["README.md"])
    await gitops.merge_continue(repo, "Merge")
    assert git(repo, "ls-files", "README.md") == ""


def test_markers_check_does_not_follow_a_link(tmp_path: Path):
    outside = tmp_path / "fora.txt"
    outside.write_text("<<<<<<< HEAD\n")
    (tmp_path / "link").symlink_to(outside)
    assert gitops._has_markers(outside) is True
    assert gitops._has_markers(tmp_path / "link") is False  # the link's text is its target
    assert gitops._has_markers(tmp_path / "sumiu") is False
    (tmp_path / "meio.txt").write_text("a\n>>>>>>> feat\n")
    assert gitops._has_markers(tmp_path / "meio.txt") is True
    (tmp_path / "igual.txt").write_text("título\n=======\n<<<<<<<sem espaço\n")
    assert gitops._has_markers(tmp_path / "igual.txt") is False


@pytest.mark.anyio
async def test_merge_continue_without_identity_leaves_the_merge_alone(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    diverged(repo)
    await gitops.merge(repo, "refs/heads/feat")
    (repo / "README.md").write_text("os dois\n")
    await gitops.mark_resolved(repo, ["README.md"])
    git(repo, "config", "--unset", "user.name")
    git(repo, "config", "--unset", "user.email")
    git(repo, "config", "user.useConfigOnly", "true")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.merge_continue(repo, "Merge branch 'feat'")
    assert str(caught.value) == gitops.IDENTITY_MESSAGE
    assert await gitops._merging(repo)


@pytest.mark.anyio
async def test_create_branch_refuses_a_name_that_clashes_with_another(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "branch", "feat")
    git(repo, "branch", "area/sub")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.create_branch(repo, "feat/x")
    assert str(caught.value) == "Já existe uma branch chamada feat, que impede criar feat/x."
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.create_branch(repo, "area")
    assert str(caught.value) == "Já existem branches dentro de area/, o que impede criar area."
    assert head(repo) == "main"


@pytest.mark.anyio
async def test_merge_ignores_merge_options_of_the_config(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    mark = tmp_path / "marca"
    signer = executable(tmp_path / "gpg", f"#!/bin/sh\ntouch {mark}\nexit 1\n")
    git(repo, "config", "gpg.program", str(signer))
    git(repo, "config", "branch.main.mergeOptions", "-S --squash --verify-signatures")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "f.txt", "f\n", "Feat")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "Main")
    result = await gitops.merge(repo, "refs/heads/feat")
    assert result == gitops.MergeResult(conflicts=False)
    assert not mark.exists()
    assert not await gitops._merging(repo)
    assert len(git(repo, "log", "-1", "--format=%P").split()) == 2


@pytest.mark.anyio
async def test_merge_makes_a_merge_commit_whatever_merge_ff_says(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "config", "merge.ff", "only")
    git(repo, "switch", "-q", "-c", "feat")
    commit_file(repo, "f.txt", "f\n", "Feat")
    git(repo, "switch", "-q", "main")
    commit_file(repo, "m.txt", "m\n", "Main")
    assert (await gitops.merge(repo, "refs/heads/feat")) == gitops.MergeResult(conflicts=False)
    assert git(repo, "log", "-1", "--format=%s").strip() == "Merge branch 'feat'"
