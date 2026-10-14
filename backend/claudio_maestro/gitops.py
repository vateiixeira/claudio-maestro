"""Git write actions of the project screen: stage, commit, branches, merge, pull and push.

Each action runs only when the user asks, always through `gitinfo.run_git`, so hooks,
filters, fsmonitor and external diff programs stay off; WRITE_CONFIG and WRITE_ENV also keep
the editor, signing and submodules out. One action per repository at a time (`repo_lock`).
Messages for the user are in Portuguese; git runs with LC_ALL=C, so its English output can
be recognised (`describe_failure`).
"""

import asyncio
import os
import re
import stat
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claudio_maestro import gitfetch, gitinfo
from claudio_maestro.security import PathNotAllowedError, resolve_within

LOCAL_TIMEOUT = 30.0
NETWORK_TIMEOUT = 120.0
TERM_GRACE = 2.0
MAX_PATHS = 1000
MAX_MESSAGE = 10_000
OUTPUT_LIMIT = 4096

# On top of SAFE_CONFIG. Signing and verifying run `gpg.program`, the editor is a program,
# and gc/maintenance would start background work in the user's repository.
WRITE_CONFIG: list[tuple[str, str]] = [
    ("commit.gpgSign", "false"),
    ("tag.gpgSign", "false"),
    ("merge.verifySignatures", "false"),
    ("log.showSignature", "false"),
    ("submodule.recurse", "false"),
    ("core.editor", ":"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
    ("rerere.enabled", "false"),
    ("merge.autoStash", "false"),
    ("commit.verbose", "false"),
]
WRITE_ENV: dict[str, str | None] = {
    "GIT_EDITOR": ":",
    "GIT_SEQUENCE_EDITOR": ":",
    "GIT_MERGE_AUTOEDIT": "no",
}

BUSY_MESSAGE = "Outra ação está em andamento neste repositório."
LOCKED_MESSAGE = "Outro processo git está usando este repositório."
IDENTITY_MESSAGE = "Configure user.name e user.email no git para commitar."
GENERIC_MESSAGE = "O git falhou."
EMPTY_MESSAGE = "Escreva a mensagem do commit."
NOTHING_TO_COMMIT = "Não há alterações para commitar."
MERGING_MESSAGE = "Há um merge em andamento neste repositório. Conclua ou aborte o merge antes."
PATH_MESSAGE = "O arquivo precisa estar dentro do repositório."
CONFLICT_MESSAGE = "Arquivo em conflito: resolva e use Marcar como resolvido."
NOT_CHANGED_MESSAGE = "O arquivo {path} não tem alterações para descartar."


class GitOpError(Exception):
    """An action that did not happen; `message` is for the user, `output` is git's."""

    code = "git"

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.output = output


class RepoBusyError(GitOpError):
    code = "busy"


class ReadOnlyError(GitOpError):
    code = "read_only"


class InvalidRequestError(GitOpError):
    code = "invalid"


class NotFoundError(GitOpError):
    code = "not_found"


# Failures -------------------------------------------------------------------------

_OVERWRITE = re.compile(
    r"(?:Your local changes to the following files|The following untracked working tree files)"
    r" would be overwritten by (checkout|merge)"
)
_SSH_HOST = re.compile(r"^(?:[\w.+-]+@)?([\w.-]+): Permission denied", re.MULTILINE)
_SSH_FAILURES = (
    # Not "Could not read from remote repository": git also says it for a missing local path.
    "Permission denied (publickey", "Host key verification failed", "ssh: Could not resolve hostname",
)


def describe_failure(stderr: str, *, target: str | None = None, upstream: str | None = None) -> str:
    """The user's message for a git failure (git runs with LC_ALL=C)."""
    if "index.lock" in stderr and "File exists" in stderr:
        return LOCKED_MESSAGE
    if any(text in stderr for text in (
        "Please tell me who you are", "Author identity unknown", "empty ident name",
        "no email was given", "no name was given",
    )):
        return IDENTITY_MESSAGE
    overwrite = _OVERWRITE.search(stderr)
    if overwrite:
        files = [line.strip() for line in stderr.splitlines() if line.startswith("\t")]
        shown = ", ".join(files[:3]) + (f" e mais {len(files) - 3}" if len(files) > 3 else "")
        verb = f"trocou para {target}" if overwrite.group(1) == "checkout" else f"mesclou {target}"
        return (
            f"O git não {verb}: suas alterações em {shown or 'alguns arquivos'} seriam "
            "sobrescritas. Commite, descarte ou leve para uma branch nova antes."
        )
    if "[rejected]" in stderr and ("non-fast-forward" in stderr or "fetch first" in stderr):
        return (
            f"O envio não foi feito: {upstream or 'o remoto'} recebeu commits que você ainda "
            "não tem. Sincronize para baixar e enviar."
        )
    if any(text in stderr for text in _SSH_FAILURES):
        host = _SSH_HOST.search(stderr)
        where = f"em {host.group(1)}" if host else "no servidor"
        return (
            f"O ssh não entrou {where} sem senha. O app não pede senha: carregue sua chave no "
            "ssh-agent e tente de novo."
        )
    return GENERIC_MESSAGE


def clean_output(text: str) -> str:
    """git's output for "Ver saída do git": no credentials, at most OUTPUT_LIMIT characters."""
    return gitinfo.strip_credentials(text).strip()[-OUTPUT_LIMIT:]


# Lock -------------------------------------------------------------------------------

_busy: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, set[str]]" = weakref.WeakKeyDictionary()


@asynccontextmanager
async def repo_lock(repo: Path) -> AsyncIterator[None]:
    """One action per repository (by realpath); a second one fails at once."""
    busy = _busy.setdefault(asyncio.get_running_loop(), set())
    key = os.path.realpath(repo)
    if key in busy:
        raise RepoBusyError(BUSY_MESSAGE)
    busy.add(key)
    try:
        yield
    finally:
        busy.discard(key)


# Paths ------------------------------------------------------------------------------


def repo_relpath(repo: Path, raw: str) -> str:
    """`raw`, relative to the repository, checked and normalised.

    The folders are resolved (a folder that links outside is refused) but the last part is
    not, so a symlink tracked in the repository names the link itself.
    """
    if not raw or os.path.isabs(raw) or gitinfo._has_control(raw):
        raise InvalidRequestError(PATH_MESSAGE)
    normal = os.path.normpath(raw)
    parts = Path(normal).parts
    if normal in ("", ".") or parts[0] == ".." or any(part.lower() == ".git" for part in parts):
        raise InvalidRequestError(PATH_MESSAGE)
    root = Path(os.path.realpath(repo))
    try:
        resolve_within((root / normal).parent, [root])
    except PathNotAllowedError as exc:
        raise InvalidRequestError(PATH_MESSAGE) from exc
    return Path(normal).as_posix()


# Running git ------------------------------------------------------------------------


async def _git(
    repo: Path, *args: str, timeout: float = LOCAL_TIMEOUT, input: bytes | None = None,
    config: list[tuple[str, str]] | None = None, env: dict[str, str | None] | None = None,
) -> tuple[int, str, str]:
    try:
        return await gitinfo.run_git(
            repo, *args, timeout=timeout, input=input,
            config=[*WRITE_CONFIG, *(config or [])], env={**WRITE_ENV, **(env or {})},
            own_group=True, grace=TERM_GRACE,
        )
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def _checked(
    repo: Path, *args: str, target: str | None = None, upstream: str | None = None, **kwargs: Any
) -> str:
    code, out, err = await _git(repo, *args, **kwargs)
    if code != 0:
        text = err or out
        raise GitOpError(describe_failure(text, target=target, upstream=upstream), clean_output(text))
    return out


async def _ensure_writable(repo: Path) -> dict[str, Any]:
    try:
        policy = await gitinfo.repo_policy(repo, cached=False)
    except gitinfo.GitError as exc:
        # A timeout or an invalid filter: a message for the user, not a 500.
        raise GitOpError(gitinfo.strip_credentials(str(exc)).strip() or GENERIC_MESSAGE) from exc
    if policy["read_only"]:
        raise ReadOnlyError(policy["read_only"])
    return policy


async def _merging(repo: Path) -> bool:
    code, _, _ = await _git(repo, "rev-parse", "--verify", "-q", "MERGE_HEAD")
    return code == 0


async def _has_head(repo: Path) -> bool:
    code, _, _ = await _git(repo, "rev-parse", "--verify", "-q", "HEAD")
    return code == 0


async def _untracked(repo: Path, paths: list[str]) -> set[str]:
    out = await _checked(repo, "ls-files", "-z", "--others", "--exclude-standard", "--", *paths)
    return {path for path in out.split("\0") if path}


# Stage, unstage, discard, commit -------------------------------------------------------


async def _refuse_conflicted(repo: Path, paths: list[str]) -> None:
    """`git add` would mark a conflicted file as resolved, markers and all; `restore` would lose
    both sides. A folder counts when a conflicted file is inside it."""
    # The whole list: one cut at MAX_FILES would let a folder through with conflicts past it.
    conflicts = await _conflicts(repo, complete=True)
    for path in paths:
        prefix = "" if path in ("", ".") else path.rstrip("/") + "/"
        if any(c == path or c.startswith(prefix) for c in conflicts):
            raise InvalidRequestError(CONFLICT_MESSAGE)


async def stage(repo: Path, paths: list[str]) -> None:
    await _ensure_writable(repo)
    await _refuse_conflicted(repo, paths)
    await _checked(repo, "add", "-A", "--", *paths)


async def _rename_origins(repo: Path, paths: list[str]) -> list[str]:
    """Original names of the staged renames whose new name is in `paths`.

    A rename is two index entries (the old name deleted, the new one added); acting on the
    new name alone would leave the old one deleted.
    """
    wanted = set(paths)
    out = await _checked(repo, "status", gitinfo.STATUS_SUBMODULES, "--porcelain=v2", "-z", "--untracked-files=no")
    fields = out.split("\0")
    origins: list[str] = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if entry.startswith("2 "):
            new = entry.split(" ", 9)[9]
            original = fields[index] if index < len(fields) else ""
            index += 1
            if new in wanted and original and original not in wanted and original not in origins:
                origins.append(original)
    return origins


async def unstage(repo: Path, paths: list[str]) -> None:
    await _ensure_writable(repo)
    if await _has_head(repo):
        everything = [*paths, *await _rename_origins(repo, paths)]
        await _checked(repo, "restore", "--staged", "--", *everything)
    else:
        await _checked(repo, "rm", "--cached", "-q", "-r", "--", *paths)


async def discard(repo: Path, paths: list[str]) -> None:
    """Back to the last commit. Only files that have changes; a new file is deleted."""
    await _ensure_writable(repo)
    await _refuse_conflicted(repo, paths)
    try:
        dirty = await gitinfo.dirty_files(repo, timeout=LOCAL_TIMEOUT)
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc
    for path in paths:
        if path not in dirty:
            raise InvalidRequestError(NOT_CHANGED_MESSAGE.format(path=path))
    untracked = await _untracked(repo, paths)
    tracked = [path for path in paths if path not in untracked]
    if tracked:
        if await _has_head(repo):
            everything = [*tracked, *await _rename_origins(repo, tracked)]
            await _checked(
                repo, "restore", "--source=HEAD", "--staged", "--worktree", "--", *everything
            )
        else:
            await _checked(repo, "rm", "-f", "-q", "--", *tracked)
    if untracked:
        # No -d (folders) and no -x (ignored files): only the files asked for.
        await _checked(repo, "clean", "-f", "-q", "--", *sorted(untracked))


async def _nothing_staged(repo: Path) -> bool:
    code, _, err = await _git(
        repo, "diff", "--cached", "--quiet", "--no-ext-diff", gitinfo.DIFF_SUBMODULES
    )
    if code not in (0, 1):
        raise GitOpError(GENERIC_MESSAGE, clean_output(err))
    return code == 0


async def _ensure_identity(repo: Path) -> None:
    """Fail before `add -A`, so a missing identity does not leave everything staged."""
    for name in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        code, out, err = await _git(repo, "var", name)
        if code != 0:
            raise GitOpError(IDENTITY_MESSAGE, clean_output(err or out))


async def commit(repo: Path, message: str) -> str:
    """Commit what is staged; with nothing staged, everything (new files included).

    The message goes through standard input, kept as written (`--cleanup=whitespace`, so a
    first line such as "#123 ..." stays). Returns the new commit's sha.
    """
    text = message.strip()
    if not text:
        raise InvalidRequestError(EMPTY_MESSAGE)
    await _ensure_writable(repo)
    if await _merging(repo):
        raise GitOpError(MERGING_MESSAGE)
    await _ensure_identity(repo)
    if await _nothing_staged(repo):
        await _checked(repo, "add", "-A")
        if await _nothing_staged(repo):
            raise InvalidRequestError(NOTHING_TO_COMMIT)
    await _checked(
        repo, "commit", "--quiet", "--no-verify", "--cleanup=whitespace", "-F", "-",
        input=(text + "\n").encode("utf-8"),
    )
    return (await _checked(repo, "rev-parse", "HEAD")).strip()


# Branches and merge -----------------------------------------------------------------

MAX_BRANCH_NAME = 255
MARKER_READ_LIMIT = 8 * 1024 * 1024

BRANCH_EMPTY = "Escreva o nome da branch."
BRANCH_INVALID = "Nome de branch inválido: {name}."
BRANCH_SPACE = "Nome de branch não pode ter espaço. Por exemplo: {example}."
BRANCH_EXISTS = "Já existe uma branch {name}."
BRANCH_BLOCKED_BY = "Já existe uma branch chamada {other}, que impede criar {name}."
BRANCH_BLOCKS = "Já existem branches dentro de {name}/, o que impede criar {name}."
REMOTE_UNKNOWN = "Esta branch remota não pertence a nenhum remoto configurado."
NOT_MERGING = "Não há merge em andamento neste repositório."
STILL_CONFLICTED = "Ainda há arquivos em conflito. Resolva e marque cada um antes de concluir o merge."
NOT_CONFLICTED = "O arquivo {path} não está em conflito."
MARKERS_LEFT = (
    "O arquivo {path} ainda tem marcas de conflito (<<<<<<< ou >>>>>>>). Resolva antes de marcar."
)
_MARKER = re.compile(rb"^(?:<{7} |>{7} )", re.MULTILINE)
_SWITCH = ("switch", "--no-guess", "--no-recurse-submodules")


@dataclass(frozen=True)
class MergeResult:
    conflicts: bool


async def check_branch_name(repo: Path, name: str) -> str:
    """`name` trimmed, if git accepts it as a new branch; never something that reads as an option."""
    text = name.strip()
    if not text:
        raise InvalidRequestError(BRANCH_EMPTY)
    if " " in text:
        raise InvalidRequestError(BRANCH_SPACE.format(example=re.sub(r" +", "-", text)))
    if (
        len(text) > MAX_BRANCH_NAME or text.startswith("-") or text == "HEAD" or "@{" in text
        or gitinfo._has_control(text)
    ):
        raise InvalidRequestError(BRANCH_INVALID.format(name=text))
    code, out, _ = await _git(repo, "check-ref-format", "--branch", text)
    if code != 0 or out.strip() != text:
        raise InvalidRequestError(BRANCH_INVALID.format(name=text))
    return text


async def _verify(repo: Path, ref: str) -> str:
    try:
        return await gitinfo.verify_branch_ref(repo, ref, timeout=LOCAL_TIMEOUT)
    except gitinfo.RefNotFoundError as exc:
        raise NotFoundError(gitinfo.BRANCH_NOT_FOUND) from exc
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def _ref_exists(repo: Path, ref: str) -> bool:
    code, _, _ = await _git(repo, "show-ref", "--verify", "-q", ref)
    return code == 0


async def _local_name(repo: Path, ref: str) -> str:
    """`refs/remotes/<remote>/<name>` → `<name>`, with the longest remote that matches."""
    short = ref.removeprefix("refs/remotes/")
    try:
        remotes = await gitinfo.remote_names(repo, timeout=LOCAL_TIMEOUT)
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc
    for remote in sorted(remotes, key=len, reverse=True):
        if short.startswith(f"{remote}/") and len(short) > len(remote) + 1:
            return short[len(remote) + 1:]
    raise InvalidRequestError(REMOTE_UNKNOWN)


async def _refuse_merging(repo: Path) -> None:
    if await _merging(repo):
        raise GitOpError(MERGING_MESSAGE)


async def _refuse_clash(repo: Path, name: str) -> None:
    """A branch `a` and `a/b` cannot both exist (git stores refs as files)."""
    parts = name.split("/")
    for end in range(1, len(parts)):
        other = "/".join(parts[:end])
        if await _ref_exists(repo, f"refs/heads/{other}"):
            raise InvalidRequestError(BRANCH_BLOCKED_BY.format(other=other, name=name))
    out = await _checked(repo, "for-each-ref", "--count=1", "--format=%(refname)", f"refs/heads/{name}/")
    if out.strip():
        raise InvalidRequestError(BRANCH_BLOCKS.format(name=name))


async def switch(repo: Path, ref: str) -> None:
    """Check out a branch, carrying the changes (git refuses if they would be overwritten).

    A remote branch becomes a local one that tracks it, unless the local one already exists.
    """
    await _ensure_writable(repo)
    await _refuse_merging(repo)
    await _verify(repo, ref)
    if ref.startswith("refs/heads/"):
        name = ref.removeprefix("refs/heads/")
        await _checked(repo, *_SWITCH, "--end-of-options", name, target=name)
        return
    name = await _local_name(repo, ref)
    if await _ref_exists(repo, f"refs/heads/{name}"):
        await _checked(repo, *_SWITCH, "--end-of-options", name, target=name)
        return
    name = await check_branch_name(repo, name)
    await _refuse_clash(repo, name)
    await _checked(repo, *_SWITCH, "--track", "-c", name, "--end-of-options", ref, target=name)


async def create_branch(repo: Path, name: str) -> str:
    """A new branch from HEAD, already checked out; the changes go with it."""
    await _ensure_writable(repo)
    await _refuse_merging(repo)
    name = await check_branch_name(repo, name)
    if await _ref_exists(repo, f"refs/heads/{name}"):
        raise InvalidRequestError(BRANCH_EXISTS.format(name=name))
    await _refuse_clash(repo, name)
    if await _has_head(repo):
        await _checked(repo, *_SWITCH, "-c", name, target=name)
    else:  # no commit yet: only HEAD's name changes
        await _checked(repo, "symbolic-ref", "HEAD", f"refs/heads/{name}")
    return name


def _merge_subject(ref: str) -> str:
    short = gitinfo._short_ref(ref) or ref
    if ref.startswith("refs/remotes/"):
        return f"Merge remote-tracking branch '{short}'"
    return f"Merge branch '{short}'"


async def _merge_ref(repo: Path, ref: str, *, upstream: str | None = None) -> MergeResult:
    """`git merge` of a verified ref. A conflict is a result, not an error: the merge stays."""
    target = gitinfo._short_ref(ref) or ref
    code, out, err = await _git(
        repo, "merge", "--no-edit", "--no-stat", "--no-progress", "--no-verify",
        # The repository's `branch.<name>.mergeOptions` and `merge.ff` must not change what runs
        # (signing runs `gpg.program`; --squash and --ff-only would break the flow).
        "--no-gpg-sign", "--no-verify-signatures", "--no-squash", "--commit", "--ff",
        "-m", _merge_subject(ref), "--end-of-options", ref,
    )
    if code == 0:
        return MergeResult(conflicts=False)
    if await _merging(repo):
        return MergeResult(conflicts=True)
    text = err or out
    raise GitOpError(describe_failure(text, target=target, upstream=upstream), clean_output(text))


async def merge(repo: Path, ref: str) -> MergeResult:
    policy = await _ensure_writable(repo)
    if policy["no_merge"]:
        raise ReadOnlyError(policy["no_merge"])
    await _refuse_merging(repo)
    await _verify(repo, ref)
    return await _merge_ref(repo, ref)


async def _conflicts(repo: Path, *, complete: bool = False) -> list[str]:
    try:
        return await gitinfo.conflicted_files(repo, timeout=LOCAL_TIMEOUT, complete=complete)
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def _require_merging(repo: Path) -> None:
    if not await _merging(repo):
        raise InvalidRequestError(NOT_MERGING)


async def merge_abort(repo: Path) -> None:
    await _ensure_writable(repo)
    await _require_merging(repo)
    await _checked(repo, "merge", "--abort")


def _has_markers(path: Path) -> bool:
    """Conflict markers at the start of a line. A link is not followed; a missing file has none."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False  # deleted, a link (ELOOP) or unreadable
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return False
        return _MARKER.search(handle.read(MARKER_READ_LIMIT)) is not None


async def mark_resolved(repo: Path, paths: list[str]) -> None:
    await _ensure_writable(repo)
    await _require_merging(repo)
    conflicts = set(await _conflicts(repo))
    for path in paths:
        if path not in conflicts:
            raise InvalidRequestError(NOT_CONFLICTED.format(path=path))
        if await asyncio.to_thread(_has_markers, repo / path):
            raise InvalidRequestError(MARKERS_LEFT.format(path=path))
    await _checked(repo, "add", "-A", "--", *paths)


async def merge_continue(repo: Path, message: str) -> str:
    """The merge commit, once nothing is left in conflict. Returns its sha."""
    text = message.strip()
    if not text:
        raise InvalidRequestError(EMPTY_MESSAGE)
    await _ensure_writable(repo)
    await _require_merging(repo)
    await _ensure_identity(repo)
    if await _conflicts(repo):
        raise GitOpError(STILL_CONFLICTED)
    await _checked(
        repo, "commit", "--quiet", "--no-verify", "--cleanup=whitespace", "-F", "-",
        input=(text + "\n").encode("utf-8"),
    )
    return (await _checked(repo, "rev-parse", "HEAD")).strip()


# Network -----------------------------------------------------------------------------

PULL_FAILED = "Não foi possível baixar do remoto: {error}"
PUSH_FAILED = "O envio não foi feito."
NO_URL_MESSAGE = "O remoto {remote} não tem endereço (URL) configurado."
REJECTED_MESSAGE = (
    "O envio não foi feito: {upstream} recebeu {commits} que você ainda não tem. "
    "Sincronize para baixar e enviar."
)


async def _upstream(repo: Path) -> gitinfo.Upstream:
    try:
        upstream = await gitinfo.upstream_of(repo)
        if upstream is not None:
            return upstream
        detached = await gitinfo._read(repo, "symbolic-ref", "-q", "HEAD") is None
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc
    raise GitOpError(gitinfo.DETACHED_MESSAGE if detached else gitinfo.NO_UPSTREAM_MESSAGE)


def _remote_failure(exc: gitinfo.GitError, fallback: str, upstream: str | None = None) -> GitOpError:
    output = getattr(exc, "output", "")
    message = describe_failure(output, upstream=upstream) if output else GENERIC_MESSAGE
    if message == GENERIC_MESSAGE:
        message = fallback
    return GitOpError(message, clean_output(output))


async def _fetch(repo: Path) -> bool:
    """Fetch the upstream through the registry (never two at once). True when something came."""
    caught: list[gitinfo.GitError] = []

    async def run() -> bool:
        try:
            return await gitinfo.fetch_upstream(repo, timeout=NETWORK_TIMEOUT)
        except gitinfo.GitError as exc:
            caught.append(exc)
            raise

    result = await gitfetch.registry.fetch(repo, run)
    if result != "failed":
        return result == "fetched"
    error = gitfetch.registry.fields(repo)["fetch_error"] or gitfetch.GENERIC_ERROR
    if caught:
        raise _remote_failure(caught[0], PULL_FAILED.format(error=error))
    raise GitOpError(PULL_FAILED.format(error=error))


def _short(upstream: gitinfo.Upstream) -> str:
    return upstream.tracking.removeprefix("refs/remotes/")


async def _behind(repo: Path, upstream: gitinfo.Upstream) -> int:
    try:
        return await gitinfo.count_between(repo, "HEAD", upstream.tracking, timeout=LOCAL_TIMEOUT)
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def _ahead(repo: Path, upstream: gitinfo.Upstream) -> int:
    try:
        return await gitinfo.count_between(repo, upstream.tracking, "HEAD", timeout=LOCAL_TIMEOUT)
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def pull(repo: Path) -> MergeResult:
    """Fetch the upstream and merge it (like the VS Code pull with merge)."""
    policy = await _ensure_writable(repo)
    if policy["no_merge"]:
        raise ReadOnlyError(policy["no_merge"])
    await _refuse_merging(repo)
    upstream = await _upstream(repo)
    if not await _fetch(repo):
        # The upstream exists, so nothing was fetched only because the remote has no URL.
        # Merging the old tracking ref without saying so would look like a pull.
        raise GitOpError(NO_URL_MESSAGE.format(remote=upstream.remote))
    if await _behind(repo, upstream) == 0:
        return MergeResult(conflicts=False)
    return await _merge_ref(repo, upstream.tracking, upstream=_short(upstream))


async def push(repo: Path) -> None:
    await _ensure_writable(repo)
    await _refuse_merging(repo)
    upstream = await _upstream(repo)
    try:
        await gitinfo.push_upstream(repo, timeout=NETWORK_TIMEOUT)
    except gitinfo.RemoteError as exc:
        failure = _remote_failure(exc, PUSH_FAILED, _short(upstream))
        if "[rejected]" in exc.output:
            await _count_rejection(repo, upstream, failure)
        raise failure from exc
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def _count_rejection(repo: Path, upstream: gitinfo.Upstream, failure: GitOpError) -> None:
    """After a refused push, fetch so the message (and the repository's row) shows how many
    commits came in. If the fetch fails too, the message stays without the count."""
    try:
        await _fetch(repo)
        behind = await _behind(repo, upstream)
    except GitOpError:
        return
    if behind > 0:
        commits = "1 commit" if behind == 1 else f"{behind} commits"
        failure.message = REJECTED_MESSAGE.format(upstream=_short(upstream), commits=commits)
        failure.args = (failure.message,)


async def sync(repo: Path) -> MergeResult:
    """Pull, then push what is left to send; a conflict stops before the push."""
    await _ensure_writable(repo)
    try:
        gitinfo.check_same_name(await _upstream(repo))  # before the pull changes anything
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc
    result = await pull(repo)
    if result.conflicts:
        return result
    upstream = await _upstream(repo)
    if await _ahead(repo, upstream) > 0:
        await push(repo)
    return result


async def publish(repo: Path) -> str:
    await _ensure_writable(repo)
    await _refuse_merging(repo)
    try:
        return await gitinfo.publish_branch(repo, timeout=NETWORK_TIMEOUT)
    except gitinfo.RemoteError as exc:
        raise _remote_failure(exc, PUSH_FAILED) from exc
    except gitinfo.GitError as exc:
        raise GitOpError(str(exc)) from exc


async def fetch_repo(repo: Path) -> None:
    """"Buscar no remoto": fetch only. Allowed in read-only repositories (no file changes)."""
    await _fetch(repo)
