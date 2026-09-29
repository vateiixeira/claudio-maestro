"""POST /api/fs/pick: native folder picker with an injected picker."""

import asyncio
import os
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import APP_ORIGIN, BACKEND_URL
from vibing import picker
from vibing.app import create_app
from vibing.config import Settings


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
    return TestClient(app, base_url=base_url, headers={"origin": APP_ORIGIN, "x-vibing": "1"})


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
        (BACKEND_URL, {"origin": APP_ORIGIN}, 403),  # no X-Vibing
        (BACKEND_URL, {"x-vibing": "1"}, 403),  # no Origin
        (BACKEND_URL, {"origin": "http://evil.com", "x-vibing": "1"}, 403),  # foreign Origin
        ("http://evil.com:6660", {"origin": APP_ORIGIN, "x-vibing": "1"}, 400),  # foreign Host
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
