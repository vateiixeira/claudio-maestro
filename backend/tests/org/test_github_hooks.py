"""Webhook receiver for PR comments: signature, filters, queueing and the listener."""

import asyncio
import hashlib
import hmac
import json
import socket
import stat
import time
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from claudio_maestro import db
from claudio_maestro.org import github_hooks, store

SECRET = "s3cret"
PR_URL = "https://github.com/acme/repo/pull/7"
OWNER = "vini"


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.db_path = tmp_path / "maestro.db"
        self.data_dir = tmp_path / "data"
        db.init_db(self.db_path)
        with closing(db.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO projects (id, name, path, color, position, created_at)"
                " VALUES (1, 'p', '/tmp/p', '#fff', 0, 0)"
            )
            self.agent_id = store.create_agent(
                conn, slug="revisor", name="Revisor", project_id=1, reports_to=None, now=1
            ).id
            github_hooks.set_owner(conn, OWNER)
        self.agent_prs = {PR_URL: self.agent_id}
        self.queued_calls = 0
        github_hooks.write_secret(self.data_dir, SECRET)
        self.client = TestClient(
            github_hooks.build_hooks_app(
                db_path=self.db_path,
                data_dir=self.data_dir,
                is_agent_pr=self.agent_prs.get,
                on_queued=self._queued,
            )
        )

    def _queued(self) -> None:
        self.queued_calls += 1

    def post(self, event: str, payload: dict, *, secret: str | None = SECRET, signature=None):
        body = json.dumps(payload).encode()
        return self.post_raw(event, body, secret=secret, signature=signature)

    def post_raw(self, event: str, body: bytes, *, secret: str | None = SECRET, signature=None):
        headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        elif secret is not None:
            headers["X-Hub-Signature-256"] = sign(secret, body)
        return self.client.post("/github", content=body, headers=headers)

    def queue(self) -> list[store.PrComment]:
        with closing(db.connect(self.db_path)) as conn:
            return store.queued_comments(conn)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def issue_comment(login: str = OWNER, *, on_pr: bool = True, action: str = "created") -> dict:
    issue: dict = {"html_url": PR_URL}
    if on_pr:
        issue["pull_request"] = {"html_url": PR_URL}
    else:
        issue["html_url"] = "https://github.com/acme/repo/issues/7"
    return {
        "action": action,
        "issue": issue,
        "comment": {
            "id": 101,
            "body": "Troque o nome",
            "user": {"login": login},
            "html_url": PR_URL + "#issuecomment-101",
            "created_at": "2026-10-23T12:00:00Z",
        },
    }


def line_comment(login: str = OWNER) -> dict:
    return {
        "action": "created",
        "pull_request": {"html_url": PR_URL},
        "comment": {
            "id": 202,
            "body": "Aqui",
            "user": {"login": login},
            "html_url": PR_URL + "#discussion_r202",
            "created_at": "2026-10-23T12:01:00Z",
            "path": "src/a.py",
            "line": 12,
        },
    }


def review(body: str | None = "Está bom, ajuste isto", login: str = OWNER) -> dict:
    return {
        "action": "submitted",
        "pull_request": {"html_url": PR_URL},
        "review": {
            "id": 303,
            "body": body,
            "user": {"login": login},
            "html_url": PR_URL + "#pullrequestreview-303",
            "submitted_at": "2026-10-23T12:02:00Z",
        },
    }


def test_rejects_bad_signature(env: Env):
    assert env.post("issue_comment", issue_comment(), secret="wrong").status_code == 401
    assert env.post("issue_comment", issue_comment(), signature="sha256=zz").status_code == 401
    assert env.post("issue_comment", issue_comment(), signature="nope").status_code == 401
    assert env.post_raw("issue_comment", b"{}", secret=None).status_code == 401
    assert env.queue() == []


def test_bad_signature_never_parses_the_body(env: Env):
    response = env.post_raw("issue_comment", b"not json", secret="wrong")
    assert response.status_code == 401


def test_rejects_missing_secret(env: Env):
    (env.data_dir / github_hooks.SECRET_FILE).unlink()
    assert env.post("issue_comment", issue_comment()).status_code == 503
    assert env.queue() == []


def test_rejects_oversized_body(env: Env):
    body = b"x" * (1024 * 1024 + 1)
    assert env.post_raw("issue_comment", body).status_code == 413


def test_signed_invalid_json_is_400(env: Env):
    assert env.post_raw("issue_comment", b"not json").status_code == 400


def test_ignores_other_author(env: Env):
    assert env.post("issue_comment", issue_comment("stranger")).status_code == 202
    assert env.queue() == []
    assert env.queued_calls == 0


def test_author_match_ignores_case(env: Env):
    assert env.post("issue_comment", issue_comment(OWNER.upper())).status_code == 202
    assert len(env.queue()) == 1


def test_ignores_everything_without_owner(env: Env):
    with closing(db.connect(env.db_path)) as conn:
        conn.execute("DELETE FROM app_state WHERE key = ?", (github_hooks.OWNER_KEY,))
    assert env.post("issue_comment", issue_comment()).status_code == 202
    assert env.queue() == []


def test_ignores_unknown_pr(env: Env):
    env.agent_prs.clear()
    assert env.post("issue_comment", issue_comment()).status_code == 202
    assert env.queue() == []
    assert env.queued_calls == 0


def test_ignores_unlisted_events_and_actions(env: Env):
    assert env.post("ping", {"zen": "x"}).status_code == 202
    assert env.post("push", issue_comment()).status_code == 202
    assert env.post("issue_comment", issue_comment(action="edited")).status_code == 202
    assert env.queue() == []


def test_issue_comment_on_pr_queued(env: Env):
    response = env.post("issue_comment", issue_comment())
    assert response.status_code == 202
    [comment] = env.queue()
    assert comment.comment_id == "issue:101"
    assert comment.pr_url == PR_URL
    assert comment.agent_id == env.agent_id
    assert comment.author == OWNER
    assert comment.body == "Troque o nome"
    assert comment.path is None and comment.line is None
    assert comment.html_url == PR_URL + "#issuecomment-101"
    assert comment.created_at == 1792756800
    assert abs(comment.received_at - time.time()) < 60
    assert comment.status == "queued" and comment.batch_at is None
    assert env.queued_calls == 1


def test_issue_comment_without_pull_request_is_ignored(env: Env):
    assert env.post("issue_comment", issue_comment(on_pr=False)).status_code == 202
    assert env.queue() == []


def test_review_comment_has_path_and_line(env: Env):
    assert env.post("pull_request_review_comment", line_comment()).status_code == 202
    [comment] = env.queue()
    assert comment.comment_id == "line:202"
    assert comment.pr_url == PR_URL
    assert comment.path == "src/a.py" and comment.line == 12


def test_review_with_body_queued(env: Env):
    assert env.post("pull_request_review", review()).status_code == 202
    [comment] = env.queue()
    assert comment.comment_id == "review:303"
    assert comment.body == "Está bom, ajuste isto"
    assert comment.created_at == 1792756920


def test_review_without_body_ignored(env: Env):
    assert env.post("pull_request_review", review(None)).status_code == 202
    assert env.post("pull_request_review", review("")).status_code == 202
    assert env.queue() == []


def test_redelivery_is_idempotent(env: Env):
    body = json.dumps(issue_comment()).encode()
    assert env.post_raw("issue_comment", body).status_code == 202
    assert env.post_raw("issue_comment", body).status_code == 202
    assert len(env.queue()) == 1
    assert env.queued_calls == 1


def test_pr_url_has_no_fragment(env: Env):
    payload = issue_comment()
    payload["issue"]["pull_request"]["html_url"] = PR_URL + "#issuecomment-101"
    assert env.post("issue_comment", payload).status_code == 202
    assert env.queue()[0].pr_url == PR_URL


def test_only_github_route(env: Env):
    assert env.client.get("/github").status_code == 405
    assert env.client.post("/api/sessions", json={}).status_code == 404
    assert env.client.get("/api/health").status_code == 404
    assert env.client.get("/").status_code == 404


def test_no_host_or_origin_check(env: Env):
    body = json.dumps(issue_comment()).encode()
    response = env.client.post(
        "/github",
        content=body,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": sign(SECRET, body),
            "Host": "hooks.example.com",
            "Origin": "https://github.com",
        },
    )
    assert response.status_code == 202


def test_secret_file_mode_600(tmp_path: Path):
    github_hooks.write_secret(tmp_path / "d", "abc")
    path = tmp_path / "d" / github_hooks.SECRET_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert github_hooks.read_secret(tmp_path / "d") == b"abc"
    github_hooks.write_secret(tmp_path / "d", "other")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert github_hooks.read_secret(tmp_path / "d") == b"other"
    assert [p.name for p in (tmp_path / "d").iterdir()] == [github_hooks.SECRET_FILE]


def test_read_secret_missing_or_blank(tmp_path: Path):
    assert github_hooks.read_secret(tmp_path) is None
    (tmp_path / github_hooks.SECRET_FILE).write_text("  \n")
    assert github_hooks.read_secret(tmp_path) is None


def test_owner_round_trip(tmp_path: Path):
    db_path = tmp_path / "m.db"
    db.init_db(db_path)
    with closing(db.connect(db_path)) as conn:
        assert github_hooks.get_owner(conn) is None
        github_hooks.set_owner(conn, "a")
        github_hooks.set_owner(conn, "b")
        assert github_hooks.get_owner(conn) == "b"


def test_verify_signature():
    body = b"hello"
    good = sign(SECRET, body)
    assert github_hooks.verify_signature(SECRET.encode(), body, good)
    assert not github_hooks.verify_signature(SECRET.encode(), body, None)
    assert not github_hooks.verify_signature(SECRET.encode(), body, good[len("sha256="):])
    assert not github_hooks.verify_signature(SECRET.encode(), body, "sha1=" + good[7:])
    assert not github_hooks.verify_signature(SECRET.encode(), body, "sha256=é")
    assert not github_hooks.verify_signature(b"other", body, good)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.anyio
async def test_serve_hooks_listens_on_loopback_and_stops(tmp_path: Path):
    env = Env(tmp_path)
    port = free_port()
    task = github_hooks.serve_hooks(env.client.app, port)
    body = json.dumps(issue_comment()).encode()
    headers = {"X-GitHub-Event": "issue_comment", "X-Hub-Signature-256": sign(SECRET, body)}
    async with httpx.AsyncClient() as http:
        for _ in range(100):
            try:
                response = await http.post(
                    f"http://127.0.0.1:{port}/github", content=body, headers=headers
                )
                break
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
        else:
            pytest.fail("o listener não subiu")
    assert response.status_code == 202
    assert len(env.queue()) == 1
    await github_hooks.stop_hooks(task)
    assert task.done()


@pytest.mark.anyio
async def test_serve_hooks_port_in_use_does_not_kill_the_loop(tmp_path: Path):
    env = Env(tmp_path)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        task = github_hooks.serve_hooks(env.client.app, busy.getsockname()[1])
        await asyncio.wait_for(asyncio.shield(task), 5)
    assert task.done() and task.exception() is None
    await github_hooks.stop_hooks(task)


# The app's lifespan -------------------------------------------------------------


def _app_with_hooks_port(home: Path, data_dir: Path, port: int | None, ports=None):
    from claudio_maestro.agent.fake import FakeAgentFactory
    from claudio_maestro.app import create_app
    from claudio_maestro.config import Settings

    return create_app(
        settings=Settings(home_dir=home, data_dir=data_dir, hooks_port=port),
        agent_factory=FakeAgentFactory(),
        ports=ports,
    )


def _signed_post(port: int) -> httpx.Response:
    body = json.dumps(issue_comment()).encode()
    headers = {"X-GitHub-Event": "issue_comment", "X-Hub-Signature-256": sign(SECRET, body)}
    return httpx.post(f"http://127.0.0.1:{port}/github", content=body, headers=headers)


def _wait_for(port: int) -> httpx.Response:
    for _ in range(100):
        try:
            return _signed_post(port)
        except httpx.ConnectError:
            time.sleep(0.05)
    pytest.fail("o listener não subiu")


def test_app_serves_hooks_only_with_a_port(home: Path, data_dir: Path):
    port = free_port()
    github_hooks.write_secret(data_dir, SECRET)
    app = _app_with_hooks_port(home, data_dir, port)
    with TestClient(app, base_url="http://127.0.0.1:6660", headers={"x-maestro": "1"}):
        assert app.state.hooks_task is not None
        # No PR belongs to an agent here, so the delivery is accepted and ignored.
        assert _wait_for(port).status_code == 202
        task = app.state.hooks_task
    assert task.done()
    with pytest.raises(httpx.ConnectError):
        _signed_post(port)

    off = _app_with_hooks_port(home, data_dir, None)
    with TestClient(off, base_url="http://127.0.0.1:6660", headers={"x-maestro": "1"}):
        assert off.state.hooks_task is None


def test_app_wires_the_hooks_to_the_agents_and_the_dispatcher(home: Path, data_dir: Path, monkeypatch):
    from claudio_maestro.org.comments import CommentDispatcher

    port = free_port()
    woken: list[int] = []
    monkeypatch.setattr(CommentDispatcher, "wake", lambda self: woken.append(1))
    github_hooks.write_secret(data_dir, SECRET)
    app = _app_with_hooks_port(home, data_dir, port)
    # The agent, its PR and the owner exist before the app starts.
    from claudio_maestro.config import Settings

    db_path = Settings(home_dir=home, data_dir=data_dir).db_path
    db.init_db(db_path)
    with closing(db.connect(db_path)) as conn, db.transaction(conn):
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/tmp/p', '#fff', 0, 0)"
        )
        agent = store.create_agent(
            conn, slug="revisor", name="Revisor", project_id=1, reports_to=None, now=1
        )
        store.upsert_pr(conn, url=PR_URL, agent_id=agent.id, session_id=None, created_at=1)
        github_hooks.set_owner(conn, OWNER)

    with TestClient(app, base_url="http://127.0.0.1:6660", headers={"x-maestro": "1"}):
        assert _wait_for(port).status_code == 202
        stranger = json.dumps({**issue_comment(), "issue": {
            "html_url": "https://github.com/acme/repo/pull/99",
            "pull_request": {"html_url": "https://github.com/acme/repo/pull/99"},
        }}).encode()
        headers = {"X-GitHub-Event": "issue_comment", "X-Hub-Signature-256": sign(SECRET, stranger)}
        httpx.post(f"http://127.0.0.1:{port}/github", content=stranger, headers=headers)

    with closing(db.connect(db_path)) as conn:
        [queued] = store.queued_comments(conn)
    assert (queued.comment_id, queued.pr_url, queued.agent_id) == ("issue:101", PR_URL, agent.id)
    assert woken == [1]  # only the comment on the agent's PR woke the dispatcher


def test_app_refuses_hooks_port_equal_to_an_app_port(home: Path, data_dir: Path):
    port = free_port()
    app = _app_with_hooks_port(home, data_dir, port, ports=(6600, port))
    with TestClient(app, base_url=f"http://127.0.0.1:{port}", headers={"x-maestro": "1"}):
        assert app.state.hooks_task is None


@pytest.mark.anyio
async def test_stop_hooks_does_not_hang_on_a_stalled_client(tmp_path: Path):
    env = Env(tmp_path)
    port = free_port()
    task = github_hooks.serve_hooks(env.client.app, port)
    reader = writer = None
    for _ in range(100):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            break
        except OSError:
            await asyncio.sleep(0.05)
    assert writer is not None, "o listener não subiu"
    # Declares 100 bytes, sends 2 and stays quiet: an open request nobody finishes.
    writer.write(
        b"POST /github HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n"
        b"X-GitHub-Event: issue_comment\r\n\r\n{}"
    )
    await writer.drain()
    await asyncio.sleep(0.2)
    started = time.monotonic()
    await asyncio.wait_for(github_hooks.stop_hooks(task), 8)
    assert time.monotonic() - started < 8
    assert task.done()
    writer.close()


@pytest.mark.anyio
async def test_stop_hooks_cancels_a_task_that_will_not_exit():
    stuck = asyncio.create_task(asyncio.sleep(100))
    await asyncio.wait_for(github_hooks.stop_hooks(stuck, timeout=0.1), 3)
    assert stuck.cancelled()


@pytest.mark.anyio
async def test_stop_hooks_propagates_cancellation_of_its_caller():
    stuck = asyncio.create_task(asyncio.sleep(100))
    caller = asyncio.create_task(github_hooks.stop_hooks(stuck, timeout=30))
    await asyncio.sleep(0.05)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await asyncio.sleep(0)
    assert stuck.cancelled()
