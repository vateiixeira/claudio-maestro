"""Permission policy for specialist sessions: which commands need the user's ok."""

import asyncio
from pathlib import Path

import pytest
from git_helpers import git, make_repo

from claudio_maestro.specialists import policy
from claudio_maestro.specialists.policy import (
    ALWAYS_DEFAULTS,
    OUTWARD_DEFAULTS,
    GitContext,
    ask_rules,
    classify,
    read_git_context,
)

NO_GIT = GitContext(default_branch=None, current_branch=None)
ON_FEATURE = GitContext(default_branch="main", current_branch="fix/a")
SESSION_DIR = Path("/sessao")


def decide(command, autonomy="full", *, outward=(), always=(), git_ctx=ON_FEATURE):
    """Every folder (the session's or one named in the command) reads as `git_ctx`."""

    async def read_git(work_dir: Path) -> GitContext:
        return git_ctx

    return asyncio.run(
        classify(
            command, autonomy=autonomy, outward=list(outward), always=list(always),
            work_dir=SESSION_DIR, read_git=read_git,
        )
    )


def test_defaults_are_the_documented_values():
    assert OUTWARD_DEFAULTS == (
        "git push", "gh pr create", "gh pr merge", "gh issue comment", "gh issue close",
        "gh release",
    )
    assert ALWAYS_DEFAULTS == ("gh pr merge",)


@pytest.mark.parametrize(
    ("command", "autonomy", "git_ctx", "expected"),
    [
        # the plain push of a work branch is the end of the line for "full"
        ("git push -u origin fix/sentry-123", "full", ON_FEATURE, "allow"),
        ("git push -u origin fix/sentry-123", "ask", ON_FEATURE, "ask"),
        # compound commands, global options, env prefixes
        ("cd repo && git push origin HEAD:main", "full", ON_FEATURE, "ask"),
        ("cd repo; git push origin HEAD:main", "full", ON_FEATURE, "ask"),
        ("make test || git push origin main", "full", ON_FEATURE, "ask"),
        ("make test | git push origin main", "full", ON_FEATURE, "ask"),
        ("make test & git push origin main", "full", ON_FEATURE, "ask"),
        ("make test\ngit push origin main", "full", ON_FEATURE, "ask"),
        ("(cd repo && git push origin main)", "full", ON_FEATURE, "ask"),
        ("git -C /x push origin main", "full", ON_FEATURE, "ask"),
        ("git -c push.default=current push origin main", "full", ON_FEATURE, "ask"),
        ("git --git-dir=/x/.git --no-pager push origin main", "full", ON_FEATURE, "ask"),
        ("git --git-dir /x/.git push origin main", "full", ON_FEATURE, "ask"),
        ("git -C /x push origin fix/a", "ask", ON_FEATURE, "ask"),
        ("env GIT_X=1 git push --force-with-lease origin fix/a", "full", ON_FEATURE, "ask"),
        ("GIT_X=1 git push origin main", "full", ON_FEATURE, "ask"),
        ("env -i GIT_X=1 /usr/bin/git push origin main", "full", ON_FEATURE, "ask"),
        ("bash -c 'git push origin main'", "full", ON_FEATURE, "ask"),
        ("sh -lc \"cd x && git push origin main\"", "full", ON_FEATURE, "ask"),
        # force
        ("git push --force origin fix/a", "full", ON_FEATURE, "ask"),
        ("git push -f origin fix/a", "full", ON_FEATURE, "ask"),
        ("git push -uf origin fix/a", "full", ON_FEATURE, "ask"),
        ("git push --force-with-lease origin fix/a", "full", ON_FEATURE, "ask"),
        ("git push --force-with-lease=fix/a origin fix/a", "full", ON_FEATURE, "ask"),
        ("git push origin +fix/a", "full", ON_FEATURE, "ask"),
        ("git push origin +HEAD:fix/a", "full", ON_FEATURE, "ask"),
        # the default branch, in every spelling
        ("git push origin main", "full", NO_GIT, "ask"),
        ("git push origin master", "full", NO_GIT, "ask"),
        ("git push origin HEAD:refs/heads/main", "full", ON_FEATURE, "ask"),
        ("git push origin fix/a:main", "full", ON_FEATURE, "ask"),
        ("git push origin :main", "full", ON_FEATURE, "ask"),
        ("git push --delete origin main", "full", ON_FEATURE, "ask"),
        ("git push --mirror origin", "full", ON_FEATURE, "ask"),
        ("git push --all origin", "full", ON_FEATURE, "ask"),
        (
            "git push origin develop",
            "full",
            GitContext(default_branch="develop", current_branch="fix/a"),
            "ask",
        ),
        (
            "git push origin develop",
            "full",
            GitContext(default_branch="main", current_branch="fix/a"),
            "allow",
        ),
        # a push without refspec goes to wherever the current branch goes; with no folder
        # in the command, the folder the CLI kept between calls is unknown, so it asks
        ("git push", "full", GitContext("main", "main"), "ask"),
        ("git push", "full", GitContext(None, "main"), "ask"),
        ("git push", "full", GitContext(None, "master"), "ask"),
        ("git push", "full", GitContext("develop", "develop"), "ask"),
        ("git push origin", "full", GitContext("main", "main"), "ask"),
        ("git push -u origin", "full", GitContext("main", "main"), "ask"),
        ("git push origin HEAD", "full", GitContext("main", "main"), "ask"),
        ("git push", "full", GitContext("main", "fix/a"), "ask"),
        ("git push origin HEAD", "full", GitContext("main", "fix/a"), "ask"),
        ("git push -u origin @", "full", GitContext("main", "fix/a"), "ask"),
        ("cd sub && git push", "full", GitContext("main", "fix/a"), "allow"),
        ("git -C sub push -u origin HEAD", "full", GitContext("main", "fix/a"), "allow"),
        ("cd sub && git push", "full", GitContext("main", "main"), "ask"),
        ("git push", "full", NO_GIT, "ask"),  # unknown branch: cannot prove it is not main
        # gh
        ("gh pr merge 12 --squash", "full", ON_FEATURE, "ask"),
        ("gh -R owner/repo pr merge 12", "full", ON_FEATURE, "ask"),
        ("gh --repo owner/repo pr merge 12", "full", ON_FEATURE, "ask"),
        ("gh pr create --fill", "full", ON_FEATURE, "allow"),
        ("gh pr create --fill", "ask", ON_FEATURE, "ask"),
        ("gh issue comment 3 -b ok", "ask", ON_FEATURE, "ask"),
        ("gh issue comment 3 -b ok", "full", ON_FEATURE, "allow"),
        ("gh release create v1", "ask", ON_FEATURE, "ask"),
        ("gh pr view 12", "ask", ON_FEATURE, "allow"),
        # redirections are not refspecs
        ("git push origin 2>&1", "full", GitContext("main", "main"), "ask"),
        ("git push -u origin 2>&1 | tail -5", "full", GitContext("main", "main"), "ask"),
        ("git push origin >/tmp/log", "full", GitContext("main", "main"), "ask"),
        ("git push origin > /tmp/log", "full", GitContext("main", "main"), "ask"),
        ("git push origin &> /tmp/log", "full", GitContext("main", "main"), "ask"),
        ("git push 2>&1 origin", "full", GitContext("main", "main"), "ask"),
        ("git push origin >> /tmp/log 2>/dev/null", "full", GitContext("main", "main"), "ask"),
        ("git push origin fix/a 2>&1", "full", GitContext("main", "fix/a"), "allow"),
        ("git push origin fix/a > /tmp/log", "full", GitContext("main", "fix/a"), "allow"),
        ("git push origin main 2>&1", "full", ON_FEATURE, "ask"),
        ("make > /dev/null 2>&1 && git push origin main", "full", ON_FEATURE, "ask"),
        # shell keywords and wrappers in front of the command
        ("if true; then git push origin main; fi", "full", ON_FEATURE, "ask"),
        ("if git push origin main; then echo ok; fi", "full", ON_FEATURE, "ask"),
        ("for r in a; do git push --force origin fix/a; done", "full", ON_FEATURE, "ask"),
        ("while true; do git push origin main; done", "full", ON_FEATURE, "ask"),
        ("{ git push origin main; }", "full", ON_FEATURE, "ask"),
        ("! git push -f origin fix/a", "full", ON_FEATURE, "ask"),
        ("true || ! git push origin main", "full", ON_FEATURE, "ask"),
        ("if x; then echo a; else gh pr merge 3; fi", "full", ON_FEATURE, "ask"),
        ("if true; then git push origin fix/a; fi", "full", ON_FEATURE, "allow"),
        ("if true; then git push origin fix/a; fi", "ask", ON_FEATURE, "ask"),
        ("timeout 60 git push origin main", "full", ON_FEATURE, "ask"),
        ("timeout -s KILL 60 git push origin main", "full", ON_FEATURE, "ask"),
        ("timeout --kill-after=5 60s git push origin main", "full", ON_FEATURE, "ask"),
        ("nice git push origin main", "full", ON_FEATURE, "ask"),
        ("nice -n 10 git push origin main", "full", ON_FEATURE, "ask"),
        ("nice -10 git push origin main", "full", ON_FEATURE, "ask"),
        ("timeout 60 nice -n 5 gh pr merge 4", "full", ON_FEATURE, "ask"),
        ("timeout 60 git push origin fix/a", "full", ON_FEATURE, "allow"),
        ("timeout 60 git push origin fix/a", "ask", ON_FEATURE, "ask"),
        # quoted text is not a command
        ('echo "git push"', "ask", ON_FEATURE, "allow"),
        ("echo 'x && git push origin main'", "full", ON_FEATURE, "allow"),
        ('git commit -m "git push origin main; gh pr merge"', "ask", ON_FEATURE, "allow"),
        ("grep -rn 'gh pr merge' docs", "full", ON_FEATURE, "allow"),
        # harmless
        ("ls -la", "ask", ON_FEATURE, "allow"),
        ("git status", "ask", ON_FEATURE, "allow"),
        ("git -C /x log --oneline", "ask", ON_FEATURE, "allow"),
        ("", "ask", ON_FEATURE, "allow"),
        ("echo 'unterminated", "ask", ON_FEATURE, "allow"),
    ],
)
def test_classify_builtin_rules(command, autonomy, git_ctx, expected):
    assert decide(command, autonomy, git_ctx=git_ctx) == expected


def test_custom_outward_pattern_only_matters_when_asking():
    command = "python3 filmes.py baixar x 3"
    assert decide(command, "ask", outward=["python3 filmes.py baixar"]) == "ask"
    assert decide(command, "full", outward=["python3 filmes.py baixar"]) == "allow"
    assert decide("python3 filmes.py listar", "ask", outward=["python3 filmes.py baixar"]) == "allow"


def test_custom_outward_pattern_matches_inside_a_compound_command():
    assert decide("cd x && python3 filmes.py baixar a", "ask", outward=["python3 filmes.py baixar"]) == "ask"


def test_custom_always_pattern_asks_in_any_autonomy():
    for autonomy in ("full", "ask"):
        assert decide("terraform apply -auto-approve", autonomy, always=["terraform apply"]) == "ask"
        assert decide("terraform plan", autonomy, always=["terraform apply"]) == "allow"


def test_pattern_needs_whole_words():
    assert decide("git pushover", "ask") == "allow"
    assert decide("gh pr merged", "full") == "allow"


def test_ask_rules_union_without_duplicates():
    rules = ask_rules(["git push", "python3 filmes.py baixar"], ["gh pr merge", "terraform apply"])
    assert rules == [
        "Bash(git push:*)",
        "Bash(gh pr create:*)",
        "Bash(gh pr merge:*)",
        "Bash(gh issue comment:*)",
        "Bash(gh issue close:*)",
        "Bash(gh release:*)",
        "Bash(python3 filmes.py baixar:*)",
        "Bash(terraform apply:*)",
    ]
    assert len(rules) == len(set(rules))


def test_ask_rules_with_no_extras_are_the_defaults():
    assert ask_rules([], []) == [f"Bash({p}:*)" for p in OUTWARD_DEFAULTS]


@pytest.mark.anyio
async def test_read_git_context_from_repo(tmp_path: Path):
    repo = make_repo(tmp_path / "r", branch="main")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "trunk", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main:trunk")
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "trunk")
    git(repo, "checkout", "-q", "-b", "fix/a")

    ctx = await read_git_context(repo)

    assert ctx == GitContext(default_branch="trunk", current_branch="fix/a")


@pytest.mark.anyio
async def test_read_git_context_without_remote_head(tmp_path: Path):
    repo = make_repo(tmp_path / "r", branch="feature/x")

    ctx = await read_git_context(repo)

    assert ctx == GitContext(default_branch=None, current_branch="feature/x")


@pytest.mark.anyio
async def test_read_git_context_outside_a_repo(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()

    assert await read_git_context(plain) == GitContext(None, None)
    assert await read_git_context(tmp_path / "missing") == GitContext(None, None)


def test_module_does_not_call_git_directly():
    source = Path(policy.__file__).read_text()
    assert "subprocess" not in source
    assert "create_subprocess" not in source


# The folder the command runs in ----------------------------------------------------------


class Repos:
    """`origin` (bare, default `main`), the session's clone `repo` on `feat/foo`, a worktree
    `wt-main` on `main` and a worktree `wt-feature` on `feat/bar`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = make_repo(root / "repo", branch="main")
        origin = root / "origin.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.repo, "remote", "add", "origin", str(origin))
        git(self.repo, "push", "-q", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")
        git(self.repo, "remote", "set-head", "origin", "main")
        git(self.repo, "checkout", "-q", "-b", "feat/foo")
        self.wt_main = root / "wt-main"
        git(self.repo, "worktree", "add", "-q", str(self.wt_main), "main")
        self.wt_feature = root / "wt-feature"
        git(self.repo, "worktree", "add", "-q", "-b", "feat/bar", str(self.wt_feature), "main")


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    return Repos(tmp_path)


def judge(command: str, work_dir: Path, autonomy: str = "full", **kwargs) -> str:
    return asyncio.run(
        classify(command, autonomy=autonomy, outward=[], always=[], work_dir=work_dir, **kwargs)
    )


@pytest.mark.parametrize(
    "template",
    [
        "cd {wt_main} && git push",
        "git -C {wt_main} push",
        "cd {wt_main} && git push -u origin HEAD",
        "git push",
    ],
)
def test_implicit_push_judged_by_the_folder_it_runs_in(repos, template):
    command = template.format(wt_main=repos.wt_main)
    assert judge(command, repos.repo) == "ask"  # the session is on feat/foo


@pytest.mark.parametrize(
    "template",
    [
        "cd {wt_feature} && git push -u origin HEAD",
        "cd {wt_feature}; git push -u origin HEAD",
        "git -C {wt_feature} push",
        "git -C {root} -C wt-feature push",
        "cd {root} && git -C wt-feature push -u origin HEAD",
        "if cd {wt_feature}; then git push; fi",
        "(cd {wt_feature} && git push -u origin HEAD)",
        "cd {wt_feature} && git log --oneline | head -3 && git push",
    ],
)
def test_implicit_push_from_a_named_feature_folder_is_allowed(repos, template):
    command = template.format(wt_feature=repos.wt_feature, root=repos.root)
    wt_main = repos.wt_main  # the session sits on main
    assert judge(command, wt_main) == "allow"
    assert judge(command, wt_main, autonomy="ask") == "ask"


@pytest.mark.parametrize(
    "template",
    [
        # the cd may not have happened, or happened in another shell
        "(cd {wt_feature} && make); git push",
        "(cd {wt_feature}); git push -u origin HEAD",
        "false && cd {wt_feature}; git push",
        "cd {wt_feature} || true; git push",
        "true || cd {wt_feature} && git push",
        "cd {wt_feature} && make || git push",
        "echo x | cd {wt_feature} && git push",
        "cd {wt_feature} | cat && git push",
        "cd {wt_feature} && make & git push",
        "bash -c 'cd {wt_feature}' && git push",
        "if true; then cd {wt_feature}; fi; git push",
        "cd {wt_feature} && cd - && git push",
        "cd $WT && git push",
        "pushd {wt_feature} && popd && git push",
        "! cd {wt_feature} && git push",
        "pushd -1 && git push",
        "pushd +1 && git push",
        "cat <<EOF\ncd {wt_feature}\nEOF\ngit push -u origin HEAD",
        "cat <<'EOF' > x.txt\ncd {wt_feature} && git push\nEOF",
        # other ways to name the repository: not followed
        "git --git-dir={wt_feature}/.git push",
        "GIT_DIR={wt_feature}/.git git push",
        # a folder that does not exist or is not a repository
        "cd {root}/missing && git push -u origin HEAD",
        "cd {root} && git push -u origin HEAD",
        "git -C {root}/missing push",
    ],
)
def test_implicit_push_asks_when_the_folder_is_unsure(repos, template):
    command = template.format(wt_feature=repos.wt_feature, root=repos.root)
    assert judge(command, repos.wt_feature) == "ask"


@pytest.mark.parametrize(
    "template",
    [
        "git push -u origin feat/x",
        "cd {wt_main} && git push -u origin feat/x",
        "git -C {wt_main} push origin HEAD:feat/x",
        "cd {root}/missing && git push origin refs/heads/feat/x",
    ],
)
def test_named_destination_is_judged_by_its_name_in_any_folder(repos, template):
    command = template.format(wt_main=repos.wt_main, root=repos.root)
    for work_dir in (repos.repo, repos.wt_main):
        assert judge(command, work_dir) == "allow"


def test_named_destination_compares_with_the_default_of_the_folder_it_runs_in(tmp_path):
    session = make_repo(tmp_path / "session", branch="feat/s")
    other = make_repo(tmp_path / "other", branch="feat/o")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "develop", str(remote))
    git(other, "remote", "add", "origin", str(remote))
    git(other, "push", "-q", "origin", "feat/o:develop")
    git(other, "fetch", "-q", "origin")
    git(other, "remote", "set-head", "origin", "develop")

    assert judge(f"git -C {other} push origin develop", session) == "ask"
    assert judge(f"cd {other} && git push origin HEAD:develop", session) == "ask"
    assert judge("git push origin develop", session) == "allow"


def test_git_dash_c_accumulates_like_git(tmp_path):
    seen: list[Path] = []

    async def spy(work_dir: Path) -> GitContext:
        seen.append(work_dir)
        return GitContext("main", "feat/x")

    session = tmp_path / "s"
    asyncio.run(classify(
        "git -C /a -C b -C ../c push", autonomy="full", outward=[], always=[],
        work_dir=session, read_git=spy,
    ))
    asyncio.run(classify(
        "cd /x && git -C y -C /z -C w push", autonomy="full", outward=[], always=[],
        work_dir=session, read_git=spy,
    ))
    asyncio.run(classify(
        "git -C rel push", autonomy="full", outward=[], always=[],
        work_dir=session, read_git=spy,
    ))

    assert Path("/a/b/../c") in seen
    assert Path("/z/w") in seen
    assert session / "rel" in seen


def test_git_dash_c_resolves_against_a_real_tree(tmp_path):
    (tmp_path / "a").mkdir()
    make_repo(tmp_path / "a" / "b", branch="feat/b")
    on_main = make_repo(tmp_path / "m", branch="main")

    assert judge(f"git -C {tmp_path}/a -C b push", on_main) == "allow"
    assert judge(f"git -C {tmp_path}/a -C {on_main} push", on_main) == "ask"


def test_no_git_is_read_for_commands_without_a_push(tmp_path):
    async def spy(work_dir: Path) -> GitContext:
        raise AssertionError("git read without a push")

    for command in ("ls", "git status", "cd /x && git log", "gh pr view 3"):
        assert judge(command, tmp_path, read_git=spy) == "allow"
    # "ask" autonomy asks for any push before reading the repository
    assert judge("git push origin feat/x", tmp_path, autonomy="ask", read_git=spy) == "ask"
