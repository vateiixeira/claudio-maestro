"""scripts/check.sh: its `checks` array matches the CI, and it picks checks by the diff."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# CI steps that prepare the runner instead of checking the code.
SETUP = ("uv sync", "pnpm --dir frontend install")


def ci_checks() -> list[str]:
    commands = re.findall(r"^\s*run:\s*(.+?)\s*$", CI.read_text(), re.M)
    assert all(c[0] not in "|>" for c in commands), (
        "ci.yml has a multi-line `run:`; teach this test to read it"
    )
    return [c for c in commands if not c.startswith(SETUP)]


def script_checks() -> list[str]:
    block = re.search(r"^checks=\((.*?)^\)", SCRIPT.read_text(), re.M | re.S)
    assert block, "scripts/check.sh has no `checks=( ... )` array"
    return re.findall(r'^\s*"([^"]+)"\s*$', block.group(1), re.M)


def test_ci_has_checks():
    assert ci_checks(), "no check command found in ci.yml"


def test_script_runs_exactly_the_ci_checks():
    assert sorted(script_checks()) == sorted(ci_checks())


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


BACKEND = ["uv run ruff check", "uv run pytest -q"]
FRONTEND = ["pnpm --dir frontend test", "pnpm --dir frontend build"]
E2E = ["pnpm --dir frontend e2e"]


@pytest.fixture(autouse=True)
def isolated_git_env(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / "work"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Teste")
    git(repo, "config", "user.email", "teste@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "scripts").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / "check.sh")
    write(repo, "backend/a.py", "a = 1\n")
    write(repo, "frontend/src/a.ts", "export const a = 1\n")
    write(repo, "README.md", "# demo\n")
    write(repo, ".github/workflows/ci.yml", "name: ci\n")
    commit_all(repo, "inicial")
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "push", "-q", "origin", "HEAD:develop")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "-b", "feat/x")
    return repo


def run_check(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/check.sh", *args], cwd=project, capture_output=True, text=True
    )


def dry(project: Path, *args: str) -> list[str]:
    result = run_check(project, "--dry-run", *args)
    assert result.returncode == 0, result.stderr
    return [line[4:] for line in result.stdout.splitlines() if line.startswith("==> ")]


def test_backend_change_runs_only_python_checks(project):
    write(project, "backend/a.py", "a = 2\n")
    commit_all(project, "backend")
    assert dry(project) == BACKEND


def test_frontend_change_runs_only_frontend_checks(project):
    write(project, "frontend/src/a.ts", "export const a = 2\n")
    commit_all(project, "frontend")
    assert dry(project) == FRONTEND


def test_both_areas_run_both_groups(project):
    write(project, "backend/a.py", "a = 2\n")
    write(project, "frontend/src/a.ts", "export const a = 2\n")
    commit_all(project, "both")
    assert dry(project) == BACKEND + FRONTEND


def test_uncommitted_change_counts(project):
    write(project, "backend/a.py", "a = 2\n")
    assert dry(project) == BACKEND


def test_untracked_file_counts(project):
    write(project, "frontend/src/novo.ts", "export const n = 1\n")
    assert dry(project) == FRONTEND


def test_deleted_file_counts(project):
    git(project, "rm", "-q", "backend/a.py")
    commit_all(project, "remove")
    assert dry(project) == BACKEND


def test_pyproject_and_scripts_count_as_backend(project):
    write(project, "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project, "scripts/x.py", "print('x')\n")
    commit_all(project, "py")
    assert dry(project) == BACKEND


def test_ci_or_check_script_change_runs_all_but_e2e(project):
    write(project, ".github/workflows/ci.yml", "name: ci2\n")
    commit_all(project, "ci")
    assert dry(project) == BACKEND + FRONTEND


def test_check_script_change_runs_all_but_e2e(project):
    with (project / "scripts" / "check.sh").open("a") as f:
        f.write("# tweak\n")
    assert dry(project) == BACKEND + FRONTEND


def test_docs_only_runs_nothing(project):
    write(project, "README.md", "# changed\n")
    commit_all(project, "docs")
    result = run_check(project, "--dry-run")
    assert result.returncode == 0
    assert [ln for ln in result.stdout.splitlines() if ln.startswith("==> ")] == []
    assert "Nada para verificar" in result.stdout


def test_e2e_flag_adds_e2e(project):
    write(project, "frontend/src/a.ts", "export const a = 2\n")
    commit_all(project, "frontend")
    assert dry(project, "--e2e") == FRONTEND + E2E


def test_all_flag(project):
    write(project, "README.md", "# changed\n")
    commit_all(project, "docs")
    assert dry(project, "--all") == BACKEND + FRONTEND


def test_full_flag_matches_ci(project):
    assert sorted(dry(project, "--full")) == sorted(ci_checks())


def test_without_develop_falls_back_to_all(project):
    git(project, "update-ref", "-d", "refs/remotes/origin/develop")
    git(project, "update-ref", "-d", "refs/heads/develop")
    result = run_check(project, "--dry-run")
    assert result.returncode == 0
    commands = [ln[4:] for ln in result.stdout.splitlines() if ln.startswith("==> ")]
    assert commands == BACKEND + FRONTEND
    assert "sem develop" in result.stdout


def test_prefers_origin_develop_over_stale_local(project):
    # Local develop sits on an old commit that touched the frontend.
    git(project, "checkout", "-q", "-b", "develop")
    write(project, "frontend/src/a.ts", "export const a = 9\n")
    commit_all(project, "old frontend work")
    # origin/develop advances past it with a commit that includes that work.
    git(project, "push", "-q", "origin", "HEAD:develop")
    write(project, "README.md", "# newer\n")
    commit_all(project, "newer")
    git(project, "push", "-q", "origin", "HEAD:develop")
    git(project, "fetch", "-q", "origin")
    git(project, "reset", "-q", "--hard", "HEAD~1")  # local develop goes stale
    git(project, "checkout", "-q", "-b", "feat/y", "origin/develop")
    write(project, "backend/a.py", "a = 3\n")
    commit_all(project, "backend only")
    assert dry(project) == BACKEND


def test_unknown_option_exits_2(project):
    result = run_check(project, "--bogus")
    assert result.returncode == 2
    assert result.stderr.strip()


def test_non_ascii_untracked_file_counts(project):
    write(project, "frontend/src/ação.ts", "export const a = 1\n")
    assert dry(project) == FRONTEND


def test_non_ascii_committed_file_counts(project):
    write(project, "backend/ação.py", "a = 1\n")
    commit_all(project, "acento")
    assert dry(project) == BACKEND


def test_file_name_with_space_counts(project):
    write(project, "backend/meu arquivo.py", "a = 1\n")
    assert dry(project) == BACKEND
    commit_all(project, "espaco")
    assert dry(project) == BACKEND


def test_moving_a_file_out_of_backend_counts(project):
    (project / "docs").mkdir()
    git(project, "mv", "backend/a.py", "docs/a.py")
    commit_all(project, "move")
    assert dry(project) == BACKEND
