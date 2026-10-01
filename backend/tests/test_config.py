from pathlib import Path

from claudio_maestro.config import load_settings


def test_settings_follow_environment(tmp_path: Path, home: Path, data_dir: Path):
    settings = load_settings()
    assert settings.home_dir == home
    assert settings.data_dir == data_dir.resolve()
    assert settings.db_path == data_dir.resolve() / "maestro.db"


def test_settings_default_to_user_folders(monkeypatch):
    monkeypatch.delenv("MAESTRO_HOME")
    monkeypatch.delenv("MAESTRO_DATA_DIR")
    monkeypatch.setenv("HOME", "/tmp/fake-home")
    settings = load_settings()
    assert settings.home_dir == Path("/tmp/fake-home").resolve()
    assert settings.data_dir == Path("/tmp/fake-home").resolve() / ".local/share/claudio-maestro"
