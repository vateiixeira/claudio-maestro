"""A local 'GitHub' (origin) with release tags, and a clone of it, for the self-updater."""

from pathlib import Path

from git_helpers import git, make_repo


def write_version(repo: Path, version: str) -> None:
    (repo / "pyproject.toml").write_text(f'[project]\nname = "claudio-maestro"\nversion = "{version}"\n')


def commit_release(repo: Path, version: str, *, tag: bool = True, extra: dict[str, str] | None = None) -> None:
    write_version(repo, version)
    for name, text in (extra or {}).items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"versão {version}")
    if tag:
        git(repo, "tag", f"v{version}")


def make_origin_and_clone(tmp_path: Path, *, bump: bool = True, extra: dict[str, str] | None = None) -> tuple[Path, Path]:
    """origin at v0.1.0 (and v0.2.0 when `bump`); clone taken at v0.1.0, on main."""
    origin = make_repo(tmp_path / "origin")
    commit_release(origin, "0.1.0")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    if bump:
        commit_release(origin, "0.2.0", extra=extra)
    return origin, clone


class Publish:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


def which_all(name: str) -> str:
    return f"/fake/bin/{name}"
