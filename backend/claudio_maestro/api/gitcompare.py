"""Read-only branch comparison routes, separate from checkout and merge actions."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from claudio_maestro import gitcompare, gitinfo
from claudio_maestro.api.deps import DbDep
from claudio_maestro.api.gitops import _git_failure, project_repo
from claudio_maestro.security import PathNotAllowedError, resolve_within

router = APIRouter(prefix="/api/projects/{project_id}/git/comparison")
FullSha = Annotated[str, Query(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


def _failure(exc: gitinfo.GitError) -> HTTPException:
    if isinstance(exc, gitcompare.UnrelatedHistoryError):
        return HTTPException(status_code=409, detail=str(exc))
    return _git_failure(exc)


@router.get("")
async def comparison(project_id: int, repo: str, base: str, conn: DbDep, ref: str | None = None) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitcompare.comparison(path, base, ref)
    except gitinfo.GitError as exc:
        raise _failure(exc) from exc


@router.get("/commits")
async def commits(
    project_id: int, repo: str, head_sha: FullSha, base_sha: FullSha,
    direction: gitcompare.Direction, conn: DbDep,
    skip: int = Query(0, ge=0, le=gitinfo.MAX_LOG_SKIP),
    limit: int = Query(gitinfo.LOG_PAGE, ge=1, le=gitinfo.MAX_LOG_LIMIT),
) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitcompare.commits(path, head_sha, base_sha, direction, skip=skip, limit=limit)
    except gitinfo.GitError as exc:
        raise _failure(exc) from exc


@router.get("/files")
async def files(
    project_id: int, repo: str, head_sha: FullSha, base_sha: FullSha,
    direction: gitcompare.Direction, conn: DbDep,
) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        return await gitcompare.files(path, head_sha, base_sha, direction)
    except gitinfo.GitError as exc:
        raise _failure(exc) from exc


@router.get("/diff")
async def file_diff(
    project_id: int, repo: str, head_sha: FullSha, base_sha: FullSha,
    direction: gitcompare.Direction, file: str, conn: DbDep,
) -> dict[str, Any]:
    _, path = await project_repo(conn, project_id, repo)
    try:
        resolved = resolve_within(file, [path], base=path)
    except PathNotAllowedError as exc:
        raise HTTPException(status_code=403, detail="O arquivo precisa estar dentro do repositório.") from exc
    if resolved == path:
        raise HTTPException(status_code=400, detail="Informe um arquivo.")
    relative = resolved.relative_to(path).as_posix()
    try:
        result = await gitcompare.file_diff(path, head_sha, base_sha, direction, relative)
    except gitinfo.GitError as exc:
        raise _failure(exc) from exc
    return {"diff": result.diff, "truncated": result.truncated, "notice": result.notice}
