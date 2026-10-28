from pathlib import Path

import pytest

from claudio_maestro import config
from claudio_maestro.config import load_settings


def test_settings_follow_environment(tmp_path: Path, home: Path, data_dir: Path):
    settings = load_settings()
    assert settings.home_dir == home
    assert settings.data_dir == data_dir.resolve()
    assert settings.db_path == data_dir.resolve() / "maestro.db"


def test_settings_default_to_user_folders(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    monkeypatch.delenv("MAESTRO_HOME")
    monkeypatch.delenv("MAESTRO_DATA_DIR")
    monkeypatch.setenv("HOME", str(fake_home))
    settings = load_settings()
    assert settings.home_dir == fake_home.resolve()
    assert settings.data_dir == fake_home.resolve() / ".local/share/claudio-maestro"


def test_ports_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_PORT", raising=False)
    monkeypatch.delenv("MAESTRO_DEV_PORT", raising=False)
    assert config.backend_port() == 6660
    assert config.dev_port() == 6600


def test_ports_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PORT", "7000")
    monkeypatch.setenv("MAESTRO_DEV_PORT", "7100")
    assert config.backend_port() == 7000
    assert config.dev_port() == 7100


def test_preview_port_is_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_PREVIEW_PORT", raising=False)
    assert config.preview_port() is None
    monkeypatch.setenv("MAESTRO_PREVIEW_PORT", "")
    assert config.preview_port() is None


def test_preview_port_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PREVIEW_PORT", "6610")
    assert config.preview_port() == 6610


def test_preview_port_is_validated(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PREVIEW_PORT", "6667")
    with pytest.raises(config.PortError, match="MAESTRO_PREVIEW_PORT"):
        config.preview_port()


def test_empty_port_uses_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_PORT", "")
    assert config.backend_port() == 6660


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("abc", "número"),
        ("6660.5", "número"),
        ("80", "1024 e 65535"),
        ("70000", "1024 e 65535"),
        ("-1", "1024 e 65535"),
        ("6666", "6665 a 6669"),
    ],
)
def test_invalid_port_rejected_with_message(monkeypatch: pytest.MonkeyPatch, raw: str, fragment: str):
    monkeypatch.setenv("MAESTRO_PORT", raw)
    with pytest.raises(config.PortError) as exc_info:
        config.backend_port()
    assert "MAESTRO_PORT" in str(exc_info.value)
    assert fragment in str(exc_info.value)


def test_validate_port_names_its_source():
    with pytest.raises(config.PortError, match="--port"):
        config.validate_port("abc", "--port")
    assert config.validate_port("7000", "--port") == 7000


def test_claude_check_is_on_by_default_and_off_with_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_CLAUDE_CHECK")
    assert load_settings().claude_check is True
    monkeypatch.setenv("MAESTRO_CLAUDE_CHECK", "1")
    assert load_settings().claude_check is True
    monkeypatch.setenv("MAESTRO_CLAUDE_CHECK", "0")
    assert load_settings().claude_check is False


def test_claude_check_timing_defaults():
    settings = load_settings()
    assert settings.claude_check_delay_seconds == 60
    assert settings.claude_check_interval_seconds == 24 * 3600


def test_hooks_port_off_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_HOOKS_PORT", raising=False)
    assert config.hooks_port() is None
    assert load_settings().hooks_port is None
    monkeypatch.setenv("MAESTRO_HOOKS_PORT", "")
    assert config.hooks_port() is None


def test_hooks_port_from_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_HOOKS_PORT", "6680")
    assert config.hooks_port() == 6680
    assert load_settings().hooks_port == 6680


@pytest.mark.parametrize("raw", ["6667", "80", "70000", "abc"])
def test_hooks_port_rejects_blocked_range(monkeypatch: pytest.MonkeyPatch, raw: str):
    monkeypatch.setenv("MAESTRO_HOOKS_PORT", raw)
    with pytest.raises(config.PortError, match="MAESTRO_HOOKS_PORT"):
        config.hooks_port()


@pytest.mark.parametrize(
    "other", ["MAESTRO_PORT", "MAESTRO_DEV_PORT", "MAESTRO_PREVIEW_PORT"]
)
def test_hooks_port_must_differ_from_app_ports(monkeypatch: pytest.MonkeyPatch, other: str):
    monkeypatch.setenv(other, "6680")
    monkeypatch.setenv("MAESTRO_HOOKS_PORT", "6680")
    with pytest.raises(config.PortError, match=other):
        config.hooks_port()


def test_hooks_port_must_differ_from_default_ports(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_PORT", raising=False)
    monkeypatch.setenv("MAESTRO_HOOKS_PORT", "6660")
    with pytest.raises(config.PortError, match="MAESTRO_PORT"):
        config.hooks_port()


# Scheduler of the routines ---------------------------------------------------------


def test_routines_scheduler_is_on_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAESTRO_ROUTINES_SCHEDULER", raising=False)
    monkeypatch.delenv("MAESTRO_SPECIALISTS_SCHEDULER", raising=False)
    assert load_settings().routines_scheduler is True


@pytest.mark.parametrize(("raw", "expected"), [("0", False), ("1", True)])
def test_routines_scheduler_follows_its_variable(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
):
    monkeypatch.delenv("MAESTRO_SPECIALISTS_SCHEDULER", raising=False)
    monkeypatch.setenv("MAESTRO_ROUTINES_SCHEDULER", raw)
    assert load_settings().routines_scheduler is expected


@pytest.mark.parametrize(("raw", "expected"), [("0", False), ("1", True)])
def test_old_scheduler_variable_still_counts_as_an_alias(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
):
    monkeypatch.delenv("MAESTRO_ROUTINES_SCHEDULER", raising=False)
    monkeypatch.setenv("MAESTRO_SPECIALISTS_SCHEDULER", raw)
    assert load_settings().routines_scheduler is expected


@pytest.mark.parametrize(("new", "old", "expected"), [("1", "0", True), ("0", "1", False)])
def test_new_scheduler_variable_wins_over_the_old_one(
    monkeypatch: pytest.MonkeyPatch, new: str, old: str, expected: bool
):
    monkeypatch.setenv("MAESTRO_ROUTINES_SCHEDULER", new)
    monkeypatch.setenv("MAESTRO_SPECIALISTS_SCHEDULER", old)
    assert load_settings().routines_scheduler is expected


def test_the_old_work_dispatcher_setting_is_gone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAESTRO_WORK_DISPATCHER", "1")
    settings = load_settings()
    assert not hasattr(settings, "work_dispatcher")
    assert not hasattr(settings, "work_dispatcher_enabled")
