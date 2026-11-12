"""Read-only, snapshot-based branch comparison for the commits panel."""

from pathlib import Path
from typing import Any, Literal

from claudio_maestro import gitinfo

Direction = Literal["ahead", "behind"]
UNRELATED = "As branches não têm ancestral comum. Escolha outra base para comparar arquivos."


class UnrelatedHistoryError(gitinfo.GitError):
    """Commit lists exist, but there is no shared base for file comparisons."""


async def _snapshot(repo: Path, head: str, base: str, timeout: float) -> tuple[str, str]:
    if not gitinfo.FULL_SHA_RE.fullmatch(head) or not gitinfo.FULL_SHA_RE.fullmatch(base):
        raise gitinfo.RefNotFoundError(gitinfo.COMMIT_NOT_FOUND)
    return (
        await gitinfo._resolve_commit(repo, head, timeout),
        await gitinfo._resolve_commit(repo, base, timeout),
    )


def _direction(direction: str) -> None:
    if direction not in ("ahead", "behind"):
        raise gitinfo.GitError("Sentido da comparação inválido.")


async def _merge_base(repo: Path, head: str, base: str, timeout: float) -> str | None:
    code, out, err = await gitinfo.run_git(repo, "merge-base", head, base, timeout=timeout)
    if code == 1:
        return None
    if code != 0:
        raise gitinfo.GitError(gitinfo._failure(err))
    return out.strip()


async def comparison(
    repo: Path, base: str, ref: str | None = None, *, timeout: float = gitinfo.GIT_TIMEOUT,
) -> dict[str, Any]:
    return await gitinfo._within(timeout, _comparison(repo, base, ref, timeout))


async def _comparison(repo: Path, base: str, ref: str | None, timeout: float) -> dict[str, Any]:
    base_sha = await gitinfo.verify_branch_ref(repo, base, timeout=timeout)
    if ref is None:
        code, out, _ = await gitinfo.run_git(repo, "symbolic-ref", "-q", "HEAD", timeout=timeout)
        head_ref = out.strip() if code == 0 else None
        code, out, _ = await gitinfo.run_git(repo, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout)
        if code != 0:
            raise gitinfo.RefNotFoundError("Ainda não há commit para comparar.")
        head_sha = out.strip()
    else:
        head_ref = ref
        head_sha = await gitinfo.verify_branch_ref(repo, ref, timeout=timeout)
    merge_base = await _merge_base(repo, head_sha, base_sha, timeout)
    code, out, err = await gitinfo.run_git(
        repo, "rev-list", "--left-right", "--count", "--end-of-options",
        f"{head_sha}...{base_sha}", "--", timeout=timeout,
    )
    if code != 0:
        raise gitinfo.GitError(gitinfo._failure(err))
    ahead, behind = map(int, out.split())
    return {
        "head_ref": head_ref, "base_ref": base, "head_sha": head_sha, "base_sha": base_sha,
        "merge_base": merge_base, "ahead_count": ahead, "behind_count": behind,
        "unrelated": merge_base is None, "notice": UNRELATED if merge_base is None else None,
    }


async def commits(
    repo: Path, head_sha: str, base_sha: str, direction: Direction, *,
    skip: int = 0, limit: int = gitinfo.LOG_PAGE, timeout: float = gitinfo.GIT_TIMEOUT,
) -> dict[str, Any]:
    _direction(direction)
    return await gitinfo._within(timeout, _commits(repo, head_sha, base_sha, direction, skip, limit, timeout))


async def _commits(
    repo: Path, head: str, base: str, direction: Direction, skip: int, limit: int, timeout: float,
) -> dict[str, Any]:
    head, base = await _snapshot(repo, head, base, timeout)
    revision = f"{base}..{head}" if direction == "ahead" else f"{head}..{base}"
    output = await gitinfo._log(repo, revision, timeout, f"--skip={skip}", "-n", str(limit + 1))
    # Do not report a clipped commit/message as a complete page.
    if len(output.encode("utf-8")) > gitinfo.FILES_READ_LIMIT:
        raise gitinfo.GitError("A página de commits é grande demais. Reduza o tamanho da página.")
    found = gitinfo._parse_log(output)
    more = len(found) > limit
    return {"commits": found[:limit], "has_more": more, "next_skip": skip + limit if more else None}


async def files(
    repo: Path, head_sha: str, base_sha: str, direction: Direction, *, timeout: float = gitinfo.GIT_TIMEOUT,
) -> dict[str, Any]:
    _direction(direction)
    return await gitinfo._within(timeout, _files(repo, head_sha, base_sha, direction, timeout))


async def _files(repo: Path, head: str, base: str, direction: Direction, timeout: float) -> dict[str, Any]:
    head, base = await _snapshot(repo, head, base, timeout)
    ancestor = await _merge_base(repo, head, base, timeout)
    if ancestor is None:
        raise UnrelatedHistoryError(UNRELATED)
    target = head if direction == "ahead" else base
    common = ("diff-tree", *gitinfo.DIFF_TREE_COMMON)
    code, names, err = await gitinfo.run_git(
        repo, *common, "--name-status", ancestor, target, "--",
        timeout=timeout, limit=gitinfo.FILES_READ_LIMIT,
    )
    if code != 0:
        raise gitinfo.GitError(gitinfo._failure(err))
    names_clipped = len(names.encode("utf-8")) > gitinfo.FILES_READ_LIMIT
    if names_clipped:
        names = names[:names.rfind("\0") + 1]
    code, numbers, err = await gitinfo.run_git(
        repo, *common, "--numstat", ancestor, target, "--",
        timeout=timeout, limit=gitinfo.FILES_READ_LIMIT,
    )
    if code != 0:
        raise gitinfo.GitError(gitinfo._failure(err))
    counts = gitinfo._parse_numstat(numbers) if len(numbers.encode("utf-8")) <= gitinfo.FILES_READ_LIMIT else {}
    # A bounded read may end after a status or rename's old path. The shared
    # parser represents that incomplete final record with an empty new path.
    found = [item for item in gitinfo._parse_name_status(names) if item["path"]]
    truncated = names_clipped or len(found) > gitinfo.MAX_FILES
    found = found[:gitinfo.MAX_FILES]
    for item in found:
        item["added"], item["removed"] = counts.get(item["path"], (None, None))
    return {"files": found, "files_truncated": truncated, "base_sha": ancestor, "target_sha": target}


async def file_diff(
    repo: Path, head_sha: str, base_sha: str, direction: Direction, file: str, *,
    timeout: float = gitinfo.GIT_TIMEOUT,
) -> gitinfo.FileDiff:
    _direction(direction)
    return await gitinfo._within(timeout, _file_diff(repo, head_sha, base_sha, direction, file, timeout))


async def _file_diff(
    repo: Path, head: str, base: str, direction: Direction, file: str, timeout: float,
) -> gitinfo.FileDiff:
    listed = await _files(repo, head, base, direction, timeout)
    match = next((item for item in listed["files"] if item["path"] == file), None)
    if match is None:
        raise gitinfo.RefNotFoundError("O arquivo não faz parte desta comparação.")
    paths = [match["old_path"], file] if match["old_path"] else [file]
    code, out, err = await gitinfo.run_git(
        repo, "diff", "--no-color", "--no-ext-diff", "--no-textconv", gitinfo.DIFF_SUBMODULES, "-M",
        listed["base_sha"], listed["target_sha"], "--", *paths,
        timeout=timeout, limit=gitinfo.DIFF_READ_LIMIT,
    )
    if code != 0:
        raise gitinfo.GitError(gitinfo._failure(err))
    return gitinfo.FileDiff(out[:gitinfo.DIFF_LIMIT], len(out) > gitinfo.DIFF_LIMIT)
