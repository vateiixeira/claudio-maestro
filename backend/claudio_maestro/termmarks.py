"""OSC 133 marks for the session terminal.

The shell prints three marks (A: prompt, C: command start, D: command end
with the exit code), each carrying a per-terminal nonce so that program output
cannot forge them. `OscTracker` pulls the valid marks out of the PTY stream and
reports them as events; everything else passes through as text.
"""

import re
from typing import Literal

MarkEvent = (
    tuple[Literal["text"], str]
    | tuple[Literal["prompt", "start"], None]
    | tuple[Literal["end"], int]
)

# Largest incomplete mark kept between `feed` calls. Past this the escape is
# not a mark (a real one is about 30 characters) and goes out as text.
MAX_PENDING = 256

_HEADER = "\x1b]133;"


class OscTracker:
    """Extracts nonce-authenticated OSC 133 marks from a PTY output stream."""

    def __init__(self, nonce: str) -> None:
        self._mark = re.compile(
            r"\x1b\]133;(?:([AC]);|D;(-?\d+);)" + re.escape(nonce) + r"\x07"
        )
        self._pending = ""
        self._busy = False
        self._ready = False

    @property
    def busy(self) -> bool:
        """True between a `start` and the next `end`."""
        return self._busy

    @property
    def ready(self) -> bool:
        """True once the first prompt mark was seen."""
        return self._ready

    def feed(self, chunk: str) -> list[MarkEvent]:
        data = self._pending + chunk
        self._pending = ""
        events: list[MarkEvent] = []
        text: list[str] = []

        def flush_text() -> None:
            if text:
                events.append(("text", "".join(text)))
                text.clear()

        pos = 0
        size = len(data)
        while pos < size:
            esc = data.find("\x1b", pos)
            if esc == -1:
                text.append(data[pos:])
                break
            if esc > pos:
                text.append(data[pos:esc])
            match = self._mark.match(data, esc)
            if match is not None:
                flush_text()
                self._handle(match, events)
                pos = match.end()
                continue
            if self._may_complete(data, esc):
                self._pending = data[esc:]
                break
            text.append("\x1b")
            pos = esc + 1
        flush_text()
        return events

    def _may_complete(self, data: str, esc: int) -> bool:
        """True when data[esc:] is an incomplete mark that more input could finish."""
        rest_len = len(data) - esc
        if rest_len > MAX_PENDING:
            return False
        if data.find("\x1b", esc + 1) != -1 or data.find("\x07", esc) != -1:
            return False
        rest = data[esc:]
        if rest_len < len(_HEADER):
            return _HEADER.startswith(rest)
        return rest.startswith(_HEADER)

    def _handle(self, match: re.Match[str], events: list[MarkEvent]) -> None:
        kind, code = match.group(1), match.group(2)
        if kind == "A":
            self._ready = True
            events.append(("prompt", None))
        elif kind == "C":
            self._busy = True
            events.append(("start", None))
        elif self._busy:
            # An end with no start before it (the shell's first D) is dropped.
            self._busy = False
            events.append(("end", int(code)))


def bash_rcfile() -> str:
    """Rcfile for `bash --rcfile <file> -i`; the nonce comes in MAESTRO_OSC_NONCE."""
    return (
        "[ -f ~/.bashrc ] && . ~/.bashrc\n"
        "__maestro_nonce=$MAESTRO_OSC_NONCE; unset MAESTRO_OSC_NONCE\n"
        "__maestro_osc() { local c=$?; "
        r"printf '\e]133;D;%s;%s\a\e]133;A;%s\a' "
        '"$c" "$__maestro_nonce" "$__maestro_nonce"; return $c; }\n'
        'PROMPT_COMMAND="__maestro_osc${PROMPT_COMMAND:+;$PROMPT_COMMAND}"\n'
        r"PS0='\e]133;C;'"
        '"$__maestro_nonce"'
        r"'\a'"
        "\n"
    )


_ZSHENV = """\
__maestro_zdotdir=$ZDOTDIR
__maestro_nonce=$MAESTRO_OSC_NONCE; unset MAESTRO_OSC_NONCE
ZDOTDIR=$HOME
[ -f "$HOME/.zshenv" ] && . "$HOME/.zshenv"
ZDOTDIR=$__maestro_zdotdir
unset __maestro_zdotdir
"""

_ZSHRC = r"""
unset ZDOTDIR
[ -f "$HOME/.zshrc" ] && . "$HOME/.zshrc"
autoload -Uz add-zsh-hook
__maestro_precmd() {
  local c=$?
  printf '\e]133;D;%s;%s\a\e]133;A;%s\a' "$c" "$__maestro_nonce" "$__maestro_nonce"
  return $c
}
__maestro_preexec() { printf '\e]133;C;%s\a' "$__maestro_nonce"; }
add-zsh-hook precmd __maestro_precmd
add-zsh-hook preexec __maestro_preexec
precmd_functions=(__maestro_precmd ${precmd_functions:#__maestro_precmd})
# PROMPT_SP prints "%" plus spaces and carriage returns before the precmd hooks, that is,
# inside the output of the command, and erases its last line when it has no final newline.
unsetopt prompt_sp
"""


def zsh_rcfiles() -> dict[str, str]:
    """Files for a temporary ZDOTDIR (nonce in MAESTRO_OSC_NONCE, ZDOTDIR set to it).

    `.zshenv` takes the nonce out of the environment and runs the user's
    `.zshenv`; `.zshrc` restores the default ZDOTDIR, runs the user's `.zshrc`
    and then registers the marks. `__maestro_precmd` goes first in
    `precmd_functions` so that `$?` is still the command's exit code.
    """
    return {".zshenv": _ZSHENV, ".zshrc": _ZSHRC.lstrip("\n")}
