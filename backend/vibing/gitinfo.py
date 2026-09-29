"""Read-only git queries: branch, change counts and file diffs.

Every command runs as `git -C <repo> ...` with list arguments (no shell),
`GIT_OPTIONAL_LOCKS=0` so it never competes with the user's own git, and a
time limit. A failure becomes an `error` on that repository only.
"""

import asyncio
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vibing.history import scan_repositories

GIT_BINARY = "git"
GIT_TIMEOUT = 5.0
DIFF_LIMIT = 200_000


class GitError(Exception):
    """A git command failed; the message is shown to the user."""


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
        if not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        and key not in ("GIT_EXTERNAL_DIFF", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT")
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
    repo: Path, *args: str, timeout: float = GIT_TIMEOUT
) -> tuple[int, str, str]:
    """Run git in `repo` with every configured program disabled.

    Raises GitError when it cannot start, times out, or the repository defines
    a filter whose name cannot be neutralised.
    """
    filters = await _disabled_filters(repo, timeout)
    return await _exec(repo, args, timeout, filters)


async def _exec(
    repo: Path,
    args: tuple[str, ...],
    timeout: float,
    extra_config: list[tuple[str, str]] | None = None,
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
        out, err = await asyncio.wait_for(process.communicate(), timeout)
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
        code, out, err = await run_git(
            repo, "status", "--porcelain=v2", "--branch", timeout=timeout
        )
    except GitError as exc:
        status.error = str(exc)
        return status
    if code != 0:
        status.error = _failure(err)
        return status
    _parse_status(status, out)
    return status


def discover(root: Path) -> list[Path]:
    """The project folder itself (if it has `.git`) and repositories below it."""
    found = scan_repositories(root)[0]
    if (root / ".git").exists():
        found.insert(0, root)
    return found


async def project_repos(root: Path, *, timeout: float = GIT_TIMEOUT) -> list[RepoStatus]:
    repos = await asyncio.to_thread(discover, root)
    return list(
        await asyncio.gather(*(repo_status(repo, root, timeout=timeout) for repo in repos))
    )


async def branch_label(repo: Path, *, timeout: float = GIT_TIMEOUT) -> str | None:
    """Branch name, or the short hash with a detached HEAD; None on failure."""
    status = await repo_status(repo, timeout=timeout)
    if status.error:
        return None
    return status.head if status.detached else status.branch


async def dirty_files(repo: Path, *, timeout: float = GIT_TIMEOUT) -> set[str]:
    """Paths (relative to the repo) with any uncommitted change, untracked included."""
    code, out, err = await run_git(
        repo, "-c", "core.quotepath=off", "status", "--porcelain=v2", "-z",
        "--untracked-files=all", timeout=timeout,
    )
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
    """Current diff of `file` (relative to `repo`) against HEAD.

    Untracked files, and files in a repository without commits, are compared
    with an empty file.
    """
    common = ("--no-color", "--no-ext-diff", "--no-textconv")
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
        code, out, err = await run_git(repo, "diff", *common, "HEAD", "--", file, timeout=timeout)
        if code != 0:
            raise GitError(_failure(err))
    elif (repo / file).is_file():
        code, out, err = await run_git(
            repo, "diff", *common, "--no-index", "--", "/dev/null", file, timeout=timeout
        )
        if code not in (0, 1):
            raise GitError(_failure(err))
    else:
        out = ""
    if len(out) > DIFF_LIMIT:
        return FileDiff(out[:DIFF_LIMIT], True)
    return FileDiff(out, False)
