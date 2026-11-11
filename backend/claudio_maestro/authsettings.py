"""Authentication for auxiliary SDK clients without loading user hooks or plugins."""

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from claudio_maestro.config import claude_config_dir

MAX_SETTINGS_BYTES = 1024 * 1024
# Explicit names only: never copy process controls such as PATH/NODE_OPTIONS,
# settings sources, hooks, plugins, model defaults or permission settings.
AUTH_ENV_KEYS = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_AWS_BASE_URL", "ANTHROPIC_AWS_WORKSPACE_ID",
    "CLAUDE_CODE_SKIP_BEDROCK_AUTH", "CLAUDE_CODE_SKIP_VERTEX_AUTH",
    "CLAUDE_CODE_SKIP_FOUNDRY_AUTH", "ANTHROPIC_BEDROCK_BASE_URL",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK", "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION",
    "ANTHROPIC_VERTEX_PROJECT_ID", "CLOUD_ML_REGION", "GOOGLE_APPLICATION_CREDENTIALS",
    "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_BASE_URL",
})


@dataclass(frozen=True)
class AuxiliaryAuth:
    env: dict[str, str] = field(default_factory=dict, repr=False)
    settings: str | None = None


def _read_settings() -> dict[str, Any]:
    try:
        # Nonblocking open plus fstat also handles a settings path replaced with a FIFO.
        fd = os.open(claude_config_dir() / "settings.json", os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return {}
            raw = stream.read(MAX_SETTINGS_BYTES + 1)
        if len(raw) > MAX_SETTINGS_BYTES:
            return {}
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


@contextmanager
def auxiliary_auth_settings() -> Iterator[AuxiliaryAuth]:
    """Keep a private helper-settings file alive until the caller closes its SDK client.

    Missing/invalid settings leave inherited environment authentication untouched.
    apiKeyHelper is intentionally allowed, but no other executable settings are loaded.
    Neither credentials nor helper commands go into command-line arguments or logs.
    """
    settings = _read_settings()
    raw_env = settings.get("env")
    env = {
        key: value for key, value in raw_env.items()
        if key in AUTH_ENV_KEYS and isinstance(value, str) and "\0" not in value
    } if isinstance(raw_env, dict) else {}
    helper = settings.get("apiKeyHelper")
    if not isinstance(helper, str) or not helper.strip() or "\0" in helper:
        yield AuxiliaryAuth(env=env)
        return
    with TemporaryDirectory(prefix="maestro-auth-") as directory:
        path = Path(directory) / "settings.json"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"apiKeyHelper": helper}, stream)
        yield AuxiliaryAuth(env=env, settings=str(path))
