"""Terminal routes: WebSocket, play endpoint and the app life cycle (real bash, fake agent)."""

import os
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_sessions_api import (
    APP_ORIGIN,
    BACKEND_URL,
    factory,  # noqa: F401
    new_session,
)

from claudio_maestro.agent.fake import FakeAgentFactory, text_turn
from claudio_maestro.app import create_app

MISSING = "00000000-0000-0000-0000-000000000000"
SLOW = 15.0  # a real shell is slower than the fake agent


def ws_url(session_id: str) -> str:
    return f"ws://127.0.0.1:6660/ws/terminal/{session_id}"


def make_app(
    factory: FakeAgentFactory, home: Path, ports: tuple[int, ...] | None = None
) -> Any:
    home.mkdir(exist_ok=True)

    def history_exists(session_id: str, cwd: str) -> bool:
        return any(c.options.session_id == session_id and c.sent for c in factory.clients)

    # A temporary HOME keeps the user's ~/.bashrc out of the shell.
    return create_app(
        agent_factory=factory,
        history_exists=history_exists,
        terminal_env_overrides={"HOME": str(home)},
        ports=ports,
    )


@pytest.fixture
def api(factory: FakeAgentFactory, tmp_path: Path) -> Iterator[TestClient]:  # noqa: F811
    app = make_app(factory, tmp_path / "shellhome")
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as c:
        yield c


def connect_terminal(
    api: TestClient, session_id: str, origin: str = APP_ORIGIN, *, open_shell: bool = True
):
    """The WebSocket of the terminal; `open_shell=False` only attaches to an existing one."""
    url = ws_url(session_id) + ("?open=1" if open_shell else "")
    return api.websocket_connect(url, headers={"origin": origin})


def read_until(ws, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """First frame that satisfies `predicate`, failing after SLOW seconds."""
    deadline = time.monotonic() + SLOW
    while time.monotonic() < deadline:
        frame = receive_slow(ws)
        if predicate(frame):
            return frame
    raise AssertionError("o quadro esperado não chegou")


def receive_slow(ws) -> dict[str, Any]:
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutureTimeout

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(ws.receive_json).result(timeout=SLOW)
    except FutureTimeout:
        raise AssertionError(f"nenhum quadro em {SLOW}s") from None
    finally:
        executor.shutdown(wait=False)


def has_output(text: str) -> Callable[[dict[str, Any]], bool]:
    return lambda frame: frame["type"] == "output" and text in frame["data"]


def wait_for(predicate: Callable[[], bool], timeout: float = SLOW) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("a condição não ficou verdadeira")
        time.sleep(0.02)


def wait_prompt(ws) -> None:
    """The first frame is the replay; the shell is usable after it printed something."""
    first = receive_slow(ws)
    assert first["type"] == "replay"


def get_terminal(api: TestClient, session_id: str):
    return api.app.state.terminals.get(session_id)


# WebSocket ------------------------------------------------------------------


def test_terminal_ws_streams_replay_and_echoes_input(api, home):
    session = new_session(api, home)

    with connect_terminal(api, session["session_id"]) as ws:
        first = receive_slow(ws)
        assert first["type"] == "replay"
        assert isinstance(first["data"], str)
        assert first["cols"] == 120
        assert first["rows"] == 30
        ws.send_json({"type": "input", "data": "echo marca\r"})
        read_until(ws, has_output("marca"))


def test_terminal_ws_resize_changes_size_and_ignores_bad_frames(api, home):
    session = new_session(api, home)

    with connect_terminal(api, session["session_id"]) as ws:
        wait_prompt(ws)
        ws.send_text("not json")
        ws.send_json({"type": "unknown"})
        ws.send_json({"type": "input", "data": 5})
        ws.send_json({"type": "resize", "cols": 1, "rows": 10})
        ws.send_json({"type": "resize", "cols": 501, "rows": 10})
        ws.send_json({"type": "resize", "cols": 80, "rows": 0})
        ws.send_json({"type": "resize", "cols": 80, "rows": 201})
        ws.send_json({"type": "resize", "cols": "80", "rows": 24})
        ws.send_json({"type": "resize", "cols": True, "rows": 24})
        ws.send_json([1, 2])
        ws.send_bytes(b"\x00\x01")
        ws.send_json({"type": "resize", "cols": 100, "rows": 40})
        # The connection survived all of that and still reaches the shell.
        ws.send_json({"type": "input", "data": "echo vivo\r"})
        read_until(ws, has_output("vivo"))
        terminal = get_terminal(api, session["session_id"])
        assert (terminal.cols, terminal.rows) == (100, 40)


def test_terminal_ws_survives_a_lone_surrogate(api, home):
    session = new_session(api, home)

    with connect_terminal(api, session["session_id"]) as ws:
        wait_prompt(ws)
        # Valid JSON, but not encodable in UTF-8.
        ws.send_text('{"type": "input", "data": "\\ud800"}')
        ws.send_json({"type": "input", "data": "echo marca\r"})
        read_until(ws, has_output("marca"))


def test_terminal_ws_sends_exit_when_the_terminal_closed_before_subscribing(api, home):
    session = new_session(api, home)
    sid = session["session_id"]
    manager = api.app.state.terminals
    original_open = manager.open
    dead: list[Any] = []

    async def open_then_close(session_id, cwd):
        # Stands for a terminal that closes while the handshake is being accepted.
        terminal = await original_open(session_id, cwd)
        await manager.kill(session_id, interrupted=True)
        dead.append(terminal)
        return terminal

    manager.open = open_then_close
    try:
        with connect_terminal(api, sid) as ws:
            assert receive_slow(ws)["type"] == "replay"
            assert receive_slow(ws) == {"type": "exit"}
    finally:
        manager.open = original_open
    assert dead[0].closed


def test_terminal_ws_requires_app_origin(api, home):
    session = new_session(api, home)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with connect_terminal(api, session["session_id"], origin="http://evil.example") as ws:
            ws.receive_json()

    assert exc_info.value.code == 1008
    assert get_terminal(api, session["session_id"]) is None


def test_ws_refuses_unknown_session_and_missing_folder(api, home):
    with pytest.raises(WebSocketDisconnect) as unknown:
        with connect_terminal(api, MISSING) as ws:
            ws.receive_json()
    assert unknown.value.code == 4404
    assert get_terminal(api, MISSING) is None

    session = new_session(api, home)
    shutil.rmtree(home / "app")
    with pytest.raises(WebSocketDisconnect) as gone:
        with connect_terminal(api, session["session_id"]) as ws:
            ws.receive_json()
    assert gone.value.code == 4409
    assert get_terminal(api, session["session_id"]) is None


def set_session_cwd(api: TestClient, session_id: str, cwd: Path) -> None:
    with closing(sqlite3.connect(api.app.state.settings.db_path)) as conn, conn:
        conn.execute("UPDATE sessions SET cwd = ? WHERE session_id = ?", (str(cwd), session_id))


@pytest.mark.parametrize("via_link", [False, True])
def test_ws_refuses_folder_outside_the_projects(api, home, tmp_path, via_link):
    session = new_session(api, home)
    outside = tmp_path / "outside"
    outside.mkdir()
    cwd = outside
    if via_link:
        # A link inside the project that points out of it is outside too.
        cwd = home / "app" / "link"
        cwd.symlink_to(outside)
    set_session_cwd(api, session["session_id"], cwd)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with connect_terminal(api, session["session_id"]) as ws:
            ws.receive_json()

    assert exc_info.value.code == 4409
    assert get_terminal(api, session["session_id"]) is None
    response = api.post(run_url(session["session_id"]), json={"command": "echo oi"})
    assert response.status_code == 409
    assert get_terminal(api, session["session_id"]) is None


def test_ws_refuses_when_the_shell_does_not_start(api, home, monkeypatch):
    session = new_session(api, home)
    from claudio_maestro.terminal import TerminalStartError

    async def fail(session_id, cwd):
        raise TerminalStartError("boom")

    monkeypatch.setattr(api.app.state.terminals, "open", fail)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with connect_terminal(api, session["session_id"]) as ws:
            ws.receive_json()

    assert exc_info.value.code == 4500


def test_ws_without_open_does_not_create_a_shell(api, home):
    session = new_session(api, home)
    sid = session["session_id"]

    for url in (ws_url(sid), ws_url(sid) + "?open=0", ws_url(sid) + "?open=true"):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with api.websocket_connect(url, headers={"origin": APP_ORIGIN}) as ws:
                ws.receive_json()
        assert exc_info.value.code == 4410
        assert get_terminal(api, sid) is None


def test_ws_without_open_keeps_the_other_refusals_first(api, home):
    with pytest.raises(WebSocketDisconnect) as unknown:
        with connect_terminal(api, MISSING, open_shell=False) as ws:
            ws.receive_json()
    assert unknown.value.code == 4404

    session = new_session(api, home)
    shutil.rmtree(home / "app")
    with pytest.raises(WebSocketDisconnect) as gone:
        with connect_terminal(api, session["session_id"], open_shell=False) as ws:
            ws.receive_json()
    assert gone.value.code == 4409


def test_ws_without_open_attaches_to_a_live_terminal(api, home):
    session = new_session(api, home)
    sid = session["session_id"]
    with connect_terminal(api, sid) as opener:
        wait_prompt(opener)
        opener.send_json({"type": "input", "data": "echo guardado\r"})
        read_until(opener, has_output("guardado"))
        terminal = get_terminal(api, sid)

        with connect_terminal(api, sid, open_shell=False) as ws:
            replay = receive_slow(ws)
            assert replay["type"] == "replay"
            assert "guardado" in replay["data"]
            ws.send_json({"type": "input", "data": "echo outro\r"})
            read_until(ws, has_output("outro"))
    assert get_terminal(api, sid) is terminal


def test_new_terminal_replays_no_runs(api, home):
    session = new_session(api, home)
    with connect_terminal(api, session["session_id"]) as ws:
        assert receive_slow(ws)["runs"] == []


def test_replay_brings_the_finished_and_the_running_runs(api, home):
    session = new_session(api, home)
    sid = session["session_id"]
    first = api.post(run_url(sid), json={"command": "echo feito"}).json()["run_id"]
    wait_for(lambda: [r["state"] for r in get_terminal(api, sid).runs()] == ["sent"])
    second = api.post(run_url(sid), json={"command": "sleep 20"}).json()["run_id"]
    wait_for(lambda: get_terminal(api, sid).busy)

    # A new connection, without `open=1`, sees both.
    with connect_terminal(api, sid, open_shell=False) as ws:
        replay = receive_slow(ws)
    assert replay["runs"] == [
        {"run_id": first, "state": "sent", "exit_code": 0},
        {"run_id": second, "state": "running", "exit_code": None},
    ]


def test_two_sockets_share_terminal_and_closing_one_keeps_it(api, home):
    session = new_session(api, home)

    with connect_terminal(api, session["session_id"]) as first:
        wait_prompt(first)
        with connect_terminal(api, session["session_id"]) as second:
            wait_prompt(second)
            first.send_json({"type": "input", "data": "echo marca\r"})
            read_until(first, has_output("marca"))
            read_until(second, has_output("marca"))
        # The second socket is gone; the terminal and the first socket go on.
        assert get_terminal(api, session["session_id"]) is not None
        first.send_json({"type": "input", "data": "echo depois\r"})
        read_until(first, has_output("depois"))

    # Disconnecting every socket does not close the terminal either.
    terminal = get_terminal(api, session["session_id"])
    assert terminal is not None
    assert not terminal.closed


def test_reconnect_gets_the_replay(api, home):
    session = new_session(api, home)
    with connect_terminal(api, session["session_id"]) as ws:
        wait_prompt(ws)
        ws.send_json({"type": "input", "data": "echo guardado\r"})
        read_until(ws, has_output("guardado"))

    with connect_terminal(api, session["session_id"]) as ws:
        replay = receive_slow(ws)
        assert replay["type"] == "replay"
        assert "guardado" in replay["data"]


# Play endpoint ---------------------------------------------------------------


def run_url(session_id: str) -> str:
    return f"/api/sessions/{session_id}/terminal/run"


def terminal_runs(api: TestClient, session_id: str) -> list[dict[str, Any]]:
    items = api.get(f"/api/sessions/{session_id}").json()["items"]
    return [i["terminal_run"] for i in items if i["type"] == "user" and i.get("terminal_run")]


def test_run_endpoint_sends_message_to_session(api, home, factory):
    factory.script = lambda content: text_turn("ok")
    session = new_session(api, home)

    response = api.post(run_url(session["session_id"]), json={"command": "echo oi"})

    assert response.status_code == 202
    assert isinstance(response.json()["run_id"], str)
    wait_for(lambda: any(c.sent for c in factory.clients))
    sent = [text for c in factory.clients for text in c.sent]
    assert sent[0].startswith("<bash-input>echo oi</bash-input>")
    wait_for(lambda: terminal_runs(api, session["session_id"]))
    assert terminal_runs(api, session["session_id"])[0]["output"] == "oi"


def test_run_endpoint_busy_is_409(api, home):
    session = new_session(api, home)
    first = api.post(run_url(session["session_id"]), json={"command": "sleep 2"})
    assert first.status_code == 202

    second = api.post(run_url(session["session_id"]), json={"command": "echo oi"})

    assert second.status_code == 409
    assert second.json() == {"detail": "O terminal está ocupado."}


def test_run_endpoint_unknown_session_is_404(api):
    response = api.post(run_url(MISSING), json={"command": "echo oi"})

    assert response.status_code == 404


def test_run_endpoint_missing_folder_is_409(api, home):
    session = new_session(api, home)
    shutil.rmtree(home / "app")

    response = api.post(run_url(session["session_id"]), json={"command": "echo oi"})

    assert response.status_code == 409
    assert response.json() == {"detail": "A pasta da sessão não existe mais."}
    assert get_terminal(api, session["session_id"]) is None


def test_run_endpoint_start_failure_is_503(api, home, monkeypatch):
    session = new_session(api, home)
    from claudio_maestro.terminal import TerminalStartError

    async def fail(session_id, cwd, command):
        raise TerminalStartError("boom")

    monkeypatch.setattr(api.app.state.terminals, "run", fail)

    response = api.post(run_url(session["session_id"]), json={"command": "echo oi"})

    assert response.status_code == 503
    assert response.json() == {"detail": "O terminal não abriu."}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"command": ""},
        {"command": "   \n"},
        {"command": "\x1b\x15"},
        {"command": " \x00\x1b\x7f\x85\r\n "},
        {"command": "x" * 20_001},
        {"command": "echo oi", "extra": 1},
        {"command": 5},
    ],
)
def test_run_endpoint_validates_the_body(api, home, body):
    session = new_session(api, home)

    response = api.post(run_url(session["session_id"]), json=body)

    assert response.status_code == 422
    assert get_terminal(api, session["session_id"]) is None


def test_run_endpoint_only_control_characters_is_refused_with_the_portuguese_message(api, home):
    session = new_session(api, home)

    response = api.post(run_url(session["session_id"]), json={"command": "\x1b\x15"})

    assert response.status_code == 422
    assert "O comando está vazio." in response.text
    assert get_terminal(api, session["session_id"]) is None


def test_run_requires_x_maestro(api, home):
    session = new_session(api, home)

    response = api.post(
        run_url(session["session_id"]), json={"command": "echo oi"}, headers={"x-maestro": ""}
    )

    assert response.status_code == 403
    assert get_terminal(api, session["session_id"]) is None


# Closing -----------------------------------------------------------------------


def test_delete_terminal_kills_it(api, home):
    session = new_session(api, home)
    assert api.post(run_url(session["session_id"]), json={"command": "sleep 30"}).status_code == 202
    terminal = get_terminal(api, session["session_id"])
    assert terminal is not None
    pid = terminal.pid

    response = api.delete(f"/api/sessions/{session['session_id']}/terminal")

    assert response.status_code == 204
    assert get_terminal(api, session["session_id"]) is None
    assert not process_alive(pid)


def test_delete_terminal_without_one_is_204_and_unknown_session_is_404(api, home):
    session = new_session(api, home)

    assert api.delete(f"/api/sessions/{session['session_id']}/terminal").status_code == 204
    assert api.delete(f"/api/sessions/{MISSING}/terminal").status_code == 404


def test_finish_session_kills_terminal_without_sending(api, home, factory):
    session = new_session(api, home)
    assert api.post(run_url(session["session_id"]), json={"command": "sleep 30"}).status_code == 202
    terminal = get_terminal(api, session["session_id"])
    assert terminal is not None
    pid = terminal.pid

    response = api.patch(f"/api/sessions/{session['session_id']}", json={"finished": True})

    assert response.status_code == 200
    assert get_terminal(api, session["session_id"]) is None
    assert not process_alive(pid)
    time.sleep(0.2)
    assert not any(c.sent for c in factory.clients)


def test_other_patches_keep_the_terminal(api, home):
    session = new_session(api, home)
    assert api.post(run_url(session["session_id"]), json={"command": "sleep 30"}).status_code == 202

    api.patch(f"/api/sessions/{session['session_id']}", json={"title": "Outro"})
    api.patch(f"/api/sessions/{session['session_id']}", json={"finished": False})

    assert get_terminal(api, session["session_id"]) is not None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_shutdown_closes_terminals(factory, home, tmp_path):
    app = make_app(factory, tmp_path / "shellhome")
    with TestClient(
        app, base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-maestro": "1"}
    ) as client:
        session = new_session(client, home)
        assert client.post(run_url(session["session_id"]), json={"command": "sleep 30"}).status_code == 202
        pid = get_terminal(client, session["session_id"]).pid
        assert process_alive(pid)

    assert not process_alive(pid)



# Real server ---------------------------------------------------------------------


def test_refusals_reach_the_browser_as_close_codes_under_uvicorn(factory, home, tmp_path):
    """Under uvicorn a close before the accept becomes an HTTP 403 (code 1006 in the browser),
    so the refusals accept first. `TestClient` cannot tell the two apart."""
    import asyncio
    import socket
    import threading

    import httpx
    import uvicorn
    from websockets.asyncio.client import connect

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Host and Origin of the app on this free port, never one of the real ports.
    app = make_app(factory, tmp_path / "shellhome", ports=(port, port))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + SLOW
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                pytest.fail("o servidor de teste não abriu a porta")
            time.sleep(0.02)
        origin = f"http://127.0.0.1:{port}"
        headers = {"origin": origin, "x-maestro": "1"}
        base = f"http://127.0.0.1:{port}"
        folder = home / "live"
        folder.mkdir()
        project = httpx.post(
            f"{base}/api/projects",
            json={"name": "live", "path": str(folder), "color": "#ff8800"},
            headers=headers,
        ).json()
        session = httpx.post(f"{base}/api/projects/{project['id']}/sessions", headers=headers).json()
        shutil.rmtree(folder)

        async def close_code(session_id: str) -> int:
            async with connect(
                f"ws://127.0.0.1:{port}/ws/terminal/{session_id}", origin=origin
            ) as ws:
                with pytest.raises(Exception) as exc_info:  # noqa: PT011
                    await asyncio.wait_for(ws.recv(), SLOW)
                assert ws.close_code is not None
                assert "ConnectionClosed" in type(exc_info.value).__name__
                return ws.close_code

        assert asyncio.run(close_code(MISSING)) == 4404
        assert asyncio.run(close_code(session["session_id"])) == 4409
        assert server.config.app.state.terminals.get(session["session_id"]) is None

        # With the folder back, but without a terminal and without `open=1`, the socket closes
        # with 4410 and opens no shell.
        folder.mkdir()
        assert asyncio.run(close_code(session["session_id"])) == 4410
        assert server.config.app.state.terminals.get(session["session_id"]) is None
    finally:
        server.should_exit = True
        thread.join(timeout=SLOW)
