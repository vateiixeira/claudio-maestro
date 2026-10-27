"""Arquivos de um agente: `AGENT.md`, memória, segredos e textos de despertar.

Cada agente tem uma pasta `<root>/<slug>/` (modo 700) com:

- `AGENT.md`: a definição (frontmatter + prompt), validada por `parse_definition`.
- `memoria.md`: texto livre que o agente mantém entre execuções (limitado).
- `secrets.env`: linhas `NOME=<string json>` (modo 600). Os valores só saem deste
  módulo por `read_secrets`, que existe para montar o `env` do processo da sessão.
  Nomes que mudariam o funcionamento do processo (`PATH`, `LD_*`, `CLAUDE*`...) são
  recusados na escrita e ignorados na leitura.
- `wake-<id>.txt`: o pedido de um despertar (texto e imagens), até a execução começar.
- `skills/`: skills próprias do agente (opcional; a pasta é criada por quem a usa).

O slug é validado antes de qualquer acesso ao disco, então nunca aponta para fora de
`root`. Toda leitura e escrita dentro da pasta é ancorada no descritor da pasta aberta,
sem seguir links simbólicos (`O_NOFOLLOW`), e toda gravação é atômica.
"""

import contextlib
import json
import os
import re
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

from claudio_maestro.org.definition import (
    DEFINITION_MAX_BYTES,
    AgentDefinition,
    DefinitionError,
    parse_definition,
)

DEFINITION_FILE = "AGENT.md"
MEMORY_FILE = "memoria.md"
SECRETS_FILE = "secrets.env"
SKILLS_DIR = "skills"

MEMORY_MAX_CHARS = 4000
WAKE_TEXT_MAX_CHARS = 5000
# Images travel as base64 inside the JSON; the whole payload stays bounded.
WAKE_PAYLOAD_MAX_BYTES = 45 * 1024 * 1024
# Memory and secrets are edited by hand or by the agent: reads are bounded, not trusted.
_READ_MAX_BYTES = 1024 * 1024

SLUG_MAX_LENGTH = 40
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SECRET_NAME_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
# Names a secret may not take: they would change how the session's process (the CLI,
# node, the dynamic loader, python) or the Maestro itself behaves.
RESERVED_SECRET_NAMES = frozenset({"PATH", "HOME", "USER", "SHELL", "PWD", "TMPDIR", "NODE_OPTIONS"})
RESERVED_SECRET_PREFIXES = ("CLAUDE", "ANTHROPIC_", "LD_", "DYLD_", "PYTHON", "MAESTRO_")
RESERVED_SECRET_TEXT = "Este nome é reservado pelo sistema. Escolha outro nome para o segredo."


class MemoryTooLongError(ValueError):
    def __init__(self) -> None:
        super().__init__("Passou de 4.000 caracteres. Consolide a memória e tente de novo.")


class InvalidSecretNameError(ValueError):
    """A secret name outside `[A-Z_][A-Z0-9_]*`, or a reserved one."""


class InvalidSecretValueError(ValueError):
    """A secret value that is not a string or contains a NUL character."""


class SecretsFileError(ValueError):
    """`secrets.env` has bytes that are not valid UTF-8. Never quotes the content."""

    def __init__(self) -> None:
        super().__init__(
            "O arquivo de segredos do agente tem bytes que não são texto UTF-8 válido. "
            "Nada foi alterado; corrija ou apague o arquivo secrets.env do agente."
        )


def _check_slug(slug: str) -> None:
    if not isinstance(slug, str) or len(slug) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Identificador de agente inválido.")


def _check_wakeup_id(wakeup_id: int) -> None:
    if type(wakeup_id) is not int or wakeup_id <= 0:
        raise ValueError("Identificador de despertar inválido.")


def _wake_name(wakeup_id: int) -> str:
    _check_wakeup_id(wakeup_id)
    return f"wake-{wakeup_id}.txt"


def _check_secret_value(name: str, value: object) -> None:
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidSecretValueError(f"Valor inválido para o segredo {name}: use texto sem o caractere nulo.")


def is_reserved_secret_name(name: str) -> bool:
    return name in RESERVED_SECRET_NAMES or name.startswith(RESERVED_SECRET_PREFIXES)


def _check_secret_name(name: str, *, setting: bool) -> None:
    # Never quotes the name: it may be a token pasted in the wrong field.
    if not isinstance(name, str) or not SECRET_NAME_PATTERN.fullmatch(name):
        raise InvalidSecretNameError("Nome de segredo inválido: use letras maiúsculas, números e _.")
    if setting and is_reserved_secret_name(name):
        raise InvalidSecretNameError(RESERVED_SECRET_TEXT)


def _read_file(folder_fd: int, name: str, limit: int) -> bytes:
    """Read a regular file of the folder, never following a link, at most `limit` bytes.

    Raises `ValueError` when the file is bigger than `limit` or is not a regular file.
    """
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError(f"{name} precisa ser um arquivo comum.")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{name} passou do tamanho permitido.")
    return raw


def _write_file(folder_fd: int, name: str, text: str) -> None:
    """Replace `name` (mode 600) through a temp file in the same folder and `os.replace`."""
    temporary = f".{name}.{uuid4().hex}"
    fd = os.open(
        temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=folder_fd
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        os.fsync(folder_fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=folder_fd)
        raise


class AgentFiles:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def folder(self, slug: str) -> Path:
        """Path of the agent's folder (for `add_dirs`); only validates the slug."""
        _check_slug(slug)
        return self.root / slug

    @contextlib.contextmanager
    def _open_folder(self, slug: str) -> Iterator[int]:
        """Anchor every operation to the open agent folder, never following a symlink."""
        _check_slug(slug)
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            folder_fd = os.open(slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            try:
                yield folder_fd
            finally:
                os.close(folder_fd)
        finally:
            os.close(root_fd)

    def create(self, slug: str, text: str) -> AgentDefinition:
        folder = self.folder(slug)
        definition = parse_definition(text)  # DefinitionError before touching the disk
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder.mkdir(mode=0o700)  # FileExistsError if the slug already has a folder (or a link)
        try:
            os.chmod(folder, 0o700)
            with self._open_folder(slug) as folder_fd:
                _write_file(folder_fd, DEFINITION_FILE, text)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return definition

    def read_definition_text(self, slug: str) -> str:
        with self._open_folder(slug) as folder_fd:
            try:
                raw = _read_file(folder_fd, DEFINITION_FILE, DEFINITION_MAX_BYTES)
            except ValueError as exc:
                raise DefinitionError(
                    f"O AGENT.md passa de {DEFINITION_MAX_BYTES // 1000} KB; reduza o texto."
                ) from exc
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DefinitionError("O AGENT.md precisa estar em UTF-8.") from exc

    def read_definition(self, slug: str) -> AgentDefinition:
        return parse_definition(self.read_definition_text(slug))

    def write_definition(self, slug: str, text: str) -> AgentDefinition:
        _check_slug(slug)
        definition = parse_definition(text)  # DefinitionError leaves the file untouched
        with self._open_folder(slug) as folder_fd:
            _write_file(folder_fd, DEFINITION_FILE, text)
        return definition

    def read_memory(self, slug: str) -> str:
        with self._open_folder(slug) as folder_fd:
            try:
                raw = _read_file(folder_fd, MEMORY_FILE, _READ_MAX_BYTES)
            except FileNotFoundError:
                return ""
        return raw.decode("utf-8", errors="replace")

    def write_memory(self, slug: str, text: str) -> None:
        _check_slug(slug)
        if len(text) > MEMORY_MAX_CHARS:
            raise MemoryTooLongError
        with self._open_folder(slug) as folder_fd:
            _write_file(folder_fd, MEMORY_FILE, text)

    def _load_secrets(self, slug: str, *, strict: bool) -> dict[str, str]:
        """Parse `secrets.env`.

        `strict` (used before any write) raises `SecretsFileError` on undecodable bytes, so a
        rewrite never starts from a partial view and drops secrets. Otherwise (reading for the
        session `env`) only the undecodable lines are skipped.
        """
        with self._open_folder(slug) as folder_fd:
            try:
                raw = _read_file(folder_fd, SECRETS_FILE, _READ_MAX_BYTES)
            except FileNotFoundError:
                return {}
        if strict:
            try:
                lines = raw.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise SecretsFileError from exc
        else:
            lines = []
            for chunk in raw.split(b"\n"):
                try:
                    lines.append(chunk.decode("utf-8"))
                except UnicodeDecodeError:
                    continue
        secrets: dict[str, str] = {}
        for line in lines:
            name, sep, encoded = line.partition("=")
            if not sep or not SECRET_NAME_PATTERN.fullmatch(name) or is_reserved_secret_name(name):
                continue
            try:
                value = json.loads(encoded)
            except ValueError:
                continue
            if isinstance(value, str):
                secrets[name] = value
        return secrets

    def read_secrets(self, slug: str) -> dict[str, str]:
        """Names and values, only to build the session `env`.

        Lenient on purpose: a corrupted line is skipped so the other secrets still reach the
        session; writes use the strict reading and refuse to touch a corrupted file.
        """
        return self._load_secrets(slug, strict=False)

    def secret_names(self, slug: str) -> list[str]:
        return sorted(self.read_secrets(slug))

    def write_secrets(self, slug: str, values: dict[str, str | None]) -> None:
        """Merge `values` into the stored secrets; a `None` value deletes that name."""
        _check_slug(slug)
        for name, value in values.items():
            _check_secret_name(name, setting=value is not None)
        for name, value in values.items():
            if value is not None:
                _check_secret_value(name, value)
        secrets = self._load_secrets(slug, strict=True)
        for name, value in values.items():
            if value is None:
                secrets.pop(name, None)
            else:
                secrets[name] = value
        # `json.dumps` escapes newlines and separators, so each secret stays on one line.
        text = "".join(f"{name}={json.dumps(secrets[name])}\n" for name in sorted(secrets))
        with self._open_folder(slug) as folder_fd:
            os.fchmod(folder_fd, 0o700)
            _write_file(folder_fd, SECRETS_FILE, text)

    def write_wake_text(
        self,
        slug: str,
        wakeup_id: int,
        text: str,
        images: list[dict] | None = None,
        *,
        max_chars: int | None = WAKE_TEXT_MAX_CHARS,
    ) -> None:
        """Save a wake request privately and atomically; SQLite holds only its id.

        `max_chars=None` lifts the character cap (messages); the payload byte ceiling
        still applies.
        """
        _check_slug(slug)
        name = _wake_name(wakeup_id)
        images = [] if images is None else images
        if not isinstance(text, str) or not isinstance(images, list):
            raise ValueError("O pedido do despertar é inválido.")
        if max_chars is not None and len(text) > max_chars:
            raise ValueError(
                f"O pedido do despertar passou de {max_chars:,} caracteres.".replace(",", ".")
            )
        if not text.strip() and not images:
            raise ValueError("O pedido do despertar não pode ficar em branco.")
        payload = json.dumps({"text": text, "images": images}, ensure_ascii=False)
        if len(payload.encode("utf-8")) > WAKE_PAYLOAD_MAX_BYTES:
            raise ValueError("O pedido do despertar passou do tamanho permitido.")
        with self._open_folder(slug) as folder_fd:
            os.fchmod(folder_fd, 0o700)
            _write_file(folder_fd, name, payload)

    def read_wake_text(self, slug: str, wakeup_id: int) -> tuple[str, list[dict]]:
        _check_slug(slug)
        name = _wake_name(wakeup_id)
        with self._open_folder(slug) as folder_fd:
            raw = _read_file(folder_fd, name, WAKE_PAYLOAD_MAX_BYTES)
        try:
            value = json.loads(raw.decode("utf-8"))
        except ValueError as exc:  # includes UnicodeDecodeError
            raise ValueError("Pedido de despertar inválido.") from exc
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or not isinstance(value.get("images"), list)
        ):
            raise ValueError("Pedido de despertar inválido.")
        return value["text"], value["images"]

    def delete_wake_text(self, slug: str, wakeup_id: int) -> None:
        _check_slug(slug)
        name = _wake_name(wakeup_id)
        with self._open_folder(slug) as folder_fd, contextlib.suppress(FileNotFoundError):
            os.unlink(name, dir_fd=folder_fd)

    def delete(self, slug: str) -> None:
        folder = self.folder(slug)
        if folder.is_symlink():
            folder.unlink()  # only the link, never what it points to
            return
        shutil.rmtree(folder, ignore_errors=True)
