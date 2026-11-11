"""Select a Claude home at startup, with separate Maestro data per folder.

Only a folder name is stored. Credential files are neither read nor copied here.
"""

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claudio_maestro.config import Settings

FILENAME = "claude-profile.json"
AUTH_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_API_KEY_HELPER_TTL_MS")


class ProfileError(ValueError):
    """A folder selection that cannot be applied safely."""


def validate_folder(raw: str, home: Path) -> Path:
    # This dedicated setting authorizes a configuration folder inside the user's
    # home, not general file access outside registered projects.
    if not raw or len(raw) > 4096 or any(ord(c) < 32 for c in raw):
        raise ProfileError("Informe uma pasta de configuração válida.")
    path = home / raw[2:] if raw.startswith("~/") else Path(raw)
    if not path.is_absolute():
        raise ProfileError("Use um caminho absoluto ou começando com ~/.")
    try:
        path = path.resolve(strict=True)
        root = home.resolve()
        if path == root or not path.is_relative_to(root) or not path.is_dir():
            raise ProfileError(
                "Escolha uma pasta existente dentro da sua pasta pessoal."
            )
    except (OSError, RuntimeError) as exc:
        raise ProfileError("A pasta não existe ou não está acessível.") from exc
    return path


def read_selection(root: Path, home: Path) -> Path | None:
    try:
        with (root / FILENAME).open(encoding="utf-8") as stream:
            raw = stream.read(65537)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise ProfileError(
            "Não foi possível ler a escolha da pasta do Claude."
        ) from exc
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {"folder"}:
            raise ValueError
        folder = data["folder"]
        if folder is None:
            return None
        if not isinstance(folder, str):
            raise ValueError
    except ValueError as exc:
        raise ProfileError("A escolha da pasta do Claude está inválida.") from exc
    return validate_folder(folder, home)


def save_selection(root: Path, raw: str | None, home: Path) -> None:
    folder = validate_folder(raw, home) if raw is not None else None
    root.mkdir(parents=True, exist_ok=True)
    # Atomic replace also avoids following a symlink at the destination filename.
    fd, name = tempfile.mkstemp(prefix=".claude-profile-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {"folder": str(folder) if folder else None}, stream, ensure_ascii=False
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, root / FILENAME)
    finally:
        Path(name).unlink(missing_ok=True)


def profile_data_dir(root: Path, folder: Path | None) -> Path:
    if folder is None:
        return root
    key = hashlib.sha256(os.fsencode(folder)).hexdigest()
    return root / "profiles" / key


@contextmanager
def profile_environment(settings: "Settings"):
    folder = settings.claude_config_dir
    # Unset CLAUDE_CONFIG_DIR differs from an explicit ~/.claude for the CLI's
    # global config and keychain. Preserve the original environment by default.
    if folder is None or not settings.profile_isolated:
        yield
        return
    changed = ["CLAUDE_CONFIG_DIR"]
    changed.extend(AUTH_ENV)
    changed.extend(
        key
        for key in os.environ
        if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_SKIP_"))
    )
    previous = {key: os.environ.get(key) for key in changed}
    try:
        for key in changed:
            os.environ.pop(key, None)
        os.environ["CLAUDE_CONFIG_DIR"] = str(folder)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
