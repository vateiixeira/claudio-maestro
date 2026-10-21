"""Process start times use local metadata only; failures remain best effort."""

import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from claudio_maestro import procinfo


def test_started_at_of_own_process_is_in_the_past():
    started = procinfo.process_started_at(os.getpid())
    assert started is not None
    assert time.time() - 86400 * 30 < started <= time.time()


def test_unknown_pid_gives_none():
    child = subprocess.Popen(["true"])
    child.wait()
    assert procinfo.process_started_at(child.pid) is None


def test_stat_with_spaces_and_parens_in_name(tmp_path, monkeypatch):
    monkeypatch.setattr(procinfo, "_PROC", tmp_path)
    monkeypatch.setattr(procinfo.sys, "platform", "linux")
    monkeypatch.setattr(procinfo.os, "sysconf", lambda name: 100)
    (tmp_path / "stat").write_text("cpu 1 2 3\nbtime 1000\n")
    (tmp_path / "42").mkdir()
    # The first token after the last ')' is field 3; field 22 is index 19.
    (tmp_path / "42" / "stat").write_text("42 (a b) c) S " + "0 " * 18 + "12300 0 0")
    assert procinfo.process_started_at(42) == 1123


@pytest.mark.parametrize("elapsed, seconds", [("05:03", 303), ("02:05:03", 7503),
                                               ("1-02:05:03", 93903)])
def test_ps_etime_formats(monkeypatch, elapsed, seconds):
    monkeypatch.setattr(procinfo.sys, "platform", "darwin")
    monkeypatch.setattr(procinfo.time, "time", lambda: 200000)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=f" {elapsed}\n", returncode=0)

    monkeypatch.setattr(procinfo.subprocess, "run", run)
    assert procinfo.process_started_at(42) == 200000 - seconds
    assert calls == [(["ps", "-o", "etime=", "-p", "42"],
                      {"capture_output": True, "text": True, "timeout": 2, "check": True})]


@pytest.mark.parametrize("failure", [OSError("no ps"), subprocess.TimeoutExpired("ps", 2),
                                      subprocess.CalledProcessError(1, "ps"),
                                      ValueError("invalid value")])
def test_ps_errors_never_escape(monkeypatch, failure):
    monkeypatch.setattr(procinfo.sys, "platform", "darwin")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(procinfo.subprocess, "run", fail)
    assert procinfo.process_started_at(42) is None


@pytest.mark.parametrize("elapsed", ["", "oops", "-1:01", "1:2:3:4", "01:99", "1-xx:00:00", "1-02:03"])
def test_ps_malformed_times_give_none(monkeypatch, elapsed):
    monkeypatch.setattr(procinfo.sys, "platform", "darwin")
    monkeypatch.setattr(procinfo.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=elapsed))
    assert procinfo.process_started_at(42) is None


@pytest.mark.parametrize("content", ["", "42 (missing fields) S 0", "42 (x) " + "x " * 22])
def test_malformed_proc_stat_gives_none(tmp_path, monkeypatch, content):
    monkeypatch.setattr(procinfo, "_PROC", tmp_path)
    monkeypatch.setattr(procinfo.sys, "platform", "linux")
    (tmp_path / "42").mkdir()
    (tmp_path / "42" / "stat").write_text(content)
    (tmp_path / "stat").write_text("btime 1000\n")
    assert procinfo.process_started_at(42) is None


@pytest.mark.parametrize("pid", [0, -1])
def test_nonpositive_pid_gives_none(pid):
    assert procinfo.process_started_at(pid) is None
