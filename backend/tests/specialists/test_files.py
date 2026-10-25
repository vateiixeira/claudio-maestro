import os
import stat
from pathlib import Path

import pytest

from claudio_maestro.specialists.files import (
    LEARNINGS_MAX_CHARS,
    SKILL_MAX_BYTES,
    InvalidSecretNameError,
    InvalidSecretValueError,
    LearningsTooLongError,
    SkillInvalidError,
    SpecialistFiles,
    parse_skill,
)

FILMES_FRONTMATTER = """---
name: filmes
description: "Acha filmes, mostra as 3 melhores opções de torrent, baixa para o Plex. Use quando o usuário pedir um filme."
metadata: {"openclaw": {"emoji": "🎬", "os": ["linux"], "requires": {"bins": ["python3"]}}}
---

# Filmes

Você usa esta skill para achar filmes.
"""


@pytest.fixture
def files(tmp_path: Path) -> SpecialistFiles:
    return SpecialistFiles(tmp_path / "specialists")


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_create_writes_template_with_frontmatter(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    meta = parse_skill(files.read_skill("filmes"))
    assert meta.name == "Filmes"
    assert meta.description
    text = files.read_skill("filmes")
    for section in ("Quando usar", "Passo a passo", "Regras"):
        assert section in text
    assert mode(files.root / "filmes") == 0o700


def test_create_quotes_names_with_special_characters(files: SpecialistFiles) -> None:
    files.create("x", 'Agente: "teste"\ncom quebra')
    assert parse_skill(files.read_skill("x")).name == 'Agente: "teste"\ncom quebra'


def test_create_twice_fails(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    with pytest.raises(FileExistsError):
        files.create("filmes", "Outro")


def test_parse_skill_accepts_filmes_frontmatter_and_ignores_metadata() -> None:
    meta = parse_skill(FILMES_FRONTMATTER)
    assert meta.name == "filmes"
    assert meta.description.startswith("Acha filmes, mostra as 3 melhores opções")
    assert meta.description.endswith("pedir um filme.")
    assert meta.body.lstrip().startswith("# Filmes")


def test_parse_skill_accepts_unquoted_and_single_quoted_values() -> None:
    meta = parse_skill("---\nname: abc\ndescription: 'Faz algo: bem'\n---\ncorpo\n")
    assert meta.name == "abc"
    assert meta.description == "Faz algo: bem"
    assert meta.body == "corpo\n"
    meta = parse_skill("---\nname: abc\ndescription: Faz algo\n---\n")
    assert meta.description == "Faz algo"


def test_write_skill_returns_meta_and_replaces_file(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    meta = files.write_skill("filmes", FILMES_FRONTMATTER)
    assert meta.name == "filmes"
    assert files.read_skill("filmes") == FILMES_FRONTMATTER
    assert [p.name for p in (files.root / "filmes").iterdir()] == ["SKILL.md"]


def test_write_skill_rejects_missing_frontmatter(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    before = files.read_skill("filmes")
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", "# Sem frontmatter\n")
    assert files.read_skill("filmes") == before


def test_write_skill_rejects_unclosed_frontmatter(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", "---\nname: a\ndescription: b\n# nunca fecha\n")


def test_write_skill_rejects_missing_name(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", "---\ndescription: algo\n---\n")


def test_write_skill_rejects_missing_description(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    before = files.read_skill("filmes")
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", "---\nname: filmes\n---\ncorpo\n")
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", '---\nname: filmes\ndescription: ""\n---\ncorpo\n')
    assert files.read_skill("filmes") == before


def test_write_skill_rejects_over_100kb(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    before = files.read_skill("filmes")
    head = "---\nname: filmes\ndescription: algo\n---\n"
    too_big = head + "x" * (SKILL_MAX_BYTES - len(head) + 1)
    assert len(too_big.encode()) == SKILL_MAX_BYTES + 1
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", too_big)
    assert files.read_skill("filmes") == before
    exact = too_big[:-1]
    files.write_skill("filmes", exact)
    assert files.read_skill("filmes") == exact


def test_write_skill_counts_bytes_not_characters(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    head = "---\nname: filmes\ndescription: algo\n---\n"
    text = head + "ç" * ((SKILL_MAX_BYTES - len(head)) // 2 + 1)
    assert len(text) <= SKILL_MAX_BYTES < len(text.encode())
    with pytest.raises(SkillInvalidError):
        files.write_skill("filmes", text)


def test_learnings_empty_when_missing(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    assert files.read_learnings("filmes") == ""


def test_learnings_cap(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    ok = "a" * LEARNINGS_MAX_CHARS
    files.write_learnings("filmes", ok)
    assert files.read_learnings("filmes") == ok
    with pytest.raises(LearningsTooLongError) as exc:
        files.write_learnings("filmes", "b" * (LEARNINGS_MAX_CHARS + 1))
    assert str(exc.value) == "Passou de 4.000 caracteres. Consolide os aprendizados e tente de novo."
    assert files.read_learnings("filmes") == ok


def test_secrets_file_mode_and_names_only(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    assert files.secret_names("filmes") == []
    files.write_secrets("filmes", {"RADARR_KEY": "abc", "API_TOKEN": 'a=b "c" d\\e\nf'})
    path = files.root / "filmes" / "secrets.env"
    assert mode(path) == 0o600
    assert files.secret_names("filmes") == ["API_TOKEN", "RADARR_KEY"]
    assert files.read_secrets("filmes") == {"RADARR_KEY": "abc", "API_TOKEN": 'a=b "c" d\\e\nf'}
    # None apaga só a chave; as outras ficam.
    files.write_secrets("filmes", {"RADARR_KEY": None, "NOVO": "1"})
    assert files.secret_names("filmes") == ["API_TOKEN", "NOVO"]
    assert files.read_secrets("filmes")["API_TOKEN"] == 'a=b "c" d\\e\nf'
    assert mode(path) == 0o600
    # Apagar uma chave que não existe não é erro.
    files.write_secrets("filmes", {"NAO_EXISTE": None})
    assert files.secret_names("filmes") == ["API_TOKEN", "NOVO"]


def test_secrets_overwrite_value(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"A": "1"})
    files.write_secrets("filmes", {"A": "2"})
    assert files.read_secrets("filmes") == {"A": "2"}


@pytest.mark.parametrize("name", ["lower", "1ABC", "A-B", "A B", "", "A=B"])
def test_secret_invalid_name_rejected_before_writing(files: SpecialistFiles, name: str) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"OK": "1"})
    with pytest.raises(InvalidSecretNameError):
        files.write_secrets("filmes", {"NOVO": "2", name: "x"})
    assert files.read_secrets("filmes") == {"OK": "1"}


def test_secret_name_with_underscore_start_accepted(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"_X1": "v"})
    assert files.secret_names("filmes") == ["_X1"]


def test_secrets_missing_file_reads_empty(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    assert files.read_secrets("filmes") == {}


def test_delete_removes_folder_and_is_idempotent(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"A": "1"})
    files.delete("filmes")
    assert not (files.root / "filmes").exists()
    files.delete("filmes")


@pytest.mark.parametrize("slug", ["../x", "A", "a/b", "", "-a", "a-", "a--b", "a_b", "x" * 41, "..", "."])
def test_slug_outside_root_rejected(files: SpecialistFiles, slug: str) -> None:
    sentinel = files.root.parent / "x"
    for call in (
        lambda: files.create(slug, "N"),
        lambda: files.read_skill(slug),
        lambda: files.write_skill(slug, FILMES_FRONTMATTER),
        lambda: files.read_learnings(slug),
        lambda: files.write_learnings(slug, "a"),
        lambda: files.secret_names(slug),
        lambda: files.write_secrets(slug, {"A": "1"}),
        lambda: files.read_secrets(slug),
        lambda: files.delete(slug),
    ):
        with pytest.raises(ValueError):
            call()
    assert not files.root.exists()
    assert not sentinel.exists()


def test_slug_with_40_chars_accepted(files: SpecialistFiles) -> None:
    files.create("x" * 40, "N")
    assert (files.root / ("x" * 40) / "SKILL.md").is_file()


def test_secret_value_with_unicode_line_separators_survives(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    value = "a b\x85c\x1cdç"
    files.write_secrets("filmes", {"A": value, "B": "2"})
    assert files.read_secrets("filmes") == {"A": value, "B": "2"}


def test_learnings_file_is_aprendizados_md(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    files.write_learnings("filmes", "algo")
    assert (files.root / "filmes" / "aprendizados.md").read_text(encoding="utf-8") == "algo"
    assert not (files.root / "filmes" / "learnings.md").exists()


@pytest.mark.parametrize("value", ["a\x00b", "\x00", 123, object(), b"x", ["a"]])
def test_secret_invalid_value_rejected_before_writing(files: SpecialistFiles, value: object) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"OK": "1"})
    with pytest.raises(InvalidSecretValueError) as exc:
        files.write_secrets("filmes", {"NOVO": "2", "RUIM": value})  # type: ignore[dict-item]
    assert "RUIM" in str(exc.value)
    assert files.read_secrets("filmes") == {"OK": "1"}


def test_secrets_write_reapplies_folder_mode(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    os.chmod(files.root / "filmes", 0o755)
    files.write_secrets("filmes", {"A": "1"})
    assert mode(files.root / "filmes") == 0o700


@pytest.mark.parametrize("name", ["", "   ", "\n\t"])
def test_create_rejects_blank_name(files: SpecialistFiles, name: str) -> None:
    with pytest.raises(ValueError):
        files.create("filmes", name)
    assert not (files.root / "filmes").exists()


@pytest.mark.parametrize("marker", [">", "|", ">-", "|+", ">2", "| "])
def test_parse_skill_rejects_yaml_block_scalars(marker: str) -> None:
    text = f"---\nname: abc\ndescription: {marker}\n  Uma descrição\n  em duas linhas\n---\n"
    with pytest.raises(SkillInvalidError, match="uma linha"):
        parse_skill(text)
    text = f"---\nname: {marker}\n  abc\ndescription: ok\n---\n"
    with pytest.raises(SkillInvalidError, match="uma linha"):
        parse_skill(text)


def test_parse_skill_accepts_quoted_block_marker_text() -> None:
    meta = parse_skill('---\nname: abc\ndescription: ">"\n---\n')
    assert meta.description == ">"


RESERVED_TEXT = "Este nome é reservado pelo sistema. Escolha outro nome para o segredo."


@pytest.mark.parametrize(
    "name",
    [
        "PATH", "HOME", "USER", "SHELL", "PWD", "TMPDIR", "NODE_OPTIONS",
        "CLAUDE", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CONFIG_DIR",
        "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "LD_PRELOAD", "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "PYTHON", "PYTHONSTARTUP",
        "MAESTRO_DATA_DIR", "MAESTRO_",
    ],
)
def test_secret_reserved_name_rejected_with_a_fixed_message(files: SpecialistFiles, name: str) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {"OK": "1"})

    with pytest.raises(InvalidSecretNameError) as info:
        files.write_secrets("filmes", {"NOVO": "2", name: "x"})

    assert str(info.value) == RESERVED_TEXT
    assert files.read_secrets("filmes") == {"OK": "1"}


@pytest.mark.parametrize("name", ["PATHS", "MY_PATH", "HOMEPAGE", "USERNAME", "ANTHROPIC", "LD", "MAESTRO", "NODE_ENV"])
def test_secret_names_that_only_look_reserved_are_accepted(files: SpecialistFiles, name: str) -> None:
    files.create("filmes", "Filmes")
    files.write_secrets("filmes", {name: "v"})
    assert files.secret_names("filmes") == [name]


def test_reserved_names_in_the_file_never_reach_the_session(files: SpecialistFiles) -> None:
    files.create("filmes", "Filmes")
    (files.root / "filmes" / "secrets.env").write_text(
        'PATH="/tmp/mal"\nLD_PRELOAD="x.so"\nTOKEN="ok"\n', encoding="utf-8"
    )

    assert files.read_secrets("filmes") == {"TOKEN": "ok"}
    files.write_secrets("filmes", {"PATH": None})  # removing one is harmless
    assert files.secret_names("filmes") == ["TOKEN"]


def test_run_text_is_private_atomic_and_removed_idempotently(files):
    files.create("filmes", "Filmes")
    folder = files.root / "filmes"
    folder.chmod(0o755)
    files.write_run_text("filmes", 12, "Pedido com ação 🎬\nna linha seguinte")
    assert files.read_run_text("filmes", 12) == "Pedido com ação 🎬\nna linha seguinte"
    assert mode(folder / "pending-12.txt") == 0o600
    assert mode(folder) == 0o700
    files.write_run_text("filmes", 12, "Outro pedido")
    assert files.read_run_text("filmes", 12) == "Outro pedido"
    assert sorted(p.name for p in folder.iterdir()) == ["SKILL.md", "pending-12.txt"]
    files.delete_run_text("filmes", 12)
    files.delete_run_text("filmes", 12)
    with pytest.raises(FileNotFoundError):
        files.read_run_text("filmes", 12)


@pytest.mark.parametrize("run_id", [0, -1, True, "../secrets.env", "1", 1.0])
def test_run_text_rejects_invalid_ids_before_disk_access(files, run_id):
    for call in (
        lambda: files.write_run_text("filmes", run_id, "texto"),
        lambda: files.read_run_text("filmes", run_id),
        lambda: files.delete_run_text("filmes", run_id),
    ):
        with pytest.raises(ValueError):
            call()
    assert not files.root.exists()


def test_run_text_refuses_invalid_slugs_and_symlink_folders(files, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    files.root.mkdir()
    (files.root / "filmes").symlink_to(outside, target_is_directory=True)
    for slug in ("../outside", "filmes"):
        for call in (
            lambda: files.write_run_text(slug, 1, "texto"),
            lambda: files.read_run_text(slug, 1),
            lambda: files.delete_run_text(slug, 1),
        ):
            with pytest.raises((ValueError, OSError)):
                call()
    assert list(outside.iterdir()) == []


def test_run_text_never_reads_a_symlink_and_replaces_only_the_link(files, tmp_path):
    files.create("filmes", "Filmes")
    outside = tmp_path / "private"
    outside.write_text("Segredo", encoding="utf-8")
    target = files.root / "filmes" / "pending-1.txt"
    target.symlink_to(outside)
    with pytest.raises(OSError):
        files.read_run_text("filmes", 1)
    files.write_run_text("filmes", 1, "Pedido")
    assert files.read_run_text("filmes", 1) == "Pedido"
    assert outside.read_text(encoding="utf-8") == "Segredo"


def test_run_text_rejects_large_or_empty_payloads_and_bounds_reads(files):
    files.create("filmes", "Filmes")
    files.write_run_text("filmes", 1, "🎬" * 5000)
    assert files.read_run_text("filmes", 1) == "🎬" * 5000
    for text in ("", "   ", "x" * 5001):
        with pytest.raises(ValueError):
            files.write_run_text("filmes", 1, text)
    (files.root / "filmes" / "pending-1.txt").write_bytes(b"x" * 20001)
    with pytest.raises(ValueError):
        files.read_run_text("filmes", 1)


def test_run_text_refuses_non_regular_files_without_waiting(files):
    files.create("filmes", "Filmes")
    os.mkfifo(files.root / "filmes" / "pending-1.txt")
    with pytest.raises(ValueError):
        files.read_run_text("filmes", 1)


def test_message_payload_keeps_images_private_and_previews_long_unicode_text(files):
    files.create("filmes", "Filmes")
    text = "🎬" * 100_000
    images = [{"media_type": "image/png", "data": "payload" * 100_000}]
    files.write_message("filmes", 1, text, images)
    assert mode(files.root / "filmes" / "pending-1.txt") == 0o600
    assert files.read_message("filmes", 1) == (text, images)
    assert files.message_preview("filmes", 1) == "🎬" * 500 + "…"


def test_message_preview_rejects_symlinks_and_non_regular_files(files, tmp_path):
    files.create("filmes", "Filmes")
    outside = tmp_path / "private.json"
    outside.write_text('{"text": "Segredo", "images": []}')
    target = files.root / "filmes" / "pending-1.txt"
    target.symlink_to(outside)
    with pytest.raises(OSError):
        files.message_preview("filmes", 1)
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(ValueError):
        files.message_preview("filmes", 1)


def test_message_preview_accepts_the_maximum_json_escape_expansion(files):
    files.create("filmes", "Filmes")
    text = "\x00" * 100_000
    files.write_message("filmes", 1, text, [])
    assert files.message_preview("filmes", 1) == text[:500] + "…"
