"""Serve the built frontend. Only the single-command mode turns this on."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

# Files under assets/ carry a content hash in the name, so they never change.
ASSET_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"


def resolve_asset(root: Path, path: str) -> Path | None:
    """The file `path` inside `root` (already resolved), or None.

    Symlinks are followed and must stay inside `root`; folders are not files.
    """
    if not path:
        return None
    try:
        candidate = (root / path).resolve()
        if candidate == root or not candidate.is_relative_to(root) or not candidate.is_file():
            return None
    except (ValueError, OSError):
        # A NUL byte or a name too long for the filesystem: no such file.
        return None
    return candidate


def mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve `dist` at the root. Unknown paths get index.html (Vue Router), except /api/."""
    root = dist.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        asset = resolve_asset(root, path)
        if asset is None:
            return FileResponse(index, headers={"Cache-Control": NO_CACHE})
        cache = ASSET_CACHE if asset.relative_to(root).parts[0] == "assets" else NO_CACHE
        return FileResponse(asset, headers={"Cache-Control": cache})
