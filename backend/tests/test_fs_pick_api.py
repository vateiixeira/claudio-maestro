"""POST /api/fs/pick: native folder picker with an injected picker."""

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro import picker
from claudio_maestro.app import create_app
from claudio_maestro.config import Settings


class Picker:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[Path] = []

    async def __call__(self, initial: Path) -> str | None:
        self.calls.append(initial)
        if self.error:
            raise self.error
        return self.result


def make_client(home: Path, data_dir: Path, pick, base_url: str = BACKEND_URL) -> TestClient:
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), pick_folder=pick)
    return TestClient(app, base_url=base_url, headers={"origin": APP_ORIGIN, "x-maestro": "1"})


def test_returns_chosen_path_resolved(home: Path, data_dir: Path):
    folder = home / "Área de trabalho" / "meu app"
    folder.mkdir(parents=True)
    pick = Picker(str(home / "Área de trabalho" / "x" / ".." / "meu app") + "/")
    with make_client(home, data_dir, pick) as client:
        response = client.post("/api/fs/pick")
    assert response.status_code == 200
    assert response.json() == {"path": str(folder)}
    assert pick.calls == [home]


def test_cancel_returns_null(home: Path, data_dir: Path):
    with make_client(home, data_dir, Picker(None)) as client:
        response = client.post("/api/fs/pick")
    assert response.status_code == 200
    assert response.json() == {"path": None}


def test_outside_home_is_forbidden(home: Path, data_dir: Path, tmp_path: Path):
    outside = tmp_path / "fora"
    outside.mkdir()
    with make_client(home, data_dir, Picker(str(outside))) as client:
        response = client.post("/api/fs/pick")
    assert response.status_code == 403
    assert "pasta pessoal" in response.json()["detail"]


def test_symlink_to_outside_is_forbidden(home: Path, data_dir: Path, tmp_path: Path):
    outside = tmp_path / "fora"
    outside.mkdir()
    os.symlink(outside, home / "atalho")
    with make_client(home, data_dir, Picker(str(home / "atalho"))) as client:
        assert client.post("/api/fs/pick").status_code == 403


def test_unavailable_is_503(home: Path, data_dir: Path):
    pick = Picker(error=picker.PickerUnavailableError())
    with make_client(home, data_dir, pick) as client:
        response = client.post("/api/fs/pick")
    assert response.status_code == 503
    assert response.json()["detail"] == "O seletor de pastas do sistema não está disponível."


def test_timeout_is_504(home: Path, data_dir: Path):
    with make_client(home, data_dir, Picker(error=picker.PickerTimeoutError())) as client:
        response = client.post("/api/fs/pick")
    assert response.status_code == 504
    assert "tempo" in response.json()["detail"]


def test_failure_is_502(home: Path, data_dir: Path):
    with make_client(home, data_dir, Picker(error=picker.PickerError("x"))) as client:
        assert client.post("/api/fs/pick").status_code == 502


def test_second_request_while_open_is_409(home: Path, data_dir: Path):
    started = threading.Event()
    release = threading.Event()

    async def slow(initial: Path) -> str | None:
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return None

    with make_client(home, data_dir, slow) as client:
        results: list[int] = []
        thread = threading.Thread(
            target=lambda: results.append(client.post("/api/fs/pick").status_code)
        )
        thread.start()
        assert started.wait(5)
        second = client.post("/api/fs/pick")
        release.set()
        thread.join(5)
        assert second.status_code == 409
        assert results == [200]
        # Free again afterwards.
        assert client.post("/api/fs/pick").status_code == 200


def test_lock_released_after_error(home: Path, data_dir: Path):
    pick = Picker(error=picker.PickerError("x"))
    with make_client(home, data_dir, pick) as client:
        assert client.post("/api/fs/pick").status_code == 502
        pick.error = None
        assert client.post("/api/fs/pick").status_code == 200


# The existing middleware protects the route like the others.


@pytest.mark.parametrize(
    ("base_url", "headers", "status"),
    [
        (BACKEND_URL, {"origin": APP_ORIGIN}, 403),  # no X-Maestro
        (BACKEND_URL, {"x-maestro": "1"}, 403),  # no Origin
        (BACKEND_URL, {"origin": "http://evil.com", "x-maestro": "1"}, 403),  # foreign Origin
        ("http://evil.com:6660", {"origin": APP_ORIGIN, "x-maestro": "1"}, 400),  # foreign Host
    ],
)
def test_pick_is_protected(home: Path, data_dir: Path, base_url, headers, status):
    pick = Picker(str(home))
    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), pick_folder=pick)
    with TestClient(app, base_url=base_url) as client:
        assert client.post("/api/fs/pick", headers=headers).status_code == status
    assert pick.calls == []


def test_default_picker_never_opens_real_zenity(client):
    """conftest replaces the process starter: the default picker cannot run zenity."""
    assert client.post("/api/fs/pick").status_code == 503


# The browser gives up (tab closed or reloaded) while the picker is open.


class FakeRequest:
    """Just what the route touches: app state and `is_disconnected`."""

    def __init__(self, pick, lock: asyncio.Lock, disconnect_after: int):
        self.app = SimpleNamespace(state=SimpleNamespace(pick_folder=pick, pick_lock=lock))
        self._polls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._polls += 1
        return self._polls > self._disconnect_after


class HangingProcess:
    def __init__(self):
        self.returncode: int | None = None
        self.killed = False

    async def communicate(self):
        await asyncio.sleep(3600)

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


@pytest.mark.anyio
async def test_disconnect_kills_picker_and_frees_lock(home: Path, data_dir: Path, monkeypatch):
    from claudio_maestro.api import fs as fs_api

    monkeypatch.setattr(fs_api, "DISCONNECT_POLL", 0.01)
    processes: list[HangingProcess] = []

    async def spawn(*argv, **kwargs):
        processes.append(HangingProcess())
        return processes[-1]

    async def pick(initial: Path) -> str | None:
        return await picker.pick_folder(initial, spawn=spawn)

    lock = asyncio.Lock()
    settings = Settings(home_dir=home, data_dir=data_dir)
    request = FakeRequest(pick, lock, disconnect_after=3)

    await asyncio.wait_for(fs_api.pick_folder(settings, request), 5)

    assert len(processes) == 1
    assert processes[0].killed
    assert not lock.locked()

    # A new request is not turned away with 409.
    async def quick(initial: Path) -> str | None:
        return None

    again = FakeRequest(quick, lock, disconnect_after=100)
    assert await fs_api.pick_folder(settings, again) == {"path": None}


@pytest.mark.anyio
@pytest.mark.parametrize("content_length", [True, False])
async def test_full_app_detects_disconnect_after_empty_body(
    home: Path, data_dir: Path, monkeypatch, content_length: bool
):
    """Whole ASGI app (all security middlewares): an empty `http.request` followed by
    `http.disconnect` cancels the hanging picker and frees the lock."""
    from claudio_maestro.api import fs as fs_api

    monkeypatch.setattr(fs_api, "DISCONNECT_POLL", 0.02)
    cancelled = asyncio.Event()

    async def hanging(initial: Path) -> str | None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    app = create_app(settings=Settings(home_dir=home, data_dir=data_dir), pick_folder=hanging)
    headers = [
        (b"host", b"localhost:6660"),
        (b"origin", APP_ORIGIN.encode()),
        (b"x-maestro", b"1"),
    ]
    if content_length:
        headers.append((b"content-length", b"0"))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "path": "/api/fs/pick", "raw_path": b"/api/fs/pick", "query_string": b"",
        "headers": headers, "server": ("127.0.0.1", 6660), "client": ("127.0.0.1", 1),
        "scheme": "http", "root_path": "",
    }
    incoming: asyncio.Queue = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        return await incoming.get()

    async def send(message):
        pass

    async with app.router.lifespan_context(app):
        request = asyncio.create_task(app(scope, receive, send))
        await asyncio.sleep(0.15)
        assert not cancelled.is_set()
        assert app.state.pick_lock.locked()
        await incoming.put({"type": "http.disconnect"})
        await asyncio.wait_for(cancelled.wait(), 5)
        await asyncio.wait_for(request, 5)
        assert not app.state.pick_lock.locked()
