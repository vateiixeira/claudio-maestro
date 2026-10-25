"""Files of an agent (specialist): SKILL.md, learnings and secrets.

Each agent has a folder `<root>/<slug>/` (mode 700) with:

- `SKILL.md`: the skill the agent follows. Frontmatter with `name` and
  `description` (one line each, quotes optional); other keys such as `metadata`
  are tolerated and ignored.
- `aprendizados.md`: free text the agent keeps between sessions (capped).
- `secrets.env`: `NAME=<json string>` lines (mode 600). Values never leave this
  module except through `read_secrets`, meant only to build a session's `env`. Names
  that would change how the process runs (`PATH`, `LD_*`, `CLAUDE*`...) are refused
  on write and skipped on read.

The slug is validated before any disk access, so it can never point outside
`root`.
"""

import contextlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

SKILL_MAX_BYTES = 100_000
LEARNINGS_MAX_CHARS = 4000
# Same instruction limit as the API; four bytes is the largest UTF-8 code point.
RUN_TEXT_MAX_CHARS = 5000
RUN_TEXT_MAX_BYTES = RUN_TEXT_MAX_CHARS * 4
SLUG_MAX_LENGTH = 40
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SECRET_NAME_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]*")
# Names a secret may not take: they would change how the session's process (the CLI,
# node, the dynamic loader, python) or the Maestro itself behaves.
RESERVED_SECRET_NAMES = frozenset({"PATH", "HOME", "USER", "SHELL", "PWD", "TMPDIR", "NODE_OPTIONS"})
RESERVED_SECRET_PREFIXES = ("CLAUDE", "ANTHROPIC_", "LD_", "DYLD_", "PYTHON", "MAESTRO_")
RESERVED_SECRET_TEXT = "Este nome é reservado pelo sistema. Escolha outro nome para o segredo."
_YAML_BLOCK_SCALAR = re.compile(r"[>|][+-]?\d*")

SKILL_FILE = "SKILL.md"
LEARNINGS_FILE = "aprendizados.md"
SECRETS_FILE = "secrets.env"

_SKILL_TEMPLATE = """---
name: {name}
description: {description}
---

# {title}

## Quando usar

Descreva em que situações este agente deve entrar em ação.

## Passo a passo

1. Descreva o primeiro passo.
2. Descreva o segundo passo.

## Regras

- Liste o que o agente deve sempre ou nunca fazer.
"""

_TEMPLATE_DESCRIPTION = "Descreva em uma frase o que este agente faz e quando usá-lo."


class SkillInvalidError(ValueError):
    """The SKILL.md text is too big or its frontmatter is invalid."""


class LearningsTooLongError(ValueError):
    def __init__(self) -> None:
        super().__init__("Passou de 4.000 caracteres. Consolide os aprendizados e tente de novo.")


class InvalidSecretNameError(ValueError):
    """A secret name outside `[A-Z_][A-Z0-9_]*`."""


class InvalidSecretValueError(ValueError):
    """A secret value that is not a string or contains a NUL character."""


@dataclass
class SkillMeta:
    name: str
    description: str
    body: str


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            loaded = json.loads(value)
        except ValueError:
            return value[1:-1]
        return loaded if isinstance(loaded, str) else value[1:-1]
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def parse_skill(text: str) -> SkillMeta:
    """Read `name`, `description` and the body from a SKILL.md text."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillInvalidError("A skill precisa começar com um bloco de cabeçalho entre linhas '---'.")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise SkillInvalidError("O cabeçalho da skill não foi fechado com uma linha '---'.")
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[0] in " \t#" or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        if key in ("name", "description") and _YAML_BLOCK_SCALAR.fullmatch(raw.strip()):
            raise SkillInvalidError(f"O campo '{key}' do cabeçalho da skill precisa caber em uma linha.")
        values.setdefault(key, _unquote(raw))
    name = values.get("name", "").strip()
    description = values.get("description", "").strip()
    if not name:
        raise SkillInvalidError("O cabeçalho da skill precisa do campo 'name'.")
    if not description:
        raise SkillInvalidError("O cabeçalho da skill precisa do campo 'description'.")
    return SkillMeta(name=name, description=description, body="".join(lines[end + 1 :]))


def _check_slug(slug: str) -> None:
    if not isinstance(slug, str) or len(slug) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Identificador de agente inválido.")


def _write_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` through a temp file in the same folder and `os.replace`."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")  # mode 600
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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


class SpecialistFiles:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _dir(self, slug: str) -> Path:
        _check_slug(slug)
        return self.root / slug

    def create(self, slug: str, name: str) -> None:
        folder = self._dir(slug)
        if not name.strip():
            raise ValueError("O nome do agente não pode ficar em branco.")
        self.root.mkdir(parents=True, exist_ok=True)
        folder.mkdir(mode=0o700)  # FileExistsError if the agent already exists
        os.chmod(folder, 0o700)
        title = " ".join(name.split()) or slug
        text = _SKILL_TEMPLATE.format(
            name=json.dumps(name),
            description=json.dumps(_TEMPLATE_DESCRIPTION),
            title=title,
        )
        _write_atomic(folder / SKILL_FILE, text)

    def read_skill(self, slug: str) -> str:
        return (self._dir(slug) / SKILL_FILE).read_text(encoding="utf-8")

    def write_skill(self, slug: str, text: str) -> SkillMeta:
        folder = self._dir(slug)
        if len(text.encode("utf-8")) > SKILL_MAX_BYTES:
            raise SkillInvalidError("A skill passou de 100 KB.")
        meta = parse_skill(text)
        _write_atomic(folder / SKILL_FILE, text)
        return meta

    def read_learnings(self, slug: str) -> str:
        try:
            return (self._dir(slug) / LEARNINGS_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_learnings(self, slug: str, text: str) -> None:
        folder = self._dir(slug)
        if len(text) > LEARNINGS_MAX_CHARS:
            raise LearningsTooLongError
        _write_atomic(folder / LEARNINGS_FILE, text)

    @contextlib.contextmanager
    def _run_folder(self, slug: str, run_id: int) -> Iterator[tuple[int, str]]:
        """Anchor queue operations to the open agent folder, never following a symlink."""
        _check_slug(slug)
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("Identificador de execução inválido.")
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            folder_fd = os.open(
                slug, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
            )
            try:
                yield folder_fd, f"pending-{run_id}.txt"
            finally:
                os.close(folder_fd)
        finally:
            os.close(root_fd)

    @staticmethod
    def _check_run_text(text: str) -> None:
        if not isinstance(text, str) or not text.strip() or len(text) > RUN_TEXT_MAX_CHARS:
            raise ValueError("O pedido da execução precisa ter de 1 a 5.000 caracteres.")

    def write_run_text(self, slug: str, run_id: int, text: str) -> None:
        """Save a private pending instruction atomically; SQLite holds only its run id."""
        self._check_run_text(text)
        self._write_pending(slug, run_id, text)

    def _write_pending(self, slug: str, run_id: int, text: str) -> None:
        with self._run_folder(slug, run_id) as (folder_fd, name):
            os.fchmod(folder_fd, 0o700)
            temporary = f".{name}.{uuid4().hex}"
            fd = os.open(
                temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600, dir_fd=folder_fd,
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

    def write_message(self, slug: str, run_id: int, text: str, images: list[dict]) -> None:
        payload = json.dumps({"text": text, "images": images}, ensure_ascii=False)
        if len(payload.encode("utf-8")) > 45 * 1024 * 1024:
            raise ValueError("A mensagem passou do tamanho permitido.")
        self._write_pending(slug, run_id, payload)

    def read_message(self, slug: str, run_id: int) -> tuple[str, list[dict]]:
        value = json.loads(self._read_pending(slug, run_id, 45 * 1024 * 1024))
        if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not isinstance(value.get("images"), list):
            raise ValueError("Mensagem inválida na fila.")
        return value["text"], value["images"]

    def message_preview(self, slug: str, run_id: int) -> str:
        # JSON writes text first. Decode only its first string, never the image bodies.
        # 100k characters need at most 600k JSON bytes (escaped control characters).
        with self._run_folder(slug, run_id) as (folder_fd, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError("Mensagem inválida na fila.")
                prefix = handle.read(600_020).decode("utf-8", "ignore")
        if not prefix.startswith('{"text": '):
            raise ValueError("Mensagem inválida na fila.")
        text, _ = json.JSONDecoder().raw_decode(prefix, 9)
        if not isinstance(text, str):
            raise ValueError("Mensagem inválida na fila.")
        return text[:500] + ("…" if len(text) > 500 else "")

    def _read_pending(self, slug: str, run_id: int, limit: int) -> str:
        with self._run_folder(slug, run_id) as (folder_fd, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
            with os.fdopen(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError("O pedido da execução precisa ser um arquivo comum.")
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("O pedido da execução passou do tamanho permitido.")
            return raw.decode("utf-8")

    def read_run_text(self, slug: str, run_id: int) -> str:
        text = self._read_pending(slug, run_id, RUN_TEXT_MAX_BYTES)
        self._check_run_text(text)
        return text

    def delete_run_text(self, slug: str, run_id: int) -> None:
        with self._run_folder(slug, run_id) as (folder_fd, name):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=folder_fd)

    def read_secrets(self, slug: str) -> dict[str, str]:
        """Names and values, only to build the session `env`."""
        try:
            raw = (self._dir(slug) / SECRETS_FILE).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        secrets: dict[str, str] = {}
        for line in raw.splitlines():
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

    def secret_names(self, slug: str) -> list[str]:
        return sorted(self.read_secrets(slug))

    def write_secrets(self, slug: str, values: dict[str, str | None]) -> None:
        """Merge `values` into the stored secrets; a `None` value deletes that name."""
        folder = self._dir(slug)
        for name, value in values.items():
            _check_secret_name(name, setting=value is not None)
        for name, value in values.items():
            if value is not None:
                _check_secret_value(name, value)
        os.chmod(folder, 0o700)
        secrets = self.read_secrets(slug)
        for name, value in values.items():
            if value is None:
                secrets.pop(name, None)
            else:
                secrets[name] = value
        text = "".join(f"{name}={json.dumps(secrets[name])}\n" for name in sorted(secrets))
        _write_atomic(folder / SECRETS_FILE, text)

    def delete(self, slug: str) -> None:
        shutil.rmtree(self._dir(slug), ignore_errors=True)
