"""Real SDK client adapter, tested without starting the SDK or the `claude` process."""

import logging
import os
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    CLIConnectionError,
    CLINotFoundError,
    PermissionResultAllow,
    ProcessError,
    create_sdk_mcp_server,
    tool,
)
from fastapi.testclient import TestClient

from claudio_maestro.agent.base import AgentClient, AgentError, AgentOptions, AttachInfo
from claudio_maestro.agent.sdk_client import (
    INHERITED_ENV_VARS,
    SdkAgentClient,
    build_sdk_options,
    clean_inherited_env,
    sdk_agent_factory,
    to_agent_error,
)
from claudio_maestro.app import create_app

SESSION_ID = "8f2c1a4e-3b7d-4e61-9a0f-5c2d8e7b1a93"


async def allow_all(name, tool_input, context):
    return PermissionResultAllow()


def make_options(tmp_path: Path, **overrides: Any) -> AgentOptions:
    values: dict[str, Any] = {
        "cwd": tmp_path,
        "session_id": SESSION_ID,
        "resume": False,
        "can_use_tool": allow_all,
    }
    values.update(overrides)
    return AgentOptions(**values)


# build_sdk_options ---------------------------------------------------------


def test_build_options_new_session_passes_session_id(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert isinstance(sdk, ClaudeAgentOptions)
    assert sdk.cwd == tmp_path
    assert sdk.session_id == SESSION_ID
    assert sdk.resume is None
    assert sdk.include_partial_messages is True
    assert sdk.forward_subagent_text is True
    assert sdk.can_use_tool is allow_all


def test_build_options_allows_switching_to_bypass_later(tmp_path):
    # Without this flag the CLI refuses set_permission_mode("bypassPermissions").
    sdk = build_sdk_options(make_options(tmp_path))

    assert sdk.extra_args == {
        "allow-dangerously-skip-permissions": None,
        "replay-user-messages": None,
    }
    assert sdk.permission_mode is None


def test_build_options_resume_passes_resume(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, resume=True))

    assert sdk.resume == SESSION_ID
    assert sdk.session_id is None


def test_build_options_without_model_effort_mode_keeps_sdk_defaults(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))
    defaults = ClaudeAgentOptions()

    assert sdk.model == defaults.model
    assert sdk.effort == defaults.effort
    assert sdk.permission_mode == defaults.permission_mode


def test_build_options_with_model_effort_mode(tmp_path):
    sdk = build_sdk_options(
        make_options(
            tmp_path, model="haiku", effort="high", permission_mode="acceptEdits"
        )
    )

    assert sdk.model == "haiku"
    assert sdk.effort == "high"
    assert sdk.permission_mode == "acceptEdits"


def test_build_options_does_not_fork_by_default(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, resume=True))

    assert sdk.fork_session is False


def test_build_options_forks_a_resumed_session(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, resume=True, fork_session=True))

    assert sdk.resume == SESSION_ID
    assert sdk.fork_session is True


def test_build_options_fork_needs_resume(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, resume=False, fork_session=True))

    assert sdk.session_id == SESSION_ID
    assert sdk.fork_session is False


def test_build_options_does_not_set_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert sdk.setting_sources == ClaudeAgentOptions().setting_sources


def test_build_options_passes_empty_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, setting_sources=[]))

    assert sdk.setting_sources == []


def test_build_options_passes_given_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, setting_sources=["user"]))

    assert sdk.setting_sources == ["user"]


def test_build_options_does_not_set_settings_by_default(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert sdk.settings == ClaudeAgentOptions().settings


def test_build_options_passes_settings_json(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, settings='{"disableAllHooks": true}'))

    assert sdk.settings == '{"disableAllHooks": true}'


def test_build_options_does_not_set_env_by_default(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))
    assert sdk.env == {}


def test_build_options_passes_entrypoint_in_env(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, entrypoint="claudio-maestro"))
    assert sdk.env == {"CLAUDE_CODE_ENTRYPOINT": "claudio-maestro"}


# clean_inherited_env -------------------------------------------------------


def _echo_server():
    @tool("eco", "Devolve o texto", {"texto": str})
    async def eco(args):
        return {"content": [{"type": "text", "text": args["texto"]}]}

    return create_sdk_mcp_server("maestro", tools=[eco])


def test_build_options_maps_specialist_fields(tmp_path):
    server = _echo_server()
    sdk = build_sdk_options(make_options(
        tmp_path,
        system_prompt_append="Você é o revisor.",
        add_dirs=[tmp_path / "outra"],
        env={"MAESTRO_X": "1", "CLAUDE_CODE_ENTRYPOINT": "outro"},
        mcp_servers={"maestro": server},
        entrypoint="claudio-maestro",
    ))

    assert sdk.system_prompt == {
        "type": "preset", "preset": "claude_code", "append": "Você é o revisor.",
    }
    assert sdk.add_dirs == [tmp_path / "outra"]
    assert sdk.mcp_servers == {"maestro": server}
    # The entrypoint of the app wins over the same key in `env`.
    assert sdk.env == {"MAESTRO_X": "1", "CLAUDE_CODE_ENTRYPOINT": "claudio-maestro"}


def test_build_options_specialist_env_without_entrypoint(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, env={"MAESTRO_X": "1"}))

    assert sdk.env == {"MAESTRO_X": "1"}


def test_build_options_without_specialist_fields_keeps_sdk_defaults(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert not sdk.system_prompt  # the SDK default: nothing appended
    assert sdk.add_dirs == []
    assert sdk.mcp_servers == {}
    assert sdk.env == {}


def test_build_options_passes_cli_path_when_given(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path), cli_path="/opt/bin/claude")
    assert sdk.cli_path == "/opt/bin/claude"


def test_build_options_leaves_cli_path_to_the_sdk_by_default(tmp_path):
    assert build_sdk_options(make_options(tmp_path)).cli_path is None


def test_client_asks_the_provider_when_built(tmp_path):
    calls = []

    def provider():
        calls.append(1)
        return "/opt/bin/claude"

    client = SdkAgentClient(make_options(tmp_path), sdk_client=object(), cli_path=provider)
    assert client.sdk_options.cli_path == "/opt/bin/claude"
    assert calls == [1]


def test_sdk_agent_factory_uses_the_current_path(tmp_path):
    path = {"value": "/a/claude"}
    factory = sdk_agent_factory(lambda: path["value"])
    assert factory(make_options(tmp_path)).sdk_options.cli_path == "/a/claude"
    path["value"] = None
    assert factory(make_options(tmp_path)).sdk_options.cli_path is None


def test_clean_inherited_env_removes_session_markers(monkeypatch):
    for name in INHERITED_ENV_VARS:
        monkeypatch.setenv(name, "1")

    clean_inherited_env()

    for name in INHERITED_ENV_VARS:
        assert name not in os.environ


def test_clean_inherited_env_lists_every_required_variable():
    required = {
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_CHILD_SESSION",
        "CLAUDE_PID",
        "CLAUDE_EFFORT",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_CODE_EXECPATH",
        "CLAUDE_CODE_MESSAGING_SOCKET",
        "CLAUDE_CODE_MESSAGING_TOKEN",
        "CLAUDE_AGENT_SDK_VERSION",
        "CLAUDE_CODE_SESSION_ATTENDED",
        "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
        "CLAUDE_CODE_ENABLE_TASKS",
    }
    assert required <= set(INHERITED_ENV_VARS)


def test_clean_inherited_env_keeps_config_and_token(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/cfg")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")

    clean_inherited_env()

    assert os.environ["CLAUDE_CONFIG_DIR"] == "/tmp/cfg"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "token"


def test_clean_inherited_env_without_variables_is_noop(monkeypatch):
    for name in INHERITED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    clean_inherited_env()


def test_app_startup_cleans_inherited_env(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/cfg")

    with TestClient(create_app()):
        assert "CLAUDECODE" not in os.environ
        assert "CLAUDE_CODE_SESSION_ID" not in os.environ
        assert os.environ["CLAUDE_CONFIG_DIR"] == "/tmp/cfg"


# Error conversion ----------------------------------------------------------


def test_cli_not_found_becomes_readable_error():
    error = to_agent_error(CLINotFoundError())

    assert isinstance(error, AgentError)
    assert error.message_pt == "O comando `claude` não foi encontrado nesta máquina."


def test_connection_error_becomes_readable_error():
    error = to_agent_error(CLIConnectionError("boom"))

    assert "conectar" in error.message_pt


def test_process_error_becomes_readable_error():
    error = to_agent_error(ProcessError("died", exit_code=1))

    assert "encerrou" in error.message_pt
    assert "1" in error.message_pt


def test_agent_error_str_is_the_message():
    assert str(AgentError("Falhou.")) == "Falhou."


# Adapter over a stub SDK client -------------------------------------------


class StubSdkClient:
    """Stands in for ClaudeSDKClient: records calls, starts nothing."""

    def __init__(
        self, messages=(), connect_error=None, receive_error=None, control_error=None
    ):
        self.queries: list[Any] = []
        self.connected = False
        self.disconnected = False
        self.interrupts = 0
        self.models: list[Any] = []
        self.modes: list[str] = []
        self._messages = list(messages)
        self._connect_error = connect_error
        self._receive_error = receive_error
        self.control_error = control_error

    async def connect(self, prompt=None):
        if self._connect_error:
            raise self._connect_error
        self.connected = True

    async def query(self, prompt, session_id="default"):
        if isinstance(prompt, str):
            self.queries.append(prompt)
        else:
            self.queries.append([msg async for msg in prompt])

    async def receive_messages(self):
        for message in self._messages:
            yield message
        if self._receive_error:
            raise self._receive_error

    async def interrupt(self):
        self.interrupts += 1

    async def set_model(self, model=None):
        if self.control_error is not None:
            raise self.control_error
        self.models.append(model)

    async def set_permission_mode(self, mode):
        if self.control_error is not None:
            raise self.control_error
        self.modes.append(mode)

    async def get_server_info(self):
        return {"models": [{"value": "haiku"}]}

    async def disconnect(self):
        self.disconnected = True


@pytest.mark.anyio
async def test_send_text_uses_query_with_string(tmp_path):
    stub = StubSdkClient()
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    await client.send("olá")

    assert stub.queries == ["olá"]


@pytest.mark.anyio
async def test_send_blocks_streams_one_user_message(tmp_path):
    stub = StubSdkClient()
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()
    blocks = [
        {"type": "text", "text": "veja"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
        },
    ]

    await client.send(blocks)

    assert stub.queries == [
        [
            {
                "type": "user",
                "message": {"role": "user", "content": blocks},
                "parent_tool_use_id": None,
            }
        ]
    ]


@pytest.mark.anyio
async def test_connect_failure_becomes_agent_error(tmp_path):
    stub = StubSdkClient(connect_error=CLINotFoundError())
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)

    with pytest.raises(AgentError) as info:
        await client.connect()

    assert info.value.message_pt == "O comando `claude` não foi encontrado nesta máquina."


@pytest.mark.anyio
async def test_messages_yields_everything_then_converts_failure(tmp_path):
    stub = StubSdkClient(
        messages=["a", "b"], receive_error=ProcessError("died", exit_code=137)
    )
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()
    received = []

    with pytest.raises(AgentError):
        async for message in client.messages():
            received.append(message)

    assert received == ["a", "b"]


@pytest.mark.anyio
async def test_messages_converts_unknown_exception(tmp_path):
    stub = StubSdkClient(receive_error=Exception("Unknown error"))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError):
        async for _ in client.messages():
            pass


@pytest.mark.anyio
async def test_controls_are_forwarded(tmp_path):
    stub = StubSdkClient()
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    await client.interrupt()
    await client.set_model("sonnet")
    await client.set_model(None)
    await client.set_permission_mode("plan")
    await client.close()

    assert stub.interrupts == 1
    assert stub.models == ["sonnet", None]
    assert stub.modes == ["plan"]
    assert stub.disconnected is True


@pytest.mark.anyio
@pytest.mark.parametrize("method,arg", [("set_model", "opus"), ("set_permission_mode", "auto")])
async def test_control_refused_by_the_cli_is_marked_refused(tmp_path, method, arg):
    # The SDK raises a bare Exception with the CLI's text when it answers "error".
    text = "Cannot set permission mode to auto: auto mode unavailable for this model"
    stub = StubSdkClient(control_error=Exception(text))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await getattr(client, method)(arg)

    assert info.value.refused is True
    assert info.value.message_pt == text


@pytest.mark.anyio
@pytest.mark.parametrize("method,arg", [("set_model", "opus"), ("set_permission_mode", "plan")])
@pytest.mark.parametrize(
    "error",
    [
        ProcessError("died", exit_code=1),
        CLIConnectionError("Not connected. Call connect() first."),
        OSError("broken pipe"),
    ],
)
async def test_control_failure_of_the_process_is_not_refused(tmp_path, method, arg, error):
    stub = StubSdkClient(control_error=error)
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await getattr(client, method)(arg)

    assert info.value.refused is False


class _ScriptedQuery:
    """Stands in for `ClaudeSDKClient._query`: records control requests and answers
    them from a script (a response dict per request, or an exception to raise)."""

    def __init__(self, *responses: Any) -> None:
        self.requests: list[dict[str, Any]] = []
        self._responses = list(responses)

    async def _send_control_request(self, request: dict[str, Any], timeout: float = 60.0):
        self.requests.append(request)
        response = self._responses.pop(0) if self._responses else {}
        if isinstance(response, BaseException):
            raise response
        return response


def _stub_with_query(*responses: Any) -> StubSdkClient:
    stub = StubSdkClient()
    stub._query = _ScriptedQuery(*responses)
    return stub


@pytest.mark.anyio
async def test_set_effort_sends_flag_settings_then_checks_applied(tmp_path):
    stub = _stub_with_query({}, {"applied": {"effort": "low"}})
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    await client.set_effort("low")

    assert stub._query.requests == [
        {"subtype": "apply_flag_settings", "settings": {"effortLevel": "low"}},
        {"subtype": "get_settings"},
    ]


@pytest.mark.anyio
async def test_set_effort_mismatch_is_refused(tmp_path):
    stub = _stub_with_query({}, {"applied": {"effort": "high"}})
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await client.set_effort("low")

    assert info.value.refused is True
    assert info.value.message_pt == "O agente não aceitou o raciocínio low."


@pytest.mark.anyio
async def test_set_effort_cli_error_is_refused(tmp_path):
    stub = _stub_with_query(Exception("x"))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await client.set_effort("low")

    assert info.value.refused is True


@pytest.mark.anyio
async def test_set_effort_process_failure_is_not_refused(tmp_path):
    stub = _stub_with_query(OSError("broken pipe"))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await client.set_effort("low")

    assert info.value.refused is False


@pytest.mark.anyio
async def test_set_remote_control_enable_sends_keep_and_name(tmp_path):
    answer = {"session_url": "https://claude.ai/code/session_1", "bridge_session_id": "cse_1"}
    stub = _stub_with_query(answer)
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    result = await client.set_remote_control(True, name="T", reattach_session_id="cse_1")

    assert stub._query.requests == [
        {
            "subtype": "remote_control",
            "enabled": True,
            "name": "T",
            "keep_session_on_exit": True,
            "reattach_session_id": "cse_1",
        }
    ]
    assert result == answer


@pytest.mark.anyio
async def test_set_remote_control_enable_omits_missing_fields(tmp_path):
    stub = _stub_with_query({"session_url": "u"})
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    await client.set_remote_control(True)

    assert stub._query.requests == [
        {"subtype": "remote_control", "enabled": True, "keep_session_on_exit": True}
    ]


@pytest.mark.anyio
async def test_set_remote_control_disable(tmp_path):
    stub = _stub_with_query({})
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    result = await client.set_remote_control(False, name="ignored")

    assert stub._query.requests == [{"subtype": "remote_control", "enabled": False}]
    assert result == {}


@pytest.mark.anyio
async def test_set_remote_control_cli_error_is_refused(tmp_path):
    stub = _stub_with_query(Exception("disabled by policy"))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    await client.connect()

    with pytest.raises(AgentError) as info:
        await client.set_remote_control(True)

    assert info.value.refused is True
    assert info.value.message_pt == "disabled by policy"


def test_default_sdk_client_is_built_from_options(tmp_path):
    """Creating the adapter builds a ClaudeSDKClient but starts no process."""
    client = SdkAgentClient(make_options(tmp_path, model="haiku"))

    assert isinstance(client, AgentClient)
    assert client.sdk_options.model == "haiku"
    assert client.sdk_options.session_id == SESSION_ID


def test_build_options_forwards_stderr_callback(tmp_path):
    lines: list[str] = []
    sdk = build_sdk_options(make_options(tmp_path), stderr=lines.append)

    sdk.stderr("linha")

    assert lines == ["linha"]


@pytest.mark.anyio
async def test_connect_failure_with_session_in_use_on_stderr_is_flagged(tmp_path):
    stub = StubSdkClient(connect_error=ProcessError("Command failed", exit_code=1))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    # The real CLI writes this to stderr before exiting.
    client.sdk_options.stderr(f"Error: Session ID {SESSION_ID} is already in use.")

    with pytest.raises(AgentError) as info:
        await client.connect()

    assert info.value.session_in_use is True


@pytest.mark.anyio
async def test_connect_failure_with_session_in_use_in_process_error_is_flagged(tmp_path):
    stub = StubSdkClient(
        connect_error=ProcessError(
            "Command failed", exit_code=1, stderr=f"Session ID {SESSION_ID} is already in use."
        )
    )
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)

    with pytest.raises(AgentError) as info:
        await client.connect()

    assert info.value.session_in_use is True


@pytest.mark.anyio
async def test_other_connect_failures_are_not_flagged(tmp_path):
    stub = StubSdkClient(connect_error=ProcessError("Command failed", exit_code=1))
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)
    client.sdk_options.stderr("outra coisa")

    with pytest.raises(AgentError) as info:
        await client.connect()

    assert info.value.session_in_use is False


@pytest.mark.anyio
async def test_get_server_info_is_forwarded(tmp_path):
    client = SdkAgentClient(make_options(tmp_path), sdk_client=StubSdkClient())
    await client.connect()

    assert await client.get_server_info() == {"models": [{"value": "haiku"}]}


# MCP handshake after attach -------------------------------------------------


class RecordingBridge:
    def __init__(self, events: list[Any], name: str, error: Exception | None = None) -> None:
        self.events = events
        self.name = name
        self.error = error

    async def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        self.events.append((self.name, message))
        if self.error is not None:
            raise self.error
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {}} if "id" in message else None


class BridgedStub(StubSdkClient):
    def __init__(self, events: list[Any], bridges: dict[str, RecordingBridge]) -> None:
        super().__init__()
        self._events = events
        self._query = type("Q", (), {"_sdk_mcp_bridges": bridges})()

    async def connect(self, prompt=None):
        self._events.append("connect")
        await super().connect(prompt)


def _attach() -> AttachInfo:
    return AttachInfo(agentd_id="abc", from_pos=0, init_response=None)


@pytest.mark.anyio
async def test_connect_without_attach_does_not_handshake_sdk_mcp_servers(tmp_path):
    events: list[Any] = []
    stub = BridgedStub(events, {"maestro": RecordingBridge(events, "maestro")})
    client = SdkAgentClient(make_options(tmp_path), sdk_client=stub)

    await client.connect()

    assert events == ["connect"]


@pytest.mark.anyio
async def test_connect_with_attach_initializes_each_sdk_mcp_server(tmp_path):
    events: list[Any] = []
    stub = BridgedStub(events, {
        "maestro": RecordingBridge(events, "maestro"),
        "outro": RecordingBridge(events, "outro"),
    })
    client = SdkAgentClient(make_options(tmp_path, attach=_attach()), sdk_client=stub)

    await client.connect()

    assert events[0] == "connect"
    for name in ("maestro", "outro"):
        mine = [message for who, message in events[1:] if who == name]
        assert [m.get("method") for m in mine] == ["initialize", "notifications/initialized"]
        assert mine[0]["jsonrpc"] == "2.0" and "id" in mine[0]
        assert mine[0]["params"]["clientInfo"]["name"] == "claudio-maestro"
        assert "id" not in mine[1]


@pytest.mark.anyio
async def test_connect_with_attach_and_no_sdk_mcp_servers_is_fine(tmp_path):
    events: list[Any] = []
    stub = BridgedStub(events, {})
    await SdkAgentClient(make_options(tmp_path, attach=_attach()), sdk_client=stub).connect()
    # A stub without `_query` (not connected to the real SDK) is fine too.
    await SdkAgentClient(
        make_options(tmp_path, attach=_attach()), sdk_client=StubSdkClient()
    ).connect()

    assert events == ["connect"]


@pytest.mark.anyio
async def test_failed_mcp_handshake_does_not_fail_the_connect(tmp_path, caplog):
    events: list[Any] = []
    stub = BridgedStub(events, {
        "ruim": RecordingBridge(events, "ruim", error=RuntimeError("quebrou")),
        "bom": RecordingBridge(events, "bom"),
    })
    client = SdkAgentClient(make_options(tmp_path, attach=_attach()), sdk_client=stub)

    await client.connect()

    assert stub.connected is True
    assert any(who == "bom" for who, _ in events[1:])
    assert "ruim" in caplog.text


def test_sdk_still_has_the_private_api_the_reattach_handshake_uses():
    """The handshake after attach reaches into the SDK (`Query._sdk_mcp_bridges`,
    `SdkMcpBridge.handle`). If an upgrade removes them, this breaks instead of production."""
    import inspect

    from claude_agent_sdk._internal.query import Query
    from claude_agent_sdk._internal.sdk_mcp_bridge import SdkMcpBridge

    assert inspect.iscoroutinefunction(SdkMcpBridge.handle)
    query = Query(
        transport=None,  # type: ignore[arg-type]
        is_streaming_mode=True,
        sdk_mcp_servers={"maestro": _echo_server()["instance"]},
    )
    bridge = query._sdk_mcp_bridges["maestro"]
    assert isinstance(bridge, SdkMcpBridge)


@pytest.mark.anyio
async def test_real_bridge_accepts_the_reattach_handshake_then_lists_tools():
    from claude_agent_sdk._internal.sdk_mcp_bridge import SdkMcpBridge

    from claudio_maestro.agent.sdk_client import initialize_sdk_mcp_servers

    bridge = SdkMcpBridge("maestro", _echo_server()["instance"])
    query = type("Q", (), {"_sdk_mcp_bridges": {"maestro": bridge}})()
    stub = StubSdkClient()
    stub._query = query
    try:
        await initialize_sdk_mcp_servers(stub)
        listed = await bridge.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    finally:
        await bridge.aclose()

    assert listed is not None and "error" not in listed
    assert [t["name"] for t in listed["result"]["tools"]] == ["eco"]


def test_build_options_can_leave_out_the_bypass_switch(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, allow_bypass=False))

    assert "allow-dangerously-skip-permissions" not in sdk.extra_args
    assert "replay-user-messages" in sdk.extra_args


def test_build_options_allows_the_bypass_switch_by_default(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert "allow-dangerously-skip-permissions" in sdk.extra_args


@pytest.mark.anyio
async def test_missing_bridges_are_logged_when_the_options_have_sdk_servers(tmp_path, caplog):
    server = _echo_server()
    stub = StubSdkClient()  # no `_query`, as if the SDK renamed it
    client = SdkAgentClient(
        make_options(tmp_path, attach=_attach(), mcp_servers={"maestro": server}),
        sdk_client=stub,
    )

    with caplog.at_level(logging.WARNING):
        await client.connect()

    assert "maestro" in caplog.text and "ponte" in caplog.text


@pytest.mark.anyio
async def test_no_warning_without_sdk_servers_in_the_options(tmp_path, caplog):
    stub = StubSdkClient()
    client = SdkAgentClient(make_options(tmp_path, attach=_attach()), sdk_client=stub)

    with caplog.at_level(logging.WARNING):
        await client.connect()

    assert caplog.text == ""
