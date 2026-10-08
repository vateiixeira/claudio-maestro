"""Which `claude` CLI the app starts, and the button that updates it.

The SDK bundles a CLI pinned by `uv.lock`. The one installed on the machine updates
itself and learns new models first, so the app starts it when it is at least as new
as the bundled one. `MAESTRO_CLAUDE_CLI=bundled` forces the bundled one.

Every process here runs with an argument list, no shell and stdin closed.
"""

import asyncio
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

ENV_VAR = "MAESTRO_CLAUDE_CLI"
CACHE_SECONDS = 600
VERSION_TIMEOUT = 5.0
UPDATE_TIMEOUT = 180.0
OUTPUT_LINES = 40
OUTPUT_CHARS = 4096
TIMEOUT_TEXT = "O comando passou do tempo limite."
BUSY_TEXT = "Já há uma atualização do Claude em andamento."
MISSING_TEXT = "Não há Claude instalado no sistema para atualizar."
FORCED_TEXT = "O app está usando o Claude embutido (MAESTRO_CLAUDE_CLI)."

_VERSION = re.compile(r"\s*(\d+)\.(\d+)\.(\d+)(?!\.)\b")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")

Source = Literal["system", "bundled"]
Which = Callable[[str], str | None]
RunVersion = Callable[[str], str | None]


@dataclass(frozen=True)
class ClaudeCli:
    source: Source
    path: str | None  # None: the SDK finds its bundled CLI
    version: str
    system_path: str | None  # only when `--version` answered
    system_version: str | None
    bundled_version: str
    forced_bundled: bool

    def as_dict(self) -> dict[str, Any]:
        system = None
        if self.system_path is not None and self.system_version is not None:
            system = {"path": self.system_path, "version": self.system_version}
        return {
            "in_use": {"source": self.source, "version": self.version},
            "system": system,
            "bundled": {"version": self.bundled_version},
            "forced_bundled": self.forced_bundled,
            "can_update": system is not None and not self.forced_bundled,
        }


@dataclass(frozen=True)
class CommandResult:
    returncode: int | None  # None: timed out or could not start
    output: str


RunUpdate = Callable[[list[str], float], Awaitable[CommandResult]]


class ClaudeCliBusy(Exception):
    """Another `claude update` is running."""


class ClaudeCliUnavailable(Exception):
    """There is no system `claude` to update, or the bundled one is forced."""


@dataclass(frozen=True)
class UpdateOutcome:
    ok: bool
    before: str
    after: str | None
    cli: ClaudeCli
    models_refreshed: bool
    output: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "before": self.before,
            "after": self.after,
            "in_use": {"source": self.cli.source, "version": self.cli.version},
            "models_refreshed": self.models_refreshed,
            "output": self.output,
            "message": self.message,
        }


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """The leading `X.Y.Z` of `claude --version` (e.g. `2.1.292 (Claude Code)`)."""
    if not text:
        return None
    match = _VERSION.match(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _text(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def clean_output(text: str) -> str:
    """The last lines of a command's output, as a terminal would show them."""
    lines = []
    for raw in _ANSI.sub("", text).split("\n"):
        # A progress bar redraws with \r: keep the last non-empty drawing.
        parts = [part.rstrip() for part in raw.split("\r") if part.strip()]
        if parts:
            lines.append(parts[-1])
    return "\n".join(lines[-OUTPUT_LINES:])[-OUTPUT_CHARS:]


def bundled_cli_version() -> str:
    from claude_agent_sdk._cli_version import __cli_version__

    return __cli_version__


def run_version_command(path: str) -> str | None:
    """Stdout of `claude --version`, or None on failure, timeout or non-zero exit."""
    try:
        done = subprocess.run(
            [path, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return done.stdout if done.returncode == 0 else None


async def run_update_command(argv: list[str], timeout: float) -> CommandResult:
    """Run `claude update` in its own process group; kill the group on timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        return CommandResult(None, str(error))
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        with suppress(Exception):
            await proc.wait()
        return CommandResult(None, TIMEOUT_TEXT)
    return CommandResult(proc.returncode, out.decode("utf-8", "replace"))


def resolve(
    *, env: Mapping[str, str], which: Which, run_version: RunVersion, bundled_version: str
) -> ClaudeCli:
    """Pick the CLI: the system one when it is at least as new as the bundled one."""
    forced = env.get(ENV_VAR, "").strip().lower() == "bundled"
    system_path = which("claude")
    system_version: str | None = None
    if system_path is not None:
        parsed = parse_version(run_version(system_path))
        if parsed is None:
            system_path = None
        else:
            system_version = _text(parsed)
    bundled = parse_version(bundled_version)
    system = parse_version(system_version)
    use_system = not forced and system is not None and (bundled is None or system >= bundled)
    return ClaudeCli(
        source="system" if use_system else "bundled",
        path=system_path if use_system else None,
        version=system_version if use_system and system_version else bundled_version,
        system_path=system_path,
        system_version=system_version,
        bundled_version=bundled_version,
        forced_bundled=forced,
    )


def _message(ok: bool, before: str, after: str | None, models: bool, output: str) -> str:
    if not ok:
        last = output.splitlines()[-1] if output else ""
        return f"Não foi possível atualizar o Claude. {last}".rstrip()
    if after is None:
        return "O Claude foi atualizado, mas não respondeu com a versão."
    if after == before:
        return f"O Claude já está na versão mais nova ({after})."
    models_text = (
        "A lista de modelos foi renovada."
        if models
        else "Não foi possível renovar a lista de modelos agora."
    )
    return f"Claude atualizado de {before} para {after}. {models_text}"


class ClaudeCliResolver:
    """Keeps the CLI choice for `CACHE_SECONDS` and runs `claude update`, one at a time.

    `current()` and `cli_path()` never do I/O: they return the last choice (the
    bundled CLI until the first `refresh`). Tests inject `which`, `run_version`
    and `run_update`; the defaults are looked up at call time so the autouse
    fixture of the tests can replace them.
    """

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        which: Which | None = None,
        run_version: RunVersion | None = None,
        run_update: RunUpdate | None = None,
        bundled_version: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        cache_seconds: float = CACHE_SECONDS,
    ) -> None:
        self._env = env
        self._which = which
        self._run_version = run_version
        self._run_update = run_update
        self._bundled = bundled_version if bundled_version is not None else bundled_cli_version()
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._current = self._fallback()
        self._resolved_at: float | None = None
        self._updating = False
        self._last: UpdateOutcome | None = None

    def _environ(self) -> Mapping[str, str]:
        return os.environ if self._env is None else self._env

    def _fallback(self) -> ClaudeCli:
        return ClaudeCli(
            source="bundled",
            path=None,
            version=self._bundled,
            system_path=None,
            system_version=None,
            bundled_version=self._bundled,
            forced_bundled=self._environ().get(ENV_VAR, "").strip().lower() == "bundled",
        )

    def current(self) -> ClaudeCli:
        return self._current

    def cli_path(self) -> str | None:
        return self._current.path

    async def refresh(self, force: bool = False) -> ClaudeCli:
        fresh = (
            self._resolved_at is not None
            and self._clock() - self._resolved_at < self._cache_seconds
        )
        if fresh and not force:
            return self._current
        try:
            cli = await asyncio.to_thread(
                resolve,
                env=self._environ(),
                which=self._which or shutil.which,
                run_version=self._run_version or run_version_command,
                bundled_version=self._bundled,
            )
        except Exception:
            logger.exception("Falha ao escolher o Claude; usando o embutido")
            cli = self._fallback()
        if cli != self._current:
            logger.info(
                "Claude em uso: %s %s (%s)", cli.source, cli.version, cli.path or "embutido no SDK"
            )
        self._current = cli
        self._resolved_at = self._clock()
        return cli

    async def run_periodic(
        self, interval: float, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep
    ) -> None:
        """Rereads the choice every `interval` seconds (the startup already read it)."""
        while True:
            await sleep(interval)
            await self.refresh(force=True)

    def job_state(self) -> dict[str, Any] | None:
        if self._updating:
            return {"state": "running"}
        if self._last is None:
            return None
        return {"state": "done" if self._last.ok else "failed", **self._last.as_dict()}

    async def update(self, refresh_models: Callable[[], Awaitable[bool]]) -> UpdateOutcome:
        """Run `claude update`, reread the choice and refresh the models list.

        Raises ClaudeCliBusy while another update runs and ClaudeCliUnavailable when
        there is no system `claude` or the bundled one is forced.
        """
        if self._updating:
            raise ClaudeCliBusy(BUSY_TEXT)
        self._updating = True
        try:
            before = await self.refresh(force=True)
            if before.forced_bundled:
                raise ClaudeCliUnavailable(FORCED_TEXT)
            if before.system_path is None or before.system_version is None:
                raise ClaudeCliUnavailable(MISSING_TEXT)
            run = self._run_update or run_update_command
            result = await run([before.system_path, "update"], UPDATE_TIMEOUT)
            output = clean_output(result.output)
            after = await self.refresh(force=True)
            models = False
            try:
                models = bool(await refresh_models())
            except Exception:
                logger.exception("Falha ao renovar a lista de modelos depois de atualizar o Claude")
            ok = result.returncode == 0
            outcome = UpdateOutcome(
                ok=ok,
                before=before.system_version,
                after=after.system_version,
                cli=after,
                models_refreshed=models,
                output=output,
                message=_message(ok, before.system_version, after.system_version, models, output),
            )
            self._last = outcome
            return outcome
        finally:
            self._updating = False
