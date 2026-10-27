"""File step of the migration: old specialist folders become agent folders."""

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.org import migration, store
from claudio_maestro.org.definition import definition_hash
from claudio_maestro.org.files import MEMORY_MAX_CHARS, AgentFiles

SKILL = """---
name: Sentry
description: "Triagem dos erros do Sentry."
---
Você acompanha os erros do Sentry e abre tarefas para os importantes.
"""

SECRET_VALUE = "sntrys_super-secret-token-123"
OTHER_SECRET = "s3cr3t-with \"quotes\" and \\ slash"


@pytest.fixture
def clock():
    return lambda: datetime(2026, 10, 28, 9, 30)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(db.connect(tmp_path / "t.db")) as c:
        db.migrate(c)
        for pid, path in ((1, "/work/app"), (2, "/work/lib")):
            c.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (?, 'p', ?, '#fff', 0, 0)",
                (pid, path),
            )
        yield c


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path


def add_specialist(
    conn,
    data_dir: Path,
    slug: str = "sentry",
    *,
    skill: str | None = SKILL,
    learnings: str | None = "- O alerta X é ruído.\n",
    secrets: dict[str, str] | None = None,
    model: str | None = "sonnet",
    effort: str | None = "high",
    denied: list[str] | None = None,
    extra: list[int] | None = None,
    project_id: int = 1,
    name: str = "Sentry",
) -> int:
    """An agent row as migration 31 leaves it, plus the old folder on disk."""
    legacy = {
        "model": model, "effort": effort, "denied_tools": denied or [],
        "extra_project_ids": extra or [],
    }
    cursor = conn.execute(
        "INSERT INTO agents (slug, name, project_id, enabled, legacy_json, created_at, updated_at)"
        " VALUES (?, ?, ?, 1, ?, 5, 5)",
        (slug, name, project_id, json.dumps(legacy)),
    )
    folder = data_dir / "specialists" / slug
    folder.mkdir(parents=True, mode=0o700)
    if skill is not None:
        (folder / "SKILL.md").write_text(skill, encoding="utf-8")
    if learnings is not None:
        (folder / "aprendizados.md").write_text(learnings, encoding="utf-8")
    if secrets is not None:
        text = "".join(f"{k}={json.dumps(v)}\n" for k, v in secrets.items())
        (folder / "secrets.env").write_text(text, encoding="utf-8")
        os.chmod(folder / "secrets.env", 0o600)
    return cursor.lastrowid


def mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def files_of(data_dir: Path) -> AgentFiles:
    return AgentFiles(data_dir / "agents")


def test_file_migration_builds_agent_md_from_skill(conn, data_dir, clock):
    agent_id = add_specialist(
        conn, data_dir, denied=["Bash(rm:*)", "WebFetch"], model="opus", effort="max"
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert [m.slug for m in report.migrated] == ["sentry"]
    definition = files_of(data_dir).read_definition("sentry")
    assert definition.name == "Sentry"
    assert definition.description == "Triagem dos erros do Sentry."
    assert definition.model == "opus"
    assert definition.effort == "max"
    assert definition.permission_mode == "bypassPermissions"
    assert definition.disallowed_tools == ["Bash(rm:*)", "WebFetch"]
    assert definition.skills == []
    assert definition.add_dirs == []
    assert definition.worktree is False
    assert definition.max_run_minutes == 120
    assert definition.body == "Você acompanha os erros do Sentry e abre tarefas para os importantes."
    agent = store.get_agent(conn, agent_id)
    text = files_of(data_dir).read_definition_text("sentry")
    assert agent.definition_hash == definition_hash(text)
    assert agent.legacy is None
    assert mode(data_dir / "agents" / "sentry") == 0o700
    # The old folder is kept, renamed.
    assert not (data_dir / "specialists" / "sentry").exists()
    assert (data_dir / "specialists" / "sentry.migrado" / "SKILL.md").read_text() == SKILL


def test_file_migration_copies_memory_and_secrets_mode_600(conn, data_dir, clock):
    add_specialist(
        conn, data_dir, learnings="- Aprendi isso.\n",
        secrets={"SENTRY_TOKEN": SECRET_VALUE, "OTHER": OTHER_SECRET},
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    files = files_of(data_dir)
    assert files.read_memory("sentry") == "- Aprendi isso.\n"
    assert files.read_secrets("sentry") == {"SENTRY_TOKEN": SECRET_VALUE, "OTHER": OTHER_SECRET}
    assert mode(data_dir / "agents" / "sentry" / "secrets.env") == 0o600
    assert mode(data_dir / "agents" / "sentry" / "memoria.md") == 0o600
    assert report.migrated[0].secret_names == ["OTHER", "SENTRY_TOKEN"]
    # No secret value ever reaches the report text or the report file.
    written = (data_dir / "agents" / "migracao-2026-10-28.md").read_text(encoding="utf-8")
    for value in (SECRET_VALUE, OTHER_SECRET, "sntrys"):
        assert value not in report.text
        assert value not in written
    assert "SENTRY_TOKEN" in written


def test_file_migration_truncates_long_memory_and_notes_it(conn, data_dir, clock):
    add_specialist(conn, data_dir, learnings="x" * (MEMORY_MAX_CHARS + 500))

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert len(files_of(data_dir).read_memory("sentry")) == MEMORY_MAX_CHARS
    assert report.migrated[0].memory_truncated is True
    assert "cortad" in report.text.lower()
    # The full text survives in the kept folder.
    kept = data_dir / "specialists" / "sentry.migrado" / "aprendizados.md"
    assert len(kept.read_text(encoding="utf-8")) == MEMORY_MAX_CHARS + 500


def test_file_migration_maps_extra_projects_to_add_dirs(conn, data_dir, clock):
    add_specialist(conn, data_dir, extra=[2, 99, 2])

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_definition("sentry").add_dirs == ["/work/lib"]
    assert report.migrated[0].add_dirs == ["/work/lib"]
    # A project that no longer exists becomes a warning, not a failure.
    assert any("99" in warning for warning in report.warnings)
    assert any("99" in line for line in report.text.splitlines())


def test_file_migration_is_idempotent(conn, data_dir, clock):
    add_specialist(conn, data_dir, secrets={"TOKEN": SECRET_VALUE})
    migration.migrate_files(data_dir, conn, clock=clock)
    files = files_of(data_dir)
    definition_before = files.read_definition_text("sentry")
    memory_before = files.read_memory("sentry")
    secrets_before = files.read_secrets("sentry")
    agents_before = store.list_agents(conn)
    report_path = data_dir / "agents" / "migracao-2026-10-28.md"
    report_before = report_path.read_text(encoding="utf-8")

    second = migration.migrate_files(data_dir, conn, clock=clock)

    assert second.migrated == []
    assert "nada a migrar" in second.text.lower()
    assert files.read_definition_text("sentry") == definition_before
    assert files.read_memory("sentry") == memory_before
    assert files.read_secrets("sentry") == secrets_before
    assert store.list_agents(conn) == agents_before
    assert sorted(p.name for p in (data_dir / "specialists").iterdir()) == ["sentry.migrado"]
    # The report of the real migration is not erased by the later no-op run.
    assert report_path.read_text(encoding="utf-8") == report_before


def test_file_migration_no_op_writes_report_when_none_exists(conn, data_dir, clock):
    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated == []
    path = data_dir / "agents" / "migracao-2026-10-28.md"
    assert report.report_path == path
    assert "nada a migrar" in path.read_text(encoding="utf-8").lower()


def test_file_migration_report_lists_each_agent(conn, data_dir, clock):
    add_specialist(conn, data_dir, "sentry", secrets={"TOKEN": SECRET_VALUE})
    add_specialist(
        conn, data_dir, "kbgen", name="KBGen", project_id=2, extra=[1],
        skill=SKILL.replace("name: Sentry", "name: KBGen"),
    )
    # Routines come from migration 31; the report counts them.
    sentry = store.get_agent_by_slug(conn, "sentry")
    routine = store.create_routine(
        conn, project_id=1, agent_id=sentry.id, name="Triagem", instruction="Veja os erros.",
        now=1,
    )
    store.replace_schedules(conn, routine.id, [("12345", "09:00"), ("12345", "17:30")], 1)

    report = migration.migrate_files(data_dir, conn, clock=clock)

    path = data_dir / "agents" / "migracao-2026-10-28.md"
    assert report.report_path == path
    assert mode(path) == 0o600
    text = path.read_text(encoding="utf-8")
    assert text == report.text
    assert "2026-10-28" in text
    assert "sentry" in text and "kbgen" in text and "KBGen" in text
    assert "TOKEN" in text
    assert "Triagem" in text and "2 horários" in text
    assert "/work/app" in text  # kbgen's extra project
    assert [m.slug for m in report.migrated] == ["sentry", "kbgen"]


def test_file_migration_resumes_after_crash_before_database_update(conn, data_dir, clock):
    agent_id = add_specialist(conn, data_dir, secrets={"TOKEN": SECRET_VALUE})
    # Simulate the first run dying after the new folder was moved into place.
    original = store.clear_legacy

    def boom(*args, **kwargs):
        raise RuntimeError("queda")

    store.clear_legacy = boom
    try:
        with pytest.raises(RuntimeError):
            migration.migrate_files(data_dir, conn, clock=clock)
    finally:
        store.clear_legacy = original
    assert (data_dir / "agents" / "sentry" / "AGENT.md").exists()
    assert (data_dir / "specialists" / "sentry" / "aprendizados.md").exists()
    assert store.get_agent(conn, agent_id).legacy is not None
    assert store.get_agent(conn, agent_id).definition_hash is None  # rolled back together

    report = migration.migrate_files(data_dir, conn, clock=clock)

    agent = store.get_agent(conn, agent_id)
    assert agent.legacy is None
    assert agent.definition_hash == definition_hash(files_of(data_dir).read_definition_text("sentry"))
    assert files_of(data_dir).read_memory("sentry") == "- O alerta X é ruído.\n"
    assert files_of(data_dir).read_secrets("sentry") == {"TOKEN": SECRET_VALUE}
    assert (data_dir / "specialists" / "sentry.migrado" / "aprendizados.md").exists()
    assert [m.slug for m in report.migrated] == ["sentry"]


def test_file_migration_discards_leftover_staging_folder(conn, data_dir, clock):
    add_specialist(conn, data_dir)
    stale = data_dir / "agents" / ".migrando" / "sentry"
    stale.mkdir(parents=True)
    (stale / "AGENT.md").write_text("lixo", encoding="utf-8")

    migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_definition("sentry").name == "Sentry"
    assert not (data_dir / "agents" / ".migrando" / "sentry").exists()


def test_file_migration_skips_agent_without_old_folder_and_warns(conn, data_dir, clock):
    agent_id = add_specialist(conn, data_dir)
    # Remove the old folder: nothing to migrate from.
    import shutil

    shutil.rmtree(data_dir / "specialists" / "sentry")

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated == []
    assert any("sentry" in warning for warning in report.warnings)
    assert not (data_dir / "agents" / "sentry").exists()
    assert store.get_agent(conn, agent_id).legacy is not None


def test_file_migration_warns_and_keeps_agent_when_skill_is_missing(conn, data_dir, clock):
    agent_id = add_specialist(conn, data_dir, skill=None)

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated == []
    assert any("SKILL.md" in warning for warning in report.warnings)
    assert not (data_dir / "agents" / "sentry").exists()
    assert (data_dir / "specialists" / "sentry" / "aprendizados.md").exists()
    assert store.get_agent(conn, agent_id).legacy is not None


def test_file_migration_one_bad_agent_does_not_block_the_others(conn, data_dir, clock):
    add_specialist(conn, data_dir, "broken", skill=None)
    add_specialist(conn, data_dir, "sentry")

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert [m.slug for m in report.migrated] == ["sentry"]
    assert files_of(data_dir).read_definition("sentry").name == "Sentry"


def test_file_migration_ignores_symlinked_secrets_and_never_follows_it(
    conn, data_dir, clock, tmp_path
):
    add_specialist(conn, data_dir)
    outside = tmp_path / "outside.env"
    outside.write_text(f"STOLEN={json.dumps(SECRET_VALUE)}\n", encoding="utf-8")
    (data_dir / "specialists" / "sentry" / "secrets.env").symlink_to(outside)

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_secrets("sentry") == {}
    assert any("secrets.env" in warning for warning in report.warnings)
    assert SECRET_VALUE not in report.text


def test_file_migration_skips_reserved_and_invalid_secret_lines_without_quoting(
    conn, data_dir, clock
):
    add_specialist(conn, data_dir, secrets={"GOOD": "ok", "PATH": "/evil"})
    folder = data_dir / "specialists" / "sentry"
    with open(folder / "secrets.env", "a", encoding="utf-8") as handle:
        handle.write("not a line with a token ghp_leakme\n")

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_secrets("sentry") == {"GOOD": "ok"}
    assert "ghp_leakme" not in report.text
    assert any("2" in warning and "secrets.env" in warning for warning in report.warnings)


def test_file_migration_falls_back_when_effort_is_unknown(conn, data_dir, clock):
    add_specialist(conn, data_dir, effort="turbo")

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_definition("sentry").effort is None
    assert any("turbo" in warning for warning in report.warnings)


def test_file_migration_picks_free_name_when_migrado_folder_exists(conn, data_dir, clock):
    add_specialist(conn, data_dir)
    (data_dir / "specialists" / "sentry.migrado").mkdir()

    migration.migrate_files(data_dir, conn, clock=clock)

    assert (data_dir / "specialists" / "sentry.migrado-2" / "SKILL.md").exists()
    assert (data_dir / "specialists" / "sentry.migrado").is_dir()


def test_file_migration_skips_invalid_slug(conn, data_dir, clock):
    conn.execute(
        "INSERT INTO agents (slug, name, project_id, enabled, legacy_json, created_at, updated_at)"
        " VALUES ('../evil', 'x', 1, 1, '{}', 0, 0)"
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated == []
    assert any("../evil" in warning for warning in report.warnings)
    assert not (data_dir / "evil").exists()
