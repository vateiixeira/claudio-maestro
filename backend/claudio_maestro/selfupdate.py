"""Update the app's own clone to the announced release, then restart.

Only ever touches REPO_ROOT (never a path from the client) and only the version the
UpdateChecker announced. Every git goes through run_git; uv and pnpm run with argument
lists, without a shell, in their own process group.
"""

import asyncio
import contextlib
import os
import re
import shutil
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from claudio_maestro.gitinfo import GitError, run_git
from claudio_maestro.updates import current_version, parse_version

# backend/claudio_maestro/selfupdate.py -> repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = "update.log"
RESULT_FILE = "update-result.json"
LOCAL_GIT_TIMEOUT = 30.0
NETWORK_TIMEOUT = 120.0
TOOL_TIMEOUT = 600.0
TAIL = 20
LINE_LIMIT = 1024 * 1024
# Never ask for a password or a host key: the update runs with nobody at the keyboard.
GIT_ENV: dict[str, str | None] = {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}

# A remote name is later passed to `git fetch`, so it must never read as an option.
_REMOTE_NAME = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]*")
_OFFICIAL = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)vateiixeira/claudio-maestro(?:\.git)?/?"
)

Mode = Literal["pull", "tag"]
Git = Callable[..., Awaitable[tuple[int, str, str]]]
RunTool = Callable[[list[str], Path, float, Callable[[str], None]], Awaitable[int]]
Which = Callable[[str], str | None]


def is_official_remote(url: str) -> bool:
    return _OFFICIAL.fullmatch(url.strip()) is not None


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str | None = None
    mode: Mode | None = None
    remote: str | None = None


class UpdateNotAllowed(Exception):
    """The clone cannot be updated by the button (the message says why)."""


class UpdateBusy(Exception):
    """An update is already running."""


class StepFailed(Exception):
    """One step of the update failed (the message is shown to the user)."""


async def run_tool(argv: list[str], cwd: Path, timeout: float, on_line: Callable[[str], None]) -> int:
    """Run `argv` in `cwd`, without a shell, stdout and stderr merged, line by line.

    Raises TimeoutError after `timeout` seconds, killing the whole process group."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True, limit=LINE_LIMIT,
    )

    async def pump() -> int:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            on_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        return await proc.wait()

    try:
        return await asyncio.wait_for(pump(), timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        raise


class SelfUpdater:
    def __init__(
        self,
        repo: Path,
        data_dir: Path,
        publish: Callable[[dict[str, Any]], None],
        *,
        restart: Callable[[], None] | None,
        git: Git = run_git,
        run_tool: RunTool = run_tool,
        which: Which = shutil.which,
        official: Callable[[str], bool] = is_official_remote,
        current: Callable[[], str] = current_version,
    ) -> None:
        self.repo = repo
        self.data_dir = data_dir
        self.log_path = data_dir / LOG_FILE
        self._publish = publish
        self._restart = restart
        self._git_fn = git
        self._run_tool = run_tool
        self._which = which
        self._official = official
        self._current = current
        self._task: asyncio.Task[None] | None = None
        self._starting = False
        self._job: dict[str, Any] | None = None

    @property
    def busy(self) -> bool:
        return self._starting or (self._task is not None and not self._task.done())

    def job_state(self) -> dict[str, Any] | None:
        if self._job is None:
            return None
        return {**self._job, "lines": list(self._job["lines"])}

    async def _git(self, *args: str, timeout: float = LOCAL_GIT_TIMEOUT) -> tuple[int, str, str]:
        return await self._git_fn(self.repo, *args, timeout=timeout, env=GIT_ENV, own_group=True)

    async def check(self) -> Eligibility:
        if self._restart is None:
            return Eligibility(False, "o app não foi iniciado pelo comando claudio-maestro")
        if not (self.repo / ".git").exists():
            return Eligibility(False, "o app não foi instalado por um clone git")
        if self._task is not None and not self._task.done():
            return Eligibility(False, "já há uma atualização em andamento")
        try:
            return await self._check_git()
        except GitError as exc:
            return Eligibility(False, f"não foi possível ler o git: {exc}")

    async def _check_git(self) -> Eligibility:
        code, out, _ = await self._git("status", "--porcelain", "--untracked-files=no")
        if code != 0:
            return Eligibility(False, "não foi possível ler o estado do clone")
        if out.strip():
            return Eligibility(False, "há arquivos alterados no clone")
        mode: Mode
        code, out, _ = await self._git("symbolic-ref", "--quiet", "--short", "HEAD")
        if code == 0:
            branch = out.strip()
            if branch != "main":
                return Eligibility(False, f"o clone está na branch {branch}")
            mode = "pull"
        else:
            code, out, _ = await self._git("tag", "--points-at", "HEAD")
            tags = [t for t in out.split() if t.startswith("v") and parse_version(t) is not None]
            if code != 0 or not tags:
                return Eligibility(False, "o clone está num commit fora de release")
            mode = "tag"
        remote = await self._official_remote()
        if remote is None:
            return Eligibility(False, "nenhum remoto aponta para o repositório oficial")
        for tool in ("uv", "pnpm"):
            if self._which(tool) is None:
                return Eligibility(False, f"{tool} não encontrado no PATH do app")
        return Eligibility(True, mode=mode, remote=remote)

    async def _official_remote(self) -> str | None:
        code, out, _ = await self._git("remote", "-v")
        if code != 0:
            return None
        for line in out.splitlines():
            parts = line.split()
            if (
                len(parts) >= 3
                and parts[2] == "(fetch)"
                and _REMOTE_NAME.fullmatch(parts[0])
                and self._official(parts[1])
            ):
                return parts[0]
        return None
