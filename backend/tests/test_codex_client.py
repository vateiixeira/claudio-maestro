"""Codex app-server adapter against a local, scripted JSON-RPC process."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from claudio_maestro.agent.base import AgentError, AgentOptions
from claudio_maestro.agent.codex_client import CodexAgentClient
from claudio_maestro.agent.codex_transport import (
    CodexTransport,
    codex_binary,
    list_codex_models,
)

THREAD = "11111111-1111-4111-8111-111111111111"
FAKE_SERVER = r"""
import json
import os
import sys

thread = "11111111-1111-4111-8111-111111111111"
turn = "turn-1"
ready = False
running = False

def output(**message):
    print(json.dumps(message), flush=True)

def event(method, **params):
    output(method=method, params={"threadId": thread, "turnId": turn, **params})

def finish(status="completed"):
    global running
    running = False
    event("thread/tokenUsage/updated", tokenUsage={
        "last": {"totalTokens": 120, "inputTokens": 100, "cachedInputTokens": 50,
                 "outputTokens": 20, "reasoningOutputTokens": 5},
        "total": {"totalTokens": 349},
        "modelContextWindow": 1000,
    })
    event("turn/completed", turn={"id": turn, "items": [], "status": status})

for line in sys.stdin:
    msg = json.loads(line)
    method, params = msg.get("method"), msg.get("params", {})
    req_id = msg.get("id")
    if method == "initialize":
        assert params["capabilities"]["experimentalApi"]
        output(id=req_id, result={"userAgent": "Codex CLI test"})
        continue
    if method == "initialized":
        ready = True
        continue
    assert ready
    if req_id in ("tool-approval", "network-approval"):
        assert msg["result"] == {"decision": "decline"}
        if req_id == "tool-approval":
            event("item/completed", item={"id": "cmd", "type": "commandExecution",
                                        "command": "pwd", "status": "declined",
                                        "aggregatedOutput": "Bloqueado"})
        finish()
        continue
    if method == "config/read":
        output(id=req_id, result={"config": {"model": "cli-model",
                                            "model_reasoning_effort": "medium"}})
    elif method == "model/list":
        if not params.get("cursor"):
            output(id=req_id, result={"data": [
                {"id": "catalog-first", "model": "cli-model", "displayName": "CLI",
                 "isDefault": True, "defaultReasoningEffort": "medium",
                 "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]},
                {"model": "invisible", "hidden": True},
            ], "nextCursor": "more"})
        else:
            assert params["cursor"] == "more"
            output(id=req_id, result={"data": [
                {"id": "catalog-second", "model": "chosen", "displayName": "Escolha",
                 "defaultReasoningEffort": "ultra",
                 "supportedReasoningEfforts": [{"reasoningEffort": "ultra"}]},
            ]})
    elif method == "thread/read":
        assert params["threadId"] == thread
        output(id=req_id, result={"thread": {"id": thread, "cwd": os.environ.get(
            "FAKE_CODEX_CWD", os.getcwd()), "historyMode": "paginated",
            "path": os.environ.get("FAKE_CODEX_ROLLOUT")}})
    elif method in ("thread/start", "thread/resume"):
        assert params["cwd"] == os.getcwd()
        if method == "thread/resume":
            assert params["threadId"] == thread and params["excludeTurns"]
        output(id=req_id, result={"thread": {"id": thread, "turns": []},
                                 "model": params.get("model", "cli-model"),
                                 "reasoningEffort": params.get("config", {}).get("model_reasoning_effort", "medium")})
    elif method == "thread/turns/list":
        assert params["threadId"] == thread
        assert params["sortDirection"] == "asc" and params["itemsView"] == "full"
        page = [{"id": "turn-last", "items": [
            {"id": "agent-last", "type": "agentMessage", "text": "Outra resposta"},
        ]}] if params.get("cursor") else [{"id": "turn-past", "items": [
            {"id": "user-past", "clientId": "in-app-id", "type": "userMessage",
             "content": [{"type": "text", "text": "Pergunta histórica"}]},
            {"id": "agent-past", "type": "agentMessage", "text": "Resposta histórica"},
        ]}]
        if os.environ.get("FAKE_CODEX_IMAGES") and params.get("cursor"):
            page[0]["items"] += [{"id": "user-img", "type": "userMessage", "content": [
                {"type": "image", "url": "data:image/png;base64,AA=="},
                {"type": "image", "url": "https://example.com/private-session-image"},
                {"type": "localImage", "path": "/private/secret-image.png"},
            ]}]
        output(id=req_id, result={"data": page, "nextCursor": None if params.get("cursor") else "next"})
    elif method == "turn/start":
        assert not running
        assert params["threadId"] == thread
        turn = "turn-" + str(req_id)
        running = True
        event("turn/started", turn={"id": turn, "items": [], "status": "inProgress"})
        output(id=req_id, result={"turn": {"id": turn, "items": [], "status": "inProgress"}})
        prompt = params["input"][0]["text"]
        if prompt == "Esperar":
            continue
        if prompt == "Sair":
            sys.exit(1)
        if prompt == "Plano":
            assert params["collaborationMode"]["mode"] == "plan"
            assert params["sandboxPolicy"]["type"] == "readOnly"
            assert params["collaborationMode"]["settings"]["model"] == "chosen"
            assert params["collaborationMode"]["settings"]["reasoning_effort"] == "ultra"
            assert params["input"][1]["url"] == "data:image/png;base64,AA=="
        if prompt == "Padrão":
            assert params["collaborationMode"]["mode"] == "default"
            assert params["model"] == "cli-model" and params["effort"] == "medium"
            assert params["sandboxPolicy"]["type"] == "workspaceWrite"
            assert params["approvalPolicy"] == "never"
        if prompt == "Modelo com esforço padrão":
            assert params["model"] == "chosen" and params["effort"] == "ultra"
        if prompt == "Esforço padrão do CLI":
            assert params["model"] == "cli-model" and params["effort"] == "medium"
        if prompt == "Rede":
            output(id="network-approval", method="item/commandExecution/requestApproval",
                   params={"threadId": thread, "turnId": turn, "itemId": "cmd",
                           "networkApprovalContext": {"host": "example.com:443", "protocol": "https"},
                           "cwd": os.getcwd()})
            continue
        if prompt == "Ferramenta":
            event("item/started", item={"id": "cmd", "type": "commandExecution",
                                       "command": "pwd", "status": "inProgress"})
            output(id="tool-approval", method="item/commandExecution/requestApproval",
                   params={"threadId": thread, "turnId": turn, "itemId": "cmd",
                           "command": "pwd", "cwd": os.getcwd()})
            continue
        event("item/reasoning/summaryTextDelta", itemId="reason", summaryIndex=0, delta="Pens")
        event("item/reasoning/summaryTextDelta", itemId="reason", summaryIndex=0, delta="ando")
        event("item/completed", item={"id": "reason", "type": "reasoning",
                                     "summary": ["Pensando"]})
        event("item/agentMessage/delta", itemId="agent", delta="Res")
        event("item/agentMessage/delta", itemId="agent", delta="posta")
        event("item/completed", item={"id": "agent", "type": "agentMessage", "text": "Resposta"})
        finish()
    elif method == "thread/compact/start":
        assert set(params) == {"threadId"} and params["threadId"] == thread
        turn = "compact-" + str(req_id)
        event("turn/started", turn={"id": turn, "items": [], "status": "inProgress"})
        output(id=req_id, result={})
        event("item/completed", item={"type": "contextCompaction", "id": "compaction"})
        finish()
    elif method == "secret/error":
        output(id=req_id, error={"code": -32603, "message": "internal api-key=credential-123"})
    elif method == "turn/interrupt":
        assert params["threadId"] == thread and params["turnId"] == turn
        finish("interrupted")
        output(id=req_id, result={})
    else:
        output(id=req_id, error={"code": -32601, "message": "Method not found"})
"""


@pytest.fixture
def command(tmp_path: Path) -> list[str]:
    path = tmp_path / "fake_codex.py"
    path.write_text(FAKE_SERVER)
    return [sys.executable, str(path)]


async def deny(*_args):
    return PermissionResultDeny(message="Bloqueado")


def create_client(tmp_path, command, *, can_use_tool=deny, resume=False, **options):
    return CodexAgentClient(
        AgentOptions(
            cwd=tmp_path,
            session_id="maestro-session",
            resume=resume,
            provider="codex",
            provider_session_id=THREAD if resume else None,
            can_use_tool=can_use_tool,
            **options,
        ),
        command=command,
    )


async def completed_turn(messages):
    received = []
    async with asyncio.timeout(4):
        async for message in messages:
            received.append(message)
            if isinstance(message, ResultMessage):
                return received
    pytest.fail("Resposta sem evento de fim do turno")


@pytest.mark.anyio
async def test_model_catalog_paginates_and_normalizes(tmp_path, command):
    async with CodexTransport(tmp_path, command=command) as transport:
        models = await list_codex_models(transport)
    assert [model["value"] for model in models] == ["cli-model", "chosen"]
    assert models[0]["isDefault"]
    assert models[0]["defaultEffort"] == "medium"
    assert models[1]["supportedEffortLevels"] == ["ultra"]


@pytest.mark.anyio
async def test_turn_streams_reasoning_text_context_and_resolved_model(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        assert client.provider_session_id == THREAD
        await client.send("Olá")
        messages = await completed_turn(client.messages())
        assert any(isinstance(msg, StreamEvent) and msg.event["type"] == "content_block_delta"
                   for msg in messages)
        content = [block for msg in messages if isinstance(msg, AssistantMessage)
                   for block in msg.content]
        assert content == [ThinkingBlock(thinking="Pensando", signature=""), TextBlock(text="Resposta")]
        result = messages[-1]
        assert not result.is_error and result.usage["output_tokens"] == 20
        summary = await client.get_context_usage("summary")
        assert summary["totalTokens"] == 120
        assert summary["rawMaxTokens"] == 1000
        details = await client.get_context_usage()
        assert sum(category["tokens"] for category in details["categories"] if category["kind"] == "used") == 120
    finally:
        await client.close()


@pytest.mark.anyio
async def test_tool_approval_and_result_are_forwarded(tmp_path, command):
    calls = []

    async def on_approval(name, tool_input, context):
        calls.append((name, tool_input, context.tool_use_id))
        return PermissionResultDeny(message="Bloqueado")

    client = create_client(tmp_path, command, can_use_tool=on_approval)
    try:
        await client.connect()
        await client.send("Ferramenta")
        messages = await completed_turn(client.messages())
        uses = [block for msg in messages if isinstance(msg, AssistantMessage)
                for block in msg.content if isinstance(block, ToolUseBlock)]
        assert len(uses) == 1 and uses[0].input["command"] == "pwd"
        assert calls == [("Bash", {"command": "pwd", "cwd": str(tmp_path)}, uses[0].id)]
        results = [block for msg in messages if isinstance(msg, UserMessage)
                   for block in msg.content if isinstance(block, ToolResultBlock)]
        assert results == [ToolResultBlock(tool_use_id=uses[0].id, content="Bloqueado", is_error=True)]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_plan_effort_image_and_restoring_cli_defaults(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        await client.set_model("chosen")
        await client.set_effort("ultra")
        await client.set_permission_mode("plan")
        await client.send([
            {"type": "text", "text": "Plano"},
            {"type": "image", "source": {"media_type": "image/png", "data": "AA=="}},
        ])
        messages = client.messages()
        assert not (await completed_turn(messages))[-1].is_error
        await client.set_model(None)
        await client.set_effort("default")
        await client.set_permission_mode("dontAsk")
        await client.send("Padrão")
        assert not (await completed_turn(messages))[-1].is_error
        await messages.aclose()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_resume_replays_all_pages_without_opening_turn(tmp_path, command):
    client = create_client(tmp_path, command, resume=True)
    try:
        await client.connect()
        await client.send("Continuar")
        messages = await completed_turn(client.messages())
        user, first, second = (msg for msg in messages[:5] if isinstance(msg, (UserMessage, AssistantMessage)))
        assert user.uuid == "in-app-id" and user.content == "Pergunta histórica"
        assert first.content == [TextBlock(text="Resposta histórica")]
        assert second.content == [TextBlock(text="Outra resposta")]
        assert not any(isinstance(msg, StreamEvent) for msg in messages[:4])
    finally:
        await client.close()


@pytest.mark.anyio
async def test_resume_rejects_thread_from_another_directory(tmp_path, command):
    client = create_client(tmp_path, command, resume=True, env={"FAKE_CODEX_CWD": "/outra-pasta"})
    with pytest.raises(AgentError, match="outra pasta"):
        await client.connect()


@pytest.mark.anyio
async def test_interrupt_releases_the_next_queued_turn(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        await client.send("Esperar")
        await client.send("Próxima")
        await client.interrupt()
        messages = client.messages()
        assert (await completed_turn(messages))[-1].terminal_reason == "aborted_streaming"
        assert not (await completed_turn(messages))[-1].is_error
        await messages.aclose()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_process_exit_surfaces_in_message_stream(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        await client.send("Sair")
        with pytest.raises(AgentError, match="encerrou"):
            await completed_turn(client.messages())
    finally:
        await client.close()


@pytest.mark.anyio
async def test_bypass_cannot_be_selected_when_disabled(tmp_path, command):
    client = create_client(tmp_path, command, allow_bypass=False)
    try:
        await client.connect()
        with pytest.raises(AgentError) as error:
            await client.set_permission_mode("bypassPermissions")
        assert error.value.refused
    finally:
        await client.close()


@pytest.mark.anyio
async def test_native_compaction_reports_completion(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        await client.send("/compact")
        messages = await completed_turn(client.messages())
        assert messages[-1].subtype == "success"
        assert any(isinstance(msg, UserMessage) and "Conversa compactada" in msg.content
                   for msg in messages)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_resume_context_uses_only_rollouts_inside_codex_home(tmp_path, command):
    home = tmp_path / "codex-home"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    path = sessions / f"rollout-2026-11-24-{THREAD}.jsonl"
    info = {"model_context_window": 1000, "last_token_usage": {
        "total_tokens": 113, "input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 13,
    }}
    path.write_text(json.dumps({"type": "event_msg", "payload": {
        "type": "token_count", "info": info,
    }}) + "\n")
    client = create_client(tmp_path, command, resume=True, replay_history=False, env={
        "CODEX_HOME": str(home), "FAKE_CODEX_ROLLOUT": str(path),
    })
    try:
        await client.connect()
        assert (await client.get_context_usage())["totalTokens"] == 113
    finally:
        await client.close()
    other = tmp_path / path.name
    path.rename(other)
    path.symlink_to(other)
    client = create_client(tmp_path, command, resume=True, env={
        "CODEX_HOME": str(home), "FAKE_CODEX_ROLLOUT": str(path),
    })
    try:
        await client.connect()
        assert await client.get_context_usage() is None
    finally:
        await client.close()


def test_binary_entrypoint_is_absolute_without_resolving_symlinks(tmp_path, monkeypatch):
    script = tmp_path / "binary"
    script.touch(mode=0o755)
    link = tmp_path / "codex"
    link.symlink_to(script)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAESTRO_CODEX_CLI", "codex")
    assert codex_binary() == str(link)
    monkeypatch.setenv("MAESTRO_CODEX_CLI", "missing")
    assert codex_binary() is None


@pytest.mark.anyio
async def test_rpc_errors_keep_server_credentials_out_of_messages(tmp_path, command):
    async with CodexTransport(tmp_path, command=command) as transport:
        with pytest.raises(AgentError) as error:
            await transport.call("secret/error")
    assert "credential-123" not in str(error.value)


@pytest.mark.anyio
async def test_reset_effort_after_explicit_startup_config_and_model_switch(tmp_path, command):
    client = create_client(tmp_path, command, effort="high")
    try:
        await client.connect()
        await client.set_effort("default")
        messages = client.messages()
        await client.send("Esforço padrão do CLI")
        assert not (await completed_turn(messages))[-1].is_error
        await client.set_model("chosen")
        await client.send("Modelo com esforço padrão")
        assert not (await completed_turn(messages))[-1].is_error
        await messages.aclose()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_network_approval_shows_destination_and_protocol(tmp_path, command):
    calls = []

    async def on_approval(name, tool_input, context):
        calls.append((name, tool_input, context.title))
        return PermissionResultDeny(message="Bloqueado")

    client = create_client(tmp_path, command, can_use_tool=on_approval)
    try:
        await client.connect()
        await client.send("Rede")
        await completed_turn(client.messages())
        assert calls == [(
            "Rede do Codex", {"host": "example.com:443", "protocol": "https"},
            "Permissão para acessar a rede",
        )]
    finally:
        await client.close()


@pytest.mark.anyio
async def test_immediate_interrupt_after_prior_turn(tmp_path, command):
    client = create_client(tmp_path, command)
    try:
        await client.connect()
        await client.send("Primeira")
        messages = client.messages()
        assert not (await completed_turn(messages))[-1].is_error
        await asyncio.sleep(0)
        await client.send("Esperar")
        await client.interrupt()
        assert (await completed_turn(messages))[-1].terminal_reason == "aborted_streaming"
        await messages.aclose()
    finally:
        await client.close()


@pytest.mark.anyio
async def test_resume_preserves_image_only_turn_without_source_urls(tmp_path, command):
    client = create_client(tmp_path, command, resume=True, env={"FAKE_CODEX_IMAGES": "1"})
    try:
        await client.connect()
        await client.send("Continuar")
        messages = await completed_turn(client.messages())
        image_only = next(msg for msg in messages if isinstance(msg, UserMessage) and msg.content == "")
        assert image_only.origin == {
            "kind": "codex_replay",
            "images": [
                {"type": "image", "media_type": "image/png", "size": 1},
                {"type": "image", "media_type": None, "size": None},
                {"type": "image", "media_type": None, "size": None},
            ],
        }
    finally:
        await client.close()
