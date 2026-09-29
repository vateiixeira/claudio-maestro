"""Git status reading with real temporary repositories."""

import os
import stat
from pathlib import Path

import pytest

from git_helpers import git, make_repo
from vibing import gitinfo

pytestmark = pytest.mark.anyio


async def test_branch_and_clean(tmp_path: Path):
    repo = make_repo(tmp_path / "r", branch="feature/x")
    status = await gitinfo.repo_status(repo)
    assert status.branch == "feature/x"
    assert status.detached is False
    assert status.head and len(status.head) >= 7
    assert status.changed == {"staged": 0, "unstaged": 0, "untracked": 0}
    assert status.error is None


async def test_detached_head(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    sha = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "--detach")
    status = await gitinfo.repo_status(repo)
    assert status.detached is True
    assert status.branch is None
    assert sha.startswith(status.head)


async def test_repo_without_commits(tmp_path: Path):
    repo = make_repo(tmp_path / "r", branch="trunk", commit=False)
    (repo / "novo.txt").write_text("x")
    status = await gitinfo.repo_status(repo)
    assert status.error is None
    assert status.branch == "trunk"
    assert status.head is None
    assert status.changed["untracked"] == 1


async def test_change_counts(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "a.txt").write_text("a")
    git(repo, "add", "a.txt")
    (repo / "README.md").write_text("mudou\n")
    (repo / "b.txt").write_text("b")
    (repo / "c.txt").write_text("c")
    status = await gitinfo.repo_status(repo)
    assert status.changed == {"staged": 1, "unstaged": 1, "untracked": 2}


async def test_failure_isolated(tmp_path: Path):
    root = tmp_path / "proj"
    make_repo(root / "good")
    broken = root / "broken"
    broken.mkdir(parents=True)
    (broken / ".git").write_text("gitdir: /nao/existe")
    repos = await gitinfo.project_repos(root)
    by_rel = {r.rel_path: r for r in repos}
    assert by_rel["good"].error is None and by_rel["good"].branch == "main"
    assert by_rel["broken"].error
    assert by_rel["broken"].branch is None


async def test_project_root_counts_as_repo(tmp_path: Path):
    root = make_repo(tmp_path / "proj")
    make_repo(root / "sub" / "inner", branch="dev")
    repos = await gitinfo.project_repos(root)
    assert [(r.rel_path, r.branch) for r in repos] == [(".", "main"), ("sub/inner", "dev")]
    assert repos[0].path == str(root)


async def test_folder_without_git(tmp_path: Path):
    (tmp_path / "plain").mkdir()
    assert await gitinfo.project_repos(tmp_path / "plain") == []


async def test_timeout(tmp_path: Path, monkeypatch):
    fake = tmp_path / "slowgit"
    fake.write_text("#!/bin/sh\nexec sleep 10\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    repo = make_repo(tmp_path / "r")
    status = await gitinfo.repo_status(repo, timeout=0.2)
    assert status.error and "tempo" in status.error.lower()


async def test_uses_list_args_and_no_locks(tmp_path: Path, monkeypatch):
    log = tmp_path / "log"
    fake = tmp_path / "spygit"
    fake.write_text(f'#!/bin/sh\necho "$GIT_OPTIONAL_LOCKS $GIT_CONFIG_COUNT $GIT_CONFIG_KEY_0 $@" >> {log}\nexit 1\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(gitinfo, "GIT_BINARY", str(fake))
    repo = tmp_path / "dir; rm -rf x"
    repo.mkdir()
    await gitinfo.repo_status(repo)
    lookup, line = log.read_text().splitlines()[:2]
    assert "-C " + str(repo) + " config -z --name-only --get-regexp" in lookup
    assert line.startswith("0 9 core.fsmonitor -C ")
    assert "-C " + str(repo) + " status" in line
    assert "status --porcelain=v2 --branch" in line


async def test_branch_label(tmp_path: Path):
    repo = make_repo(tmp_path / "r", branch="dev")
    assert await gitinfo.branch_label(repo) == "dev"
    git(repo, "checkout", "-q", "--detach")
    label = await gitinfo.branch_label(repo)
    assert label and label != "dev"


async def test_diff_modified(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("linha 1\nnova\n")
    result = await gitinfo.file_diff(repo, "README.md")
    assert "-linha 2" in result.diff and "+nova" in result.diff
    assert result.truncated is False


async def test_diff_untracked(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "novo.py").write_text("print(1)\n")
    result = await gitinfo.file_diff(repo, "novo.py")
    assert "+print(1)" in result.diff


async def test_diff_unchanged(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    result = await gitinfo.file_diff(repo, "README.md")
    assert result.diff == ""


async def test_diff_without_commits(tmp_path: Path):
    repo = make_repo(tmp_path / "r", commit=False)
    (repo / "a.txt").write_text("oi\n")
    git(repo, "add", "a.txt")
    result = await gitinfo.file_diff(repo, "a.txt")
    assert "+oi" in result.diff


async def test_diff_truncated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(gitinfo, "DIFF_LIMIT", 50)
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("x" * 500 + "\n")
    result = await gitinfo.file_diff(repo, "README.md")
    assert result.truncated is True and len(result.diff) == 50


async def test_dirty_files(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudou\n")
    (repo / "d").mkdir()
    (repo / "d" / "n.txt").write_text("n")
    assert await gitinfo.dirty_files(repo) == {"README.md", "d/n.txt"}


def _evil_repo(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "executou"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat \"$1\" 2>/dev/null\n")
    script.chmod(0o755)
    repo = make_repo(tmp_path / "home" / "evil")
    git(repo, "config", "core.fsmonitor", str(script))
    git(repo, "config", "diff.x.textconv", str(script))
    git(repo, "config", "core.pager", str(script))
    (repo / ".gitattributes").write_text("*.md diff=x\n")
    (repo / "README.md").write_text("mudou\n")
    return repo, marker


async def test_repo_config_commands_not_executed(tmp_path: Path):
    repo, marker = _evil_repo(tmp_path)
    await gitinfo.repo_status(repo)
    await gitinfo.dirty_files(repo)
    result = await gitinfo.file_diff(repo, "README.md")
    assert "+mudou" in result.diff
    assert not marker.exists()


async def test_pathspec_is_literal(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    (repo / "README.md").write_text("mudou\n")
    (repo / "a").write_text("a")
    for spec in ("*", ":(top)a", ":(top)README.md"):
        assert (await gitinfo.file_diff(repo, spec)).diff == ""


def _filter_repo(tmp_path: Path) -> tuple[Path, Path]:
    marker = tmp_path / "filtro-executou"
    script = tmp_path / "filter.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    repo = make_repo(tmp_path / "home" / "filtros")
    (repo / ".gitattributes").write_text("*.md filter=x\n*.txt filter=p\n")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "attrs")
    git(repo, "config", "filter.x.clean", str(script))
    git(repo, "config", "filter.x.smudge", str(script))
    git(repo, "config", "filter.p.process", str(script))
    (repo / "README.md").write_text("mudou\n")
    (repo / "a.txt").write_text("b\n")
    # Newer mtime than the index, so git must re-read (and re-filter) the files.
    return repo, marker


async def test_repo_filters_not_executed(tmp_path: Path):
    repo, marker = _filter_repo(tmp_path)
    marker.unlink(missing_ok=True)
    status = await gitinfo.repo_status(repo)
    assert status.error is None and status.changed["unstaged"] == 2
    assert await gitinfo.dirty_files(repo) == {"README.md", "a.txt"}
    assert "+mudou" in (await gitinfo.file_diff(repo, "README.md")).diff
    assert "+b" in (await gitinfo.file_diff(repo, "a.txt")).diff
    assert not marker.exists()


async def test_filter_names_with_equals_not_executed(tmp_path: Path):
    marker = tmp_path / "armadilha"
    script = tmp_path / "f.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\ncat\n")
    script.chmod(0o755)
    repo = make_repo(tmp_path / "r")
    (repo / ".gitattributes").write_text("*.md filter=a=b\n*.txt filter=tr=x.clean\n")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "attrs")
    for name in ("a=b", "tr=x.clean"):
        for part in ("clean", "smudge", "process"):
            git(repo, "config", f"filter.{name}.{part}", str(script))
    (repo / "README.md").write_text("mudou\n")
    (repo / "a.txt").write_text("b\n")
    status = await gitinfo.repo_status(repo)
    assert status.error is None
    assert await gitinfo.dirty_files(repo) == {"README.md", "a.txt"}
    assert "+mudou" in (await gitinfo.file_diff(repo, "README.md")).diff
    assert "+b" in (await gitinfo.file_diff(repo, "a.txt")).diff
    assert not marker.exists()


async def test_filter_name_with_newline_refused(tmp_path: Path):
    repo = make_repo(tmp_path / "r")
    config = repo / ".git" / "config"
    config.write_text(config.read_text() + '[filter "a\tb"]\n\tclean = x\n')
    status = await gitinfo.repo_status(repo)
    assert status.error == "Repositório com filtro de nome inválido"
    with pytest.raises(gitinfo.GitError):
        await gitinfo.file_diff(repo, "README.md")
