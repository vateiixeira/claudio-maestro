"""Git routes: repositories of a project, file diff and a session's changed files."""

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from claudio_maestro import gitinfo, projects, sessions
from claudio_maestro.api.deps import DbDep
from claudio_maestro.security import PathNotAllowedError, resolve_within

router = APIRouter(prefix="/api")

EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")


def _project(conn: sqlite3.Connection, project_id: int) -> projects.Project:
    try:
        return projects.get_project(conn, project_id)
    except projects.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.get("/projects/{project_id}/git")
async def project_git(project_id: int, conn: DbDep) -> dict[str, Any]:
    project = _project(conn, project_id)
    if not project.available:
        return {"repos": [], "limit_reached": False}
    repos, limit_reached = await gitinfo.project_repos_scan(Path(project.path))
    return {"repos": [repo.to_dict() for repo in repos], "limit_reached": limit_reached}


@router.get("/projects/{project_id}/git/details")
async def project_git_details(project_id: int, conn: DbDep) -> dict[str, Any]:
    project = _project(conn, project_id)
    if not project.available:
        return {"repos": [], "limit_reached": False}
    repos, limit_reached = await gitinfo.project_details_scan(Path(project.path))
    return {"repos": repos, "limit_reached": limit_reached}


async def _worktree_root(repo: str, root: Path) -> Path | None:
    """`repo` (absolute) when it is exactly the root of a proven worktree, else None."""
    if not repo or "\x00" in repo or not os.path.isabs(repo):
        return None
    found = await gitinfo.project_worktree(Path(repo), [root])
    if found is None or Path(os.path.realpath(repo)) != found.path:
        return None
    return found.path


@router.get("/projects/{project_id}/diff")
async def file_diff(project_id: int, repo: str, file: str, conn: DbDep) -> dict[str, Any]:
    project = _project(conn, project_id)
    root = Path(project.path).resolve()
    try:
        repo_path = resolve_within(repo, [root], base=root)
    except PathNotAllowedError as exc:
        # The one exception: the root of a proven linked worktree of a repository in the project.
        repo_path = await _worktree_root(repo, root)
        if repo_path is None:
            raise _forbidden("O repositório precisa estar dentro do projeto.") from exc
    if not (repo_path / ".git").exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A pasta não é um repositório git."
        )
    try:
        file_path = resolve_within(file, [repo_path], base=repo_path)
    except PathNotAllowedError as exc:
        raise _forbidden("O arquivo precisa estar dentro do repositório.") from exc
    if file_path == repo_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe um arquivo.")
    relative = file_path.relative_to(repo_path).as_posix()
    try:
        result = await gitinfo.file_diff(repo_path, relative)
    except gitinfo.FileGoneError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except gitinfo.GitError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"diff": result.diff, "truncated": result.truncated, "notice": result.notice}


def _patch_counts(item: dict[str, Any]) -> tuple[int, int] | None:
    counts = item.get("counts")
    if counts is not None:
        return counts
    result = item.get("result")
    details = result.get("details") if isinstance(result, dict) else None
    patch = details.get("structuredPatch") if isinstance(details, dict) else None
    if not isinstance(patch, list):
        return None
    added = removed = 0
    for hunk in patch:
        lines = hunk.get("lines") if isinstance(hunk, dict) else None
        for line in lines or []:
            if isinstance(line, str) and line.startswith("+"):
                added += 1
            elif isinstance(line, str) and line.startswith("-"):
                removed += 1
    return added, removed


def _edited_files(items: list[dict[str, Any]], cwd: Path) -> dict[Path, list[int] | None]:
    """Edited file -> [added, removed] summed over its edits (None: no patch seen)."""
    files: dict[Path, list[int] | None] = {}
    for item in items:
        if item.get("type") != "tool" or item.get("name") not in EDIT_TOOLS:
            continue
        data = item.get("input") or {}
        raw = data.get("file_path") or data.get("notebook_path")
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            continue
        path = Path(raw) if Path(raw).is_absolute() else cwd / raw
        # Resolved like the repositories, so links and `..` group correctly.
        path = Path(os.path.realpath(path))
        counts = _patch_counts(item)
        current = files.setdefault(path, None)
        if counts is not None:
            if current is None:
                files[path] = [counts[0], counts[1]]
            else:
                current[0] += counts[0]
                current[1] += counts[1]
    return files


def _owner(path: Path, repos: list[gitinfo.RepoStatus]) -> gitinfo.RepoStatus | None:
    best = None
    path = Path(os.path.normpath(path))
    for repo in repos:
        if path.is_relative_to(os.path.normpath(repo.path)) and (best is None or len(repo.path) > len(best.path)):
            best = repo
    return best


async def _dirty(repo: gitinfo.RepoStatus) -> set[str]:
    if repo.error:
        return set()
    try:
        return await gitinfo.dirty_files(Path(repo.path))
    except gitinfo.GitError:
        return set()


async def _with_worktrees(
    repos: list[gitinfo.RepoStatus],
    files: dict[Path, list[int] | None],
    root: Path,
    names: dict[str, str],
) -> list[gitinfo.RepoStatus]:
    """`repos` plus every proven linked worktree an edited file lives in.

    The scan skips dot folders (`.claude/worktrees`) and cannot see worktrees outside the
    project. `names` receives realpath -> worktree name for each proven worktree.
    """
    by_folder: dict[Path, gitinfo.LinkedWorktree | None] = {}
    for path in files:
        if path.parent not in by_folder:
            by_folder[path.parent] = await gitinfo.project_worktree(path.parent, [root])
    known = {os.path.realpath(repo.path) for repo in repos}
    result = list(repos)
    for found in by_folder.values():
        if found is None or str(found.path) in names:
            continue
        names[str(found.path)] = found.name
        if str(found.path) in known:
            continue
        # No `root`: a worktree outside the project has no path relative to it.
        status_ = await gitinfo.repo_status(found.path)
        status_.rel_path = (
            found.path.relative_to(root).as_posix() if found.path.is_relative_to(root)
            else str(found.path)
        )
        result.append(status_)
    return result


@router.get("/sessions/{session_id}/changes")
async def session_changes(session_id: str, conn: DbDep, request: Request) -> dict[str, Any]:
    manager: sessions.SessionManager = request.app.state.sessions
    try:
        session = manager.get(session_id)
    except sessions.SessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    project = _project(conn, session.record.project_id)
    snapshot = await manager.open(session_id)
    root = Path(project.path).resolve()
    items = list(snapshot.get("items", []))
    # Edits older than the loaded history come from the whole transcript.
    seen = {item.get("tool_use_id") for item in items if item.get("type") == "tool"}
    for edit in await manager.transcript_edits(session_id):
        if edit["tool_use_id"] in seen:
            continue
        added, removed = edit.get("added"), edit.get("removed")
        items.append({
            "type": "tool", "name": edit["name"], "tool_use_id": edit["tool_use_id"],
            "input": {"file_path": edit["file_path"]},
            "counts": (added, removed) if added is not None and removed is not None else None,
        })
    files = _edited_files(items, Path(session.record.work_dir()))

    repos = await gitinfo.project_repos(root) if project.available else []
    worktree_names: dict[str, str] = {}
    if project.available:
        repos = await _with_worktrees(repos, files, root, worktree_names)
    groups: dict[str | None, list[tuple[Path, list[int] | None]]] = {}
    owners: dict[str | None, gitinfo.RepoStatus | None] = {}
    for path, counts in files.items():
        owner = _owner(path, repos)
        key = owner.path if owner else None
        owners[key] = owner
        groups.setdefault(key, []).append((path, counts))

    used = [owner for owner in owners.values() if owner is not None]
    dirty = dict(zip(
        [repo.path for repo in used], await asyncio.gather(*(_dirty(r) for r in used)),
        strict=True,
    ))

    out = []
    for key, entries in groups.items():
        owner = owners[key]
        base = Path(owner.path) if owner else root
        group_files = []
        for path, counts in sorted(entries):
            rel = path.relative_to(base).as_posix() if path.is_relative_to(base) else str(path)
            group_files.append({
                "path": str(path),
                "rel_path": rel,
                "added": counts[0] if counts else None,
                "removed": counts[1] if counts else None,
                "uncommitted": rel in dirty[key] if owner else None,
            })
        out.append({
            "path": owner.path if owner else None,
            "rel_path": owner.rel_path if owner else None,
            "branch": owner.branch if owner else None,
            "detached": owner.detached if owner else False,
            "head": owner.head if owner else None,
            "worktree": worktree_names.get(os.path.realpath(owner.path)) if owner else None,
            "files": group_files,
        })
    out.sort(key=lambda g: (g["rel_path"] is None, g["rel_path"] or ""))
    return {"repos": out}
