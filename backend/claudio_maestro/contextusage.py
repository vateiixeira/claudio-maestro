"""Normalizes the CLI's `get_context_usage()` response into the route's `breakdown`."""

from __future__ import annotations

from typing import Any

# Display order of the categories by kind: used (largest first), then the rest.
_KIND_ORDER = {"used": 0, "buffer": 1, "free": 2, "deferred": 3}
_BUFFER_NAMES = {"autocompact buffer", "compact buffer"}


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _tokens(item: dict[str, Any]) -> int | None:
    tokens = _integer(item.get("tokens"))
    return tokens if tokens is not None and tokens > 0 else None


def _kind(item: dict[str, Any], name: str) -> str:
    kind = item.get("kind")
    if isinstance(kind, str) and kind in _KIND_ORDER:
        return kind
    lowered = name.strip().lower()
    if lowered == "free space":
        return "free"
    if lowered in _BUFFER_NAMES:
        return "buffer"
    if item.get("isDeferred") is True or lowered.endswith("(deferred)"):
        return "deferred"
    return "used"


def _categories(value: Any) -> list[dict[str, Any]]:
    result = []
    for item in _items(value):
        name, tokens = _text(item.get("name")), _tokens(item)
        if name is not None and tokens is not None:
            result.append({"name": name, "tokens": tokens, "kind": _kind(item, name)})
    # `sorted` is stable: ties keep the order the CLI sent.
    return sorted(result, key=lambda c: (_KIND_ORDER[c["kind"]], -c["tokens"]))


def _ranked(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda e: -e["tokens"])


def _mcp_tools(value: Any) -> list[dict[str, Any]]:
    result = []
    for item in _items(value):
        name, tokens = _text(item.get("name")), _tokens(item)
        if name is None or tokens is None:
            continue
        server = _text(item.get("serverName"))
        result.append(
            {
                "name": name,
                "server": server or "",
                "tokens": tokens,
                "loaded": item.get("isLoaded") is not False,
            }
        )
    return _ranked(result)


def _named(value: Any, key: str, field: str) -> list[dict[str, Any]]:
    result = []
    for item in _items(value):
        name, tokens = _text(item.get(key)), _tokens(item)
        if name is not None and tokens is not None:
            result.append({field: name, "tokens": tokens})
    return _ranked(result)


def context_breakdown(usage: Any) -> dict[str, Any] | None:
    """Breakdown of a `get_context_usage()` response; None when it is unusable.

    Same validity and percent base as `sessions.context_from_sdk`: the percent is over
    `rawMaxTokens` (else `maxTokens`) and is capped at 100 (`total_tokens` keeps the real
    value). Lists that are missing or have the wrong type come out empty."""
    if not isinstance(usage, dict):
        return None
    total = _integer(usage.get("totalTokens"))
    limit = _integer(usage.get("rawMaxTokens")) or _integer(usage.get("maxTokens"))
    if total is None or total < 0 or limit is None or limit <= 0:
        return None
    skills = usage.get("skills")
    return {
        "model": _text(usage.get("model")),
        "total_tokens": total,
        "max_tokens": limit,
        # Same rule as `sessions._percent` (replicated: sessions will import this module).
        "percent": round(min(total / limit * 100, 100.0), 1),
        "categories": _categories(usage.get("categories")),
        "mcp_tools": _mcp_tools(usage.get("mcpTools")),
        "memory_files": _named(usage.get("memoryFiles"), "path", "path"),
        "agents": _named(usage.get("agents"), "agentType", "name"),
        "skills": _named(
            skills.get("skillFrontmatter") if isinstance(skills, dict) else None, "name", "name"
        ),
    }
