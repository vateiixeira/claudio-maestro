"""Real temporary git repositories for tests."""

import subprocess
from pathlib import Path

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
