"""Read-only git queries: branch, change counts and file diffs.

Every command runs as `git -C <repo> ...` with list arguments (no shell),
`GIT_OPTIONAL_LOCKS=0` so it never competes with the user's own git, and a
time limit. A failure becomes an `error` on that repository only.
"""

import asyncio
import contextvars
import logging
import os
import time
import weakref
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from vibing.history import REPO_MAX_COUNT, scan_repositories
from vibing.worktree import LinkedWorktree, linked_worktree, parse_worktree_list

logger = logging.getLogger(__name__)

GIT_BINARY = "git"
GIT_TIMEOUT = 5.0
DIFF_LIMIT = 200_000
# Bytes read: enough for DIFF_LIMIT characters of up to 4 bytes each.
DIFF_READ_LIMIT = DIFF_LIMIT * 4
MAX_DIFF_FILE = 5 * 1024 * 1024
MAX_GIT_PROCESSES = 16
MAX_FILES = 200
MAX_COMMITS = 10
# Bytes read from `status` / `diff --numstat` for the file list.
FILES_READ_LIMIT = 4 * 1024 * 1024
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
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
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


def _apply_header(repo: RepoStatus, line: str) -> None:
    """Fill branch, head, upstream and ahead/behind from a `# branch.*` header line."""
    if line.startswith("# branch.oid "):
        oid = line.removeprefix("# branch.oid ")
        repo.head = None if oid == "(initial)" else oid[:7]
    elif line.startswith("# branch.head "):
        head = line.removeprefix("# branch.head ")
        if head == "(detached)":
            repo.detached = True
        else:
            repo.branch = head
    elif line.startswith("# branch.upstream "):
        repo.upstream = line.removeprefix("# branch.upstream ")
    elif line.startswith("# branch.ab "):
        parts = line.removeprefix("# branch.ab ").split()
        try:
            repo.ahead = int(parts[0].removeprefix("+"))
            repo.behind = int(parts[1].removeprefix("-"))
        except (IndexError, ValueError):
            repo.ahead = repo.behind = None


def _parse_status(repo: RepoStatus, output: str) -> None:
    changed = repo.changed
    for line in output.splitlines():
        if line.startswith("# "):
            _apply_header(repo, line)
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


def _rel_path(repo: Path, root: Path) -> str:
    return repo.relative_to(root).as_posix() if repo != root else "."


async def repo_status(
    repo: Path, root: Path | None = None, *, timeout: float = GIT_TIMEOUT
) -> RepoStatus:
    """Branch and change counts. `rel_path` is relative to `root` ("." for itself)."""
    status = RepoStatus(path=str(repo), rel_path=_rel_path(repo, root or repo))
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


# main repo -> (mtime of its `.git/worktrees`, realpaths git listed for it). Only a
# positive hint: the pointers on disk are proven again on every request.
_listed_worktrees: dict[Path, tuple[int, frozenset[str]]] = {}


def _prove_worktree(path: Path, roots: list[Path]) -> tuple[LinkedWorktree, int] | None:
    """Pointer proof plus "its main repo is inside a project". Blocking: a few `stat`s."""
    found = linked_worktree(path)
    if found is None:
        return None
    for root in roots:
        try:
            inside = found.main_repo.is_relative_to(os.path.realpath(root))
            stamp = (found.main_repo / ".git" / "worktrees").stat().st_mtime_ns
        except (OSError, ValueError):
            continue
        if inside:
            return found, stamp
    return None


async def project_worktree(path: Path, roots: list[Path]) -> LinkedWorktree | None:
    """The linked worktree containing `path`, if it is safe to treat like project files.

    Needs all of: pointers that agree in both directions (`linked_worktree`), a main
    repository inside one of `roots`, and the worktree listed by that repository's own
    `git worktree list`. A link or a lookalike folder fails at least one of them.
    """
    proven = await asyncio.to_thread(_prove_worktree, path, roots)
    if proven is None:
        return None
    found, stamp = proven
    cached = _listed_worktrees.get(found.main_repo)
    if cached is not None and cached[0] == stamp and str(found.path) in cached[1]:
        return found
    try:
        code, out, _ = await run_git(found.main_repo, "worktree", "list", "--porcelain")
    except GitError:
        return None
    if code != 0:
        return None
    listed = frozenset(os.path.realpath(entry) for entry in parse_worktree_list(out))
    _listed_worktrees[found.main_repo] = (stamp, listed)
    return found if str(found.path) in listed else None


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


# Details: changed files and recent commits ---------------------------------------

_STATUS_ORDER = {"staged": 0, "unstaged": 1, "untracked": 2}


def _parse_files(
    output: str, summary: RepoStatus | None = None
) -> tuple[list[tuple[str, str]], bool]:
    """(path, status) pairs from `status --porcelain=v2 -z`, and whether the output
    was cut short (the last, possibly partial, entry is dropped then).

    Entries that end in `/` are dropped: a nested repository that is not ignored
    shows up as `sub/`, and it is not a file. With `summary` (for output that also
    has `--branch`), the branch fields and `changed` are filled from the same output.
    The counts are per listed file (an untracked folder counts each of its files,
    unlike `repo_status`, which counts the folder once) and cover only the part that
    was read when the output was cut short.
    """
    fields = output.split("\0")
    cut = len(output.encode("utf-8", "replace")) > FILES_READ_LIMIT
    if cut:
        fields = fields[:-1]
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if entry.startswith("# "):
            if summary is not None:
                _apply_header(summary, entry)
        elif entry.startswith(("1 ", "2 ")):
            renamed = entry.startswith("2 ")
            path = entry.split(" ", 9 if renamed else 8)[9 if renamed else 8]
            if renamed:
                index += 1  # the original path follows
            if entry[2] != ".":
                entries.append((path, "staged"))
            if entry[3] != ".":
                entries.append((path, "unstaged"))
        elif entry.startswith("u "):
            entries.append((entry.split(" ", 10)[10], "unstaged"))
        elif entry.startswith("? "):
            entries.append((entry[2:], "untracked"))
    entries = [entry for entry in entries if not entry[0].endswith("/")]
    if summary is not None:
        for _, status in entries:
            summary.changed[status] += 1
    return entries, cut


def _parse_numstat(output: str) -> dict[str, tuple[int | None, int | None]]:
    """Path -> (added, removed) from `diff --numstat -z`; binary files give None."""
    counts: dict[str, tuple[int | None, int | None]] = {}
    fields = output.split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if not path:  # rename: "added<TAB>removed<TAB>", then the old and the new path
            if index + 1 >= len(fields):
                break
            path = fields[index + 1]
            index += 2
        try:
            counts[path] = (int(added), int(removed))
        except ValueError:
            counts[path] = (None, None)
    return counts


async def repo_files(
    repo: Path, *, timeout: float = GIT_TIMEOUT
) -> tuple[list[dict[str, Any]], bool]:
    """Changed files of a repository and whether the list was cut at MAX_FILES.

    A file with staged and unstaged changes is listed twice. Untracked and
    binary files have no line counts.
    """
    return await _within(timeout, _repo_files(repo, timeout))


async def _repo_files(
    repo: Path, timeout: float, summary: RepoStatus | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """`repo_files`; with `summary`, the same status call also fills it (branch,
    upstream, ahead/behind and counts), so the details need no second status."""
    args = ["status", STATUS_SUBMODULES, "--porcelain=v2", "-z", "--untracked-files=all"]
    if summary is not None:
        args.append("--branch")
    code, out, err = await run_git(repo, *args, timeout=timeout, limit=FILES_READ_LIMIT)
    if code != 0:
        raise GitError(_failure(err))
    entries, truncated = _parse_files(out, summary)
    entries = sorted(set(entries), key=lambda e: (e[0], _STATUS_ORDER[e[1]]))
    if len(entries) > MAX_FILES:
        entries, truncated = entries[:MAX_FILES], True

    counts: dict[str, dict[str, tuple[int | None, int | None]]] = {}
    for status, extra in (("unstaged", ()), ("staged", ("--cached",))):
        if not any(entry_status == status for _, entry_status in entries):
            continue
        code, out, err = await run_git(
            repo, "diff", *extra, "--numstat", "-z", "--no-color", "--no-ext-diff",
            "--no-textconv", DIFF_SUBMODULES, timeout=timeout, limit=FILES_READ_LIMIT,
        )
        if code != 0:
            raise GitError(_failure(err))
        counts[status] = _parse_numstat(out)

    files = []
    for path, status in entries:
        added, removed = counts.get(status, {}).get(path, (None, None))
        files.append({"path": path, "status": status, "added": added, "removed": removed})
    return files, truncated


COMMIT_FORMAT = "%H%x1f%an%x1f%aI%x1f%s%x1e"


async def repo_commits(
    repo: Path, *, has_upstream: bool, timeout: float = GIT_TIMEOUT
) -> list[dict[str, Any]]:
    """The last MAX_COMMITS commits of HEAD; empty for a repository without commits.

    `pushed` is False for commits in `@{u}..HEAD`; None when there is no
    (resolvable) upstream.
    """
    return await _within(timeout, _repo_commits(repo, has_upstream, timeout))


async def _repo_commits(repo: Path, has_upstream: bool, timeout: float) -> list[dict[str, Any]]:
    code, _, _ = await run_git(repo, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout)
    if code != 0:
        return []
    code, out, err = await run_git(
        repo, "log", "-n", str(MAX_COMMITS), "--no-color", "--no-show-signature",
        f"--format={COMMIT_FORMAT}", "HEAD", "--", timeout=timeout,
    )
    if code != 0:
        raise GitError(_failure(err))
    unpushed: set[str] | None = None
    if has_upstream:
        code, listed, _ = await run_git(
            repo, "rev-list", "--max-count=1000", "@{u}..HEAD", "--", timeout=timeout
        )
        if code == 0:
            unpushed = set(listed.split())
    commits = []
    for record in out.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) != 4:
            continue
        full, author, date, subject = parts
        commits.append({
            "hash": full[:7], "full_hash": full, "subject": subject, "author": author,
            "date": date, "pushed": None if unpushed is None else full not in unpushed,
        })
    return commits


async def repo_details(
    repo: Path, root: Path | None = None, *, timeout: float = GIT_TIMEOUT
) -> dict[str, Any]:
    """Status of a repository plus its changed files and last commits.

    One `git status` gives both the summary and the files, so `changed` counts
    files (each untracked file, not each untracked folder as `repo_status` does).
    Any failure becomes `error` with empty lists; it never raises.
    """
    root = root or repo
    status = RepoStatus(path=str(repo), rel_path=str(repo))
    try:
        status.rel_path = _rel_path(repo, root)
        files, truncated = await _within(timeout, _repo_files(repo, timeout, status))
        commits = await repo_commits(
            repo, has_upstream=status.upstream is not None, timeout=timeout
        )
    except GitError as exc:
        return _detail(status, error=str(exc))
    except Exception:
        logger.exception("Falha inesperada ao ler os detalhes de %s", repo)
        fresh = RepoStatus(path=str(repo), rel_path=status.rel_path)
        return _detail(fresh, error="Falha ao ler o repositório.")
    return _detail(status, files=files, truncated=truncated, commits=commits)


def _detail(
    status: RepoStatus, *, error: str | None = None, files: list[dict[str, Any]] | None = None,
    truncated: bool = False, commits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        **status.to_dict(), "error": error, "files": files or [], "files_truncated": truncated,
        "commits": commits or [],
    }


async def project_details_scan(
    root: Path, *, timeout: float = GIT_TIMEOUT
) -> tuple[list[dict[str, Any]], bool]:
    """Details of every repository of a folder, and whether the limit was reached."""
    paths, limit_reached = await asyncio.to_thread(discover_scan, root)
    repos = await asyncio.gather(*(repo_details(path, root, timeout=timeout) for path in paths))
    return list(repos), limit_reached
