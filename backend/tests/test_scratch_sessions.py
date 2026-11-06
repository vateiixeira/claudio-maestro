"""Sessions of the built-in "Sem projeto" project: own folder, recreated on resume, prompt."""

import os
import re
import stat
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_sessions import fake_history, make_project

from claudio_maestro import db, projects, scratch
from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app
from claudio_maestro.org import store
from claudio_maestro.sessions import InvalidDecisionError, SessionExtras, SessionManager

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"
FOLDER_NAME = re.compile(r"^scratch-\d{4}-\d{2}-\d{2}-[0-9a-f]{6}$")


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path / "data"
        self.db_path = self.data_dir / "maestro.db"
        db.init_db(self.db_path)
        with closing(db.connect(self.db_path)) as conn, conn:
            self.scratch_project = projects.ensure_scratch_project(conn, self.data_dir)
        self.root = projects.scratch_root(self.data_dir)
        self.regular = make_project(self.db_path, tmp_path / "home" / "app")
        self.factory = FakeAgentFactory(script=lambda content: text_turn("x", "oi"))
        self.manager = SessionManager(
            self.db_path,
            lambda event: None,
            agent_factory=self.factory,
            history_exists=fake_history(self.factory),
            scratch_root=self.root,
        )


@pytest.fixture
def env(tmp_path: Path):
    return Env(tmp_path)


@pytest.fixture
async def env_cleanup():
    """Shut down the managers a test registers, so no task outlives it."""
    managers: list[SessionManager] = []
    yield managers
    for manager in managers:
        await manager.shutdown()


def test_new_scratch_session_gets_own_folder(tmp_path: Path):
    app = create_app(agent_factory=FakeAgentFactory())
    headers = {"origin": APP_ORIGIN, "x-maestro": "1"}
    with TestClient(app, base_url=BACKEND_URL, headers=headers) as api:
        scratch_id = next(p["id"] for p in api.get("/api/projects").json() if p["kind"] == "scratch")
        ids = []
        for _ in range(2):
            response = api.post(f"/api/projects/{scratch_id}/sessions")
            assert response.status_code == 201
            ids.append(response.json()["session_id"])
    with closing(db.connect(tmp_path / "data" / "maestro.db")) as conn:
        cwds = [
            conn.execute("SELECT cwd FROM sessions WHERE session_id = ?", (sid,)).fetchone()["cwd"]
            for sid in ids
        ]
    assert cwds[0] != cwds[1]
    root = (tmp_path / "data" / "scratch").resolve()
    for cwd in cwds:
        folder = Path(cwd)
        assert folder.parent == root
        assert FOLDER_NAME.match(folder.name)
        assert folder.is_dir()
        assert mode_of(folder) == 0o700


@pytest.mark.anyio
async def test_scratch_session_rejects_client_cwd(env: Env, env_cleanup):
    env_cleanup.append(env.manager)
    with pytest.raises(InvalidDecisionError):
        env.manager.create_session(env.scratch_project, cwd=env.regular.path)


def test_new_folder_retries_on_collision(tmp_path: Path):
    root = tmp_path / "scratch"
    root.mkdir()
    tokens = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
    first = scratch.new_folder(root, token=lambda: next(tokens))
    second = scratch.new_folder(root, token=lambda: next(tokens))
    assert first.name.endswith("-aaaaaa")
    assert second.name.endswith("-bbbbbb")
    with pytest.raises(RuntimeError):
        scratch.new_folder(root, token=lambda: "aaaaaa")


@pytest.mark.anyio
async def test_scratch_session_gets_prompt_append(env: Env, env_cleanup):
    env_cleanup.append(env.manager)
    scratch_session = env.manager.get(env.manager.create_session(env.scratch_project).session_id)
    await scratch_session.send("oi")
    assert env.factory.clients[-1].options.system_prompt_append == scratch.SCRATCH_PROMPT

    regular_session = env.manager.get(env.manager.create_session(env.regular).session_id)
    await regular_session.send("oi")
    assert env.factory.clients[-1].options.system_prompt_append is None


@pytest.mark.anyio
async def test_resume_recreates_missing_folder(env: Env, env_cleanup):
    env_cleanup.append(env.manager)
    record = env.manager.create_session(env.scratch_project)
    folder = Path(record.cwd)
    assert folder.is_dir()
    folder.rmdir()

    await env.manager.get(record.session_id).send("oi")

    assert folder.is_dir()
    assert list(folder.iterdir()) == []
    assert mode_of(folder) == 0o700
    assert env.factory.clients[-1].options.cwd == folder


def test_ensure_folder_never_creates_outside_root(tmp_path: Path):
    root = tmp_path / "scratch"
    root.mkdir()
    outside = tmp_path / "fora" / "x"
    scratch.ensure_folder(str(outside), root)
    assert not outside.exists()
    assert not outside.parent.exists()

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, root / "link")
    scratch.ensure_folder(str(root / "link" / "x"), root)
    assert not (elsewhere / "x").exists()


def test_ensure_folder_recreates_direct_child(tmp_path: Path):
    root = tmp_path / "scratch"
    root.mkdir()
    child = root / "scratch-2026-11-06-abcdef"
    scratch.ensure_folder(str(child), root)
    assert child.is_dir()
    assert mode_of(child) == 0o700


def test_is_scratch_cwd(tmp_path: Path):
    root = tmp_path / "scratch"
    root.mkdir()
    assert scratch.is_scratch_cwd(str(root / "scratch-x"), root)
    assert not scratch.is_scratch_cwd(str(tmp_path / "other"), root)


@pytest.mark.anyio
async def test_agent_session_keeps_the_extras_prompt(tmp_path: Path, env_cleanup):
    """An agent session takes the prompt of its definition, never the scratch one."""
    env = Env(tmp_path)

    def setup(record) -> SessionExtras:
        async def decide(tool_name, tool_input):
            return "allow"

        return SessionExtras(
            system_prompt_append="Você é o revisor.",
            add_dirs=[],
            env={},
            mcp_servers={},
            decide=decide,
        )

    env.manager = SessionManager(
        env.db_path,
        lambda event: None,
        agent_factory=env.factory,
        history_exists=fake_history(env.factory),
        scratch_root=env.root,
        session_setup=setup,
    )
    env_cleanup.append(env.manager)
    with closing(db.connect(env.db_path)) as conn, db.transaction(conn):
        agent_id = store.create_agent(
            conn, slug="revisor", name="Revisor", project_id=env.regular.id,
            reports_to=None, now=1,
        ).id
    record = env.manager.create_session(env.regular, agent_id=agent_id)

    await env.manager.get(record.session_id).send("oi")

    assert env.factory.clients[-1].options.system_prompt_append == "Você é o revisor."
