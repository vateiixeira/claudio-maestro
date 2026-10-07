"""Where the app is running: official service, a home-made service, a terminal."""

import subprocess
import sys

import pytest

from claudio_maestro import runmode
from claudio_maestro.runmode import RunMode, detect_run_mode

CGROUP_SERVICE = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/meu-maestro.service\n"
CGROUP_TERMINAL = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-gnome-terminal-1.scope\n"


@pytest.mark.parametrize(
    ("env", "tty", "cgroup", "expected"),
    [
        ({"MAESTRO_RUN_MODE": "systemd", "INVOCATION_ID": "x"}, False, CGROUP_SERVICE,
         RunMode("service-systemd", "claudio-maestro.service")),
        ({"MAESTRO_RUN_MODE": "launchd", "XPC_SERVICE_NAME": "io.github.vateiixeira.claudio-maestro"}, False, None,
         RunMode("service-launchd", "io.github.vateiixeira.claudio-maestro")),
        # A terminal opened by GNOME inherits INVOCATION_ID from gnome-terminal-server.service.
        ({"INVOCATION_ID": "x"}, True, CGROUP_TERMINAL, RunMode("terminal")),
        ({"INVOCATION_ID": "x"}, False, CGROUP_SERVICE, RunMode("systemd", "meu-maestro.service")),
        ({"INVOCATION_ID": "x"}, False, CGROUP_TERMINAL, RunMode("unknown")),
        ({"INVOCATION_ID": "x"}, False, None, RunMode("unknown")),
        ({"XPC_SERVICE_NAME": "com.fulano.maestro"}, False, None, RunMode("launchd", "com.fulano.maestro")),
        ({"XPC_SERVICE_NAME": "0"}, False, None, RunMode("unknown")),
        ({"XPC_SERVICE_NAME": "application.com.apple.Terminal.123"}, False, None, RunMode("unknown")),
        ({"XPC_SERVICE_NAME": "0"}, True, None, RunMode("terminal")),
        ({}, True, None, RunMode("terminal")),
        ({}, False, None, RunMode("unknown")),
        ({"MAESTRO_RUN_MODE": "outra-coisa"}, False, None, RunMode("unknown")),
    ],
)
def test_detect_run_mode(env, tty, cgroup, expected):
    assert detect_run_mode(env, stdin_isatty=tty, cgroup_text=cgroup) == expected


def test_as_dict():
    assert RunMode("systemd", "a.service", "process").as_dict() == {
        "kind": "systemd", "unit": "a.service", "kill_mode": "process",
    }


class Run:
    def __init__(self, stdout="process\n", code=0, exc=None):
        self.calls = []
        self.stdout, self.code, self.exc = stdout, code, exc

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.code, self.stdout, "")


def test_kill_mode_reads_systemctl_with_argument_list():
    run = Run("control-group\n")
    assert runmode.kill_mode("meu.service", run=run, which=lambda name: "/usr/bin/systemctl") == "control-group"
    argv, kwargs = run.calls[0]
    assert argv == ["/usr/bin/systemctl", "--user", "show", "meu.service", "-p", "KillMode", "--value"]
    assert kwargs["timeout"] == 5
    assert "shell" not in kwargs


@pytest.mark.parametrize(
    "run",
    [Run(code=1), Run(stdout=""), Run(exc=subprocess.TimeoutExpired("systemctl", 5)), Run(exc=OSError("x"))],
)
def test_kill_mode_none_on_failure(run):
    assert runmode.kill_mode("meu.service", run=run, which=lambda name: "/usr/bin/systemctl") is None


def test_kill_mode_none_without_systemctl():
    assert runmode.kill_mode("meu.service", run=Run(), which=lambda name: None) is None


def test_current_run_mode_reads_kill_mode_only_for_home_made_systemd(monkeypatch):
    monkeypatch.setattr(runmode, "_read_cgroup", lambda: CGROUP_SERVICE)
    monkeypatch.setattr(runmode, "_stdin_isatty", lambda: False)
    monkeypatch.setenv("INVOCATION_ID", "x")
    monkeypatch.delenv("MAESTRO_RUN_MODE", raising=False)
    mode = runmode.current_run_mode(run=Run("process\n"), which=lambda name: "/usr/bin/systemctl")
    assert mode == RunMode("systemd", "meu-maestro.service", "process")

    monkeypatch.setenv("MAESTRO_RUN_MODE", "systemd")
    run = Run()
    assert runmode.current_run_mode(run=run, which=lambda name: "/usr/bin/systemctl").kind == "service-systemd"
    assert run.calls == []


def test_current_run_mode_survives_closed_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(runmode, "_read_cgroup", lambda: None)
    for name in ("MAESTRO_RUN_MODE", "INVOCATION_ID", "XPC_SERVICE_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert runmode.current_run_mode(run=Run(), which=lambda name: None) == RunMode("unknown")
