"""Settings and data paths, read from the environment."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FRONTEND_PORT = 6600
BACKEND_PORT = 6660
LOCAL_HOSTNAMES = ("localhost", "127.0.0.1")

DB_FILENAME = "vibing.db"


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
    # Folder where the CLI saves conversations, watched for real-time updates.
    # None: `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`, resolved at startup.
    claude_projects_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME


def load_settings() -> Settings:
    """Read settings from the environment.

    `VIBING_HOME` overrides the user's home folder (the folder browser limit).
    `VIBING_DATA_DIR` overrides where the database lives.
    """
    home_env = os.environ.get("VIBING_HOME")
    home = Path(home_env) if home_env else Path.home()
    home = home.resolve()

    data_env = os.environ.get("VIBING_DATA_DIR")
    data_dir = Path(data_env).resolve() if data_env else home / ".local" / "share" / "vini7-vibing"

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
