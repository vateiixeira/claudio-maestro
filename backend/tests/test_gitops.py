"""Write actions of `gitops`: lock, stage, unstage, discard and commit, on real repositories."""

import asyncio
import stat
import subprocess
from pathlib import Path

import pytest
from git_helpers import (  # noqa: F401 (fixture)
    GIT_ENV,
    commit_file,
    git,
    git_home,
    make_repo,
    set_identity,
)

from claudio_maestro import gitinfo, gitops


@pytest.fixture(autouse=True)
def fresh_policy():
    gitinfo.clear_policy_cache()
    yield
    gitinfo.clear_policy_cache()


def writable_repo(path: Path, **kwargs) -> Path:
    repo = make_repo(path, **kwargs)
    set_identity(repo)
    return repo


def status(repo: Path) -> str:
    return git(repo, "status", "--porcelain=v1", "--untracked-files=all")


def executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


# run_git ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_git_feeds_input(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    code, out, _ = await gitinfo.run_git(repo, "hash-object", "--stdin", input=b"oi\n")
    expected = subprocess.run(["git", "hash-object", "--stdin"], input=b"oi\n", capture_output=True, check=True).stdout
    assert code == 0 and out.strip() == expected.decode().strip()


@pytest.mark.anyio
async def test_grace_sends_sigterm_before_sigkill(tmp_path: Path, monkeypatch):
    mark = tmp_path / "termo"
    fake = executable(tmp_path / "git", (
        "#!/bin/sh\n"
        'case "$3" in config) exit 1;; esac\n'
        f"trap 'echo term > {mark}; exit 0' TERM\n"
        "while :; do sleep 0.05; done\n"
    ))
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    with pytest.raises(gitinfo.GitError):
        await gitinfo.run_git(tmp_path, "status", timeout=0.3, grace=2.0, own_group=True)
    assert mark.read_text().strip() == "term"


@pytest.mark.anyio
async def test_without_grace_the_process_is_killed(tmp_path: Path, monkeypatch):
    mark = tmp_path / "termo"
    fake = executable(tmp_path / "git", (
        "#!/bin/sh\n"
        'case "$3" in config) exit 1;; esac\n'
        f"trap 'echo term > {mark}; exit 0' TERM\n"
        "while :; do sleep 0.05; done\n"
    ))
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    with pytest.raises(gitinfo.GitError):
        await gitinfo.run_git(tmp_path, "status", timeout=0.3, own_group=True)
    assert not mark.exists()


def _process_alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


@pytest.mark.anyio
async def test_second_cancel_during_grace_still_sends_sigkill(tmp_path: Path, monkeypatch):
    pidfile = tmp_path / "pid"
    fake = executable(tmp_path / "git", (
        "#!/bin/sh\n"
        'case "$3" in config) exit 1;; esac\n'
        "trap '' TERM\n"
        f"echo $$ > {pidfile}\n"
        "while :; do sleep 0.05; done\n"
    ))
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    task = asyncio.ensure_future(gitinfo.run_git(tmp_path, "status", timeout=30, grace=30.0, own_group=True))
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pidfile.read_text())
    task.cancel()
    await asyncio.sleep(0.3)
    assert _process_alive(pid)  # SIGTERM was ignored; waiting out the grace
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):
        if not _process_alive(pid):
            break
        await asyncio.sleep(0.05)
    assert not _process_alive(pid)


@pytest.mark.anyio
async def test_actions_run_git_with_grace_and_own_group(tmp_path: Path, monkeypatch, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a\n")
    seen = []
    real = gitinfo.run_git

    async def spy(*args, **kwargs):
        seen.append(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(gitinfo, "run_git", spy)
    await gitops.stage(repo, ["a.txt"])
    writes = [kw for kw in seen if kw.get("grace")]
    assert writes and all(kw["grace"] == gitops.TERM_GRACE and kw["own_group"] for kw in writes)
    assert all(kw["timeout"] == gitops.LOCAL_TIMEOUT for kw in writes)


# lock -----------------------------------------------------------------------


@pytest.mark.anyio
async def test_lock_refuses_a_second_action_in_the_same_repository(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    link = tmp_path / "atalho"
    link.symlink_to(repo)
    other = make_repo(tmp_path / "outro")
    async with gitops.repo_lock(repo):
        with pytest.raises(gitops.RepoBusyError) as caught:
            async with gitops.repo_lock(link):
                pass
        assert caught.value.code == "busy" and str(caught.value) == gitops.BUSY_MESSAGE
        async with gitops.repo_lock(other):
            pass
    async with gitops.repo_lock(repo):
        pass  # free again


# paths ----------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "", "/etc/passwd", "../fora.txt", "a/../../fora", ".git/config", "sub/.git/HEAD", ".GIT/config",
    "a\x00b", "linha\nnova", ".",
])
def test_repo_relpath_refuses(tmp_path: Path, raw):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(gitops.InvalidRequestError):
        gitops.repo_relpath(repo, raw)


def test_repo_relpath_refuses_a_folder_that_links_outside(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (tmp_path / "fora").mkdir()
    (repo / "pasta").symlink_to(tmp_path / "fora")
    with pytest.raises(gitops.InvalidRequestError):
        gitops.repo_relpath(repo, "pasta/x.txt")


def test_repo_relpath_keeps_a_link_that_points_outside(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "docs").mkdir()
    (repo / "docs" / "atalho").symlink_to("/etc")
    assert gitops.repo_relpath(repo, "docs/atalho") == "docs/atalho"
    assert gitops.repo_relpath(repo, "./docs//atalho") == "docs/atalho"


# stage / unstage ------------------------------------------------------------


@pytest.mark.anyio
async def test_stage_and_unstage(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudou\n")
    (repo / "-rf.txt").write_text("perigo\n")
    (repo / "ação é.txt").write_text("acento\n")
    await gitops.stage(repo, ["README.md", "-rf.txt", "ação é.txt"])
    staged = git(repo, "diff", "--cached", "--name-only", "-z").split("\0")
    assert {"README.md", "-rf.txt", "ação é.txt"} <= set(staged)
    await gitops.unstage(repo, ["README.md", "-rf.txt"])
    staged = git(repo, "diff", "--cached", "--name-only", "-z").split("\0")
    assert "README.md" not in staged and "-rf.txt" not in staged and "ação é.txt" in staged
    assert (repo / "README.md").read_text() == "mudou\n"


@pytest.mark.anyio
async def test_stage_a_deletion(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "README.md").unlink()
    await gitops.stage(repo, ["README.md"])
    assert git(repo, "diff", "--cached", "--name-status").strip() == "D\tREADME.md"


@pytest.mark.anyio
async def test_unstage_without_commits(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r", commit=False)
    (repo / "a.txt").write_text("a\n")
    await gitops.stage(repo, ["a.txt"])
    await gitops.unstage(repo, ["a.txt"])
    assert status(repo).strip() == "?? a.txt"


@pytest.mark.anyio
async def test_unstage_a_staged_rename_restores_both_names(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "NOVO.md")
    assert status(repo).startswith("R  README.md -> NOVO.md")
    await gitops.unstage(repo, ["NOVO.md"])
    assert status(repo) == " D README.md\n?? NOVO.md\n"


@pytest.mark.anyio
async def test_unstage_a_rename_leaves_nothing_staged(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "NOVO.md")
    await gitops.unstage(repo, ["NOVO.md"])
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert (repo / "NOVO.md").read_text() == "linha 1\nlinha 2\n"


# discard --------------------------------------------------------------------


@pytest.mark.anyio
async def test_discard_tracked_staged_and_untracked(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudou\n")
    (repo / "novo.txt").write_text("novo\n")
    (repo / "preparado.txt").write_text("p\n")
    git(repo, "add", "preparado.txt")
    (repo / "-n.txt").write_text("traço\n")
    await gitops.discard(repo, ["README.md", "novo.txt", "preparado.txt", "-n.txt"])
    assert (repo / "README.md").read_text() == "linha 1\nlinha 2\n"
    assert not (repo / "novo.txt").exists() and not (repo / "preparado.txt").exists()
    assert not (repo / "-n.txt").exists()
    assert status(repo) == ""


@pytest.mark.anyio
async def test_discard_refuses_a_file_without_changes(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    commit_file(repo, "limpo.txt")
    with pytest.raises(gitops.InvalidRequestError):
        await gitops.discard(repo, ["limpo.txt"])
    assert (repo / "limpo.txt").exists()


@pytest.mark.anyio
async def test_discard_never_removes_ignored_files_or_folders(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / ".gitignore").write_text("segredo.env\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    (repo / "segredo.env").write_text("x\n")
    (repo / "pasta").mkdir()
    (repo / "pasta" / "a.txt").write_text("a\n")
    with pytest.raises(gitops.InvalidRequestError):
        await gitops.discard(repo, ["segredo.env"])
    with pytest.raises(gitops.InvalidRequestError):
        await gitops.discard(repo, ["pasta"])
    assert (repo / "segredo.env").exists() and (repo / "pasta" / "a.txt").exists()


@pytest.mark.anyio
async def test_discard_a_staged_rename_brings_the_original_back(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "NOVO.md")
    await gitops.discard(repo, ["NOVO.md"])
    assert (repo / "README.md").read_text() == "linha 1\nlinha 2\n"
    assert not (repo / "NOVO.md").exists()
    assert status(repo) == ""


@pytest.mark.anyio
async def test_discard_a_rename_with_changes_and_its_original_listed(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "mv", "README.md", "NOVO.md")
    (repo / "NOVO.md").write_text("linha 1\nlinha 2\nlinha 3\n")
    await gitops.discard(repo, ["NOVO.md"])
    assert (repo / "README.md").read_text() == "linha 1\nlinha 2\n"
    assert status(repo) == ""


# commit ---------------------------------------------------------------------


@pytest.mark.anyio
async def test_commit_only_what_is_staged(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a\n")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "a.txt")
    sha = await gitops.commit(repo, "Adicionar a")
    assert git(repo, "show", "--name-only", "--format=%s", sha).split() == ["Adicionar", "a", "a.txt"]
    assert status(repo).strip() == "?? b.txt"


@pytest.mark.anyio
async def test_commit_with_nothing_staged_takes_everything(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudou\n")
    (repo / "novo.txt").write_text("n\n")
    await gitops.commit(repo, "Tudo")
    assert status(repo) == ""
    assert set(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == {"README.md", "novo.txt"}


@pytest.mark.anyio
async def test_commit_keeps_a_message_that_starts_with_hash(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a\n")
    await gitops.commit(repo, "#123 corrige o frete\n\n# segunda linha fica\n")
    assert git(repo, "log", "-1", "--format=%B").strip() == "#123 corrige o frete\n\n# segunda linha fica"


@pytest.mark.anyio
async def test_first_commit(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r", commit=False)
    (repo / "a.txt").write_text("a\n")
    sha = await gitops.commit(repo, "Primeiro")
    assert git(repo, "rev-parse", "HEAD").strip() == sha


@pytest.mark.anyio
@pytest.mark.parametrize("message", ["", "   ", "\n\n"])
async def test_commit_refuses_an_empty_message(tmp_path: Path, git_home, message):
    repo = writable_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a\n")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.commit(repo, message)
    assert str(caught.value) == gitops.EMPTY_MESSAGE


@pytest.mark.anyio
async def test_commit_with_nothing_to_commit(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    with pytest.raises(gitops.InvalidRequestError) as caught:
        await gitops.commit(repo, "Nada")
    assert str(caught.value) == gitops.NOTHING_TO_COMMIT


@pytest.mark.anyio
async def test_commit_without_identity(tmp_path: Path, git_home):
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "user.useConfigOnly", "true")
    (repo / "a.txt").write_text("a\n")
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.commit(repo, "Sem identidade")
    assert str(caught.value) == gitops.IDENTITY_MESSAGE and caught.value.output
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert status(repo).strip() == "?? a.txt"


@pytest.mark.anyio
async def test_commit_runs_no_hook_editor_or_signing_program(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    marks = tmp_path / "marcas"
    marks.mkdir()
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    for name in ("pre-commit", "commit-msg", "prepare-commit-msg", "post-commit"):
        executable(hooks / name, f"#!/bin/sh\ntouch {marks / name}\n")
    gpg = executable(tmp_path / "gpg", f"#!/bin/sh\ntouch {marks / 'gpg'}\nexit 1\n")
    editor = executable(tmp_path / "editor", f"#!/bin/sh\ntouch {marks / 'editor'}\n")
    git(repo, "config", "commit.gpgsign", "true")
    git(repo, "config", "gpg.program", str(gpg))
    git(repo, "config", "core.editor", str(editor))
    (repo / "a.txt").write_text("a\n")
    await gitops.commit(repo, "Sem programas")
    assert list(marks.iterdir()) == []
    assert git(repo, "log", "-1", "--format=%G?").strip() == "N"


@pytest.mark.anyio
async def test_writes_are_refused_in_a_read_only_repository(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "config", "filter.lfs.clean", "git-lfs clean -- %f")
    (repo / ".gitattributes").write_text("*.psd filter=lfs\n")
    (repo / "a.psd").write_text("binario\n")
    for action in (
        lambda: gitops.stage(repo, ["a.psd"]),
        lambda: gitops.unstage(repo, ["a.psd"]),
        lambda: gitops.discard(repo, ["a.psd"]),
        lambda: gitops.commit(repo, "Não"),
    ):
        with pytest.raises(gitops.ReadOnlyError) as caught:
            await action()
        assert str(caught.value) == gitinfo.LFS_READ_ONLY
    assert git(repo, "diff", "--cached", "--name-only") == ""


@pytest.mark.anyio
async def test_commit_refuses_while_merging(tmp_path: Path, git_home):
    repo = writable_repo(tmp_path / "r")
    git(repo, "switch", "-q", "-c", "feat")
    (repo / "README.md").write_text("feat\n")
    git(repo, "commit", "-q", "-am", "feat")
    git(repo, "switch", "-q", "main")
    (repo / "README.md").write_text("main\n")
    git(repo, "commit", "-q", "-am", "main")
    subprocess.run(["git", "-C", str(repo), "merge", "feat"], capture_output=True, env=GIT_ENV)
    with pytest.raises(gitops.GitOpError) as caught:
        await gitops.commit(repo, "No meio do merge")
    assert str(caught.value) == gitops.MERGING_MESSAGE


# failures ------------------------------------------------------------------


def test_describe_failure():
    assert gitops.describe_failure(
        "fatal: Unable to create '/r/.git/index.lock': File exists.\n"
    ) == gitops.LOCKED_MESSAGE
    assert gitops.describe_failure("Author identity unknown\n*** Please tell me who you are.") == gitops.IDENTITY_MESSAGE
    assert gitops.describe_failure("fatal: no email was given and auto-detection is disabled") == gitops.IDENTITY_MESSAGE
    assert gitops.describe_failure(
        "error: Your local changes to the following files would be overwritten by checkout:\n"
        "\tsrc/app/api.ts\nPlease commit your changes or stash them before you switch branches.\nAborting\n",
        target="staging",
    ) == (
        "O git não trocou para staging: suas alterações em src/app/api.ts seriam sobrescritas. "
        "Commite, descarte ou leve para uma branch nova antes."
    )
    assert gitops.describe_failure(
        " ! [rejected]        main -> main (fetch first)\nerror: failed to push some refs\n",
        upstream="origin/main",
    ) == (
        "O envio não foi feito: origin/main recebeu commits que você ainda não tem. "
        "Sincronize para baixar e enviar."
    )
    assert gitops.describe_failure(
        "git@github.com: Permission denied (publickey).\nfatal: Could not read from remote repository.\n"
    ) == (
        "O ssh não entrou em github.com sem senha. O app não pede senha: carregue sua chave no "
        "ssh-agent e tente de novo."
    )
    assert gitops.describe_failure("fatal: algo estranho") == gitops.GENERIC_MESSAGE


def test_clean_output_strips_credentials_and_limits():
    text = "fatal: https://usuario:senha@example.com/r.git falhou\n" + "x" * 10_000
    cleaned = gitops.clean_output(text)
    assert "senha" not in cleaned and len(cleaned) <= gitops.OUTPUT_LIMIT
