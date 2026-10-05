"""Whether a newer release of the app exists on GitHub (checked once a day).

The only request the app makes on its own to the internet: a read of the latest
release. Nothing about projects or conversations is sent.
"""

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib import metadata
from typing import Any

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/vateiixeira/claudio-maestro"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API_URL = "https://api.github.com/repos/vateiixeira/claudio-maestro/releases/latest"
TIMEOUT_SECONDS = 10
MAX_NOTES = 20_000
MAX_RESPONSE_BYTES = 2_000_000
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str  # "0.2.0", without the "v"
    url: str
    notes: str  # markdown, at most MAX_NOTES characters
    published_at: float | None  # Unix seconds


class ReleaseCheckError(Exception):
    """The check failed (network, rate limit, odd answer): keep the last result."""


FetchRelease = Callable[[], Awaitable[ReleaseInfo | None]]
Opener = Callable[..., Any]


def current_version() -> str:
    try:
        return metadata.version("claudio-maestro")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def parse_version(text: str) -> tuple[int, int, int] | None:
    """`X.Y.Z`, with an optional leading `v`; anything else (pre-releases too) is None."""
    match = _VERSION.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _unix(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_release(payload: object) -> ReleaseInfo:
    if not isinstance(payload, dict):
        raise ReleaseCheckError("resposta inesperada do GitHub")
    tag = payload.get("tag_name")
    version = parse_version(tag) if isinstance(tag, str) else None
    if version is None:
        raise ReleaseCheckError(f"tag de release inválida: {tag!r}")
    url = payload.get("html_url")
    if not isinstance(url, str) or not url.startswith(f"{REPO_URL}/"):
        url = RELEASES_URL
    body = payload.get("body")
    notes = body[:MAX_NOTES] if isinstance(body, str) else ""
    return ReleaseInfo(
        version=".".join(str(part) for part in version),
        url=url,
        notes=notes,
        published_at=_unix(payload.get("published_at")),
    )


def _request_latest(opener: Opener = urllib.request.urlopen) -> ReleaseInfo | None:
    """Blocking read of the latest release; None when the repository has none (404)."""
    request = urllib.request.Request(
        LATEST_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"claudio-maestro/{current_version()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:  # before URLError: it is a subclass
        if exc.code == 404:
            return None
        raise ReleaseCheckError(f"GitHub respondeu {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:  # TimeoutError is an OSError
        raise ReleaseCheckError(str(exc)) from exc
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ReleaseCheckError("resposta do GitHub não é JSON") from exc
    return parse_release(payload)


def _get_latest() -> ReleaseInfo | None:
    # Indirection so tests can replace the network call (see conftest).
    return _request_latest()


async def fetch_latest_release() -> ReleaseInfo | None:
    return await asyncio.to_thread(_get_latest)


class UpdateChecker:
    """Keeps, in memory, the latest release seen and whether it is newer than this one."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        *,
        enabled: bool,
        fetch: FetchRelease = fetch_latest_release,
        current: Callable[[], str] = current_version,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._publish = publish
        self.enabled = enabled
        self._fetch = fetch
        self._current = current()
        self._clock = clock
        self._latest: ReleaseInfo | None = None
        self._checked_at: float | None = None

    def _available(self) -> bool:
        if self._latest is None:
            return False
        latest = parse_version(self._latest.version)
        current = parse_version(self._current)
        return latest is not None and current is not None and latest > current

    def state(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "current": self._current,
            "available": self._available(),
            "latest": asdict(self._latest) if self._latest is not None else None,
            "checked_at": self._checked_at,
            "releases_url": RELEASES_URL,
        }

    async def check(self) -> None:
        if not self.enabled:
            return
        try:
            latest = await self._fetch()
        except ReleaseCheckError as exc:
            logger.warning("Não foi possível verificar se há versão nova: %s", exc)
            return
        except Exception:
            logger.exception("Falha ao verificar se há versão nova")
            return
        self._checked_at = self._clock()
        changed = latest != self._latest
        self._latest = latest
        if changed:
            self._publish(
                {"session_id": None, "seq": 0, "type": "app.update", "data": self.state()}
            )

    async def run_periodic(self, initial_delay: float, interval: float) -> None:
        if not self.enabled:
            return
        await asyncio.sleep(initial_delay)
        while True:
            await self.check()
            await asyncio.sleep(interval)
