import asyncio
import os
import sys
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
)

from claudio_maestro.agent.agentd_client import AgentdClient
from claudio_maestro.agent.base import AgentOptions, AttachInfo
from claudio_maestro.agent.sdk_client import SdkAgentClient
from claudio_maestro.agent.spawn import SpawnSpec

FAKE_CLI = [sys.executable, str(Path(__file__).with_name("fake_cli.py"))]


@pytest.fixture
async def agentd(tmp_path, monkeypatch):
    # The fake CLI stands in for `claude`: build_cli_spawn's command is replaced.
    monkeypatch.setattr(
        "claudio_maestro.agent.sdk_client.build_cli_spawn",
        lambda sdk_options: SpawnSpec(cmd=FAKE_CLI, cwd=str(sdk_options.cwd), env=dict(os.environ)),
    )
    client = AgentdClient(tmp_path / "data", idle_exit=5, orphan_timeout=5)
    await client.ensure_running()
    yield client
    for child in await client.list():
        await client.kill(child.id)
    await client.aclose()


async def allow(*_args):
    return PermissionResultAllow()


def options(tmp_path, agentd, **extra) -> AgentOptions:
    return AgentOptions(cwd=tmp_path, session_id="11111111-1111-1111-1111-111111111111",
                        resume=False, can_use_tool=allow, agentd=agentd, **extra)


async def text_until_result(client: SdkAgentClient) -> str:
    text = ""
    async for message in client.messages():
        if isinstance(message, AssistantMessage):
            text += "".join(b.text for b in message.content if isinstance(b, TextBlock))
        if isinstance(message, ResultMessage):
            return text
    raise AssertionError("no result")


@pytest.mark.anyio
async def test_turn_through_agentd(tmp_path, agentd):
    client = SdkAgentClient(options(tmp_path, agentd))
    await client.connect()
    await client.send("oi")
    assert await text_until_result(client) == "eco: oi"
    assert (await client.get_server_info())["models"] == [{"value": "fake"}]
    await client.close()
    for _ in range(100):  # the agentd removes the child once the process is gone
        if not await agentd.list():
            break
        await asyncio.sleep(0.05)
    assert await agentd.list() == []


@pytest.mark.anyio
async def test_detach_keeps_process_and_reattach_continues(tmp_path, agentd):
    first = SdkAgentClient(options(tmp_path, agentd))
    await first.connect()
    await first.send("oi")
    await text_until_result(first)
    assert await first.detach() is True
    child = (await agentd.list())[0]
    assert child.exit_code is None

    second = SdkAgentClient(options(
        tmp_path, agentd,
        attach=AttachInfo(agentd_id=child.id, from_pos=child.ack, init_response=child.init),
    ))
    await second.connect()
    await second.send("de novo")
    # The first turn's result was not confirmed (ack == 3), so the agentd replays it.
    assert await text_until_result(second) == ""
    assert await text_until_result(second) == "eco: de novo"
    await second.close()


@pytest.mark.anyio
async def test_messages_ack_after_processing(tmp_path, agentd):
    client = SdkAgentClient(options(tmp_path, agentd))
    await client.connect()
    await client.send("oi")
    await text_until_result(client)
    child = (await agentd.list())[0]
    # 0 initialize response (not a message), 1 system, 2 assistant, 3 result. The session
    # handled system and assistant; the result is confirmed only when the next one is asked.
    assert child.ack == 3
    await client.close()


@pytest.mark.anyio
async def test_falls_back_to_direct_process_when_agentd_is_down(tmp_path, monkeypatch):
    started = []

    class ClientStub:
        """Stands in for ClaudeSDKClient: with a transport it only connects it (and the
        agentd being down raises); without one it records a direct start."""

        def __init__(self, options, transport=None):
            self.transport = transport

        async def connect(self):
            if self.transport is not None:
                await self.transport.connect()
            else:
                started.append(True)

    monkeypatch.setattr("claudio_maestro.agent.sdk_client.ClaudeSDKClient", ClientStub)
    down = AgentdClient(tmp_path / "nothing-here", spawn_allowed=False)
    client = SdkAgentClient(options(tmp_path, down))
    await client.connect()
    assert len(started) == 1
    assert await client.detach() is False  # now a plain child of the backend


@pytest.mark.anyio
async def test_detach_without_agentd_returns_false(tmp_path):
    client = SdkAgentClient(AgentOptions(cwd=tmp_path, session_id="x", resume=False,
                                         can_use_tool=allow), sdk_client=object())
    assert await client.detach() is False
