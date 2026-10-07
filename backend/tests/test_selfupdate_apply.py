"""Applying an update: git moves, tools run, failures roll back, then restart."""

import asyncio
import json

import pytest
from git_helpers import git
from selfupdate_helpers import Publish, commit_release, make_origin_and_clone, which_all

from claudio_maestro.gitinfo import run_git
from claudio_maestro.selfupdate import (
    SelfUpdater,
    UpdateBusy,
    UpdateNotAllowed,
    take_update_result,
)


class Tools:
    """Fake uv/pnpm: records each call; fails the n-th call whose argv contains `fail_on`."""

    def __init__(self, fail_on: tuple[str, ...] = (), gate: asyncio.Event | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = list(fail_on)
        self.gate = gate

    async def __call__(self, argv, cwd, timeout, on_line):
        if self.gate is not None:
            await self.gate.wait()
        self.calls.append(argv)
        on_line(f"rodou {argv[1]}")
        if self.fail_on and self.fail_on[0] in argv:
            self.fail_on.pop(0)
            return 1
        return 0


class Restart:
    def __init__(self):
        self.count = 0

    def __call__(self):
        self.count += 1


def make(tmp_path, clone, origin, tools=None, which=which_all):
    publish, restart = Publish(), Restart()
    u = SelfUpdater(
        clone, tmp_path / "data", publish, restart=restart, run_tool=tools or Tools(),
        which=which, official=lambda url: url == str(origin), current=lambda: "0.1.0",
    )
    return u, publish, restart


def head(repo):
    return git(repo, "rev-parse", "HEAD").strip()


def short_calls(tools):
    return [[part for part in argv[1:] if not part.startswith("/")] for argv in tools.calls]


EXPECTED_TOOLS = [["sync", "--frozen"], ["--dir", "install", "--frozen-lockfile"], ["--dir", "build"]]


@pytest.mark.anyio
async def test_pull_updates_main_and_restarts(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    tools = Tools()
    u, publish, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == head(origin)
    assert git(clone, "symbolic-ref", "--short", "HEAD").strip() == "main"
    assert short_calls(tools) == EXPECTED_TOOLS
    assert all(argv[0].startswith("/fake/bin/") for argv in tools.calls)
    assert tools.calls[1][2] == str(clone / "frontend")
    assert restart.count == 1
    assert u.job_state()["state"] == "restarting"
    result = json.loads((tmp_path / "data" / "update-result.json").read_text())
    assert result["from"] == "0.1.0" and result["to"] == "0.2.0" and result["agentd_changed"] is False
    assert all(e["type"] == "app.update.progress" and e["session_id"] is None for e in publish.events)
    assert "rodou sync" in (tmp_path / "data" / "update.log").read_text()


@pytest.mark.anyio
async def test_tag_mode_checks_out_the_announced_tag(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach", "v0.1.0")
    u, _, restart = make(tmp_path, clone, origin)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == git(origin, "rev-parse", "v0.2.0").strip()
    assert restart.count == 1


@pytest.mark.anyio
async def test_tag_with_wrong_pyproject_version_fails_without_moving(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path, bump=False)
    commit_release(origin, "0.2.5", tag=False)
    git(origin, "tag", "v0.3.0")
    git(clone, "checkout", "-q", "--detach", "v0.1.0")
    before = head(clone)
    u, _, restart = make(tmp_path, clone, origin)
    await u.apply("0.3.0")
    await u.wait()
    assert head(clone) == before
    job = u.job_state()
    assert job["state"] == "failed" and "0.2.5" in job["error"]
    assert restart.count == 0


@pytest.mark.anyio
async def test_tag_that_does_not_continue_head_is_refused(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path, bump=False)
    git(origin, "checkout", "-q", "-b", "lado", "HEAD~1")
    commit_release(origin, "0.3.0")
    git(clone, "checkout", "-q", "--detach", "v0.1.0")
    before = head(clone)
    u, _, _ = make(tmp_path, clone, origin)
    await u.apply("0.3.0")
    await u.wait()
    assert head(clone) == before
    assert "não continua" in u.job_state()["error"]


@pytest.mark.anyio
async def test_pull_that_is_not_fast_forward_fails_without_tools(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    commit_release(clone, "0.1.1", tag=False)
    before = head(clone)
    tools = Tools()
    u, _, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before
    assert u.job_state()["error"] == "há commits locais na main que não estão no GitHub"
    assert tools.calls == [] and restart.count == 0


@pytest.mark.anyio
async def test_untracked_file_in_the_way_fails_without_moving(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path, extra={"novo.txt": "da versão"})
    (clone / "novo.txt").write_text("meu")
    before = head(clone)
    u, _, _ = make(tmp_path, clone, origin)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before
    job = u.job_state()
    assert job["state"] == "failed"
    assert "novo.txt" in job["error"] and "commits locais" not in job["error"]
    assert (clone / "novo.txt").read_text() == "meu"


@pytest.mark.anyio
async def test_nothing_new_ends_up_to_date_without_restart(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path, bump=False)
    tools = Tools()
    u, _, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()
    assert u.job_state()["state"] == "up-to-date"
    assert tools.calls == [] and restart.count == 0


@pytest.mark.anyio
@pytest.mark.parametrize("failing", ["sync", "install", "build"])
async def test_failed_step_rolls_back(tmp_path, failing):
    origin, clone = make_origin_and_clone(tmp_path)
    before = head(clone)
    tools = Tools(fail_on=(failing,))
    u, _, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before
    assert git(clone, "symbolic-ref", "--short", "HEAD").strip() == "main"
    job = u.job_state()
    assert job["state"] == "failed" and failing in job["error"]
    assert short_calls(tools)[-3:] == EXPECTED_TOOLS  # rollback reinstalls and rebuilds
    assert restart.count == 0
    assert not (tmp_path / "data" / "update-result.json").exists()


@pytest.mark.anyio
async def test_rollback_in_tag_mode_returns_to_old_commit(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    git(clone, "checkout", "-q", "--detach", "v0.1.0")
    before = head(clone)
    u, _, _ = make(tmp_path, clone, origin, Tools(fail_on=("build",)))
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before


@pytest.mark.anyio
async def test_rollback_that_fails_is_reported(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    u, _, _ = make(tmp_path, clone, origin, Tools(fail_on=("build", "sync")))
    await u.apply("0.2.0")
    await u.wait()
    job = u.job_state()
    assert job["state"] == "rolled-back-failed"
    assert "Não foi possível desfazer" in job["error"]


@pytest.mark.anyio
async def test_tool_missing_mid_update_rolls_back(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    before = head(clone)
    seen = {"pnpm": 0}

    def which(name):
        if name == "pnpm":
            seen["pnpm"] += 1
            return "/fake/bin/pnpm" if seen["pnpm"] == 1 else None  # present at check, gone after
        return f"/fake/bin/{name}"

    tools = Tools()
    u, _, restart = make(tmp_path, clone, origin, tools, which=which)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before
    assert u.job_state()["state"] in ("failed", "rolled-back-failed")
    assert all(argv[0] is not None for argv in tools.calls)
    assert restart.count == 0


@pytest.mark.anyio
async def test_tool_output_line_too_long_rolls_back(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    before = head(clone)

    class Overflow(Tools):
        async def __call__(self, argv, cwd, timeout, on_line):
            if not self.calls:
                self.calls.append(argv)
                raise ValueError("Separator is not found, and chunk exceed the limit")
            return await super().__call__(argv, cwd, timeout, on_line)

    tools = Overflow()
    u, _, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()
    assert head(clone) == before
    job = u.job_state()
    assert job["state"] == "failed" and "linha" in job["error"]
    assert short_calls(tools)[-3:] == EXPECTED_TOOLS  # rollback reinstalls and rebuilds
    assert restart.count == 0


@pytest.mark.anyio
async def test_git_gets_end_of_options_before_remote_and_refs(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    calls: list[tuple[str, ...]] = []

    async def spy(repo, *args, **kwargs):
        calls.append(args)
        return await run_git(repo, *args, **kwargs)

    publish, restart = Publish(), Restart()
    u = SelfUpdater(
        clone, tmp_path / "data", publish, restart=restart, run_tool=Tools(), git=spy,
        which=which_all, official=lambda url: url == str(origin), current=lambda: "0.1.0",
    )
    await u.apply("0.2.0")
    await u.wait()
    for name in ("fetch", "merge"):
        used = [c for c in calls if c[0] == name]
        assert used and all("--end-of-options" in c for c in used)
    fetch = next(c for c in calls if c[0] == "fetch")
    assert fetch[fetch.index("--end-of-options") + 1:] == ("origin", "main")


@pytest.mark.anyio
async def test_unexpected_tool_error_rolls_back_and_publishes_failed(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    before = head(clone)

    class Boom(Tools):
        async def __call__(self, argv, cwd, timeout, on_line):
            if not self.calls:
                self.calls.append(argv)
                raise RuntimeError("quebrou")
            return await super().__call__(argv, cwd, timeout, on_line)

    tools = Boom()
    u, publish, restart = make(tmp_path, clone, origin, tools)
    await u.apply("0.2.0")
    await u.wait()  # must not raise
    assert head(clone) == before
    assert restart.count == 0
    assert publish.events[-1]["data"]["state"] == "failed"
    assert "quebrou" in publish.events[-1]["data"]["error"]
    assert short_calls(tools)[-3:] == EXPECTED_TOOLS


@pytest.mark.anyio
async def test_restart_that_raises_ends_failed_and_rolls_back(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    before = head(clone)

    def broken_restart():
        raise RuntimeError("sem como reiniciar")

    u, publish, _ = make(tmp_path, clone, origin)
    u._restart = broken_restart
    await u.apply("0.2.0")
    await u.wait()  # must not raise
    assert publish.events[-1]["data"]["state"] == "failed"
    assert "sem como reiniciar" in publish.events[-1]["data"]["error"]
    assert head(clone) == before
    assert not (tmp_path / "data" / "update-result.json").exists()


@pytest.mark.anyio
async def test_agentd_change_is_recorded(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path, extra={"backend/claudio_maestro/agentd/server.py": "x"})
    u, _, _ = make(tmp_path, clone, origin)
    await u.apply("0.2.0")
    await u.wait()
    result = json.loads((tmp_path / "data" / "update-result.json").read_text())
    assert result["agentd_changed"] is True


@pytest.mark.anyio
async def test_two_concurrent_applies_start_one_job(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    gate = asyncio.Event()
    u, _, _ = make(tmp_path, clone, origin, Tools(gate=gate))
    results = await asyncio.gather(u.apply("0.2.0"), u.apply("0.2.0"), return_exceptions=True)
    assert sum(isinstance(r, UpdateBusy) for r in results) == 1
    gate.set()
    await u.wait()


@pytest.mark.anyio
async def test_apply_refuses_when_check_fails(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    (clone / "pyproject.toml").write_text("mexido")
    u, _, _ = make(tmp_path, clone, origin)
    with pytest.raises(UpdateNotAllowed, match="arquivos alterados"):
        await u.apply("0.2.0")
    assert u.job_state() is None


@pytest.mark.anyio
async def test_apply_refuses_invalid_version(tmp_path):
    origin, clone = make_origin_and_clone(tmp_path)
    u, _, _ = make(tmp_path, clone, origin)
    with pytest.raises(UpdateNotAllowed):
        await u.apply("0.2.0; rm -rf /")


def test_take_update_result_reads_once(tmp_path):
    path = tmp_path / "update-result.json"
    path.write_text(json.dumps({"from": "0.1.0", "to": "0.2.0", "agentd_changed": True, "at": 10}))
    assert take_update_result(tmp_path) == {"from": "0.1.0", "to": "0.2.0", "agentd_changed": True, "at": 10.0}
    assert not path.exists()
    assert take_update_result(tmp_path) is None


def test_take_update_result_ignores_garbage(tmp_path):
    (tmp_path / "update-result.json").write_text("{não é json")
    assert take_update_result(tmp_path) is None
    assert not (tmp_path / "update-result.json").exists()
