"""How much of the subscription has been used (the same numbers as the CLI's /usage).

Reads the CLI login token from `<claude config>/.credentials.json` on every check and
sends it only to api.anthropic.com. The token is never stored, logged, sent to the
frontend or refreshed: refreshing rotates it and could log the CLI out.
"""

import asyncio
import json
import logging
import math
import os
import re
import secrets
import stat
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
# Bounds for the `Retry-After` of an HTTP 429, in seconds.
RETRY_AFTER_MIN_SECONDS = 60
RETRY_AFTER_MAX_SECONDS = 3600
# Wait after the first 429 without `Retry-After`; doubles on each consecutive 429.
RATE_LIMIT_BASE_SECONDS = 300
RATE_LIMIT_MAX_SECONDS = 1800
# The cache of the last good reading is tiny; refuse anything bigger.
CACHE_MAX_BYTES = 64 * 1024
CACHE_MAX_LABEL_CHARS = 200
# A cached `fetched_at` may be at most this far ahead of the clock (clock drift).
CACHE_MAX_FUTURE_SECONDS = 300
SEVERITIES = frozenset({"normal", "warning", "critical"})
_ORDER = {"session": 0, "weekly_all": 1, "weekly_scoped": 2}
_PLAN_NAMES = {
    "max": "Max",
    "pro": "Pro",
    "team": "Team",
    "enterprise": "Enterprise",
    "free": "Free",
}
_TIER_MULTIPLIER = re.compile(r"_(\d+)x$")


@dataclass(frozen=True)
class UsageLimit:
    kind: str  # "session", "weekly_all" or "weekly_scoped"
    label: str  # "Sessão", "Semana", "Semana · Fable"
    percent: int  # 0 to 100
    severity: str  # "normal", "warning" or "critical"
    resets_at: float | None  # Unix seconds


@dataclass(frozen=True)
class UsageReport:
    limits: list[UsageLimit]
    plan: str | None  # "Max 20x", "Pro"... Never has the token.


class UsageCheckError(Exception):
    """The check failed. The message is short, in Portuguese, and never has the token.

    `rate_limited` is True for an HTTP 429; `retry_after` is the wait (seconds) the
    server asked for on it, if any."""

    def __init__(
        self, message: str, *, retry_after: float | None = None, rate_limited: bool = False
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.rate_limited = rate_limited


FetchUsage = Callable[[], Awaitable[UsageReport]]
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


def plan_label(subscription_type: object, rate_limit_tier: object) -> str | None:
    """The plan name for the menu, such as "Max 20x". Neither field is a secret."""
    if not isinstance(subscription_type, str) or not subscription_type.strip():
        return None
    name = _PLAN_NAMES.get(subscription_type.strip().lower()) or subscription_type.strip().capitalize()
    if isinstance(rate_limit_tier, str) and (match := _TIER_MULTIPLIER.search(rate_limit_tier)):
        return f"{name} {match.group(1)}x"
    return name


def _retry_after(headers: Any) -> int | None:
    """Seconds from a `Retry-After` header, clamped. Only whole seconds are accepted: an
    HTTP date or anything else gives None."""
    try:
        value = headers.get("Retry-After") if headers is not None else None
    except Exception:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not (value.isascii() and value.isdigit()) or len(value) > 9:
        return None
    return max(RETRY_AFTER_MIN_SECONDS, min(RETRY_AFTER_MAX_SECONDS, int(value)))


def read_credentials(
    config_dir: Path, clock: Callable[[], float] = time.time
) -> tuple[str, str | None]:
    """The CLI login token and the plan name, read now. Never keep the token."""
    try:
        data = json.loads((config_dir / ".credentials.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UsageCheckError("Credenciais do CLI não encontradas") from None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    # Only visible ASCII: a newline or a space would break the header, and the resulting
    # error would carry the token in its message.
    if not isinstance(token, str) or not token:
        raise UsageCheckError("Credenciais do CLI não encontradas")
    if not (token.isascii() and token.isprintable() and " " not in token):
        raise UsageCheckError("Credenciais do CLI não encontradas")
    expires = oauth.get("expiresAt")
    if isinstance(expires, int | float) and not isinstance(expires, bool):
        if expires / 1000 <= clock():
            raise UsageCheckError("Token do CLI vencido; renova no próximo uso do CLI")
    return token, plan_label(oauth.get("subscriptionType"), oauth.get("rateLimitTier"))


def read_access_token(config_dir: Path, clock: Callable[[], float] = time.time) -> str:
    """The CLI login token, read now. Never keep the returned value."""
    return read_credentials(config_dir, clock)[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would carry the request (and the token) to another host: refuse it.
    The 30x then surfaces as an `HTTPError`."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def request_usage(
    config_dir: Path,
    opener: Opener = _opener.open,
    clock: Callable[[], float] = time.time,
) -> UsageReport:
    """Blocking read of the usage. No error is raised from inside an `except`: the
    urllib exceptions carry the request, and with it the Authorization header, and the
    original would stay in `__context__`."""
    token, plan = read_credentials(config_dir, clock)
    request = urllib.request.Request(
        USAGE_URL,
        headers={
            "anthropic-beta": OAUTH_BETA,
            "Accept": "application/json",
            "User-Agent": f"claudio-maestro/{current_version()}",
        },
    )
    # Never copied to another request by a redirect (and the opener refuses them anyway).
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    failure: str | None = None
    retry_after: int | None = None
    rate_limited = False
    raw = b""
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:  # before URLError: it is a subclass
        if exc.code in (401, 403):
            failure = "Login do CLI expirado"
        else:
            failure = f"Consulta de uso falhou (HTTP {exc.code})"
            if exc.code == 429:
                rate_limited = True
                retry_after = _retry_after(exc.headers)
    except (urllib.error.URLError, OSError):  # TimeoutError is an OSError
        failure = "Sem conexão com a Anthropic"
    except Exception:  # e.g. ValueError("Invalid header value b'Bearer ...'")
        failure = "Consulta de uso falhou"
    if failure is not None:
        raise UsageCheckError(failure, retry_after=retry_after, rate_limited=rate_limited)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise UsageCheckError("Resposta inesperada")
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if payload is None:
        raise UsageCheckError("Resposta inesperada")
    return UsageReport(parse_usage(payload), plan)


def _get_usage() -> UsageReport:
    # Indirection so tests can block the network (see conftest).
    return request_usage(claude_config_dir())


async def fetch_usage() -> UsageReport:
    return await asyncio.to_thread(_get_usage)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _limit_from_cache(item: object) -> UsageLimit | None:
    if not isinstance(item, dict):
        return None
    kind, label = item.get("kind"), item.get("label")
    percent, severity, resets_at = item.get("percent"), item.get("severity"), item.get("resets_at")
    if (
        kind not in _ORDER
        or not isinstance(label, str)
        or not label
        or len(label) > CACHE_MAX_LABEL_CHARS
        or not _is_number(percent)
        or not 0 <= percent <= 100
        or severity not in SEVERITIES
        or not (resets_at is None or _is_number(resets_at))
    ):
        return None
    return UsageLimit(kind, label, round(percent), severity, resets_at)


def _read_regular_file(path: Path) -> bytes | None:
    """Up to CACHE_MAX_BYTES + 1 bytes of a regular file; None for a symlink, a FIFO, a
    directory or any other kind. Neither follows a link nor blocks on a FIFO."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise
    except OSError:  # ELOOP for a symlink, or anything else
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks: list[bytes] = []
        remaining = CACHE_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def load_cache(path: Path, now: float) -> tuple[list[UsageLimit], str | None, float] | None:
    """The last good reading kept on disk, or None when there is none or it is not valid.
    Limits that already reset are dropped: their percentage no longer holds."""
    try:
        raw = _read_regular_file(path)
    except FileNotFoundError:
        return None
    except OSError:
        logger.debug("Cache de uso ilegível")
        return None
    if raw is None:
        logger.debug("Cache de uso ignorado: não é um arquivo comum")
        return None
    try:
        if len(raw) > CACHE_MAX_BYTES:
            raise ValueError("too big")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("limits"), list):
            raise ValueError("shape")
        plan, fetched_at = data.get("plan"), data.get("fetched_at")
        if (
            not (plan is None or isinstance(plan, str))
            or not _is_number(fetched_at)
            or not 0 < fetched_at <= now + CACHE_MAX_FUTURE_SECONDS
        ):
            raise ValueError("fields")
        limits = [_limit_from_cache(item) for item in data["limits"]]
        if any(limit is None for limit in limits):
            raise ValueError("limit")
    except ValueError:
        logger.debug("Cache de uso ignorado: conteúdo inválido")
        return None
    kept = [
        limit
        for limit in limits
        if limit is not None and (limit.resets_at is None or limit.resets_at > now)
    ]
    return kept, plan, float(fetched_at)


def write_cache(path: Path, limits: list[UsageLimit], plan: str | None, fetched_at: float) -> None:
    """Atomic, 600. Never raises: a failure only costs the cache."""
    payload = json.dumps(
        {"limits": [asdict(limit) for limit in limits], "plan": plan, "fetched_at": fetched_at}
    )
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp, path)
    except Exception as exc:
        # Only the class name: keep paths and messages out of the log.
        logger.warning("Não foi possível guardar a última leitura de uso (%s)", type(exc).__name__)
        try:
            os.unlink(temp)
        except OSError:
            pass


class UsageChecker:
    """Keeps the last usage read (in memory and in `cache_path`); publishes `app.usage`
    after every attempt. Backs off after an HTTP 429."""

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        *,
        enabled: bool,
        fetch: FetchUsage = fetch_usage,
        clock: Callable[[], float] = time.time,
        cache_path: Path | None = None,
    ) -> None:
        self._publish = publish
        self.enabled = enabled
        self._fetch = fetch
        self._clock = clock
        self._limits: list[UsageLimit] = []
        self._plan: str | None = None
        self._fetched_at: float | None = None
        self._error: str | None = None
        self._attempted_at: float | None = None
        self._running = False
        self._blocked_until: float | None = None
        self._rate_limited_count = 0
        self._cache_path = cache_path
        if enabled and cache_path is not None and (cached := load_cache(cache_path, clock())):
            self._limits, self._plan, self._fetched_at = cached

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "limits": [asdict(limit) for limit in self._limits] if self.enabled else [],
            "fetched_at": self._fetched_at,
            "error": self._error,
            "plan": self._plan if self.enabled else None,
        }

    def _blocked(self) -> bool:
        return self._blocked_until is not None and self._clock() < self._blocked_until

    def wants_refresh(self) -> bool:
        """For the end of a turn: on, idle, not rate limited, and the last attempt is a
        minute old."""
        if not self.enabled or self._running or self._blocked():
            return False
        if self._attempted_at is None:
            return True
        return self._clock() - self._attempted_at >= TURN_REFRESH_MIN_SECONDS

    def _fail(self, message: str, detail: str | None = None) -> None:
        if message != self._error:
            logger.warning(
                "Consulta de uso da assinatura: %s%s", message, f" ({detail})" if detail else ""
            )
        self._error = message

    def _back_off(self, retry_after: float | None) -> None:
        self._rate_limited_count += 1
        if retry_after is not None:
            wait = float(retry_after)
        else:
            wait = min(
                RATE_LIMIT_BASE_SECONDS * 2 ** (self._rate_limited_count - 1), RATE_LIMIT_MAX_SECONDS
            )
        self._blocked_until = self._clock() + wait
        logger.warning("Consulta de uso da assinatura limitada (HTTP 429): espera de %.0f s", wait)

    async def refresh(self) -> None:
        if not self.enabled or self._running or self._blocked():
            return
        self._running = True
        self._attempted_at = self._clock()
        try:
            report = await self._fetch()
        except UsageCheckError as exc:
            self._fail(str(exc))
            if exc.rate_limited:
                self._back_off(exc.retry_after)
        except Exception as exc:
            # Only the class name: the message of an unexpected error may have the token.
            self._fail("Consulta de uso falhou", type(exc).__name__)
        else:
            self._limits = report.limits
            self._plan = report.plan
            self._fetched_at = self._clock()
            self._error = None
            self._blocked_until = None
            self._rate_limited_count = 0
            if self._cache_path is not None:
                write_cache(self._cache_path, self._limits, self._plan, self._fetched_at)
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
