"""Git routes of the project screen: history, commits, branches and write actions."""

import asyncio
import os
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from claudio_maestro import gitinfo, gitops
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.git import _forbidden, _project, _worktree_root
from claudio_maestro.security import PathNotAllowedError, resolve_within

router = APIRouter(prefix="/api")

NOT_A_REPO = "A pasta não é um repositório do projeto."
INVALID_SHA = "Hash de commit inválido."

Path4096 = Annotated[str, Field(min_length=1, max_length=4096)]


async def project_repo(conn: sqlite3.Connection, project_id: int, repo: str) -> tuple[Path, Path]:
    """(project folder, repository) for `repo`, checked like /diff.

    The repository must be one the project scan finds, or the root of a proven linked
    worktree of one of them (inside or outside the project folder).
    """
    project = _project(conn, project_id)
    if not project.available:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="A pasta do projeto não existe mais.")
    root = Path(project.path).resolve()
    try:
        repo_path = resolve_within(repo, [root], base=root)
    except PathNotAllowedError as exc:
        worktree = await _worktree_root(repo, root)
        if worktree is None:
            raise _forbidden("O repositório precisa estar dentro do projeto.") from exc
        return root, worktree
    found = {Path(os.path.realpath(path)) for path in await asyncio.to_thread(gitinfo.discover, root)}
    if repo_path in found:
        return root, repo_path
    worktree = await _worktree_root(str(repo_path), root)
    if worktree is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_REPO)
    return root, worktree


def _git_failure(exc: gitinfo.GitError) -> HTTPException:
    if isinstance(exc, gitinfo.RefNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def _check_sha(sha: str) -> None:
    if not gitinfo.SHA_RE.match(sha):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_SHA)


@router.get("/projects/{project_id}/git/log")
async def git_log(
    project_id: int, repo: str, conn: DbDep, ref: str | None = None,
    skip: int = Query(0, ge=0, le=gitinfo.MAX_LOG_SKIP),
    limit: int = Query(gitinfo.LOG_PAGE, ge=1, le=gitinfo.MAX_LOG_LIMIT),
) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitinfo.repo_log(path, ref, skip=skip, limit=limit)
    except gitinfo.GitError as exc:
        raise _git_failure(exc) from exc


@router.get("/projects/{project_id}/git/commit")
async def git_commit(project_id: int, repo: str, sha: str, conn: DbDep) -> dict[str, Any]:
    _check_sha(sha)
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitinfo.commit_detail(path, sha)
    except gitinfo.GitError as exc:
        raise _git_failure(exc) from exc


@router.get("/projects/{project_id}/git/commit/diff")
async def git_commit_diff(
    project_id: int, repo: str, sha: str, file: str, conn: DbDep
) -> dict[str, Any]:
    _check_sha(sha)
    if not file or "\x00" in file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe um arquivo.")
    _, path = await project_repo(conn, project_id, repo)
    try:
        result = await gitinfo.commit_file_diff(path, sha, file)
    except gitinfo.GitError as exc:
        raise _git_failure(exc) from exc
    return {"diff": result.diff, "truncated": result.truncated, "notice": result.notice}


@router.get("/projects/{project_id}/git/branches")
async def git_branches(project_id: int, repo: str, conn: DbDep) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitinfo.branches(path)
    except gitinfo.GitError as exc:
        raise _git_failure(exc) from exc


@router.get("/projects/{project_id}/git/compare")
async def git_compare(project_id: int, repo: str, ref: str, conn: DbDep) -> dict[str, int]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        await gitinfo.verify_branch_ref(path, ref)
        return {"incoming": await gitinfo.count_between(path, "HEAD", ref)}
    except gitinfo.GitError as exc:
        raise _git_failure(exc) from exc


class RepoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: Path4096


class PathsBody(RepoBody):
    paths: list[Path4096] = Field(min_length=1, max_length=gitops.MAX_PATHS)


class CommitBody(RepoBody):
    message: str = Field(max_length=gitops.MAX_MESSAGE)

    @field_validator("message")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("A mensagem não pode ter o caractere NUL.")
        return value


_ERROR_STATUS = {
    "invalid": status.HTTP_400_BAD_REQUEST,
    "not_found": status.HTTP_404_NOT_FOUND,
}


def _op_error(exc: gitops.GitOpError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_409_CONFLICT),
        detail={"code": exc.code, "message": exc.message, "output": exc.output},
    )


def _paths(repo_path: Path, raw: list[str]) -> list[str]:
    try:
        return list(dict.fromkeys(gitops.repo_relpath(repo_path, path) for path in raw))
    except gitops.GitOpError as exc:
        raise _op_error(exc) from exc


async def _repo_answer(
    request: Request, project_id: int, root: Path, repo_path: Path, **extra: Any
) -> dict[str, Any]:
    """Publish `project.git` and answer with the repository as /git/details shows it."""
    await request.app.state.git_monitor.refresh_project(project_id, force=True)
    base = root if repo_path.is_relative_to(root) else None
    return {"repo": await gitinfo.repo_details(repo_path, base), **extra}


async def _run(
    request: Request, project_id: int, root: Path, repo_path: Path,
    action: Callable[[], Awaitable[Any]],
) -> Any:
    """Run `action` under the repository's lock; a failure becomes the JSON error."""
    try:
        async with gitops.repo_lock(repo_path):
            return await action()
    except gitops.GitOpError as exc:
        if not isinstance(exc, gitops.RepoBusyError | gitops.InvalidRequestError):
            # The repository may have changed before the failure; others should see it.
            await request.app.state.git_monitor.refresh_project(project_id, force=True)
        raise _op_error(exc) from exc


@router.post("/projects/{project_id}/git/stage")
async def git_stage(project_id: int, body: PathsBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    paths = _paths(path, body.paths)
    await _run(request, project_id, root, path, lambda: gitops.stage(path, paths))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/unstage")
async def git_unstage(project_id: int, body: PathsBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    paths = _paths(path, body.paths)
    await _run(request, project_id, root, path, lambda: gitops.unstage(path, paths))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/discard")
async def git_discard(project_id: int, body: PathsBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    paths = _paths(path, body.paths)
    await _run(request, project_id, root, path, lambda: gitops.discard(path, paths))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/commit")
async def git_commit_action(project_id: int, body: CommitBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    await _run(request, project_id, root, path, lambda: gitops.commit(path, body.message))
    return await _repo_answer(request, project_id, root, path)


class RefBody(RepoBody):
    ref: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"^refs/(heads|remotes)/.")]


class BranchBody(RepoBody):
    name: Annotated[str, Field(min_length=1, max_length=1024)]


@router.post("/projects/{project_id}/git/switch")
async def git_switch(project_id: int, body: RefBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    await _run(request, project_id, root, path, lambda: gitops.switch(path, body.ref))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/branch")
async def git_branch(project_id: int, body: BranchBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    await _run(request, project_id, root, path, lambda: gitops.create_branch(path, body.name))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/merge")
async def git_merge(project_id: int, body: RefBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    result = await _run(request, project_id, root, path, lambda: gitops.merge(path, body.ref))
    return await _repo_answer(request, project_id, root, path, conflicts=result.conflicts)


@router.post("/projects/{project_id}/git/merge-abort")
async def git_merge_abort(project_id: int, body: RepoBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    await _run(request, project_id, root, path, lambda: gitops.merge_abort(path))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/merge-continue")
async def git_merge_continue(project_id: int, body: CommitBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    await _run(request, project_id, root, path, lambda: gitops.merge_continue(path, body.message))
    return await _repo_answer(request, project_id, root, path)


@router.post("/projects/{project_id}/git/resolve")
async def git_resolve(project_id: int, body: PathsBody, request: Request, conn: DbDep) -> dict[str, Any]:
    root, path = await project_repo(conn, project_id, body.repo)
    paths = _paths(path, body.paths)
    await _run(request, project_id, root, path, lambda: gitops.mark_resolved(path, paths))
    return await _repo_answer(request, project_id, root, path)
