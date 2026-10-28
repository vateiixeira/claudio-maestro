"""File step of the migration: old specialist folders become agent folders."""

import json
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
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
    ask: list | None = None,
    outward: list | None = None,
    project_id: int = 1,
    name: str = "Sentry",
) -> int:
    """An agent row as migration 31 leaves it, plus the old folder on disk."""
    legacy = {
        "model": model, "effort": effort, "denied_tools": denied or [],
        "extra_project_ids": extra or [],
        "always_ask_patterns": ask or [], "outward_patterns": outward or [],
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


KBGEM_ASK = [
    "npm run release-patch", "npm run publish-lib", "npm publish",
    "node scripts/release-patch.js", "node scripts/publish.js", "yarn release-patch",
    "yarn publish-lib",
]
KBGEM_DENIED = [f"mcp__kbgen-issues__tool{n}" for n in range(9)]
ASK_SENTENCE = "o que pedia o seu ok agora é negado; edite o `AGENT.md` se quiser liberar"


def test_ask_patterns_become_bash_denials_after_the_denied_tools(conn, data_dir, clock):
    agent_id = add_specialist(
        conn, data_dir, "kbgem-issues", denied=KBGEM_DENIED, ask=KBGEM_ASK,
        secrets={"TOKEN": SECRET_VALUE},
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    definition = files_of(data_dir).read_definition("kbgem-issues")
    assert definition.disallowed_tools == KBGEM_DENIED + [f"Bash({p}:*)" for p in KBGEM_ASK]
    assert definition.permission_mode == "bypassPermissions"
    text = report.text
    assert ASK_SENTENCE in text
    for pattern in KBGEM_ASK:
        assert f"`{pattern}`" in text
    assert SECRET_VALUE not in text
    assert (data_dir / "agents" / "migracao-2026-10-28.md").read_text(encoding="utf-8") == text
    assert [m.ask_patterns for m in report.migrated] == [KBGEM_ASK]
    assert store.get_agent(conn, agent_id).legacy is None


def test_ask_patterns_are_deduplicated_and_junk_is_ignored(conn, data_dir, clock):
    add_specialist(
        conn, data_dir, denied=["Bash(npm publish:*)", "WebFetch"],
        ask=["npm publish", " npm publish ", "", "   ", 7, None, ["x"], "git push"],
        outward=["git push", "gh pr merge"],
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    definition = files_of(data_dir).read_definition("sentry")
    assert definition.disallowed_tools == [
        "Bash(npm publish:*)", "WebFetch", "Bash(git push:*)", "Bash(gh pr merge:*)",
    ]
    assert report.migrated[0].ask_patterns == ["npm publish", "git push", "gh pr merge"]


def test_ask_patterns_with_quotes_and_line_breaks_survive_the_round_trip(conn, data_dir, clock):
    add_specialist(conn, data_dir, ask=['echo "a: b"\nrm -rf /', "it's #1"])

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.warnings == []
    definition = files_of(data_dir).read_definition("sentry")
    assert definition.disallowed_tools == ['Bash(echo "a: b"\nrm -rf /:*)', "Bash(it's #1:*)"]
    assert "`echo \"a: b\" rm -rf /`" in report.text  # one line in the report


def test_agent_without_ask_patterns_gets_no_ask_line_and_no_notice(conn, data_dir, clock):
    add_specialist(conn, data_dir, denied=["WebFetch"])

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert files_of(data_dir).read_definition("sentry").disallowed_tools == ["WebFetch"]
    assert ASK_SENTENCE not in report.text
    assert report.migrated[0].ask_patterns == []
    assert store.list_notices(conn) == []


def test_ask_line_is_only_on_the_agent_that_had_patterns(conn, data_dir, clock):
    add_specialist(conn, data_dir, "sentry")
    add_specialist(
        conn, data_dir, "kbgem", name="KBGem", ask=["npm publish"],
        skill=SKILL.replace("name: Sentry", "name: KBGem"),
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.text.count(ASK_SENTENCE) == 1
    section = report.text.split("## kbgem")[1]
    assert ASK_SENTENCE in section
    assert ASK_SENTENCE not in report.text.split("## kbgem")[0]


def test_ask_patterns_leave_one_unread_alert_in_the_inbox(conn, data_dir, clock):
    agent_id = add_specialist(conn, data_dir, "kbgem", name="KBGem", ask=KBGEM_ASK)

    migration.migrate_files(data_dir, conn, clock=clock)

    notices = store.list_notices(conn, unread_only=True)
    assert len(notices) == 1
    assert (notices[0].agent_id, notices[0].kind, notices[0].run_id) == (agent_id, "alert", None)
    assert "npm publish" in notices[0].text and "negado" in notices[0].text
    assert "AGENT.md" in notices[0].text


def test_ask_patterns_are_idempotent_on_a_second_start(conn, data_dir, clock):
    add_specialist(conn, data_dir, "kbgem", name="KBGem", ask=KBGEM_ASK)
    migration.migrate_files(data_dir, conn, clock=clock)
    path = data_dir / "agents" / "migracao-2026-10-28.md"
    before = path.read_text(encoding="utf-8")
    definition_before = files_of(data_dir).read_definition_text("kbgem")
    notices_before = store.list_notices(conn)

    second = migration.migrate_files(data_dir, conn, clock=clock)

    assert second.migrated == [] and second.report_path is None
    assert path.read_text(encoding="utf-8") == before
    assert before.count(ASK_SENTENCE) == 1
    assert files_of(data_dir).read_definition_text("kbgem") == definition_before
    assert store.list_notices(conn) == notices_before


def test_resumed_migration_still_reports_the_ask_patterns_once(conn, data_dir, clock):
    agent_id = add_specialist(conn, data_dir, "kbgem", name="KBGem", ask=KBGEM_ASK)
    original = store.clear_legacy

    def boom(*args, **kwargs):
        raise RuntimeError("crash")

    store.clear_legacy = boom
    try:
        with pytest.raises(RuntimeError):
            migration.migrate_files(data_dir, conn, clock=clock)
    finally:
        store.clear_legacy = original
    assert store.get_agent(conn, agent_id).legacy is not None
    assert store.list_notices(conn) == []  # the notice is part of the same transaction

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated[0].resumed
    assert report.migrated[0].ask_patterns == KBGEM_ASK
    assert ASK_SENTENCE in report.text
    assert len(store.list_notices(conn)) == 1
    definition = files_of(data_dir).read_definition("kbgem")
    assert definition.disallowed_tools == [f"Bash({p}:*)" for p in KBGEM_ASK]


def test_legacy_without_pattern_keys_still_migrates(conn, data_dir, clock):
    """A `legacy_json` written before the patterns were carried over has no such keys."""
    add_specialist(conn, data_dir, "sentry")
    conn.execute(
        "UPDATE agents SET legacy_json = ?",
        (json.dumps({"model": None, "effort": None, "denied_tools": [], "extra_project_ids": []}),),
    )

    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated[0].ask_patterns == []
    assert files_of(data_dir).read_definition("sentry").disallowed_tools == []


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


def test_fresh_install_writes_no_report(conn, data_dir, clock):
    """No `specialists/` folder and no old agent: there is nothing to say, so no file either."""
    report = migration.migrate_files(data_dir, conn, clock=clock)

    assert report.migrated == [] and report.warnings == []
    assert report.report_path is None
    assert not list((data_dir / "agents").glob("migracao-*.md"))
    assert not (data_dir / "specialists").exists()
    # And again on the next start.
    assert migration.migrate_files(data_dir, conn, clock=clock).report_path is None
    assert not list((data_dir / "agents").glob("migracao-*.md"))


def test_report_is_written_when_there_is_only_a_warning(conn, data_dir, clock):
    add_specialist(conn, data_dir, skill=None)  # SKILL.md missing: a warning, nothing migrated

    report = migration.migrate_files(data_dir, conn, clock=clock)

    path = data_dir / "agents" / "migracao-2026-10-28.md"
    assert report.migrated == [] and report.warnings
    assert report.report_path == path
    assert "## Avisos" in path.read_text(encoding="utf-8")


def test_database_at_version_29_goes_through_30_31_32_and_the_files_still_migrate(
    tmp_path, data_dir, clock
):
    """The old tables are dropped by migration 32; the file step must not need them."""
    db_path = tmp_path / "old.db"
    with closing(db.connect(db_path)) as old:
        for statements in db.MIGRATIONS[:29]:
            for statement in statements:
                old.execute(statement) if isinstance(statement, str) else statement(old)
        old.execute("PRAGMA user_version = 29")
        old.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/work/app', '#fff', 0, 0)"
        )
        old.execute(
            "INSERT INTO specialists (id, slug, name, project_id, extra_project_ids, model, effort,"
            " run_text, denied_tools, enabled, created_at, updated_at)"
            " VALUES (3, 'sentry', 'Sentry', 1, '[]', 'sonnet', 'high', 'Veja os erros.',"
            " '[\"WebFetch\"]', 1, 5, 6)"
        )
        old.execute(
            "UPDATE specialists SET autonomy = 'ask', outward_patterns = '[]',"
            " always_ask_patterns = ? WHERE id = 3",
            (json.dumps(KBGEM_ASK),),
        )
        old.execute(
            "INSERT INTO specialist_schedules (specialist_id, days, time) VALUES (3, '12345', '09:00')"
        )
        old.execute(
            "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at,"
            " specialist_id) VALUES ('s', 1, '/work/app', 't', 0, 0, 3)"
        )
    folder = data_dir / "specialists" / "sentry"
    folder.mkdir(parents=True, mode=0o700)
    (folder / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (folder / "aprendizados.md").write_text("- O alerta X é ruído.\n", encoding="utf-8")
    (folder / "secrets.env").write_text(f"TOKEN={json.dumps(SECRET_VALUE)}\n", encoding="utf-8")
    os.chmod(folder / "secrets.env", 0o600)

    with closing(db.connect(db_path)) as migrated:
        db.migrate(migrated)
        assert db.schema_version(migrated) == db.SCHEMA_VERSION >= 32
        names = {r[0] for r in migrated.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not {n for n in names if n.startswith("specialist")}

        report = migration.migrate_files(data_dir, migrated, clock=clock)

        assert [m.slug for m in report.migrated] == ["sentry"] and report.warnings == []
        assert [(r, c) for m in report.migrated for r, c in m.routines] == [("Sentry", 1)]
        files = files_of(data_dir)
        definition = files.read_definition("sentry")
        assert (definition.name, definition.model, definition.effort) == ("Sentry", "sonnet", "high")
        assert definition.disallowed_tools == ["WebFetch"] + [f"Bash({p}:*)" for p in KBGEM_ASK]
        assert files.read_secrets("sentry") == {"TOKEN": SECRET_VALUE}
        assert "ruído" in files.read_memory("sentry")
        path = data_dir / "agents" / "migracao-2026-10-28.md"
        assert report.report_path == path
        text = path.read_text(encoding="utf-8")
        assert "sentry" in text and "TOKEN" in text and SECRET_VALUE not in text
        assert ASK_SENTENCE in text and "`npm publish`" in text
        assert [n.kind for n in store.list_notices(migrated)] == ["alert"]
        assert (data_dir / "specialists" / "sentry.migrado" / "SKILL.md").is_file()
        assert migrated.execute("SELECT agent_id FROM sessions WHERE session_id = 's'").fetchone()[0] == 3
        assert migrated.execute("SELECT legacy_json FROM agents WHERE id = 3").fetchone()[0] is None
        assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []

        # A second start repeats nothing and keeps the report.
        again = migration.migrate_files(data_dir, migrated, clock=clock)
        assert again.migrated == [] and again.report_path is None
        assert path.read_text(encoding="utf-8") == text


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


# --- migrate_work: the CTO, the tasks, the decisions and the PRs of the old `work/` ------------

FORBIDDEN_IN_INHERITED = (
    "#50", "#55", "#135", "delegate_work", "collect_source", "start_work", "reevaluate_work",
    "get_work", "conclude", "declare_workspaces", "verify_ci_run", "request_decision",
    "get_review_evidence", "submit_review",
)


def drop_work_tables(conn: sqlite3.Connection) -> None:
    """Migration 34 already drops the `work_*` tables on the real start, before the file step
    runs, so `migrate_work` may only use `org_legacy_work`, `tasks` and the disk. This makes sure
    no test database keeps one (a table left by a partial migration would hide a dependency)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    names = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'work\\_%' ESCAPE '\\'"
        )
    ]
    for name in names:
        conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute("PRAGMA foreign_keys = ON")
    assert not [n for n in names if not n.startswith("work_")]


@pytest.fixture
def org_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    drop_work_tables(conn)
    return conn


def add_session(conn, session_id: str, project_id: int = 1, agent_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, project_id, cwd, title, created_at, last_activity_at,"
        " agent_id) VALUES (?, ?, '/work/app', 't', 0, 0, ?)",
        (session_id, project_id, agent_id),
    )


def add_task(conn, task_id: int, *, project_id: int = 1, title: str = "Corrigir login",
             status: str = "todo", legacy: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, status, created_by, legacy_json, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, 'human', ?, 10, 20)",
        (task_id, project_id, title, status, json.dumps(legacy) if legacy is not None else None),
    )


def add_legacy(conn, kind: str, project_id: int | None, task_id: int | None, data: dict) -> None:
    conn.execute(
        "INSERT INTO org_legacy_work (kind, project_id, task_id, data) VALUES (?, ?, ?, ?)",
        (kind, project_id, task_id, json.dumps(data)),
    )


def write_work_file(data_dir: Path, value: dict | bytes, name: str | None = None) -> str:
    folder = data_dir / "work"
    folder.mkdir(mode=0o700, exist_ok=True)
    name = name or f"{uuid.uuid4().hex}.json"
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    (folder / name).write_bytes(raw)
    os.chmod(folder / name, 0o600)
    return name


def dossier_legacy(ref: str | None, **extra) -> dict:
    return {"dossier_ref": ref, "source": None, "external_id": None,
            "coordinator_session_id": None, **extra}


def run_work(data_dir, conn, clock):
    return migration.migrate_work(data_dir, conn, files=files_of(data_dir), clock=clock)


def task_row(conn, task_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def slug_id(conn, slug: str) -> int:
    return store.get_agent_by_slug(conn, slug).id


def test_migrate_work_creates_three_agents_per_coordinator(org_conn, data_dir, clock):
    add_session(org_conn, "coord-1", 1)
    add_session(org_conn, "coord-2", 2)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "coord-1", "created_at": 11})
    add_legacy(org_conn, "coordinator", 2, None, {"session_id": "coord-2", "created_at": 12})

    report = run_work(data_dir, org_conn, clock)

    assert report.warnings == []
    assert sorted(report.work.agents_created) == sorted(
        f"{kind}-{pid}" for kind in ("cto", "trabalhador", "revisor") for pid in (1, 2)
    )
    files = files_of(data_dir)
    for pid in (1, 2):
        cto = store.get_agent_by_slug(org_conn, f"cto-{pid}")
        worker = store.get_agent_by_slug(org_conn, f"trabalhador-{pid}")
        reviewer = store.get_agent_by_slug(org_conn, f"revisor-{pid}")
        assert (cto.project_id, cto.reports_to) == (pid, None)
        assert (worker.reports_to, reviewer.reports_to) == (cto.id, cto.id)
        for agent in (cto, worker, reviewer):
            text = files.read_definition_text(agent.slug)
            assert agent.definition_hash == definition_hash(text)
            assert "Contexto herdado" in text
            assert not [word for word in FORBIDDEN_IN_INHERITED if word in text]
            assert mode(files.folder(agent.slug)) == 0o700
        assert "tarefa_criar" in files.read_definition_text(f"cto-{pid}")  # the template text
    assert store.list_legacy_work(org_conn, "coordinator") == []
    path = data_dir / "agents" / "migracao-2026-10-28.md"
    assert report.report_path == path and "cto-1" in path.read_text(encoding="utf-8")


def test_migrate_work_rebinds_coordinator_session_to_cto(org_conn, data_dir, clock):
    add_session(org_conn, "coord-1", 1)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "coord-1", "created_at": 11})

    run_work(data_dir, org_conn, clock)

    cto = store.get_agent_by_slug(org_conn, "cto-1")
    assert cto.main_session_id == "coord-1"
    assert org_conn.execute(
        "SELECT agent_id FROM sessions WHERE session_id = 'coord-1'"
    ).fetchone()[0] == cto.id
    assert org_conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrate_work_does_not_steal_a_session_that_belongs_to_someone_else(
    org_conn, data_dir, clock
):
    other = org_conn.execute(
        "INSERT INTO agents (slug, name, project_id, created_at, updated_at)"
        " VALUES ('outro', 'Outro', 1, 0, 0)"
    ).lastrowid
    add_session(org_conn, "coord-1", 1, agent_id=other)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "coord-1", "created_at": 11})
    add_legacy(org_conn, "coordinator", 2, None, {"session_id": "gone", "created_at": 11})

    report = run_work(data_dir, org_conn, clock)

    assert store.get_agent_by_slug(org_conn, "cto-1").main_session_id is None
    assert org_conn.execute(
        "SELECT agent_id FROM sessions WHERE session_id = 'coord-1'"
    ).fetchone()[0] == other
    assert store.get_agent_by_slug(org_conn, "cto-2").main_session_id is None
    assert len([w for w in report.warnings if "sessão" in w]) == 2
    assert store.list_legacy_work(org_conn, "coordinator") == []


def test_migrate_work_fills_description_from_dossier(org_conn, data_dir, clock):
    ref = write_work_file(
        data_dir, {"kind": "source_issue", "objective": "Investigar o erro 500.",
                   "acceptance": "Causa raiz explicada.", "url": "https://x.test/issues/7"},
    )
    add_task(org_conn, 7, title="Erro 500", status="done",
             legacy=dossier_legacy(ref, source="github", external_id="#7"))

    report = run_work(data_dir, org_conn, clock)

    task = task_row(org_conn, 7)
    assert task["description"].startswith(
        "Investigar o erro 500.\n\n## Critérios de aceite\nCausa raiz explicada."
    )
    assert "github" in task["description"] and "https://x.test/issues/7" in task["description"]
    assert task["legacy_json"] is None
    assert report.work.tasks_completed == [7]
    assert report.warnings == []


def test_migrate_work_description_is_cut_at_the_limit(org_conn, data_dir, clock):
    ref = write_work_file(data_dir, {"objective": "o" * 30_000, "acceptance": "a"})
    add_task(org_conn, 7, status="done", legacy=dossier_legacy(ref))

    report = run_work(data_dir, org_conn, clock)

    description = task_row(org_conn, 7)["description"]
    assert len(description) <= 20_000 and description.startswith("ooo")
    assert any("7" in w and "cortada" in w for w in report.warnings)


def test_migrate_work_without_dossier_falls_back_to_title(org_conn, data_dir, clock):
    missing = f"{uuid.uuid4().hex}.json"
    oversize = write_work_file(data_dir, b'{"objective": "' + b"x" * 70_000 + b'"}')
    garbage = write_work_file(data_dir, b"not json")
    not_dict = write_work_file(data_dir, b"[1, 2]")
    outside = data_dir / "outside.json"
    outside.write_text('{"objective": "segredo"}', encoding="utf-8")
    link = f"{uuid.uuid4().hex}.json"
    (data_dir / "work" / link).symlink_to(outside)
    cases = {1: missing, 2: oversize, 3: garbage, 4: not_dict, 5: link, 6: "../outside.json",
             7: None}
    for task_id, ref in cases.items():
        add_task(org_conn, task_id, title=f"Titulo {task_id}", status="done",
                 legacy=dossier_legacy(ref))

    report = run_work(data_dir, org_conn, clock)  # no exception for any of them

    for task_id in cases:
        row = task_row(org_conn, task_id)
        assert row["description"] == f"Titulo {task_id}"
        assert row["legacy_json"] is None
    assert "segredo" not in "".join(r["description"] for r in org_conn.execute("SELECT * FROM tasks"))
    assert len(report.warnings) == len(cases)
    assert all("dossiê" in w for w in report.warnings)


def test_migrate_work_without_work_folder_falls_back_too(org_conn, data_dir, clock):
    add_task(org_conn, 1, title="Sem pasta", status="done",
             legacy=dossier_legacy(f"{uuid.uuid4().hex}.json"))

    run_work(data_dir, org_conn, clock)

    assert task_row(org_conn, 1)["description"] == "Sem pasta"
    assert not (data_dir / "work").exists()  # reading never creates the folder


def test_migrate_work_assigns_open_tasks_to_worker(org_conn, data_dir, clock):
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    for task_id, status in enumerate(
        ("todo", "in_progress", "in_review", "blocked", "done", "cancelled"), start=1
    ):
        add_task(org_conn, task_id, status=status, legacy=dossier_legacy(None))
    add_task(org_conn, 20, project_id=2, status="todo", legacy=dossier_legacy(None))
    add_task(org_conn, 30, status="todo")  # a task created in the new system: untouched

    report = run_work(data_dir, org_conn, clock)

    cto, worker, reviewer = (slug_id(org_conn, f"{k}-1") for k in ("cto", "trabalhador", "revisor"))
    for task_id in (1, 2, 3, 4):
        row = task_row(org_conn, task_id)
        assert (row["assignee_agent_id"], row["created_by_agent_id"], row["created_by"]) == (
            worker, cto, "agent",
        )
        assert row["reviewer_agent_id"] == (reviewer if task_id == 3 else None)
        assert row["legacy_json"] is None
    for task_id in (5, 6):  # closed ones keep no owner
        row = task_row(org_conn, task_id)
        assert (row["assignee_agent_id"], row["created_by"]) == (None, "human")
        assert row["status"] == ("done" if task_id == 5 else "cancelled")
    assert (task_row(org_conn, 4)["status"], task_row(org_conn, 2)["status"]) == (
        "blocked", "in_progress"
    )
    # Project 2 has no coordinator: the task has no owner, and the report says so.
    lonely = task_row(org_conn, 20)
    assert (lonely["assignee_agent_id"], lonely["legacy_json"]) == (None, None)
    assert any("20" in w and "sem responsável" in w for w in report.warnings)
    assert task_row(org_conn, 30)["created_by"] == "human"
    # Nothing is woken by the migration.
    assert org_conn.execute("SELECT COUNT(*) FROM wakeups").fetchone()[0] == 0
    assert org_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def pending_request(data_dir: Path, **fields) -> str:
    return write_work_file(
        data_dir, {"question": "Posso apagar a tabela?", "action": "DROP TABLE x",
                   "options": ["sim", "não"], "evidence": [], "scope": {"work_item_id": 1},
                   **fields},
    )


def test_migrate_work_copies_pending_decisions_and_prs(org_conn, data_dir, clock):
    add_session(org_conn, "worker-sess", 1)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    add_task(org_conn, 1, status="blocked", legacy=dossier_legacy(None))
    add_task(org_conn, 2, status="in_review", legacy=dossier_legacy(None))
    ref = pending_request(data_dir)
    add_legacy(org_conn, "decision", 1, 1, {"request_ref": ref, "created_at": 123})
    add_legacy(org_conn, "pr", 1, 1, {"url": "https://github.com/o/r/pull/9/?x=1",
                                      "last_session_id": "worker-sess", "created_at": 50,
                                      "closed": 0})
    add_legacy(org_conn, "pr", 1, 2, {"url": "https://github.com/o/r/pull/10",
                                      "last_session_id": "never-existed", "created_at": 60,
                                      "closed": 1})

    report = run_work(data_dir, org_conn, clock)

    worker = slug_id(org_conn, "trabalhador-1")
    decisions = store.list_decisions(org_conn)
    assert len(decisions) == 1
    decision = decisions[0]
    assert (decision.project_id, decision.task_id, decision.agent_id, decision.status) == (
        1, 1, worker, "pending",
    )
    assert decision.question == "Posso apagar a tabela?\n\nAção proposta: DROP TABLE x"
    assert decision.options == ["sim", "não"] and decision.created_at == 123
    assert decision.run_id is None and decision.session_id is None
    first = store.get_pr(org_conn, "https://github.com/o/r/pull/9")
    second = store.get_pr(org_conn, "https://github.com/o/r/pull/10")
    assert (first.agent_id, first.session_id, first.closed, first.created_at) == (
        worker, "worker-sess", False, 50,
    )
    assert (second.agent_id, second.session_id, second.closed) == (worker, None, True)
    tasks = dict(org_conn.execute("SELECT url, task_id FROM agent_prs").fetchall())
    assert tasks == {"https://github.com/o/r/pull/9": 1, "https://github.com/o/r/pull/10": 2}
    assert (report.work.decisions, report.work.prs) == (1, 2)
    assert store.list_legacy_work(org_conn) == []
    assert org_conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrate_work_decision_limits_and_fallbacks(org_conn, data_dir, clock):
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    add_task(org_conn, 1, title="Tarefa A", status="blocked", legacy=dossier_legacy(None))
    long_question = "q" * 1990
    big = pending_request(
        data_dir, question=long_question, action="a" * 100,
        options=[f"opt{i}" + "o" * 300 for i in range(12)] + ["", 5],
    )
    add_legacy(org_conn, "decision", 1, 1, {"request_ref": big, "created_at": 1})
    add_legacy(org_conn, "decision", 1, 1,
               {"request_ref": f"{uuid.uuid4().hex}.json", "created_at": 2})

    report = run_work(data_dir, org_conn, clock)

    big_decision, lost = store.list_decisions(org_conn)
    assert big_decision.question == long_question  # the action did not fit in 2.000
    assert len(big_decision.options) == 8
    assert all(len(option) == 200 and option.startswith("opt") for option in big_decision.options)
    assert "Tarefa A" in lost.question and lost.options == []
    assert any("pedido" in w for w in report.warnings)


def test_migrate_work_discards_what_has_no_agent_and_says_so(org_conn, data_dir, clock):
    add_task(org_conn, 1, title="Sem dono", status="blocked", legacy=dossier_legacy(None))
    ref = pending_request(data_dir)
    add_legacy(org_conn, "decision", 2, 1, {"request_ref": ref, "created_at": 1})
    add_legacy(org_conn, "pr", 2, 1, {"url": "https://github.com/o/r/pull/3",
                                      "last_session_id": None, "created_at": 1, "closed": 0})
    add_legacy(org_conn, "coordinator", 99, None, {"session_id": "x", "created_at": 1})

    report = run_work(data_dir, org_conn, clock)

    assert store.list_legacy_work(org_conn) == []
    assert store.list_decisions(org_conn) == []
    assert org_conn.execute("SELECT COUNT(*) FROM agent_prs").fetchone()[0] == 0
    joined = "\n".join(report.warnings)
    assert "Posso apagar a tabela?" in joined  # the question is kept in the report
    assert "https://github.com/o/r/pull/3" in joined
    assert "projeto 99" in joined
    assert store.list_agents(org_conn) == []


def test_migrate_work_is_idempotent(org_conn, data_dir, clock):
    add_session(org_conn, "coord-1", 1)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "coord-1", "created_at": 11})
    ref = write_work_file(data_dir, {"objective": "Fazer X", "acceptance": "Y"})
    add_task(org_conn, 1, status="blocked", legacy=dossier_legacy(ref))
    add_legacy(org_conn, "decision", 1, 1, {"request_ref": pending_request(data_dir),
                                            "created_at": 5})
    add_legacy(org_conn, "pr", 1, 1, {"url": "https://github.com/o/r/pull/1",
                                      "last_session_id": None, "created_at": 1, "closed": 0})
    first = run_work(data_dir, org_conn, clock)
    path = first.report_path
    assert path is not None
    snapshot = {
        "agents": store.list_agents(org_conn),
        "task": tuple(task_row(org_conn, 1)),
        "decisions": store.list_decisions(org_conn),
        "prs": tuple(map(tuple, org_conn.execute("SELECT * FROM agent_prs"))),
        "files": {
            slug: files_of(data_dir).read_definition_text(slug)
            for slug in ("cto-1", "trabalhador-1", "revisor-1")
        },
        "report": path.read_text(encoding="utf-8"),
    }

    again = run_work(data_dir, org_conn, clock)

    assert again.report_path is None and again.warnings == []
    assert (again.work.agents_created, again.work.tasks_completed, again.work.decisions,
            again.work.prs) == ([], [], 0, 0)
    assert store.list_agents(org_conn) == snapshot["agents"]
    assert tuple(task_row(org_conn, 1)) == snapshot["task"]
    assert store.list_decisions(org_conn) == snapshot["decisions"]
    assert tuple(map(tuple, org_conn.execute("SELECT * FROM agent_prs"))) == snapshot["prs"]
    assert {
        slug: files_of(data_dir).read_definition_text(slug) for slug in snapshot["files"]
    } == snapshot["files"]
    assert path.read_text(encoding="utf-8") == snapshot["report"]
    assert store.list_legacy_work(org_conn) == []


def test_migrate_work_reuses_existing_agents_without_overwriting_agent_md(
    org_conn, data_dir, clock
):
    now = 5
    cto = store.create_agent(org_conn, slug="cto-1", name="Meu CTO", project_id=1,
                             reports_to=None, now=now)
    files = files_of(data_dir)
    custom = template_text("Meu CTO", "cto").replace("CTO deste projeto", "CHEFE ÚNICO")
    files.create("cto-1", custom)
    # A folder left by an earlier run that died before the commit: no row, same protection.
    files.create("revisor-1", template_text("Revisor", "reviewer").replace("Revisor", "Meu revisor"))
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})

    report = run_work(data_dir, org_conn, clock)

    assert sorted(report.work.agents_created) == ["revisor-1", "trabalhador-1"]
    assert report.work.agents_reused == ["cto-1"]
    assert files.read_definition_text("cto-1") == custom
    assert "Contexto herdado" not in files.read_definition_text("revisor-1")
    assert "Meu revisor" in files.read_definition_text("revisor-1")
    reviewer = store.get_agent_by_slug(org_conn, "revisor-1")
    assert reviewer.reports_to == cto.id
    assert reviewer.definition_hash == definition_hash(files.read_definition_text("revisor-1"))
    assert "Contexto herdado" in files.read_definition_text("trabalhador-1")
    assert len([a for a in store.list_agents(org_conn) if a.slug == "cto-1"]) == 1


def template_text(name: str, kind: str) -> str:
    from claudio_maestro.org.definition import template

    return template(name, kind)


def test_migrate_work_leaves_a_project_alone_when_its_agents_cannot_be_made(
    org_conn, data_dir, clock
):
    # The slug is taken by an agent of another project: the unit rolls back, nothing is lost.
    store.create_agent(org_conn, slug="cto-1", name="Intruso", project_id=2, reports_to=None, now=1)
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    add_task(org_conn, 1, status="todo", legacy=dossier_legacy(None))
    add_legacy(org_conn, "decision", 1, 1, {"request_ref": pending_request(data_dir),
                                            "created_at": 5})

    report = run_work(data_dir, org_conn, clock)

    assert any("cto-1" in w for w in report.warnings)
    assert store.get_agent_by_slug(org_conn, "trabalhador-1") is None
    assert not files_of(data_dir).folder("trabalhador-1").exists()
    assert len(store.list_legacy_work(org_conn)) == 2  # coordinator and decision wait
    assert task_row(org_conn, 1)["legacy_json"] is not None  # and so does the task


def test_migrate_work_does_not_import_the_old_work_package():
    import ast

    tree = ast.parse(Path(migration.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append((node.module or "") + " " + " ".join(a.name for a in node.names))
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    assert not [name for name in imported if "claudio_maestro.work" in name or " work" in f" {name}"]


def test_migrate_work_from_a_version_32_database_with_real_work_tables(
    tmp_path, data_dir, clock
):
    """Migration 33 hands the coordinators, decisions and PRs over; the work tables can be
    dropped right after (what migration 34 does) and the file step still finishes."""
    db_path = tmp_path / "old.db"
    with closing(db.connect(db_path)) as old:
        for statements in db.MIGRATIONS[:32]:
            for statement in statements:
                old.execute(statement) if isinstance(statement, str) else statement(old)
        old.execute("PRAGMA user_version = 32")
        old.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/work/app', '#fff', 0, 0)"
        )
        for sid in ("coord", "worker"):
            old.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, '/work/app', 't', 0, 0)",
                (sid,),
            )
        old.execute("INSERT INTO work_coordinators (project_id, session_id, created_at)"
                    " VALUES (1, 'coord', 30)")
        for item_id, status, title in ((1, "active", "Ativa"), (2, "waiting", "Esperando"),
                                       (3, "done", "Pronta")):
            old.execute(
                "INSERT INTO work_items (id, project_id, source, source_instance, source_project,"
                " external_id, title, priority, status, phase, created_at, updated_at)"
                " VALUES (?, 1, 'github', 'i', 'p', ?, ?, 'normal', ?, 'investigation', 1, 2)",
                (item_id, f"#{item_id}", title, status),
            )
        dossier = write_work_file(data_dir, {"objective": "Investigar", "acceptance": "Relatório"})
        old.execute("INSERT INTO work_specs (work_item_id, dossier_ref, role)"
                    " VALUES (2, ?, 'investigator')", (dossier,))
        old.execute(
            "INSERT INTO work_attempts (id, work_item_id, session_id, role, state, work_revision,"
            " created_at, updated_at) VALUES (1, 2, 'worker', 'investigator', 'waiting', 1, 3, 3)"
        )
        request = pending_request(data_dir, question="Pode migrar?", action="Rodar a migração")
        old.execute(
            "INSERT INTO work_decision_requests (work_item_id, attempt_id, work_revision,"
            " dossier_ref, target_ref, request_ref, status, created_at)"
            " VALUES (2, 1, 1, ?, 'x', ?, 'pending', 99)", (dossier, request),
        )
        old.execute(
            "INSERT INTO work_decision_requests (work_item_id, attempt_id, work_revision,"
            " dossier_ref, target_ref, request_ref, status, created_at)"
            " VALUES (2, 1, 1, ?, 'x', ?, 'expired', 98)", (dossier, request),
        )
        old.execute(
            "INSERT INTO work_prs (url, project_id, work_item_id, origin_attempt_id,"
            " last_attempt_id, origin_session_id, last_session_id, workspace, target_ref,"
            " created_at, closed) VALUES ('https://github.com/o/r/pull/5', 1, 2, 1, 1, 'worker',"
            " 'worker', '/work/app', 'x', 77, 0)"
        )

    with closing(db.connect(db_path)) as migrated:
        db.migrate(migrated)
        drop_work_tables(migrated)

        report = run_work(data_dir, migrated, clock)

        assert report.warnings == [] or all("dossiê" in w for w in report.warnings)
        cto = store.get_agent_by_slug(migrated, "cto-1")
        worker = store.get_agent_by_slug(migrated, "trabalhador-1")
        assert cto.main_session_id == "coord"
        assert [task_row(migrated, i)["assignee_agent_id"] for i in (1, 2, 3)] == [
            worker.id, worker.id, None,
        ]
        assert task_row(migrated, 2)["description"].startswith(
            "Investigar\n\n## Critérios de aceite\nRelatório"
        )
        assert task_row(migrated, 1)["description"] == "Ativa"  # no dossier: title
        decision, = store.list_decisions(migrated)
        assert (decision.task_id, decision.agent_id, decision.created_at) == (2, worker.id, 99)
        assert "Pode migrar?" in decision.question
        pr = store.get_pr(migrated, "https://github.com/o/r/pull/5")
        assert (pr.agent_id, pr.session_id, pr.created_at) == (worker.id, "worker", 77)
        assert store.list_legacy_work(migrated) == []
        assert migrated.execute("PRAGMA foreign_key_check").fetchall() == []


# --- Round 1 of the review ---------------------------------------------------------------------


def test_migrate_work_prs_are_marked_as_polled_so_old_comments_stay_quiet(
    org_conn, data_dir, clock
):
    """Without `polled_at` the sweep reads everything since the PR was created and would wake
    the worker for comments the old system already delivered."""
    import asyncio

    from claudio_maestro.org import gh_comments

    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    add_task(org_conn, 1, status="in_progress", legacy=dossier_legacy(None))
    base = int(datetime(2026, 10, 28, 9, 30).timestamp())
    url_old, url_new, url_key = (f"https://github.com/acme/app/pull/{n}" for n in (7, 8, 9))
    add_legacy(org_conn, "pr", 1, 1, {"url": url_old, "last_session_id": None, "created_at": 50,
                                      "polled_at": 4_000, "closed": 0})
    add_legacy(org_conn, "pr", 1, 1, {"url": url_new, "last_session_id": None, "created_at": 50,
                                      "polled_at": None, "closed": 0})
    add_legacy(org_conn, "pr", 1, 1, {"url": url_key, "last_session_id": None, "created_at": 50,
                                      "closed": 0})  # row from before the key existed

    run_work(data_dir, org_conn, clock)

    assert store.get_pr(org_conn, url_old).polled_at == 4_000
    assert store.get_pr(org_conn, url_new).polled_at == base
    assert store.get_pr(org_conn, url_key).polled_at == base

    # A sweep that finds an old comment of the owner queues nothing and wakes nobody.
    def iso(epoch: int) -> str:
        return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    old_comment = {"id": 1, "user": {"login": "vini"}, "body": "antigo", "created_at": iso(base - 5_000),
                   "html_url": f"{url_new}#issuecomment-1"}

    async def gh(args):
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"state": "OPEN"})
        return 0, json.dumps([[old_comment] if args[1].endswith("/issues/8/comments") else []])

    org_conn.close()  # `poll_comments` opens its own connections
    db_file = data_dir.parent / "t.db"
    with closing(db.connect(db_file)) as again:
        assert store.queued_comments(again) == []
        queued = asyncio.run(
            gh_comments.poll_comments(db_file, owner="vini", run_gh=gh, now=float(base + 60))
        )
        assert queued == 0 and store.queued_comments(again) == []
        assert again.execute("SELECT COUNT(*) FROM wakeups").fetchone()[0] == 0


def test_migrate_work_deeply_nested_dossier_falls_back_to_title(org_conn, data_dir, clock):
    deep = write_work_file(data_dir, b'{"objective": ' + b"[" * 30_000 + b"]" * 30_000 + b"}")
    add_task(org_conn, 1, title="Aninhado", status="done", legacy=dossier_legacy(deep))
    add_task(org_conn, 2, title="Outro", status="done",
             legacy=dossier_legacy(write_work_file(data_dir, {"objective": "ok"})))
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})
    add_legacy(org_conn, "decision", 1, 1, {"request_ref": deep, "created_at": 1})

    report = run_work(data_dir, org_conn, clock)  # no RecursionError

    assert task_row(org_conn, 1)["description"] == "Aninhado"
    assert task_row(org_conn, 2)["description"] == "ok"
    assert any("tarefa 1" in w and "dossiê" in w for w in report.warnings)
    assert len(store.list_decisions(org_conn)) == 1


def test_migrate_work_blocked_project_warning_names_the_folder_to_check(
    org_conn, data_dir, clock
):
    folder = files_of(data_dir).folder("trabalhador-1")
    folder.mkdir(parents=True, mode=0o700)  # half-made folder: no AGENT.md inside
    add_legacy(org_conn, "coordinator", 1, None, {"session_id": "gone", "created_at": 11})

    report = run_work(data_dir, org_conn, clock)

    warning = next(w for w in report.warnings if "projeto 1" in w)
    assert str(folder) in warning and "apague" in warning
    assert store.get_agent_by_slug(org_conn, "trabalhador-1") is None
    assert not files_of(data_dir).folder("cto-1").exists()  # the others were rolled back
    assert len(store.list_legacy_work(org_conn)) == 1
