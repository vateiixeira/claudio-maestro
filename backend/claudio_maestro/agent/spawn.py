"""The `claude` command line and environment, exactly as the SDK builds them.

The agentd starts the process for the backend, so the backend has to build what
`SubprocessCLITransport.connect()` would pass to `anyio.open_process`. This uses
the SDK's own `_build_command()`; the environment block mirrors
`subprocess_cli.py` (connect). `tests/test_agent_spawn.py` compares both and
breaks when the SDK changes.
"""

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.transport.subprocess_cli import (
    _SDK_READS_SESSION_STATE_ENV,
    SubprocessCLITransport,
)
from claude_agent_sdk._version import __version__
from claude_agent_sdk.types import _configure_can_use_tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpawnSpec:
    # Not carried: `options.user` and the stderr callback. The agentd always
    # pipes stderr and runs the process as its own user.
    cmd: list[str]
    cwd: str | None
    env: dict[str, str]


async def _no_prompt() -> AsyncIterator[dict[str, Any]]:
    return
    yield  # pragma: no cover - makes this an async generator


def build_cli_spawn(sdk_options: ClaudeAgentOptions) -> SpawnSpec:
    options = _configure_can_use_tool(sdk_options)
    transport = SubprocessCLITransport(prompt=_no_prompt(), options=options)
    if transport._cli_path is None:
        transport._cli_path = transport._find_cli()
    cmd = transport._build_command()
    inherited = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env: dict[str, str] = {
        **inherited,
        "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
        **options.env,
        "CLAUDE_AGENT_SDK_VERSION": __version__,
    }
    # Propagate the active OTEL trace context, as connect() does. No-op without
    # opentelemetry-api or an active span.
    try:
        from opentelemetry import propagate

        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        if "traceparent" in carrier:
            for key in ("TRACEPARENT", "TRACESTATE"):
                if key not in options.env:
                    env.pop(key, None)
            for k, v in carrier.items():
                key = k.upper()
                if key not in options.env:
                    env[key] = v
    except Exception:  # noqa: BLE001 - best-effort tracing must never break the spawn
        logger.debug("OTEL trace context injection failed", exc_info=True)
    if not any(key.upper() == _SDK_READS_SESSION_STATE_ENV for key in env):
        env[_SDK_READS_SESSION_STATE_ENV] = "1"
    if options.enable_file_checkpointing:
        env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "true"
    cwd = str(options.cwd) if options.cwd else None
    if cwd:
        env["PWD"] = cwd
    return SpawnSpec(cmd=cmd, cwd=cwd, env=env)
