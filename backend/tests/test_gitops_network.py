"""Pull, push, publish, sync and fetch of `gitops`, against a bare repository on disk."""

from pathlib import Path

import pytest
from git_helpers import commit_file, git, git_home, set_identity  # noqa: F401 (fixture)
from test_gitinfo_fetch import LOCAL_OK, make_clone, push_from_elsewhere

from claudio_maestro import gitfetch, gitinfo, gitops

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def local_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", LOCAL_OK)
    gitinfo.clear_policy_cache()


def clone_with_identity(tmp_path: Path) -> tuple[Path, Path]:
    remote, clone = make_clone(tmp_path)
    set_identity(clone)
    return remote, clone


def sha(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


async def test_pull_fast_forwards(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    result = await gitops.pull(clone)
    assert result == gitops.MergeResult(conflicts=False)
    assert sha(clone, "HEAD") == sha(remote, "main")
    assert gitfetch.registry.fields(clone)["fetched_at"] is not None


async def test_pull_with_nothing_new_is_a_no_op(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    before = sha(clone, "HEAD")
    assert (await gitops.pull(clone)).conflicts is False
    assert sha(clone, "HEAD") == before


async def test_pull_merges_and_can_stop_in_conflict(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    push_from_elsewhere(tmp_path, remote, name="README.md")
    (clone / "README.md").write_text("meu\n")
    git(clone, "commit", "-q", "-am", "meu")
    result = await gitops.pull(clone)
    assert result.conflicts is True
    state = await gitinfo.repo_state(clone, cached=False)
    assert state["merging"] and state["conflicts"] == ["README.md"]
    assert state["merge_branch"] == "origin/main"


async def test_pull_refuses_with_a_merge_driver(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "config", "merge.meu.driver", "false")
    commit_file(clone, ".gitattributes", "* merge=meu\n", "Atributos")
    with pytest.raises(gitops.ReadOnlyError) as caught:
        await gitops.pull(clone)
    assert str(caught.value) == gitinfo.MERGE_DRIVER_MESSAGE.format(name="meu")


async def test_pull_refuses_detached(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "--detach")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.pull(clone)
    assert str(caught.value) == gitinfo.DETACHED_MESSAGE


async def test_pull_failure_explains_and_keeps_the_output(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "config", "remote.origin.url", str(tmp_path / "sumiu.git"))
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.pull(clone)
    assert str(caught.value).startswith("Não foi possível baixar do remoto")
    assert caught.value.output


async def test_pull_ignores_merge_options_of_the_repository(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    git(clone, "config", "branch.main.mergeOptions", "--squash")
    git(clone, "config", "merge.ff", "only")
    push_from_elsewhere(tmp_path, remote)
    commit_file(clone, "meu.txt", "meu\n", "Meu")
    assert (await gitops.pull(clone)).conflicts is False
    assert len(git(clone, "log", "-1", "--format=%P").split()) == 2


async def test_push_and_its_rejection(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    commit_file(clone, "a.txt", "a\n", "A")
    await gitops.push(clone)
    assert sha(remote, "main") == sha(clone, "HEAD")
    push_from_elsewhere(tmp_path, remote)
    commit_file(clone, "b.txt", "b\n", "B")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.push(clone)
    assert str(caught.value) == (
        "O envio não foi feito: origin/main recebeu 1 commit que você ainda não tem. "
        "Sincronize para baixar e enviar."
    )
    assert "[rejected]" in caught.value.output
    assert sha(clone, "origin/main") == sha(remote, "main")  # fetched, so the row shows 1↓


async def test_push_refuses_detached(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "--detach")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.push(clone)
    assert str(caught.value) == gitinfo.DETACHED_MESSAGE


async def test_push_without_upstream_says_so(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "-c", "nova")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.push(clone)
    assert str(caught.value) == gitinfo.NO_UPSTREAM_MESSAGE


async def test_sync_pulls_then_pushes(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    commit_file(clone, "meu.txt", "meu\n", "Meu")
    result = await gitops.sync(clone)
    assert result.conflicts is False
    assert sha(remote, "main") == sha(clone, "HEAD")
    assert len(git(clone, "log", "-1", "--format=%P").split()) == 2


async def test_sync_stops_at_a_conflict_without_pushing(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    push_from_elsewhere(tmp_path, remote, name="README.md")
    before = sha(remote, "main")
    (clone / "README.md").write_text("meu\n")
    git(clone, "commit", "-q", "-am", "meu")
    assert (await gitops.sync(clone)).conflicts is True
    assert sha(remote, "main") == before


async def test_publish_and_fetch_repo(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "-c", "feat/x")
    commit_file(clone, "x.txt", "x\n", "X")
    assert await gitops.publish(clone) == "origin"
    assert sha(remote, "feat/x") == sha(clone, "HEAD")
    push_from_elsewhere(tmp_path, remote)
    git(clone, "switch", "-q", "main")
    await gitops.fetch_repo(clone)
    assert sha(clone, "origin/main") == sha(remote, "main")
    assert sha(clone, "HEAD") != sha(remote, "main")  # fetched, not merged


async def test_lfs_repository_cannot_push(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "config", "filter.lfs.clean", "git-lfs clean -- %f")
    (clone / ".gitattributes").write_text("*.psd filter=lfs\n")
    git(clone, "add", ".gitattributes")
    git(clone, "commit", "-q", "-m", "lfs")
    with pytest.raises(gitops.ReadOnlyError):
        await gitops.push(clone)


async def test_push_refuses_a_branch_that_tracks_another_name(tmp_path: Path, git_home):
    remote, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "-c", "feat/x", "origin/main")
    commit_file(clone, "x.txt", "x\n", "X")
    before = sha(remote, "main")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.push(clone)
    assert str(caught.value) == gitinfo.RENAMED_UPSTREAM_MESSAGE.format(upstream="origin/main")
    assert sha(remote, "main") == before


async def test_sync_refuses_a_renamed_upstream_before_touching_the_repository(
    tmp_path: Path, git_home
):
    remote, clone = clone_with_identity(tmp_path)
    git(clone, "switch", "-q", "-c", "feat/x", "origin/main")
    push_from_elsewhere(tmp_path, remote)
    commit_file(clone, "x.txt", "x\n", "X")
    head, before = sha(clone, "HEAD"), sha(remote, "main")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.sync(clone)
    assert str(caught.value) == gitinfo.RENAMED_UPSTREAM_MESSAGE.format(upstream="origin/main")
    assert sha(clone, "HEAD") == head  # no merge commit
    assert not (clone / "remoto.txt").exists()  # the pull did not happen
    assert sha(remote, "main") == before


async def test_publish_refuses_a_branch_that_has_an_upstream(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.publish(clone)
    assert str(caught.value) == gitinfo.HAS_UPSTREAM_MESSAGE.format(upstream="origin/main")


async def test_pull_and_push_with_an_unsupported_protocol(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "config", "remote.origin.url", "http://example.invalid/x.git")
    commit_file(clone, "x.txt", "x\n", "X")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.push(clone)
    assert str(caught.value) == gitinfo.URL_MESSAGE
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.pull(clone)
    assert gitinfo.URL_MESSAGE in str(caught.value)


async def test_pull_refuses_a_remote_without_url(tmp_path: Path, git_home):
    _, clone = clone_with_identity(tmp_path)
    git(clone, "config", "--unset", "remote.origin.url")
    before = sha(clone, "HEAD")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.pull(clone)
    assert str(caught.value) == gitops.NO_URL_MESSAGE.format(remote="origin")
    assert sha(clone, "HEAD") == before
