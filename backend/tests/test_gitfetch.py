"""In-memory state of the periodic `git fetch`: results, waiting after failures, concurrency."""

import asyncio
import os
from pathlib import Path

import pytest

from claudio_maestro import gitfetch
from claudio_maestro.gitfetch import FetchRegistry

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_registry(clock: Clock | None = None) -> tuple[FetchRegistry, Clock]:
    clock = clock or Clock()
    return FetchRegistry(clock=clock, monotonic=clock), clock


async def ok() -> bool:
    return True


async def skipped() -> bool:
    return False


def failing(message: str = "fatal: sem rede"):
    async def run() -> bool:
        raise RuntimeError(message)

    return run


async def test_unknown_repository_has_empty_fields(tmp_path: Path):
    registry, _ = make_registry()
    assert registry.fields(str(tmp_path)) == {
        "fetched_at": None, "fetch_error": None, "fetching": False,
    }


async def test_success_records_time_and_clears_error(tmp_path: Path):
    registry, clock = make_registry()
    assert await registry.fetch(str(tmp_path), failing("fatal: x")) == "failed"
    assert registry.fields(str(tmp_path))["fetch_error"] == "fatal: x"
    clock.now = 2000.0
    assert await registry.fetch(str(tmp_path), ok) == "fetched"
    assert registry.fields(str(tmp_path)) == {
        "fetched_at": 2000.0, "fetch_error": None, "fetching": False,
    }


async def test_failure_keeps_last_success_time(tmp_path: Path):
    registry, clock = make_registry()
    await registry.fetch(str(tmp_path), ok)
    clock.now += 600
    await registry.fetch(str(tmp_path), failing())
    fields = registry.fields(str(tmp_path))
    assert fields["fetched_at"] == 1000.0
    assert fields["fetch_error"] == "fatal: sem rede"


async def test_error_message_is_one_line(tmp_path: Path):
    registry, _ = make_registry()
    await registry.fetch(str(tmp_path), failing("primeira\nsegunda  \n"))
    assert registry.fields(str(tmp_path))["fetch_error"] == "segunda"
    await registry.fetch(str(tmp_path), failing(""))
    assert registry.fields(str(tmp_path))["fetch_error"] == gitfetch.GENERIC_ERROR


async def test_skipped_records_nothing_but_the_attempt(tmp_path: Path):
    registry, clock = make_registry()
    assert await registry.fetch(str(tmp_path), skipped) == "skipped"
    assert registry.fields(str(tmp_path)) == {
        "fetched_at": None, "fetch_error": None, "fetching": False,
    }
    # Looked at just now: not due again until the interval passes.
    assert registry.due(str(tmp_path), 300) is False
    clock.now += 300
    assert registry.due(str(tmp_path), 300) is True


async def test_key_is_the_real_path(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    registry, _ = make_registry()
    await registry.fetch(str(link), ok)
    assert registry.fields(str(real))["fetched_at"] == 1000.0


async def test_due_when_never_tried_and_after_interval(tmp_path: Path):
    registry, clock = make_registry()
    path = str(tmp_path)
    assert registry.due(path, 300) is True
    await registry.fetch(path, ok)
    assert registry.due(path, 300) is False
    clock.now += 299
    assert registry.due(path, 300) is False
    clock.now += 1
    assert registry.due(path, 300) is True


async def test_wait_doubles_with_each_failure_up_to_30_minutes(tmp_path: Path):
    registry, clock = make_registry()
    path = str(tmp_path)
    waits = []
    for _ in range(6):
        await registry.fetch(path, failing())
        start = clock.now
        step = 10
        while not registry.due(path, 300):
            clock.now += step
        waits.append(clock.now - start)
    assert waits == [600, 1200, 1800, 1800, 1800, 1800]


async def test_success_resets_the_wait(tmp_path: Path):
    registry, clock = make_registry()
    path = str(tmp_path)
    await registry.fetch(path, failing())
    await registry.fetch(path, failing())
    await registry.fetch(path, ok)
    clock.now += 300
    assert registry.due(path, 300) is True


async def test_wait_never_drops_below_a_long_interval(tmp_path: Path):
    # An interval above the cap is the floor: waiting less than it would be a bug.
    registry, clock = make_registry()
    path = str(tmp_path)
    await registry.fetch(path, failing())
    clock.now += 3599
    assert registry.due(path, 3600) is False
    clock.now += 1
    assert registry.due(path, 3600) is True


async def test_fetching_flag_while_running(tmp_path: Path):
    registry, _ = make_registry()
    release = asyncio.Event()
    seen: list[bool] = []

    async def run() -> bool:
        seen.append(registry.fields(str(tmp_path))["fetching"])
        await release.wait()
        return True

    task = asyncio.create_task(registry.fetch(str(tmp_path), run))
    await asyncio.sleep(0.01)
    assert registry.fields(str(tmp_path))["fetching"] is True
    assert registry.due(str(tmp_path), 0.001) is False  # being fetched: not due
    release.set()
    await task
    assert seen == [True]
    assert registry.fields(str(tmp_path))["fetching"] is False


async def test_fetching_flag_cleared_when_cancelled(tmp_path: Path):
    registry, _ = make_registry()

    async def hang() -> bool:
        await asyncio.sleep(60)
        return True

    task = asyncio.create_task(registry.fetch(str(tmp_path), hang))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    fields = registry.fields(str(tmp_path))
    assert fields["fetching"] is False and fields["fetched_at"] is None


async def test_cancelled_fetch_counts_as_a_failure(tmp_path: Path):
    # The 45 s limit of "Verificar agora" cancels the fetch; the loop must not try
    # again on its next tick.
    registry, clock = make_registry()
    path = str(tmp_path)

    async def hang() -> bool:
        await asyncio.sleep(60)
        return True

    task = asyncio.create_task(registry.fetch(path, hang))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert registry.fields(path)["fetch_error"] == gitfetch.INTERRUPTED_ERROR
    assert registry.due(path, 300) is False
    clock.now += 599
    assert registry.due(path, 300) is False  # waits twice the interval, like any failure
    clock.now += 1
    assert registry.due(path, 300) is True


async def test_same_repository_never_fetched_twice_at_once(tmp_path: Path):
    registry, _ = make_registry()
    release = asyncio.Event()
    running = 0
    peak = 0
    calls = 0

    async def run() -> bool:
        nonlocal running, peak, calls
        calls += 1
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1
        return True

    first = asyncio.create_task(registry.fetch(str(tmp_path), run))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(registry.fetch(str(tmp_path), run))
    third = asyncio.create_task(registry.fetch(str(tmp_path), run))
    await asyncio.sleep(0.01)
    release.set()
    assert await asyncio.gather(first, second, third) == ["fetched"] * 3
    # The late requests waited for the first one and reused its result.
    assert calls == 1 and peak == 1


async def test_waiter_reuses_a_failure_too(tmp_path: Path):
    registry, _ = make_registry()
    release = asyncio.Event()
    calls = 0

    async def run() -> bool:
        nonlocal calls
        calls += 1
        await release.wait()
        raise RuntimeError("fatal: caiu")

    first = asyncio.create_task(registry.fetch(str(tmp_path), run))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(registry.fetch(str(tmp_path), run))
    await asyncio.sleep(0.01)
    release.set()
    assert await asyncio.gather(first, second) == ["failed", "failed"]
    assert calls == 1


async def test_waiter_runs_its_own_when_the_first_is_cancelled(tmp_path: Path):
    registry, _ = make_registry()

    async def hang() -> bool:
        await asyncio.sleep(60)
        return True

    first = asyncio.create_task(registry.fetch(str(tmp_path), hang))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(registry.fetch(str(tmp_path), ok))
    await asyncio.sleep(0.01)
    first.cancel()
    assert await second == "fetched"


async def test_at_most_four_fetches_at_once(tmp_path: Path):
    registry, _ = make_registry()
    release = asyncio.Event()
    running = 0
    peak = 0

    async def run() -> bool:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1
        return True

    tasks = []
    for index in range(10):
        folder = tmp_path / f"r{index}"
        folder.mkdir()
        tasks.append(asyncio.create_task(registry.fetch(str(folder), run)))
    await asyncio.sleep(0.05)
    assert running == gitfetch.MAX_CONCURRENT == 4
    release.set()
    assert await asyncio.gather(*tasks) == ["fetched"] * 10
    assert peak == 4


async def test_fill_copies_the_fields_into_a_status(tmp_path: Path):
    from claudio_maestro.gitinfo import RepoStatus

    registry, _ = make_registry()
    await registry.fetch(str(tmp_path), failing())
    status = RepoStatus(path=str(tmp_path), rel_path=".")
    registry.fill(status)
    assert (status.fetched_at, status.fetch_error, status.fetching) == (None, "fatal: sem rede", False)
