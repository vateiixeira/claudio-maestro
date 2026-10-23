"""Comment sweep through `gh`: the safety net for the webhook."""

import asyncio
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.specialists import gh_comments, store

PR_URL = "https://github.com/acme/app/pull/7"
OWNER = "vini"
T0 = 1_800_000_000  # PR creation


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "t.db"
    with closing(db.connect(path)) as conn:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO projects (id, name, path, color, position, created_at)"
            " VALUES (1, 'p', '/tmp/p', '#fff', 0, 0)"
        )
        store.create_specialist(conn, slug="rev", name="Rev", project_id=1, now=1)
        store.upsert_pr(conn, url=PR_URL, specialist_id=1, session_id=None, created_at=T0)
    return path


def read(db_path: Path):
    with closing(db.connect(db_path)) as conn:
        return store.queued_comments(conn), store.get_pr(conn, PR_URL)


class FakeGh:
    """Answers by arguments; records every call. A value that is an Exception is raised."""

    def __init__(self, *, state="OPEN", issue=(), line=(), review=(), fail=()):
        self.calls: list[list[str]] = []
        self.state = state
        self.payload = {"issues": list(issue), "pulls": list(line), "reviews": list(review)}
        self.fail = set(fail)

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        joined = " ".join(args)
        if any(marker in joined for marker in self.fail):
            return 1, ""
        if args[:2] == ["pr", "view"]:
            return 0, json.dumps({"state": self.state})
        assert args[0] == "api"
        endpoint = args[1]
        assert endpoint.startswith("repos/acme/app/")
        if endpoint.endswith("/issues/7/comments"):
            return 0, json.dumps([self.payload["issues"]])
        if endpoint.endswith("/pulls/7/comments"):
            return 0, json.dumps([self.payload["pulls"]])
        if endpoint.endswith("/pulls/7/reviews"):
            return 0, json.dumps([self.payload["reviews"]])
        raise AssertionError(f"unexpected call {args}")


def issue_comment(id_, author=OWNER, at=T0 + 100, body="ajuste isso"):
    return {
        "id": id_, "user": {"login": author}, "body": body, "created_at": iso(at),
        "html_url": f"{PR_URL}#issuecomment-{id_}",
    }


def line_comment(id_, author=OWNER, at=T0 + 100, body="aqui", path="a.py", line=12):
    return {
        "id": id_, "user": {"login": author}, "body": body, "created_at": iso(at),
        "html_url": f"{PR_URL}#discussion_r{id_}", "path": path, "line": line,
    }


def review(id_, author=OWNER, at=T0 + 100, body="geral", state="COMMENTED"):
    return {
        "id": id_, "user": {"login": author}, "body": body, "submitted_at": iso(at),
        "state": state, "html_url": f"{PR_URL}#pullrequestreview-{id_}",
    }


def poll(db_path, gh, now=T0 + 3600):
    return asyncio.run(gh_comments.poll_comments(db_path, owner=OWNER, run_gh=gh, now=now))


def test_poll_queues_owner_comments_since_last_poll(db_path):
    with closing(db.connect(db_path)) as conn:
        store.mark_pr_polled(conn, PR_URL, T0 + 1000)
    gh = FakeGh(
        issue=[issue_comment(1, at=T0 + 500), issue_comment(2, at=T0 + 1500)],
        line=[line_comment(3, at=T0 + 2000)],
        review=[review(4, at=T0 + 2500)],
    )

    assert poll(db_path, gh, now=T0 + 3600) == 3

    queued, pr = read(db_path)
    assert {c.comment_id for c in queued} == {"issue:2", "line:3", "review:4"}
    by_id = {c.comment_id: c for c in queued}
    assert by_id["issue:2"].created_at == T0 + 1500
    assert by_id["issue:2"].html_url == f"{PR_URL}#issuecomment-2"
    assert by_id["issue:2"].pr_url == PR_URL and by_id["issue:2"].specialist_id == 1
    assert by_id["issue:2"].author == OWNER and by_id["issue:2"].path is None
    assert by_id["line:3"].path == "a.py" and by_id["line:3"].line == 12
    assert by_id["review:4"].body == "geral"
    assert all(c.status == "queued" and c.received_at == T0 + 3600 for c in queued)
    assert pr.polled_at == T0 + 3600


def test_first_poll_uses_pr_creation_time(db_path):
    gh = FakeGh(issue=[issue_comment(1, at=T0 - 5000), issue_comment(2, at=T0 + 10)])

    assert poll(db_path, gh) == 1

    assert [c.comment_id for c in read(db_path)[0]] == ["issue:2"]


def test_poll_ignores_other_authors_and_empty_reviews(db_path):
    gh = FakeGh(
        issue=[issue_comment(1, author="someone-else"), issue_comment(2, author="VINI")],
        line=[line_comment(3, author="copilot")],
        review=[review(4, body=""), review(5, body="   "), review(6, author="other"),
                review(7, body="ok")],
    )

    assert poll(db_path, gh) == 2

    assert {c.comment_id for c in read(db_path)[0]} == {"issue:2", "review:7"}


def test_poll_ignores_pending_review_without_submit_time(db_path):
    pending = review(9)
    del pending["submitted_at"]
    pending["state"] = "PENDING"

    assert poll(db_path, FakeGh(review=[pending])) == 0


def test_poll_closes_merged_pr(db_path):
    gh = FakeGh(state="MERGED", issue=[issue_comment(1)])

    assert poll(db_path, gh) == 0

    queued, _ = read(db_path)
    with closing(db.connect(db_path)) as conn:
        assert store.get_pr(conn, PR_URL).closed is True
        assert store.open_prs(conn) == []
    assert queued == []
    assert all(call[0] != "api" for call in gh.calls)


def test_poll_closes_closed_pr(db_path):
    poll(db_path, FakeGh(state="CLOSED"))
    with closing(db.connect(db_path)) as conn:
        assert store.get_pr(conn, PR_URL).closed is True


def test_poll_dedupes_with_webhook(db_path):
    with closing(db.connect(db_path)) as conn:
        store.insert_comment(conn, store.PrComment(
            comment_id="issue:1", pr_url=PR_URL, specialist_id=1, author=OWNER, body="x",
            path=None, line=None, html_url="h", created_at=T0 + 100, received_at=T0 + 101,
            status="delivered", batch_at=T0 + 200,
        ))
    gh = FakeGh(issue=[issue_comment(1), issue_comment(2)])

    assert poll(db_path, gh) == 1

    assert [c.comment_id for c in read(db_path)[0]] == ["issue:2"]
    assert poll(db_path, gh, now=T0 + 7200) == 0  # a second sweep brings nothing new


def test_poll_continues_after_one_pr_fails(db_path):
    other = "https://github.com/acme/other/pull/3"
    with closing(db.connect(db_path)) as conn:
        store.upsert_pr(conn, url=other, specialist_id=1, session_id=None, created_at=T0 + 1)

    class Gh(FakeGh):
        async def __call__(self, args):
            if "acme/app" in " ".join(args) or PR_URL in args:
                return 1, ""
            self.calls.append(args)
            if args[:2] == ["pr", "view"]:
                return 0, json.dumps({"state": "OPEN"})
            if args[1].endswith("/issues/3/comments"):
                return 0, json.dumps([issue_comment(50)])
            return 0, "[]"

    assert poll(db_path, Gh()) == 1

    with closing(db.connect(db_path)) as conn:
        assert [c.comment_id for c in store.queued_comments(conn)] == ["issue:50"]
        # the failed PR is not marked as polled, so its comments are still picked up later
        assert store.get_pr(conn, PR_URL).polled_at is None
        assert store.get_pr(conn, other).polled_at == T0 + 3600


def test_poll_does_not_mark_polled_when_a_comment_call_fails(db_path):
    gh = FakeGh(issue=[issue_comment(1)], fail=["pulls/7/reviews"])

    assert poll(db_path, gh) == 0

    assert read(db_path)[1].polled_at is None


def test_poll_survives_gh_exception_and_garbage(db_path):
    async def gh(args):
        raise RuntimeError("boom")

    assert poll(db_path, gh) == 0

    async def garbage(args):
        return 0, "not json"

    assert poll(db_path, garbage) == 0
    assert read(db_path)[1].polled_at is None


def test_poll_without_open_prs_does_nothing(db_path):
    with closing(db.connect(db_path)) as conn:
        store.close_pr(conn, PR_URL)
    gh = FakeGh()

    assert poll(db_path, gh) == 0
    assert gh.calls == []


def test_poll_normalizes_pr_url_with_trailing_slash(db_path):
    with closing(db.connect(db_path)) as conn:
        conn.execute("DELETE FROM specialist_prs")
        store.upsert_pr(conn, url=PR_URL + "/", specialist_id=1, session_id=None, created_at=T0)
    gh = FakeGh(issue=[issue_comment(1)])

    assert poll(db_path, gh) == 1
    assert read(db_path)[0][0].pr_url == PR_URL


@pytest.mark.parametrize("raw", [
    '[[{"id": 1}],[{"id": 2}]]',  # --slurp
    '[{"id": 1}][{"id": 2}]',  # --paginate without --slurp
    '[{"id": 1}]\n[{"id": 2}]',
])
def test_parse_pages_handles_pagination_shapes(raw):
    assert gh_comments.parse_pages(raw) == [{"id": 1}, {"id": 2}]


def test_parse_pages_empty_output_is_empty():
    assert gh_comments.parse_pages("") == []


def test_parse_pr_url():
    assert gh_comments.parse_pr_url("https://github.com/a/b/pull/12/") == ("a", "b", 12)
    assert gh_comments.parse_pr_url("https://github.com/a/b/pull/12#issuecomment-1") == ("a", "b", 12)
    assert gh_comments.parse_pr_url("https://github.com/a/b/issues/12") is None
    assert gh_comments.parse_pr_url("not a url") is None


class FakeProc:
    returncode = 0

    def __init__(self, out=b"[]", hang=False):
        self.out, self.hang, self.killed = out, hang, False

    async def communicate(self):
        if self.hang:
            await asyncio.sleep(3600)
        return self.out, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return -9


def test_run_gh_uses_argument_list(monkeypatch):
    seen = {}
    proc = FakeProc(b'{"ok": true}')

    async def fake_exec(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    code, out = asyncio.run(gh_comments.run_gh(["api", "repos/a/b; rm -rf /"]))

    assert (code, out) == (0, '{"ok": true}')
    assert seen["args"] == ("gh", "api", "repos/a/b; rm -rf /")
    assert "shell" not in seen["kwargs"]


def test_run_gh_missing_binary_returns_127(monkeypatch):
    async def fake_exec(*args, **kwargs):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    assert asyncio.run(gh_comments.run_gh(["pr", "view"])) == (127, "")


def test_run_gh_kills_process_on_timeout(monkeypatch):
    proc = FakeProc(hang=True)

    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(gh_comments, "GH_TIMEOUT_SECONDS", 0.05)

    code, out = asyncio.run(gh_comments.run_gh(["pr", "view"]))

    assert code != 0 and out == ""
    assert proc.killed is True


