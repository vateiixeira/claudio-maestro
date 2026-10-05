"""Release helper for Cláudio Maestro maintainers.

Subcommands:
  suggest   suggests the release kind (patch, minor or atual) and the new version
  check     computes the new version and validates that a release can start
  prepare   bumps the version in pyproject.toml and stamps the CHANGELOG

This is a maintainer tool and only operates on the project's own repository, so it
calls git directly with argument lists and no shell. It deliberately does not use
`run_git` from the app (`backend/claudio_maestro/gitinfo.py`): that function exists
to neutralize hostile configuration in the repositories of the app's users, which
does not apply here. Standard library only; `uv lock`, the tests and the publication
are steps of the `/release` skill (`.claude/skills/release/SKILL.md`).
"""

import argparse
import datetime
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
UNRELEASED_HEADING = "## [Não lançado]"
FEATURE_SECTIONS = ("Adicionado", "Alterado", "Removido")
ALL_SECTIONS = (*FEATURE_SECTIONS, "Corrigido")

Version = tuple[int, int, int]


class ReleaseError(Exception):
    """A validation failed; the message says what to do."""


def fmt(version: Version) -> str:
    return ".".join(str(part) for part in version)


def parse_version(text: str) -> Version:
    match = VERSION_RE.fullmatch(text)
    if not match:
        raise ReleaseError(f"versão inválida: {text!r}; use o formato X.Y.Z (por exemplo, 0.2.0).")
    return int(match[1]), int(match[2]), int(match[3])


# ---- git ---------------------------------------------------------------------


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, capture_output=True, text=True
    )


def fetch(repo: Path) -> None:
    result = git(repo, "fetch", "origin", "--tags", "--quiet", check=False)
    if result.returncode != 0:
        raise ReleaseError(
            "não consegui atualizar de origin (`git fetch origin --tags`): "
            f"{result.stderr.strip()}. Confira a rede e o acesso ao remoto."
        )


def latest_tag(repo: Path) -> Version | None:
    versions = []
    for name in git(repo, "tag", "--list", "v*").stdout.split():
        match = TAG_RE.fullmatch(name)
        if match:
            versions.append((int(match[1]), int(match[2]), int(match[3])))
    return max(versions) if versions else None


def ensure_clean_tree(repo: Path) -> None:
    if git(repo, "status", "--porcelain").stdout.strip():
        raise ReleaseError(
            "a árvore tem alterações não commitadas; commite, guarde ou descarte antes de lançar."
        )


def ensure_head_is_origin_main(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    remote = git(repo, "rev-parse", "--verify", "--quiet", "origin/main", check=False)
    if remote.returncode != 0 or remote.stdout.strip() != head:
        raise ReleaseError(
            "o HEAD não é o mesmo commit de origin/main; crie a worktree de lançamento "
            "a partir de `origin/main` atualizado (ou faça `git rebase origin/main`)."
        )


def ensure_tag_absent(repo: Path, version: str) -> None:
    tag = f"v{version}"
    if git(repo, "tag", "--list", tag).stdout.strip():
        raise ReleaseError(f"a tag {tag} já existe no repositório local.")
    result = git(repo, "ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    if result.returncode != 0:
        raise ReleaseError(
            f"não consegui consultar as tags do remoto: {result.stderr.strip()}."
        )
    if result.stdout.strip():
        raise ReleaseError(f"a tag {tag} já existe no remoto (origin).")


# ---- pyproject e CHANGELOG ---------------------------------------------------


def pyproject_version(repo: Path) -> Version:
    path = repo / "pyproject.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        text = data["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError) as error:
        raise ReleaseError(
            f"não achei `[project] version` em {path}: {error!r}."
        ) from error
    return parse_version(text)


def split_unreleased(text: str) -> tuple[str, str, str]:
    """Return (before, body, after) around the body of "Não lançado".

    `before` ends right after the "Não lançado" heading line; `after` starts at the
    next `## [` heading (or is empty).
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.rstrip() == UNRELEASED_HEADING), None)
    if start is None:
        raise ReleaseError(f"o CHANGELOG.md não tem a seção `{UNRELEASED_HEADING}`.")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## [")), len(lines)
    )
    return "".join(lines[: start + 1]), "".join(lines[start + 1 : end]), "".join(lines[end:])


def unreleased_counts(body: str) -> dict[str, int]:
    """Count `- ` items per `###` subsection of the "Não lançado" body."""
    counts: dict[str, int] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
        elif line.startswith("- "):
            key = current or ""
            counts[key] = counts.get(key, 0) + 1
    return counts


def read_unreleased_counts(repo: Path) -> dict[str, int]:
    path = repo / "CHANGELOG.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseError(f"não consegui ler {path}: {error}.") from error
    counts = unreleased_counts(split_unreleased(text)[1])
    if sum(counts.values()) == 0:
        raise ReleaseError(
            f"a seção `{UNRELEASED_HEADING}` do CHANGELOG.md está vazia; nada para lançar."
        )
    return counts


# ---- cálculo da versão -------------------------------------------------------


def current_state(repo: Path) -> tuple[Version, Version | None]:
    """Fetch, then return (pyproject version, latest tag), failing if inconsistent."""
    fetch(repo)
    current = pyproject_version(repo)
    tag = latest_tag(repo)
    if tag is not None and current < tag:
        raise ReleaseError(
            f"versão inconsistente: o pyproject tem {fmt(current)}, mas a última tag é "
            f"v{fmt(tag)}. Acerte o `version` do pyproject.toml antes de lançar."
        )
    return current, tag


def compute_version(kind: str, current: Version, tag: Version | None) -> str:
    ahead = tag is not None and current > tag
    if kind == "atual":
        if tag is not None and not ahead:
            raise ReleaseError(
                f"a versão {fmt(current)} já foi lançada (é a última tag); "
                "use `patch` ou `minor` para lançar uma versão nova."
            )
        return fmt(current)
    if ahead:
        raise ReleaseError(
            f"a versão {fmt(current)} já está no pyproject e não foi lançada; use `atual`."
        )
    major, minor, patch = current
    return fmt((major, minor + 1, 0) if kind == "minor" else (major, minor, patch + 1))


def describe_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{counts[name]} em {name}" for name in ALL_SECTIONS if counts.get(name))


def check(repo: Path, kind: str) -> tuple[str, list[str]]:
    current, tag = current_state(repo)
    version = compute_version(kind, current, tag)
    ensure_clean_tree(repo)
    ensure_head_is_origin_main(repo)
    ensure_tag_absent(repo, version)
    new = parse_version(version)
    if tag is not None and new <= tag:
        raise ReleaseError(f"a versão {version} não é maior que a última tag (v{fmt(tag)}).")
    counts = read_unreleased_counts(repo)
    warnings = []
    if kind == "patch":
        sections = [name for name in FEATURE_SECTIONS if counts.get(name)]
        if sections:
            warnings.append(f"há itens em {', '.join(sections)}; talvez seja `minor`")
    return version, warnings


def suggest(repo: Path) -> tuple[str, str, str]:
    """Return (kind, version, reason). Does not check the tree or HEAD (that is `check`)."""
    current, tag = current_state(repo)
    if tag is not None and current > tag:
        return "atual", fmt(current), (
            f"a versão {fmt(current)} já está no pyproject e não foi lançada"
        )
    counts = read_unreleased_counts(repo)
    summary = describe_counts(counts)
    if any(counts.get(name) for name in FEATURE_SECTIONS):
        kind, reason = "minor", f"{summary}; na fase 0.x funcionalidade sobe o minor"
    else:
        kind, reason = "patch", f"só correções ({summary})"
    return kind, compute_version(kind, current, tag), reason


# ---- prepare -----------------------------------------------------------------


def bump_pyproject(text: str, version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_project = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
        elif in_project and re.match(r"version\s*=", stripped):
            lines[i] = re.sub(r'"[^"]*"', f'"{version}"', line, count=1)
            return "".join(lines)
    raise ReleaseError("não achei `version = \"...\"` na seção `[project]` do pyproject.toml.")


def stamp_changelog(text: str, version: str, date: str, summary: str) -> tuple[str, str]:
    """Return (new changelog, release notes)."""
    before, body, after = split_unreleased(text)
    if not unreleased_counts(body):
        raise ReleaseError(
            f"a seção `{UNRELEASED_HEADING}` do CHANGELOG.md está vazia; nada para lançar."
        )
    notes = (f"{summary}\n\n" if summary else "") + body.strip("\n") + "\n"
    stamped = f"{before}\n## [{version}] - {date}\n\n{notes}"
    if after:
        stamped += "\n" + after
    return stamped, notes


def prepare(repo: Path, version: str, date: str, summary: str, notes_out: Path) -> None:
    parse_version(version)
    try:
        datetime.date.fromisoformat(date)
    except ValueError as error:
        raise ReleaseError(f"data inválida: {date!r}; use o formato AAAA-MM-DD.") from error
    pyproject = repo / "pyproject.toml"
    changelog = repo / "CHANGELOG.md"
    new_pyproject = bump_pyproject(pyproject.read_text(encoding="utf-8"), version)
    new_changelog, notes = stamp_changelog(
        changelog.read_text(encoding="utf-8"), version, date, summary.strip()
    )
    # Everything is computed above; write the notes first, since that is the write
    # most likely to fail (a bad path), and leave the repository files for last.
    try:
        notes_out.write_text(notes, encoding="utf-8")
        changelog.write_text(new_changelog, encoding="utf-8")
        pyproject.write_text(new_pyproject, encoding="utf-8")
    except OSError as error:
        raise ReleaseError(f"não consegui gravar os arquivos do lançamento: {error}.") from error


# ---- linha de comando --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release.py",
        description=(
            "Apoio ao lançamento de versões. O projeto está em 0.x: correção sobe o patch, "
            "funcionalidade sobe o minor, e `major` não é uma opção."
        ),
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="raiz do repositório")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("suggest", help="sugere o tipo (patch, minor ou atual) e a versão nova")
    check_parser = sub.add_parser("check", help="calcula a versão nova e valida o lançamento")
    check_parser.add_argument(
        "kind",
        choices=["patch", "minor", "atual"],
        help="patch: correção; minor: funcionalidade; atual: versão que já está no pyproject "
        "(major não existe: o projeto está em 0.x)",
    )
    prep = sub.add_parser("prepare", help="troca a versão e carimba o CHANGELOG")
    prep.add_argument("version", help="versão nova, no formato X.Y.Z")
    prep.add_argument("--date", default=None, help="AAAA-MM-DD (padrão: hoje)")
    prep.add_argument("--summary", default="", help="resumo de 1 ou 2 frases da versão")
    prep.add_argument("--notes-out", type=Path, required=True, help="arquivo das notas da release")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.command == "check":
            version, warnings = check(repo, args.kind)
            print(f"version={version}")
            for warning in warnings:
                print(f"aviso: {warning}")
        elif args.command == "suggest":
            kind, version, reason = suggest(repo)
            print(f"suggest={kind}")
            print(f"version={version}")
            print(f"motivo: {reason}")
        else:
            date = args.date or datetime.date.today().isoformat()
            prepare(repo, args.version, date, args.summary, args.notes_out)
            print(f"preparado: {args.version} ({date})")
    except ReleaseError as error:
        print(f"erro: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
