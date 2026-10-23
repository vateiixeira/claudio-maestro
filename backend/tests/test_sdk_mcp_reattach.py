"""The reattach handshake against a real `ClaudeSDKClient` over a scripted transport.

The transport answers the SDK's initialize request and nothing else, so no `claude`
process starts. The file is exempt from the guard that cuts `ClaudeSDKClient.connect`
(see `conftest.py`) for that reason.
"""

import asyncio
import json
from typing import Any

import pytest
from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk._internal.transport import Transport
from test_agent_sdk_client import _attach, _echo_server, make_options

from claudio_maestro.agent.sdk_client import SdkAgentClient, build_sdk_options


class ScriptedTransport(Transport):
    """A transport that answers the SDK's initialize request and nothing else."""

    def __init__(self) -> None:
        self.written: list[dict[str, Any]] = []
        self._incoming: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def connect(self) -> None:
        pass

    async def write(self, data: str) -> None:
        message = json.loads(data)
        self.written.append(message)
        if message.get("type") == "control_request":
            self._incoming.put_nowait({
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": message["request_id"],
                    "response": {},
                },
            })

    async def read_messages(self):
        while (message := await self._incoming.get()) is not None:
            yield message

    async def close(self) -> None:
        self._incoming.put_nowait(None)

    def is_ready(self) -> bool:
        return True

    async def end_input(self) -> None:
        pass


@pytest.mark.anyio
async def test_real_sdk_client_exposes_the_bridges_after_connect(tmp_path):
    """The reattach handshake finds the bridges at `ClaudeSDKClient._query._sdk_mcp_bridges`.
    If an SDK upgrade renames either, this breaks instead of the handshake going silent."""
    sdk_options = build_sdk_options(
        make_options(tmp_path, mcp_servers={"maestro": _echo_server()})
    )
    sdk_client = ClaudeSDKClient(sdk_options, transport=ScriptedTransport())
    await sdk_client.connect()
    try:
        assert set(sdk_client._query._sdk_mcp_bridges) == {"maestro"}
    finally:
        await sdk_client.disconnect()


@pytest.mark.anyio
async def test_attach_handshake_initializes_the_server_of_a_real_sdk_client(tmp_path):
    options = make_options(
        tmp_path, attach=_attach(), mcp_servers={"maestro": _echo_server()}
    )
    sdk_client = ClaudeSDKClient(build_sdk_options(options), transport=ScriptedTransport())
    client = SdkAgentClient(options, sdk_client=sdk_client)
    await client.connect()
    try:
        bridge = sdk_client._query._sdk_mcp_bridges["maestro"]
        listed = await bridge.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    finally:
        await client.close()

    assert listed is not None and "error" not in listed
    assert [t["name"] for t in listed["result"]["tools"]] == ["eco"]
