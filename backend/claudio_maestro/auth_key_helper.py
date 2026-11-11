"""Small API-key bridge for the CLI; argv contains a folder, never a credential.

This file also runs directly with Python -I, so it imports only the standard
library and does not depend on the session's working directory or PYTHONPATH.
"""

import json
import os
import signal
import stat
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

MAX_BYTES = 1024 * 1024
ERROR = "Não foi possível obter a autenticação de API da pasta escolhida."


def valid_key(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 16384 and all(
        33 <= ord(char) <= 126 for char in value
    )


def read_source(folder: Path) -> tuple[str | None, str | None]:
    """Read only the API key/helper, failing closed without exposing file contents."""
    try:
        fd = os.open(folder / "settings.json", os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        env = data.get("env")
        key = env.get("ANTHROPIC_API_KEY") if isinstance(env, dict) else None
        if key not in (None, ""):
            if not valid_key(key):
                raise ValueError
            return key, None
        helper = data.get("apiKeyHelper")
        if not isinstance(helper, str) or not helper.strip() or "\0" in helper:
            raise ValueError
        return None, helper
    except (OSError, ValueError, RecursionError):
        raise ValueError(ERROR) from None


def api_key(folder: Path) -> str:
    key, helper = read_source(folder)
    if key is not None:
        return key
    # apiKeyHelper is explicitly a shell command in the CLI's settings contract.
    # Only that configured helper is delegated; its stderr never reaches logs/UI.
    process = subprocess.Popen(  # noqa: S603 - configured credential helper, CLI contract
        ["/bin/sh", "-c", helper], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=30)
    except BaseException:
        # A shell helper may have children. Kill its whole isolated group rather
        # than leaving a credential command running after its request timed out.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    try:
        key = stdout.decode("ascii").strip()
    except UnicodeError:
        raise ValueError(ERROR) from None
    if process.returncode or not valid_key(key):
        raise ValueError(ERROR)
    return key


def _terminate(signum, _frame) -> None:
    # The CLI may stop this wrapper while its shell helper runs in another group.
    # Raise through api_key's cleanup rather than abandoning that helper.
    raise SystemExit(128 + signum)


def main() -> int:
    signal.signal(signal.SIGTERM, _terminate)
    try:
        if len(sys.argv) != 2:
            raise ValueError(ERROR)
        print(api_key(Path(sys.argv[1])))
    except (OSError, ValueError, subprocess.SubprocessError):
        print(ERROR, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
