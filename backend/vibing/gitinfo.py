"""Read-only git queries: branch, change counts and file diffs.

Every command runs as `git -C <repo> ...` with list arguments (no shell),
`GIT_OPTIONAL_LOCKS=0` so it never competes with the user's own git, and a
time limit. A failure becomes an `error` on that repository only.
"""

import asyncio
import contextvars
import os
import time
import weakref
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vibing.history import REPO_MAX_COUNT, scan_repositories

GIT_BINARY = "git"
GIT_TIMEOUT = 5.0
DIFF_LIMIT = 200_000
# Bytes read: enough for DIFF_LIMIT characters of up to 4 bytes each.
DIFF_READ_LIMIT = DIFF_LIMIT * 4
MAX_DIFF_FILE = 5 * 1024 * 1024
MAX_GIT_PROCESSES = 16
BIG_FILE_NOTICE = "Arquivo maior que 5 MB; o diff não é mostrado."
# Submodules run their own git with their own config (filters included), and
# `submodule.<n>.ignore` overrides the config key, so only the command line works.
STATUS_SUBMODULES = "--ignore-submodules=dirty"
DIFF_SUBMODULES = "--ignore-submodules=all"

# One semaphore per event loop (a semaphore is bound to the loop that uses it).
_process_slots: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slots = _process_slots.get(loop)
    if slots is None:
        slots = _process_slots[loop] = asyncio.Semaphore(MAX_GIT_PROCESSES)
    return slots


class GitError(Exception):
    """A git command failed; the message is shown to the user."""


class FileGoneError(GitError):
    """The file disappeared while its diff was being read."""


FILE_GONE_MESSAGE = "O arquivo não existe mais."


class _Budget:
    """Time left to a high-level operation. Only time spent running git counts:
    waiting for a process slot does not."""

    def __init__(self, seconds: float) -> None:
        self.total = seconds
        self.left = seconds


_budget: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar(
    "git_budget", default=None
)


@dataclass
class RepoStatus:
    path: str
    rel_path: str
    branch: str | None = None
    detached: bool = False
    head: str | None = None
    changed: dict[str, int] = field(
        default_factory=lambda: {"staged": 0, "unstaged": 0, "untracked": 0}
    )
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileDiff:
    diff: str
    truncated: bool
    notice: str | None = None


# Repository config must never make us run a program (fsmonitor, pager, hooks,
# external diff, filters): `/api/fs/dirs` reads any repository under the home
# folder. Passed through GIT_CONFIG_KEY_n/VALUE_n, which take the whole key as
# is (`-c` would split a key containing `=`).
SAFE_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.fsmonitor", "false"),
    ("core.pager", "cat"),
    ("core.hooksPath", "/dev/null"),
    ("diff.external", ""),
    ("core.untrackedCache", "false"),
    ("filter.lfs.process", ""),
    ("filter.lfs.clean", ""),
    ("filter.lfs.smudge", ""),
    ("filter.lfs.required", "false"),
)

INVALID_FILTER_NAME = "Repositório com filtro de nome inválido"


def _filter_names(output: str) -> set[str]:
    """Filter names from `git config -z --name-only` output (NUL-separated keys)."""
    names = set()
    for key in output.split("\0"):
        if key[:7].lower() == "filter." and key.count(".") >= 2:
            names.add(key[len("filter."):].rsplit(".", 1)[0])
    return names


def _has_control(text: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in text)


async def _disabled_filters(repo: Path, timeout: float) -> list[tuple[str, str]]:
    """Config entries that blank every filter the repository defines.

    Filters (`filter.<name>.clean/smudge/process`, picked by `.gitattributes`)
    are commands, and git runs them on status and diff. Listed on every command,
    so there is no window between reading and running.
    """
    code, out, _ = await _exec(
        repo, ("config", "-z", "--name-only", "--get-regexp", r"^filter\."), timeout
    )
    entries: list[tuple[str, str]] = []
    for name in sorted(_filter_names(out) if code == 0 else set()):
        if _has_control(name):
            raise GitError(INVALID_FILTER_NAME)
        for part in ("clean", "smudge", "process"):
            entries.append((f"filter.{name}.{part}", ""))
        entries.append((f"filter.{name}.required", "false"))
    return entries


def _env(extra_config: list[tuple[str, str]] | None = None) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env.update(
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_PAGER="cat",
        # File names are paths, never patterns like `*` or `:(top)`.
        GIT_LITERAL_PATHSPECS="1",
    )
    config = [*SAFE_CONFIG, *(extra_config or [])]
    env["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


async def run_git(
    repo: Path, *args: str, timeout: float = GIT_TIMEOUT, limit: int | None = None
) -> tuple[int, str, str]:
    """Run git in `repo` with every configured program disabled.

    Raises GitError when it cannot start, times out, or the repository defines
    a filter whose name cannot be neutralised.
    """
    filters = await _disabled_filters(repo, timeout)
    return await _exec(repo, args, timeout, filters, limit)


async def _within(timeout: float, operation):
    """Runs a whole high-level operation under one time limit, counting only the
    time its git processes run (not the wait for a free process slot)."""
    token = _budget.set(_Budget(timeout))
    try:
        return await operation
    finally:
        _budget.reset(token)


async def _exec(
    repo: Path,
    args: tuple[str, ...],
    timeout: float,
    extra_config: list[tuple[str, str]] | None = None,
    limit: int | None = None,
) -> tuple[int, str, str]:
    async with _slots():
        budget = _budget.get()
        if budget is None:
            return await _exec_now(repo, args, timeout, extra_config, limit)
        if budget.left <= 0:
            raise GitError(f"O git passou do tempo limite de {budget.total:g} s.")
        started = time.monotonic()
        try:
            return await _exec_now(repo, args, min(timeout, budget.left), extra_config, limit)
        except GitError as exc:
            if budget.left - (time.monotonic() - started) <= 0:
                raise GitError(f"O git passou do tempo limite de {budget.total:g} s.") from exc
            raise
        finally:
            budget.left -= time.monotonic() - started


async def _read_limited(stream: asyncio.StreamReader, limit: int | None) -> bytes:
    """Reads up to `limit + 1` bytes and drains the rest without keeping it."""
    if limit is None:
        return await stream.read()
    data = bytearray()
    while chunk := await stream.read(65536):
        if len(data) <= limit:
            data += chunk[: limit + 1 - len(data)]
    return bytes(data)


async def _exec_now(
    repo: Path,
    args: tuple[str, ...],
    timeout: float,
    extra_config: list[tuple[str, str]] | None,
    limit: int | None,
) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            GIT_BINARY, "-C", str(repo), *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_env(extra_config),
        )
    except OSError as exc:
        raise GitError(f"Não foi possível executar o git: {exc}") from exc
    try:
        if limit is None:
            out, err = await asyncio.wait_for(process.communicate(), timeout)
        else:
            assert process.stdout is not None and process.stderr is not None
            out, err, _ = await asyncio.wait_for(
                asyncio.gather(
                    _read_limited(process.stdout, limit),
                    _read_limited(process.stderr, 65536),
                    process.wait(),
                ),
                timeout,
            )
    except (TimeoutError, asyncio.CancelledError) as exc:
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(Exception):
            await asyncio.shield(process.wait())
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise GitError(f"O git passou do tempo limite de {timeout:g} s.") from exc
    return (
        process.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


def _failure(stderr: str) -> str:
    text = stderr.strip().splitlines()
    return text[-1] if text else "Falha ao ler o repositório."


def _parse_status(repo: RepoStatus, output: str) -> None:
    changed = repo.changed
    for line in output.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.removeprefix("# branch.oid ")
            repo.head = None if oid == "(initial)" else oid[:7]
        elif line.startswith("# branch.head "):
            head = line.removeprefix("# branch.head ")
            if head == "(detached)":
                repo.detached = True
            else:
                repo.branch = head
        elif line.startswith(("1 ", "2 ")):
            xy = line[2:4]
            if xy[0] != ".":
                changed["staged"] += 1
            if xy[1] != ".":
                changed["unstaged"] += 1
        elif line.startswith("u "):
            changed["unstaged"] += 1
        elif line.startswith("? "):
            changed["untracked"] += 1


async def repo_status(
    repo: Path, root: Path | None = None, *, timeout: float = GIT_TIMEOUT
) -> RepoStatus:
    """Branch and change counts. `rel_path` is relative to `root` ("." for itself)."""
    root = root or repo
    rel = repo.relative_to(root).as_posix() if repo != root else "."
    status = RepoStatus(path=str(repo), rel_path=rel)
    try:
        code, out, err = await _within(timeout, run_git(
            repo, "status", STATUS_SUBMODULES, "--porcelain=v2", "--branch", timeout=timeout
        ))
    except GitError as exc:
        status.error = str(exc)
        return status
    if code != 0:
        status.error = _failure(err)
        return status
    _parse_status(status, out)
    return status


def discover_scan(root: Path) -> tuple[list[Path], bool]:
    """Like `discover`, plus whether the scan stopped at the repository limit.

    Only the limit counts: an unreadable folder does not. One more repository
    than the limit is looked for, so exactly the limit is not "reached".
    """
    found = scan_repositories(root, max_count=REPO_MAX_COUNT + 1)[0]
    limit_reached = len(found) > REPO_MAX_COUNT
    found = found[:REPO_MAX_COUNT]
    if (root / ".git").exists():
        found.insert(0, root)
    return found, limit_reached


def discover(root: Path) -> list[Path]:
    """The project folder itself (if it has `.git`) and repositories below it."""
    return discover_scan(root)[0]


async def project_repos_scan(
    root: Path, *, timeout: float = GIT_TIMEOUT
) -> tuple[list[RepoStatus], bool]:
    """Status of every repository of a folder, and whether the limit was reached."""
    paths, limit_reached = await asyncio.to_thread(discover_scan, root)
    repos = await asyncio.gather(*(repo_status(path, root, timeout=timeout) for path in paths))
    return list(repos), limit_reached


async def project_repos(root: Path, *, timeout: float = GIT_TIMEOUT) -> list[RepoStatus]:
    return (await project_repos_scan(root, timeout=timeout))[0]


async def branch_label(repo: Path, *, timeout: float = GIT_TIMEOUT) -> str | None:
    """Branch name, or the short hash with a detached HEAD; None on failure."""
    status = await repo_status(repo, timeout=timeout)
    if status.error:
        return None
    return status.head if status.detached else status.branch


async def dirty_files(repo: Path, *, timeout: float = GIT_TIMEOUT) -> set[str]:
    """Paths (relative to the repo) with any uncommitted change, untracked included."""
    code, out, err = await _within(timeout, run_git(
        repo, "-c", "core.quotepath=off", "status", STATUS_SUBMODULES, "--porcelain=v2",
        "-z", "--untracked-files=all", timeout=timeout,
    ))
    if code != 0:
        raise GitError(_failure(err))
    result: set[str] = set()
    fields = out.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if entry.startswith("1 "):
            result.add(entry.split(" ", 8)[8])
        elif entry.startswith("2 "):
            result.add(entry.split(" ", 9)[9])
            index += 1  # original path follows
        elif entry.startswith("u "):
            result.add(entry.split(" ", 10)[10])
        elif entry.startswith("? "):
            result.add(entry[2:])
    return result


async def file_diff(repo: Path, file: str, *, timeout: float = GIT_TIMEOUT) -> FileDiff:
    return await _within(timeout, _file_diff(repo, file, timeout))


async def _file_diff(repo: Path, file: str, timeout: float) -> FileDiff:
    """Current diff of `file` (relative to `repo`) against HEAD.

    Untracked files, and files in a repository without commits, are compared
    with an empty file.
    """
    common = ("--no-color", "--no-ext-diff", "--no-textconv", DIFF_SUBMODULES)
    code, _, _ = await run_git(repo, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout)
    has_head = code == 0
    tracked = False
    if has_head:
        code, _, _ = await run_git(
            repo, "ls-files", "--error-unmatch", "--", file, timeout=timeout
        )
        tracked = code == 0
        if not tracked:
            code, out, _ = await run_git(
                repo, "ls-tree", "--name-only", "HEAD", "--", file, timeout=timeout
            )
            tracked = bool(out.strip())
    if tracked:
        code, out, err = await run_git(
            repo, "diff", *common, "HEAD", "--", file, timeout=timeout, limit=DIFF_READ_LIMIT
        )
        if code != 0:
            raise GitError(_failure(err))
    elif (repo / file).is_file():
        try:
            size = (repo / file).stat().st_size
        except FileNotFoundError as exc:
            raise FileGoneError(FILE_GONE_MESSAGE) from exc
        if size > MAX_DIFF_FILE:
            return FileDiff("", True, BIG_FILE_NOTICE)
        code, out, err = await run_git(
            repo, "diff", *common, "--no-index", "--", "/dev/null", file,
            timeout=timeout, limit=DIFF_READ_LIMIT,
        )
        # Gone meanwhile: git answers 1 ("Could not access"), like a real diff.
        if not (repo / file).exists():
            raise FileGoneError(FILE_GONE_MESSAGE)
        if code not in (0, 1):
            raise GitError(_failure(err))
    else:
        out = ""
    if len(out) > DIFF_LIMIT:
        return FileDiff(out[:DIFF_LIMIT], True)
    return FileDiff(out, False)
