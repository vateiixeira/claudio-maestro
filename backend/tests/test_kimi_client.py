"""Kimi Code client (ACP) and the provider plumbing of the sessions.

The client tests run against a fake `kimi acp` process (a Python script that
speaks ACP over stdio with the message shapes of kimi 2.7.3, probed live).
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro import db
from claudio_maestro.agent.base import AgentError, AgentOptions
from claudio_maestro.agent.kimi_client import KimiAgentClient, kimi_binary
from claudio_maestro.agent.sdk_client import SdkAgentClient
from claudio_maestro.projects import Project
from claudio_maestro.sessions import (
    ProviderUnavailableError,
    SessionManager,
    default_agent_factory,
)

FAKE_ACP = r"""
import json
import sys

CONFIG_OPTIONS = [
    {"type": "select", "id": "model", "name": "Model", "category": "model",
     "currentValue": "kimi-code/k3",
     "options": [{"value": "kimi-code/k3", "name": "K3"},
                 {"value": "kimi-code/kimi-for-coding", "name": "K2.8 Preview"}]},
    {"type": "select", "id": "thinking", "name": "Thinking", "category": "thought_level",
     "currentValue": "high",
     "options": [{"value": "low", "name": "Low"}, {"value": "high", "name": "High"},
                 {"value": "max", "name": "Max"}]},
    {"type": "select", "id": "mode", "name": "Mode", "category": "mode",
     "currentValue": "default",
     "options": [{"value": "default", "name": "Default"}, {"value": "plan", "name": "Plan"},
                 {"value": "auto", "name": "Auto"}, {"value": "yolo", "name": "YOLO"}]},
]


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def update(session_id, update):
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": session_id, "update": update}})


def answer(request_id, result):
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def prompt_turn(request_id, session_id, text):
    if text == "tool":
        update(session_id, {"sessionUpdate": "tool_call", "toolCallId": "0:tool_1",
                            "title": "Write", "kind": "edit", "status": "pending",
                            "content": [{"type": "content", "content": {"type": "text", "text": ""}}]})
        update(session_id, {"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_1",
                            "status": "in_progress",
                            "content": [{"type": "content",
                                         "content": {"type": "text", "text": '{"path": "/tmp/x"}'}}]})
        send({"jsonrpc": "2.0", "id": 999, "method": "session/request_permission",
              "params": {"sessionId": session_id,
                         "options": [
                             {"optionId": "approve_once", "name": "Approve once", "kind": "allow_once"},
                             {"optionId": "approve_always", "name": "Always", "kind": "allow_always"},
                             {"optionId": "reject", "name": "Reject", "kind": "reject_once"}],
                         "toolCall": {"toolCallId": "0:tool_1", "title": "Write",
                                      "content": [{"type": "content", "content": {
                                          "type": "text",
                                          "text": "Requesting approval to Writing /tmp/x"}}]}}})
        for line in sys.stdin:
            reply = json.loads(line)
            if reply.get("method") == "session/prompt":
                # Mid-turn prompt: the real CLI refuses it (turn.agent_busy).
                send({"jsonrpc": "2.0", "id": reply.get("id"),
                      "error": {"code": -32600,
                                "message": "Invalid request: another turn is already in progress",
                                "data": {"code": "turn.agent_busy"}}})
                continue
            if reply.get("id") == 999:
                chosen = reply.get("result", {}).get("outcome", {}).get("optionId")
                update(session_id, {"sessionUpdate": "tool_call_update", "toolCallId": "0:tool_1",
                                    "status": "completed",
                                    "content": [{"type": "content",
                                                 "content": {"type": "text", "text": "Wrote"}}],
                                    "rawOutput": "Wrote"})
                update(session_id, {"sessionUpdate": "agent_message_chunk",
                                    "content": {"type": "text", "text": f"escolheu {chosen}"}})
                answer(request_id, {"stopReason": "end_turn"})
                return
    else:
        update(session_id, {"sessionUpdate": "agent_thought_chunk",
                            "content": {"type": "text", "text": "hmm"}})
        update(session_id, {"sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "olá"}})
        answer(request_id, {"stopReason": "end_turn"})


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        answer(request_id, {"protocolVersion": 1,
                            "agentCapabilities": {"loadSession": True}})
    elif method == "session/new":
        answer(request_id, {"sessionId": "session_fake-1", "configOptions": CONFIG_OPTIONS})
    elif method == "session/load":
        session_id = message["params"]["sessionId"]
        update(session_id, {"sessionUpdate": "user_message_chunk",
                            "content": {"type": "text", "text": "pergunta antiga"}})
        update(session_id, {"sessionUpdate": "agent_thought_chunk",
                            "content": {"type": "text", "text": "pensando"}})
        update(session_id, {"sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "resposta antiga"}})
        answer(request_id, {"configOptions": CONFIG_OPTIONS})
    elif method == "session/set_config_option":
        answer(request_id, {"configOptions": CONFIG_OPTIONS})
    elif method == "session/prompt":
        prompt_turn(request_id, message["params"]["sessionId"],
                    message["params"]["prompt"][0].get("text", ""))
    elif method == "session/cancel":
        pass
"""


@pytest.fixture
def fake_acp(tmp_path: Path) -> list[str]:
    script = tmp_path / "fake_acp.py"
    script.write_text(FAKE_ACP, encoding="utf-8")
    return [sys.executable, str(script)]


async def deny_all(tool_name: str, tool_input: dict, context: Any) -> PermissionResultDeny:
    return PermissionResultDeny(message="não")


def make_options(**kwargs: Any) -> AgentOptions:
    kwargs.setdefault("cwd", Path("/tmp"))
    kwargs.setdefault("session_id", "app-session-1")
    kwargs.setdefault("resume", False)
    kwargs.setdefault("can_use_tool", deny_all)
    kwargs.setdefault("provider", "kimi")
    return AgentOptions(**kwargs)


async def collect(client: KimiAgentClient, count: int, timeout: float = 10.0) -> list[Any]:
    """The next `count` messages of the client, or a failure naming what arrived."""
    messages: list[Any] = []

    async def read() -> None:
        async for message in client.messages():
            messages.append(message)
            if len(messages) >= count:
                return

    task = asyncio.create_task(read())
    try:
        await asyncio.wait_for(task, timeout)
    except TimeoutError:
        raise AssertionError(f"só chegaram {len(messages)} mensagens: {messages!r}") from None
    return messages


@pytest.mark.anyio
async def test_connect_new_session(fake_acp: list[str]):
    client = KimiAgentClient(make_options(), command=fake_acp)
    await client.connect()
    try:
        assert client.provider_session_id == "session_fake-1"
        info = await client.get_server_info()
        assert info is not None
        models = {m["value"]: m for m in info["models"]}
        assert models["kimi-code/k3"]["displayName"] == "K3"
        assert models["kimi-code/k3"]["supportedEffortLevels"] == ["low", "high", "max"]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_text_turn_streams_and_completes(fake_acp: list[str]):
    client = KimiAgentClient(make_options(), command=fake_acp)
    await client.connect()
    try:
        reader = asyncio.create_task(collect(client, 9))
        await client.send("oi")
        messages = await reader
        kinds = [type(m).__name__ for m in messages]
        assert kinds[0] == "StreamEvent" and messages[0].event["type"] == "message_start"
        assert "content_block_delta" in [m.event["type"] for m in messages if isinstance(m, StreamEvent)]
        assistant = next(
            m for m in messages
            if isinstance(m, AssistantMessage) and any(isinstance(b, TextBlock) for b in m.content)
        )
        assert [type(b).__name__ for b in assistant.content] == ["ThinkingBlock", "TextBlock"]
        assert assistant.content[0].thinking == "hmm"
        assert assistant.content[1].text == "olá"
        result = messages[-1]
        assert isinstance(result, ResultMessage) and not result.is_error
    finally:
        await client.close()


@pytest.mark.anyio
async def test_tool_call_and_permission_allow(fake_acp: list[str]):
    asked: list[tuple[str, dict]] = []

    async def allow(tool_name: str, tool_input: dict, context: Any) -> PermissionResultAllow:
        asked.append((tool_name, tool_input))
        return PermissionResultAllow()

    options = make_options(can_use_tool=allow)
    client = KimiAgentClient(options, command=fake_acp)
    await client.connect()
    try:
        reader = asyncio.create_task(collect(client, 8))
        await client.send("tool")
        messages = await reader
        assert asked == [("Write", {"path": "/tmp/x"})]
        use = next(
            m for m in messages
            if isinstance(m, AssistantMessage)
            and any(isinstance(b, ToolUseBlock) for b in m.content)
        )
        block = use.content[0]
        assert isinstance(block, ToolUseBlock)
        assert block.name == "Write" and block.input == {"path": "/tmp/x"}
        result = next(m for m in messages if isinstance(m, UserMessage))
        result_block = result.content[0]
        assert isinstance(result_block, ToolResultBlock)
        assert result_block.tool_use_id == "0:tool_1"
        assert result_block.content == "Wrote" and not result_block.is_error
        text = next(
            m for m in messages
            if isinstance(m, AssistantMessage) and any(isinstance(b, TextBlock) for b in m.content)
        )
        assert text.content[0].text == "escolheu approve_once"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_permission_deny_maps_to_reject(fake_acp: list[str]):
    client = KimiAgentClient(make_options(), command=fake_acp)
    await client.connect()
    try:
        reader = asyncio.create_task(collect(client, 8))
        await client.send("tool")
        messages = await reader
        text = next(
            m for m in messages
            if isinstance(m, AssistantMessage) and any(isinstance(b, TextBlock) for b in m.content)
        )
        assert text.content[0].text == "escolheu reject"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_resume_replays_history_without_stream_events(fake_acp: list[str]):
    options = make_options(resume=True, provider_session_id="session_fake-1")
    client = KimiAgentClient(options, command=fake_acp)
    await client.connect()
    try:
        messages = await collect(client, 2)
        assert not any(isinstance(m, StreamEvent) for m in messages)
        user = messages[0]
        assert isinstance(user, UserMessage) and user.content == "pergunta antiga"
        assert (user.origin or {}).get("kind") == "human"
        assistant = messages[1]
        assert isinstance(assistant, AssistantMessage)
        assert isinstance(assistant.content[0], ThinkingBlock)
        assert assistant.content[0].thinking == "pensando"
        assert assistant.content[1].text == "resposta antiga"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_config_changes(fake_acp: list[str]):
    client = KimiAgentClient(make_options(), command=fake_acp)
    await client.connect()
    try:
        await client.set_model("kimi-code/kimi-for-coding")
        await client.set_effort("xhigh")  # maps to the "max" thinking level
        await client.set_permission_mode("bypassPermissions")  # maps to yolo
        with pytest.raises(AgentError) as excinfo:
            await client.set_effort("bogus")
        assert excinfo.value.refused
    finally:
        await client.close()


# Provider plumbing ------------------------------------------------------------


def make_project(db_path: Path, folder: Path) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    with db.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, path, color, position, created_at)"
            " VALUES ('app', ?, '#ff8800', 0, 0)",
            (str(folder),),
        )
        project_id = cursor.lastrowid
    return Project(
        id=project_id, name="app", path=str(folder), color="#ff8800", position=0,
        created_at=0, available=True,
    )


def make_manager(tmp_path: Path) -> SessionManager:
    db_path = tmp_path / "data" / "maestro.db"
    db.init_db(db_path)
    return SessionManager(db_path, lambda event: None)


def enable_kimi(db_path: Path) -> None:
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES ('preferences', ?)",
            (json.dumps({"kimi_enabled": True}),),
        )


def test_create_kimi_session_requires_the_preference(tmp_path: Path):
    manager = make_manager(tmp_path)
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    with pytest.raises(ProviderUnavailableError):
        manager.create_session(project, provider="kimi")


def test_create_kimi_session_requires_the_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("claudio_maestro.providers.kimi_binary", lambda: None)
    manager = make_manager(tmp_path)
    enable_kimi(manager._db_path)
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    with pytest.raises(ProviderUnavailableError):
        manager.create_session(project, provider="kimi")


def test_create_kimi_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("claudio_maestro.providers.kimi_binary", lambda: "/usr/bin/kimi")
    manager = make_manager(tmp_path)
    enable_kimi(manager._db_path)
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    record = manager.create_session(project, provider="kimi")
    assert record.provider == "kimi"
    # The Claude defaults of new sessions do not apply to Kimi.
    assert record.model is None and record.effort is None and record.permission_mode is None
    with db.connect(manager._db_path) as conn:
        row = conn.execute(
            "SELECT provider FROM sessions WHERE session_id = ?", (record.session_id,)
        ).fetchone()
    assert row["provider"] == "kimi"
    described = manager.describe_record(record)
    assert described["provider"] == "kimi"
    assert "provider_session_id" not in described


def test_create_claude_session_keeps_the_default_provider(tmp_path: Path):
    manager = make_manager(tmp_path)
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    record = manager.create_session(project)
    assert record.provider == "claude"


def test_default_agent_factory_dispatches_by_provider():
    claude = default_agent_factory(make_options(provider="claude"))
    assert isinstance(claude, SdkAgentClient)
    kimi = default_agent_factory(make_options())
    assert isinstance(kimi, KimiAgentClient)


def test_kimi_binary_prefers_the_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    binary = tmp_path / "kimi"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("MAESTRO_KIMI_CLI", str(binary))
    assert kimi_binary() == str(binary)


def test_wire_context_reads_the_last_step_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from claudio_maestro.agent.kimi_client import KIMI_CONTEXT_WINDOW, wire_context

    monkeypatch.setenv("MAESTRO_KIMI_SESSIONS", str(tmp_path))
    wire = tmp_path / "wd_app_123" / "session_abc" / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True)
    wire.write_text(
        '{"type":"context.append_loop_event","event":{"type":"step.end",'
        '"usage":{"inputOther":100,"output":10,"inputCacheRead":200,"inputCacheCreation":50}}}\n'
        '{"type":"context.append_loop_event","event":{"type":"step.end",'
        '"usage":{"inputOther":789,"output":2651,"inputCacheRead":37376,"inputCacheCreation":0}}}\n',
        encoding="utf-8",
    )
    usage = wire_context("session_abc")
    assert usage == {"totalTokens": 38165, "rawMaxTokens": KIMI_CONTEXT_WINDOW}
    assert wire_context("session_sem_log") is None
    assert wire_context("../etc") is None


@pytest.mark.anyio
async def test_a_message_sent_mid_turn_waits_for_the_running_one(fake_acp: list[str]):
    """The CLI refuses a prompt sent mid-turn (turn.agent_busy): the client queues it."""
    async def allow(tool_name: str, tool_input: dict, context: Any) -> PermissionResultAllow:
        return PermissionResultAllow()

    client = KimiAgentClient(make_options(can_use_tool=allow), command=fake_acp)
    await client.connect()
    try:
        # The tool turn holds the fake busy (waiting for the permission answer):
        # without the queue, the second prompt would be refused.
        reader = asyncio.create_task(collect(client, 17))
        await client.send("tool")
        await client.send("oi")
        messages = await reader
        results = [m for m in messages if isinstance(m, ResultMessage)]
        assert len(results) == 2
        assert not any(r.is_error for r in results)
        texts = [
            block.text
            for m in messages
            if isinstance(m, AssistantMessage)
            for block in m.content
            if isinstance(block, TextBlock)
        ]
        assert texts == ["escolheu approve_once", "olá"]
    finally:
        await client.close()


def test_create_kimi_session_uses_the_kimi_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("claudio_maestro.providers.kimi_binary", lambda: "/usr/bin/kimi")
    manager = make_manager(tmp_path)
    with db.connect(manager._db_path) as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES ('preferences', ?)",
            (json.dumps({
                "kimi_enabled": True,
                "kimi_new_session_model": "kimi-code/k3",
                "kimi_new_session_effort": "max",
                # The Claude defaults never leak into a Kimi session.
                "new_session_model": "opus",
                "new_session_effort": "high",
            }),),
        )
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    record = manager.create_session(project, provider="kimi")
    assert record.model == "kimi-code/k3"
    assert record.effort == "max"
    assert record.permission_mode is None


@pytest.mark.anyio
async def test_finishing_a_kimi_session_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Finishing turns Remote Control off; the Kimi gate must only block turning it on."""
    monkeypatch.setattr("claudio_maestro.providers.kimi_binary", lambda: "/usr/bin/kimi")
    manager = make_manager(tmp_path)
    enable_kimi(manager._db_path)
    project = make_project(manager._db_path, tmp_path / "home" / "app")
    record = manager.create_session(project, provider="kimi")
    try:
        updated = await manager.update(record.session_id, finished=True)
        assert updated["finished"] is True
        with pytest.raises(Exception, match="Remote Control"):
            await manager.update(record.session_id, finished=False, remote_control=True)
    finally:
        await manager.shutdown()
