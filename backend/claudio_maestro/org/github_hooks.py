"""Receiver of GitHub webhooks for the comments of the agents' pull requests.

GitHub reaches this machine through a public proxy and an SSH tunnel, on a port of its
own (`MAESTRO_HOOKS_PORT`), apart from the app. That listener serves a single route,
`POST /github`, and only queues PR comments written by the owner on PRs of an agent.
The HMAC signature is the authentication, so none of the app's Host and Origin checks
apply here. The main API never leaves 127.0.0.1.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.store import PrComment

logger = logging.getLogger(__name__)

SECRET_FILE = "github-webhook.secret"
OWNER_KEY = "github_owner_login"
MAX_BODY_BYTES = 1024 * 1024
GRACEFUL_SHUTDOWN_SECONDS = 3
STOP_TIMEOUT_SECONDS = 5
_SIGNATURE_PREFIX = "sha256="


# Secret and owner ---------------------------------------------------------------


def read_secret(data_dir: Path) -> bytes | None:
    """The webhook secret, or None when missing or blank."""
    try:
        value = (Path(data_dir) / SECRET_FILE).read_bytes().strip()
    except OSError:
        return None
    return value or None


def write_secret(data_dir: Path, value: str) -> None:
    """Save the secret atomically with mode 600 (it is never readable by others)."""
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / SECRET_FILE
    temp = folder / f".{SECRET_FILE}.{os.getpid()}.tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def get_owner(conn: sqlite3.Connection) -> str | None:
    """The GitHub login whose comments are accepted."""
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (OWNER_KEY,)).fetchone()
    return row["value"] if row and row["value"] else None


def set_owner(conn: sqlite3.Connection, login: str) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (OWNER_KEY, login),
    )


# Signature and payloads ---------------------------------------------------------


@dataclass(frozen=True)
class IncomingComment:
    """External data only: ownership is assigned by the server after parsing."""
    comment_id: str
    pr_url: str
    author: str
    body: str
    path: str | None
    line: int | None
    html_url: str
    created_at: int



def verify_signature(secret: bytes, body: bytes, header: str | None) -> bool:
    """`header` is `sha256=<hex>` of the HMAC-SHA256 of `body` under `secret`."""
    if not header or not header.startswith(_SIGNATURE_PREFIX):
        return False
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header[len(_SIGNATURE_PREFIX):].encode())


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _epoch(value: Any) -> int:
    """GitHub's ISO time (`2026-10-23T12:00:00Z`) as epoch seconds; now when unreadable."""
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return int(datetime.fromisoformat(value).timestamp())
    return int(time.time())


def _build(
    comment_id: str, pr_url: Any, item: dict[str, Any], *, body: Any, created: Any,
    path: Any = None, line: Any = None,
) -> IncomingComment | None:
    login = _dict(item.get("user")).get("login")
    if not isinstance(pr_url, str) or not pr_url or not isinstance(login, str) or not login:
        return None
    html_url = item.get("html_url")
    return IncomingComment(
        comment_id=comment_id,
        pr_url=store.normalize_pr_url(pr_url),
        author=login,
        body=body if isinstance(body, str) else "",
        path=path if isinstance(path, str) and path else None,
        line=line if isinstance(line, int) and not isinstance(line, bool) else None,
        html_url=html_url if isinstance(html_url, str) else pr_url,
        created_at=_epoch(created),
    )


def parse_event(event: str, payload: dict[str, Any]) -> list[IncomingComment]:
    """The PR comments a delivery carries; empty for events and actions we do not use.

    Ownership and receipt time are filled in by the receiver. The `comment_id`
    formats (`issue:<id>`, `line:<id>`, `review:<id>`) are shared with the sweep that
    backs this webhook up, so both deduplicate against each other.
    """
    action = payload.get("action")
    if event == "issue_comment" and action == "created":
        issue = _dict(payload.get("issue"))
        pull_request = _dict(issue.get("pull_request"))
        if not pull_request:
            return []  # a plain issue, not a PR
        comment = _dict(payload.get("comment"))
        built = _build(
            f"issue:{comment.get('id')}", pull_request.get("html_url") or issue.get("html_url"),
            comment, body=comment.get("body"), created=comment.get("created_at"),
        )
    elif event == "pull_request_review_comment" and action == "created":
        comment = _dict(payload.get("comment"))
        built = _build(
            f"line:{comment.get('id')}", _dict(payload.get("pull_request")).get("html_url"),
            comment, body=comment.get("body"), created=comment.get("created_at"),
            path=comment.get("path"), line=comment.get("line") or comment.get("original_line"),
        )
    elif event == "pull_request_review" and action == "submitted":
        review = _dict(payload.get("review"))
        if not isinstance(review.get("body"), str) or not review["body"].strip():
            return []
        built = _build(
            f"review:{review.get('id')}", _dict(payload.get("pull_request")).get("html_url"),
            review, body=review["body"], created=review.get("submitted_at"),
        )
    else:
        return []
    return [built] if built is not None and not built.comment_id.endswith(":None") else []


# The receiver -------------------------------------------------------------------


async def _read_body(request: Request, limit: int) -> bytes | None:
    """The request body, or None as soon as it passes `limit` bytes."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def build_hooks_app(
    *,
    db_path: Path,
    data_dir: Path,
    is_agent_pr: Callable[[str], int | None],
    on_queued: Callable[[], None],
) -> Starlette:
    """The webhook app: `POST /github` and nothing else.

    `is_agent_pr(pr_url)` gives the id of the agent that opened the PR, or None.
    `on_queued()` runs (in the event loop) after a new comment entered the queue.
    """

    def queue(comments: list[IncomingComment]) -> int:
        """Store what comes from the owner on an agent's PR; how many are new."""
        with closing(db.connect(db_path)) as conn:
            owner = get_owner(conn)
            if not owner:
                return 0
            added = 0
            for comment in comments:
                if comment.author.casefold() != owner.casefold():
                    continue
                agent_id = is_agent_pr(comment.pr_url)
                if agent_id is None:
                    continue
                stored = PrComment(
                    **asdict(comment), agent_id=agent_id, received_at=int(time.time()),
                    status="queued", batch_at=None,
                )
                if store.insert_comment(conn, stored):
                    added += 1
            return added

    async def github(request: Request) -> Response:
        secret = read_secret(data_dir)
        if secret is None:
            return Response("Webhook sem segredo configurado.", status_code=503)
        body = await _read_body(request, MAX_BODY_BYTES)
        if body is None:
            return Response(status_code=413)
        if not verify_signature(secret, body, request.headers.get("x-hub-signature-256")):
            return Response(status_code=401)
        try:
            payload = _json(body)
        except ValueError:
            return Response(status_code=400)
        event = request.headers.get("x-github-event", "")
        comments = parse_event(event, payload)
        if comments:
            if await asyncio.to_thread(queue, comments):
                try:
                    on_queued()
                except Exception:
                    logger.exception("Falha ao avisar que há comentários de PR na fila")
        return Response(status_code=202)

    return Starlette(routes=[Route("/github", github, methods=["POST"])])


def _json(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("payload is not an object")
    return value


# The listener -------------------------------------------------------------------


class _HooksServer(uvicorn.Server):
    """A uvicorn server that leaves the process signals to the main one."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


_SERVERS: "weakref.WeakKeyDictionary[asyncio.Task[None], _HooksServer]" = weakref.WeakKeyDictionary()


def serve_hooks(app: Starlette, port: int) -> "asyncio.Task[None]":
    """Serve `app` on 127.0.0.1:`port` in the running loop; stop it with `stop_hooks`.

    Only loopback: the public proxy reaches it through an SSH tunnel. A failure to
    start (port in use) is logged and ends the task; it never takes the app down.
    """
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        # The logging of the main uvicorn is left as it is.
        log_config=None,
        log_level=None,
        lifespan="off",
        ws="none",
        server_header=False,
        # The proxy is public: a client holding a request open must not hold the app's
        # shutdown with it.
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = _HooksServer(config)

    async def run() -> None:
        try:
            await server.serve()
        except (Exception, SystemExit):
            # uvicorn exits the process when it cannot bind.
            logger.exception("O receptor de webhooks do GitHub não subiu na porta %s", port)

    task = asyncio.get_running_loop().create_task(run(), name="github-hooks")
    _SERVERS[task] = server
    return task


async def stop_hooks(task: "asyncio.Task[None]", timeout: float = STOP_TIMEOUT_SECONDS) -> None:
    """Ask the listener to exit and wait for its task; cancel it after `timeout` seconds.

    Cancelling the caller propagates (the listener is cancelled too).
    """
    server = _SERVERS.pop(task, None)
    if server is not None:
        server.should_exit = True
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            logger.warning("O receptor de webhooks não parou a tempo; cancelando.")
            task.cancel()
            await asyncio.wait({task})
    except asyncio.CancelledError:
        task.cancel()
        raise
