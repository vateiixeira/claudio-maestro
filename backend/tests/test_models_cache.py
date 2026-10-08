"""Models list kept in SQLite and refreshed at most a few times a day."""

import asyncio
from pathlib import Path

import pytest

from claudio_maestro import db
from claudio_maestro.agent.fake import DEFAULT_SERVER_MODELS, FakeAgentFactory
from claudio_maestro.sessions import FALLBACK_MODELS, MODELS_MAX_AGE, SessionManager

HOUR = 3600
NEW_INFO = {"models": [{"value": "opus-x", "displayName": "Opus X"}]}


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Env:
    def __init__(self, tmp_path: Path, info=None, clock=None) -> None:
        self.db_path = tmp_path / "maestro.db"
        db.init_db(self.db_path)
        self.clock = clock or Clock()
        self.events: list[dict] = []
        self.factory = FakeAgentFactory(server_info=info)

    def manager(self) -> SessionManager:
        return SessionManager(
            self.db_path, self.events.append, agent_factory=self.factory, clock=self.clock
        )

    def updates(self) -> list[dict]:
        return [e for e in self.events if e["type"] == "models.updated"]

    def calls(self) -> int:
        return sum(c.server_info_calls for c in self.factory.clients)


def test_max_age_is_eight_hours():
    assert MODELS_MAX_AGE == 8 * HOUR


def test_fallback_only_without_stored_list(tmp_path):
    env = Env(tmp_path)
    assert env.manager().list_models() == FALLBACK_MODELS


@pytest.mark.anyio
async def test_stored_list_survives_new_manager(tmp_path):
    env = Env(tmp_path)
    first = env.manager()
    assert await first.refresh_models_if_stale() is True
    assert first.list_models() == DEFAULT_SERVER_MODELS

    second = env.manager()
    assert second.list_models() == DEFAULT_SERVER_MODELS
    assert second.list_models() != FALLBACK_MODELS


@pytest.mark.anyio
async def test_on_connected_queries_when_missing_and_publishes(tmp_path):
    env = Env(tmp_path)
    manager = env.manager()
    client = env.factory(None)
    await manager._on_connected(client)
    assert client.server_info_calls == 1
    assert len(env.updates()) == 1


@pytest.mark.anyio
async def test_on_connected_skips_when_fresh(tmp_path):
    env = Env(tmp_path)
    await env.manager().refresh_models_if_stale()
    manager = env.manager()
    client = env.factory(None)
    env.clock.now += 7 * HOUR
    await manager._on_connected(client)
    assert client.server_info_calls == 0


@pytest.mark.anyio
async def test_on_connected_queries_when_stale(tmp_path):
    env = Env(tmp_path)
    await env.manager().refresh_models_if_stale()
    env.factory.server_info = NEW_INFO
    manager = env.manager()
    client = env.factory(None)
    env.clock.now += 9 * HOUR
    await manager._on_connected(client)
    assert client.server_info_calls == 1
    assert [m["value"] for m in manager.list_models()] == ["opus-x"]
    assert [m["value"] for m in env.updates()[-1]["data"]["models"]] == ["opus-x"]
    assert [m["value"] for m in env.manager().list_models()] == ["opus-x"]


@pytest.mark.anyio
async def test_unchanged_list_does_not_publish_but_renews_time(tmp_path):
    env = Env(tmp_path)
    manager = env.manager()
    await manager.refresh_models_if_stale()
    env.clock.now += 9 * HOUR
    assert await manager.refresh_models_if_stale() is True
    assert len(env.updates()) == 1
    env.clock.now += 5 * HOUR  # fresh again relative to the renewed time
    assert await manager.refresh_models_if_stale() is False


@pytest.mark.anyio
async def test_empty_new_list_keeps_stored(tmp_path):
    env = Env(tmp_path)
    manager = env.manager()
    await manager.refresh_models_if_stale()
    env.factory.server_info = {"models": []}
    env.clock.now += 9 * HOUR
    await manager.refresh_models_if_stale()
    assert manager.list_models() == DEFAULT_SERVER_MODELS
    assert env.manager().list_models() == DEFAULT_SERVER_MODELS


@pytest.mark.anyio
async def test_refresh_uses_temporary_client_and_closes_it(tmp_path):
    env = Env(tmp_path)
    await env.manager().refresh_models_if_stale()
    assert len(env.factory.clients) == 1
    client = env.factory.clients[0]
    assert client.server_info_calls == 1
    assert client.options.cwd == Path.home() or client.options.cwd.exists()
    assert client.sent == []
    assert client.closed
    # No hooks, plugins or settings of the user or project run for this client.
    assert client.options.setting_sources == []


@pytest.mark.anyio
async def test_refresh_failure_is_swallowed(tmp_path):
    env = Env(tmp_path)
    env.factory.connect_error = "sem login"
    manager = env.manager()
    assert await manager.refresh_models_if_stale() is False
    assert manager.list_models() == FALLBACK_MODELS


@pytest.mark.anyio
async def test_periodic_task_refreshes_and_repeats(tmp_path):
    env = Env(tmp_path)
    manager = env.manager()
    ticks = asyncio.Queue()
    sleeps = 0

    async def fake_sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        env.clock.now += seconds
        await ticks.get()

    task = asyncio.create_task(manager.run_models_refresh(8 * HOUR, sleep=fake_sleep))
    try:
        async with asyncio.timeout(2):
            while sleeps < 1:
                await asyncio.sleep(0)
            assert env.calls() == 1  # at startup, list absent
            env.factory.server_info = NEW_INFO
            ticks.put_nowait(None)  # 8 h later: stale
            while sleeps < 2:
                await asyncio.sleep(0)
        assert env.calls() == 2
        assert [m["value"] for m in manager.list_models()] == ["opus-x"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_periodic_task_idle_when_fresh_and_survives_failure(tmp_path):
    env = Env(tmp_path)
    await env.manager().refresh_models_if_stale()
    before = env.calls()
    manager = env.manager()
    seen = asyncio.Event()

    async def fake_sleep(seconds):
        seen.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(manager.run_models_refresh(8 * HOUR, sleep=fake_sleep))
    async with asyncio.timeout(2):
        await seen.wait()
    assert env.calls() == before
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_periodic_task_survives_failure(tmp_path):
    env = Env(tmp_path)
    env.factory.connect_error = "falhou"
    manager = env.manager()
    seen = asyncio.Event()

    async def fake_sleep(seconds):
        seen.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(manager.run_models_refresh(8 * HOUR, sleep=fake_sleep))
    async with asyncio.timeout(2):
        await seen.wait()
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_models_cache_lives_in_app_state(tmp_path):
    env = Env(tmp_path)
    with db.connect(env.db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM app_state WHERE key = 'models_cache'"
        ).fetchone() is None


@pytest.mark.anyio
async def test_models_refresh_client_keeps_the_sdk_entrypoint(tmp_path):
    env = Env(tmp_path)
    await env.manager().refresh_models_if_stale()
    assert [c.options.entrypoint for c in env.factory.clients] == [None]


@pytest.mark.anyio
async def test_force_refresh_asks_even_when_fresh(tmp_path):
    env = Env(tmp_path, info=NEW_INFO)
    manager = env.manager()
    assert await manager.refresh_models_if_stale() is True
    assert await manager.refresh_models_if_stale() is False
    assert await manager.refresh_models_if_stale(force=True) is True
    assert env.calls() == 2
