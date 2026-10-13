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
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from claudio_maestro import gitinfo
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
    "Permission denied (publickey", "Host key verification failed",
    "Could not read from remote repository", "ssh: Could not resolve hostname",
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
    policy = await gitinfo.repo_policy(repo, cached=False)
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


async def stage(repo: Path, paths: list[str]) -> None:
    await _ensure_writable(repo)
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
