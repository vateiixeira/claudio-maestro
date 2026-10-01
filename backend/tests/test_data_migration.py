import logging
import os
import sqlite3
from pathlib import Path

import pytest

from claudio_maestro import config

NEW = ".local/share/claudio-maestro"
OLD = ".local/share/vini7-vibing"


def make_database(path: Path, value: str = "dado") -> None:
    """A real SQLite database in WAL mode with one row, closed cleanly."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def read_rows(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT v FROM t")]
    finally:
        conn.close()


def make_legacy(home: Path) -> Path:
    old = home / OLD
    old.mkdir(parents=True)
    make_database(old / "vibing.db")
    (old / "digest-agent").mkdir()
    return old


def test_moves_legacy_folder_and_renames_database(tmp_path: Path):
    home = tmp_path / "h"
    old = make_legacy(home)

    data = config.migrate_legacy_data_dir(home)

    assert data == home / NEW
    assert not old.exists()
    assert read_rows(data / "maestro.db") == ["dado"]
    assert not (data / "vibing.db").exists()
    assert not (data / "vibing.db-wal").exists()
    assert not (data / "vibing.db-shm").exists()
    assert not (data / "maestro.db-wal").exists()
    assert not (data / "maestro.db-shm").exists()
    assert (data / "digest-agent").is_dir()


def test_wal_content_is_checkpointed_into_the_database(tmp_path: Path):
    home = tmp_path / "h"
    old = home / OLD
    old.mkdir(parents=True)
    conn = sqlite3.connect(old / "vibing.db")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 0")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('so no wal')")
    conn.commit()
    conn.close()

    data = config.migrate_legacy_data_dir(home)

    assert read_rows(data / "maestro.db") == ["so no wal"]


def test_without_legacy_folder_returns_new_and_creates_nothing(tmp_path: Path):
    home = tmp_path / "h"
    home.mkdir()

    data = config.migrate_legacy_data_dir(home)

    assert data == home / NEW
    assert not data.exists()


def test_both_folders_keep_new_untouched_and_warn(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    home = tmp_path / "h"
    old = make_legacy(home)
    new = home / NEW
    new.mkdir(parents=True)
    (new / "maestro.db").write_text("novo")

    with caplog.at_level(logging.WARNING):
        data = config.migrate_legacy_data_dir(home)

    assert data == new
    assert (new / "maestro.db").read_text() == "novo"
    assert read_rows(old / "vibing.db") == ["dado"]
    assert "vini7-vibing" in caplog.text


def test_failed_move_keeps_using_legacy_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    home = tmp_path / "h"
    old = make_legacy(home)
    real_rename = os.rename

    def rename(src, dst):
        if Path(src) == old:
            raise OSError("Invalid cross-device link")
        return real_rename(src, dst)

    monkeypatch.setattr(config.os, "rename", rename)

    with caplog.at_level(logging.ERROR):
        data = config.migrate_legacy_data_dir(home)

    assert data == old
    # The database is renamed inside the old folder first, so the app still finds it.
    assert read_rows(old / "maestro.db") == ["dado"]
    assert not (old / "vibing.db").exists()
    assert not (home / NEW).exists()
    assert "cross-device" in caplog.text


def test_database_open_elsewhere_aborts_without_touching_anything(tmp_path: Path):
    home = tmp_path / "h"
    old = make_legacy(home)
    other = sqlite3.connect(old / "vibing.db")  # the old app, still running
    try:
        other.execute("PRAGMA journal_mode = WAL")
        other.execute("INSERT INTO t VALUES ('escrita nova')")
        other.commit()

        with pytest.raises(config.DataMigrationError) as error:
            config.migrate_legacy_data_dir(home)

        assert str(old / "vibing.db") in str(error.value)
        assert "aberto por outro processo" in str(error.value)
        assert (old / "vibing.db").exists()
        assert not (old / "maestro.db").exists()
        assert (old / "digest-agent").is_dir()
        assert not (home / NEW).exists()
    finally:
        other.close()
    assert read_rows(old / "vibing.db") == ["dado", "escrita nova"]


def test_failed_database_rename_raises_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "h"
    old = make_legacy(home)
    real_rename = os.rename

    def rename(src, dst):
        if Path(src) == old / "vibing.db":
            raise OSError("Permission denied")
        return real_rename(src, dst)

    monkeypatch.setattr(config.os, "rename", rename)

    with pytest.raises(config.DataMigrationError) as error:
        config.migrate_legacy_data_dir(home)

    assert str(old / "vibing.db") in str(error.value)
    assert read_rows(old / "vibing.db") == ["dado"]
    assert not (old / "maestro.db").exists()
    assert not (home / NEW).exists()


def test_unreadable_database_raises(tmp_path: Path):
    home = tmp_path / "h"
    old = home / OLD
    old.mkdir(parents=True)
    (old / "vibing.db").write_bytes(b"this is not a sqlite database" * 100)

    with pytest.raises(config.DataMigrationError) as error:
        config.migrate_legacy_data_dir(home)

    assert str(old / "vibing.db") in str(error.value)
    assert (old / "vibing.db").exists()
    assert not (home / NEW).exists()


def test_existing_new_database_name_in_old_folder_is_not_touched(tmp_path: Path):
    home = tmp_path / "h"
    old = make_legacy(home)
    make_database(old / "maestro.db", "ja migrado")

    data = config.migrate_legacy_data_dir(home)

    assert data == home / NEW
    assert read_rows(data / "maestro.db") == ["ja migrado"]
    assert read_rows(data / "vibing.db") == ["dado"]


def test_load_settings_migrates_without_data_dir_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "h"
    make_legacy(home)
    monkeypatch.setenv("MAESTRO_HOME", str(home))
    monkeypatch.delenv("MAESTRO_DATA_DIR")

    settings = config.load_settings()

    assert settings.data_dir == home.resolve() / NEW
    assert read_rows(settings.db_path) == ["dado"]


def test_load_settings_propagates_migration_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "h"
    old = make_legacy(home)
    monkeypatch.setenv("MAESTRO_HOME", str(home))
    monkeypatch.delenv("MAESTRO_DATA_DIR")
    other = sqlite3.connect(old / "vibing.db")
    try:
        other.execute("INSERT INTO t VALUES ('aberto')")
        other.commit()

        with pytest.raises(config.DataMigrationError):
            config.load_settings()
    finally:
        other.close()


def test_load_settings_with_data_dir_env_does_not_migrate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "h"
    old = make_legacy(home)
    monkeypatch.setenv("MAESTRO_HOME", str(home))  # MAESTRO_DATA_DIR comes from conftest

    config.load_settings()

    assert old.exists()
    assert not (home / NEW).exists()


def test_history_ignores_new_and_legacy_agent_folders(client, home: Path, data_dir: Path):
    ignored = client.app.state.history._ignored
    assert str((data_dir / "digest-agent").resolve()) in ignored
    assert str((home / OLD / "digest-agent").resolve()) in ignored
