import asyncio
import contextlib
import json
import os
import signal
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from claudio_maestro.agentd import PROTOCOL, peer
from claudio_maestro.agentd.paths import lock_path, socket_path
from claudio_maestro.agentd.server import Agentd

FAKE_CLI = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]


class Conn:
    """Minimal protocol client for tests (the real one is Task 3)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer, self.req = reader, writer, 0
        self.events: list[dict] = []

    @classmethod
    async def open(cls, path: Path) -> "Conn":
        reader, writer = await asyncio.open_unix_connection(str(path), limit=256 * 1024 * 1024)
        return cls(reader, writer)

    async def call(self, op: str, **args) -> dict:
        self.req += 1
        req = self.req
        self.writer.write((json.dumps({"op": op, "req": req, **args}) + "\n").encode())
        await self.writer.drain()
        while True:
            msg = await self._next()
            if msg.get("req") == req:
                return msg
            self.events.append(msg)

    async def event(self, timeout: float = 5) -> dict:
        if self.events:
            return self.events.pop(0)
        return await asyncio.wait_for(self._next(), timeout)

    async def _next(self) -> dict:
        line = await self.reader.readline()
        assert line, "agentd closed the connection"
        return json.loads(line)

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()


@pytest.fixture
async def agentd(tmp_path):
    server = Agentd(tmp_path, idle_exit=60, orphan_timeout=60)
    task = asyncio.create_task(server.serve())
    await asyncio.wait_for(server.ready.wait(), 5)
    yield server
    await server.stop()
    await asyncio.wait_for(task, 10)


async def spawn(conn: Conn, tmp_path: Path, session_id: str = "s1") -> str:
    reply = await conn.call("spawn", session_id=session_id, cmd=FAKE_CLI, cwd=str(tmp_path),
                            env=dict(os.environ))
    assert reply["ok"], reply
    return reply["id"]


def user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text},
                       "parent_tool_use_id": None, "session_id": "s1"}) + "\n"


async def lines_until(conn: Conn, predicate) -> list[dict]:
    seen = []
    while True:
        ev = await conn.event()
        if ev["ev"] == "line":
            msg = json.loads(ev["line"])
            seen.append({"pos": ev["pos"], **msg})
            if predicate(msg):
                return seen


@pytest.mark.anyio
async def test_hello_checks_protocol(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    assert (await conn.call("hello", protocol=PROTOCOL))["ok"]
    bad = await conn.call("hello", protocol=PROTOCOL + 1)
    assert bad == {"req": 2, "ok": False, "error": "protocol"}
    await conn.close()


@pytest.mark.anyio
async def test_socket_and_dir_permissions(agentd, tmp_path):
    path = socket_path(tmp_path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


@pytest.mark.anyio
async def test_spawn_write_subscribe_live_and_replay(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    assert (await conn.call("subscribe", id=child, **{"from": 0}))["ok"]
    await conn.call("write", id=child, data=user("oi"))
    seen = await lines_until(conn, lambda m: m["type"] == "result")
    assert [m["type"] for m in seen] == ["system", "assistant", "result"]
    assert [m["pos"] for m in seen] == [0, 1, 2]
    # A second connection replays from any position.
    other = await Conn.open(socket_path(tmp_path))
    await other.call("subscribe", id=child, **{"from": 1})
    replay = await lines_until(other, lambda m: m["type"] == "result")
    assert [m["pos"] for m in replay] == [1, 2]
    await conn.close()
    await other.close()


@pytest.mark.anyio
async def test_ack_drops_older_lines(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("oi"))
    await lines_until(conn, lambda m: m["type"] == "result")
    await conn.call("ack", id=child, pos=2)
    other = await Conn.open(socket_path(tmp_path))
    await other.call("subscribe", id=child, **{"from": 0})
    first = await other.event()
    assert first == {"ev": "gap", "id": child, "from": 2}
    assert (await other.event())["pos"] == 2
    listed = (await conn.call("list"))["children"][0]
    assert listed["ack"] == 2 and listed["next_pos"] == 3 and listed["session_id"] == "s1"
    await conn.close()
    await other.close()


@pytest.mark.anyio
async def test_pending_cleared_only_by_written_response(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("ask"))
    seen = await lines_until(conn, lambda m: m["type"] == "control_request")
    request = seen[-1]
    # Acked past the request: it is still pending.
    await conn.call("ack", id=child, pos=request["pos"] + 1)
    pending = (await conn.call("pending", id=child))["lines"]
    assert [json.loads(line)["request_id"] for line in pending] == [request["request_id"]]
    response = {"type": "control_response", "response": {
        "subtype": "success", "request_id": request["request_id"],
        "response": {"behavior": "allow", "updatedInput": {"command": "echo hi"}}}}
    await conn.call("write", id=child, data=json.dumps(response) + "\n")
    await lines_until(conn, lambda m: m["type"] == "result")
    assert (await conn.call("pending", id=child))["lines"] == []
    await conn.close()


@pytest.mark.anyio
async def test_initialize_response_is_kept(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    init = {"type": "control_request", "request_id": "req_1",
            "request": {"subtype": "initialize", "hooks": None}}
    await conn.call("write", id=child, data=json.dumps(init) + "\n")
    await lines_until(conn, lambda m: m["type"] == "control_response")
    listed = (await conn.call("list"))["children"][0]
    assert listed["init"]["models"] == [{"value": "fake"}]
    await conn.close()


@pytest.mark.anyio
async def test_exit_reports_code_and_stderr(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("exit:3"))
    while (ev := await conn.event())["ev"] != "exit":
        pass
    assert ev["code"] == 3 and ev["stderr"] == ["fake failure"]
    assert (await conn.call("list"))["children"][0]["exit_code"] == 3
    # Subscribing after the exit replays and ends with the exit event.
    other = await Conn.open(socket_path(tmp_path))
    await other.call("subscribe", id=child, **{"from": 0})
    while (ev := await other.event())["ev"] != "exit":
        pass
    await conn.close()
    await other.close()


@pytest.mark.anyio
async def test_kill_removes_child(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    pid = (await conn.call("list"))["children"][0]["pid"]
    assert (await conn.call("kill", id=child))["ok"]
    for _ in range(100):
        if not (await conn.call("list"))["children"]:
            break
        await asyncio.sleep(0.05)
    assert (await conn.call("list"))["children"] == []
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    await conn.close()


@pytest.mark.anyio
async def test_large_lines_pass_whole(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    big = "x" * (5 * 1024 * 1024)
    await conn.call("write", id=child, data=user(big))
    seen = await lines_until(conn, lambda m: m["type"] == "result")
    echoed = next(m for m in seen if m["type"] == "assistant")
    assert echoed["message"]["content"][0]["text"] == f"eco: {big}"
    await conn.close()


@pytest.mark.anyio
async def test_log_limit_produces_gap(tmp_path, monkeypatch):
    monkeypatch.setattr("claudio_maestro.agentd.server.LOG_LIMIT_BYTES", 2000)
    server = Agentd(tmp_path, idle_exit=60, orphan_timeout=60)
    task = asyncio.create_task(server.serve())
    await server.ready.wait()
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("stream:40"))
    await lines_until(conn, lambda m: m["type"] == "result")
    other = await Conn.open(socket_path(tmp_path))
    await other.call("subscribe", id=child, **{"from": 0})
    assert (await other.event())["ev"] == "gap"
    await conn.close()
    await other.close()
    await server.stop()
    await task


@pytest.mark.anyio
async def test_other_uid_is_refused(agentd, tmp_path, monkeypatch):
    monkeypatch.setattr(peer, "peer_uid", lambda sock: os.getuid() + 1)
    reader, writer = await asyncio.open_unix_connection(str(socket_path(tmp_path)))
    assert await asyncio.wait_for(reader.read(), 5) == b""  # closed without a word
    writer.close()


def test_peer_uid_is_ours():
    a, b = socket.socketpair(socket.AF_UNIX)
    try:
        assert peer.peer_uid(a) == os.getuid()
    finally:
        a.close()
        b.close()


@pytest.mark.anyio
async def test_idle_exit_without_children_or_clients(tmp_path):
    server = Agentd(tmp_path, idle_exit=0.3, orphan_timeout=60)
    task = asyncio.create_task(server.serve())
    await asyncio.wait_for(task, 5)
    assert not socket_path(tmp_path).exists()


@pytest.mark.anyio
async def test_orphan_timeout_kills_children_and_exits(tmp_path):
    server = Agentd(tmp_path, idle_exit=60, orphan_timeout=0.5)
    task = asyncio.create_task(server.serve())
    await server.ready.wait()
    conn = await Conn.open(socket_path(tmp_path))
    await spawn(conn, tmp_path)
    pid = (await conn.call("list"))["children"][0]["pid"]
    await conn.close()
    await asyncio.wait_for(task, 10)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.anyio
async def test_second_agentd_exits_when_locked(tmp_path):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "claudio_maestro.agentd", "--data-dir", str(tmp_path),
        "--idle-exit", "30")
    for _ in range(60):
        if socket_path(tmp_path).exists():
            break
        await asyncio.sleep(0.05)
    second = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "claudio_maestro.agentd", "--data-dir", str(tmp_path))
    assert await asyncio.wait_for(second.wait(), 5) == 0
    conn = await Conn.open(socket_path(tmp_path))
    await conn.call("shutdown")
    await conn.close()
    assert await asyncio.wait_for(proc.wait(), 10) == 0


def test_long_data_dir_uses_short_socket(tmp_path, monkeypatch):
    # pytest's tmp_path is itself long; the runtime dir must be short to fit.
    with tempfile.TemporaryDirectory() as run:
        monkeypatch.setenv("XDG_RUNTIME_DIR", run)
        deep = tmp_path / ("d" * 120)
        path = socket_path(deep)
        assert len(str(path).encode()) <= 100
        assert path.parent == Path(run) / "claudio-maestro"
    assert lock_path(deep) == deep / "agentd-v1.lock"


async def wait_for_exit(conn: Conn, timeout: float = 8) -> dict:
    async def loop() -> dict:
        while (ev := await conn.event(timeout))["ev"] != "exit":
            pass
        return ev

    return await asyncio.wait_for(loop(), timeout)


@pytest.mark.anyio
async def test_exit_does_not_wait_for_a_grandchild_holding_the_pipes(agentd, tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    cmd = ["sh", "-c", f"sleep 30 & echo $! > {pidfile}; exec sleep 0.2"]
    conn = await Conn.open(socket_path(tmp_path))
    try:
        reply = await conn.call("spawn", session_id="s1", cmd=cmd, cwd=str(tmp_path),
                                env=dict(os.environ))
        child = reply["id"]
        await conn.call("subscribe", id=child, **{"from": 0})
        ev = await wait_for_exit(conn)
        assert ev["code"] == 0
        assert (await conn.call("list"))["children"][0]["exit_code"] == 0
        assert (await conn.call("kill", id=child))["ok"]
        for _ in range(100):
            if not (await conn.call("list"))["children"]:
                break
            await asyncio.sleep(0.05)
        assert (await conn.call("list"))["children"] == []
    finally:
        with contextlib.suppress(Exception):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        await conn.close()


@pytest.mark.anyio
async def test_stop_finishes_with_a_grandchild_holding_the_pipes(tmp_path, monkeypatch):
    monkeypatch.setattr("claudio_maestro.agentd.server.KILL_GRACE", 0.5)
    pidfile = tmp_path / "grandchild.pid"
    server = Agentd(tmp_path, idle_exit=60, orphan_timeout=60)
    task = asyncio.create_task(server.serve())
    await asyncio.wait_for(server.ready.wait(), 5)
    conn = await Conn.open(socket_path(tmp_path))
    try:
        reply = await conn.call("spawn", session_id="s1", cwd=str(tmp_path), env=dict(os.environ),
                                cmd=["sh", "-c", f"sleep 30 & echo $! > {pidfile}; exec sleep 30"])
        assert reply["ok"]
        await asyncio.sleep(0.3)
        await server.stop()
        await asyncio.wait_for(task, 8)
        assert not socket_path(tmp_path).exists()
        # The lock was released: a new agentd can take it.
        again = Agentd(tmp_path, idle_exit=60, orphan_timeout=60)
        again._acquire_lock()
        os.close(again._lock_fd)
    finally:
        with contextlib.suppress(Exception):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
        await conn.close()


@pytest.mark.anyio
async def test_refused_response_keeps_the_request_pending(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("ask"))
    seen = await lines_until(conn, lambda m: m["type"] == "control_request")
    request = seen[-1]
    pid = (await conn.call("list"))["children"][0]["pid"]
    os.kill(pid, signal.SIGKILL)
    await wait_for_exit(conn)
    response = {"type": "control_response", "response": {
        "subtype": "success", "request_id": request["request_id"],
        "response": {"behavior": "allow", "updatedInput": {}}}}
    reply = await conn.call("write", id=child, data=json.dumps(response) + "\n")
    assert reply["ok"] is False
    pending = (await conn.call("pending", id=child))["lines"]
    assert [json.loads(line)["request_id"] for line in pending] == [request["request_id"]]
    await conn.close()


@pytest.mark.anyio
async def test_subscribe_requires_an_integer_from(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    assert (await conn.call("subscribe", id=child))["ok"] is False
    assert (await conn.call("subscribe", id=child, **{"from": "0"}))["ok"] is False
    assert (await conn.call("subscribe", id=child, **{"from": 0}))["ok"] is True
    await conn.close()


@pytest.mark.anyio
async def test_replay_skips_control_requests_already_answered(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("write", id=child, data=user("ask"))
    seen = await lines_until(conn, lambda m: m["type"] == "control_request")
    request = seen[-1]
    # Not answered yet: a late subscriber still gets the request.
    other = await Conn.open(socket_path(tmp_path))
    await other.call("subscribe", id=child, **{"from": 0})
    replay = await lines_until(other, lambda m: m["type"] == "control_request")
    assert replay[-1]["request_id"] == request["request_id"]
    await other.close()
    response = {"type": "control_response", "response": {
        "subtype": "success", "request_id": request["request_id"],
        "response": {"behavior": "allow", "updatedInput": {"command": "echo hi"}}}}
    await conn.call("write", id=child, data=json.dumps(response) + "\n")
    await lines_until(conn, lambda m: m["type"] == "result")
    # Answered: the replay keeps the other lines in order but not the request.
    late = await Conn.open(socket_path(tmp_path))
    await late.call("subscribe", id=child, **{"from": 0})
    replay = await lines_until(late, lambda m: m["type"] == "result")
    assert [m["type"] for m in replay] == ["system", "assistant", "assistant", "result"]
    assert [m["pos"] for m in replay] == [0, 1, 3, 4]
    await conn.close()
    await late.close()


async def spawn_cmd(conn: Conn, tmp_path: Path, cmd: list[str]) -> str:
    reply = await conn.call("spawn", session_id="s1", cmd=cmd, cwd=str(tmp_path),
                            env=dict(os.environ))
    assert reply["ok"], reply
    return reply["id"]


@pytest.mark.anyio
async def test_kill_closes_stdin_first_so_the_cli_exits_without_a_signal(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    await conn.call("subscribe", id=child, **{"from": 0})
    assert (await conn.call("kill", id=child))["ok"]
    ev = await wait_for_exit(conn)
    assert ev["code"] == 0  # a SIGTERM would have given -15
    await conn.close()


@pytest.mark.anyio
async def test_kill_sends_sigterm_when_stdin_eof_is_not_enough(agentd, tmp_path, monkeypatch):
    monkeypatch.setattr("claudio_maestro.agentd.server.KILL_GRACE", 0.3)
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn_cmd(conn, tmp_path, ["sh", "-c", "exec sleep 30"])
    await conn.call("subscribe", id=child, **{"from": 0})
    await conn.call("kill", id=child)
    assert (await wait_for_exit(conn))["code"] == -signal.SIGTERM
    await conn.close()


@pytest.mark.anyio
async def test_kill_escalates_to_sigkill_for_a_child_ignoring_sigterm_and_eof(
    agentd, tmp_path, monkeypatch
):
    monkeypatch.setattr("claudio_maestro.agentd.server.KILL_GRACE", 0.3)
    code = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(60)")
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn_cmd(conn, tmp_path, [sys.executable, "-c", code])
    await conn.call("subscribe", id=child, **{"from": 0})
    while (await conn.event())["ev"] != "line":  # the handler is installed
        pass
    await conn.call("kill", id=child)
    assert (await wait_for_exit(conn))["code"] == -signal.SIGKILL
    for _ in range(100):
        if not (await conn.call("list"))["children"]:
            break
        await asyncio.sleep(0.05)
    assert (await conn.call("list"))["children"] == []
    await conn.close()


@pytest.mark.anyio
async def test_kill_twice_is_harmless(agentd, tmp_path):
    conn = await Conn.open(socket_path(tmp_path))
    child = await spawn(conn, tmp_path)
    assert (await conn.call("kill", id=child))["ok"]
    reply = await conn.call("kill", id=child)
    assert reply["ok"] or reply["error"] == "unknown child"
    await conn.close()
