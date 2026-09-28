from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point home and data dirs to temporary folders in every test."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    monkeypatch.setenv("VIBING_HOME", str(home))
    monkeypatch.setenv("VIBING_DATA_DIR", str(data))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return (tmp_path / "home").resolve()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client():
    """Client that looks like the frontend: valid Host and Origin."""
    with TestClient(
        create_app(), base_url=BACKEND_URL, headers={"origin": APP_ORIGIN}
    ) as c:
        yield c
