"""Where the agentd socket and lock live."""

import hashlib
import os
from pathlib import Path

from claudio_maestro.agentd import LOCK_NAME, SOCKET_NAME

# sun_path holds 104 bytes on macOS and 108 on Linux; keep a margin.
MAX_SOCKET_PATH = 100


def socket_path(data_dir: Path) -> Path:
    """`<data_dir>/agentd-v1.sock`, or a short path when that is too long."""
    candidate = data_dir / SOCKET_NAME
    if len(str(candidate).encode()) <= MAX_SOCKET_PATH:
        return candidate
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(f"/tmp/claudio-maestro-{os.getuid()}")
    digest = hashlib.sha1(str(data_dir).encode()).hexdigest()[:10]
    return base / "claudio-maestro" / f"{digest}-{SOCKET_NAME}"


def lock_path(data_dir: Path) -> Path:
    return data_dir / LOCK_NAME


def private_dir(path: Path) -> None:
    """Create `path` (and parents) and make it 0700."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
