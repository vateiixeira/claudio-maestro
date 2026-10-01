"""Scheduler of the digest agent: queue, pause, config changes, cancellation."""

import asyncio
import threading
from contextlib import closing
from pathlib import Path

import pytest
from digest_fakes import NOW, World, exchange

from claudio_maestro import db
from claudio_maestro.digest import store
from claudio_maestro.digest.config import DigestConfig, load_config
from claudio_maestro.digest.model import DigestModelError, FakeDigestModel


def runs(world: World) -> list[dict]:
    with closing(db.connect(world.db_path)) as conn:
        return store.list_runs(conn)


@pytest.mark.anyio
async def test_first_automatic_pass_waits_an_interval(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    assert service.status()["next_run_at"] == int(NOW + 600)
    await service.tick()
    assert model.requests == []
    world.clock[0] = NOW + 600
    await service.tick()
    assert len(model.requests) == 1
    assert service.status()["next_run_at"] == int(NOW + 1200)


@pytest.mark.anyio
async def test_disabled_agent_runs_only_manual_requests(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    world.clock[0] = NOW + 10_000
    await service.tick()
    assert model.requests == [] and service.status()["next_run_at"] is None
    service.request_session("s1")
    await service.tick()
    assert len(model.requests) == 1
    assert [r["trigger"] for r in runs(world)] == ["manual_session"]


@pytest.mark.anyio
async def test_requests_are_queued_without_repeats(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    service.request_session("s1")
    service.request_session("s1")
    service.request_session("s2")
    service.request_all()
    service.request_all()
    await service.tick()
    # Newest first: the general request runs before the session requests.
    assert [r["trigger"] for r in runs(world)] == ["manual_session", "manual_all"]


@pytest.mark.anyio
async def test_disabling_cancels_the_running_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel([FakeDigestModel.DEFAULT])
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True, min_new_messages=1))
    world.clock[0] = NOW + 600
    model.gate = asyncio.Event()  # never set: the first reading hangs
    tick = asyncio.create_task(service.tick())
    await model.started.wait()
    await service.update_config(DigestConfig(enabled=False))
    await asyncio.wait_for(tick, 1)  # the pass is cancelled, the tick itself ends normally
    assert runs(world)[0]["stopped"] == "Desligado."
    assert service.status() == {"enabled": False, "running": False, "next_run_at": None,
                                "paused_until": None}


@pytest.mark.anyio
async def test_disabling_during_a_manual_session_pass_ends_every_requested_session(
    tmp_path: Path,
) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    model.gate = asyncio.Event()  # never set: the first reading hangs
    service.request_session("s1")
    service.request_session("s2")
    tick = asyncio.create_task(service.tick())
    await model.started.wait()
    await service.update_config(DigestConfig(enabled=False))
    await asyncio.wait_for(tick, 1)
    failed = {e["data"]["session_id"]: e["data"]["digest"]["error"]
              for e in world.published("session.digest")}
    assert failed == {"s1": "Desligado.", "s2": "Desligado."}
    assert world.digest("s1").error == "Desligado." and world.digest("s2").error == "Desligado."
    assert runs(world)[0]["stopped"] == "Desligado."


@pytest.mark.anyio
async def test_finish_run_is_off_the_loop_thread_unless_cancelled(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    world.add("s2", exchange(0, 2))
    service = world.service(FakeDigestModel())
    threads: list[threading.Thread] = []
    original = service._finish_run

    def spy(*args, **kwargs):
        threads.append(threading.current_thread())
        return original(*args, **kwargs)

    service._finish_run = spy
    await service.run_pass("manual_session", ["s1"])
    assert threads[-1] is not threading.main_thread()

    model = FakeDigestModel()
    model.gate = asyncio.Event()
    service = world.service(model)
    service._finish_run = spy
    task = asyncio.create_task(service.run_pass("manual_session", ["s2"]))
    await asyncio.wait_for(model.started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert threads[-1] is threading.main_thread()


@pytest.mark.anyio
async def test_a_failing_initial_load_does_not_kill_the_loop(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)

    def boom() -> None:
        raise RuntimeError("banco indisponível")

    service.load = boom
    loop = asyncio.create_task(service.run())
    await asyncio.sleep(0.05)
    assert not loop.done()
    service.request_session("s1")
    await asyncio.wait_for(model.started.wait(), 1)
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop


@pytest.mark.anyio
async def test_pause_holds_automatic_passes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    model = FakeDigestModel()
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    service._paused_until = NOW + 3600
    world.clock[0] = NOW + 600
    await service.tick()
    assert model.requests == []
    world.clock[0] = NOW + 3600
    await service.tick()
    assert len(model.requests) == 1 and service.status()["paused_until"] is None


@pytest.mark.anyio
async def test_update_config_is_saved_and_published(tmp_path: Path) -> None:
    world = World(tmp_path)
    service = world.service(FakeDigestModel())
    await service.update_config(DigestConfig(enabled=True, window_days=5))
    with closing(db.connect(world.db_path)) as conn:
        assert load_config(conn).window_days == 5
    assert world.published("digest.status")[-1]["data"]["enabled"] is True


@pytest.mark.anyio
async def test_run_wakes_up_for_a_request(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = FakeDigestModel()
    service = world.service(model)
    loop = asyncio.create_task(service.run())
    await asyncio.sleep(0)
    service.request_session("s1")
    await asyncio.wait_for(model.started.wait(), 1)
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop


class SlowToCancelModel(FakeDigestModel):
    """Needs one more loop iteration to unwind after being cancelled."""

    async def summarize(self, request):
        try:
            return await super().summarize(request)
        finally:
            await asyncio.sleep(0)


@pytest.mark.anyio
async def test_cancelling_the_loop_finishes_the_running_pass(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 2))
    model = SlowToCancelModel()
    model.gate = asyncio.Event()  # never set: the reading hangs
    service = world.service(model)
    loop = asyncio.create_task(service.run())
    await asyncio.sleep(0)
    service.request_session("s1")
    await asyncio.wait_for(model.started.wait(), 1)
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop
    # No further loop iteration: the run must already be closed.
    run = runs(world)[0]
    assert run["stopped"] == "Desligado." and run["finished_at"] is not None
    assert service.status()["running"] is False


@pytest.mark.anyio
async def test_limit_error_pauses_automatic_passes(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.add("s1", exchange(0, 12))
    resets_at = int(NOW + 600 + 3600)
    model = FakeDigestModel([DigestModelError("Limite atingido.", stop_pass=True,
                                              resets_at=resets_at)])
    service = world.service(model)
    await service.update_config(DigestConfig(enabled=True))
    world.clock[0] = NOW + 600
    await service.tick()
    assert len(model.requests) == 1
    assert service.status()["paused_until"] == resets_at
    world.clock[0] = NOW + 1200  # the next interval is due, but the pause holds it
    await service.tick()
    assert len(model.requests) == 1
    world.clock[0] = resets_at
    await service.tick()
    assert len(model.requests) == 2 and service.status()["paused_until"] is None


@pytest.mark.anyio
async def test_status_hides_an_expired_pause(tmp_path: Path) -> None:
    world = World(tmp_path)
    service = world.service(FakeDigestModel())
    service._paused_until = NOW + 100
    assert service.status()["paused_until"] == int(NOW + 100)
    world.clock[0] = NOW + 100
    assert service.status()["paused_until"] is None
