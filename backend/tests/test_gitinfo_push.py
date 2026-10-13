"""`gitinfo.push_upstream` and `publish_branch`: the same throwaway-repository design as the fetch."""

import stat
from pathlib import Path

import pytest
from git_helpers import git, make_repo
from test_gitinfo_fetch import (
    LOCAL_OK,
    commit_file,
    init_bare,
    make_clone,
    push_from_elsewhere,
)

from claudio_maestro import gitinfo

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def local_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", LOCAL_OK)


def executable(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def sha(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


async def test_push_sends_the_branch_and_moves_the_tracking_ref(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    commit_file(clone, "a.txt")
    await gitinfo.push_upstream(clone)
    assert sha(remote, "main") == sha(clone, "HEAD")
    assert sha(clone, "origin/main") == sha(clone, "HEAD")


async def test_push_never_forces(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    before = sha(remote, "main")
    commit_file(clone, "meu.txt")
    with pytest.raises(gitinfo.RemoteError) as caught:
        await gitinfo.push_upstream(clone)
    assert "[rejected]" in caught.value.output
    assert sha(remote, "main") == before


async def test_push_ignores_the_repository_config(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    marks = tmp_path / "marcas"
    marks.mkdir()
    receive = executable(
        tmp_path / "receive", f"#!/bin/sh\ntouch {marks / 'receive'}\nexec git-receive-pack \"$@\"\n"
    )
    git(clone, "config", "remote.origin.receivepack", str(receive))
    git(clone, "config", "credential.helper", f"!touch {marks / 'credential'}")
    git(clone, "config", "core.sshCommand", f"touch {marks / 'ssh'}")
    git(clone, "config", "push.gpgSign", "true")
    git(clone, "config", f"url.{tmp_path / 'nao-existe.git'}.insteadOf", str(remote))
    executable(clone / ".git" / "hooks" / "pre-push", f"#!/bin/sh\ntouch {marks / 'pre-push'}\n")
    commit_file(clone, "a.txt")
    await gitinfo.push_upstream(clone)
    assert sha(remote, "main") == sha(clone, "HEAD")
    assert list(marks.iterdir()) == []


async def test_push_uses_the_push_url_and_checks_it(tmp_path: Path, monkeypatch):
    remote, clone = make_clone(tmp_path)
    other = tmp_path / "outro.git"
    init_bare(other)
    git(clone, "config", "remote.origin.pushurl", str(other))
    commit_file(clone, "a.txt")
    await gitinfo.push_upstream(clone)
    assert sha(other, "main") == sha(clone, "HEAD")
    git(clone, "config", "remote.origin.pushurl", "ext::sh -c touch% /tmp/x")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.push_upstream(clone)
    assert str(caught.value) == gitinfo.URL_MESSAGE
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", ("https", "ssh"))
    git(clone, "config", "--unset", "remote.origin.pushurl")
    with pytest.raises(gitinfo.GitError):
        await gitinfo.push_upstream(clone)  # a local path is the file transport


async def test_push_without_upstream_or_detached(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.push_upstream(repo)
    assert str(caught.value) == gitinfo.NO_UPSTREAM_MESSAGE
    _, clone = make_clone(tmp_path)
    git(clone, "switch", "-q", "--detach")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.push_upstream(clone)
    assert str(caught.value) == gitinfo.DETACHED_MESSAGE


async def test_publish_to_origin_sets_the_upstream(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    git(clone, "switch", "-q", "-c", "feat/nova")
    commit_file(clone, "n.txt")
    assert await gitinfo.publish_branch(clone) == "origin"
    assert sha(remote, "feat/nova") == sha(clone, "HEAD")
    assert git(clone, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == "origin/feat/nova"
    assert sha(clone, "origin/feat/nova") == sha(clone, "HEAD")


async def test_publish_picks_the_only_remote_and_refuses_many(tmp_path: Path):
    fork = tmp_path / "fork.git"
    init_bare(fork)
    repo = make_repo(tmp_path / "r")
    git(repo, "remote", "add", "fork", str(fork))
    assert await gitinfo.publish_branch(repo) == "fork"
    git(repo, "remote", "add", "outro", str(fork))
    git(repo, "switch", "-q", "-c", "b")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.publish_branch(repo)
    assert str(caught.value) == gitinfo.MANY_REMOTES_MESSAGE


async def test_publish_refuses_detached_unborn_and_no_remote(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.publish_branch(repo)
    assert str(caught.value) == gitinfo.NO_REMOTE_MESSAGE
    git(repo, "switch", "-q", "--detach")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.publish_branch(repo)
    assert str(caught.value) == gitinfo.DETACHED_MESSAGE
    empty = make_repo(tmp_path / "vazio", commit=False)
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.publish_branch(empty)
    assert str(caught.value) == gitinfo.NO_COMMITS_MESSAGE


async def test_fetch_failure_carries_the_output(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    git(clone, "config", "remote.origin.url", str(tmp_path / "sumiu.git"))
    with pytest.raises(gitinfo.RemoteError) as caught:
        await gitinfo.fetch_upstream(clone)
    assert caught.value.output


async def test_push_refuses_a_branch_that_tracks_another_name(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    git(clone, "switch", "-q", "-c", "feat/x", "origin/main")
    commit_file(clone, "x.txt")
    before = sha(remote, "main")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.push_upstream(clone)
    assert str(caught.value) == gitinfo.RENAMED_UPSTREAM_MESSAGE.format(upstream="origin/main")
    assert sha(remote, "main") == before
    assert git(remote, "branch", "--list", "feat/x").strip() == ""


async def test_publish_refuses_a_branch_that_already_has_an_upstream(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    other = tmp_path / "outro.git"
    init_bare(other)
    git(clone, "remote", "add", "fork", str(other))
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.publish_branch(clone)
    assert str(caught.value) == gitinfo.HAS_UPSTREAM_MESSAGE.format(upstream="origin/main")
    assert git(other, "branch", "--list").strip() == ""
    assert git(clone, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == "origin/main"


@pytest.mark.parametrize("url", ["http://example.invalid/x.git", "ext::sh -c true", "git://example.invalid/x"])
async def test_manual_actions_say_the_protocol_is_not_supported(tmp_path: Path, url: str):
    _, clone = make_clone(tmp_path)
    git(clone, "config", "remote.origin.url", url)
    commit_file(clone, "a.txt")
    with pytest.raises(gitinfo.GitError) as caught:
        await gitinfo.push_upstream(clone)
    assert str(caught.value) == gitinfo.URL_MESSAGE
    assert "automática" not in gitinfo.URL_MESSAGE
    assert "terminal" in gitinfo.URL_MESSAGE
