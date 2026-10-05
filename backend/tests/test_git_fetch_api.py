"""POST /api/projects/{id}/git/fetch ("Verificar agora") and its guards."""

import asyncio
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git_helpers import git, make_repo
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    factory,
    git_events,
    spawn,
)
from test_git_fetch_monitor import (  # noqa: F401
    HEADERS,
    Clock,
    FakeFetch,
    fake,
    started,
)
from test_gitinfo_fetch import clone_to, commit_file, make_clone
from test_sessions_api import APP_ORIGIN, BACKEND_URL, WS_URL

from claudio_maestro import gitfetch, gitinfo
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(gitfetch.registry, "_clock", clock)
    monkeypatch.setattr(gitfetch.registry, "_monotonic", clock)
    return clock


@pytest.fixture
def api(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


def test_fetch_route_fetches_and_answers_like_get(api, home, fake):
    root = make_repo(home / "proj")
    make_repo(root / "api")
    project = add_project(api, root)
    response = api.post(f"/api/projects/{project['id']}/git/fetch")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"repos", "limit_reached"} and body["limit_reached"] is False
    assert [r["rel_path"] for r in body["repos"]] == [".", "api"]
    assert [r["fetched_at"] for r in body["repos"]] == [10_000.0, 10_000.0]
    assert fake.names == ["api", "proj"]
    assert api.get(f"/api/projects/{project['id']}/git").json() == body


def test_fetch_route_reports_failures_per_repository(api, home, fake):
    project = add_project(api, make_repo(home / "proj"))
    fake.error = "fatal: sem rede"
    response = api.post(f"/api/projects/{project['id']}/git/fetch")
    assert response.status_code == 200
    (repo,) = response.json()["repos"]
    assert (repo["fetched_at"], repo["fetch_error"]) == (None, "fatal: sem rede")


def test_fetch_route_ignores_the_interval_and_the_wait(api, home, fake):
    project = add_project(api, make_repo(home / "proj"))
    fake.error = "fatal: sem rede"
    api.post(f"/api/projects/{project['id']}/git/fetch")
    api.post(f"/api/projects/{project['id']}/git/fetch")
    assert len(fake.calls) == 2


def test_fetch_route_publishes_the_event(api, home):
    project = add_project(api, make_repo(home / "proj"))
    with api.websocket_connect(WS_URL, headers=HEADERS) as ws:
        api.post(f"/api/projects/{project['id']}/git/fetch")
        (event,) = git_events(ws, 1)
    assert event["data"]["project_id"] == project["id"]
    assert event["data"]["repos"][0]["fetched_at"] == 10_000.0


def test_fetch_route_unknown_project(api):
    assert api.post("/api/projects/999/git/fetch").status_code == 404


def test_fetch_route_unavailable_project_is_empty(api, home, fake):
    root = make_repo(home / "proj")
    project = add_project(api, root)
    shutil.rmtree(root)
    response = api.post(f"/api/projects/{project['id']}/git/fetch")
    assert response.json() == {"repos": [], "limit_reached": False}
    assert fake.calls == []


def test_fetch_route_stops_waiting_for_a_slow_remote(api, home, monkeypatch):
    project = add_project(api, make_repo(home / "proj"))
    monkeypatch.setattr("claudio_maestro.gitmonitor.MANUAL_FETCH_LIMIT_SECONDS", 0.2)

    async def slow(repo: Path, **kwargs) -> bool:
        await asyncio.sleep(30)
        return True

    api.app.state.git_monitor._fetch = slow
    response = api.post(f"/api/projects/{project['id']}/git/fetch")
    assert response.status_code == 200
    (repo,) = response.json()["repos"]
    assert repo["fetching"] is False and repo["fetched_at"] is None


# The route in the real stack: real repositories, real fetch ----------------------------


@pytest.fixture
def real(factory, spawn, home, data_dir, monkeypatch):
    monkeypatch.setattr(gitinfo, "FETCH_ALLOWED_PROTOCOLS", (*gitinfo.FETCH_ALLOWED_PROTOCOLS, "file"))
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir, git_fetch_interval_seconds=0),
        agent_factory=factory, history_exists=lambda s, c: False, spawn_editor=spawn,
    )
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as c:
        yield c


def test_fetch_route_makes_behind_current(real, home):
    remote, clone = make_clone(home)
    project_root = home / "proj"
    clone.rename(project_root)
    other = home / "other"
    clone_to(remote, other)
    commit_file(other, "novo.txt")
    git(other, "push", "-q")
    project = add_project(real, project_root)
    (before,) = real.get(f"/api/projects/{project['id']}/git").json()["repos"]
    assert (before["upstream"], before["behind"]) == ("origin/main", 0)
    (after,) = real.post(f"/api/projects/{project['id']}/git/fetch").json()["repos"]
    assert after["behind"] == 1
    assert after["fetched_at"] is not None and after["fetch_error"] is None
    (details,) = real.get(f"/api/projects/{project['id']}/git/details").json()["repos"]
    assert details["behind"] == 1 and details["fetched_at"] == after["fetched_at"]


def test_fetch_route_default_refuses_local_remote(factory, spawn, home, data_dir):
    # No override: the production allowlist is https and ssh only.
    app = create_app(
        settings=Settings(home_dir=home, data_dir=data_dir, git_fetch_interval_seconds=0),
        agent_factory=factory, history_exists=lambda s, c: False, spawn_editor=spawn,
    )
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        remote, clone = make_clone(home)
        project = add_project(api, clone)
        (repo,) = api.post(f"/api/projects/{project['id']}/git/fetch").json()["repos"]
        assert repo["fetched_at"] is None and repo["fetch_error"]
        assert "\n" not in repo["fetch_error"]


# Security ------------------------------------------------------------------------------


def test_fetch_route_needs_the_app_origin(factory, spawn, home, data_dir, fake):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, make_repo(home / "proj"))
    url = f"/api/projects/{project['id']}/git/fetch"
    with TestClient(app, base_url=BACKEND_URL) as bare:
        assert bare.post(url, headers={"x-maestro": "1"}).status_code == 403  # no origin
        assert bare.post(url, headers={"x-maestro": "1", "origin": "http://evil.com"}).status_code == 403
        assert bare.post(url, headers={"origin": APP_ORIGIN}).status_code == 403  # no X-Maestro
        assert bare.get(f"/api/projects/{project['id']}/git").status_code == 403
        assert fake.calls == []
        assert bare.post(url, headers=HEADERS).status_code == 200
