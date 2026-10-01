"""Request guards (Host and Origin) and path validation."""

import json
import os
from collections.abc import Iterable
from pathlib import Path

from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from claudio_maestro.config import BACKEND_PORT, FRONTEND_PORT, LOCAL_HOSTNAMES

ALLOWED_HOSTS = frozenset(
    f"{name}:{port}" for name in LOCAL_HOSTNAMES for port in (FRONTEND_PORT, BACKEND_PORT)
)
ALLOWED_ORIGINS = frozenset(f"http://{name}:{FRONTEND_PORT}" for name in LOCAL_HOSTNAMES)
CUSTOM_HEADER = "x-maestro"
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
    - Every HTTP request to /api/ must carry `X-Maestro: 1`. Otherwise: 403.
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

        # Browsers only send a custom header cross-site after a CORS preflight,
        # which the app refuses, so this blocks <img>/<form> reads from other sites.
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/api/")
            and headers.get(CUSTOM_HEADER) != "1"
        ):
            await self._reject(scope, send, 403, "Cabeçalho do app ausente.")
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


MAX_BODY_BYTES = 60 * 1024 * 1024  # messages with images
BODY_TOO_LARGE = "A requisição passa do limite de 60 MB."


class BodySizeLimitMiddleware:
    """Refuse HTTP bodies over `max_bytes` with 413: by `Content-Length` before
    reading, and by counting what arrives when the header is missing (the app
    then sees a disconnect and whatever it tries to answer is dropped)."""

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes if self.max_bytes is not None else MAX_BODY_BYTES
        length = Headers(scope=scope).get("content-length")
        if length is not None:
            try:
                too_big = int(length) > limit
            except ValueError:
                too_big = True
            if too_big:
                await HostOriginMiddleware._reject(scope, send, 413, BODY_TOO_LARGE)
                return
            await self.app(scope, receive, send)
            return

        received = 0
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    await HostOriginMiddleware._reject(scope, send, 413, BODY_TOO_LARGE)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not rejected:
                await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except ClientDisconnect:
            if not rejected:
                raise


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
