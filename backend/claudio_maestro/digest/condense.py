"""What the digest agent reads: the transcript entries after the cursor, as short text.

Pure: the transcript is read by the caller (history.read_transcript_at).
"""

import os
from dataclasses import dataclass
from typing import Any

from claudio_maestro.conversation import COMPACT_SUMMARY_PREFIX, classify_user_text
from claudio_maestro.history import Transcript

USER_LIMIT = 4000
CLAUDE_LIMIT = 1500
BASH_LIMIT = 200
DEFAULT_BUDGET = 60_000
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"})
SUBAGENT_TOOLS = frozenset({"Task", "Agent"})


@dataclass
class Slice:
    messages: list[Any]
    # uuid of the last message of the slice; the old cursor when nothing is new.
    cursor: str | None
    # False when the old cursor was not in the file (compacted or rewritten).
    cursor_found: bool


@dataclass
class Condensed:
    text: str
    # Condensable entries (prompts, Claude texts, tool calls, compaction summaries).
    count: int
    # Files read or edited, absolute, first appearance order, no repeats.
    paths: list[str]


def entries_after(transcript: Transcript, cursor: str | None) -> Slice:
    messages = transcript.messages
    if cursor is None:
        start, found = 0, True
    else:
        index = next((i for i, m in enumerate(messages) if m.uuid == cursor), None)
        if index is not None:
            start, found = index + 1, True
        else:
            compacts = [i for i, m in enumerate(messages) if m.uuid in transcript.compact_uuids]
            start, found = (compacts[-1] if compacts else 0), False
    rest = messages[start:]
    return Slice(rest, rest[-1].uuid if rest else cursor, found)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _relative(path: str, cwd: str | None) -> str:
    if cwd and (path == cwd or path.startswith(cwd.rstrip(os.sep) + os.sep)):
        return os.path.relpath(path, cwd)
    return path


def tool_line(name: str, tool_input: Any, cwd: str | None) -> str:
    inp = tool_input if isinstance(tool_input, dict) else {}
    if name in FILE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path")
        return f"[{name}] {_relative(path, cwd)}" if isinstance(path, str) else f"[{name}]"
    if name == "Bash" and isinstance(inp.get("command"), str):
        return f"[Bash] {_clip(' '.join(inp['command'].split()), BASH_LIMIT)}"
    if name in SUBAGENT_TOOLS:
        kind = inp.get("subagent_type") or "agente"
        return f"[{name}] {kind}: {inp.get('description') or ''}".rstrip()
    if name == "Skill" and isinstance(inp.get("skill"), str):
        return f"[Skill] {inp['skill']}"
    if name in ("Grep", "Glob") and isinstance(inp.get("pattern"), str):
        return f"[{name}] {inp['pattern']}"
    return f"[{name}]"


def _user_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            b["text"] for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ]
    return []


def _lines(
    messages: list[Any], tool_results: dict[str, dict[str, Any]], cwd: str | None
) -> tuple[list[tuple[str, str]], list[str]]:
    lines: list[tuple[str, str]] = []  # (kind, text); kind "user" is never omitted
    paths: dict[str, None] = {}
    for message in messages:
        body = message.message if isinstance(message.message, dict) else {}
        content = body.get("content")
        if message.type == "user":
            for raw in _user_texts(content):
                if raw.lstrip().startswith(COMPACT_SUMMARY_PREFIX):
                    lines.append(("other", "[Compactação] " + _clip(raw.strip(), USER_LIMIT)))
                    continue
                kept, _notice = classify_user_text(raw)
                if kept:
                    lines.append(("user", "[Você] " + _clip(kept, USER_LIMIT)))
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                value = block["text"].strip()
                if value:
                    lines.append(("other", "[Claude] " + _clip(value, CLAUDE_LIMIT)))
            elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                name, inp = block["name"], block.get("input")
                line = tool_line(name, inp, cwd)
                result = tool_results.get(block.get("id") or "", {})
                if result.get("is_error"):
                    line += " (falhou)"
                lines.append(("other", line))
                if name in FILE_TOOLS and isinstance(inp, dict):
                    path = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(path, str):
                        paths[path] = None
    return lines, list(paths)


def _fit(lines: list[tuple[str, str]], budget: int) -> str:
    sizes = [len(text) + 1 for _, text in lines]
    if sum(sizes) <= budget:
        return "\n".join(text for _, text in lines)
    users = [i for i, (kind, _) in enumerate(lines) if kind == "user"]
    others = [i for i, (kind, _) in enumerate(lines) if kind != "user"]
    keep: set[int] = set()
    if sum(sizes[i] for i in users) <= budget:
        keep.update(users)
        room = budget - sum(sizes[i] for i in users)
        head = 0
        for i in others:
            if head + sizes[i] > room // 2:
                break
            keep.add(i)
            head += sizes[i]
        tail = 0
        for i in reversed(others):
            if i in keep or tail + sizes[i] > room - head:
                break
            keep.add(i)
            tail += sizes[i]
    else:
        # The prompts alone blow the budget: keep the newest ones that fit (at least one).
        used = 0
        for i in reversed(users):
            if keep and used + sizes[i] > budget:
                break
            keep.add(i)
            used += sizes[i]
    out: list[str] = []
    omitted = 0
    for i, (_, text) in enumerate(lines):
        if i in keep:
            if omitted:
                out.append(f"[… {omitted} entradas omitidas …]")
                omitted = 0
            out.append(text)
        else:
            omitted += 1
    if omitted:
        out.append(f"[… {omitted} entradas omitidas …]")
    return "\n".join(out)


def condense(
    messages: list[Any],
    tool_results: dict[str, dict[str, Any]],
    cwd: str | None,
    budget: int = DEFAULT_BUDGET,
) -> Condensed:
    lines, paths = _lines(messages, tool_results, cwd)
    return Condensed(text=_fit(lines, budget), count=len(lines), paths=paths)
