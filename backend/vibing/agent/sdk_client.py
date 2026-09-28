"""Real agent client over `ClaudeSDKClient`.

Nothing here starts the `claude` process until `connect()` is called.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    Message,
    ProcessError,
)

from vibing.agent.base import AgentError, AgentOptions

# Variables that mark the process as a child of a Claude Code session. When the
# backend is started from inside one, the spawned `claude` misbehaves unless
# they are removed. Config and auth variables (CLAUDE_CONFIG_DIR,
# CLAUDE_CODE_OAUTH_TOKEN) are kept on purpose.
INHERITED_ENV_VARS: tuple[str, ...] = (
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
)

CLI_NOT_FOUND_MESSAGE = "O comando `claude` não foi encontrado nesta máquina."


def clean_inherited_env() -> None:
    """Remove from os.environ the variables inherited from a parent Claude Code session."""
    for name in INHERITED_ENV_VARS:
        os.environ.pop(name, None)


def build_sdk_options(options: AgentOptions) -> ClaudeAgentOptions:
    """Translate the app options into SDK options. Pure: starts nothing."""
    kwargs: dict[str, Any] = {
        "cwd": options.cwd,
        "include_partial_messages": True,
        "can_use_tool": options.can_use_tool,
    }
    if options.resume:
        kwargs["resume"] = options.session_id
    else:
        kwargs["session_id"] = options.session_id
    if options.model is not None:
        kwargs["model"] = options.model
    if options.effort is not None:
        kwargs["effort"] = options.effort
    if options.permission_mode is not None:
        kwargs["permission_mode"] = options.permission_mode
    return ClaudeAgentOptions(**kwargs)


def to_agent_error(error: BaseException) -> AgentError:
    """Turn an SDK failure into an AgentError with a readable pt-BR message."""
    if isinstance(error, AgentError):
        return error
    if isinstance(error, CLINotFoundError):
        return AgentError(CLI_NOT_FOUND_MESSAGE)
    if isinstance(error, CLIJSONDecodeError):
        return AgentError("O agente enviou uma resposta ilegível.")
    if isinstance(error, CLIConnectionError):
        return AgentError("Não foi possível conectar ao agente.")
    if isinstance(error, ProcessError):
        if error.exit_code is not None:
            return AgentError(
                f"O processo do agente encerrou inesperadamente (código {error.exit_code})."
            )
        return AgentError("O processo do agente encerrou inesperadamente.")
    if isinstance(error, ClaudeSDKError):
        return AgentError(f"Falha no agente: {error}")
    return AgentError(f"Falha inesperada no agente: {error}")


class SdkAgentClient:
    """AgentClient backed by the real SDK.

    `sdk_client` exists for tests: they pass a stub so no process is started.
    """

    def __init__(self, options: AgentOptions, sdk_client: Any | None = None) -> None:
        self.options = options
        self.sdk_options = build_sdk_options(options)
        self._client = sdk_client or ClaudeSDKClient(self.sdk_options)

    async def connect(self) -> None:
        try:
            await self._client.connect()
        except Exception as error:
            raise to_agent_error(error) from error

    async def send(self, content: str | list[dict[str, Any]]) -> None:
        try:
            if isinstance(content, str):
                await self._client.query(content)
            else:
                await self._client.query(_single_user_message(content))
        except Exception as error:
            raise to_agent_error(error) from error

    async def messages(self) -> AsyncIterator[Message]:
        # receive_messages keeps going after each ResultMessage, unlike
        # receive_response, so messages sent mid-turn are not lost.
        try:
            async for message in self._client.receive_messages():
                yield message
        except Exception as error:
            raise to_agent_error(error) from error

    async def interrupt(self) -> None:
        try:
            await self._client.interrupt()
        except Exception as error:
            raise to_agent_error(error) from error

    async def set_model(self, model: str | None) -> None:
        try:
            await self._client.set_model(model)
        except Exception as error:
            raise to_agent_error(error) from error

    async def set_permission_mode(self, mode: str) -> None:
        try:
            await self._client.set_permission_mode(mode)
        except Exception as error:
            raise to_agent_error(error) from error

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception as error:
            raise to_agent_error(error) from error


async def _single_user_message(
    blocks: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """One user message with content blocks, in the SDK streaming-input format."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": blocks},
        "parent_tool_use_id": None,
    }
