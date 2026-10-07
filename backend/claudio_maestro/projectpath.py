"""Paths the app may touch: inside a registered project, or inside a proven linked
worktree of a repository that is inside one."""

import os
from pathlib import Path

from claudio_maestro import gitinfo
from claudio_maestro.security import PathNotAllowedError, resolve_within


async def resolve_project_path(
    raw: str, roots: list[Path], *, base: Path | None = None
) -> Path:
    """Resolved `raw` (symlinks followed) when it is inside a root or inside a proven
    linked worktree (see `gitinfo.project_worktree`). Relative paths need `base`.

    Raises `PathNotAllowedError` otherwise."""
    try:
        return resolve_within(raw, roots, base=base)
    except PathNotAllowedError:
        if not raw or "\x00" in raw:
            raise
        if os.path.isabs(raw):
            joined = raw
        elif base is not None:
            joined = os.path.join(base, raw)
        else:
            raise
    target = Path(os.path.realpath(joined))
    found = await gitinfo.project_worktree(target, roots)
    if found is None or not target.is_relative_to(found.path):
        raise PathNotAllowedError("Caminho fora das pastas permitidas.")
    return target
