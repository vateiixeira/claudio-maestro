"""Real temporary git repositories for tests."""

import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Teste",
    "GIT_AUTHOR_EMAIL": "teste@example.com",
    "GIT_COMMITTER_NAME": "Teste",
    "GIT_COMMITTER_EMAIL": "teste@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        env=GIT_ENV,
    ).stdout


def make_repo(path: Path, *, branch: str = "main", commit: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    if commit:
        (path / "README.md").write_text("linha 1\nlinha 2\n")
        git(path, "add", "README.md")
        git(path, "commit", "-q", "-m", "inicial")
    return path


@pytest.fixture
def git_home(tmp_path: Path, monkeypatch) -> Path:
    """HOME temporário: o git que o app roda não lê a configuração global de quem testa."""
    home = tmp_path / "git-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


def set_identity(repo: Path) -> None:
    """`user.name`/`user.email` locais: o `run_git` tira as variáveis GIT_* do ambiente."""
    git(repo, "config", "user.name", "Teste")
    git(repo, "config", "user.email", "teste@example.com")


def commit_file(repo: Path, name: str, text: str = "x\n", message: str | None = None) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", "--", name)
    git(repo, "commit", "-q", "-m", message or f"add {name}")
    return git(repo, "rev-parse", "HEAD").strip()
