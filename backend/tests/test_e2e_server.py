"""Tests for scripts/e2e_server.py: the throwaway backend the E2E suite runs against."""

import asyncio
import importlib.util
import json
import os
import re
import signal
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest
from claude_agent_sdk import list_sessions
from fastapi.testclient import TestClient
from git_helpers import GIT_ENV, git

from claudio_maestro import db, gitinfo, history, projects
from claudio_maestro.agent.base import AgentError, AgentOptions
from claudio_maestro.claudecli import ClaudeCliUnavailable
from claudio_maestro.config import load_settings
from claudio_maestro.digest.model import DigestModelError, DigestRequest

# The suite stubs these file lookups for every test; read before the stubs are applied.
REAL_FILE_LOOKUPS = {
    name: getattr(history, name)
    for name in ("sdk_session_file", "sdk_session_file_mtime", "sdk_session_file_exists")
}

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_server.py"
_spec = importlib.util.spec_from_file_location("e2e_server_script", SCRIPT)
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)


def apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)


# e2e_port --------------------------------------------------------------------


def test_port_defaults_to_6620():
    assert e2e.e2e_port({}) == 6620


def test_port_can_be_overridden():
    assert e2e.e2e_port({"MAESTRO_E2E_PORT": "6633"}) == 6633


@pytest.mark.parametrize("port", ["6660", "6600", "6610"])
def test_port_refuses_service_and_preview_ports(port):
    with pytest.raises(e2e.E2EError, match="serviços"):
        e2e.e2e_port({"MAESTRO_E2E_PORT": port})


@pytest.mark.parametrize("port", ["6667", "80", "abc", "70000"])
def test_port_refuses_blocked_or_invalid_ports(port):
    with pytest.raises(e2e.E2EError):
        e2e.e2e_port({"MAESTRO_E2E_PORT": port})


# isolated_env ----------------------------------------------------------------


def test_isolated_env_points_everything_inside_root(tmp_path):
    env = e2e.isolated_env({}, tmp_path, 6620)

    for key in ("HOME", "MAESTRO_HOME", "MAESTRO_DATA_DIR", "CLAUDE_CONFIG_DIR"):
        assert Path(env[key]).is_relative_to(tmp_path), key
    assert env["MAESTRO_PORT"] == "6620"


def test_isolated_env_drops_inherited_variables(tmp_path):
    base = {
        "PATH": "/usr/bin",
        "MAESTRO_PREVIEW_PORT": "6610",
        "MAESTRO_DEV_PORT": "6600",
        "MAESTRO_RUN_MODE": "systemd",
        "MAESTRO_HOME": "/home/real",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
        "CLAUDECODE": "1",
    }

    env = e2e.isolated_env(base, tmp_path, 6620)

    assert env["PATH"] == "/usr/bin"
    for dropped in ("MAESTRO_PREVIEW_PORT", "MAESTRO_DEV_PORT", "MAESTRO_RUN_MODE",
                    "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE"):
        assert dropped not in env
    assert env["MAESTRO_HOME"] != "/home/real"


def test_isolated_env_keeps_the_git_config_of_whoever_runs_it_out(tmp_path):
    base = {
        "XDG_CONFIG_HOME": "/home/real/.config",
        "GIT_CONFIG_GLOBAL": "/home/real/.gitconfig",
        "GIT_CONFIG_SYSTEM": "/etc/real-gitconfig",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/home/real/hooks",
        "GIT_AUTHOR_NAME": "Real",
    }

    env = e2e.isolated_env(base, tmp_path, 6620)

    assert "XDG_CONFIG_HOME" not in env
    # Only for git run straight from the process: run_git drops GIT_* variables, so the server's
    # git still reads /etc/gitconfig. The personal config is out because of HOME and XDG above.
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    for dropped in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        assert dropped not in env
    # The global config git reads then is the one in the fake HOME, which does not exist.
    assert Path(env["HOME"]).is_relative_to(tmp_path)


def test_isolated_env_keeps_the_routines_scheduler_off_whatever_is_inherited(tmp_path):
    base = {"MAESTRO_ROUTINES_SCHEDULER": "1", "MAESTRO_SPECIALISTS_SCHEDULER": "1"}
    env = e2e.isolated_env(base, tmp_path, 6620)
    assert env["MAESTRO_ROUTINES_SCHEDULER"] == "0"
    assert "MAESTRO_SPECIALISTS_SCHEDULER" not in env


def test_isolated_env_turns_off_outside_work(tmp_path):
    env = e2e.isolated_env({}, tmp_path, 6620)
    assert 'MAESTRO_WORK_DISPATCHER' not in env
    assert env['MAESTRO_REMOTE_RECONNECT'] == '0'
    assert env['MAESTRO_ROUTINES_SCHEDULER'] == '0'

    assert env["MAESTRO_AGENTD"] == "0"
    assert env["MAESTRO_UPDATE_CHECK"] == "0"
    assert env["MAESTRO_USAGE_CHECK"] == "0"
    assert env["MAESTRO_CLAUDE_CHECK"] == "0"


# seed --------------------------------------------------------------------------


def test_seed_registers_the_scenario_projects(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    with closing(db.connect(load_settings().db_path)) as conn:
        registered = projects.list_projects(conn)
    assert [p.name for p in registered] == [p["name"] for p in (*e2e.SCENARIO, *e2e.GIT_SCENARIO)]
    assert all(Path(p.path).is_dir() for p in registered)
    assert all(Path(p.path).is_relative_to(tmp_path) for p in registered)


def test_seed_creates_the_triagem_agent_with_routine_runs_and_notices(tmp_path, monkeypatch):
    from claudio_maestro.org import store
    from claudio_maestro.org.files import AgentFiles

    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    settings = load_settings()
    with closing(db.connect(settings.db_path)) as conn:
        project = next(p for p in projects.list_projects(conn) if p.name == "Loja Demo")
        agents = store.list_agents(conn)
        assert [(a.slug, a.name, a.project_id) for a in agents] == [
            ("maestro", "Maestro", project.id),
            ("triagem", "Triagem", project.id),
            ("revisor", "Revisor", project.id),
        ]
        triagem = agents[1]
        assert triagem.legacy is None
        routines = store.list_routines(conn, agent_id=triagem.id)
        schedules = store.list_schedules(conn, routines[0].id)
        runs = [r for r in store.list_runs(conn, triagem.id) if r.task_id is None]
        notices = store.list_notices(conn)
        announcements = store.pending_announcements(conn, triagem.id)
    assert len(announcements) == 1
    assert announcements[0].text == e2e.TRIAGEM_SUMMARY_TEXT
    assert [r.name for r in routines] == ["Triagem"]
    assert routines[0].create_task is True
    assert [(s.days, s.time) for s in schedules] == [("12345", "03:00")]
    assert sorted(r.outcome for r in runs) == ["concluded", "failed"]
    assert {r.source for r in runs} == {"routine"}
    failed = next(r for r in runs if r.outcome == "failed")
    assert failed.reason == e2e.TRIAGEM_FAILURE_REASON
    assert all(r.ended_at is not None for r in runs)
    by_kind = {n.kind: n for n in notices}
    assert set(by_kind) == {"alert", "summary"}
    assert by_kind["alert"].text == e2e.TRIAGEM_ALERT_TEXT
    assert by_kind["alert"].read_at is None
    assert by_kind["summary"].text == e2e.TRIAGEM_SUMMARY_TEXT
    assert by_kind["summary"].read_at is not None
    files = AgentFiles(settings.data_dir / "agents")
    definition = files.read_definition("triagem")
    assert definition.name and definition.description and definition.body.strip()
    assert (settings.data_dir / "agents" / "triagem" / "AGENT.md").resolve().is_relative_to(
        tmp_path.resolve()
    )
    assert not (settings.data_dir / "specialists").exists()


def test_seed_builds_the_organization_tree_with_valid_definitions(tmp_path, monkeypatch):
    from claudio_maestro.org import store
    from claudio_maestro.org.definition import definition_hash
    from claudio_maestro.org.files import AgentFiles

    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    settings = load_settings()
    files = AgentFiles(settings.data_dir / "agents")
    with closing(db.connect(settings.db_path)) as conn:
        by_slug = {a.slug: a for a in store.list_agents(conn)}
    maestro, triagem, revisor = by_slug["maestro"], by_slug["triagem"], by_slug["revisor"]
    assert maestro.reports_to is None
    assert triagem.reports_to == maestro.id and revisor.reports_to == maestro.id
    assert all(a.enabled for a in by_slug.values())
    for agent in by_slug.values():
        # Every file opens and the hash on the row is the one of the file, as the API leaves it.
        files.read_definition(agent.slug)
        assert agent.definition_hash == definition_hash(files.read_definition_text(agent.slug))
    assert files.read_definition("maestro").name == "Maestro"
    assert files.read_definition("revisor").name == "Revisor"


def test_seed_creates_the_tasks_with_thread_run_and_decision(tmp_path, monkeypatch):
    from claudio_maestro.org import store

    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    with closing(db.connect(load_settings().db_path)) as conn:
        agents = {a.slug: a for a in store.list_agents(conn)}
        tasks = {t.title: t for t in store.list_tasks(conn, limit=500)}
        by_title = {title: tasks[title] for title in e2e.TASK_TITLES.values()}
        first = by_title[e2e.TASK_TITLES["urgent"]]
        comments = store.list_comments(conn, first.id)
        runs = store.list_task_runs(conn, first.id)
        decisions = store.list_decisions(conn)
        project = projects.list_projects(conn)[0]

    titles = e2e.TASK_TITLES
    assert {t.project_id for t in tasks.values()} == {project.id}
    assert first.status == "in_progress"
    assert first.assignee_agent_id == agents["triagem"].id
    assert [c.author_kind for c in comments] == ["human", "agent", "app"]
    assert comments[1].author_agent_id == agents["triagem"].id
    assert [(r.outcome, r.source) for r in runs] == [("concluded", "assignment")]
    assert first.run_count == 1
    review = by_title[titles["review"]]
    assert review.status == "in_review"
    assert review.assignee_agent_id == agents["triagem"].id
    assert review.reviewer_agent_id == agents["revisor"].id
    blocked = by_title[titles["blocked"]]
    assert blocked.status == "blocked" and blocked.blocked_reason == e2e.BLOCKED_REASON
    assert by_title[titles["done"]].status == "done"
    assert by_title[titles["done"]].closed_at is not None
    # The tasks that the specs change are theirs alone and nobody works on them: no wake-up.
    for key in ("loose", "unblock"):
        assert by_title[titles[key]].assignee_agent_id is None
    assert by_title[titles["loose"]].status == "todo"
    assert by_title[titles["unblock"]].status == "blocked"
    assert [(d.question, d.task_id, d.status) for d in decisions] == [
        (e2e.DECISION_QUESTION, first.id, "pending")
    ]
    assert decisions[0].options == e2e.DECISION_OPTIONS
    assert decisions[0].agent_id == agents["triagem"].id


def _seeded(tmp_path, monkeypatch) -> Path:
    """Seed in an isolated environment; returns the fake HOME, where the projects are."""
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    e2e.seed(tmp_path)
    return Path(os.environ["MAESTRO_HOME"]).resolve()


def test_seed_creates_the_history_project(tmp_path, monkeypatch):
    home = _seeded(tmp_path, monkeypatch)
    api = home / "projetos" / "historico-demo" / "api"
    log = git(api, "log", "--format=%s", "main").splitlines()
    assert len(log) == 35 and log[0] == "Ajustar a rota 35"
    assert git(api, "rev-list", "--left-right", "--count", "main...origin/main").split() == ["2", "1"]
    assert set(git(api, "branch", "--format=%(refname:short)").split()) == {"main", "feat/relatorios"}
    assert (home / "projetos" / "historico-demo" / "web" / ".git").is_dir()
    for path in (api, tmp_path / "remotes"):
        assert path.resolve().is_relative_to(tmp_path.resolve())


def test_seed_creates_the_changes_project(tmp_path, monkeypatch):
    home = _seeded(tmp_path, monkeypatch)
    repo = home / "projetos" / "alteracoes-demo"
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    assert sorted(status.splitlines()) == sorted([" M src/carrinho.ts", "?? src/cupom.ts", " M README.md"])
    assert git(repo, "config", "user.email").strip() == "demo@example.com"


def test_seed_creates_the_sync_project(tmp_path, monkeypatch):
    home = _seeded(tmp_path, monkeypatch)
    loja = home / "projetos" / "sincronia-demo" / "loja"
    assert git(loja, "rev-list", "--left-right", "--count", "main...origin/main").split() == ["1", "1"]
    site = home / "projetos" / "sincronia-demo" / "site"
    assert git(site, "symbolic-ref", "--short", "HEAD").strip() == "feat/nova"
    assert subprocess.run(["git", "-C", str(site), "rev-parse", "@{upstream}"], capture_output=True, env=GIT_ENV).returncode != 0
    for path in (loja, site):
        url = git(path, "remote", "get-url", "origin").strip()
        assert Path(url).resolve().is_relative_to(tmp_path.resolve())


def test_seed_creates_the_branches_project_with_three_repositories_and_a_conversation(tmp_path, monkeypatch):
    home = _seeded(tmp_path, monkeypatch)
    project = home / "projetos" / "ramos-demo"
    for name in ("api", "docs", "web"):
        assert git(project / name, "symbolic-ref", "--short", "HEAD").strip() == "main"
    folder = load_settings().claude_projects_dir / re.sub(r"[^a-zA-Z0-9]", "-", str(project.resolve()))
    assert len(list(folder.glob("*.jsonl"))) == 1


def test_seed_creates_the_merge_project(tmp_path, monkeypatch):
    home = _seeded(tmp_path, monkeypatch)
    repo = home / "projetos" / "merge-demo"
    branches = git(repo, "branch", "--format=%(refname:short)").split()
    assert set(branches) == {"main", "feat/cupom", "feat/docs", "feat/limpeza"}
    assert git(repo, "status", "--porcelain=v1") == ""

    def merge_tree(other: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), "merge-tree", "--write-tree", "main", other],
            capture_output=True, text=True, env=GIT_ENV,
        )

    assert merge_tree("feat/cupom").returncode == 1  # conflicts with main, with markers
    assert merge_tree("feat/docs").returncode == 0
    deleted = merge_tree("feat/limpeza")
    assert deleted.returncode == 1 and "docs/antigo.md" in deleted.stdout


def test_seed_ignores_the_git_config_of_whoever_runs_it(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    (xdg / "git").mkdir(parents=True)
    (xdg / "git" / "config").write_text(
        "[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /nao/existe/gpg\n"
    )
    root = tmp_path / "root"
    root.mkdir()
    apply_env(monkeypatch, e2e.isolated_env({}, root, 6620))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    e2e.seed(root)

    api = Path(os.environ["MAESTRO_HOME"]) / "projetos" / "historico-demo" / "api"
    assert len(git(api, "log", "--format=%s", "main").splitlines()) == 35


def test_seed_turns_a_git_error_into_an_e2e_error(tmp_path, monkeypatch):
    async def broken(*args, **kwargs):
        raise e2e.gitinfo.GitError("tempo esgotado")

    monkeypatch.setattr(e2e.gitinfo, "run_git", broken)
    with pytest.raises(e2e.E2EError, match="git status falhou.*tempo esgotado"):
        e2e._git(tmp_path, "status")


def test_seed_makes_conversations_readable_by_the_sdk(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    home = Path(os.environ["MAESTRO_HOME"]).resolve()
    for project in e2e.SCENARIO:
        found = list_sessions(directory=str(home / "projetos" / project["slug"]))
        assert sorted(s.first_prompt for s in found) == sorted(
            c["prompt"] for c in project["conversations"]
        )


def test_seed_writes_the_phrase_conversation_with_turns_after_it(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    projects_dir = load_settings().claude_projects_dir.resolve()
    [session] = [
        path for path in projects_dir.glob("*/*.jsonl")
        if "tarefa automaticamente" in path.read_text(encoding="utf-8")
    ]
    lines = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    text = session.read_text(encoding="utf-8")
    # The phrase comes before the 20 filler turns, and the file is one linear chain.
    assert text.index("tarefa automaticamente") < text.index("Resposta de enchimento 1.")
    assert "Resposta de enchimento 20." in text
    uuids = {line["uuid"] for line in lines}
    assert all(line["parentUuid"] is None or line["parentUuid"] in uuids for line in lines)


def test_seed_writes_the_subagents_of_the_scenario_next_to_the_session(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))

    e2e.seed(tmp_path)

    projects_dir = load_settings().claude_projects_dir.resolve()
    [session] = [
        path for path in projects_dir.glob("*/*.jsonl")
        if "Investigue o módulo de pagamentos" in path.read_text(encoding="utf-8")
    ]
    transcript = history.read_transcript_file(session, with_subagents=True)
    # Transcript model, alias only in the meta file, no model at all.
    assert transcript.subagent_models == {
        "toolu_e2e_agent_1": "claude-sonnet-5-5",
        "toolu_e2e_agent_2": "haiku",
    }
    calls = [
        block
        for line in session.read_text(encoding="utf-8").splitlines()
        for block in (json.loads(line).get("message", {}).get("content") or [])
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    assert [c["name"] for c in calls] == ["Agent"] * 3
    assert [c["id"] for c in calls] == [f"toolu_e2e_agent_{n}" for n in (1, 2, 3)]
    # Everything the seed wrote is inside the temporary root.
    assert all(
        path.resolve().is_relative_to(tmp_path.resolve())
        for path in projects_dir.rglob("*")
    )


def test_seed_refuses_paths_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    apply_env(monkeypatch, e2e.isolated_env({}, root, 6620))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))

    with pytest.raises(e2e.E2EError, match="fora"):
        e2e.seed(root)

    assert not elsewhere.exists()
    assert not (root / "data").exists()


# build_app -----------------------------------------------------------------------


def test_refusing_factory_explains_itself(tmp_path):
    async def deny(tool_name, tool_input, context):
        raise AssertionError("not called")

    options = AgentOptions(cwd=tmp_path, session_id="s", resume=False, can_use_tool=deny)

    with pytest.raises(AgentError, match="servidor de E2E não inicia o agente real"):
        e2e.refuse_agent(options)


def test_app_uses_the_refusing_factory(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    e2e.seed(tmp_path)

    with TestClient(e2e.build_app(6620)) as client:
        assert client.app.state.sessions.agent_factory is e2e.refuse_agent
        assert client.app.state.agentd is None


def forbid_claude(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make every way to the SDK or to the `claude` binary record the attempt and raise."""
    attempts: list[str] = []

    def forbidden(name: str):
        def refuse(*args, **kwargs):
            attempts.append(name)
            raise AssertionError(f"o servidor de E2E tocou em {name}")

        return refuse

    for target in (
        "claudio_maestro.agent.sdk_client.sdk_agent_factory",
        "claudio_maestro.agent.sdk_client.ClaudeSDKClient",
        "claude_agent_sdk.ClaudeSDKClient",
        "claude_agent_sdk.query",
        "claudio_maestro.digest.model._sdk_query",
        "claudio_maestro.claudecli.run_version_command",
        "claudio_maestro.claudecli.run_update_command",
    ):
        monkeypatch.setattr(target, forbidden(target))

    def guard(name: str, original):
        def wrapper(args, *rest, **kwargs):
            argv = [args] if isinstance(args, (str, os.PathLike)) else list(args)
            if argv and os.path.basename(str(argv[0])) == "claude":
                attempts.append(name)
                raise AssertionError(f"o servidor de E2E executou o claude por {name}")
            return original(args, *rest, **kwargs)

        return wrapper

    # Git runs for real (the projects are plain folders); only the `claude` binary is off limits.
    monkeypatch.setattr(subprocess, "Popen", guard("subprocess.Popen", subprocess.Popen))
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec",
        guard("create_subprocess_exec", asyncio.create_subprocess_exec),
    )
    return attempts


def test_app_never_reaches_the_sdk_or_the_claude_binary(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    e2e.seed(tmp_path)
    attempts = forbid_claude(monkeypatch)
    # The suite stubs the history listing; the seeded conversations need the real one (it only
    # reads files).
    monkeypatch.setattr("claudio_maestro.history.sdk_list_sessions", list_sessions)
    for name, real in REAL_FILE_LOOKUPS.items():
        monkeypatch.setattr(f"claudio_maestro.history.{name}", real)

    app = e2e.build_app(6620)
    with TestClient(
        app,
        base_url="http://127.0.0.1:6620",
        headers={"origin": "http://localhost:6620", "x-maestro": "1"},
    ) as client:
        time.sleep(0.5)  # long enough for any startup task to have opened a client
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/projects").status_code == 200
        for _ in range(50):  # the first history sync runs in the background
            found = client.get("/api/sessions").json()
            if found:
                break
            time.sleep(0.1)
        assert found, "as conversas semeadas não apareceram"
        session_id = found[0]["session_id"]

        client.post(f"/api/sessions/{session_id}/digest")
        client.post("/api/digest/run")
        client.post(f"/api/sessions/{session_id}/messages", json={"text": "oi"})
        client.get("/api/projects/1/commands")
        client.get(f"/api/sessions/{session_id}/commands")
        client.get("/api/models")
        client.get("/api/updates")
        client.get("/api/usage")
        cli = client.get("/api/claude-cli")
        update = client.post("/api/claude-cli/update")
        time.sleep(1.0)  # the digest worker and the other background tasks get their turn

        assert cli.status_code == 200
        assert cli.json()["system"] is None
        assert cli.json()["can_update"] is False
        assert update.status_code == 409
        assert client.get("/api/health").status_code == 200

    assert attempts == []


def test_agents_live_in_the_temporary_root_and_run_without_the_real_agent(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    e2e.seed(tmp_path)
    attempts = forbid_claude(monkeypatch)

    with TestClient(
        e2e.build_app(6620),
        base_url="http://127.0.0.1:6620",
        headers={"origin": "http://localhost:6620", "x-maestro": "1"},
    ) as client:
        project_id = client.get("/api/projects").json()[0]["id"]
        created = client.post(
            "/api/agents", json={"name": "Teste", "slug": "teste", "project_id": project_id}
        )
        assert created.status_code == 201
        woke = client.post(f"/api/agents/{created.json()['id']}/wake", json={})
        assert woke.status_code == 202
        folder = client.app.state.agent_files.root

    assert folder == tmp_path / "data" / "agents"
    assert (folder / "teste" / "AGENT.md").is_file()
    assert attempts == []


def test_digest_model_refuses_with_a_clear_message():
    request = DigestRequest(system_prompt="s", prompt="p", model="haiku", effort="low")

    with pytest.raises(DigestModelError, match="agente de resumos") as raised:
        asyncio.run(e2e.RefusingDigestModel().summarize(request))
    assert raised.value.stop_pass is True


def test_claude_resolver_runs_nothing_from_the_system(monkeypatch):
    attempts = forbid_claude(monkeypatch)
    resolver = e2e.inert_claude_resolver()

    state = asyncio.run(resolver.refresh(force=True))
    assert state.system_path is None
    assert state.source == "bundled"
    with pytest.raises(ClaudeCliUnavailable):
        asyncio.run(resolver.update(lambda: asyncio.sleep(0, result=False)))
    outcome = asyncio.run(e2e.refuse_claude_update(["claude", "update"], 1.0))
    assert outcome.returncode is None
    assert "E2E" in outcome.output
    assert attempts == []


def test_serve_returns_cleanly_when_a_signal_arrives_while_building(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    # `serve` swaps this global; the line makes monkeypatch restore it afterwards.
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", gitinfo.FETCH_ALLOWED_PROTOCOLS)

    def interrupted(port):
        raise KeyboardInterrupt

    monkeypatch.setattr(e2e, "build_app", interrupted)
    monkeypatch.setattr(e2e.cli, "port_available", lambda port: True)

    e2e.serve(6620)  # returns instead of raising


def test_serve_limits_git_remotes_to_local_folders(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({}, tmp_path, 6620))
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", gitinfo.FETCH_ALLOWED_PROTOCOLS)  # restored after
    seen = []

    def interrupted(port):
        seen.append(gitinfo.FETCH_ALLOWED_PROTOCOLS)
        raise KeyboardInterrupt

    monkeypatch.setattr(e2e, "build_app", interrupted)
    monkeypatch.setattr(e2e.cli, "port_available", lambda port: True)
    e2e.serve(6620)
    assert seen == [("file",)]


def test_sigterm_becomes_keyboard_interrupt():
    # uvicorn shuts down and then re-raises the signal with the handler it found, so SIGTERM
    # must unwind the stack (and remove the temporary folder) instead of killing the process.
    previous = signal.getsignal(signal.SIGTERM)
    try:
        e2e.stop_on_sigterm()
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, previous)


# check_same_checkout -----------------------------------------------------------


def test_same_checkout_refuses_a_different_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(e2e.cli, "REPO_ROOT", tmp_path)

    with pytest.raises(e2e.E2EError, match="checkout diferente"):
        e2e.check_same_checkout()


def test_same_checkout_accepts_the_script_repo_root(monkeypatch):
    monkeypatch.setattr(e2e.cli, "REPO_ROOT", SCRIPT.parents[1])

    e2e.check_same_checkout()


def test_same_checkout_compares_resolved_paths(tmp_path, monkeypatch):
    link = tmp_path / "link"
    link.symlink_to(SCRIPT.parents[1])
    monkeypatch.setattr(e2e.cli, "REPO_ROOT", link)

    e2e.check_same_checkout()


# main ----------------------------------------------------------------------------


def test_main_refuses_a_different_checkout_before_building(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(e2e.cli, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        e2e.cli, "needs_build", lambda frontend: pytest.fail("compilou o frontend")
    )

    assert e2e.main() == 1
    assert "checkout diferente" in capsys.readouterr().err


def test_main_handles_sigterm_before_seeding(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(e2e, "check_same_checkout", lambda: None)
    monkeypatch.setattr(e2e.cli, "needs_build", lambda frontend: False)
    monkeypatch.setattr(e2e, "stop_on_sigterm", lambda: calls.append("sigterm"))
    monkeypatch.setattr(e2e, "seed", lambda root: calls.append("seed"))
    monkeypatch.setattr(e2e, "serve", lambda port: calls.append("serve"))
    monkeypatch.setattr(os, "environ", dict(os.environ))

    assert e2e.main() == 0
    assert calls == ["sigterm", "seed", "serve"]


def test_main_cleans_the_temporary_folder_when_interrupted_while_seeding(
    tmp_path, monkeypatch
):
    root = tmp_path / "maestro-e2e-fake"
    root.mkdir()
    monkeypatch.setattr(e2e, "check_same_checkout", lambda: None)
    monkeypatch.setattr(e2e.cli, "needs_build", lambda frontend: False)
    monkeypatch.setattr(e2e.tempfile, "mkdtemp", lambda prefix: str(root))
    monkeypatch.setattr(e2e, "stop_on_sigterm", lambda: None)
    monkeypatch.setattr(e2e, "serve", lambda port: pytest.fail("serviu depois de interrompido"))
    monkeypatch.setattr(os, "environ", dict(os.environ))

    def interrupted(path):
        raise KeyboardInterrupt

    monkeypatch.setattr(e2e, "seed", interrupted)

    assert e2e.main() == 1
    assert not root.exists()


def test_chat_e2e_uses_only_the_opt_in_fake_client(tmp_path, monkeypatch):
    env = e2e.isolated_env({'MAESTRO_E2E_CHAT': '1'}, tmp_path, 6620)
    assert env['MAESTRO_E2E_CHAT'] == '1'
    apply_env(monkeypatch, env)
    e2e.seed(tmp_path)
    attempts = forbid_claude(monkeypatch)
    with TestClient(e2e.build_app(6620), base_url="http://127.0.0.1:6620",
                    headers={"x-maestro": "1", "origin": "http://localhost:6620"}) as client:
        assert client.app.state.sessions.agent_factory.__name__ == "chat_agent"
        assert client.app.state.agentd is None
        project_id = client.get("/api/projects").json()[0]["id"]
        assert client.get(f"/api/projects/{project_id}/commands").status_code == 200
    assert attempts == []


def test_e2e_drops_github_credentials_and_never_selects_real_gh(tmp_path, monkeypatch):
    from claudio_maestro import app as app_module
    env = e2e.isolated_env({'MAESTRO_E2E_CHAT': '1', 'GH_TOKEN': 'sentinel', 'GITHUB_TOKEN': 'sentinel',
                            'GH_CONFIG_DIR': '/host-gh-config', 'GITHUB_API_URL': 'https://external.invalid'}, tmp_path, 6620)
    assert not any(k.startswith(('GH_', 'GITHUB_')) for k in env)
    apply_env(monkeypatch, env)
    e2e.seed(tmp_path)
    async def external(*args):
        pytest.fail('o transporte GitHub real nunca deve ser selecionado pelo E2E')
    monkeypatch.setattr(app_module, 'default_run_gh', external)
    with TestClient(e2e.build_app(6620), base_url='http://127.0.0.1:6620') as client:
        assert client.app.state.ci._run_gh is e2e.refuse_gh
        assert client.portal.call(client.app.state.ci._run_gh, ['api', 'anything']) == (127, '')


def test_chat_e2e_has_no_old_work_scenario(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({'MAESTRO_E2E_CHAT': '1'}, tmp_path, 6620))
    e2e.seed(tmp_path)
    attempts = forbid_claude(monkeypatch)
    with TestClient(e2e.build_app(6620), base_url='http://127.0.0.1:6620',
                    headers={'x-maestro': '1', 'origin': 'http://localhost:6620'}) as client:
        names = [p['name'] for p in client.get('/api/projects').json()]
        assert 'Trabalho Demo' not in names and 'Coleta Demo' not in names
        assert not hasattr(client.app.state, 'work')
        assert client.app.state.tasks is not None
        assert client.get('/api/tasks').status_code == 200
    assert attempts == []


def test_seeded_organization_is_served_by_the_api(tmp_path, monkeypatch):
    apply_env(monkeypatch, e2e.isolated_env({'MAESTRO_E2E_CHAT': '1'}, tmp_path, 6620))
    e2e.seed(tmp_path)
    attempts = forbid_claude(monkeypatch)
    with TestClient(e2e.build_app(6620), base_url='http://127.0.0.1:6620',
                    headers={'x-maestro': '1', 'origin': 'http://localhost:6620'}) as client:
        agents = client.get('/api/agents').json()
        tasks = client.get('/api/tasks', params={'limit': 100}).json()
        pending = client.get('/api/decisions').json()
        detail = client.get(f"/api/tasks/{next(t['id'] for t in tasks if t['title'] == e2e.TASK_TITLES['urgent'])}").json()
    assert [a['name'] for a in agents] == ['Maestro', 'Triagem', 'Revisor']
    assert all(a['definition_error'] is None for a in agents)
    assert sorted(t['title'] for t in tasks) == sorted(e2e.TASK_TITLES.values())
    assert [d['question'] for d in pending] == [e2e.DECISION_QUESTION]
    assert [c['text'] for c in detail['comments']] == list(e2e.URGENT_COMMENTS.values())
    assert len(detail['runs']) == 1 and len(detail['decisions']) == 1
    assert attempts == []
