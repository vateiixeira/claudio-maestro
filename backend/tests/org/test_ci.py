"""CI receipts: the backend reads the GitHub Actions run with `gh` (faked here) and proves the
folder of the agent's session is at the run's commit, clean, with the same `origin`. Real git
in `tmp_path`; the `gh` runner is a fake that records its arguments."""

import json
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from git_helpers import (  # noqa: F401
    commit_file,
    git,
    git_home,
    make_repo,
    set_identity,
)

from claudio_maestro import db
from claudio_maestro.org import store
from claudio_maestro.org.ci import CiService
from claudio_maestro.sessions import SessionNotFoundError, SessionRecord

pytestmark = pytest.mark.anyio

NOW = 1_700_000_000
URL = "https://github.com/acme/app/actions/runs/73"
SESSION = "agent-session"


class FakeSessions:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}

    def find_record(self, session_id: str) -> SessionRecord:
        if session_id not in self.records:
            raise SessionNotFoundError("Sessão não encontrada.")
        return self.records[session_id]


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.repo = make_repo(tmp_path / "proj").resolve()
        set_identity(self.repo)
        git(self.repo, "remote", "add", "origin", "git@github.com:acme/app.git")
        self.sha = git(self.repo, "rev-parse", "HEAD").strip()
        self.db_path = tmp_path / "maestro.db"
        db.init_db(self.db_path)
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (1, 'p', ?, '#fff', 0, 0)",
                (str(self.repo),),
            )
            self.agent = store.create_agent(
                conn, slug="dev", name="Dev", project_id=1, reports_to=None, now=1
            ).id
        self.sessions = FakeSessions()
        self.add_session(SESSION, agent_id=self.agent)
        self.add_session("plain-session", agent_id=None)
        self.run: dict[str, Any] = {
            "id": 73, "run_attempt": 2, "status": "completed", "conclusion": "success",
            "head_sha": self.sha, "html_url": URL, "name": "CI",
            "repository": {"full_name": "acme/app"},
        }
        self.jobs: dict[str, Any] = {
            "total_count": 2,
            "jobs": [
                {"id": 91, "run_id": 73, "head_sha": self.sha, "status": "completed",
                 "conclusion": "success", "name": "pytest"},
                {"id": 92, "run_id": 73, "head_sha": self.sha, "status": "completed",
                 "conclusion": "skipped", "name": "deploy"},
            ],
        }
        self.calls: list[list[str]] = []
        self.gh_code = 0
        self.on_call: Any = None
        self.ci = CiService(
            self.db_path, run_gh=self._gh, sessions=self.sessions,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )

    def add_session(self, session_id: str, *, agent_id: int | None, cwd: Path | None = None) -> None:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            conn.execute(
                "INSERT INTO sessions (session_id, project_id, cwd, title, created_at,"
                " last_activity_at) VALUES (?, 1, ?, 't', 0, 0)",
                (session_id, str(cwd or self.repo)),
            )
        self.sessions.records[session_id] = SessionRecord(
            session_id=session_id, project_id=1, cwd=str(cwd or self.repo), title="t",
            created_at=0, last_activity_at=0, agent_id=agent_id,
        )

    async def _gh(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        if self.on_call is not None:
            self.on_call(len(self.calls))
        if self.gh_code:
            return self.gh_code, ""
        return 0, json.dumps(self.jobs if "/jobs?" in args[-1] else self.run)

    def start_run(self, *, task_id: int | None, outcome: str = "running") -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            return store.insert_run(
                conn, agent_id=self.agent, source="assignment", started_at=NOW,
                outcome=outcome, session_id=SESSION, task_id=task_id,
            ).id

    def task(self) -> int:
        with closing(db.connect(self.db_path)) as conn, db.transaction(conn):
            return store.create_task(conn, project_id=1, title="T", now=NOW).id

    def receipts(self) -> list[Any]:
        with closing(db.connect(self.db_path)) as conn:
            return [
                dict(row) for row in conn.execute("SELECT * FROM ci_receipts ORDER BY id")
            ]


@pytest.fixture
def world(tmp_path: Path, git_home) -> World:  # noqa: F811
    return World(tmp_path)


async def test_verify_records_receipt_with_jobs(world: World):
    task_id = world.task()
    run_id = world.start_run(task_id=task_id)

    result = await world.ci.verify(SESSION, run_url=URL)

    assert result["conclusion"] == "success"
    assert result["head_sha"] == world.sha
    assert result["jobs"] == [
        {"name": "pytest", "conclusion": "success"},
        {"name": "deploy", "conclusion": "skipped"},
    ]
    assert result["receipt"].startswith("ci-")
    (row,) = world.receipts()
    assert row["receipt"] == result["receipt"]
    assert (row["project_id"], row["task_id"], row["agent_id"], row["run_id"]) == (
        1, task_id, world.agent, run_id,
    )
    assert (row["run_url"], row["repository"], row["head_sha"], row["conclusion"]) == (
        URL, "acme/app", world.sha, "success",
    )
    assert json.loads(row["jobs"]) == result["jobs"]
    assert row["created_at"] == NOW
    with closing(db.connect(world.db_path)) as conn:
        assert store.list_ci_receipts(conn, task_id)[0].receipt == result["receipt"]


async def test_gh_is_called_with_fixed_endpoints(world: World):
    await world.ci.verify(SESSION, run_url=URL)

    head = ["api", "--hostname", "github.com", "--method", "GET"]
    assert world.calls[0] == [*head, "repos/acme/app/actions/runs/73"]
    assert world.calls[1] == [*head, "repos/acme/app/actions/runs/73/attempts/2/jobs?per_page=100&page=1"]
    assert all(call[:5] == head for call in world.calls)


async def test_verify_without_active_run_has_no_task(world: World):
    world.start_run(task_id=world.task(), outcome="concluded")  # ended: not the current work

    await world.ci.verify(SESSION, run_url=URL)

    (row,) = world.receipts()
    assert row["task_id"] is None and row["run_id"] is None and row["agent_id"] == world.agent


async def test_verify_with_active_run_without_task(world: World):
    run_id = world.start_run(task_id=None)

    await world.ci.verify(SESSION, run_url=URL)

    (row,) = world.receipts()
    assert row["task_id"] is None and row["run_id"] == run_id


async def test_verify_rejects_other_repository(world: World):
    git(world.repo, "remote", "set-url", "origin", "git@github.com:acme/other.git")

    with pytest.raises(store.OrgError, match="origin"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.calls and not world.receipts()


@pytest.mark.parametrize(
    "remote",
    ["https://github.com/Acme/App.git", "ssh://git@github.com/acme/app", "https://github.com/acme/app/"],
)
async def test_verify_accepts_github_remote_spellings(world: World, remote: str):
    git(world.repo, "remote", "set-url", "origin", remote)

    await world.ci.verify(SESSION, run_url=URL)

    assert len(world.receipts()) == 1


@pytest.mark.parametrize("remote", ["https://evil.test/acme/app.git", "/tmp/acme/app", "git@gitlab.com:acme/app.git"])
async def test_verify_rejects_non_github_remote(world: World, remote: str):
    git(world.repo, "remote", "set-url", "origin", remote)

    with pytest.raises(store.OrgError):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.calls


async def test_verify_rejects_missing_origin(world: World):
    git(world.repo, "remote", "remove", "origin")

    with pytest.raises(store.OrgError, match="origin"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.calls


async def test_verify_rejects_head_mismatch(world: World):
    world.run["head_sha"] = "c" * 40
    world.jobs["jobs"][0]["head_sha"] = "c" * 40

    with pytest.raises(store.OrgError, match="HEAD"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_verify_rejects_dirty_tree(world: World):
    (world.repo / "new.py").write_text("x = 1\n")

    with pytest.raises(store.OrgError, match="alterações"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.calls and not world.receipts()


async def test_verify_rejects_modified_tracked_file(world: World):
    commit_file(world.repo, "a.py", "a = 1\n")
    world.sha = git(world.repo, "rev-parse", "HEAD").strip()
    (world.repo / "a.py").write_text("a = 2\n")

    with pytest.raises(store.OrgError, match="alterações"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.calls


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.test/acme/app/actions/runs/73",
        URL + "?x=1",
        URL + "#x",
        "https://github.com/acme/app/actions/runs/73/../../secrets",
        "https://user@github.com/acme/app/actions/runs/73",
        "https://github.com/acme/app/actions/runs/0",
        "https://github.com/acme/app/actions/runs/abc",
        "http://github.com/acme/app/actions/runs/73",
        "https://github.com/acme/app/pull/3",
        "--hostname=evil.test",
        "",
    ],
)
async def test_untrusted_url_never_reaches_gh(world: World, url: str):
    with pytest.raises(store.OrgError, match="URL"):
        await world.ci.verify(SESSION, run_url=url)

    assert not world.calls and not world.receipts()


async def test_non_string_url_is_refused(world: World):
    with pytest.raises(store.OrgError, match="URL"):
        await world.ci.verify(SESSION, run_url=73)  # type: ignore[arg-type]


async def test_url_of_other_repository_than_origin_is_refused(world: World):
    with pytest.raises(store.OrgError, match="origin"):
        await world.ci.verify(SESSION, run_url="https://github.com/acme/other/actions/runs/73")

    assert not world.calls


async def test_only_agent_sessions_can_verify(world: World):
    with pytest.raises(store.OrgError, match="agente"):
        await world.ci.verify("plain-session", run_url=URL)
    with pytest.raises(store.OrgError, match="Sessão"):
        await world.ci.verify("unknown", run_url=URL)

    assert not world.calls


async def test_session_folder_outside_project_is_refused(world: World):
    foreign = make_repo(world.tmp_path / "foreign").resolve()
    git(foreign, "remote", "add", "origin", "git@github.com:acme/app.git")
    world.add_session("foreign-session", agent_id=world.agent, cwd=foreign)

    with pytest.raises(store.OrgError, match="projeto"):
        await world.ci.verify("foreign-session", run_url=URL)

    assert not world.calls


async def test_symlink_out_of_project_is_refused(world: World):
    foreign = make_repo(world.tmp_path / "foreign").resolve()
    git(foreign, "remote", "add", "origin", "git@github.com:acme/app.git")
    link = world.repo / "link"
    link.symlink_to(foreign)
    world.add_session("link-session", agent_id=world.agent, cwd=link)

    with pytest.raises(store.OrgError, match="projeto"):
        await world.ci.verify("link-session", run_url=URL)

    assert not world.calls


async def test_proven_worktree_outside_project_is_accepted(world: World):
    outside = world.tmp_path / "elsewhere"
    git(world.repo, "worktree", "add", "-q", "-b", "tarefa/1", str(outside))
    world.add_session("wt-session", agent_id=world.agent, cwd=outside)

    await world.ci.verify("wt-session", run_url=URL)

    assert len(world.receipts()) == 1


async def test_worktree_pointing_elsewhere_is_refused(world: World):
    other = make_repo(world.tmp_path / "other-repo").resolve()
    git(other, "worktree", "add", "-q", "-b", "x", str(world.tmp_path / "stray"))
    world.add_session("stray-session", agent_id=world.agent, cwd=world.tmp_path / "stray")

    with pytest.raises(store.OrgError, match="projeto"):
        await world.ci.verify("stray-session", run_url=URL)

    assert not world.calls


async def test_folder_that_is_not_a_repository_is_refused(world: World):
    with closing(db.connect(world.db_path)) as conn, db.transaction(conn):
        bare = world.tmp_path / "norepo"
        bare.mkdir()
        conn.execute("UPDATE projects SET path = ? WHERE id = 1", (str(bare),))
    world.add_session("norepo-session", agent_id=world.agent, cwd=bare)

    with pytest.raises(store.OrgError, match="repositório"):
        await world.ci.verify("norepo-session", run_url=URL)

    assert not world.calls


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("status", "in_progress", "terminou"),
        ("status", "queued", "terminou"),
        ("id", 74, "não confere"),
        ("repository", {"full_name": "acme/other"}, "não confere"),
        ("html_url", "https://github.com/acme/other/actions/runs/73", "não confere"),
        ("conclusion", None, "inválid"),
        ("conclusion", "success; rm -rf", "inválid"),
        ("run_attempt", 0, "inválid"),
        ("run_attempt", "2", "inválid"),
    ],
)
async def test_wrong_run_never_issues_receipt(world: World, key: str, value: Any, match: str):
    world.run[key] = value

    with pytest.raises(store.OrgError, match=match):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_failed_run_is_recorded_as_failure(world: World):
    world.run["conclusion"] = "failure"
    world.jobs["jobs"][0]["conclusion"] = "failure"

    result = await world.ci.verify(SESSION, run_url=URL)

    assert result["conclusion"] == "failure"
    assert world.receipts()[0]["conclusion"] == "failure"
    assert result["jobs"][0] == {"name": "pytest", "conclusion": "failure"}


@pytest.mark.parametrize(
    "problem", ["truncated", "more_than_listed", "running", "wrong_sha", "wrong_run", "none", "not_list", "no_name"]
)
async def test_jobs_must_be_complete_and_match_the_run(world: World, problem: str):
    jobs = world.jobs["jobs"]
    if problem == "truncated":
        world.jobs["total_count"] = 101
    elif problem == "more_than_listed":
        world.jobs["total_count"] = 3
    elif problem == "running":
        jobs[0]["status"] = "in_progress"
    elif problem == "wrong_sha":
        jobs[0]["head_sha"] = "c" * 40
    elif problem == "wrong_run":
        jobs[0]["run_id"] = 99
    elif problem == "none":
        world.jobs = {"total_count": 0, "jobs": []}
    elif problem == "not_list":
        world.jobs = {"total_count": 1, "jobs": "x"}
    else:
        jobs[0]["name"] = ""

    with pytest.raises(store.OrgError):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_gh_failure_has_a_clear_message(world: World):
    world.gh_code = 1

    with pytest.raises(store.OrgError, match="GitHub"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_gh_garbage_is_refused(world: World):
    async def garbage(args: list[str]) -> tuple[int, str]:
        return 0, "not json"

    world.ci._run_gh = garbage  # type: ignore[attr-defined]

    with pytest.raises(store.OrgError, match="inválid"):
        await world.ci.verify(SESSION, run_url=URL)


async def test_oversized_gh_response_is_refused(world: World):
    async def huge(args: list[str]) -> tuple[int, str]:
        return 0, " " * 300_000

    world.ci._run_gh = huge  # type: ignore[attr-defined]

    with pytest.raises(store.OrgError, match="limite"):
        await world.ci.verify(SESSION, run_url=URL)


async def test_run_changing_during_verification_is_refused(world: World):
    def change(count: int) -> None:
        if count == 2:
            world.run["run_attempt"] = 3

    world.on_call = change

    with pytest.raises(store.OrgError, match="mudou"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_head_moving_during_verification_is_refused(world: World):
    def move(count: int) -> None:
        if count == 1:
            commit_file(world.repo, "later.py")

    world.on_call = move

    with pytest.raises(store.OrgError, match="mudou"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_tree_getting_dirty_during_verification_is_refused(world: World):
    def dirty(count: int) -> None:
        if count == 3:
            (world.repo / "late.py").write_text("x\n")

    world.on_call = dirty

    with pytest.raises(store.OrgError, match="mudou"):
        await world.ci.verify(SESSION, run_url=URL)

    assert not world.receipts()


async def test_each_verification_gets_its_own_receipt(world: World):
    first = await world.ci.verify(SESSION, run_url=URL)
    second = await world.ci.verify(SESSION, run_url=URL)

    assert first["receipt"] != second["receipt"]
    assert len(world.receipts()) == 2
