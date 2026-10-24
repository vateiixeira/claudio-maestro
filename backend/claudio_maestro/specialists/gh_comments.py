"""Sweep of PR comments through `gh`: the safety net for the webhook.

Every hour (and when the backend starts) the owner's new comments on the PRs opened by agents
are read with the `gh` already logged in on this machine and put in the same queue the webhook
feeds. The `comment_id` is the same as the webhook's, so a comment seen by both enters once.
Nothing here uses the Claude subscription.
"""

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from claudio_maestro import db
from claudio_maestro.specialists import store

logger = logging.getLogger(__name__)

GhRunner = Callable[[list[str]], Awaitable[tuple[int, str]]]

GH_TIMEOUT_SECONDS: float = 30
# The sweep reads a little before the last poll: our clock and GitHub's may differ by seconds,
# and re-reading a comment is harmless (`insert_comment` ignores a known `comment_id`).
CLOCK_MARGIN_SECONDS = 120

_PR_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)$")


async def run_gh(args: list[str]) -> tuple[int, str]:
    """Run `gh` with an argument list (no shell). Missing `gh` gives 127; a timeout, 124."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, ""
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), GH_TIMEOUT_SECONDS)
    except TimeoutError:
        await _kill(proc)
        return 124, ""
    except asyncio.CancelledError:
        # The sweep was cancelled (the app is stopping): no `gh` is left running behind it.
        await _kill(proc)
        raise
    return proc.returncode if proc.returncode is not None else 1, stdout.decode(
        "utf-8", errors="replace"
    )


async def _kill(proc: "asyncio.subprocess.Process") -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    await proc.wait()


def clean_pr_url(url: str) -> str:
    """The PR URL without fragment, query and trailing slash."""
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


def parse_pr_url(url: str) -> tuple[str, str, int] | None:
    match = _PR_URL.match(clean_pr_url(url))
    return (match[1], match[2], int(match[3])) if match else None


def parse_pages(text: str) -> list[dict[str, Any]]:
    """Items of a paginated `gh api` output.

    `--paginate` prints one JSON array per page (`[...][...]`) and `--slurp` wraps the pages in
    one more array (`[[...],[...]]`). Both shapes, and plain arrays, come out as one flat list.
    """
    decoder = json.JSONDecoder()
    items: list[dict[str, Any]] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return items
        value, index = decoder.raw_decode(text, index)
        _flatten(value, items)


def _flatten(value: Any, items: list[dict[str, Any]]) -> None:
    if isinstance(value, list):
        for entry in value:
            _flatten(entry, items)
    elif isinstance(value, dict):
        items.append(value)


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def _comment(
    item: dict[str, Any], *, kind: str, pr: store.Pr, pr_url: str, now: float
) -> store.PrComment | None:
    """A GitHub REST item as a queue entry; None when it is not something to queue."""
    body = item.get("body") or ""
    if kind == "review":
        if not body.strip() or not item.get("submitted_at"):
            return None
        created = item["submitted_at"]
    else:
        created = item["created_at"]
    line = (item.get("line") or item.get("original_line")) if kind == "line" else None
    return store.PrComment(
        comment_id=f"{kind}:{item['id']}",
        pr_url=pr_url,
        specialist_id=pr.specialist_id,
        author=(item.get("user") or {}).get("login") or "",
        body=body,
        path=item.get("path") if kind == "line" else None,
        line=line,
        html_url=item.get("html_url") or "",
        created_at=_epoch(created),
        received_at=int(now),
        status="queued",
        batch_at=None,
    )


async def _fetch(run: GhRunner, endpoint: str) -> list[dict[str, Any]]:
    code, out = await run(["api", endpoint, "--paginate", "--slurp"])
    if code != 0:
        raise RuntimeError(f"gh api {endpoint} exited with {code}")
    return parse_pages(out)


async def _sweep_pr(
    pr: store.Pr, *, owner: str, run: GhRunner, now: float
) -> tuple[str, list[store.PrComment]]:
    """('closed', []) when the PR is over, else ('open', new owner comments)."""
    pr_url = clean_pr_url(pr.url)
    parsed = parse_pr_url(pr_url)
    if parsed is None:
        raise ValueError(f"not a pull request URL: {pr.url}")
    org, repo, number = parsed

    code, out = await run(["pr", "view", pr_url, "--json", "state"])
    if code != 0:
        raise RuntimeError(f"gh pr view exited with {code}")
    if json.loads(out).get("state") in ("MERGED", "CLOSED"):
        return "closed", []

    base = f"repos/{org}/{repo}"
    sources = (
        ("issue", f"{base}/issues/{number}/comments"),
        ("line", f"{base}/pulls/{number}/comments"),
        ("review", f"{base}/pulls/{number}/reviews"),
    )
    since = (pr.polled_at if pr.polled_at is not None else pr.created_at) - CLOCK_MARGIN_SECONDS
    found: list[store.PrComment] = []
    for kind, endpoint in sources:
        for item in await _fetch(run, endpoint):
            author = (item.get("user") or {}).get("login") or ""
            if author.casefold() != owner.casefold():
                continue
            comment = _comment(item, kind=kind, pr=pr, pr_url=pr_url, now=now)
            if comment is not None and comment.created_at > since:
                found.append(comment)
    return "open", found


async def poll_comments(
    db_path: Path, *, owner: str | None, run_gh: GhRunner, now: float
) -> int:
    """Queue the owner's new comments on the open PRs. Returns how many entered the queue.

    Without an owner nothing is read: there is no one whose comments count, and an item
    without a login must not pass as the owner's.

    A PR that fails (network, `gh` signed out, odd output) is logged and left as it was, so the
    next sweep reads the same period again; the others carry on.
    """
    if not owner:
        return 0
    with closing(db.connect(db_path)) as conn:
        prs = store.open_prs(conn)

    queued = 0
    for pr in prs:
        try:
            state, comments = await _sweep_pr(pr, owner=owner, run=run_gh, now=now)
        except Exception:
            logger.warning("Comment sweep failed for %s", pr.url, exc_info=True)
            continue
        with closing(db.connect(db_path)) as conn, db.transaction(conn):
            if state == "closed":
                store.close_pr(conn, pr.url)
                continue
            queued += sum(store.insert_comment(conn, comment) for comment in comments)
            store.mark_pr_polled(conn, pr.url, int(now))
    return queued
