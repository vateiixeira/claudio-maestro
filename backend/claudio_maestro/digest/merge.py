"""Merge of the agent's answer with the stored digest. Pure.

Done phases already stored are frozen: the answer may only update the open phase,
close it and add new ones. The model alone never sets the plan seal.
"""

from collections import Counter
from pathlib import Path
from typing import Any

from claudio_maestro.digest.prompt import (
    ITEM_LIMIT,
    MAX_ITEMS,
    MAX_PHASES,
    PHASE_KINDS,
    PHASE_STATUSES,
    SHORT_LIMIT,
    TITLE_LIMIT,
)
from claudio_maestro.digest.store import Digest
from claudio_maestro.plans import PlanProgress

FOLDED_TITLE = "Fases anteriores"


class DigestFormatError(ValueError):
    def __init__(self) -> None:
        super().__init__("Resposta do agente fora do formato.")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    items = [_clip(i.strip(), ITEM_LIMIT) for i in raw if isinstance(i, str) and i.strip()]
    return items[:MAX_ITEMS]


def _ref(raw: Any, roots: list[Path]) -> str | None:
    if not isinstance(raw, str) or not raw.startswith("/"):
        return None
    try:
        resolved = Path(raw).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    for root in roots:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return str(resolved)
        except (OSError, RuntimeError):
            continue
    return None


def clean_phase(raw: Any, roots: list[Path]) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
        return None
    title = raw["title"].strip()
    if not title:
        return None
    return {
        "title": _clip(title, TITLE_LIMIT),
        "kind": raw.get("kind") if raw.get("kind") in PHASE_KINDS else "other",
        "status": raw.get("status") if raw.get("status") in PHASE_STATUSES else "open",
        "done": _items(raw.get("done")),
        "pending": _items(raw.get("pending")),
        "ref": _ref(raw.get("ref"), roots),
    }


def _key(title: str) -> str:
    return title.strip().casefold()


def _fold(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(phases) <= MAX_PHASES:
        return phases
    extra = len(phases) - MAX_PHASES + 1
    folded = phases[:extra]
    items: list[str] = []
    for p in folded:
        if p["title"] == FOLDED_TITLE:
            items.extend(p.get("done") or [])
        else:
            items.append(_clip(p["title"], ITEM_LIMIT))
    summary = {
        "title": FOLDED_TITLE, "kind": "other", "status": "done",
        "done": items[-MAX_ITEMS:],
        "pending": [], "ref": None,
    }
    return [summary, *phases[extra:]]


def merge_digest(
    old: Digest | None,
    result: Any,
    *,
    session_id: str,
    cursor: str | None,
    read_at: int,
    plan_path: str | None,
    plan: PlanProgress | None,
    roots: list[Path],
) -> Digest:
    if not isinstance(result, dict) or not isinstance(result.get("phases"), list):
        raise DigestFormatError()
    frozen = [p for p in (old.phases if old else []) if p.get("status") == "done"]
    # Each frozen phase swallows at most one phase of the answer (multiset by title),
    # so a new phase that repeats a frozen title survives as the tail.
    pending_frozen = Counter(_key(p["title"]) for p in frozen)
    tail = []
    for raw in result["phases"]:
        cleaned = clean_phase(raw, roots)
        if cleaned is None:
            continue
        key = _key(cleaned["title"])
        if pending_frozen[key] > 0:
            pending_frozen[key] -= 1
            continue
        tail.append(cleaned)
    for p in tail[:-1]:
        p["status"] = "done"
    phases = _fold([*frozen, *tail])

    short_raw = result.get("short")
    short = _clip(short_raw.strip(), SHORT_LIMIT) if isinstance(short_raw, str) else ""
    evidence = result.get("plan_evidence")
    by_evidence = result.get("plan_completed") is True and isinstance(evidence, str) \
        and bool(evidence.strip())
    by_file = plan is not None and plan.total > 0 and plan.done == plan.total
    kept = old is not None and old.plan_done and old.plan_ref == plan_path

    return Digest(
        session_id=session_id,
        cursor=cursor,
        read_at=read_at,
        short=short or (old.short if old else None),
        phases=phases,
        plan_done=kept or by_file or by_evidence,
        plan_ref=plan_path,
        error=None,
        error_at=None,
    )
