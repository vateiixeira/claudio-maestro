import os
import stat
from pathlib import Path

import pytest

from claudio_maestro.org.definition import DEFINITION_MAX_BYTES, DefinitionError
from claudio_maestro.org.files import (
    MEMORY_MAX_CHARS,
    WAKE_TEXT_MAX_CHARS,
    AgentFiles,
    InvalidSecretNameError,
    InvalidSecretValueError,
    MemoryTooLongError,
    SecretsFileError,
)

CTO = """---
name: CTO
description: Coordena o trabalho de engenharia.
model: opus
---
Você é o CTO do projeto.
"""

OTHER = "---\nname: Outro\n---\nOutro prompt.\n"


@pytest.fixture
def files(tmp_path: Path) -> AgentFiles:
    return AgentFiles(tmp_path / "agents")


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_create_makes_folder_700_with_definition(files: AgentFiles) -> None:
    definition = files.create("cto", CTO)
    assert definition.name == "CTO"
    assert definition.model == "opus"
    assert mode(files.root / "cto") == 0o700
    assert mode(files.root / "cto" / "AGENT.md") == 0o600
    assert files.read_definition_text("cto") == CTO
    assert files.read_definition("cto") == definition
    assert files.folder("cto") == files.root / "cto"


def test_create_refuses_existing_folder_and_keeps_it(files: AgentFiles) -> None:
    files.create("cto", CTO)
    with pytest.raises(FileExistsError):
        files.create("cto", OTHER)
    assert files.read_definition_text("cto") == CTO


def test_create_refuses_invalid_text_without_creating_the_folder(files: AgentFiles) -> None:
    with pytest.raises(DefinitionError):
        files.create("cto", "# sem cabeçalho\n")
    assert not (files.root / "cto").exists()


def test_create_does_not_follow_a_symlink_in_the_slug_place(files: AgentFiles, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    files.root.mkdir()
    (files.root / "cto").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileExistsError):
        files.create("cto", CTO)
    assert list(outside.iterdir()) == []


def test_write_definition_rejects_invalid_and_keeps_old(files: AgentFiles) -> None:
    files.create("cto", CTO)
    for bad in ("# sem cabeçalho\n", "---\nname: X\nmodelo: opus\n---\ncorpo\n", "---\nname: X\n---\n"):
        with pytest.raises(DefinitionError):
            files.write_definition("cto", bad)
    assert files.read_definition_text("cto") == CTO
    assert [p.name for p in (files.root / "cto").iterdir()] == ["AGENT.md"]


def test_write_definition_replaces_atomically_and_returns_definition(files: AgentFiles) -> None:
    files.create("cto", CTO)
    definition = files.write_definition("cto", OTHER)
    assert definition.name == "Outro"
    assert files.read_definition_text("cto") == OTHER
    assert mode(files.root / "cto" / "AGENT.md") == 0o600
    assert [p.name for p in (files.root / "cto").iterdir()] == ["AGENT.md"]


def test_write_definition_rejects_over_100kb(files: AgentFiles) -> None:
    files.create("cto", CTO)
    head = "---\nname: X\n---\n"
    too_big = head + "x" * (DEFINITION_MAX_BYTES - len(head) + 1)
    with pytest.raises(DefinitionError):
        files.write_definition("cto", too_big)
    assert files.read_definition_text("cto") == CTO


def test_read_definition_of_an_oversized_or_non_utf8_file_is_a_definition_error(files: AgentFiles) -> None:
    files.create("cto", CTO)
    path = files.root / "cto" / "AGENT.md"
    path.write_bytes(b"---\nname: X\n---\n" + b"x" * (DEFINITION_MAX_BYTES + 1))
    with pytest.raises(DefinitionError):
        files.read_definition_text("cto")
    path.write_bytes(b"---\nname: \xff\n---\ncorpo\n")
    with pytest.raises(DefinitionError):
        files.read_definition_text("cto")


def test_read_definition_never_follows_a_symlink(files: AgentFiles, tmp_path: Path) -> None:
    files.create("cto", CTO)
    outside = tmp_path / "private.md"
    outside.write_text("segredo", encoding="utf-8")
    path = files.root / "cto" / "AGENT.md"
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(OSError):
        files.read_definition_text("cto")


def test_missing_definition_raises_file_not_found(files: AgentFiles) -> None:
    files.create("cto", CTO)
    (files.root / "cto" / "AGENT.md").unlink()
    with pytest.raises(FileNotFoundError):
        files.read_definition_text("cto")


def test_memory_empty_when_missing_then_roundtrip(files: AgentFiles) -> None:
    files.create("cto", CTO)
    assert files.read_memory("cto") == ""
    files.write_memory("cto", "Aprendi isto 🎬\ne aquilo.")
    assert files.read_memory("cto") == "Aprendi isto 🎬\ne aquilo."
    assert (files.root / "cto" / "memoria.md").read_text(encoding="utf-8") == "Aprendi isto 🎬\ne aquilo."
    assert not (files.root / "cto" / "aprendizados.md").exists()


def test_memory_cap(files: AgentFiles) -> None:
    files.create("cto", CTO)
    ok = "a" * MEMORY_MAX_CHARS
    files.write_memory("cto", ok)
    assert files.read_memory("cto") == ok
    with pytest.raises(MemoryTooLongError) as exc:
        files.write_memory("cto", "b" * (MEMORY_MAX_CHARS + 1))
    assert str(exc.value) == "Passou de 4.000 caracteres. Consolide a memória e tente de novo."
    assert files.read_memory("cto") == ok


def test_memory_write_replaces_a_symlink_instead_of_following_it(files: AgentFiles, tmp_path: Path) -> None:
    files.create("cto", CTO)
    outside = tmp_path / "private.txt"
    outside.write_text("Segredo", encoding="utf-8")
    (files.root / "cto" / "memoria.md").symlink_to(outside)
    with pytest.raises(OSError):
        files.read_memory("cto")
    files.write_memory("cto", "nova")
    assert files.read_memory("cto") == "nova"
    assert outside.read_text(encoding="utf-8") == "Segredo"


def test_secrets_file_mode_and_names_only(files: AgentFiles) -> None:
    files.create("cto", CTO)
    assert files.secret_names("cto") == []
    files.write_secrets("cto", {"RADARR_KEY": "abc", "API_TOKEN": 'a=b "c" d\\e\nf'})
    path = files.root / "cto" / "secrets.env"
    assert mode(path) == 0o600
    assert files.secret_names("cto") == ["API_TOKEN", "RADARR_KEY"]
    assert files.read_secrets("cto") == {"RADARR_KEY": "abc", "API_TOKEN": 'a=b "c" d\\e\nf'}
    files.write_secrets("cto", {"RADARR_KEY": None, "NOVO": "1"})
    assert files.secret_names("cto") == ["API_TOKEN", "NOVO"]
    assert files.read_secrets("cto")["API_TOKEN"] == 'a=b "c" d\\e\nf'
    assert mode(path) == 0o600
    files.write_secrets("cto", {"NAO_EXISTE": None})
    assert files.secret_names("cto") == ["API_TOKEN", "NOVO"]
    assert [p.name for p in (files.root / "cto").iterdir() if p.name.startswith(".")] == []


def test_secrets_are_stored_one_json_string_per_line(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"B": "x\ny", "A": "z"})
    raw = (files.root / "cto" / "secrets.env").read_text(encoding="utf-8")
    assert raw == 'A="z"\nB="x\\ny"\n'


def test_secrets_overwrite_value(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"A": "1"})
    files.write_secrets("cto", {"A": "2"})
    assert files.read_secrets("cto") == {"A": "2"}


def test_secrets_missing_file_reads_empty(files: AgentFiles) -> None:
    files.create("cto", CTO)
    assert files.read_secrets("cto") == {}


@pytest.mark.parametrize("name", ["lower", "1ABC", "A-B", "A B", "", "A=B"])
def test_secret_invalid_name_rejected_before_writing(files: AgentFiles, name: str) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"OK": "1"})
    with pytest.raises(InvalidSecretNameError):
        files.write_secrets("cto", {"NOVO": "2", name: "x"})
    assert files.read_secrets("cto") == {"OK": "1"}


def test_secret_name_with_underscore_start_accepted(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"_X1": "v"})
    assert files.secret_names("cto") == ["_X1"]


@pytest.mark.parametrize("value", ["a\x00b", "\x00", 123, object(), b"x", ["a"]])
def test_secret_invalid_value_rejected_before_writing(files: AgentFiles, value: object) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"OK": "1"})
    with pytest.raises(InvalidSecretValueError) as exc:
        files.write_secrets("cto", {"NOVO": "2", "RUIM": value})  # type: ignore[dict-item]
    assert "RUIM" in str(exc.value)
    assert files.read_secrets("cto") == {"OK": "1"}


def test_secret_value_with_unicode_line_separators_survives(files: AgentFiles) -> None:
    files.create("cto", CTO)
    value = "a b\x85c\x1cdç"
    files.write_secrets("cto", {"A": value, "B": "2"})
    assert files.read_secrets("cto") == {"A": value, "B": "2"}


def test_secrets_write_reapplies_folder_mode(files: AgentFiles) -> None:
    files.create("cto", CTO)
    os.chmod(files.root / "cto", 0o755)
    files.write_secrets("cto", {"A": "1"})
    assert mode(files.root / "cto") == 0o700


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
def test_secrets_reserved_names_refused(files: AgentFiles, name: str) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"OK": "1"})
    with pytest.raises(InvalidSecretNameError) as info:
        files.write_secrets("cto", {"NOVO": "2", name: "x"})
    assert str(info.value) == RESERVED_TEXT
    assert files.read_secrets("cto") == {"OK": "1"}


@pytest.mark.parametrize("name", ["PATHS", "MY_PATH", "HOMEPAGE", "USERNAME", "ANTHROPIC", "LD", "MAESTRO", "NODE_ENV"])
def test_secret_names_that_only_look_reserved_are_accepted(files: AgentFiles, name: str) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {name: "v"})
    assert files.secret_names("cto") == [name]


def test_read_secrets_skips_reserved_on_disk(files: AgentFiles) -> None:
    files.create("cto", CTO)
    (files.root / "cto" / "secrets.env").write_text(
        'PATH="/tmp/mal"\nLD_PRELOAD="x.so"\nTOKEN="ok"\nlixo sem igual\nBAD=nao-json\nNUM=5\n',
        encoding="utf-8",
    )
    assert files.read_secrets("cto") == {"TOKEN": "ok"}
    files.write_secrets("cto", {"PATH": None})  # removing a reserved name is harmless
    assert files.secret_names("cto") == ["TOKEN"]


def test_write_secrets_with_an_undecodable_file_fails_and_keeps_it_byte_for_byte(files: AgentFiles) -> None:
    files.create("cto", CTO)
    path = files.root / "cto" / "secrets.env"
    content = b'A="1"\nB="2"\nC="\xff\xfe"\n'
    path.write_bytes(content)
    for call in (
        lambda: files.write_secrets("cto", {"D": "4"}),
        lambda: files.write_secrets("cto", {"A": None}),
    ):
        with pytest.raises(SecretsFileError) as info:
            call()
        assert "UTF-8" in str(info.value)
        assert "\xff" not in str(info.value) and "1" not in str(info.value).replace("UTF-8", "")
    assert path.read_bytes() == content
    assert [p.name for p in path.parent.iterdir() if p.name.startswith(".")] == []


def test_read_secrets_skips_only_the_undecodable_line(files: AgentFiles) -> None:
    files.create("cto", CTO)
    (files.root / "cto" / "secrets.env").write_bytes(b'A="1"\nC="\xff"\nB="2"\n')
    assert files.read_secrets("cto") == {"A": "1", "B": "2"}
    assert files.secret_names("cto") == ["A", "B"]


def test_read_secrets_never_follows_a_symlink(files: AgentFiles, tmp_path: Path) -> None:
    files.create("cto", CTO)
    outside = tmp_path / "outside.env"
    outside.write_text('TOKEN="x"\n', encoding="utf-8")
    (files.root / "cto" / "secrets.env").symlink_to(outside)
    with pytest.raises(OSError):
        files.read_secrets("cto")


def test_wake_text_roundtrip_with_images(files: AgentFiles) -> None:
    files.create("cto", CTO)
    folder = files.root / "cto"
    folder.chmod(0o755)
    images = [{"media_type": "image/png", "data": "payload" * 1000}]
    files.write_wake_text("cto", 12, "Pedido com ação 🎬\nna linha seguinte", images)
    assert files.read_wake_text("cto", 12) == ("Pedido com ação 🎬\nna linha seguinte", images)
    assert mode(folder / "wake-12.txt") == 0o600
    assert mode(folder) == 0o700
    files.write_wake_text("cto", 12, "Outro")
    assert files.read_wake_text("cto", 12) == ("Outro", [])
    assert sorted(p.name for p in folder.iterdir()) == ["AGENT.md", "wake-12.txt"]
    files.delete_wake_text("cto", 12)
    files.delete_wake_text("cto", 12)
    with pytest.raises(FileNotFoundError):
        files.read_wake_text("cto", 12)


def test_wake_text_limits(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_wake_text("cto", 1, "🎬" * WAKE_TEXT_MAX_CHARS)
    assert files.read_wake_text("cto", 1)[0] == "🎬" * WAKE_TEXT_MAX_CHARS
    with pytest.raises(ValueError):
        files.write_wake_text("cto", 1, "x" * (WAKE_TEXT_MAX_CHARS + 1))
    for blank in ("", "   "):
        with pytest.raises(ValueError):
            files.write_wake_text("cto", 1, blank)
    # With images, the text may be blank.
    files.write_wake_text("cto", 2, "", [{"media_type": "image/png", "data": "x"}])
    assert files.read_wake_text("cto", 2)[0] == ""
    with pytest.raises(ValueError):
        files.write_wake_text("cto", 3, "texto", "nao-lista")  # type: ignore[arg-type]
    assert not (files.root / "cto" / "wake-3.txt").exists()


def test_wake_text_max_chars_none_lifts_the_character_cap_only(files: AgentFiles) -> None:
    files.create("cto", CTO)
    long_text = "🎬" * 20_000
    with pytest.raises(ValueError, match="5.000"):
        files.write_wake_text("cto", 1, long_text)
    assert not (files.root / "cto" / "wake-1.txt").exists()
    files.write_wake_text("cto", 1, long_text, max_chars=None)
    assert files.read_wake_text("cto", 1) == (long_text, [])
    # A numeric cap is honored and named in the message.
    with pytest.raises(ValueError, match="100"):
        files.write_wake_text("cto", 2, "x" * 101, max_chars=100)
    files.write_wake_text("cto", 2, "x" * 100, max_chars=100)
    # Blank text with no images is still refused, and the byte ceiling still applies.
    with pytest.raises(ValueError):
        files.write_wake_text("cto", 3, "  ", max_chars=None)
    huge = [{"media_type": "image/png", "data": "x" * (46 * 1024 * 1024)}]
    with pytest.raises(ValueError):
        files.write_wake_text("cto", 4, "texto", huge, max_chars=None)
    assert not (files.root / "cto" / "wake-4.txt").exists()


@pytest.mark.parametrize("wakeup_id", [0, -1, True, "../secrets.env", "1", 1.0])
def test_wake_text_rejects_invalid_ids_before_disk_access(files: AgentFiles, wakeup_id: object) -> None:
    for call in (
        lambda: files.write_wake_text("cto", wakeup_id, "texto"),  # type: ignore[arg-type]
        lambda: files.read_wake_text("cto", wakeup_id),  # type: ignore[arg-type]
        lambda: files.delete_wake_text("cto", wakeup_id),  # type: ignore[arg-type]
    ):
        with pytest.raises(ValueError):
            call()
    assert not files.root.exists()


def test_wake_text_refuses_symlink_folders(files: AgentFiles, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    files.root.mkdir()
    (files.root / "cto").symlink_to(outside, target_is_directory=True)
    for call in (
        lambda: files.write_wake_text("cto", 1, "texto"),
        lambda: files.read_wake_text("cto", 1),
        lambda: files.delete_wake_text("cto", 1),
        lambda: files.write_definition("cto", CTO),
        lambda: files.write_memory("cto", "x"),
        lambda: files.write_secrets("cto", {"A": "1"}),
        lambda: files.read_definition_text("cto"),
        lambda: files.read_memory("cto"),
        lambda: files.read_secrets("cto"),
    ):
        with pytest.raises(OSError):
            call()
    assert list(outside.iterdir()) == []


def test_wake_text_never_reads_a_symlink_and_replaces_only_the_link(files: AgentFiles, tmp_path: Path) -> None:
    files.create("cto", CTO)
    outside = tmp_path / "private"
    outside.write_text("Segredo", encoding="utf-8")
    (files.root / "cto" / "wake-1.txt").symlink_to(outside)
    with pytest.raises(OSError):
        files.read_wake_text("cto", 1)
    files.write_wake_text("cto", 1, "Pedido")
    assert files.read_wake_text("cto", 1) == ("Pedido", [])
    assert outside.read_text(encoding="utf-8") == "Segredo"


def test_wake_text_refuses_non_regular_files_and_invalid_payloads(files: AgentFiles) -> None:
    files.create("cto", CTO)
    path = files.root / "cto" / "wake-1.txt"
    os.mkfifo(path)
    with pytest.raises(ValueError):
        files.read_wake_text("cto", 1)
    path.unlink()
    for payload in ("nao json", "[]", '{"text": 1, "images": []}', '{"text": "a", "images": "x"}'):
        path.write_text(payload, encoding="utf-8")
        with pytest.raises(ValueError):
            files.read_wake_text("cto", 1)


def test_delete_removes_folder_and_is_idempotent(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_secrets("cto", {"A": "1"})
    files.delete("cto")
    assert not (files.root / "cto").exists()
    files.delete("cto")
    files.create("cto", CTO)  # the slug is free again


def test_delete_of_a_symlink_removes_only_the_link(files: AgentFiles, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    files.root.mkdir()
    (files.root / "cto").symlink_to(outside, target_is_directory=True)
    files.delete("cto")
    assert not (files.root / "cto").exists()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("slug", ["../x", "A", "a/b", "", "-a", "a-", "a--b", "a_b", "x" * 41, "..", "."])
def test_slug_outside_root_refused(files: AgentFiles, slug: str) -> None:
    sentinel = files.root.parent / "x"
    for call in (
        lambda: files.create(slug, CTO),
        lambda: files.folder(slug),
        lambda: files.read_definition_text(slug),
        lambda: files.read_definition(slug),
        lambda: files.write_definition(slug, CTO),
        lambda: files.read_memory(slug),
        lambda: files.write_memory(slug, "a"),
        lambda: files.secret_names(slug),
        lambda: files.write_secrets(slug, {"A": "1"}),
        lambda: files.read_secrets(slug),
        lambda: files.write_wake_text(slug, 1, "a"),
        lambda: files.read_wake_text(slug, 1),
        lambda: files.delete_wake_text(slug, 1),
        lambda: files.delete(slug),
    ):
        with pytest.raises(ValueError):
            call()
    assert not files.root.exists()
    assert not sentinel.exists()


def test_slug_with_40_chars_accepted(files: AgentFiles) -> None:
    files.create("x" * 40, CTO)
    assert (files.root / ("x" * 40) / "AGENT.md").is_file()


def test_slug_must_be_a_string(files: AgentFiles) -> None:
    for slug in (None, 1, b"cto"):
        with pytest.raises(ValueError):
            files.folder(slug)  # type: ignore[arg-type]


def test_wake_preview_reads_only_the_start_of_the_text(files: AgentFiles) -> None:
    files.create("cto", CTO)
    files.write_wake_text("cto", 1, "Mensagem curta 🎬\ncom linha", [{"media_type": "image/png", "data": "x" * 1000}])
    assert files.wake_preview("cto", 1) == "Mensagem curta 🎬\ncom linha"
    files.write_wake_text("cto", 2, "", [{"media_type": "image/png", "data": "x"}])
    assert files.wake_preview("cto", 2) == ""
    files.write_wake_text("cto", 3, "é" * 500)
    assert files.wake_preview("cto", 3) == "é" * 500
    files.write_wake_text("cto", 4, "a" * 501)
    assert files.wake_preview("cto", 4) == "a" * 500 + "…"


def test_wake_preview_of_a_long_message_with_escapes(files: AgentFiles) -> None:
    files.create("cto", CTO)
    # 90.000 characters, every second one needing an escape: far past the first chunk read.
    text = '"\n' * 30_000
    files.write_wake_text("cto", 1, text, [{"media_type": "image/png", "data": "x" * 100_000}], max_chars=None)
    assert files.wake_preview("cto", 1) == text[:500] + "…"


def test_wake_preview_refuses_bad_files_and_ids(files: AgentFiles) -> None:
    files.create("cto", CTO)
    folder = files.root / "cto"
    with pytest.raises(FileNotFoundError):
        files.wake_preview("cto", 9)
    (folder / "wake-5.txt").write_text("não é json")
    with pytest.raises(ValueError):
        files.wake_preview("cto", 5)
    (folder / "wake-6.txt").write_text('{"text": 5, "images": []}')
    with pytest.raises(ValueError):
        files.wake_preview("cto", 6)
    (folder / "wake-7.txt").symlink_to(folder / "AGENT.md")
    with pytest.raises(OSError):
        files.wake_preview("cto", 7)
    (folder / "wake-8.txt").mkdir()
    with pytest.raises((OSError, ValueError)):
        files.wake_preview("cto", 8)
    for bad in (0, -1, True):
        with pytest.raises(ValueError):
            files.wake_preview("cto", bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        files.wake_preview("../x", 1)
