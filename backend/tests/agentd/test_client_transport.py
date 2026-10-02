import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import CLIConnectionError, ProcessError
from claude_agent_sdk.types import StreamEvent

from claudio_maestro.agent.agentd_client import (
    AgentdChild,
    AgentdClient,
    AgentdUnavailable,
)
from claudio_maestro.agent.agentd_transport import AgentdConnectError, AgentdTransport
from claudio_maestro.agent.spawn import SpawnSpec
from claudio_maestro.agentd.paths import socket_path

FAKE_CLI = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]


def spec(tmp_path: Path) -> SpawnSpec:
    return SpawnSpec(cmd=FAKE_CLI, cwd=str(tmp_path), env=dict(os.environ))


@pytest.fixture
async def agentd(tmp_path):
    client = AgentdClient(tmp_path, idle_exit=5, orphan_timeout=5)
    await client.ensure_running()
    yield client
    for child in await client.list():
        await client.kill(child.id)
    await client.aclose()


def user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text},
                       "parent_tool_use_id": None, "session_id": "s"}) + "\n"


def initialize(req_id: str = "req_1") -> str:
    return json.dumps({"type": "control_request", "request_id": req_id,
                       "request": {"subtype": "initialize", "hooks": None}}) + "\n"


async def read_until(transport: AgentdTransport, kind: str) -> list[dict]:
    seen = []
    async for message in transport.read_messages():
        seen.append(message)
        if message.get("type") == kind:
            return seen
    return seen


@pytest.mark.anyio
async def test_ensure_running_starts_agentd_detached(tmp_path):
    client = AgentdClient(tmp_path, idle_exit=5, orphan_timeout=5)
    await client.ensure_running()
    assert client.connected and socket_path(tmp_path).exists()
    await client.aclose()


@pytest.mark.anyio
async def test_ensure_running_twice_starts_one_agentd(tmp_path):
    a = AgentdClient(tmp_path, idle_exit=5)
    b = AgentdClient(tmp_path, idle_exit=5)
    await asyncio.gather(a.ensure_running(), b.ensure_running())
    assert a.server_pid == b.server_pid
    await a.aclose()
    await b.aclose()


@pytest.mark.anyio
async def test_attach_only_client_does_not_start_agentd(tmp_path):
    client = AgentdClient(tmp_path, spawn_allowed=False)
    with pytest.raises(AgentdUnavailable):
        await client.ensure_running()


@pytest.mark.anyio
async def test_new_transport_spawns_and_streams(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    await t.write(initialize())
    await t.write(user("oi"))
    seen = await read_until(t, "result")
    kinds = [m["type"] for m in seen]
    assert kinds[0] == "control_response" and kinds[-1] == "result"
    assert (await agentd.list())[0].init["models"] == [{"value": "fake"}]
    await t.close()
    assert len(await agentd.list()) == 1  # close does not kill
    await t.kill()


@pytest.mark.anyio
async def test_reattach_answers_initialize_locally_and_redelivers_pending(agentd, tmp_path):
    first = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await first.connect()
    await first.write(initialize("req_a"))
    await first.write(user("ask"))
    seen = await read_until(first, "control_request")
    request_id = seen[-1]["request_id"]
    first.detach()
    await first.close()

    child = (await agentd.list())[0]
    second = AgentdTransport(agentd, session_id="s", attach_id=child.id,
                             attach_from=child.next_pos, attach_init=child.init)
    await second.connect()
    await second.write(initialize("req_b"))
    messages = second.read_messages()
    first_two = [await anext(messages), await anext(messages)]  # order between them is free
    reply = next(m for m in first_two if m["type"] == "control_response")
    assert reply["response"]["request_id"] == "req_b"
    assert reply["response"]["response"]["models"] == [{"value": "fake"}]
    pending = next(m for m in first_two if m["type"] == "control_request")
    assert pending["request_id"] == request_id
    await second.write(json.dumps({"type": "control_response", "response": {
        "subtype": "success", "request_id": request_id,
        "response": {"behavior": "allow", "updatedInput": {}}}}) + "\n")
    rest = []
    async for message in messages:
        rest.append(message)
        if message["type"] == "result":
            break
    assert any(m["type"] == "assistant" and
               m["message"]["content"][0]["text"] == "permitido" for m in rest)
    await second.kill()


@pytest.mark.anyio
async def test_reattach_delivers_a_pending_request_once_even_if_the_log_replays_it(agentd, tmp_path):
    first = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await first.connect()
    await first.write(initialize("req_a"))
    await first.write(user("ask"))
    seen = await read_until(first, "control_request")
    request_id = seen[-1]["request_id"]
    first.detach()
    await first.close()

    child = (await agentd.list())[0]
    # Nothing was acked: the request is both pending and in the log from `ack`.
    second = AgentdTransport(agentd, session_id="s", attach_id=child.id,
                             attach_from=child.ack, attach_init=child.init)
    await second.connect()
    await second.write(initialize("req_b"))
    collected = []
    answered = False
    async for message in second.read_messages():
        collected.append(message)
        if message["type"] == "control_request" and not answered:
            answered = True
            await second.write(json.dumps({"type": "control_response", "response": {
                "subtype": "success", "request_id": request_id,
                "response": {"behavior": "allow", "updatedInput": {}}}}) + "\n")
        if message["type"] == "result":
            break
    requests = [m for m in collected if m["type"] == "control_request"]
    assert [m["request_id"] for m in requests] == [request_id]
    await second.kill()


@pytest.mark.anyio
async def test_foreign_control_responses_are_filtered(agentd, tmp_path):
    first = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await first.connect()
    await first.write(initialize("req_a"))
    await read_until(first, "control_response")
    child = (await agentd.list())[0]
    first.detach()
    second = AgentdTransport(agentd, session_id="s", attach_id=child.id, attach_from=0,
                             attach_init=child.init)
    await second.connect()
    await second.write(user("oi"))
    seen = await read_until(second, "result")
    # req_a's response belongs to the first transport: never shown to the second.
    assert all(m.get("response", {}).get("request_id") != "req_a" for m in seen)
    await second.kill()


@pytest.mark.anyio
async def test_processed_acks_complete_messages_only(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    await t.write(user("stream:3"))
    async for message in t.read_messages():
        if message["type"] == "stream_event":
            t.processed(StreamEvent(uuid=message["uuid"], session_id="s",
                                    event=message["event"]))
            continue
        if message["type"] == "assistant":
            class Done:  # anything with the uuid of the line
                uuid = message["uuid"]
            t.processed(Done())
            break
    await asyncio.sleep(0.2)  # ack is sent in the background
    child = (await agentd.list())[0]
    # stream:3 -> 0 system, 1 message_start, 2 block_start, 3-5 deltas, 6 assistant,
    # 7 block_stop: processing the assistant confirms up to 7.
    assert child.ack == 7
    await t.kill()


@pytest.mark.anyio
async def test_nonzero_exit_raises_process_error_with_stderr(agentd, tmp_path):
    lines: list[str] = []
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path),
                        on_stderr=lines.append)
    await t.connect()
    await t.write(user("exit:4"))
    with pytest.raises(ProcessError) as caught:
        async for _ in t.read_messages():
            pass
    assert caught.value.exit_code == 4
    assert lines == ["fake failure"]
    await t.kill()


@pytest.mark.anyio
async def test_detached_transport_drops_writes(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    t.detach()
    await t.write(user("oi"))  # no error, nothing sent
    child = (await agentd.list())[0]
    await asyncio.sleep(0.3)
    assert (await agentd.list())[0].next_pos == child.next_pos == 0
    await agentd.kill(child.id)


@pytest.mark.anyio
async def test_lost_connection_ends_reads_with_error(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    child_id = t.child_id
    await agentd._close_connection()  # simulates the agentd going away
    with pytest.raises(CLIConnectionError):
        async for _ in t.read_messages():
            pass
    await agentd.ensure_running()
    await agentd.kill(child_id)


@pytest.mark.anyio
async def test_stale_connection_drop_does_not_wipe_the_new_connection(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    old_writer = agentd._writer
    await agentd._close_connection()
    await agentd.ensure_running()  # new connection
    assert agentd._writer is not old_writer and agentd.connected
    queue = await agentd.subscribe(t.child_id, 0)
    # The old connection's read loop ends late and reports its own loss.
    agentd._drop_connection(old_writer)
    assert agentd.connected
    assert len(await agentd.list()) == 1
    await agentd.write(t.child_id, user("oi"))
    kinds = []
    while "result" not in kinds:
        event = await asyncio.wait_for(queue.get(), 5)
        assert event.get("ev") != "lost"
        if event.get("ev") == "line":
            kinds.append(json.loads(event["line"])["type"])


@pytest.mark.anyio
async def test_silent_listener_does_not_hang_ensure_running(tmp_path):
    path = socket_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connections = []

    async def accept(reader, writer):
        connections.append(writer)  # accepts and never answers

    server = await asyncio.start_unix_server(accept, str(path))
    client = AgentdClient(tmp_path, spawn_allowed=False)
    try:
        with pytest.raises(AgentdUnavailable):
            await asyncio.wait_for(client.ensure_running(), 6)
        assert not client.connected
    finally:
        server.close()
        for writer in connections:
            writer.close()


@pytest.mark.anyio
async def test_failed_subscribe_leaves_no_queue(agentd, tmp_path):
    with pytest.raises(AgentdUnavailable):
        await agentd.subscribe("nope", 0)
    assert "nope" not in agentd._subscriptions


@pytest.mark.anyio
async def test_connect_kills_spawned_child_when_subscribe_fails(agentd, tmp_path, monkeypatch):
    async def broken(child_id, start):
        raise AgentdUnavailable("boom")

    monkeypatch.setattr(agentd, "subscribe", broken)
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    with pytest.raises(AgentdConnectError):
        await t.connect()
    for _ in range(50):
        if not await agentd.list():
            break
        await asyncio.sleep(0.1)
    assert await agentd.list() == []


@pytest.mark.anyio
async def test_invalid_json_line_raises_connection_error(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    t._queue.put_nowait({"ev": "line", "pos": 0, "line": "not json"})
    with pytest.raises(CLIConnectionError):
        async for _ in t.read_messages():
            pass
    await t.kill()


@pytest.mark.anyio
async def test_finished_agentd_launchers_are_reaped(tmp_path):
    client = AgentdClient(tmp_path, idle_exit=5)
    await client.ensure_running()
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    client._procs.append(done)
    await asyncio.sleep(0.5)
    await client.ensure_running()
    assert done not in client._procs and done.returncode is not None
    await client.aclose()


@pytest.mark.anyio
async def test_transport_kill_returns_only_after_the_process_is_gone(agentd, tmp_path):
    # Takes a second to wind down after its stdin closes, and ignores SIGTERM meanwhile.
    code = ("import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "sys.stdin.read(); time.sleep(1)")
    slow = SpawnSpec(cmd=[sys.executable, "-c", code], cwd=str(tmp_path), env=dict(os.environ))
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: slow)
    await t.connect()
    pid = (await agentd.list())[0].pid
    await t.kill()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert await agentd.list() == []


@pytest.mark.anyio
async def test_kill_after_a_lost_connection_reconnects_and_kills(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    child_id = t.child_id
    await agentd._close_connection()  # the connection is lost; the agentd is still there
    assert not agentd.connected
    await agentd.kill(child_id)
    assert agentd.connected
    await agentd.wait_gone(child_id)
    assert await agentd.list() == []


@pytest.mark.anyio
async def test_kill_does_not_start_an_agentd_that_is_not_running(tmp_path):
    client = AgentdClient(tmp_path, idle_exit=5)
    await client.kill("nothing")
    assert not socket_path(tmp_path).exists()
    assert client._procs == []


def test_agentd_child_ignores_unknown_fields_and_defaults_stderr():
    child = AgentdChild.from_reply({
        "id": "c", "session_id": "s", "pid": 1, "next_pos": 2, "ack": 1, "exit_code": None,
        "init": None, "added_by_a_newer_agentd": True})
    assert child.id == "c" and child.stderr == []
    exited = AgentdChild.from_reply({
        "id": "c", "session_id": "s", "pid": 1, "next_pos": 2, "ack": 1, "exit_code": 1,
        "init": None, "stderr": ["boom"]})
    assert exited.stderr == ["boom"]


@pytest.mark.anyio
async def test_list_carries_the_stderr_tail_of_an_exited_child(agentd, tmp_path):
    t = AgentdTransport(agentd, session_id="s", spawn=lambda: spec(tmp_path))
    await t.connect()
    await agentd.write(t.child_id, user("exit:3"))
    for _ in range(100):
        children = await agentd.list()
        if children and children[0].exit_code is not None:
            break
        await asyncio.sleep(0.05)
    assert children[0].exit_code == 3 and children[0].stderr == ["fake failure"]
    await t.kill()


@pytest.mark.anyio
async def test_failed_start_is_not_retried_during_the_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr("claudio_maestro.agent.agentd_client.START_WAIT", 0.2)
    client = AgentdClient(tmp_path, start_cooldown=0.6)
    starts = []
    monkeypatch.setattr(client, "_start_server", lambda: starts.append(True))  # never comes up
    with pytest.raises(AgentdUnavailable):
        await client.ensure_running()
    assert len(starts) == 1
    loop = asyncio.get_running_loop()
    began = loop.time()
    with pytest.raises(AgentdUnavailable):
        await client.ensure_running()
    assert loop.time() - began < 0.1 and len(starts) == 1  # no wait, no new start
    await asyncio.sleep(0.6)
    with pytest.raises(AgentdUnavailable):
        await client.ensure_running()
    assert len(starts) == 2
