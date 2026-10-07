"""Whether the app's own clone can be updated by the button."""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from git_helpers import git
from selfupdate_helpers import Publish, commit_release, make_origin_and_clone, which_all

from claudio_maestro.selfupdate import (
    Eligibility,
    SelfUpdater,
    is_official_remote,
    run_tool,
)


def updater(clone: Path, tmp_path: Path, origin: Path, **kw) -> SelfUpdater:
    kw.setdefault("restart", lambda: None)
    kw.setdefault("which", which_all)
    return SelfUpdater(
        clone, tmp_path / "data", Publish(), official=lambda url: url == str(origin), **kw
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/vateiixeira/claudio-maestro",
        "https://github.com/vateiixeira/claudio-maestro.git",
        "git@github.com:vateiixeira/claudio-maestro.git",
        "ssh://git@github.com/vateiixeira/claudio-maestro.git",
    ],
)
def test_official_remote_accepts(url):
    assert is_official_remote(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/outro/claudio-maestro",
        "https://github.com/vateiixeira/claudio-maestro-fork",
        "https://evil.example/github.com/vateiixeira/claudio-maestro",
        "/tmp/claudio-maestro",
    ],
)
def test_official_remote_rejects(url):
    assert not is_official_remote(url)


@pytest.mark.anyio
async def test_main_is_pull_mode(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    assert await updater(clone, tmp_path, origin).check() == Eligibility(True, mode="pull", remote="origin")


@pytest.mark.anyio
async def test_detached_at_release_tag_is_tag_mode(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach", "v0.1.0")
    assert await updater(clone, tmp_path, origin).check() == Eligibility(True, mode="tag", remote="origin")


@pytest.mark.anyio
async def test_untracked_files_are_allowed(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    (clone / "anotacoes.txt").write_text("x")
    assert (await updater(clone, tmp_path, origin).check()).ok


@pytest.mark.anyio
async def test_remote_with_another_name(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    git(clone, "remote", "rename", "origin", "upstream")
    assert (await updater(clone, tmp_path, origin).check()).remote == "upstream"


@pytest.mark.anyio
async def test_remote_named_like_a_git_option_is_not_official(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    # `git remote rename` refuses such a name, but `remote add --` accepts it.
    git(clone, "remote", "add", "--", "--upload-pack=x", str(origin))
    git(clone, "remote", "remove", "origin")
    result = await updater(clone, tmp_path, origin).check()
    assert not result.ok
    assert result.reason == "nenhum remoto aponta para o repositório oficial"


async def reason(clone, tmp_path, origin, **kw) -> str | None:
    result = await updater(clone, tmp_path, origin, **kw).check()
    assert not result.ok
    return result.reason


@pytest.mark.anyio
async def test_not_started_by_the_cli(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    assert await reason(clone, tmp_path, origin, restart=None) == "o app não foi iniciado pelo comando claudio-maestro"


@pytest.mark.anyio
async def test_not_a_git_clone(tmp_path):
    origin, _ = make_origin_and_clone(tmp_path)
    plain = tmp_path / "sem-git"
    plain.mkdir()
    assert await reason(plain, tmp_path, origin) == "o app não foi instalado por um clone git"


@pytest.mark.anyio
async def test_changed_files(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    (clone / "pyproject.toml").write_text("mexido")
    assert await reason(clone, tmp_path, origin) == "há arquivos alterados no clone"


@pytest.mark.anyio
async def test_other_branch(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    git(clone, "checkout", "-q", "-b", "feat/x")
    assert await reason(clone, tmp_path, origin) == "o clone está na branch feat/x"


@pytest.mark.anyio
async def test_detached_outside_a_release(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    commit_release(clone, "0.1.1", tag=False)
    git(clone, "checkout", "-q", "--detach", "HEAD")
    assert await reason(clone, tmp_path, origin) == "o clone está num commit fora de release"


@pytest.mark.anyio
async def test_no_official_remote(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    result = await SelfUpdater(
        clone, tmp_path / "data", Publish(), restart=lambda: None, which=which_all, official=lambda url: False
    ).check()
    assert result.reason == "nenhum remoto aponta para o repositório oficial"


@pytest.mark.anyio
@pytest.mark.parametrize("missing", ["uv", "pnpm"])
async def test_missing_tool(tmp_path, missing):
    origin, clone = make_origin_and_clone(tmp_path)
    which = lambda name: None if name == missing else f"/fake/bin/{name}"  # noqa: E731
    assert await reason(clone, tmp_path, origin, which=which) == f"{missing} não encontrado no PATH do app"


def test_no_job_before_any_update(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    u = updater(clone, tmp_path, origin)
    assert u.job_state() is None
    assert u.busy is False
    assert u.log_path == tmp_path / "data" / "update.log"


@pytest.mark.anyio
async def test_run_tool_streams_lines_and_returns_code(tmp_path):
    lines = []
    code = await run_tool(
        [sys.executable, "-c", "print('a'); print('b'); raise SystemExit(3)"], tmp_path, 10, lines.append
    )
    assert (code, lines) == (3, ["a", "b"])


@pytest.mark.anyio
async def test_run_tool_merges_stderr(tmp_path):
    lines = []
    await run_tool([sys.executable, "-c", "import sys; sys.stderr.write('erro\\n')"], tmp_path, 10, lines.append)
    assert lines == ["erro"]


@pytest.mark.anyio
async def test_run_tool_timeout_kills_the_process_group(tmp_path):
    marker = tmp_path / "filho.pid"
    script = (
        "import subprocess, sys, time;"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(marker)!r}, 'w').write(str(p.pid)); time.sleep(60)"
    )
    with pytest.raises(TimeoutError):
        await run_tool([sys.executable, "-c", script], tmp_path, 1.5, lambda line: None)
    pid = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("o neto continuou vivo depois do timeout")
