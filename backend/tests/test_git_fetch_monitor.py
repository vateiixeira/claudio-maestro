"""The monitor's fetch: manual and periodic, with a fake `fetch` (no git remote involved)."""

import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from git_helpers import make_repo
from test_git_api import (  # noqa: F401 (fixtures)
    add_project,
    factory,
    git_events,
    spawn,
)
from test_sessions_api import APP_ORIGIN, BACKEND_URL, WS_URL

from claudio_maestro import gitfetch, gitinfo
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}


class FakeFetch:
    """Stands in for `gitinfo.fetch_upstream`: records the repositories it was asked for."""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.result: bool = True
        self.error: str | None = None

    async def __call__(self, repo: Path, **kwargs) -> bool:
        self.calls.append(repo)
        if self.error:
            raise gitinfo.GitError(self.error)
        return self.result

    @property
    def names(self) -> list[str]:
        return sorted(call.name for call in self.calls)


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def fake() -> FakeFetch:
    return FakeFetch()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(gitfetch.registry, "_clock", clock)
    monkeypatch.setattr(gitfetch.registry, "_monotonic", clock)
    return clock


def started(factory, spawn, home, data_dir, fake, **settings):
    return create_app(
        settings=Settings(home_dir=home, data_dir=data_dir, **settings),
        agent_factory=factory, history_exists=lambda s, c: False, spawn_editor=spawn,
        git_fetch=fake,
    )


def two_repos(home: Path) -> Path:
    root = make_repo(home / "proj")
    make_repo(root / "api")
    return root


def test_fetch_project_fetches_every_repository_and_publishes(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, two_repos(home))
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]
        api.portal.call(app.state.git_monitor.fetch_project, project["id"])
        assert fake.names == ["api", "proj"]
        (event,) = [e for e in events if e["type"] == "project.git"]
        repos = event["data"]["repos"]
        assert [r["fetched_at"] for r in repos] == [10_000.0, 10_000.0]
        assert [r["fetch_error"] for r in repos] == [None, None]
        assert [r["fetching"] for r in repos] == [False, False]


def test_fetch_project_ignores_the_wait(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, make_repo(home / "proj"))
        monitor = app.state.git_monitor
        fake.error = "fatal: sem rede"
        api.portal.call(monitor.fetch_project, project["id"])
        api.portal.call(monitor.fetch_project, project["id"])
        assert len(fake.calls) == 2


def test_fetch_project_publishes_failures(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, make_repo(home / "proj"))
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]
        fake.error = "fatal: sem rede"
        api.portal.call(app.state.git_monitor.fetch_project, project["id"])
        (event,) = [e for e in events if e["type"] == "project.git"]
        (repo,) = event["data"]["repos"]
        assert repo["fetch_error"] == "fatal: sem rede" and repo["fetched_at"] is None


def test_nothing_to_fetch_publishes_nothing(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, make_repo(home / "proj"))
        monitor = app.state.git_monitor
        api.portal.call(monitor.refresh_project, project["id"])
        events: list[dict] = []
        app.state.hub.publish = events.append  # type: ignore[method-assign]
        fake.result = False  # no upstream
        api.portal.call(monitor.fetch_project, project["id"])
        assert [e for e in events if e["type"] == "project.git"] == []


def test_unavailable_project_is_not_fetched(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        root = make_repo(home / "proj")
        project = add_project(api, root)
        shutil.rmtree(root)
        api.portal.call(app.state.git_monitor.fetch_project, project["id"])
        assert fake.calls == []


def test_fetch_due_only_fetches_what_is_due(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, two_repos(home))
        monitor = app.state.git_monitor
        api.portal.call(monitor.fetch_due, 300)
        assert fake.names == ["api", "proj"]
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 2  # nothing is due yet
        clock.now += 299
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 2
        clock.now += 1
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 4


def test_fetch_due_waits_twice_as_long_after_a_failure(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, make_repo(home / "proj"))
        monitor = app.state.git_monitor
        fake.error = "fatal: sem rede"
        api.portal.call(monitor.fetch_due, 300)
        clock.now += 300
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 1  # still waiting: failed once, so 600 s
        clock.now += 300
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 2
        fake.error = None
        clock.now += 1200
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 3
        clock.now += 300  # a success is back to the normal interval
        api.portal.call(monitor.fetch_due, 300)
        assert len(fake.calls) == 4


def test_periodic_pass_reuses_the_repositories_of_the_last_refresh(
    factory, spawn, home, data_dir, fake, clock, monkeypatch
):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, two_repos(home))
        monitor = app.state.git_monitor
        scans: list[Path] = []
        real = gitinfo.discover_scan
        monkeypatch.setattr(
            gitinfo, "discover_scan", lambda root: (scans.append(root), real(root))[1]
        )
        fake.result = False  # nothing fetched, so nothing is published or rescanned
        api.portal.call(monitor.fetch_due, 300)  # no refresh yet: has to look
        assert len(scans) == 1 and fake.names == ["api", "proj"]
        api.portal.call(monitor.refresh_project, project["id"])
        scans.clear()
        clock.now += 300
        api.portal.call(monitor.fetch_due, 300)
        assert scans == [] and len(fake.calls) == 4  # the list of the last refresh was enough
        api.portal.call(monitor.fetch_project, project["id"])  # "Verificar agora" looks again
        assert len(scans) == 1


def test_status_and_details_carry_the_fetch_fields(factory, spawn, home, data_dir, fake, clock):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        project = add_project(api, make_repo(home / "proj"))
        pid = project["id"]
        for route in ("git", "git/details"):
            (repo,) = api.get(f"/api/projects/{pid}/{route}").json()["repos"]
            assert (repo["fetched_at"], repo["fetch_error"], repo["fetching"]) == (None, None, False)
        api.portal.call(app.state.git_monitor.fetch_project, pid)
        for route in ("git", "git/details"):
            (repo,) = api.get(f"/api/projects/{pid}/{route}").json()["repos"]
            assert (repo["fetched_at"], repo["fetch_error"], repo["fetching"]) == (10_000.0, None, False)
        fake.error = "fatal: sem rede"
        api.portal.call(app.state.git_monitor.fetch_project, pid)
        for route in ("git", "git/details"):
            (repo,) = api.get(f"/api/projects/{pid}/{route}").json()["repos"]
            assert (repo["fetched_at"], repo["fetch_error"]) == (10_000.0, "fatal: sem rede")


# The periodic loop ------------------------------------------------------------------


def wait_for(condition, timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_loop_waits_for_a_connection_then_fetches(factory, spawn, home, data_dir, fake):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0.05)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, make_repo(home / "proj"))
        time.sleep(0.3)
        assert fake.calls == []  # nobody is looking
        with api.websocket_connect(WS_URL, headers=HEADERS) as ws:
            events = git_events(ws, 1)
            assert wait_for(lambda: len(fake.calls) >= 1)
            (event,) = events
            assert event["data"]["repos"][0]["fetched_at"] is not None


def test_loop_fetches_again_every_interval(factory, spawn, home, data_dir, fake):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0.1)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, make_repo(home / "proj"))
        with api.websocket_connect(WS_URL, headers=HEADERS):
            assert wait_for(lambda: len(fake.calls) >= 3)


def test_loop_off_with_interval_zero(factory, spawn, home, data_dir, fake):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, make_repo(home / "proj"))
        with api.websocket_connect(WS_URL, headers=HEADERS):
            time.sleep(0.3)
        assert fake.calls == []


def test_loop_survives_a_failing_pass(factory, spawn, home, data_dir, fake, monkeypatch):
    app = started(factory, spawn, home, data_dir, fake, git_fetch_interval_seconds=0.05)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as api:
        add_project(api, make_repo(home / "proj"))
        monitor = app.state.git_monitor
        original = monitor.fetch_due
        passes = []

        async def broken(interval):
            passes.append(1)
            if len(passes) == 1:
                raise RuntimeError("falha")
            await original(interval)

        monkeypatch.setattr(monitor, "fetch_due", broken)
        with api.websocket_connect(WS_URL, headers=HEADERS):
            assert wait_for(lambda: len(fake.calls) >= 1)
