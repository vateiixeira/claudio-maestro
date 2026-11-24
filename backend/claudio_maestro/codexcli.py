"""Local Codex CLI metadata and updates, using the same login and catalog as the CLI."""

import asyncio
import json
import re
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claudio_maestro.agent.base import AgentError
from claudio_maestro.agent.codex_transport import (
    CodexTransport,
    codex_binary,
    list_codex_models,
)
from claudio_maestro.claudecli import (
    UPDATE_TIMEOUT,
    run_update_command,
    run_version_command,
)
from claudio_maestro.updates import parse_version

LATEST_URL = "https://api.github.com/repos/openai/codex/releases/latest"
DATA_TTL = 120
VERSION_TTL = 600
RELEASE_TTL = 3600
CODEX_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
_METADATA_ERROR = "Não foi possível consultar o Codex CLI."
_QUOTA_ERROR = "Não foi possível consultar os limites do Codex."
_PLAN_NAMES = {
    "free": "Free", "go": "Go", "plus": "Plus", "pro": "Pro", "prolite": "Pro Lite",
    "promax": "Pro Max", "team": "Team", "business": "Business", "enterprise": "Enterprise",
    "edu": "Edu", "edu_plus": "Edu Plus", "edu_pro": "Edu Pro",
}


class CodexUpdateUnavailable(Exception):
    """The installed CLI cannot be updated right now."""


def installed_version(output: str | None) -> str | None:
    match = re.fullmatch(r"codex-cli (\d+\.\d+\.\d+(?:-[\w.-]+)?)", (output or "").strip())
    return match[1] if match else None


def fetch_latest_version() -> str | None:
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "claudio-maestro",
    })
    with urllib.request.urlopen(request, timeout=5) as response:
        data = json.loads(response.read(512_000))
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if isinstance(tag, str) and tag.startswith("rust-v") and parse_version(tag[6:]):
        return tag[6:]
    return None


def _window_label(duration: object, fallback: str) -> str:
    if duration == 10_080:
        return "Semana"
    if type(duration) is int and duration > 0:
        if duration % 1440 == 0:
            return f"{duration // 1440} dias"
        if duration % 60 == 0:
            return f"{duration // 60} h"
        return f"{duration} min"
    return fallback


def usage_limits(result: dict[str, Any]) -> list[dict[str, Any]]:
    grouped = result.get("rateLimitsByLimitId")
    grouped = grouped if isinstance(grouped, dict) else {}
    # Older versions return only the single main bucket. The multi-bucket form
    # includes model-specific limits in addition to the main Codex quota.
    main = grouped.get("codex") or result.get("rateLimits")
    buckets = [(None, main), *((key, value) for key, value in grouped.items() if key != "codex")]
    limits = []
    for key, snapshot in buckets:
        if not isinstance(snapshot, dict):
            continue
        for window_key, kind, fallback in (("primary", "session", "Sessão"),
                                            ("secondary", "weekly_all", "Semana")):
            window = snapshot.get(window_key)
            if not isinstance(window, dict) or type(window.get("usedPercent")) is not int:
                continue
            percent = max(0, min(100, window["usedPercent"]))
            label = _window_label(window.get("windowDurationMins"), fallback)
            if key is not None:
                name = snapshot.get("limitName")
                label = f"{label} · {name if isinstance(name, str) and name else key}"
                kind = "weekly_scoped"
            reset = window.get("resetsAt")
            severity = "critical" if percent >= 90 else "warning" if percent >= 75 else "normal"
            limits.append({"kind": kind, "label": label, "percent": percent, "severity": severity,
                           "resets_at": reset if type(reset) is int and reset > 0 else None})
    return limits


class CodexCli:
    def __init__(
        self,
        cwd: Path,
        publish: Callable[[dict[str, Any]], None],
        fetch_latest: Callable[[], str | None] | None = None,
    ) -> None:
        self._cwd = cwd
        self._publish = publish
        self._fetch_latest = fetch_latest
        self._refresh_lock = asyncio.Lock()
        self._update_lock = asyncio.Lock()
        self._path: str | None = None
        self._version: str | None = None
        self._latest: str | None = None
        self._usage: dict[str, Any] | None = None
        self._auth: str | None = None
        self._identity: tuple[object, ...] | None = None
        self._requires_auth: bool | None = None
        self._default_model: str | None = None
        self._default_effort: str | None = None
        self._models: list[dict[str, Any]] = []
        self._error: str | None = None
        self._metadata_at = self._version_at = self._release_at = float("-inf")

    def models(self) -> list[dict[str, Any]]:
        return [dict(model) for model in self._models]

    def state(self, *, models_refreshed: bool = False) -> dict[str, Any]:
        version = parse_version(self._version.split("-", 1)[0]) if self._version else None
        latest = parse_version(self._latest) if self._latest else None
        update_available = bool(latest and version and (
            latest > version or (latest == version and "-" in (self._version or ""))
        ))
        return {
            "installed": self._path is not None, "version": self._version, "latest": self._latest,
            "can_update": self._version is not None, "update_available": update_available,
            "auth": self._auth, "requires_auth": self._requires_auth, "usage": self._usage,
            "default_model": self._default_model, "default_effort": self._default_effort,
            "models_refreshed": models_refreshed, "error": self._error,
        }

    async def _check_latest(self) -> None:
        self._release_at = time.monotonic()
        try:
            self._latest = await asyncio.to_thread(self._fetch_latest or fetch_latest_version) or self._latest
        except (OSError, ValueError):
            pass  # A failed check keeps the last confirmed release.

    async def refresh(self, *, force: bool = False, check_latest: bool = True) -> dict[str, Any]:
        async with self._refresh_lock:
            path = codex_binary()
            now = time.monotonic()
            changed = path != self._path
            if path is None:
                if changed:
                    self._set_models([])
                    self._auth = self._usage = self._identity = self._requires_auth = None
                    self._default_model = self._default_effort = None
                self._path = self._version = self._error = None
                return self.state()
            if changed or force or now - self._version_at >= VERSION_TTL:
                version = installed_version(await asyncio.to_thread(run_version_command, path))
                changed = changed or version != self._version
                self._path, self._version, self._version_at = path, version, now
            latest_task = None
            if check_latest and (force or now - self._release_at >= RELEASE_TTL):
                latest_task = asyncio.create_task(self._check_latest())
            try:
                refreshed = False
                if changed or force or now - self._metadata_at >= DATA_TTL:
                    self._metadata_at = now
                    refreshed = await self._refresh_metadata()
                if latest_task is not None:
                    await latest_task
                return self.state(models_refreshed=refreshed)
            finally:
                if latest_task is not None and not latest_task.done():
                    latest_task.cancel()

    async def _refresh_metadata(self) -> bool:
        try:
            async with CodexTransport(self._cwd) as transport:
                models, config, account = await asyncio.gather(
                    list_codex_models(transport),
                    transport.call("config/read", {"includeLayers": False}),
                    transport.call("account/read", {"refreshToken": False}),
                    return_exceptions=True,
                )
                await self._refresh_account(transport, account)
        except (AgentError, OSError):
            self._error = _METADATA_ERROR
            self._auth = self._usage = self._identity = self._requires_auth = None
            return False
        if isinstance(models, Exception):
            self._error = "Não foi possível atualizar a lista de modelos do Codex."
            return False
        self._error = None
        raw_config = config.get("config") if isinstance(config, dict) else None
        settings = raw_config if isinstance(raw_config, dict) else {}
        model = settings.get("model")
        catalog_default = next((m for m in models if m.get("isDefault")), {})
        self._default_model = model if isinstance(model, str) and model else catalog_default.get("value")
        selected = next((m for m in models if m["value"] == self._default_model), {})
        effort = settings.get("model_reasoning_effort")
        self._default_effort = effort if effort in CODEX_EFFORTS else selected.get("defaultEffort")
        self._set_models([{**m, "isDefault": m["value"] == self._default_model} for m in models])
        return True

    def _set_models(self, models: list[dict[str, Any]]) -> None:
        if models != self._models:
            self._models = models
            self._publish({"session_id": None, "seq": 0, "type": "models.updated",
                           "data": {"provider": "codex", "models": self.models()}})

    async def _refresh_account(self, transport: CodexTransport, response: object) -> None:
        raw = response.get("account") if isinstance(response, dict) else None
        account = raw if isinstance(raw, dict) else {}
        auth = account.get("type")
        self._auth = auth if isinstance(auth, str) else None
        requires_auth = response.get("requiresOpenaiAuth") if isinstance(response, dict) else None
        self._requires_auth = requires_auth if isinstance(requires_auth, bool) else None
        if auth != "chatgpt":
            self._usage = self._identity = None
            return
        # Identifiers are only used in memory to avoid displaying a previous account's limits.
        identity = (response.get("userId") or account.get("email"), account.get("workspaceName"))
        plan = account.get("planType")
        plan_label = _PLAN_NAMES.get(plan, plan.replace("_", " ").title()) if (
            isinstance(plan, str) and plan != "unknown"
        ) else None
        try:
            limits = usage_limits(await transport.call("account/rateLimits/read"))
        except AgentError:
            last = self._usage if identity[0] and identity == self._identity and self._usage else {}
            self._usage = {"enabled": True, "plan": plan_label, "limits": last.get("limits", []),
                           "fetched_at": last.get("fetched_at"), "error": _QUOTA_ERROR}
        else:
            self._usage = {"enabled": True, "plan": plan_label, "limits": limits,
                           "fetched_at": time.time(), "error": None}
        self._identity = identity

    async def update(self) -> dict[str, Any]:
        if self._update_lock.locked():
            raise CodexUpdateUnavailable("Já há uma atualização do Codex em andamento.")
        async with self._update_lock:
            async with self._refresh_lock:
                path = codex_binary()
                before = installed_version(await asyncio.to_thread(run_version_command, path)) if path else None
                if not path or not before:
                    raise CodexUpdateUnavailable("O Codex CLI não está disponível para atualizar.")
                result = await run_update_command([path, "update"], UPDATE_TIMEOUT)
            state = await self.refresh(force=True)
            after = state["version"]
            ok = result.returncode == 0 and after is not None
            if not ok:
                message = "O Codex CLI não confirmou a atualização. Confira `codex update` no terminal."
            elif after == before:
                message = f"O Codex CLI continua na versão {after}."
            else:
                message = f"Codex CLI atualizado para {after}."
            return {**state, "ok": ok, "before": before, "after": after, "message": message}
