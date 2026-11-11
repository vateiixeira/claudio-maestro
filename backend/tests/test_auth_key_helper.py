"""Alternate API authentication preserves history and never puts keys in argv."""

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from claudio_maestro import auth_key_helper, claudeprofile
from claudio_maestro.agent.base import AgentOptions, AttachInfo
from claudio_maestro.agent.sdk_client import build_sdk_options
from claudio_maestro.agent.spawn import build_cli_spawn
from claudio_maestro.authsettings import auxiliary_auth_settings


def selected(monkeypatch, tmp_path, value):
    folder = tmp_path / "api"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps(value))
    monkeypatch.setattr(claudeprofile, "active_auth_folder", lambda: folder)
    return folder


def test_sdk_auth_overlay_preserves_history_and_session_settings(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {
        "env": {"ANTHROPIC_API_KEY": "fake-selected-key", "ANTHROPIC_BASE_URL": "https://ignored.invalid"},
        "hooks": {"SessionStart": ["must not load"]}, "enabledPlugins": {"other": True},
    })
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fake-old-token")
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    history = os.environ["CLAUDE_CONFIG_DIR"]
    options = AgentOptions(cwd=tmp_path, session_id="session", resume=True, can_use_tool=None,
                           settings=json.dumps({"permissions": {"deny": ["Bash(rm *)"]}, "env": {"CUSTOM": "keep"}}))
    sdk = build_sdk_options(options)
    overlay = json.loads(sdk.settings)
    assert str(folder) in overlay["apiKeyHelper"]
    assert "fake-selected-key" not in sdk.settings
    assert overlay["permissions"] == {"deny": ["Bash(rm *)"]}
    assert overlay["env"]["CUSTOM"] == "keep"
    assert overlay["env"]["ANTHROPIC_AUTH_TOKEN"] == ""
    assert overlay["env"]["CLAUDE_CODE_USE_VERTEX"] == ""
    assert overlay["env"]["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert "hooks" not in overlay and "enabledPlugins" not in overlay
    assert "CLAUDE_CONFIG_DIR" not in sdk.env
    assert os.environ["CLAUDE_CONFIG_DIR"] == history
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "fake-old-token"
    assert sdk.resume == "session"
    spec = build_cli_spawn(sdk)
    assert "fake-selected-key" not in str(spec.cmd)
    assert spec.env["CLAUDE_CONFIG_DIR"] == history


def test_auth_only_keeps_model_and_other_existing_configuration(monkeypatch, tmp_path):
    selected(monkeypatch, tmp_path, {"env": {"ANTHROPIC_API_KEY": "fake-key"}})
    monkeypatch.setenv("ANTHROPIC_MODEL", "current-model")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "current-sonnet")
    sdk = build_sdk_options(AgentOptions(cwd=tmp_path, session_id="session", resume=False, can_use_tool=None))
    env = build_cli_spawn(sdk).env
    assert env["ANTHROPIC_MODEL"] == "current-model"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "current-sonnet"


def test_reattach_does_not_require_a_new_credential(monkeypatch, tmp_path):
    selected(monkeypatch, tmp_path, {})
    options = AgentOptions(cwd=tmp_path, session_id="session", resume=True, can_use_tool=None,
                           attach=AttachInfo(agentd_id="existing", from_pos=0, init_response={}))
    sdk = build_sdk_options(options)
    assert sdk.settings is None


def test_helper_command_quotes_folder_and_uses_isolated_python(monkeypatch, tmp_path):
    folder = tmp_path / "folder with ' quote"
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "fake-key"}}))
    monkeypatch.setattr(claudeprofile, "active_auth_folder", lambda: folder)
    with auxiliary_auth_settings() as auth:
        args = shlex.split(json.loads(auth.settings)["apiKeyHelper"])
    assert args[:2] == [sys.executable, "-I"]
    assert args[-1] == str(folder)
    assert Path(args[2]).is_absolute()


def test_existing_settings_file_is_not_copied_into_argv(monkeypatch, tmp_path):
    selected(monkeypatch, tmp_path, {"env": {"ANTHROPIC_API_KEY": "fake-key"}})
    existing = tmp_path / "session-settings.json"
    existing.write_text(json.dumps({"env": {"CUSTOM_TOKEN": "private-value"}}))
    with pytest.raises(ValueError) as error:
        build_sdk_options(AgentOptions(cwd=tmp_path, session_id="session", resume=False,
                                       can_use_tool=None, settings=str(existing)))
    assert "private-value" not in str(error.value)


def test_auxiliary_clients_use_selected_helper_without_loading_other_settings(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {"env": {"ANTHROPIC_API_KEY": "fake-key"}})
    with auxiliary_auth_settings() as auth:
        assert str(folder) in json.loads(auth.settings)["apiKeyHelper"]
        assert "fake-key" not in auth.settings


@pytest.mark.parametrize("settings", [{}, {"env": {"ANTHROPIC_API_KEY": ""}}, {"env": {"ANTHROPIC_API_KEY": "bad\nkey"}}, {"apiKeyHelper": ""}])
def test_invalid_selected_auth_fails_closed(monkeypatch, tmp_path, settings):
    selected(monkeypatch, tmp_path, settings)
    with pytest.raises(ValueError, match="autenticação"):
        build_sdk_options(AgentOptions(cwd=tmp_path, session_id="session", resume=False, can_use_tool=None))


def run_helper(folder):
    helper = Path(__file__).parents[1] / "claudio_maestro" / "auth_key_helper.py"
    return subprocess.run([sys.executable, "-I", str(helper), str(folder)], capture_output=True, text=True, check=False)


def test_helper_prints_selected_key_and_does_not_modify_files(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {"env": {"ANTHROPIC_API_KEY": "fake-key"}})
    before = (folder / "settings.json").read_bytes()
    result = run_helper(folder)
    assert result.returncode == 0 and result.stdout == "fake-key\n" and result.stderr == ""
    assert (folder / "settings.json").read_bytes() == before


def test_helper_delegates_and_redacts_errors(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {"env": {"ANTHROPIC_API_KEY": ""}, "apiKeyHelper": "printf fake-helper-key"})
    result = run_helper(folder)
    assert result.returncode == 0 and result.stdout == "fake-helper-key\n"
    (folder / "settings.json").write_text(json.dumps({"apiKeyHelper": "printf secret-error >&2; exit 1"}))
    result = run_helper(folder)
    assert result.returncode == 1 and result.stdout == ""
    assert "secret-error" not in result.stderr


def test_helper_missing_key_does_not_fall_back_to_inherited_key(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-old-key")
    result = run_helper(folder)
    assert result.returncode == 1 and result.stdout == ""
    assert "fake-old-key" not in result.stderr


def test_helper_timeout_terminates_its_process_group(monkeypatch, tmp_path):
    folder = selected(monkeypatch, tmp_path, {"apiKeyHelper": "sleep 60"})
    killed = []
    class Process:
        pid = 999
        returncode = -9
        calls = 0
        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("helper", timeout)
            return b"", b""
    process = Process()
    monkeypatch.setattr(auth_key_helper.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(auth_key_helper.os, "killpg", lambda pid, signal: killed.append(pid))
    with pytest.raises(subprocess.TimeoutExpired):
        auth_key_helper.api_key(folder)
    assert killed == [999]


def test_terminating_wrapper_terminates_running_helper(monkeypatch, tmp_path):
    pidfile = tmp_path / "helper.pid"
    folder = selected(monkeypatch, tmp_path, {
        "apiKeyHelper": f"printf '%s' $$ > {shlex.quote(str(pidfile))}; exec sleep 30",
    })
    helper = Path(auth_key_helper.__file__)
    process = subprocess.Popen([sys.executable, "-I", str(helper), str(folder)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child = None
    try:
        deadline = time.monotonic() + 3
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pidfile.exists()
        child = int(pidfile.read_text())
        process.terminate()
        process.communicate(timeout=3)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        if child is not None:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass
