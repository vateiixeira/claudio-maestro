import asyncio
import os
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from claudio_maestro.app import create_app
from claudio_maestro.security import (
    HostOriginMiddleware,
    PathNotAllowedError,
    is_within,
    resolve_within,
)

APP_ORIGIN = "http://localhost:6600"
MAESTRO = {"x-maestro": "1"}
VALID_HOSTS = [
    "http://localhost:6600",
    "http://localhost:6660",
    "http://127.0.0.1:6600",
    "http://127.0.0.1:6660",
]
INVALID_HOSTS = [
    "http://evil.com",
    "http://evil.com:6660",
    "http://localhost",
    "http://localhost:8080",
    "http://127.0.0.1:6601",
    "http://0.0.0.0:6660",
    "http://localhost.evil.com:6660",
]


def ws_app() -> FastAPI:
    """Minimal app with the middleware and a WebSocket route that accepts."""
    app = FastAPI()
    app.add_middleware(HostOriginMiddleware)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    @app.post("/echo")
    def echo():
        return {"ok": True}

    return app


# Host, HTTP


@pytest.mark.parametrize("base_url", VALID_HOSTS)
def test_valid_host_accepted(base_url):
    with TestClient(create_app(), base_url=base_url, headers=MAESTRO) as client:
        assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("base_url", INVALID_HOSTS)
def test_invalid_host_rejected_http(base_url):
    with TestClient(create_app(), base_url=base_url, headers=MAESTRO) as client:
        response = client.get("/api/health")
        assert response.status_code == 400


def test_missing_host_rejected_http():
    # TestClient always sends Host, so call the middleware directly.
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/echo",
        "raw_path": b"/echo",
        "query_string": b"",
        "headers": [],
        "http_version": "1.1",
        "scheme": "http",
        "server": ("127.0.0.1", 6660),
        "client": ("127.0.0.1", 1234),
        "root_path": "",
    }
    asyncio.run(HostOriginMiddleware(ws_app())(scope, receive, send))
    assert sent[0]["status"] == 400


# Host, WebSocket


def ws_url(base_url: str) -> str:
    # TestClient ignores base_url for WebSockets, so pass the full URL.
    return base_url.replace("http://", "ws://", 1) + "/ws"


@pytest.mark.parametrize("base_url", VALID_HOSTS)
def test_valid_host_accepted_websocket(base_url):
    client = TestClient(ws_app())
    with client.websocket_connect(ws_url(base_url), headers={"origin": APP_ORIGIN}) as ws:
        assert ws.receive_text() == "hello"


@pytest.mark.parametrize("base_url", INVALID_HOSTS)
def test_invalid_host_rejected_websocket(base_url):
    client = TestClient(ws_app())
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(ws_url(base_url), headers={"origin": APP_ORIGIN}) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


# Origin, HTTP


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_state_changing_without_origin_rejected(method):
    client = TestClient(ws_app(), base_url="http://127.0.0.1:6660")
    response = client.request(method.upper(), "/echo")
    assert response.status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.com",
        "http://localhost:6660",
        "http://localhost:3000",
        "https://localhost:6600",
        "null",
        "http://localhost:6600.evil.com",
    ],
)
def test_post_with_foreign_origin_rejected(origin):
    client = TestClient(ws_app(), base_url="http://127.0.0.1:6660")
    response = client.post("/echo", headers={"origin": origin})
    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:6600", "http://127.0.0.1:6600"])
def test_post_with_app_origin_accepted(origin):
    client = TestClient(ws_app(), base_url="http://127.0.0.1:6660")
    response = client.post("/echo", headers={"origin": origin})
    assert response.status_code == 200


def test_get_without_origin_accepted():
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=MAESTRO) as client:
        assert client.get("/api/health").status_code == 200


def test_get_with_foreign_origin_rejected():
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=MAESTRO) as client:
        response = client.get("/api/health", headers={"origin": "http://evil.com"})
        assert response.status_code == 403


def test_no_cors_headers():
    with TestClient(create_app(), base_url="http://127.0.0.1:6660", headers=MAESTRO) as client:
        response = client.get("/api/health", headers={"origin": APP_ORIGIN})
        assert "access-control-allow-origin" not in response.headers


# Origin, WebSocket


BACKEND_WS = "ws://127.0.0.1:6660/ws"


@pytest.mark.parametrize("origin", ["http://localhost:6600", "http://127.0.0.1:6600"])
def test_websocket_with_app_origin_accepted(origin):
    client = TestClient(ws_app())
    with client.websocket_connect(BACKEND_WS, headers={"origin": origin}) as ws:
        assert ws.receive_text() == "hello"


def test_websocket_without_origin_rejected():
    client = TestClient(ws_app())
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(BACKEND_WS) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


@pytest.mark.parametrize("origin", ["http://evil.com", "http://localhost:6660", "null"])
def test_websocket_with_foreign_origin_rejected(origin):
    client = TestClient(ws_app())
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(BACKEND_WS, headers={"origin": origin}) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


# Path validation


def test_resolve_within_accepts_inside(tmp_path: Path):
    root = tmp_path / "root"
    (root / "a b" / "ção").mkdir(parents=True)
    resolved = resolve_within(root / "a b" / "ção", [root])
    assert resolved == (root / "a b" / "ção").resolve()


def test_resolve_within_accepts_root_itself(tmp_path: Path):
    assert resolve_within(tmp_path, [tmp_path]) == tmp_path.resolve()


def test_resolve_within_rejects_outside(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathNotAllowedError):
        resolve_within(tmp_path, [root])


def test_resolve_within_rejects_dotdot(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathNotAllowedError):
        resolve_within(str(root) + "/../", [root])


def test_resolve_within_rejects_sibling_with_same_prefix(tmp_path: Path):
    root = tmp_path / "root"
    sibling = tmp_path / "root-evil"
    root.mkdir()
    sibling.mkdir()
    with pytest.raises(PathNotAllowedError):
        resolve_within(sibling, [root])


def test_resolve_within_rejects_symlink_to_outside(tmp_path: Path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    os.symlink(outside, root / "link")
    with pytest.raises(PathNotAllowedError):
        resolve_within(root / "link", [root])
    with pytest.raises(PathNotAllowedError):
        resolve_within(root / "link" / "not-yet-created.txt", [root])


def test_resolve_within_rejects_relative_path(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_within("relative/path", [tmp_path])


def test_resolve_within_relative_to_base(tmp_path: Path):
    (tmp_path / "src").mkdir()
    assert resolve_within("src", [tmp_path], base=tmp_path) == (tmp_path / "src").resolve()
    with pytest.raises(PathNotAllowedError):
        resolve_within("../..", [tmp_path], base=tmp_path)


def test_resolve_within_rejects_null_byte(tmp_path: Path):
    with pytest.raises(PathNotAllowedError):
        resolve_within(str(tmp_path) + "/a\x00b", [tmp_path])


def test_resolve_within_multiple_roots(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert resolve_within(b, [a, b]) == b.resolve()


def test_is_within(tmp_path: Path):
    assert is_within(tmp_path / "x", tmp_path)
    assert not is_within(tmp_path.parent, tmp_path)


# Custom header on /api


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "OPTIONS"])
def test_api_without_custom_header_rejected(method):
    with TestClient(create_app(), base_url="http://127.0.0.1:6660") as client:
        response = client.request(method, "/api/fs/dirs", headers={"origin": APP_ORIGIN})
        assert response.status_code == 403


def test_api_get_with_custom_header_accepted():
    with TestClient(create_app(), base_url="http://127.0.0.1:6660") as client:
        assert client.get("/api/health", headers=MAESTRO).status_code == 200
        assert client.get("/api/health").status_code == 403
        assert client.get("/api/health", headers={"x-maestro": "0"}).status_code == 403
