"""Real SDK client adapter, tested without starting the SDK or the `claude` process."""

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
)
from fastapi.testclient import TestClient
from vibing.agent.base import AgentClient, AgentError, AgentOptions
from vibing.agent.sdk_client import (
    INHERITED_ENV_VARS,
    SdkAgentClient,
    build_sdk_options,
    clean_inherited_env,
    to_agent_error,
)
from vibing.app import create_app

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


def test_build_options_does_not_set_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path))

    assert sdk.setting_sources == ClaudeAgentOptions().setting_sources


def test_build_options_passes_empty_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, setting_sources=[]))

    assert sdk.setting_sources == []


def test_build_options_passes_given_setting_sources(tmp_path):
    sdk = build_sdk_options(make_options(tmp_path, setting_sources=["user"]))

    assert sdk.setting_sources == ["user"]


# clean_inherited_env -------------------------------------------------------


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

    def __init__(self, messages=(), connect_error=None, receive_error=None):
        self.queries: list[Any] = []
        self.connected = False
        self.disconnected = False
        self.interrupts = 0
        self.models: list[Any] = []
        self.modes: list[str] = []
        self._messages = list(messages)
        self._connect_error = connect_error
        self._receive_error = receive_error

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
        self.models.append(model)

    async def set_permission_mode(self, mode):
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
