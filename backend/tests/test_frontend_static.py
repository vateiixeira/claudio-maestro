"""The built frontend served by the backend (single-command mode)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claudio_maestro.app import create_app
from claudio_maestro.frontend_static import resolve_asset

BACKEND_URL = "http://127.0.0.1:6660"
INDEX = "<!doctype html><title>Cláudio Maestro</title>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text(INDEX, encoding="utf-8")
    (folder / "assets" / "app-abc123.js").write_text("console.log(1)")
    (folder / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("segredo")
    return folder


@pytest.fixture
def served(dist: Path):
    # A browser loading the page sends neither Origin nor X-Maestro.
    with TestClient(create_app(frontend_dir=dist), base_url=BACKEND_URL) as client:
        yield client


def test_root_serves_index_without_cache(served):
    response = served.get("/")
    assert response.status_code == 200
    assert "Cláudio Maestro" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_head_on_root(served):
    assert served.head("/").status_code == 200


def test_hashed_asset_has_long_cache(served):
    response = served.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log(1)"
    assert "immutable" in response.headers["cache-control"]


def test_public_file_is_not_cached(served):
    response = served.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/conversas/abc", "/conversas/abc?x=1", "/projetos/3/git", "/assets/nao-existe.js"])
def test_vue_routes_fall_back_to_index(served, path):
    response = served.get(path)
    assert response.status_code == 200
    assert "Cláudio Maestro" in response.text


def test_unknown_api_route_is_json_404(served):
    response = served.get("/api/nao-existe", headers={"x-maestro": "1"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_api_keeps_working(served):
    assert served.get("/api/health", headers={"x-maestro": "1"}).json() == {"status": "ok"}


def test_api_still_requires_its_header(served):
    assert served.get("/api/health").status_code == 403


@pytest.mark.parametrize("path", ["/%2e%2e/secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/..%2fsecret.txt"])
def test_traversal_never_reaches_outside_dist(served, path):
    assert "segredo" not in served.get(path).text


def test_resolve_asset_refuses_outside_and_missing(dist: Path):
    root = dist.resolve()
    assert resolve_asset(root, "../secret.txt") is None
    assert resolve_asset(root, "") is None
    assert resolve_asset(root, "assets") is None  # a folder is not a file
    assert resolve_asset(root, "nada.js") is None
    assert resolve_asset(root, "favicon.svg") == root / "favicon.svg"


@pytest.mark.parametrize("path", ["\x00", "assets/\x00x", "a" * 5000])
def test_resolve_asset_survives_invalid_paths(dist: Path, path: str):
    assert resolve_asset(dist.resolve(), path) is None


@pytest.mark.parametrize("path", ["/%00", "/assets/%00", "/" + "a" * 5000])
def test_invalid_paths_never_cause_a_server_error(served, path):
    response = served.get(path)
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "Cláudio Maestro" in response.text


def test_symlink_to_outside_is_not_served(served, dist: Path, tmp_path: Path):
    (dist / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert "segredo" not in served.get("/link.txt").text


def test_host_check_applies_to_the_page(dist: Path):
    with TestClient(create_app(frontend_dir=dist), base_url="http://evil.com:6660") as client:
        assert client.get("/").status_code == 400


def test_dev_mode_serves_no_page(client):
    assert client.get("/").status_code == 404
