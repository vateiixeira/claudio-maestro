"""Update the app's own clone to the announced release, then restart.

Only ever touches REPO_ROOT (never a path from the client) and only the version the
UpdateChecker announced. Every git goes through run_git; uv and pnpm run with argument
lists, without a shell, in their own process group.
"""

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import time
import tomllib
from collections.abc import Awaitable, Callable, Mapping
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
AGENTD_DIR = "backend/claudio_maestro/agentd/"
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
RunTool = Callable[..., Awaitable[int]]  # (argv, cwd, timeout, on_line, env=None)
Which = Callable[[str], str | None]


STEP_LABELS = {
    "check": "Verificando", "fetch": "Baixando", "python": "Dependências do Python",
    "frontend-deps": "Dependências do frontend", "build": "Compilando", "restart": "Reiniciando",
}


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


async def run_tool(
    argv: list[str],
    cwd: Path,
    timeout: float,
    on_line: Callable[[str], None],
    env: Mapping[str, str] | None = None,
) -> int:
    """Run `argv` in `cwd` (with `env`, or the app's own environment), without a shell, stdout and
    stderr merged, line by line.

    Raises TimeoutError after `timeout` seconds, killing the whole process group."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=None if env is None else dict(env), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
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


def take_update_result(data_dir: Path) -> dict[str, Any] | None:
    """The result an update left for the new process; read once, then deleted."""
    path = data_dir / RESULT_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        raw = ""
    with contextlib.suppress(OSError):
        path.unlink()
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return {
            "from": str(data.get("from", "")), "to": str(data.get("to", "")),
            "agentd_changed": bool(data.get("agentd_changed")), "at": float(data.get("at", 0)),
        }
    except (TypeError, ValueError):
        return None


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
        self._log: Any = None

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

    async def apply(self, version: str) -> None:
        if self.busy:
            raise UpdateBusy("já há uma atualização em andamento")
        if parse_version(version) is None or version.startswith("v"):
            raise UpdateNotAllowed("versão inválida")
        self._starting = True
        try:
            eligibility = await self.check()
            if not eligibility.ok:
                raise UpdateNotAllowed(eligibility.reason or "atualização indisponível")
            self._job = {
                "state": "running", "step": "check", "failed_step": None, "rolling_back": False,
                "lines": [], "error": None, "log_path": str(self.log_path),
            }
            self._emit()
            self._task = asyncio.create_task(self._run(version, eligibility))
        finally:
            self._starting = False

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    # -- job state ---------------------------------------------------------------

    def _emit(self) -> None:
        self._publish({"session_id": None, "seq": 0, "type": "app.update.progress", "data": self.job_state()})

    def _step(self, step: str) -> None:
        assert self._job is not None
        self._job["step"] = step
        self._line(f"== {STEP_LABELS[step]}")

    def _line(self, text: str) -> None:
        assert self._job is not None
        if self._log is not None:
            with contextlib.suppress(OSError, ValueError):
                self._log.write(text + "\n")
                self._log.flush()
        self._job["lines"] = [*self._job["lines"], text][-TAIL:]
        self._emit()

    def _finish(self, state: str, error: str | None) -> None:
        assert self._job is not None
        self._job["state"] = state
        self._job["error"] = error
        if state in ("failed", "rolled-back-failed") and self._job["failed_step"] is None:
            self._job["failed_step"] = self._job["step"]
        if error:
            self._line(error)
        else:
            self._emit()

    # -- the update itself -------------------------------------------------------

    async def _run(self, version: str, eligibility: Eligibility) -> None:
        self._log = None
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "w", encoding="utf-8") as log:
                self._log = log
                try:
                    await self._update(version, eligibility)
                except Exception as exc:  # noqa: BLE001 - anything unexpected still ends the job
                    self._finish("failed", f"erro inesperado: {exc}")
        except Exception as exc:  # noqa: BLE001 - the log could not even be opened or closed
            self._log = None
            self._finish("failed", f"erro inesperado: {exc}")
        finally:
            self._log = None

    async def _update(self, version: str, eligibility: Eligibility) -> None:
        assert eligibility.mode is not None and eligibility.remote is not None
        from_version = self._current()
        try:
            old = await self._rev()
            self._step("fetch")
            await self._move(eligibility.mode, eligibility.remote, version)
            moved = await self._rev() != old
        except StepFailed as exc:
            self._finish("failed", str(exc))
            return
        if not moved:
            self._finish("up-to-date", None)
            return
        try:
            await self._tools()
            code, _, _ = await self._git("diff", "--quiet", "--end-of-options", old, "HEAD", "--", AGENTD_DIR)
            result = {"from": from_version, "to": self._repo_version(), "agentd_changed": code == 1, "at": time.time()}
            try:
                (self.data_dir / RESULT_FILE).write_text(json.dumps(result), encoding="utf-8")
            except OSError as exc:
                raise StepFailed(f"não foi possível gravar o resultado da atualização: {exc}") from exc
            self._step("restart")
            self._finish("restarting", None)
            assert self._restart is not None
            self._restart()
        except StepFailed as exc:
            await self._rollback(eligibility.mode, old, str(exc))
        except Exception as exc:  # noqa: BLE001 - the clone already moved, so any failure must undo it
            await self._rollback(eligibility.mode, old, f"erro inesperado: {exc}")

    async def _move(self, mode: Mode, remote: str, version: str) -> None:
        if mode == "pull":
            await self._git_step("fetch", "--no-tags", "--end-of-options", remote, "main", timeout=NETWORK_TIMEOUT)
            code, _, _ = await self._git_or_fail("merge-base", "--is-ancestor", "--end-of-options", "HEAD", "FETCH_HEAD")
            if code == 1:
                raise StepFailed("há commits locais na main que não estão no GitHub")
            await self._git_step("merge", "--ff-only", "--end-of-options", "FETCH_HEAD")
            return
        tag = f"v{version}"
        await self._git_step(
            "fetch", "--no-tags", "--end-of-options", remote, f"refs/tags/{tag}:refs/tags/{tag}", timeout=NETWORK_TIMEOUT
        )
        await self._verify_tag(tag, version)
        await self._git_step("checkout", "--detach", "--end-of-options", tag)

    async def _verify_tag(self, tag: str, version: str) -> None:
        code, out, _ = await self._git_or_fail("show", "--end-of-options", f"{tag}:pyproject.toml")
        if code != 0:
            raise StepFailed(f"a tag {tag} não tem pyproject.toml")
        try:
            found = tomllib.loads(out)["project"]["version"]
        except (tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
            raise StepFailed(f"não foi possível ler a versão da tag {tag}") from exc
        if found != version:
            raise StepFailed(f"a tag {tag} traz a versão {found}, não {version}")
        code, _, _ = await self._git_or_fail("merge-base", "--is-ancestor", "--end-of-options", "HEAD", tag)
        if code != 0:
            raise StepFailed(f"a tag {tag} não continua o commit atual do clone")

    async def _tools(self) -> None:
        frontend = str(self.repo / "frontend")
        # CI=1: with no terminal, pnpm aborts when it wants to confirm recreating node_modules.
        env = {**os.environ, "CI": "1"}
        steps = (
            ("python", "uv", ["sync", "--frozen"]),
            ("frontend-deps", "pnpm", ["--dir", frontend, "install", "--frozen-lockfile"]),
            ("build", "pnpm", ["--dir", frontend, "build"]),
        )
        for step, tool, args in steps:
            self._step(step)
            program = self._which(tool)
            if program is None:
                raise StepFailed(f"{tool} não encontrado no PATH do app")
            argv = [program, *args]
            shown = " ".join([tool, *(a for a in args if a not in ("--dir", frontend))])
            try:
                code = await self._run_tool(argv, self.repo, TOOL_TIMEOUT, self._line, env=env)
            except TimeoutError as exc:
                raise StepFailed(f"`{shown}` passou de {int(TOOL_TIMEOUT)} s") from exc
            except ValueError as exc:  # a single output line over LINE_LIMIT
                raise StepFailed(f"`{shown}` escreveu uma linha longa demais na saída") from exc
            except OSError as exc:
                raise StepFailed(f"não foi possível rodar `{shown}`: {exc}") from exc
            if code != 0:
                raise StepFailed(f"`{shown}` falhou (código {code})")

    async def _rollback(self, mode: Mode, old: str, reason: str) -> None:
        assert self._job is not None
        # The rollback runs the tools again and moves `step`: remember which one broke.
        self._job["failed_step"] = self._job["step"]
        self._job["rolling_back"] = True
        self._line(f"Desfazendo: {reason}")
        with contextlib.suppress(OSError):
            (self.data_dir / RESULT_FILE).unlink(missing_ok=True)
        try:
            if mode == "pull":
                await self._git_step("reset", "--keep", "--end-of-options", old)
            else:
                await self._git_step("checkout", "--detach", "--end-of-options", old)
            await self._tools()
        except StepFailed as exc:
            self._finish("rolled-back-failed", f"{reason}. Não foi possível desfazer: {exc}")
            return
        self._finish("failed", reason)

    async def _git_or_fail(self, *args: str, timeout: float = LOCAL_GIT_TIMEOUT) -> tuple[int, str, str]:
        try:
            return await self._git(*args, timeout=timeout)
        except GitError as exc:
            raise StepFailed(f"git {args[0]} falhou: {exc}") from exc

    async def _git_step(self, *args: str, timeout: float = LOCAL_GIT_TIMEOUT) -> None:
        code, out, err = await self._git_or_fail(*args, timeout=timeout)
        for line in (out + err).splitlines():
            self._line(line)
        if code != 0:
            raise StepFailed(f"git {args[0]} falhou: {err.strip()[:300]}")

    async def _rev(self) -> str:
        code, out, _ = await self._git_or_fail("rev-parse", "HEAD")
        return out.strip() if code == 0 else ""

    def _repo_version(self) -> str:
        try:
            with open(self.repo / "pyproject.toml", "rb") as file:
                return str(tomllib.load(file)["project"]["version"])
        except (OSError, tomllib.TOMLDecodeError, KeyError):
            return "?"
