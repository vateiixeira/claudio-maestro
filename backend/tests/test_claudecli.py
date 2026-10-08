"""Which `claude` the app starts, and the `claude update` button."""

import asyncio
import os
import sys

import pytest

from claudio_maestro import claudecli
from claudio_maestro.claudecli import (
    ClaudeCliBusy,
    ClaudeCliResolver,
    ClaudeCliUnavailable,
    CommandResult,
    clean_output,
    parse_version,
    resolve,
)

BUNDLED = "2.1.284"
SYSTEM = "/opt/bin/claude"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Machine:
    """A fake machine: where `claude` is, what `--version` prints, what `update` does."""

    def __init__(self, version: str | None = "2.1.292", path: str | None = SYSTEM) -> None:
        self.path = path
        self.version = version
        self.version_calls = 0
        self.update_calls: list[list[str]] = []
        self.update_result = CommandResult(0, "ok")
        self.new_version: str | None = None
        self.gate: asyncio.Event | None = None

    def which(self, name: str) -> str | None:
        assert name == "claude"
        return self.path

    def run_version(self, path: str) -> str | None:
        self.version_calls += 1
        return None if self.version is None else f"{self.version} (Claude Code)\n"

    async def run_update(self, argv: list[str], timeout: float) -> CommandResult:
        self.update_calls.append(argv)
        if self.gate is not None:
            await self.gate.wait()
        if self.new_version is not None:
            self.version = self.new_version
        return self.update_result


def make(machine: Machine, env: dict[str, str] | None = None, clock: Clock | None = None):
    return ClaudeCliResolver(
        env=env or {},
        which=machine.which,
        run_version=machine.run_version,
        run_update=machine.run_update,
        bundled_version=BUNDLED,
        clock=clock or Clock(),
    )


def resolved(machine: Machine, env: dict[str, str] | None = None):
    return resolve(
        env=env or {}, which=machine.which, run_version=machine.run_version, bundled_version=BUNDLED
    )


# parse_version / clean_output ------------------------------------------------


def test_parse_version_reads_leading_semver():
    assert parse_version("2.1.292 (Claude Code)\n") == (2, 1, 292)
    assert parse_version("  10.0.1") == (10, 0, 1)


@pytest.mark.parametrize("text", [None, "", "Claude Code", "v2.1", "erro: 2.1.3"])
def test_parse_version_rejects_anything_else(text):
    assert parse_version(text) is None


def test_clean_output_strips_ansi_and_carriage_returns():
    raw = "\x1b[32mChecking\x1b[0m\rDownloading 10%\rDownloading 100%\nDone\n\n"
    assert clean_output(raw) == "Downloading 100%\nDone"


def test_clean_output_keeps_last_40_lines_and_4096_chars():
    many = "\n".join(f"linha {i}" for i in range(100))
    lines = clean_output(many).splitlines()
    assert len(lines) == 40 and lines[-1] == "linha 99"
    assert len(clean_output("x" * 10_000)) == 4096


# resolve ----------------------------------------------------------------------


def test_newer_system_wins():
    cli = resolved(Machine("2.1.292"))
    assert (cli.source, cli.path, cli.version) == ("system", SYSTEM, "2.1.292")
    assert cli.bundled_version == BUNDLED


def test_relative_which_result_becomes_absolute():
    # PATH="bin:/usr/bin" makes `which` answer "bin/claude"; the agentd runs with the
    # project as cwd, so a relative path would start `<project>/bin/claude`.
    seen: list[str] = []

    def run_version(path: str) -> str | None:
        seen.append(path)
        return "2.1.292 (Claude Code)\n"

    cli = resolve(
        env={}, which=lambda name: "bin/claude", run_version=run_version, bundled_version=BUNDLED
    )
    expected = os.path.abspath("bin/claude")
    assert os.path.isabs(expected)
    assert (cli.path, cli.system_path) == (expected, expected)
    assert seen == [expected]


def test_equal_system_wins():
    cli = resolved(Machine(BUNDLED))
    assert (cli.source, cli.path) == ("system", SYSTEM)


def test_older_system_loses():
    cli = resolved(Machine("2.1.200"))
    assert (cli.source, cli.path, cli.version) == ("bundled", None, BUNDLED)
    assert cli.system_version == "2.1.200"


def test_missing_system_uses_bundled():
    cli = resolved(Machine(path=None))
    assert (cli.source, cli.path, cli.system_path, cli.system_version) == ("bundled", None, None, None)


def test_unreadable_version_counts_as_missing():
    machine = Machine()
    machine.run_version = lambda path: "Claude Code\n"  # type: ignore[method-assign]
    cli = resolved(machine)
    assert (cli.source, cli.system_path, cli.system_version) == ("bundled", None, None)


def test_version_timeout_falls_back_to_bundled():
    # run_version_command returns None on timeout, failure or a non-zero exit.
    cli = resolved(Machine(version=None))
    assert (cli.source, cli.system_path) == ("bundled", None)


def test_env_forces_bundled_but_still_reports_system():
    cli = resolved(Machine("2.1.292"), env={"MAESTRO_CLAUDE_CLI": "bundled"})
    assert (cli.source, cli.path, cli.forced_bundled) == ("bundled", None, True)
    assert cli.system_version == "2.1.292"


def test_unknown_env_value_is_ignored():
    cli = resolved(Machine("2.1.292"), env={"MAESTRO_CLAUDE_CLI": "/tmp/outro"})
    assert (cli.source, cli.forced_bundled) == ("system", False)


def test_as_dict_shape():
    assert resolved(Machine("2.1.292")).as_dict() == {
        "in_use": {"source": "system", "version": "2.1.292"},
        "system": {"path": SYSTEM, "version": "2.1.292"},
        "bundled": {"version": BUNDLED},
        "forced_bundled": False,
        "can_update": True,
    }
    assert resolved(Machine(path=None)).as_dict()["system"] is None
    assert resolved(Machine(path=None)).as_dict()["can_update"] is False
    forced = resolved(Machine("2.1.292"), env={"MAESTRO_CLAUDE_CLI": "bundled"})
    assert forced.as_dict()["can_update"] is False


# real runners (a tiny Python script stands in for `claude`) -------------------


def write_script(tmp_path, body: str) -> str:
    script = tmp_path / "fake-claude"
    script.write_text(f"#!{sys.executable}\n{body}\n")
    script.chmod(0o755)
    return str(script)


def test_run_version_command_reads_stdout(tmp_path):
    path = write_script(tmp_path, "print('2.1.300 (Claude Code)')")
    assert claudecli.run_version_command(path) == "2.1.300 (Claude Code)\n"


def test_run_version_command_none_on_failure(tmp_path):
    path = write_script(tmp_path, "import sys; sys.exit(3)")
    assert claudecli.run_version_command(path) is None
    assert claudecli.run_version_command(str(tmp_path / "nao-existe")) is None


def test_run_version_command_none_on_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(claudecli, "VERSION_TIMEOUT", 0.2)
    path = write_script(tmp_path, "import time; time.sleep(5)")
    assert claudecli.run_version_command(path) is None


@pytest.mark.anyio
async def test_run_update_command_captures_output(tmp_path):
    path = write_script(tmp_path, "import sys; print('atualizado'); print('aviso', file=sys.stderr)")
    result = await claudecli.run_update_command([path, "update"], 10)
    assert result.returncode == 0
    assert "atualizado" in result.output and "aviso" in result.output


@pytest.mark.anyio
async def test_run_update_command_kills_on_timeout(tmp_path):
    marker = tmp_path / "child.pid"
    body = (
        "import os, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(30)"
    )
    path = write_script(tmp_path, body)
    result = await claudecli.run_update_command([path, "update"], 1.0)
    assert result.returncode is None
    assert result.output == "O comando passou do tempo limite."
    child = int(marker.read_text())
    # The whole process group died (the child is reaped by init shortly after).
    for _ in range(60):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("o filho do claude update continuou vivo")


@pytest.mark.anyio
async def test_run_update_command_missing_binary(tmp_path):
    result = await claudecli.run_update_command([str(tmp_path / "nao-existe"), "update"], 5)
    assert result.returncode is None and result.output


# ClaudeCliResolver ------------------------------------------------------------


@pytest.mark.anyio
async def test_starts_as_bundled_without_running_anything():
    machine = Machine()
    resolver = make(machine)
    assert resolver.current().source == "bundled"
    assert resolver.cli_path() is None
    assert machine.version_calls == 0


@pytest.mark.anyio
async def test_refresh_caches_for_ten_minutes():
    machine, clock = Machine(), Clock()
    resolver = make(machine, clock=clock)
    assert (await resolver.refresh()).path == SYSTEM
    assert resolver.cli_path() == SYSTEM
    clock.now += 599
    await resolver.refresh()
    assert machine.version_calls == 1
    clock.now += 2
    await resolver.refresh()
    assert machine.version_calls == 2


@pytest.mark.anyio
async def test_refresh_after_cache_picks_up_removal():
    machine, clock = Machine(), Clock()
    resolver = make(machine, clock=clock)
    await resolver.refresh()
    machine.path = None
    clock.now += 601
    assert (await resolver.refresh()).source == "bundled"
    assert resolver.cli_path() is None


@pytest.mark.anyio
async def test_force_skips_the_cache():
    machine = Machine()
    resolver = make(machine)
    await resolver.refresh()
    await resolver.refresh(force=True)
    assert machine.version_calls == 2


@pytest.mark.anyio
async def test_refresh_never_raises():
    machine = Machine()

    def boom(name):
        raise RuntimeError("quebrou")

    machine.which = boom  # type: ignore[method-assign]
    cli = await make(machine).refresh()
    assert (cli.source, cli.path) == ("bundled", None)


@pytest.mark.anyio
async def test_run_periodic_sleeps_first_then_forces():
    machine = Machine()
    resolver = make(machine)
    sleeps: list[float] = []

    async def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await resolver.run_periodic(600, sleep=sleep)
    assert sleeps == [600, 600, 600]
    assert machine.version_calls == 2


async def models_ok() -> bool:
    return True


@pytest.mark.anyio
async def test_update_to_new_version():
    machine = Machine("2.1.292")
    machine.new_version = "2.1.295"
    resolver = make(machine)
    outcome = await resolver.update(models_ok)
    assert machine.update_calls == [[SYSTEM, "update"]]
    assert (outcome.ok, outcome.before, outcome.after) == (True, "2.1.292", "2.1.295")
    assert outcome.message == "Claude atualizado de 2.1.292 para 2.1.295. A lista de modelos foi renovada."
    assert resolver.current().version == "2.1.295"
    assert outcome.as_dict() == {
        "ok": True,
        "before": "2.1.292",
        "after": "2.1.295",
        "in_use": {"source": "system", "version": "2.1.295"},
        "models_refreshed": True,
        "output": "ok",
        "message": outcome.message,
    }
    assert resolver.job_state() == {"state": "done", **outcome.as_dict()}


@pytest.mark.anyio
async def test_update_already_latest():
    outcome = await make(Machine("2.1.292")).update(models_ok)
    assert outcome.ok is True
    assert outcome.message == "O Claude já está na versão mais nova (2.1.292)."


@pytest.mark.anyio
async def test_update_models_not_refreshed():
    machine = Machine("2.1.292")
    machine.new_version = "2.1.295"

    async def models_fail() -> bool:
        return False

    outcome = await make(machine).update(models_fail)
    assert outcome.models_refreshed is False
    assert outcome.message == (
        "Claude atualizado de 2.1.292 para 2.1.295. "
        "Não foi possível renovar a lista de modelos agora."
    )


@pytest.mark.anyio
async def test_update_models_refresh_raising_is_not_fatal():
    async def models_boom() -> bool:
        raise RuntimeError("x")

    outcome = await make(Machine()).update(models_boom)
    assert outcome.ok is True and outcome.models_refreshed is False


@pytest.mark.anyio
async def test_update_failure_shows_last_line():
    machine = Machine()
    machine.update_result = CommandResult(1, "Checking...\nErro: sem permissão em /usr/lib\n")
    resolver = make(machine)
    outcome = await resolver.update(models_ok)
    assert outcome.ok is False
    assert outcome.message == "Não foi possível atualizar o Claude. Erro: sem permissão em /usr/lib"
    assert resolver.job_state()["state"] == "failed"


@pytest.mark.anyio
async def test_update_timeout_message():
    machine = Machine()
    machine.update_result = CommandResult(None, "O comando passou do tempo limite.")
    outcome = await make(machine).update(models_ok)
    assert outcome.message == "Não foi possível atualizar o Claude. O comando passou do tempo limite."


@pytest.mark.anyio
async def test_update_without_system_claude():
    with pytest.raises(ClaudeCliUnavailable, match="Não há Claude instalado no sistema"):
        await make(Machine(path=None)).update(models_ok)


@pytest.mark.anyio
async def test_update_refused_when_forced_bundled():
    machine = Machine()
    with pytest.raises(ClaudeCliUnavailable, match="MAESTRO_CLAUDE_CLI"):
        await make(machine, env={"MAESTRO_CLAUDE_CLI": "bundled"}).update(models_ok)
    assert machine.update_calls == []


@pytest.mark.anyio
async def test_second_update_while_running_is_refused():
    machine = Machine()
    machine.gate = asyncio.Event()
    resolver = make(machine)
    first = asyncio.create_task(resolver.update(models_ok))
    while not machine.update_calls:
        await asyncio.sleep(0)
    assert resolver.job_state() == {"state": "running"}
    with pytest.raises(ClaudeCliBusy, match="Já há uma atualização do Claude em andamento."):
        await resolver.update(models_ok)
    machine.gate.set()
    assert (await first).ok is True
    assert len(machine.update_calls) == 1
    # Free again afterwards.
    assert (await resolver.update(models_ok)).ok is True


@pytest.mark.anyio
async def test_unavailable_does_not_leave_the_lock_taken():
    machine = Machine(path=None)
    resolver = make(machine)
    with pytest.raises(ClaudeCliUnavailable):
        await resolver.update(models_ok)
    machine.path = SYSTEM
    machine.version = "2.1.292"
    assert (await resolver.update(models_ok)).ok is True


def test_default_runners_are_blocked_in_tests():
    # The autouse fixture in conftest.py keeps the real `claude` out of the tests.
    assert claudecli.run_version_command("/usr/bin/true") is None


# on_change ----------------------------------------------------------------------


def watching(machine: Machine, clock: Clock | None = None, fail: bool = False):
    calls: list[tuple[claudecli.ClaudeCli, claudecli.ClaudeCli]] = []

    async def on_change(old, new) -> None:
        calls.append((old, new))
        if fail:
            raise RuntimeError("quebrou")

    resolver = ClaudeCliResolver(
        env={},
        which=machine.which,
        run_version=machine.run_version,
        run_update=machine.run_update,
        bundled_version=BUNDLED,
        clock=clock or Clock(),
        on_change=on_change,
    )
    return resolver, calls


@pytest.mark.anyio
async def test_on_change_runs_when_the_version_changes_after_the_cache():
    machine, clock = Machine("2.1.292"), Clock()
    resolver, calls = watching(machine, clock)
    await resolver.refresh()
    machine.version = "2.1.295"
    clock.now += 601
    await resolver.refresh()
    assert len(calls) == 1
    old, new = calls[0]
    assert (old.version, new.version) == ("2.1.292", "2.1.295")
    assert resolver.current() is new


@pytest.mark.anyio
async def test_on_change_runs_when_the_path_changes():
    machine = Machine("2.1.292")
    resolver, calls = watching(machine)
    await resolver.refresh()
    machine.path = None
    await resolver.refresh(force=True)
    assert [(o.source, n.source) for o, n in calls] == [("system", "bundled")]


@pytest.mark.anyio
async def test_on_change_does_not_run_on_the_first_resolution():
    resolver, calls = watching(Machine())
    await resolver.refresh()
    assert calls == []


@pytest.mark.anyio
async def test_on_change_does_not_run_when_nothing_changes():
    resolver, calls = watching(Machine())
    await resolver.refresh()
    await resolver.refresh(force=True)
    await resolver.refresh(force=True)
    assert calls == []


@pytest.mark.anyio
async def test_on_change_raising_does_not_break_refresh():
    machine = Machine("2.1.292")
    resolver, calls = watching(machine, fail=True)
    await resolver.refresh()
    machine.version = "2.1.295"
    cli = await resolver.refresh(force=True)
    assert cli.version == "2.1.295"
    assert resolver.current() is cli
    assert len(calls) == 1


@pytest.mark.anyio
async def test_on_change_is_not_duplicated_during_update():
    machine = Machine("2.1.292")
    machine.new_version = "2.1.295"
    resolver, calls = watching(machine)
    await resolver.refresh()
    refreshed: list[bool] = []

    async def refresh_models() -> bool:
        refreshed.append(True)
        return True

    outcome = await resolver.update(refresh_models)
    assert outcome.after == "2.1.295"
    assert refreshed == [True]
    assert calls == []
    # Back to normal afterwards.
    machine.version = "2.1.300"
    await resolver.refresh(force=True)
    assert len(calls) == 1


@pytest.mark.anyio
async def test_on_change_still_runs_when_update_ends_before_the_models_refresh():
    # The terminal updated by itself and the install then vanished: the models of the
    # old CLI must not stay just because the button was refused.
    machine = Machine("2.1.292")
    resolver, calls = watching(machine)
    await resolver.refresh()
    machine.path = None

    async def refresh_models() -> bool:
        raise AssertionError("not reached")

    with pytest.raises(ClaudeCliUnavailable):
        await resolver.update(refresh_models)
    assert [(o.source, n.source) for o, n in calls] == [("system", "bundled")]
