"""Which shell commands a specialist's session may run without the user's ok.

The app, not the skill text, enforces this. A specialist session runs with a
permission callback that asks `classify` about every shell command a tool runs (Bash,
Monitor...): "allow" runs it, "ask" turns it into a pending permission for the user.

A push is judged by the folder it runs in, which the command line itself must name
(`cd <dir> && git push`, `git -C <dir> push`): the folder the CLI keeps between Bash
calls is unknown here. So a push without a destination branch and without a folder in
the command always asks; one that names its destination branch is judged by the name.

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
- A relative `cd`/`-C` resolves against the session's folder, though the CLI may have
  kept another one from an earlier call; `CDPATH` is not followed.
"""

import os
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
# Environment variables that name the repository instead of the folder.
_GIT_LOCATION_VARIABLES = frozenset({"GIT_DIR", "GIT_WORK_TREE"})


@dataclass(frozen=True)
class GitContext:
    """What `classify` needs to know about the repository the command runs in."""

    default_branch: str | None
    current_branch: str | None


GitReader = Callable[[Path], Awaitable[GitContext]]


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


async def classify(
    command: str,
    *,
    autonomy: str,
    outward: list[str],
    always: list[str],
    work_dir: Path,
    read_git: GitReader | None = None,
) -> Literal["allow", "ask"]:
    """"ask" when the user must approve the command, "allow" when it may just run.

    `work_dir` is the session's folder. A push is judged by the folder it runs in: the
    one a `cd` earlier in the same command line, `git -C` or both name. A push without
    a destination branch and without a folder in the command asks, because the folder
    the CLI keeps between calls is unknown. The repository is only read for a push."""
    segments = _segments(command, _Place.start(work_dir))
    always_patterns = [_words(p) for p in (*ALWAYS_DEFAULTS, *always)]
    if any(_matches(seg.words, pattern) for seg in segments for pattern in always_patterns):
        return "ask"
    if autonomy == "ask":
        outward_patterns = [_words(p) for p in (*OUTWARD_DEFAULTS, *outward)]
        if any(_matches(seg.words, pattern) for seg in segments for pattern in outward_patterns):
            return "ask"
    contexts = _Contexts(work_dir, read_git or read_git_context)
    for seg in segments:
        if seg.words[:2] == ["git", "push"] and await _push_needs_ok(seg, contexts):
            return "ask"
    return "allow"


def _matches(segment: list[str], pattern: list[str]) -> bool:
    return bool(pattern) and segment[: len(pattern)] == pattern


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


# Splitting -------------------------------------------------------------------------------


def _split_unquoted(command: str) -> list[tuple[str, str]]:
    """Cuts at `&&`, `||`, `;`, `|`, `&`, line breaks, parentheses and backticks that are
    not inside quotes, so text such as `echo "git push"` stays one argument. Each part
    comes with the separator that ends it ("" for the last one)."""
    parts: list[tuple[str, str]] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        index += 1
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
        elif char == "&" and _is_redirection_ampersand(command, index - 1):
            current.append(char)
        elif char in _SEPARATORS:
            separator = char
            if char in "&|" and command[index : index + 1] == char:
                separator = char * 2
                index += 1
            elif char == "|" and command[index : index + 1] == "&":
                index += 1  # `|&` pipes stderr too: still a pipe
            parts.append(("".join(current), separator))
            current = []
        else:
            current.append(char)
    parts.append(("".join(current), ""))
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


# Where each command runs -------------------------------------------------------------------


@dataclass(frozen=True)
class _Place:
    """The folder of the shell at some point of the command line.

    `folder`: the folder, when the command named it (a `cd`); None when unknown.
    `base`: what a relative path resolves against: `folder`, or the session's folder
    before any `cd`; None once the folder is unknown.
    `conditional`: the `cd` that set `folder` may not have run (it came after `&&` or
    inside an `if`/loop body), so the folder only holds along the same `&&` chain."""

    folder: Path | None
    base: Path | None
    conditional: bool = False

    @staticmethod
    def start(work_dir: Path) -> "_Place":
        return _Place(folder=None, base=work_dir)

    @property
    def moved(self) -> bool:
        return self.folder is not None or self.base is None

    def to(self, target: str | None) -> "_Place":
        """The place after `cd <target>` (None: a target that cannot be read)."""
        folder = _resolve(self.base, target)
        return _Place(folder=folder, base=folder) if folder is not None else _UNKNOWN

    def through(self, separator: str) -> "_Place":
        """The place for the next command, past `separator`."""
        if not self.moved:
            return self
        if separator in _UNSURE_AFTER:
            return _UNKNOWN
        if self.conditional and separator not in ("&&", "|"):
            return _UNKNOWN
        return self


_UNKNOWN = _Place(folder=None, base=None)
# Past these, an earlier `cd` may not hold any more: the end of a subshell or of a
# command substitution, a command sent to the background, or `||` (what follows runs
# when something before it failed, maybe the `cd` itself).
_UNSURE_AFTER = frozenset({")", "`", "&", "||"})
# A `cd` with one of these before or after it may not change the folder of the commands
# that follow (a pipeline element runs in a subshell; `||` and `&` may skip it or run it
# apart).
_CD_UNSURE_BEFORE = frozenset({"|", "||", "&", "`", ")"})
_CD_UNSURE_AFTER = frozenset({"|", "||", "&", "`", "("})
# Shell keywords whose body may not run.
_CONDITIONAL_KEYWORDS = frozenset({"then", "else", "elif", "do"})
_CD_COMMANDS = frozenset({"cd", "pushd"})
_UNREADABLE_PATH = re.compile(r"[$`*?\[\]{}]")
_HEREDOC = re.compile(r"^\d*<<(?!<)")


def _resolve(base: Path | None, target: str | None) -> Path | None:
    """The folder `target` names, from `base`; None when it cannot be known from the
    text (variables, globs, `cd -`, `~user`) or is relative to an unknown folder."""
    if target is None or target == "-" or _UNREADABLE_PATH.search(target):
        return None
    if target == "~" or target.startswith("~/"):
        return Path.home() / target[2:]
    if target.startswith("~"):
        return None
    path = Path(target)
    if path.is_absolute():
        return path
    return base / path if base is not None else None


def _cd_target(program: str, args: list[str]) -> str | None:
    """The folder of `cd`/`pushd` arguments; `~` without one (as the shell does). None
    for `pushd +N`/`-N`, which turn the folder stack."""
    if program == "pushd" and any(arg[:1] in "+-" for arg in args):
        return None
    index = 0
    while index < len(args) and args[index].startswith("-") and args[index] != "-":
        if args[index] == "--":
            index += 1
            break
        index += 1
    if index >= len(args):
        return "~"
    return args[index]


@dataclass
class _Segment:
    """One simple command: its words (git/gh options removed) and the folder it runs in
    (None when the command line does not say)."""

    words: list[str]
    folder: Path | None


@dataclass
class _Cleaned:
    words: list[str]
    # `git -C`/`env -C` folders, in order.
    chdirs: list[str] = field(default_factory=list)
    # `--git-dir`, `--work-tree`, `GIT_DIR=`...: the repository is named some other way.
    elsewhere: bool = False
    # A shell keyword whose body may not run came first.
    conditional: bool = False
    # `!` came first: what follows runs when this command failed.
    negated: bool = False


def _segments(command: str, place: _Place, depth: int = 0) -> list[_Segment]:
    """Every simple command in `command`, with the folder it runs in."""
    result: list[_Segment] = []
    before = ""
    # Past a here-document its lines are text, not commands: no folder is trusted then.
    lost = False
    for part, after in _split_unquoted(command):
        raw = _words(part)
        cleaned = _clean(_drop_redirections(raw))
        words = cleaned.words
        if words:
            if lost:
                place = _UNKNOWN
            elif words[0] in _CD_COMMANDS:
                if (
                    before in _CD_UNSURE_BEFORE
                    or after in _CD_UNSURE_AFTER
                    or cleaned.negated
                ):
                    place = _UNKNOWN
                else:
                    moved = place.to(_cd_target(words[0], words[1:]))
                    conditional = (
                        moved.folder is not None
                        and (cleaned.conditional or before == "&&" or place.conditional)
                    )
                    place = _Place(moved.folder, moved.base, conditional)
            elif words[0] == "popd":
                place = _UNKNOWN
            result.append(_Segment(words, _folder_of(place, cleaned)))
            if depth < _MAX_NESTING and words[0] in _SHELLS:
                script = _shell_script(words)
                if script is not None:
                    # A child shell starts where this one is; its `cd` stays inside it.
                    result.extend(_segments(script, place, depth + 1))
        lost |= any(_HEREDOC.match(word) for word in raw)
        place = _UNKNOWN if lost else place.through(after)
        before = after
    return result


def _folder_of(place: _Place, cleaned: _Cleaned) -> Path | None:
    """The folder a command runs in: the shell's, moved by `git -C`/`env -C` (each
    relative one from the previous, as git does)."""
    if cleaned.elsewhere:
        return None
    folder, base = place.folder, place.base
    for target in cleaned.chdirs:
        if target == "":
            continue  # git ignores an empty -C
        folder = base = _resolve(base, target)
        if folder is None:
            return None
    return folder


def _shell_script(words: list[str]) -> str | None:
    """The script of `bash -c <script>` (also `-lc`, `-ec`...)."""
    for index, word in enumerate(words[1:], start=1):
        if not word.startswith("-"):
            return None
        if not word.startswith("--") and "c" in word[1:]:
            return words[index + 1] if index + 1 < len(words) else None
    return None


def _clean(words: list[str]) -> _Cleaned:
    """Drops `NAME=value` prefixes, `env`/`command`/... wrappers and, for git and gh,
    the global options that come before the subcommand, keeping what tells where the
    command runs."""
    words = list(words)
    cleaned = _Cleaned(words=[])
    while words:
        head = words[0]
        if _ASSIGNMENT.match(head):
            cleaned.elsewhere |= head.split("=", 1)[0] in _GIT_LOCATION_VARIABLES
            words.pop(0)
        elif head in _KEYWORDS:
            cleaned.conditional |= head in _CONDITIONAL_KEYWORDS
            cleaned.negated |= head == "!"
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
                if _ASSIGNMENT.match(option):
                    cleaned.elsewhere |= option.split("=", 1)[0] in _GIT_LOCATION_VARIABLES
                elif option in ("-C", "--chdir") and words:
                    cleaned.chdirs.append(words.pop(0))
                elif option.startswith("--chdir="):
                    cleaned.chdirs.append(option.removeprefix("--chdir="))
                elif option in _ENV_VALUE_OPTIONS and words:
                    words.pop(0)
        elif head in _PREFIX_COMMANDS or head == "builtin":
            words.pop(0)
            while words and words[0].startswith("-"):
                words.pop(0)
        else:
            break
    if not words:
        return cleaned
    program = _program(words[0])
    if program == "git":
        rest, chdirs, elsewhere = _git_globals(words[1:])
        cleaned.words = ["git", *rest]
        cleaned.chdirs.extend(chdirs)
        cleaned.elsewhere |= elsewhere
    elif program == "gh":
        cleaned.words = ["gh", *_strip_options(words[1:], _GH_VALUE_OPTIONS)]
    else:
        cleaned.words = [program, *words[1:]]
    return cleaned


def _git_globals(words: list[str]) -> tuple[list[str], list[str], bool]:
    """git's global options: the words after them, the `-C` folders and whether the
    repository is named some other way (`--git-dir`, `--work-tree`)."""
    chdirs: list[str] = []
    elsewhere = False
    index = 0
    while index < len(words) and words[index].startswith("-"):
        option = words[index]
        name = option.split("=", 1)[0]
        elsewhere |= name in ("--git-dir", "--work-tree")
        if option in _GIT_VALUE_OPTIONS:
            if option == "-C" and index + 1 < len(words):
                chdirs.append(words[index + 1])
            index += 2
        else:
            index += 1
    return words[index:], chdirs, elsewhere


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


# Pushes ----------------------------------------------------------------------------------------


class _Contexts:
    """The repositories read for one command, each once."""

    def __init__(self, work_dir: Path, read_git: GitReader) -> None:
        self._work_dir = work_dir
        self._read_git = read_git
        self._cache: dict[Path, GitContext] = {}

    async def of(self, folder: Path) -> GitContext:
        if folder not in self._cache:
            self._cache[folder] = await self._read_git(folder)
        return self._cache[folder]

    async def protected(self, folder: Path | None) -> set[str]:
        """The default branch (of `folder` when known and readable, else of the
        session's folder) and the usual names of one."""
        default = (await self.of(folder)).default_branch if folder is not None else None
        if default is None:
            default = (await self.of(self._work_dir)).default_branch
        return {b for b in (default, *_FALLBACK_PROTECTED) if b}


async def _push_needs_ok(segment: _Segment, contexts: _Contexts) -> bool:
    """A `git push` that must ask in any autonomy: forced, aimed at the default branch,
    or without destination branch from a folder that is unknown or on the default
    branch."""
    positional: list[str] = []
    options_ended = False
    args = segment.words[2:]
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
    if any(refspec.startswith("+") for refspec in refspecs):
        return True
    implicit = not refspecs or any(r in ("HEAD", "@") for r in refspecs)
    named = [
        refspec.rsplit(":", 1)[-1].removeprefix("refs/heads/")
        for refspec in refspecs
        if refspec not in ("HEAD", "@")
    ]
    if implicit and segment.folder is None:
        # It goes wherever the current branch goes, in a folder the command does not
        # name: the one the CLI kept from an earlier call is unknown here.
        return True
    protected = await contexts.protected(segment.folder)
    if any(destination in protected for destination in named):
        return True
    if implicit and segment.folder is not None:
        current = (await contexts.of(segment.folder)).current_branch
        return current is None or current in protected
    return False
