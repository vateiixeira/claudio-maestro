"""Git routes of the project screen: history, commits, branches and (later tasks) actions."""

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from claudio_maestro import gitinfo
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.git import _forbidden, _project, _worktree_root
from claudio_maestro.security import PathNotAllowedError, resolve_within

router = APIRouter(prefix="/api")

NOT_A_REPO = "A pasta não é um repositório do projeto."
INVALID_SHA = "Hash de commit inválido."


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
