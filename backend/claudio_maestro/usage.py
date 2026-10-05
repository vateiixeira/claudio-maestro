"""How much of the subscription has been used (the same numbers as the CLI's /usage).

Reads the CLI login token from `<claude config>/.credentials.json` on every check and
sends it only to api.anthropic.com. The token is never stored, logged, sent to the
frontend or refreshed: refreshing rotates it and could log the CLI out.
"""

import asyncio
import json
import logging
import math
import time
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from claudio_maestro.config import claude_config_dir
from claudio_maestro.updates import current_version

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
TIMEOUT_SECONDS = 10
MAX_RESPONSE_BYTES = 1_000_000
# After a turn, check again only if the last attempt is at least this old.
TURN_REFRESH_MIN_SECONDS = 60
SEVERITIES = frozenset({"normal", "warning", "critical"})
_ORDER = {"session": 0, "weekly_all": 1, "weekly_scoped": 2}


@dataclass(frozen=True)
class UsageLimit:
    kind: str  # "session", "weekly_all" or "weekly_scoped"
    label: str  # "Sessão", "Semana", "Semana · Fable"
    percent: int  # 0 to 100
    severity: str  # "normal", "warning" or "critical"
    resets_at: float | None  # Unix seconds


class UsageCheckError(Exception):
    """The check failed. The message is short, in Portuguese, and never has the token."""


FetchUsage = Callable[[], Awaitable[list[UsageLimit]]]
Opener = Callable[..., Any]


def _unix(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _label(item: dict[str, Any]) -> str | None:
    kind = item.get("kind")
    if kind == "session":
        return "Sessão"
    if kind == "weekly_all":
        return "Semana"
    if kind == "weekly_scoped":
        scope = item.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        name = model.get("display_name") if isinstance(model, dict) else None
        if isinstance(name, str) and name.strip():
            return f"Semana · {name.strip()}"
    return None


def parse_usage(payload: object) -> list[UsageLimit]:
    """The known limits of the `limits` list: session first, then weekly, then per model."""
    if not isinstance(payload, dict) or not isinstance(payload.get("limits"), list):
        raise UsageCheckError("Resposta inesperada")
    limits: list[UsageLimit] = []
    for item in payload["limits"]:
        if not isinstance(item, dict):
            continue
        label = _label(item)
        percent = item.get("percent")
        if (
            label is None
            or isinstance(percent, bool)
            or not isinstance(percent, int | float)
            or not math.isfinite(percent)
        ):
            continue
        severity = item.get("severity")
        limits.append(
            UsageLimit(
                kind=item["kind"],
                label=label,
                percent=max(0, min(100, round(percent))),
                severity=severity if severity in SEVERITIES else "normal",
                resets_at=_unix(item.get("resets_at")),
            )
        )
    return sorted(limits, key=lambda limit: _ORDER[limit.kind])


def read_access_token(config_dir: Path, clock: Callable[[], float] = time.time) -> str:
    """The CLI login token, read now. Never keep the returned value."""
    try:
        data = json.loads((config_dir / ".credentials.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UsageCheckError("Credenciais do CLI não encontradas") from None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if not isinstance(token, str) or not token:
        raise UsageCheckError("Credenciais do CLI não encontradas")
    expires = oauth.get("expiresAt")
    if isinstance(expires, int | float) and not isinstance(expires, bool):
        if expires / 1000 <= clock():
            raise UsageCheckError("Login do CLI expirado")
    return token


def request_usage(
    config_dir: Path,
    opener: Opener = urllib.request.urlopen,
    clock: Callable[[], float] = time.time,
) -> list[UsageLimit]:
    """Blocking read of the usage. Every error is re-raised `from None`: the urllib
    exceptions carry the request, and with it the Authorization header."""
    token = read_access_token(config_dir, clock)
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": OAUTH_BETA,
            "Accept": "application/json",
            "User-Agent": f"claudio-maestro/{current_version()}",
        },
    )
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:  # before URLError: it is a subclass
        code = exc.code
        if code in (401, 403):
            raise UsageCheckError("Login do CLI expirado") from None
        raise UsageCheckError(f"Consulta de uso falhou (HTTP {code})") from None
    except (urllib.error.URLError, OSError):  # TimeoutError is an OSError
        raise UsageCheckError("Sem conexão com a Anthropic") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UsageCheckError("Resposta inesperada")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise UsageCheckError("Resposta inesperada") from None
    return parse_usage(payload)


def _get_usage() -> list[UsageLimit]:
    # Indirection so tests can block the network (see conftest).
    return request_usage(claude_config_dir())


async def fetch_usage() -> list[UsageLimit]:
    return await asyncio.to_thread(_get_usage)


class UsageChecker:
    """Keeps, in memory, the last usage read; publishes `app.usage` after every attempt."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        *,
        enabled: bool,
        fetch: FetchUsage = fetch_usage,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._publish = publish
        self.enabled = enabled
        self._fetch = fetch
        self._clock = clock
        self._limits: list[UsageLimit] = []
        self._fetched_at: float | None = None
        self._error: str | None = None
        self._attempted_at: float | None = None
        self._running = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "limits": [asdict(limit) for limit in self._limits] if self.enabled else [],
            "fetched_at": self._fetched_at,
            "error": self._error,
        }

    def wants_refresh(self) -> bool:
        """For the end of a turn: on, idle, and the last attempt is a minute old."""
        if not self.enabled or self._running:
            return False
        if self._attempted_at is None:
            return True
        return self._clock() - self._attempted_at >= TURN_REFRESH_MIN_SECONDS

    def _fail(self, message: str) -> None:
        if message != self._error:
            logger.warning("Consulta de uso da assinatura: %s", message)
        self._error = message

    async def refresh(self) -> None:
        if not self.enabled or self._running:
            return
        self._running = True
        self._attempted_at = self._clock()
        try:
            limits = await self._fetch()
        except UsageCheckError as exc:
            self._fail(str(exc))
        except Exception:
            logger.exception("Falha inesperada na consulta de uso")
            self._fail("Consulta de uso falhou")
        else:
            self._limits = limits
            self._fetched_at = self._clock()
            self._error = None
        finally:
            self._running = False
        self._publish({"session_id": None, "seq": 0, "type": "app.usage", "data": self.snapshot()})

    async def run_periodic(self, initial_delay: float, interval: float) -> None:
        if not self.enabled:
            return
        await asyncio.sleep(initial_delay)
        while True:
            await self.refresh()
            await asyncio.sleep(interval)
