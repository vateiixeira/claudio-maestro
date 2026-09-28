"""Request guards (Host and Origin) and path validation."""

import json
import os
from collections.abc import Iterable
from pathlib import Path

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from vibing.config import BACKEND_PORT, FRONTEND_PORT, LOCAL_HOSTNAMES

ALLOWED_HOSTS = frozenset(
    f"{name}:{port}" for name in LOCAL_HOSTNAMES for port in (FRONTEND_PORT, BACKEND_PORT)
)
ALLOWED_ORIGINS = frozenset(f"http://{name}:{FRONTEND_PORT}" for name in LOCAL_HOSTNAMES)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# WebSocket close code "policy violation". Closing before accept makes the
# server answer the handshake with HTTP 403.
WS_POLICY_VIOLATION = 1008


class HostOriginMiddleware:
    """Pure ASGI middleware that checks Host and Origin on HTTP and WebSocket.

    - Host must be localhost or 127.0.0.1 on the frontend or backend port
      (blocks DNS rebinding). Otherwise: 400, or WebSocket closed before accept.
    - Origin, when present, must be the app's own. It is required on
      state-changing methods and on WebSockets. Otherwise: 403, or WebSocket
      closed before accept.
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: Iterable[str] = ALLOWED_HOSTS,
        allowed_origins: Iterable[str] = ALLOWED_ORIGINS,
    ) -> None:
        self.app = app
        self.allowed_hosts = frozenset(allowed_hosts)
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "").lower()
        origin = headers.get("origin")

        if host not in self.allowed_hosts:
            await self._reject(scope, send, 400, "Host não permitido.")
            return

        origin_required = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
        if origin is None:
            if origin_required:
                await self._reject(scope, send, 403, "Origem ausente.")
                return
        elif origin not in self.allowed_origins:
            await self._reject(scope, send, 403, "Origem não permitida.")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION, "reason": ""})
            return
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class PathNotAllowedError(ValueError):
    """The path is relative, malformed, or resolves outside every allowed root."""


def is_within(path: Path, root: Path) -> bool:
    """True if `path` resolves to `root` or something inside it."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def resolve_within(
    path: str | os.PathLike[str],
    roots: Iterable[Path],
    *,
    base: Path | None = None,
) -> Path:
    """Resolve `path` (following symlinks) and require it to be inside a root.

    Relative paths are only accepted when `base` is given; they are joined to
    it before resolving. The path does not need to exist. Returns the resolved
    absolute path, or raises `PathNotAllowedError`.
    """
    raw = os.fspath(path)
    if not raw or "\x00" in raw:
        raise PathNotAllowedError("Caminho inválido.")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if base is None:
            raise PathNotAllowedError("O caminho precisa ser absoluto.")
        candidate = base / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise PathNotAllowedError("Caminho inválido.") from exc
    for root in roots:
        try:
            if resolved.is_relative_to(root.resolve()):
                return resolved
        except OSError:
            continue
    raise PathNotAllowedError("Caminho fora das pastas permitidas.")
