"""Which shell commands a specialist's session may run without the user's ok.

The app, not the skill text, enforces this. A specialist session runs with a
permission callback that asks `classify` about every Bash command: "allow" runs it,
"ask" turns it into a pending permission for the user.

The threat model is the agent's mistake, not an adversary (the projects and
everything the agents read belong to the user). So the matching below catches the
shapes a distracted agent produces (compound commands, `git -C`, `env`, global git
options, force refspecs) but is not a sandbox: it does not expand variables, aliases,
scripts or command substitution.

Known limits (a distracted agent rarely produces these; only a sandbox would stop them):
- `gh api` calls to the merge endpoint, or any other program that merges or pushes.
- `--repo <x>` on `git push` consumes the next word, so the remote then looks like a
  refspec.
- `push.default=upstream` (or a branch whose upstream is main) sends a push without
  refspec from a feature branch to main.
- `sudo`, `xargs`, `eval`, `find -exec` and other wrappers that run a command.
- Variable and `$(...)` expansion, aliases and scripts: only the typed text is read.
"""

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from claudio_maestro.gitinfo import GitError, run_git

# Actions that reach outside the machine. They ask when the autonomy is "ask".
OUTWARD_DEFAULTS = (
    "git push",
    "gh pr create",
    "gh pr merge",
    "gh issue comment",
    "gh issue close",
    "gh release",
)
# Actions that ask in every autonomy. The other "always" cases (a push to the default
# branch, a forced push) depend on the command and on the repository, so they are code.
ALWAYS_DEFAULTS = ("gh pr merge",)

_FALLBACK_PROTECTED = ("main", "master")
_SEPARATORS = frozenset("\n;|&()`")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_PREFIX_COMMANDS = frozenset({"command", "exec", "nohup", "time"})
# Shell keywords that can stand in front of (or alone beside) a command.
_KEYWORDS = frozenset(
    {"if", "then", "else", "elif", "fi", "while", "until", "do", "done", "{", "}", "!"}
)
_REDIRECTION = re.compile(r"^(?:\d*|&)[<>]+[&|]?")
_MAX_NESTING = 3

# Global options that take the next word as their value.
_GIT_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
)
_GH_VALUE_OPTIONS = frozenset({"-R", "--repo"})
_ENV_VALUE_OPTIONS = frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"})
_TIMEOUT_VALUE_OPTIONS = frozenset({"-s", "--signal", "-k", "--kill-after"})
_PUSH_VALUE_OPTIONS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})


@dataclass(frozen=True)
class GitContext:
    """What `classify` needs to know about the repository the command runs in."""

    default_branch: str | None
    current_branch: str | None


async def read_git_context(work_dir: Path) -> GitContext:
    """The remote's default branch and the checked-out branch; None when unknown."""
    default = await _git_line(work_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if default is not None:
        default = default.removeprefix("origin/") or None
    current = await _git_line(work_dir, "rev-parse", "--abbrev-ref", "HEAD")
    return GitContext(default_branch=default, current_branch=current)


async def _git_line(work_dir: Path, *args: str) -> str | None:
    try:
        code, out, _ = await run_git(work_dir, *args)
    except (GitError, OSError):
        return None
    line = out.strip()
    return line if code == 0 and line else None


def ask_rules(outward: list[str], always: list[str]) -> list[str]:
    """`Bash(<prefix>:*)` for every outward and always pattern, defaults first."""
    rules: list[str] = []
    for pattern in (*OUTWARD_DEFAULTS, *ALWAYS_DEFAULTS, *outward, *always):
        rule = f"Bash({pattern}:*)"
        if rule not in rules:
            rules.append(rule)
    return rules


def classify(
    command: str,
    *,
    autonomy: str,
    outward: list[str],
    always: list[str],
    git: GitContext,
) -> Literal["allow", "ask"]:
    """"ask" when the user must approve the command, "allow" when it may just run."""
    segments = _segments(command)
    always_patterns = [_words(p) for p in (*ALWAYS_DEFAULTS, *always)]
    if any(_matches(seg, pattern) for seg in segments for pattern in always_patterns):
        return "ask"
    if any(seg[:2] == ["git", "push"] and _push_needs_ok(seg[2:], git) for seg in segments):
        return "ask"
    if autonomy == "ask":
        outward_patterns = [_words(p) for p in (*OUTWARD_DEFAULTS, *outward)]
        if any(_matches(seg, pattern) for seg in segments for pattern in outward_patterns):
            return "ask"
    return "allow"


def _matches(segment: list[str], pattern: list[str]) -> bool:
    return bool(pattern) and segment[: len(pattern)] == pattern


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _split_unquoted(command: str) -> list[str]:
    """Cuts at `&&`, `||`, `;`, `|`, `&`, line breaks, parentheses and backticks that are
    not inside quotes, so text such as `echo "git push"` stays one argument."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quote != "'":
            current.append(char)
            escaped = True
        elif quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "'\"":
            current.append(char)
            quote = char
        elif char == "&" and _is_redirection_ampersand(command, index):
            current.append(char)
        elif char in _SEPARATORS:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _is_redirection_ampersand(command: str, index: int) -> bool:
    """`&` in `2>&1`, `>&2` or `&>file` belongs to a redirection, not to a separator."""
    after = command[index + 1 : index + 2]
    before = command[index - 1 : index] if index else ""
    return before in ("<", ">") or (after == ">" and before != "&")


def _drop_redirections(words: list[str]) -> list[str]:
    """Removes `2>&1`, `>file`, `> file`, `&> file`... so they are not taken as arguments."""
    kept: list[str] = []
    skip_target = False
    for word in words:
        if skip_target:
            skip_target = False
            continue
        match = _REDIRECTION.match(word)
        if match:
            skip_target = match.end() == len(word)
        else:
            kept.append(word)
    return kept


def _segments(command: str, depth: int = 0) -> list[list[str]]:
    """Every simple command in `command` as a clean word list (git/gh options removed)."""
    result: list[list[str]] = []
    for part in _split_unquoted(command):
        words = _clean(_drop_redirections(_words(part)))
        if not words:
            continue
        result.append(words)
        if depth < _MAX_NESTING and words[0] in _SHELLS:
            script = _shell_script(words)
            if script is not None:
                result.extend(_segments(script, depth + 1))
    return result


def _shell_script(words: list[str]) -> str | None:
    """The script of `bash -c <script>` (also `-lc`, `-ec`...)."""
    for index, word in enumerate(words[1:], start=1):
        if not word.startswith("-"):
            return None
        if not word.startswith("--") and "c" in word[1:]:
            return words[index + 1] if index + 1 < len(words) else None
    return None


def _clean(words: list[str]) -> list[str]:
    """Drops `NAME=value` prefixes, `env`/`command`/... wrappers and, for git and gh,
    the global options that come before the subcommand."""
    words = list(words)
    while words:
        head = words[0]
        if _ASSIGNMENT.match(head) or head in _KEYWORDS:
            words.pop(0)
        elif head == "timeout":
            words.pop(0)
            _skip_options(words, _TIMEOUT_VALUE_OPTIONS)
            if words:
                words.pop(0)  # the duration
        elif head == "nice":
            words.pop(0)
            _skip_options(words, frozenset({"-n", "--adjustment"}))
        elif _program(head) == "env":
            words.pop(0)
            while words and (_ASSIGNMENT.match(words[0]) or words[0].startswith("-")):
                option = words.pop(0)
                if option in _ENV_VALUE_OPTIONS and words:
                    words.pop(0)
        elif head in _PREFIX_COMMANDS:
            words.pop(0)
            while words and words[0].startswith("-"):
                words.pop(0)
        else:
            break
    if not words:
        return words
    program = _program(words[0])
    if program == "git":
        return ["git", *_strip_options(words[1:], _GIT_VALUE_OPTIONS)]
    if program == "gh":
        return ["gh", *_strip_options(words[1:], _GH_VALUE_OPTIONS)]
    return [program, *words[1:]]


def _skip_options(words: list[str], value_options: frozenset[str]) -> None:
    while words and words[0].startswith("-"):
        if words.pop(0) in value_options and words:
            words.pop(0)


def _program(word: str) -> str:
    return os.path.basename(word) if "/" in word else word


def _strip_options(words: list[str], value_options: frozenset[str]) -> list[str]:
    index = 0
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in value_options else 1
    return words[index:]


def _push_needs_ok(args: list[str], git: GitContext) -> bool:
    """A `git push` that must ask in any autonomy: forced, aimed at the default branch,
    or without refspec while the current branch is the default one."""
    protected = {b for b in (git.default_branch, *_FALLBACK_PROTECTED) if b}
    positional: list[str] = []
    options_ended = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if options_ended or not arg.startswith("-") or arg == "-":
            positional.append(arg)
        elif arg == "--":
            options_ended = True
        elif arg in ("--force", "--mirror", "--all") or arg.startswith("--force-with-lease"):
            return True
        elif arg in _PUSH_VALUE_OPTIONS:
            index += 1
        elif not arg.startswith("--") and "f" in arg[1:]:
            return True
    refspecs = positional[1:]
    if not refspecs:
        return git.current_branch is None or git.current_branch in protected
    for refspec in refspecs:
        if refspec.startswith("+"):
            return True
        destination = refspec.rsplit(":", 1)[-1].removeprefix("refs/heads/")
        if ":" not in refspec and destination in ("HEAD", "@"):
            destination = git.current_branch or "main"
        if destination in protected:
            return True
    return False
