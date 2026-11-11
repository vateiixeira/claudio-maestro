"""Only authentication settings reach clients with user settings disabled."""

import json
import os
import stat
from pathlib import Path

import pytest

from claudio_maestro import config
from claudio_maestro.authsettings import MAX_SETTINGS_BYTES, auxiliary_auth_settings


def write_settings(data):
    path = config.claude_config_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def test_auth_env_is_allowlisted_without_mutating_process(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "inherited-fake")
    write_settings({"env": {
        "ANTHROPIC_API_KEY": "profile-fake", "ANTHROPIC_BASE_URL": "https://example.invalid",
        "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1", "AWS_PROFILE": "fake",
        "PATH": "/untrusted", "NODE_OPTIONS": "--require=bad", "CLAUDE_CONFIG_DIR": "/other",
        "ANTHROPIC_AUTH_TOKEN": 123, "AWS_SESSION_TOKEN": "bad\u0000value",
    }, "hooks": {"SessionStart": ["bad"]}, "enabledPlugins": {"bad": True}})
    with auxiliary_auth_settings() as auth:
        assert auth.env == {
            "ANTHROPIC_API_KEY": "profile-fake", "ANTHROPIC_BASE_URL": "https://example.invalid",
            "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1", "AWS_PROFILE": "fake",
        }
        assert auth.settings is None
        assert "profile-fake" not in repr(auth)
    assert os.environ["ANTHROPIC_API_KEY"] == "inherited-fake"


def test_helper_is_private_file_and_removed_even_on_failure():
    write_settings({"apiKeyHelper": "printf fake-key", "hooks": {"SessionStart": ["bad"]}})
    with pytest.raises(RuntimeError):
        with auxiliary_auth_settings() as auth:
            path = Path(auth.settings)
            assert json.loads(path.read_text()) == {"apiKeyHelper": "printf fake-key"}
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
            assert "fake-key" not in auth.settings
            raise RuntimeError("test")
    assert not path.exists()
    assert not path.parent.exists()


@pytest.mark.parametrize("content", [b"{", b"[]", b'"text"', b"\xff", b" " * (MAX_SETTINGS_BYTES + 1)])
def test_invalid_or_oversized_settings_are_ignored(content):
    path = write_settings({})
    path.write_bytes(content)
    with auxiliary_auth_settings() as auth:
        assert auth.env == {} and auth.settings is None


def test_missing_settings_preserve_inherited_auth(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "inherited-fake")
    with auxiliary_auth_settings() as auth:
        assert auth.env == {} and auth.settings is None
    assert os.environ["ANTHROPIC_API_KEY"] == "inherited-fake"


def test_fifo_is_not_opened_for_blocking_read():
    path = config.claude_config_dir() / "settings.json"
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    with auxiliary_auth_settings() as auth:
        assert auth.env == {} and auth.settings is None


def test_current_config_is_read_for_each_call(tmp_path, monkeypatch):
    write_settings({"env": {"ANTHROPIC_API_KEY": "first-fake"}})
    with auxiliary_auth_settings() as auth:
        assert auth.env["ANTHROPIC_API_KEY"] == "first-fake"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "other"))
    write_settings({"env": {"ANTHROPIC_API_KEY": "second-fake"}})
    with auxiliary_auth_settings() as auth:
        assert auth.env["ANTHROPIC_API_KEY"] == "second-fake"


def test_anthropic_aws_provider_settings():
    env = {
        "CLAUDE_CODE_USE_ANTHROPIC_AWS": "1",
        "ANTHROPIC_AWS_API_KEY": "aws-fake",
        "ANTHROPIC_AWS_BASE_URL": "https://example.invalid",
        "ANTHROPIC_AWS_WORKSPACE_ID": "workspace-fake",
    }
    write_settings({"env": env})
    with auxiliary_auth_settings() as auth:
        assert auth.env == env
