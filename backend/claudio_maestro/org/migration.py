"""Passo de arquivos da migração: pastas dos agentes antigos viram pastas de agente.

A migração 31 de `db.py` já copiou as linhas de `specialists` para `agents` (ids preservados) e
guardou em `agents.legacy_json` o que o `AGENT.md` ainda vai absorver (`model`, `effort`,
`denied_tools`, `extra_project_ids`). Aqui, para cada agente com `legacy_json`:

    <data_dir>/specialists/<slug>/   SKILL.md, aprendizados.md, secrets.env
        -> <data_dir>/agents/<slug>/ AGENT.md, memoria.md, secrets.env

Ordem segura (um reinício em qualquer ponto não perde nada nem deixa o agente sem `AGENT.md`):

1. a pasta nova é montada inteira em `agents/.migrando/<slug>`;
2. ela entra no lugar com um `rename` (atômico, mesmo sistema de arquivos);
3. numa transação: `definition_hash` gravado e `legacy_json` apagado;
4. só então a pasta antiga é renomeada para `specialists/<slug>.migrado` (nunca apagada).

Se a execução cair entre 2 e 4, a próxima vê `legacy_json` ainda preenchido e a pasta nova
pronta: só termina os passos 3 e 4. Depois da migração `legacy_json` fica nulo, então uma
segunda chamada não encontra nada a fazer.

Segredos: os valores só passam por `AgentFiles` (modo 600) e nunca entram em avisos, no
relatório nem em mensagens de erro; o relatório lista só os nomes.
"""

import contextlib
import json
import os
import shutil
import sqlite3
import stat
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.definition import (
    DEFAULT_MAX_RUN_MINUTES,
    DEFAULT_PERMISSION_MODE,
    DEFINITION_MAX_BYTES,
    EFFORTS,
    AgentDefinition,
    DefinitionError,
    definition_hash,
    render_definition,
)
from claudio_maestro.org.files import (
    MEMORY_MAX_CHARS,
    SECRET_NAME_PATTERN,
    SLUG_MAX_LENGTH,
    SLUG_PATTERN,
    AgentFiles,
    is_reserved_secret_name,
)

OLD_DIR = "specialists"
NEW_DIR = "agents"
STAGING_DIR = ".migrando"
OLD_SKILL = "SKILL.md"
OLD_LEARNINGS = "aprendizados.md"
OLD_SECRETS = "secrets.env"
REPORT_PREFIX = "migracao-"
_READ_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class AgentMigration:
    slug: str
    name: str
    model: str | None
    effort: str | None
    disallowed_tools: list[str]
    add_dirs: list[str]
    secret_names: list[str]
    memory_chars: int
    memory_truncated: bool
    routines: list[tuple[str, int]]  # (nome da rotina, quantidade de horários)
    old_folder: str | None  # nome da pasta antiga depois de renomeada
    resumed: bool = False


@dataclass
class MigrationReport:
    migrated: list[AgentMigration] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Texto desta execução. O arquivo pode ter mais, se já havia relatório do mesmo dia.
    text: str = ""
    report_path: Path | None = None


class _SkipAgent(Exception):
    """O agente não pode ser migrado agora; a mensagem (sem segredos) vira aviso."""


# --- Leitura da pasta antiga -------------------------------------------------------


def _read_old(folder: Path, name: str, limit: int) -> bytes | None:
    """Arquivo comum da pasta antiga, sem seguir link simbólico; `None` se não existe."""
    try:
        folder_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise _SkipAgent("a pasta antiga não pôde ser aberta") from exc
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValueError(f"{name} não pôde ser lido (link simbólico ou arquivo irregular)") from exc
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError(f"{name} não é um arquivo comum")
            raw = handle.read(limit + 1)
    finally:
        os.close(folder_fd)
    if len(raw) > limit:
        raise ValueError(f"{name} passou do tamanho permitido")
    return raw


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


def _parse_skill(text: str) -> tuple[str, str, str]:
    """`name`, `description` e corpo de um SKILL.md antigo (mesma leitura do `specialists/`)."""
    lines = text.lstrip("﻿").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise _SkipAgent("o SKILL.md não começa com um cabeçalho entre linhas '---'")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise _SkipAgent("o cabeçalho do SKILL.md não foi fechado com '---'")
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line[0] in " \t#" or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        values.setdefault(key.strip(), _unquote(raw))
    return (
        values.get("name", "").strip(),
        values.get("description", "").strip(),
        "".join(lines[end + 1 :]).strip(),
    )


def _parse_secrets(raw: bytes) -> tuple[dict[str, str], int]:
    """Valores válidos e quantas linhas ficaram de fora. Nunca cita o conteúdo."""
    secrets: dict[str, str] = {}
    ignored = 0
    for chunk in raw.split(b"\n"):
        if not chunk.strip():
            continue
        try:
            line = chunk.decode("utf-8").rstrip("\r")
        except UnicodeDecodeError:
            ignored += 1
            continue
        name, sep, encoded = line.partition("=")
        if not sep or not SECRET_NAME_PATTERN.fullmatch(name) or is_reserved_secret_name(name):
            ignored += 1
            continue
        try:
            value = json.loads(encoded)
        except ValueError:
            ignored += 1
            continue
        if isinstance(value, str) and "\x00" not in value:
            secrets[name] = value
        else:
            ignored += 1
    return secrets, ignored


# --- Ajuda com o que veio do legado ------------------------------------------------


def _legacy_list(value: object) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _extra_dirs(conn: sqlite3.Connection, slug: str, legacy: dict, warnings: list[str]) -> list[str]:
    dirs: list[str] = []
    for project_id in _legacy_list(legacy.get("extra_project_ids")):
        if type(project_id) is not int:
            continue
        row = conn.execute("SELECT path FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            warnings.append(
                f"{slug}: o projeto extra {project_id} não existe mais; ficou de fora das "
                "pastas extras (addDirs) do agente."
            )
        elif row["path"] not in dirs:
            dirs.append(row["path"])
    return dirs


def _fsync_dir(path: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    else:
        shutil.rmtree(path, ignore_errors=True)


def _free_migrated_name(old_root: Path, slug: str) -> Path:
    candidate = old_root / f"{slug}.migrado"
    number = 2
    while os.path.lexists(candidate):
        candidate = old_root / f"{slug}.migrado-{number}"
        number += 1
    return candidate


def _routines_of(conn: sqlite3.Connection, agent_id: int) -> list[tuple[str, int]]:
    return [
        (routine.name, len(store.list_schedules(conn, routine.id)))
        for routine in store.list_routines(conn, agent_id=agent_id)
    ]


# --- Migração de um agente ---------------------------------------------------------


def _build_staging(
    staging: AgentFiles, old: Path, agent: store.Agent, conn: sqlite3.Connection,
    warnings: list[str],
) -> AgentMigration:
    slug = agent.slug
    legacy = agent.legacy or {}

    raw_skill = _read_old(old, OLD_SKILL, DEFINITION_MAX_BYTES)
    if raw_skill is None:
        raise _SkipAgent("a pasta antiga não tem SKILL.md")
    try:
        skill_text = raw_skill.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _SkipAgent("o SKILL.md não está em UTF-8") from exc
    skill_name, description, body = _parse_skill(skill_text)

    model = legacy.get("model")
    model = model.strip() if isinstance(model, str) and model.strip() else None
    effort = legacy.get("effort")
    if effort is not None and effort not in EFFORTS:
        warnings.append(
            f"{slug}: o esforço «{effort}» não existe mais; o agente ficou com o esforço padrão."
        )
        effort = None
    denied = [t for t in _legacy_list(legacy.get("denied_tools")) if isinstance(t, str)]
    add_dirs = _extra_dirs(conn, slug, legacy, warnings)

    definition = AgentDefinition(
        name=skill_name or agent.name,
        description=description,
        model=model,
        effort=effort,
        permission_mode=DEFAULT_PERMISSION_MODE,
        disallowed_tools=denied,
        skills=[],
        add_dirs=add_dirs,
        worktree=False,
        max_run_minutes=DEFAULT_MAX_RUN_MINUTES,
        body=body,
    )
    try:
        staging.create(slug, render_definition(definition))
    except DefinitionError as exc:
        raise _SkipAgent(f"o AGENT.md gerado é inválido: {exc.message}") from exc

    memory_chars = 0
    truncated = False
    try:
        raw_memory = _read_old(old, OLD_LEARNINGS, _READ_MAX_BYTES)
    except ValueError as exc:
        warnings.append(f"{slug}: {exc}; a memória não foi copiada.")
        raw_memory = None
    if raw_memory is not None:
        memory = raw_memory.decode("utf-8", errors="replace")
        if len(memory) > MEMORY_MAX_CHARS:
            memory = memory[:MEMORY_MAX_CHARS]
            truncated = True
            warnings.append(
                f"{slug}: o aprendizados.md passava de {MEMORY_MAX_CHARS:,} caracteres e foi "
                "cortado na cópia (o original continua na pasta .migrado).".replace(",", ".")
            )
        staging.write_memory(slug, memory)
        memory_chars = len(memory)

    secret_names: list[str] = []
    try:
        raw_secrets = _read_old(old, OLD_SECRETS, _READ_MAX_BYTES)
    except ValueError as exc:
        warnings.append(f"{slug}: {exc}; os segredos não foram copiados.")
        raw_secrets = None
    if raw_secrets is not None:
        secrets, ignored = _parse_secrets(raw_secrets)
        if ignored:
            warnings.append(
                f"{slug}: {ignored} linha(s) do secrets.env não foram copiadas "
                "(formato inválido ou nome reservado)."
            )
        if secrets:
            staging.write_secrets(slug, dict(secrets))
        secret_names = sorted(secrets)

    return AgentMigration(
        slug=slug,
        name=definition.name,
        model=model,
        effort=effort,
        disallowed_tools=denied,
        add_dirs=add_dirs,
        secret_names=secret_names,
        memory_chars=memory_chars,
        memory_truncated=truncated,
        routines=_routines_of(conn, agent.id),
        old_folder=None,
    )


def _finalize(
    conn: sqlite3.Connection, files: AgentFiles, agent: store.Agent, old: Path | None, now: int
) -> str | None:
    """Passos 3 e 4: hash + `legacy_json` nulo numa transação, depois a pasta antiga."""
    text = files.read_definition_text(agent.slug)
    with db.transaction(conn):
        store.update_agent(conn, agent.id, now=now, definition_hash=definition_hash(text))
        store.clear_legacy(conn, agent.id)
    if old is None:
        return None
    target = _free_migrated_name(old.parent, agent.slug)
    os.rename(old, target)
    _fsync_dir(old.parent)
    return target.name


def _migrate_one(
    conn: sqlite3.Connection, data_dir: Path, agent: store.Agent, now: int, warnings: list[str]
) -> AgentMigration:
    slug = agent.slug
    if len(slug) > SLUG_MAX_LENGTH or not SLUG_PATTERN.fullmatch(slug):
        raise _SkipAgent("identificador inválido; a pasta não foi tocada")
    agents_root = data_dir / NEW_DIR
    files = AgentFiles(agents_root)
    new = agents_root / slug
    old = data_dir / OLD_DIR / slug
    old_present = os.path.lexists(old)
    if old_present and (old.is_symlink() or not old.is_dir()):
        raise _SkipAgent("a pasta antiga não é uma pasta comum; não foi migrada")

    if os.path.lexists(new):
        # Uma execução anterior caiu depois de colocar a pasta nova no lugar: só terminar.
        try:
            definition = files.read_definition(slug)
        except (OSError, DefinitionError) as exc:
            raise _SkipAgent("a pasta nova já existe, mas o AGENT.md dela não pôde ser lido") from exc
        old_name = _finalize(conn, files, agent, old if old_present else None, now)
        return AgentMigration(
            slug=slug,
            name=definition.name,
            model=definition.model,
            effort=definition.effort,
            disallowed_tools=definition.disallowed_tools,
            add_dirs=definition.add_dirs,
            secret_names=files.secret_names(slug),
            memory_chars=len(files.read_memory(slug)),
            memory_truncated=False,
            routines=_routines_of(conn, agent.id),
            old_folder=old_name,
            resumed=True,
        )

    if not old_present:
        raise _SkipAgent("a pasta antiga (specialists) não existe; nada para migrar")

    agents_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging_root = agents_root / STAGING_DIR
    staging_root.mkdir(mode=0o700, exist_ok=True)
    staging = AgentFiles(staging_root)
    stale = staging_root / slug
    if os.path.lexists(stale):
        _remove_tree(stale)
    moved = False
    try:
        migration = _build_staging(staging, old, agent, conn, warnings)
        os.rename(stale, new)
        moved = True
        _fsync_dir(agents_root)
    finally:
        if not moved and os.path.lexists(stale):
            _remove_tree(stale)
    old_name = _finalize(conn, files, agent, old, now)
    return replace(migration, old_folder=old_name)


# --- Relatório ---------------------------------------------------------------------


def _render_report(
    migrated: list[AgentMigration], warnings: list[str], when: datetime
) -> str:
    lines = [
        f"# Migração para a organização de agentes, {when:%Y-%m-%d}",
        "",
        f"Gerado pelo Cláudio Maestro em {when:%Y-%m-%d %H:%M}. Nenhum valor de segredo "
        "aparece aqui, só os nomes.",
        "",
    ]
    if migrated:
        lines += [f"Agentes migrados: {len(migrated)}.", ""]
    elif warnings:
        lines += ["Nenhum agente foi migrado nesta execução.", ""]
    else:
        lines += ["Nada a migrar: todos os agentes já estão na nova organização.", ""]
    for item in migrated:
        lines += [f"## {item.slug} ({item.name})", ""]
        if item.resumed:
            lines.append(
                "- Retomada: a pasta nova já estava pronta de uma execução anterior; "
                "só faltava registrar e arquivar a pasta antiga."
            )
        else:
            lines.append("- `AGENT.md` criado a partir do `SKILL.md`.")
        lines.append(f"- Modelo: {item.model or 'padrão'}; esforço: {item.effort or 'padrão'}.")
        lines.append("- Modo de permissão: bypassPermissions.")
        if item.disallowed_tools:
            lines.append(f"- Ferramentas negadas: {', '.join(item.disallowed_tools)}.")
        if item.add_dirs:
            lines.append(f"- Pastas extras (addDirs): {', '.join(item.add_dirs)}.")
        if item.memory_chars or item.memory_truncated:
            note = " (cortada em 4.000 caracteres)" if item.memory_truncated else ""
            lines.append(
                f"- Memória: `aprendizados.md` virou `memoria.md`, "
                f"{item.memory_chars} caracteres{note}."
            )
        else:
            lines.append("- Memória: vazia (sem `aprendizados.md`).")
        if item.secret_names:
            lines.append(f"- Segredos copiados (só os nomes): {', '.join(item.secret_names)}.")
        else:
            lines.append("- Segredos: nenhum.")
        for routine_name, count in item.routines:
            lines.append(
                f"- Rotina «{routine_name}» criada pela migração do banco, com {count} "
                f"{'horário' if count == 1 else 'horários'}."
            )
        if item.old_folder:
            lines.append(
                f"- Pasta antiga mantida em `specialists/{item.old_folder}` "
                "(pode ser apagada quando você confirmar que está tudo certo)."
            )
        lines.append("")
    if warnings:
        lines += ["## Avisos", ""]
        lines += [f"- {warning}" for warning in warnings]
        lines.append("")
    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _write_report(agents_root: Path, text: str, migrated: bool, when: datetime) -> Path | None:
    agents_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = agents_root / f"{REPORT_PREFIX}{when:%Y-%m-%d}.md"
    if not migrated:
        # Uma execução sem trabalho nunca apaga o relatório de uma execução que fez.
        if any(agents_root.glob(f"{REPORT_PREFIX}*.md")):
            return None
        _write_text(path, text)
        return path
    if path.is_file() and not path.is_symlink():
        previous = path.read_text(encoding="utf-8", errors="replace")
        text_to_write = f"{previous.rstrip()}\n\n---\n\n{text}"
    else:
        text_to_write = text
    _write_text(path, text_to_write)
    return path


# --- Entrada -----------------------------------------------------------------------


def migrate_files(
    data_dir: Path, conn: sqlite3.Connection, *, clock: Callable[[], datetime] | None = None
) -> MigrationReport:
    """Migra as pastas dos agentes antigos. Chamado na subida, depois de `db.migrate`.

    `clock` devolve a data e hora do relatório (os testes injetam uma fixa).
    """
    data_dir = Path(data_dir)
    when = (clock or datetime.now)()
    now = int(when.timestamp())
    report = MigrationReport()
    agents_root = data_dir / NEW_DIR
    for agent in store.list_agents(conn):
        if agent.legacy is None:
            continue
        warnings: list[str] = []
        try:
            report.migrated.append(_migrate_one(conn, data_dir, agent, now, warnings))
        except _SkipAgent as exc:
            warnings.append(f"{agent.slug}: {exc}")
        except (OSError, ValueError) as exc:
            # Mensagens de `AgentFiles` e do sistema falam de arquivos, nunca de valores.
            warnings.append(f"{agent.slug}: não foi possível migrar ({type(exc).__name__}).")
        report.warnings.extend(warnings)
    with contextlib.suppress(OSError):
        (agents_root / STAGING_DIR).rmdir()
    report.text = _render_report(report.migrated, report.warnings, when)
    report.report_path = _write_report(agents_root, report.text, bool(report.migrated), when)
    return report
