"""`gitinfo.fetch_upstream`: updates the tracking branch and never runs repository config."""

import http.server
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest
from git_helpers import GIT_ENV, git, make_repo

from claudio_maestro import gitinfo

pytestmark = pytest.mark.anyio

# The default allows only https and ssh. The tests' "remote" is a folder on disk, so
# they add the local transport; everything else in the safe setup stays.
LOCAL_OK = (*gitinfo.FETCH_ALLOWED_PROTOCOLS, "file")


@pytest.fixture
def local_remotes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", LOCAL_OK)


def init_bare(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)], check=True, env=GIT_ENV)


def clone_to(remote: Path, path: Path) -> None:
    subprocess.run(["git", "clone", "-q", str(remote), str(path)], check=True, env=GIT_ENV)


def commit_file(repo: Path, name: str, text: str = "x\n") -> None:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


def make_clone(tmp_path: Path) -> tuple[Path, Path]:
    """A bare "remote" and a repository tracking it with one pushed commit."""
    remote = tmp_path / "remote.git"
    init_bare(remote)
    clone = make_repo(tmp_path / "clone")
    git(clone, "remote", "add", "origin", str(remote))
    git(clone, "push", "-q", "-u", "origin", "main")
    return remote, clone


def push_from_elsewhere(tmp_path: Path, remote: Path, name: str = "remoto.txt") -> Path:
    other = tmp_path / "other"
    if not other.exists():
        clone_to(remote, other)
    commit_file(other, name)
    git(other, "push", "-q")
    return other


def script(path: Path, body: str) -> Path:
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


# Updating the tracking branch -------------------------------------------------


async def test_fetch_updates_the_tracking_branch(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    assert (await gitinfo.repo_status(clone)).behind == 0
    assert await gitinfo.fetch_upstream(clone) is True
    status = await gitinfo.repo_status(clone)
    assert (status.upstream, status.ahead, status.behind) == ("origin/main", 0, 1)


async def test_fetch_follows_a_force_push(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    other = push_from_elsewhere(tmp_path, remote)
    await gitinfo.fetch_upstream(clone)
    git(other, "reset", "-q", "--hard", "HEAD~1")
    commit_file(other, "outro.txt")
    git(other, "push", "-q", "--force")
    assert await gitinfo.fetch_upstream(clone) is True
    assert git(clone, "rev-parse", "origin/main").strip() == git(other, "rev-parse", "HEAD").strip()


async def test_fetch_uses_the_upstream_of_a_differently_named_branch(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    git(clone, "checkout", "-q", "-b", "trabalho")
    git(clone, "branch", "-q", "--set-upstream-to=origin/main")
    push_from_elsewhere(tmp_path, remote)
    assert await gitinfo.fetch_upstream(clone) is True
    assert (await gitinfo.repo_status(clone)).behind == 1


async def test_fetch_does_not_touch_other_branches_tags_or_fetch_head(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    other = push_from_elsewhere(tmp_path, remote)
    git(other, "tag", "v1")
    git(other, "push", "-q", "origin", "v1")
    git(other, "push", "-q", "origin", "HEAD:refs/heads/outra")
    await gitinfo.fetch_upstream(clone)
    assert git(clone, "tag").strip() == ""
    assert "origin/outra" not in git(clone, "branch", "-r")
    assert not (clone / ".git" / "FETCH_HEAD").exists()


async def test_fetch_does_not_change_the_working_tree(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    (clone / "README.md").write_text("mudou\n")
    head = git(clone, "rev-parse", "HEAD")
    await gitinfo.fetch_upstream(clone)
    assert git(clone, "rev-parse", "HEAD") == head
    assert (clone / "README.md").read_text() == "mudou\n"


# Nothing to fetch ---------------------------------------------------------------


async def test_no_upstream_does_nothing(tmp_path: Path, local_remotes):
    repo = make_repo(tmp_path / "r")
    assert await gitinfo.fetch_upstream(repo) is False


async def test_detached_head_does_nothing(tmp_path: Path, local_remotes):
    _, clone = make_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach")
    assert await gitinfo.fetch_upstream(clone) is False


async def test_local_upstream_does_nothing(tmp_path: Path, local_remotes):
    repo = make_repo(tmp_path / "r")
    git(repo, "branch", "base")
    git(repo, "branch", "--set-upstream-to=base")
    assert git(repo, "config", "branch.main.remote").strip() == "."
    assert await gitinfo.fetch_upstream(repo) is False


async def test_unborn_branch_does_nothing(tmp_path: Path, local_remotes):
    repo = make_repo(tmp_path / "r", commit=False)
    assert await gitinfo.fetch_upstream(repo) is False


async def test_upstream_that_is_a_url_does_nothing(tmp_path: Path, local_remotes):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "branch.main.remote", "https://example.invalid/x.git")
    git(repo, "config", "branch.main.merge", "refs/heads/main")
    assert await gitinfo.fetch_upstream(repo) is False


# Failures -----------------------------------------------------------------------


async def test_default_protocols_refuse_a_local_remote(tmp_path: Path):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    assert gitinfo.FETCH_ALLOWED_PROTOCOLS == ("https", "ssh")
    with pytest.raises(gitinfo.GitError) as error:
        await gitinfo.fetch_upstream(clone)
    assert "\n" not in str(error.value) and str(error.value)
    assert (await gitinfo.repo_status(clone)).behind == 0


async def test_failure_is_a_one_line_message(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    for child in remote.rglob("*"):
        if child.is_file():
            child.chmod(0o644)
    git(clone, "remote", "set-url", "origin", str(tmp_path / "nao-existe.git"))
    with pytest.raises(gitinfo.GitError) as error:
        await gitinfo.fetch_upstream(clone)
    assert "\n" not in str(error.value) and str(error.value)


async def test_failure_message_hides_credentials_in_urls(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)

    async def failing(repo, *args, **kwargs):
        if args[0] == "fetch":
            return 128, "", "fatal: unable to access 'https://usuario:segredo@example.com/x.git/': 503"
        return await real(repo, *args, **kwargs)

    real = gitinfo.run_git
    monkeypatch.setattr(gitinfo, "run_git", failing)
    with pytest.raises(gitinfo.GitError) as error:
        await gitinfo.fetch_upstream(clone)
    assert "segredo" not in str(error.value) and "usuario" not in str(error.value)
    assert "example.com" in str(error.value)


async def test_fetch_times_out(tmp_path: Path, local_remotes):
    _, clone = make_clone(tmp_path)
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone, timeout=0)


# The command line ---------------------------------------------------------------


async def test_fetch_command_and_environment(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    monkeypatch.setenv("SSH_ASKPASS", "/bin/evil")
    monkeypatch.setenv("GIT_ASKPASS", "/bin/evil")
    monkeypatch.setenv("GIT_SSH_COMMAND", "evil")
    seen: list[tuple[tuple[str, ...], dict[str, str]]] = []
    real = gitinfo._exec_now

    async def spy(repo, args, timeout, extra_config, limit, extra_env=None, own_group=False):
        seen.append((args, gitinfo._env(extra_config, extra_env)))
        assert own_group is (args[0] == "fetch")  # only the fetch gets its own process group
        return await real(repo, args, timeout, extra_config, limit, extra_env, own_group)

    monkeypatch.setattr(gitinfo, "_exec_now", spy)
    await gitinfo.fetch_upstream(clone)
    (args, env), = [item for item in seen if item[0][0] == "fetch"]
    assert args == (
        "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
        "--no-prune", "--upload-pack=git-upload-pack", "--", "origin", "+refs/heads/main:refs/remotes/origin/main",
    )
    assert env["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes -o ConnectTimeout=10"
    assert env["SSH_ASKPASS_REQUIRE"] == "never"
    assert env["GIT_ALLOW_PROTOCOL"] == "https:ssh:file"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "SSH_ASKPASS" not in env and "GIT_ASKPASS" not in env
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    for key, value in (
        ("credential.helper", ""), ("core.askPass", ""), ("protocol.allow", "never"),
        ("protocol.https.allow", "always"), ("protocol.ssh.allow", "always"),
        ("protocol.file.allow", "always"),
        ("fetch.recurseSubmodules", "false"), ("submodule.recurse", "false"), ("gc.auto", "0"),
        ("maintenance.auto", "false"), ("fetch.writeCommitGraph", "false"),
        ("core.hooksPath", "/dev/null"), ("core.alternateRefsCommand", ""),
        ("fetch.bundleURI", ""), ("transfer.bundleURI", "false"), ("ssh.variant", "ssh"),
    ):
        assert config[key] == value, key


async def test_plain_commands_keep_the_old_environment():
    env = gitinfo._env()
    assert "GIT_SSH_COMMAND" not in env and "SSH_ASKPASS_REQUIRE" not in env


# Repository config never runs a program -------------------------------------------


def raw_fetch(clone: Path, extra_env: dict[str, str] | None = None) -> None:
    """The same fetch with none of the protections, to prove a marker would be created."""
    env = {**GIT_ENV, **os.environ, "GIT_TERMINAL_PROMPT": "0", **(extra_env or {})}
    subprocess.run(
        ["git", "-C", str(clone), "fetch", "-q", "origin"], env=env, capture_output=True, timeout=30,
    )


async def test_core_ssh_command_is_not_run(tmp_path: Path, local_remotes):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-ssh"
    evil = script(tmp_path / "evil-ssh.sh", f"touch {marker}\nexit 1")
    git(clone, "remote", "set-url", "origin", "ssh://127.0.0.1:1/repo.git")
    git(clone, "config", "core.sshCommand", str(evil))
    raw_fetch(clone)
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_core_ask_pass_is_not_run(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-askpass"
    evil = script(tmp_path / "evil-askpass.sh", f"touch {marker}\necho x")
    with unauthorized_server() as url:
        monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", (*LOCAL_OK, "http"))
        git(clone, "remote", "set-url", "origin", url)
        git(clone, "config", "core.askPass", str(evil))
        raw_fetch(clone)
        assert marker.exists(), "control: without the protections the program runs"
        marker.unlink()
        with pytest.raises(gitinfo.GitError):
            await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_repository_credential_helper_is_not_run(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-helper"
    evil = script(tmp_path / "evil-helper.sh", f"touch {marker}")
    with unauthorized_server() as url:
        monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", (*LOCAL_OK, "http"))
        git(clone, "remote", "set-url", "origin", url)
        git(clone, "config", "credential.helper", f"!{evil}")
        git(clone, "config", f"credential.{url}.helper", f"!{evil}")
        raw_fetch(clone)
        assert marker.exists(), "control: without the protections the program runs"
        marker.unlink()
        with pytest.raises(gitinfo.GitError):
            await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_user_credential_helper_still_runs(tmp_path: Path, local_remotes, monkeypatch):
    # The helpers in the user's own git config (system and global) are how https logins
    # work; only the repository's are dropped.
    _, clone = make_clone(tmp_path)
    repo_marker = tmp_path / "marker-repo-helper"
    user_marker = tmp_path / "marker-user-helper"
    repo_helper = script(tmp_path / "repo-helper.sh", f"touch {repo_marker}")
    user_helper = script(tmp_path / "user-helper.sh", f"touch {user_marker}")
    home = tmp_path / "fakehome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    with unauthorized_server() as url:
        (home / ".gitconfig").write_text(
            f"[credential]\n\thelper = !{user_helper}\n[credential \"{url}\"]\n\thelper = !{user_helper}\n"
        )
        monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", (*LOCAL_OK, "http"))
        git(clone, "remote", "set-url", "origin", url)
        git(clone, "config", "credential.helper", f"!{repo_helper}")
        with pytest.raises(gitinfo.GitError):
            await gitinfo.fetch_upstream(clone)
    assert user_marker.exists()
    assert not repo_marker.exists()


async def test_remote_helper_program_is_not_run(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-vcs"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "git-remote-evil", f"touch {marker}\nexit 1")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    git(clone, "config", "remote.origin.vcs", "evil")
    raw_fetch(clone, {"PATH": os.environ["PATH"]})
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_ext_transport_enabled_by_the_repository_is_not_run(tmp_path: Path, local_remotes):
    # `ext::` runs any command. Git keeps it off by default, but a repository can turn it
    # on for itself with `protocol.ext.allow` (and reach it through `url.<base>.insteadOf`).
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-ext"
    evil = script(tmp_path / "evil-ext.sh", f"touch {marker}\nexit 1")
    git(clone, "remote", "set-url", "origin", "https://example.invalid/repo.git")
    git(clone, "config", f"url.ext::{evil} .insteadOf", "https://example.invalid/")
    git(clone, "config", "protocol.ext.allow", "always")
    raw_fetch(clone)
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_remote_helper_enabled_by_the_repository_is_not_run(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-helper-allowed"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script(bin_dir / "git-remote-evil", f"touch {marker}\nexit 1")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    git(clone, "remote", "set-url", "origin", "evil::alguma-coisa")
    git(clone, "config", "protocol.evil.allow", "always")
    raw_fetch(clone, {"PATH": os.environ["PATH"]})
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_git_proxy_command_is_not_run(tmp_path: Path, local_remotes):
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-proxy"
    evil = script(tmp_path / "evil-proxy.sh", f"touch {marker}\nexit 1")
    git(clone, "remote", "set-url", "origin", "git://127.0.0.1:1/repo.git")
    git(clone, "config", "core.gitProxy", str(evil))
    raw_fetch(clone)
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_hooks_and_fsmonitor_are_not_run(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    marker = tmp_path / "marker-hook"
    evil = script(tmp_path / "evil.sh", f"touch {marker}")
    git(clone, "config", "core.hooksPath", str(tmp_path / "hooks"))
    (tmp_path / "hooks").mkdir()
    script(tmp_path / "hooks" / "reference-transaction", f"touch {marker}")
    git(clone, "config", "core.fsmonitor", str(evil))
    assert await gitinfo.fetch_upstream(clone) is True
    assert not marker.exists()


async def test_alternate_refs_command_is_not_run(tmp_path: Path, local_remotes):
    # Git runs this command while negotiating, once for each alternate object store.
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    marker = tmp_path / "marker-alternates"
    evil = script(tmp_path / "evil-alt.sh", f"touch {marker}")
    (clone / ".git" / "objects" / "info").mkdir(exist_ok=True)
    (clone / ".git" / "objects" / "info" / "alternates").write_text(f"{remote / 'objects'}\n")
    git(clone, "config", "core.alternateRefsCommand", str(evil))
    git(clone, "config", "core.alternateRefsPrefixes", "refs/")
    raw_fetch(clone)
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    assert await gitinfo.fetch_upstream(clone) is True
    assert not marker.exists()
    assert (await gitinfo.repo_status(clone)).behind == 1


async def test_remote_upload_pack_program_is_not_run(tmp_path: Path, local_remotes):
    # `remote.<name>.uploadpack` is the command the transport runs to talk to the remote
    # (through a shell for a local path, on the server over ssh).
    remote, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-uploadpack"
    evil = script(tmp_path / "evil-up.sh", f'touch {marker}\nexec git-upload-pack "$@"')
    git(clone, "config", "remote.origin.uploadpack", str(evil))
    raw_fetch(clone)
    assert marker.exists(), "control: without the protections the program runs"
    marker.unlink()
    assert await gitinfo.fetch_upstream(clone) is True
    assert not marker.exists()


async def test_bundle_uri_in_the_repository_is_ignored(tmp_path: Path, local_remotes, monkeypatch):
    # `fetch.bundleURI` makes git download (or, for file://, read) a bundle first.
    _, clone = make_clone(tmp_path)
    lure = tmp_path / "lure.txt"
    lure.write_text("isto não é um bundle\n")
    git(clone, "config", "fetch.bundleURI", lure.as_uri())
    raw = subprocess.run(
        ["git", "-C", str(clone), "fetch", "origin"], env={**GIT_ENV, **os.environ},
        capture_output=True, text=True,
    )
    assert "bundle" in raw.stderr, "control: without the protections git reads the bundle URI"
    seen: list[str] = []
    real = gitinfo.run_git

    async def spy(repo, *args, **kwargs):
        result = await real(repo, *args, **kwargs)
        if args[0] == "fetch":
            seen.append(result[2])
        return result

    monkeypatch.setattr(gitinfo, "run_git", spy)
    assert await gitinfo.fetch_upstream(clone) is True
    assert seen and "bundle" not in seen[0]


async def test_option_like_ssh_host_is_refused(tmp_path: Path, local_remotes):
    # `ssh://-oProxyCommand=...` would hand a program to ssh; git refuses such hosts.
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-proxycommand"
    git(clone, "remote", "set-url", "origin", f"ssh://-oProxyCommand=touch%20{marker}/repo.git")
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert not marker.exists()


async def test_submodules_are_not_fetched(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    git(clone, "config", "fetch.recurseSubmodules", "true")
    git(clone, "config", "submodule.recurse", "true")
    push_from_elsewhere(tmp_path, remote)
    assert await gitinfo.fetch_upstream(clone) is True


# A local server that answers 401, so git asks for credentials ---------------------


class _Unauthorized(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="teste"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET  # noqa: N815

    def log_message(self, *args):
        pass


class unauthorized_server:  # noqa: N801
    def __enter__(self) -> str:
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Unauthorized)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/repo.git"

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


# Stopping a fetch stops everything it started --------------------------------------


def hanging_ssh(tmp_path: Path, monkeypatch) -> Path:
    """An "ssh" that records its pid and sleeps, standing in for a stuck connection."""
    pid_file = tmp_path / "ssh.pid"
    fake_ssh = script(tmp_path / "fake-ssh.sh", f"echo $$ > {pid_file}\nsleep 60")
    monkeypatch.setitem(gitinfo.FETCH_ENV, "GIT_SSH_COMMAND", str(fake_ssh))
    return pid_file


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_dead(pid: int, seconds: float = 3.0) -> bool:
    import asyncio

    for _ in range(int(seconds / 0.05)):
        if not alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


async def test_timeout_kills_the_programs_git_started(tmp_path: Path, local_remotes, monkeypatch):
    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "ssh://127.0.0.1:1/repo.git")
    pid_file = hanging_ssh(tmp_path, monkeypatch)
    with pytest.raises(gitinfo.GitError) as error:
        await gitinfo.fetch_upstream(clone, timeout=1.5)
    assert "tempo limite" in str(error.value)
    pid = int(pid_file.read_text())
    assert await wait_dead(pid), "the ssh child outlived the fetch"


async def test_cancelling_kills_the_programs_git_started(tmp_path: Path, local_remotes, monkeypatch):
    import asyncio

    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "ssh://127.0.0.1:1/repo.git")
    pid_file = hanging_ssh(tmp_path, monkeypatch)
    task = asyncio.create_task(gitinfo.fetch_upstream(clone, timeout=30))
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text().strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pid_file.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await wait_dead(pid), "the ssh child outlived the cancelled fetch"
