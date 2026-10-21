"""Text format of the messages that come from the session terminal.

Two kinds reach the conversation as ordinary user messages, so the Claude sees them and the
JSONL history keeps them:

* a command run with the play button, written with the same tags the CLI uses for a `!`
  command (`<bash-input>`, `<bash-stdout>`, `<bash-stderr>`), plus a trailer comment with the
  exit code and the duration;
* snippets of terminal output attached to a message, as quoted blocks.

`conversation.py` recognizes both to show them as cards instead of raw text. The notes that
tell Claude what is missing from an output are in English, as the rest of what it reads.
"""

import re
from typing import Literal, TypedDict

EndedBy = Literal["done", "input", "shell-exit"]
NoteCode = Literal["truncated", "cleared", "input", "shell-exit", "empty"]

# What goes to Claude, keeping the end of the output.
RUN_OUTPUT_LIMIT = 102_400

NOTES: dict[NoteCode, str] = {
    "cleared": (
        "[The command cleared the terminal screen; output printed before the clear is not "
        "included.]"
    ),
    "truncated": "[…earlier output truncated; only the end is shown…]",
    "input": (
        "[The user typed into the terminal while this command was running, so output after "
        "that point is not included; it may still be running there.]"
    ),
    "shell-exit": (
        "[The terminal's shell exited before this command finished; the command may not have "
        "run to completion.]"
    ),
    "empty": "[No output was captured.]",
}

_OPENING_NOTES: tuple[NoteCode, ...] = ("cleared", "truncated")
_CLOSING_NOTES: tuple[NoteCode, ...] = ("input", "shell-exit", "empty")

ATTACH_HEADER = "<!-- attach: Terminal -->"


class TerminalRun(TypedDict):
    command: str
    output: str
    exit_code: int | None
    duration_ms: int | None
    notes: list[NoteCode]


# Output cleaning -------------------------------------------------------------

_CLEAR_SCREEN = re.compile(r"\x1b\[[23]J|\x1bc")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OTHER_ESCAPE = re.compile(r"\x1b.", re.DOTALL)


def clean_output(raw: str) -> tuple[str, bool]:
    """Plain text of what the terminal printed, and whether the screen was cleared.

    Keeps only what comes after the last screen clear, drops escape codes and, in a line
    redrawn with `\\r`, keeps the last non-empty piece.
    """
    cleared = False
    matches = list(_CLEAR_SCREEN.finditer(raw))
    if matches:
        raw = raw[matches[-1].end():]
        cleared = True
    text = raw.replace("\r\n", "\n")
    text = _OSC.sub("", text)
    text = _CSI.sub("", text)
    text = _OTHER_ESCAPE.sub("", text)
    lines: list[str] = []
    for line in text.split("\n"):
        if "\r" in line:
            pieces = [piece for piece in line.split("\r") if piece]
            line = pieces[-1] if pieces else ""
        lines.append(line.rstrip())
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines), cleared


# Run messages ----------------------------------------------------------------

_CLOSING_TAG = "</bash-"
_ESCAPED_CLOSING_TAG = "&lt;/bash-"
_RUN = re.compile(
    r"<bash-input>(?P<command>.*?)</bash-input>"
    r"<bash-stdout>(?P<stdout>.*?)</bash-stdout>"
    r"<bash-stderr>(?P<stderr>.*?)</bash-stderr>"
    r"(?:\n<!-- terminal: exit=(?P<exit>-?\d*) duration_ms=(?P<duration>\d*) -->)?",
    re.DOTALL,
)


def _escape(text: str) -> str:
    return text.replace(_CLOSING_TAG, _ESCAPED_CLOSING_TAG)


def _unescape(text: str) -> str:
    return text.replace(_ESCAPED_CLOSING_TAG, _CLOSING_TAG)


def format_run_message(
    command: str,
    raw_output: str,
    exit_code: int | None,
    duration_ms: int,
    ended_by: EndedBy,
) -> str:
    """The message the play button sends: the command, its output and how it ended."""
    output, cleared = clean_output(raw_output)
    truncated = len(output) > RUN_OUTPUT_LIMIT
    if truncated:
        output = output[-RUN_OUTPUT_LIMIT:]
    parts: list[str] = []
    if cleared:
        parts.append(NOTES["cleared"])
    if truncated:
        parts.append(NOTES["truncated"])
    if output:
        parts.append(output)
    if ended_by == "input":
        parts.append(NOTES["input"])
    elif ended_by == "shell-exit":
        parts.append(NOTES["shell-exit"])
    elif not output:
        parts.append(NOTES["empty"])
    body = _escape("\n".join(parts))
    code = "" if exit_code is None else str(exit_code)
    return (
        f"<bash-input>{_escape(command)}</bash-input>"
        f"<bash-stdout>{body}</bash-stdout><bash-stderr></bash-stderr>\n"
        f"<!-- terminal: exit={code} duration_ms={duration_ms} -->"
    )


def parse_terminal_message(text: str) -> TerminalRun | None:
    """Read back a run message: the three tags in one text, with or without the trailer.

    The CLI writes a `!` command as separate entries (`<bash-input>` alone, then the output
    tags), so what it saves never matches here; only a message in this module's format, which
    puts the three tags in one text, does.
    """
    match = _RUN.fullmatch(text.strip())
    if match is None:
        return None
    lines = _unescape(match.group("stdout")).split("\n")
    notes: list[NoteCode] = []
    for code in _OPENING_NOTES:
        if lines and lines[0] == NOTES[code]:
            notes.append(code)
            lines.pop(0)
    if lines:
        for code in _CLOSING_NOTES:
            if lines[-1] == NOTES[code]:
                notes.append(code)
                lines.pop()
                break
    output = "\n".join(lines)
    stderr = _unescape(match.group("stderr"))
    if stderr:
        output = f"{output}\n{stderr}" if output else stderr
    exit_code = match.group("exit")
    duration = match.group("duration")
    return {
        "command": _unescape(match.group("command")),
        "output": output,
        "exit_code": int(exit_code) if exit_code else None,
        "duration_ms": int(duration) if duration else None,
        "notes": notes,
    }


# Attachments -----------------------------------------------------------------

SNIPPET_TITLE = "Trecho do terminal"


def split_terminal_snippets(text: str) -> tuple[list[str], str]:
    """Terminal blocks a message opens with, and the user text that follows them."""
    lines = text.split("\n")
    snippets: list[str] = []
    i = 0
    while i < len(lines) and lines[i] == ATTACH_HEADER:
        i += 1
        body: list[str] = []
        while i < len(lines) and (lines[i].startswith("> ") or lines[i] == ">"):
            body.append(lines[i][2:])
            i += 1
        snippets.append("\n".join(body))
        if i + 1 < len(lines) and lines[i] == "" and lines[i + 1] == ATTACH_HEADER:
            i += 1
    if not snippets:
        return [], text
    if i < len(lines) and lines[i] == "":
        i += 1
    return snippets, "\n".join(lines[i:])


def terminal_title_text(text: str) -> str:
    """The text a session title is made from when `text` is its first message.

    A play-button run gives its command, and snippets of terminal output give the text the
    user wrote after them, or `SNIPPET_TITLE` when there is none. Any other text is unchanged.
    """
    run = parse_terminal_message(text)
    if run is not None:
        return run["command"]
    snippets, rest = split_terminal_snippets(text)
    if snippets:
        return rest if rest.strip() else SNIPPET_TITLE
    return text
