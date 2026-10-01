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
