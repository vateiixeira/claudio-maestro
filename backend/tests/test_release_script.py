"""Tests for scripts/release.py, using real temporary git repositories.

Each test repository has a local bare repository as `origin`; nothing touches the
network or GitHub.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release.py"
_spec = importlib.util.spec_from_file_location("release_script", SCRIPT)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)

PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
description = "Demo"

[tool.other]
version = "9.9.9"
"""

CHANGELOG = """\
# Changelog

Texto de abertura.

## [Não lançado]

### Adicionado

- Item novo A.
- Item novo B.

### Corrigido

- Correção X.

## [0.1.0] - 2026-10-01

Primeira versão pública.

### Adicionado

- Algo antigo.
"""


FIXES_ONLY = CHANGELOG.replace(
    "### Adicionado\n\n- Item novo A.\n- Item novo B.\n\n", "", 1
)


def run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def commit_all(repo: Path, message: str = "mudança") -> None:
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", message)


@pytest.fixture(autouse=True)
def isolated_git_env(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


def make_project(tmp_path: Path, *, changelog: str = CHANGELOG, tag: str | None = "v0.1.0") -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = tmp_path / "work"
    repo.mkdir()
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.name", "Teste")
    run(repo, "config", "user.email", "teste@example.com")
    run(repo, "config", "commit.gpgsign", "false")
    run(repo, "config", "tag.gpgsign", "false")
    (repo / "pyproject.toml").write_text(PYPROJECT)
    (repo / "CHANGELOG.md").write_text(changelog)
    commit_all(repo, "inicial")
    run(repo, "remote", "add", "origin", str(bare))
    run(repo, "push", "-q", "-u", "origin", "main")
    if tag:
        run(repo, "tag", "-a", tag, "-m", tag)
        run(repo, "push", "-q", "origin", tag)
    return repo


def set_version(repo: Path, version: str) -> None:
    path = repo / "pyproject.toml"
    path.write_text(path.read_text().replace('version = "0.1.0"', f'version = "{version}"', 1))
    commit_all(repo, "versão")
    run(repo, "push", "-q", "origin", "main")


@pytest.fixture
def repo(tmp_path):
    return make_project(tmp_path)


# ---- check: cálculo da versão ----------------------------------------------


def test_check_minor(repo):
    version, warnings = release.check(repo, "minor")
    assert version == "0.2.0"
    assert warnings == []


def test_check_patch_warns_about_added_items(repo):
    version, warnings = release.check(repo, "patch")
    assert version == "0.1.1"
    assert warnings == ["há itens em Adicionado; talvez seja `minor`"]


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("Alterado", "há itens em Alterado; talvez seja `minor`"),
        ("Removido", "há itens em Removido; talvez seja `minor`"),
    ],
)
def test_check_patch_warns_about_changed_or_removed_items(tmp_path, section, expected):
    changelog = CHANGELOG.replace(
        "### Adicionado\n\n- Item novo A.\n- Item novo B.\n",
        f"### {section}\n\n- Mudou algo.\n",
        1,
    )
    repo = make_project(tmp_path, changelog=changelog)
    version, warnings = release.check(repo, "patch")
    assert version == "0.1.1"
    assert warnings == [expected]


def test_check_patch_warning_lists_every_section_with_items(tmp_path):
    changelog = CHANGELOG.replace(
        "### Corrigido\n", "### Alterado\n\n- Mudou algo.\n\n### Corrigido\n", 1
    )
    repo = make_project(tmp_path, changelog=changelog)
    _, warnings = release.check(repo, "patch")
    assert warnings == ["há itens em Adicionado, Alterado; talvez seja `minor`"]


def test_check_patch_only_fixes_has_no_warning(tmp_path):
    changelog = FIXES_ONLY
    repo = make_project(tmp_path, changelog=changelog)
    assert release.check(repo, "patch")[1] == []


def test_check_patch_without_added_items_has_no_warning(tmp_path):
    changelog = CHANGELOG.replace("### Adicionado\n\n- Item novo A.\n- Item novo B.\n\n", "", 1)
    repo = make_project(tmp_path, changelog=changelog)
    version, warnings = release.check(repo, "patch")
    assert version == "0.1.1"
    assert warnings == []


def test_check_minor_resets_patch(tmp_path):
    repo = make_project(tmp_path, tag="v0.3.4")
    set_version(repo, "0.3.4")
    version, _ = release.check(repo, "minor")
    assert version == "0.4.0"


def test_check_picks_highest_tag_and_ignores_malformed_ones(repo):
    for name in ("v0.1.10", "v0.1.9", "vfoo", "v1.2", "v0.1.0-rc1", "0.9.9"):
        run(repo, "tag", name)
    run(repo, "push", "-q", "origin", "--tags")
    set_version(repo, "0.1.10")
    version, _ = release.check(repo, "patch")
    assert version == "0.1.11"


def test_check_atual_uses_pyproject_version(repo):
    set_version(repo, "0.2.0")
    version, _ = release.check(repo, "atual")
    assert version == "0.2.0"


def test_check_without_tags_uses_pyproject_as_base(tmp_path):
    repo = make_project(tmp_path, tag=None)
    assert release.check(repo, "minor")[0] == "0.2.0"
    assert release.check(repo, "atual")[0] == "0.1.0"


# ---- check: falhas -----------------------------------------------------------


def test_check_patch_fails_when_pyproject_is_ahead_of_tag(repo):
    set_version(repo, "0.2.0")
    with pytest.raises(release.ReleaseError, match=r"0\.2\.0.*não foi lançada.*atual"):
        release.check(repo, "patch")
    with pytest.raises(release.ReleaseError, match="atual"):
        release.check(repo, "minor")


def test_check_patch_fails_when_pyproject_is_behind_tag(repo):
    run(repo, "tag", "v0.1.5")
    run(repo, "push", "-q", "origin", "v0.1.5")
    with pytest.raises(release.ReleaseError, match="inconsistente"):
        release.check(repo, "patch")
    with pytest.raises(release.ReleaseError, match="inconsistente"):
        release.check(repo, "atual")


def test_check_atual_fails_when_pyproject_equals_tag(repo):
    with pytest.raises(release.ReleaseError, match=r"0\.1\.0.*já foi lançada"):
        release.check(repo, "atual")


def test_check_fails_with_dirty_tree(repo):
    (repo / "sujo.txt").write_text("x")
    with pytest.raises(release.ReleaseError, match="árvore.*alterações"):
        release.check(repo, "minor")


def test_check_fails_with_modified_tracked_file(repo):
    (repo / "CHANGELOG.md").write_text(CHANGELOG + "\nmais\n")
    with pytest.raises(release.ReleaseError, match="árvore"):
        release.check(repo, "minor")


def test_check_fails_when_head_is_ahead_of_origin_main(repo):
    (repo / "a.txt").write_text("a")
    commit_all(repo)
    with pytest.raises(release.ReleaseError, match="origin/main"):
        release.check(repo, "minor")


def test_check_fails_when_head_is_behind_origin_main(repo):
    (repo / "a.txt").write_text("a")
    commit_all(repo)
    run(repo, "push", "-q", "origin", "main")
    run(repo, "reset", "-q", "--hard", "HEAD~1")
    with pytest.raises(release.ReleaseError, match="origin/main"):
        release.check(repo, "minor")


def test_check_fails_when_origin_main_moved_after_local_clone(repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    run(other, "config", "user.name", "Outro")
    run(other, "config", "user.email", "outro@example.com")
    run(other, "config", "commit.gpgsign", "false")
    (other / "b.txt").write_text("b")
    commit_all(other)
    run(other, "push", "-q", "origin", "main")
    # O fetch do check traz o avanço e o HEAD local deixa de ser o origin/main.
    with pytest.raises(release.ReleaseError, match="origin/main"):
        release.check(repo, "minor")


def test_check_fails_when_unreleased_is_empty(tmp_path):
    changelog = CHANGELOG.split("### Adicionado")[0] + "## [0.1.0] - 2026-10-01\n\n- Algo.\n"
    repo = make_project(tmp_path, changelog=changelog)
    with pytest.raises(release.ReleaseError, match="Não lançado.*vazia"):
        release.check(repo, "minor")


def test_check_fails_when_unreleased_has_only_headings(tmp_path):
    changelog = CHANGELOG.replace("- Item novo A.\n- Item novo B.\n", "").replace("- Correção X.\n", "")
    repo = make_project(tmp_path, changelog=changelog)
    with pytest.raises(release.ReleaseError, match="Não lançado.*vazia"):
        release.check(repo, "minor")


def test_check_fails_when_unreleased_section_is_missing(tmp_path):
    repo = make_project(tmp_path, changelog="# Changelog\n\n## [0.1.0] - 2026-10-01\n\n- Algo.\n")
    with pytest.raises(release.ReleaseError, match="Não lançado"):
        release.check(repo, "minor")


def test_ensure_tag_absent_detects_local_tag(repo):
    run(repo, "tag", "v0.2.0")
    with pytest.raises(release.ReleaseError, match=r"v0\.2\.0.*local"):
        release.ensure_tag_absent(repo, "0.2.0")


def test_ensure_tag_absent_detects_remote_only_tag(repo, tmp_path):
    run(tmp_path / "origin.git", "tag", "v0.2.0", "main")
    with pytest.raises(release.ReleaseError, match=r"v0\.2\.0.*remoto"):
        release.ensure_tag_absent(repo, "0.2.0")


def test_ensure_tag_absent_passes_when_absent(repo):
    release.ensure_tag_absent(repo, "0.2.0")


def test_check_fetches_remote_tags(repo, tmp_path):
    # A tag criada só no remoto entra na conta depois do fetch do check.
    run(tmp_path / "origin.git", "tag", "v0.1.1", "main")
    with pytest.raises(release.ReleaseError, match="inconsistente"):
        release.check(repo, "patch")


# ---- check: linha de comando -------------------------------------------------


def test_main_check_prints_version_and_warning(repo, capsys):
    assert release.main(["--repo", str(repo), "check", "patch"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "version=0.1.1"
    assert out[1] == "aviso: há itens em Adicionado; talvez seja `minor`"


def test_main_check_failure_exits_one_with_message(repo, capsys):
    (repo / "sujo.txt").write_text("x")
    assert release.main(["--repo", str(repo), "check", "minor"]) == 1
    captured = capsys.readouterr()
    assert "version=" not in captured.out
    assert "erro:" in captured.err


def test_major_is_not_an_option(repo, capsys):
    with pytest.raises(SystemExit) as exc:
        release.main(["--repo", str(repo), "check", "major"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        release.main(["--help"])
    assert "0.x" in capsys.readouterr().out


# ---- prepare -----------------------------------------------------------------


def prepare(repo: Path, tmp_path: Path, *extra: str, version: str = "0.2.0") -> tuple[int, Path]:
    notes = tmp_path / "notas.md"
    code = release.main(
        ["--repo", str(repo), "prepare", version, "--date", "2026-10-05", "--notes-out", str(notes), *extra]
    )
    return code, notes


def test_prepare_updates_only_project_version(repo, tmp_path):
    code, _ = prepare(repo, tmp_path)
    assert code == 0
    assert (repo / "pyproject.toml").read_text() == PYPROJECT.replace(
        'version = "0.1.0"', 'version = "0.2.0"', 1
    )


def test_prepare_rewrites_changelog_without_summary(repo, tmp_path):
    prepare(repo, tmp_path)
    expected = CHANGELOG.replace(
        "## [Não lançado]\n\n",
        "## [Não lançado]\n\n## [0.2.0] - 2026-10-05\n\n",
        1,
    )
    assert (repo / "CHANGELOG.md").read_text() == expected


def test_prepare_rewrites_changelog_with_summary(repo, tmp_path):
    prepare(repo, tmp_path, "--summary", "  Resumo da versão.  ")
    expected = CHANGELOG.replace(
        "## [Não lançado]\n\n",
        "## [Não lançado]\n\n## [0.2.0] - 2026-10-05\n\nResumo da versão.\n\n",
        1,
    )
    assert (repo / "CHANGELOG.md").read_text() == expected


def test_prepare_writes_notes_without_heading(repo, tmp_path):
    _, notes = prepare(repo, tmp_path, "--summary", "Resumo da versão.")
    assert notes.read_text() == (
        "Resumo da versão.\n\n"
        "### Adicionado\n\n- Item novo A.\n- Item novo B.\n\n"
        "### Corrigido\n\n- Correção X.\n"
    )


def test_prepare_notes_without_summary(repo, tmp_path):
    _, notes = prepare(repo, tmp_path)
    assert notes.read_text().startswith("### Adicionado\n")
    assert "## [" not in notes.read_text()


def test_prepare_with_unreleased_as_last_section(tmp_path):
    changelog = "# Changelog\n\n## [Não lançado]\n\n### Corrigido\n\n- Só isto.\n"
    repo = make_project(tmp_path, changelog=changelog)
    code, notes = prepare(repo, tmp_path)
    assert code == 0
    assert (repo / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## [Não lançado]\n\n## [0.2.0] - 2026-10-05\n\n### Corrigido\n\n- Só isto.\n"
    )
    assert notes.read_text() == "### Corrigido\n\n- Só isto.\n"


def test_prepare_default_date_is_today(repo, tmp_path):
    import datetime

    notes = tmp_path / "n.md"
    assert release.main(["--repo", str(repo), "prepare", "0.2.0", "--notes-out", str(notes)]) == 0
    assert f"## [0.2.0] - {datetime.date.today().isoformat()}" in (repo / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("bad", ["1.0", "v0.2.0", "0.2.x", "abc", "0.2.0-rc1", ""])
def test_prepare_rejects_invalid_version(repo, tmp_path, capsys, bad):
    code, notes = prepare(repo, tmp_path, version=bad)
    assert code == 1
    assert "erro:" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text() == PYPROJECT
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG
    assert not notes.exists()


def test_prepare_rejects_invalid_date(repo, tmp_path, capsys):
    notes = tmp_path / "n.md"
    code = release.main(
        ["--repo", str(repo), "prepare", "0.2.0", "--date", "05/10/2026", "--notes-out", str(notes)]
    )
    assert code == 1
    assert "data" in capsys.readouterr().err
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG


def test_prepare_rejects_empty_unreleased(tmp_path, capsys):
    changelog = CHANGELOG.replace("- Item novo A.\n- Item novo B.\n", "").replace("- Correção X.\n", "")
    repo = make_project(tmp_path, changelog=changelog)
    code, notes = prepare(repo, tmp_path)
    assert code == 1
    assert "vazia" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text() == PYPROJECT
    assert (repo / "CHANGELOG.md").read_text() == changelog
    assert not notes.exists()


def test_prepare_rejects_pyproject_without_project_version(tmp_path, capsys):
    repo = make_project(tmp_path)
    (repo / "pyproject.toml").write_text('[tool.other]\nversion = "9.9.9"\n')
    code, _ = prepare(repo, tmp_path)
    assert code == 1
    assert "pyproject" in capsys.readouterr().err
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG


# ---- suggest -----------------------------------------------------------------


def test_suggest_minor_when_there_are_added_items(repo):
    kind, version, reason = release.suggest(repo)
    assert (kind, version) == ("minor", "0.2.0")
    assert reason == "2 em Adicionado, 1 em Corrigido; na fase 0.x funcionalidade sobe o minor"


def test_suggest_minor_when_only_changed_items(tmp_path):
    changelog = FIXES_ONLY.replace("### Corrigido\n", "### Alterado\n\n- Mudou.\n\n### Corrigido\n", 1)
    repo = make_project(tmp_path, changelog=changelog)
    kind, version, reason = release.suggest(repo)
    assert (kind, version) == ("minor", "0.2.0")
    assert reason.startswith("1 em Alterado, 1 em Corrigido")


def test_suggest_minor_when_only_removed_items(tmp_path):
    changelog = FIXES_ONLY.replace("### Corrigido\n", "### Removido\n\n- Saiu.\n\n### Corrigido\n", 1)
    repo = make_project(tmp_path, changelog=changelog)
    kind, _, reason = release.suggest(repo)
    assert kind == "minor"
    assert reason.startswith("1 em Removido, 1 em Corrigido")


def test_suggest_patch_when_only_fixes(tmp_path):
    repo = make_project(tmp_path, changelog=FIXES_ONLY)
    kind, version, reason = release.suggest(repo)
    assert (kind, version) == ("patch", "0.1.1")
    assert reason == "só correções (1 em Corrigido)"


def test_suggest_atual_when_pyproject_is_ahead_of_tag(repo):
    set_version(repo, "0.2.0")
    kind, version, reason = release.suggest(repo)
    assert (kind, version) == ("atual", "0.2.0")
    assert reason == "a versão 0.2.0 já está no pyproject e não foi lançada"


def test_suggest_atual_wins_over_changelog_contents(tmp_path):
    repo = make_project(tmp_path, changelog=FIXES_ONLY)
    set_version(repo, "0.1.1")
    assert release.suggest(repo)[0] == "atual"


def test_suggest_fails_when_pyproject_is_behind_tag(repo):
    run(repo, "tag", "v0.1.5")
    run(repo, "push", "-q", "origin", "v0.1.5")
    with pytest.raises(release.ReleaseError, match="inconsistente"):
        release.suggest(repo)


def test_suggest_fails_when_nothing_to_release(tmp_path):
    changelog = CHANGELOG.replace("- Item novo A.\n- Item novo B.\n", "").replace("- Correção X.\n", "")
    repo = make_project(tmp_path, changelog=changelog)
    with pytest.raises(release.ReleaseError, match="nada para lançar"):
        release.suggest(repo)


def test_suggest_does_not_require_clean_tree_or_synced_head(repo):
    (repo / "sujo.txt").write_text("x")
    (repo / "a.txt").write_text("a")
    commit_all(repo)
    assert release.suggest(repo)[0] == "minor"


def test_suggest_without_tags_uses_pyproject_as_base(tmp_path):
    repo = make_project(tmp_path, tag=None)
    kind, version, _ = release.suggest(repo)
    assert (kind, version) == ("minor", "0.2.0")


def test_main_suggest_prints_three_lines(repo, capsys):
    assert release.main(["--repo", str(repo), "suggest"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "suggest=minor"
    assert out[1] == "version=0.2.0"
    assert out[2].startswith("motivo: 2 em Adicionado, 1 em Corrigido")


def test_main_suggest_failure_exits_one(tmp_path, capsys):
    changelog = CHANGELOG.replace("- Item novo A.\n- Item novo B.\n", "").replace("- Correção X.\n", "")
    repo = make_project(tmp_path, changelog=changelog)
    assert release.main(["--repo", str(repo), "suggest"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "erro:" in captured.err


def test_prepare_writes_nothing_when_notes_file_cannot_be_written(repo, tmp_path, capsys):
    notes = tmp_path / "nao-existe" / "notas.md"
    code = release.main(
        ["--repo", str(repo), "prepare", "0.2.0", "--date", "2026-10-05", "--notes-out", str(notes)]
    )
    assert code == 1
    assert "erro:" in capsys.readouterr().err
    assert (repo / "pyproject.toml").read_text() == PYPROJECT
    assert (repo / "CHANGELOG.md").read_text() == CHANGELOG
