"""`gitinfo.fetch_upstream`: updates the tracking branch and never runs repository config."""

import asyncio
import http.server
import os
import ssl
import stat
import subprocess
import threading
from contextlib import suppress
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
    remote, clone = make_clone(tmp_path)
    monkeypatch.setenv("SSH_ASKPASS", "/bin/evil")
    monkeypatch.setenv("GIT_ASKPASS", "/bin/evil")
    monkeypatch.setenv("GIT_SSH_COMMAND", "evil")
    seen: list[tuple[tuple[str, ...], dict[str, str], Path]] = []
    real = gitinfo._exec_now

    async def spy(repo, args, timeout, extra_config, limit, extra_env=None, own_group=False):
        seen.append((args, gitinfo._env(extra_config, extra_env), repo))
        assert own_group is (args[0] == "fetch")  # only the fetch gets its own process group
        return await real(repo, args, timeout, extra_config, limit, extra_env, own_group)

    monkeypatch.setattr(gitinfo, "_exec_now", spy)
    await gitinfo.fetch_upstream(clone)
    (args, env, where), = [item for item in seen if item[0][0] == "fetch"]
    assert args == (
        "fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
        "--no-prune", "--upload-pack=git-upload-pack", "--", str(remote),
        "+refs/heads/main:refs/remotes/origin/main",
    )
    # It runs in a throwaway repository, never in the real one, and writes objects to the real one.
    assert where != clone and env["GIT_DIR"] == str(where)
    assert env["GIT_OBJECT_DIRECTORY"] == str(clone / ".git" / "objects")
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
        ("core.askPass", ""), ("protocol.allow", "never"),
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
    await gitinfo.fetch_upstream(clone)  # the repository's `remote.origin.vcs` is not even read
    assert not marker.exists()


async def test_ext_transport_enabled_by_the_repository_is_not_run(tmp_path: Path, local_remotes):
    # `ext::` runs any command. Git keeps it off by default, but a repository can turn it
    # on for itself with `protocol.ext.allow` (and reach it through `url.<base>.insteadOf`).
    _, clone = make_clone(tmp_path)
    marker = tmp_path / "marker-ext"
    evil = script(tmp_path / "evil-ext.sh", f"touch {marker}\nexit 1")
    git(clone, "remote", "set-url", "origin", "https://127.0.0.1:1/repo.git")
    git(clone, "config", f"url.ext::{evil} .insteadOf", "https://127.0.0.1:1/")
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



# The repository's config is not read at all ---------------------------------------------
#
# A local HTTPS server stands in for an attacker's. Its certificate is trusted through the
# user's own global git config (`http.sslCAInfo`), as a real login would be; the repository
# asks for `http.sslVerify=false`, which must not matter.


class _Recorder(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        server = self.server
        server.requests.append({k.lower(): v for k, v in self.headers.items()})  # type: ignore[attr-defined]
        body = b""
        if server.advert and self.path.startswith("/repo.git/info/refs"):  # type: ignore[attr-defined]
            # A valid smart-http answer naming a tip the repository already has: git
            # finishes cleanly, which is when it writes a cookie jar.
            def pkt(data: bytes) -> bytes:
                return f"{len(data) + 4:04x}".encode() + data

            body = (
                pkt(b"# service=git-upload-pack\n") + b"0000"
                + pkt(f"{server.advert} refs/heads/main\0ofs-delta agent=teste\n".encode())  # type: ignore[attr-defined]
                + b"0000"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-git-upload-pack-advertisement")
        else:
            self.send_response(404)
        self.send_header("Set-Cookie", "sessao=roubada; Path=/; Secure")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET  # noqa: N815

    def log_message(self, *args):
        pass


class HttpsRecorder:
    def __init__(self, tmp_path: Path) -> None:
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
             "-out", str(cert), "-days", "2", "-subj", "/CN=127.0.0.1",
             "-addext", "subjectAltName=IP:127.0.0.1"],
            check=True, capture_output=True,
        )
        self.cert = cert
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
        self.server.requests = []  # type: ignore[attr-defined]
        self.server.advert = None  # type: ignore[attr-defined]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"https://127.0.0.1:{self.server.server_address[1]}"
        self.url = f"{self.base}/repo.git"

    def advertise(self, sha: str) -> None:
        """Answer `info/refs` as a server whose `main` is at `sha`."""
        self.server.advert = sha  # type: ignore[attr-defined]

    @property
    def requests(self) -> list[dict[str, str]]:
        return self.server.requests  # type: ignore[attr-defined]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def https_server(tmp_path: Path, monkeypatch):
    server = HttpsRecorder(tmp_path)
    home = tmp_path / "fakehome"
    home.mkdir()
    (home / ".gitconfig").write_text(f"[http]\n\tsslCAInfo = {server.cert}\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    yield server
    server.close()


async def attempt(clone: Path) -> None:
    with suppress(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)


def untrusting_clone(tmp_path: Path, server: HttpsRecorder) -> Path:
    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", server.url)
    git(clone, "config", "http.sslVerify", "false")
    return clone


@pytest.mark.parametrize("scoped", [False, True], ids=["generic", "url-scoped"])
async def test_cookie_jar_is_never_written_to_a_file_named_by_the_repository(
    tmp_path: Path, https_server, scoped: bool
):
    clone = untrusting_clone(tmp_path, https_server)
    https_server.advertise(git(clone, "rev-parse", "HEAD").strip())
    victim = tmp_path / "importante.txt"
    victim.write_text("dados importantes\n")
    prefix = f"http.{https_server.base}/." if scoped else "http."
    git(clone, "config", f"{prefix}cookieFile", str(victim))
    git(clone, "config", f"{prefix}saveCookies", "true")
    raw_fetch(clone)
    assert victim.read_text().startswith("# Netscape HTTP Cookie File"), (
        "control: without the protections the file is overwritten with the cookie jar"
    )
    victim.write_text("dados importantes\n")
    https_server.requests.clear()
    await attempt(clone)
    assert https_server.requests, "the fetch should have reached the server"
    assert victim.read_text() == "dados importantes\n"


@pytest.mark.parametrize("scoped", [False, True], ids=["generic", "url-scoped"])
async def test_cookie_file_is_never_read_nor_sent(tmp_path: Path, https_server, scoped: bool):
    clone = untrusting_clone(tmp_path, https_server)
    secret = tmp_path / "cookies.txt"
    secret.write_text("127.0.0.1\tFALSE\t/\tTRUE\t0\tsegredo\tvalor\n")
    prefix = f"http.{https_server.base}/." if scoped else "http."
    git(clone, "config", f"{prefix}cookieFile", str(secret))
    raw_fetch(clone)
    assert any("segredo=valor" in r.get("cookie", "") for r in https_server.requests), (
        "control: without the protections the file's cookies go to the server"
    )
    https_server.requests.clear()
    await attempt(clone)
    assert https_server.requests, "the fetch should have reached the server"
    assert all("cookie" not in r for r in https_server.requests)


async def test_client_certificate_and_headers_from_the_repository_are_not_used(
    tmp_path: Path, https_server
):
    clone = untrusting_clone(tmp_path, https_server)
    git(clone, "config", "http.extraHeader", "X-Vazamento: sim")
    raw_fetch(clone)
    assert any(r.get("x-vazamento") == "sim" for r in https_server.requests), (
        "control: without the protections the repository's header is sent"
    )
    # A client certificate the repository names does not exist: git would fail before the
    # request if it read that key.
    git(clone, "config", "http.sslCert", str(tmp_path / "nao-existe.pem"))
    git(clone, "config", "http.sslKey", str(tmp_path / "nao-existe.key"))
    https_server.requests.clear()
    await attempt(clone)
    assert https_server.requests, "the client certificate named by the repository was used"
    assert all("x-vazamento" not in r for r in https_server.requests)


async def test_users_global_git_config_still_applies(tmp_path: Path, https_server, monkeypatch):
    # The server's certificate is only trusted through the user's global `http.sslCAInfo`.
    clone = untrusting_clone(tmp_path, https_server)
    git(clone, "config", "--unset", "http.sslVerify")
    await attempt(clone)
    assert https_server.requests


# What cannot be checked is refused with a clear message ------------------------------------


async def test_shallow_repository_is_refused(tmp_path: Path, local_remotes):
    remote, _ = make_clone(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", remote.as_uri(), str(shallow)], check=True,
        env={**GIT_ENV, "GIT_ALLOW_PROTOCOL": "file"},
    )
    with pytest.raises(gitinfo.GitError, match="raso"):
        await gitinfo.fetch_upstream(shallow)


@pytest.mark.parametrize("key", ["extensions.partialclone", "remote.origin.promisor"])
async def test_partial_clone_is_refused(tmp_path: Path, local_remotes, key: str):
    _, clone = make_clone(tmp_path)
    git(clone, "config", key, "origin" if key.startswith("ext") else "true")
    with pytest.raises(gitinfo.GitError, match="parcial"):
        await gitinfo.fetch_upstream(clone)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x.git", "git://example.com/x.git", "ext::sh -c touch% x", "evil::x",
        "-oProxyCommand=x", "-x:y", "ssh://-oProxyCommand=x/y", "file:///tmp/x", "/tmp/x",
        "ftp://example.com/x.git", "https://exa mple.com/x",
    ],
)
async def test_urls_outside_https_and_ssh_are_refused(tmp_path: Path, url: str):
    with pytest.raises(gitinfo.GitError, match="https e ssh"):
        gitinfo._check_fetch_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x.git", "HTTPS://user:token@example.com:8443/x.git",
        "ssh://git@example.com/x.git", "ssh://git@example.com:2222/x.git",
        "git@github.com:vateiixeira/claudio-maestro.git", "example.com:x/y.git",
    ],
)
async def test_https_and_ssh_urls_are_accepted(url: str):
    gitinfo._check_fetch_url(url)


async def test_local_remote_is_refused_by_default_with_a_clear_message(tmp_path: Path):
    _, clone = make_clone(tmp_path)
    with pytest.raises(gitinfo.GitError, match="https e ssh"):
        await gitinfo.fetch_upstream(clone)


async def test_upstream_with_an_invalid_ref_name_is_refused(tmp_path: Path, local_remotes):
    _, clone = make_clone(tmp_path)
    git(clone, "config", "branch.main.merge", "refs/heads/a:refs/heads/b")
    with pytest.raises(gitinfo.GitError, match="inválido"):
        await gitinfo.fetch_upstream(clone)


# Behaviour of the throwaway-repository fetch ------------------------------------------------


async def test_negotiation_starts_from_what_the_repository_has(tmp_path: Path, local_remotes, monkeypatch):
    remote, clone = make_clone(tmp_path)
    other = push_from_elsewhere(tmp_path, remote)
    for index in range(30):
        commit_file(other, f"f{index}.txt", f"{index}\n" * 50)
    git(other, "push", "-q")
    await gitinfo.fetch_upstream(clone)
    old = git(clone, "rev-parse", "origin/main").strip()
    commit_file(other, "ultimo.txt")
    git(other, "push", "-q")
    new = git(other, "rev-parse", "HEAD").strip()
    trace = tmp_path / "packets.txt"
    monkeypatch.setitem(gitinfo.FETCH_ENV, "GIT_TRACE_PACKET", str(trace))
    assert await gitinfo.fetch_upstream(clone) is True
    packets = trace.read_text()
    assert f"want {new}" in packets
    assert f"have {old}" in packets, "git did not tell the server what the repository already has"
    assert git(clone, "rev-parse", "origin/main").strip() == new


async def test_first_fetch_uses_the_local_branch_as_what_it_has(tmp_path: Path, local_remotes, monkeypatch):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    head = git(clone, "rev-parse", "HEAD").strip()
    trace = tmp_path / "packets.txt"
    monkeypatch.setitem(gitinfo.FETCH_ENV, "GIT_TRACE_PACKET", str(trace))
    await gitinfo.fetch_upstream(clone)
    assert f"have {head}" in trace.read_text()
    assert (await gitinfo.repo_status(clone)).behind == 1


async def test_linked_worktree(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    tree = tmp_path / "tree"
    git(clone, "worktree", "add", "-q", "-b", "trabalho", str(tree), "origin/main")
    assert git(tree, "config", "branch.trabalho.remote").strip() == "origin"
    push_from_elsewhere(tmp_path, remote)
    assert await gitinfo.fetch_upstream(tree) is True
    assert (await gitinfo.repo_status(tree)).behind == 1
    assert git(clone, "rev-parse", "origin/main").strip() == git(tree, "rev-parse", "origin/main").strip()


async def test_sha256_repository(tmp_path: Path, local_remotes):
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "--object-format=sha256", "-b", "main", str(remote)],
        check=True, env=GIT_ENV,
    )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", "-b", "main", str(clone)],
        check=True, env=GIT_ENV,
    )
    commit_file(clone, "a.txt")
    git(clone, "remote", "add", "origin", str(remote))
    git(clone, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    clone_to(remote, other)
    commit_file(other, "b.txt")
    git(other, "push", "-q")
    assert await gitinfo.fetch_upstream(clone) is True
    assert (await gitinfo.repo_status(clone)).behind == 1


async def test_a_concurrent_update_of_the_ref_is_not_overwritten(tmp_path: Path, local_remotes, monkeypatch):
    remote, clone = make_clone(tmp_path)
    other = push_from_elsewhere(tmp_path, remote)
    commit_file(other, "segundo.txt")
    git(other, "push", "-q")
    middle = git(other, "rev-parse", "HEAD~1").strip()
    real = gitinfo.run_git

    async def racing(repo, *args, **kwargs):
        result = await real(repo, *args, **kwargs)
        if args[0] == "fetch":
            # Meanwhile the user's own `git fetch` brings the ref to another commit.
            git(clone, "fetch", "-q", "origin")
            git(clone, "update-ref", "refs/remotes/origin/main", middle)
        return result

    monkeypatch.setattr(gitinfo, "run_git", racing)
    assert await gitinfo.fetch_upstream(clone) is True
    assert git(clone, "rev-parse", "origin/main").strip() == middle


async def test_the_ref_is_created_when_it_did_not_exist(tmp_path: Path, local_remotes):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    assert await gitinfo.fetch_upstream(clone) is True
    assert git(clone, "rev-parse", "origin/main").strip() == git(remote, "rev-parse", "main").strip()


async def test_a_failure_of_the_ref_update_is_reported(tmp_path: Path, local_remotes, monkeypatch):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    lock = clone / ".git" / "refs" / "remotes" / "origin" / "main.lock"
    real = gitinfo.run_git

    async def locking(repo, *args, **kwargs):
        if args[0] == "update-ref" and repo == clone:
            lock.write_text("")
        return await real(repo, *args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", locking)
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)


# The throwaway repository is always removed ---------------------------------------------------


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "scratch"
    folder.mkdir()
    monkeypatch.setattr(gitinfo, "FETCH_SCRATCH_ROOT", folder)
    return folder


async def test_scratch_is_removed_after_success(tmp_path: Path, local_remotes, scratch):
    remote, clone = make_clone(tmp_path)
    push_from_elsewhere(tmp_path, remote)
    assert await gitinfo.fetch_upstream(clone) is True
    assert list(scratch.iterdir()) == []


async def test_scratch_is_removed_after_a_failure(tmp_path: Path, local_remotes, scratch):
    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", str(tmp_path / "nao-existe.git"))
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)
    assert list(scratch.iterdir()) == []


async def test_scratch_is_not_made_when_nothing_is_checked(tmp_path: Path, scratch):
    _, clone = make_clone(tmp_path)
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone)  # local path: refused before any work
    assert list(scratch.iterdir()) == []


async def test_scratch_is_removed_after_a_timeout(tmp_path: Path, local_remotes, monkeypatch, scratch):
    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "ssh://127.0.0.1:1/repo.git")
    hanging_ssh(tmp_path, monkeypatch)
    with pytest.raises(gitinfo.GitError):
        await gitinfo.fetch_upstream(clone, timeout=1.5)
    assert list(scratch.iterdir()) == []


async def test_scratch_is_removed_after_a_cancellation(tmp_path: Path, local_remotes, monkeypatch, scratch):
    _, clone = make_clone(tmp_path)
    git(clone, "remote", "set-url", "origin", "ssh://127.0.0.1:1/repo.git")
    pid_file = hanging_ssh(tmp_path, monkeypatch)
    task = asyncio.create_task(gitinfo.fetch_upstream(clone, timeout=30))
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text().strip():
            break
        await asyncio.sleep(0.05)
    assert list(scratch.iterdir()), "the fetch was running in a scratch repository"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert list(scratch.iterdir()) == []
