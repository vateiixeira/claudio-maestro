"""Settings and data paths, read from the environment."""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BACKEND_PORT = 6660
DEFAULT_DEV_PORT = 6600
# Browsers refuse these ports (IRC), so the app could never be opened on them.
BROWSER_BLOCKED_PORTS = range(6665, 6670)
LOCAL_HOSTNAMES = ("localhost", "127.0.0.1")

DB_FILENAME = "maestro.db"
DATA_DIR_NAME = "claudio-maestro"
# The app was called Vini7 Vibing before going public; its data is moved on first start.
LEGACY_DATA_DIR_NAME = "vini7-vibing"
LEGACY_DB_FILENAME = "vibing.db"


class PortError(ValueError):
    """Invalid port setting. The message is for the user."""


def validate_port(raw: str | int, source: str) -> int:
    """`raw` as a port, or `PortError` naming `source` (variable or option)."""
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise PortError(f"{source} precisa ser um número de porta, não {raw!r}.") from None
    if not 1024 <= port <= 65535:
        raise PortError(f"{source} precisa estar entre 1024 e 65535 (recebido {port}).")
    if port in BROWSER_BLOCKED_PORTS:
        raise PortError(f"{source} não pode ser de 6665 a 6669: os navegadores bloqueiam essas portas.")
    return port


def _port_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if not raw else validate_port(raw, name)


def backend_port() -> int:
    """Port of the backend (and of the app in single-command mode): `MAESTRO_PORT`."""
    return _port_from_env("MAESTRO_PORT", DEFAULT_BACKEND_PORT)


def dev_port() -> int:
    """Port of the Vite dev server: `MAESTRO_DEV_PORT`."""
    return _port_from_env("MAESTRO_DEV_PORT", DEFAULT_DEV_PORT)


@dataclass(frozen=True)
class Settings:
    home_dir: Path
    data_dir: Path
    # A session idle this long has its client closed; it resumes on the next message.
    idle_timeout_seconds: float = 30 * 60
    idle_sweep_interval_seconds: float = 60
    # Default for "finished by inactivity"; `preferences.finished_after_days` overrides it.
    finished_after_days: float = 3
    # The history index is synced at startup and then every this many seconds.
    history_sync_interval_seconds: float = 60
    # Git branches are refreshed this often while a WebSocket is connected.
    git_refresh_interval_seconds: float = 30
    # The stored models list is checked at startup and then this often (3 times a day).
    models_refresh_interval_seconds: float = 8 * 3600
    # Progress of plans linked to unfinished conversations is reread this often.
    plan_sweep_interval_seconds: float = 30
    # Folder where the CLI saves conversations, watched for real-time updates.
    # None: `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`, resolved at startup.
    claude_projects_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME


def default_data_dir(home: Path) -> Path:
    return home / ".local" / "share" / DATA_DIR_NAME


def legacy_data_dir(home: Path) -> Path:
    return home / ".local" / "share" / LEGACY_DATA_DIR_NAME


class DataMigrationError(RuntimeError):
    """The old data could not be migrated safely. The message is for the user."""


def _prepare_legacy_database(folder: Path) -> None:
    """Make `vibing.db` a single self-contained file named `maestro.db`.

    Does nothing when there is no `vibing.db` or `maestro.db` already exists. Otherwise:
    1. Checkpoint the WAL into the main file, so no data lives only in `-wal`.
    2. If `-wal`/`-shm` survive the close, another process still has the database open
       (the old app running); renaming under it would lose writes, so abort.
    3. Rename just `vibing.db`: a single rename, so there is no half-done state.
    Raises `DataMigrationError` and leaves the files as they were on any failure.
    """
    source = folder / LEGACY_DB_FILENAME
    if (folder / DB_FILENAME).exists() or not source.exists():
        return
    try:
        conn = sqlite3.connect(source, timeout=1)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise DataMigrationError(
            f"Não foi possível ler o banco antigo em {source} ({exc}). "
            "Os dados não foram alterados."
        ) from exc
    if any((folder / f"{LEGACY_DB_FILENAME}{suffix}").exists() for suffix in ("-wal", "-shm")):
        raise DataMigrationError(
            f"O banco em {source} está aberto por outro processo (a versão antiga do app "
            "ainda está rodando?). Feche-o e inicie de novo."
        )
    try:
        os.rename(source, folder / DB_FILENAME)
    except OSError as exc:
        raise DataMigrationError(
            f"Não foi possível renomear o banco antigo em {source} ({exc}). "
            "Os dados não foram alterados."
        ) from exc


def migrate_legacy_data_dir(home: Path) -> Path:
    """Move the old name's data folder to the new one; return the folder to use.

    - No old folder: the new folder (not created here).
    - Both exist: the new one; nothing is touched.
    - The old database cannot be prepared (unreadable, open in another process, rename
      fails): `DataMigrationError`, nothing changed, so the app never starts on an empty
      database while real data sits in the old folder.
    - Moving the folder fails: the old folder keeps being used, so the data never
      disappears. The database is renamed to `maestro.db` before the move, so the app
      finds it there too.
    """
    new = default_data_dir(home)
    old = legacy_data_dir(home)
    if not old.is_dir():
        return new
    if new.exists():
        logger.warning(
            "Há dados do nome antigo em %s e do novo em %s. Usando %s; a pasta antiga não foi tocada.",
            old, new, new,
        )
        return new
    _prepare_legacy_database(old)
    try:
        os.rename(old, new)
    except OSError as exc:
        logger.error("Não foi possível mover %s para %s (%s). Usando a pasta antiga.", old, new, exc)
        return old
    logger.info("Dados movidos de %s para %s.", old, new)
    return new


def load_settings() -> Settings:
    """Read settings from the environment.

    `MAESTRO_HOME` overrides the user's home folder (the folder browser limit).
    `MAESTRO_DATA_DIR` overrides where the database lives. Without it, data left by the
    old name (`vini7-vibing`) is moved to the new folder first (see `migrate_legacy_data_dir`);
    `DataMigrationError` propagates when that cannot be done safely.
    """
    home_env = os.environ.get("MAESTRO_HOME")
    home = Path(home_env) if home_env else Path.home()
    home = home.resolve()

    data_env = os.environ.get("MAESTRO_DATA_DIR")
    data_dir = Path(data_env).resolve() if data_env else migrate_legacy_data_dir(home)

    return Settings(
        home_dir=home, data_dir=data_dir, claude_projects_dir=claude_projects_dir()
    )


def claude_config_dir() -> Path:
    """The CLI configuration folder (`CLAUDE_CONFIG_DIR` or `~/.claude`)."""
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(config) if config else Path.home() / ".claude"


def claude_projects_dir() -> Path:
    """Where the CLI saves conversations (respects `CLAUDE_CONFIG_DIR`, like the SDK)."""
    return claude_config_dir() / "projects"


def read_user_claude_settings() -> dict[str, Any]:
    """The user's CLI `settings.json`; empty when missing, unreadable or invalid."""
    path = claude_config_dir() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
