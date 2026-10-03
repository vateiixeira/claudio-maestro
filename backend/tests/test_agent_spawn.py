"""build_cli_spawn must produce exactly what the SDK's own connect() would spawn.

If this fails after an SDK upgrade, update spawn.py to match subprocess_cli.py.
"""

from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk._internal.transport import subprocess_cli

from claudio_maestro.agent.spawn import build_cli_spawn


class Captured(Exception):
    pass


@pytest.fixture
def fake_cli(monkeypatch):
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(
        subprocess_cli.SubprocessCLITransport, "_find_cli", lambda self: "/opt/fake/claude"
    )


async def _sdk_spawn(options: ClaudeAgentOptions, monkeypatch) -> dict:
    seen: dict = {}

    async def fake_open_process(cmd, **kwargs):
        seen.update(cmd=list(cmd), cwd=kwargs.get("cwd"), env=dict(kwargs.get("env") or {}))
        raise Captured

    monkeypatch.setattr(subprocess_cli.anyio, "open_process", fake_open_process)
    with pytest.raises(Exception):
        await ClaudeSDKClient(options).connect()
    return seen


async def _allow(*_args):
    return None


@pytest.mark.anyio
@pytest.mark.parametrize("extra", [
    {"session_id": "11111111-1111-1111-1111-111111111111"},
    {"resume": "22222222-2222-2222-2222-222222222222", "model": "haiku",
     "permission_mode": "plan", "effort": "high"},
    {"session_id": "33333333-3333-3333-3333-333333333333",
     "env": {"CLAUDE_CODE_ENTRYPOINT": "claudio-maestro"}, "setting_sources": []},
])
async def test_matches_sdk_connect(tmp_path: Path, monkeypatch, fake_cli, extra):
    options = ClaudeAgentOptions(
        cwd=tmp_path, include_partial_messages=True, forward_subagent_text=True,
        can_use_tool=_allow, max_buffer_size=64 * 1024 * 1024, **extra,
    )
    sdk = await _sdk_spawn(options, monkeypatch)
    ours = build_cli_spawn(options)
    assert ours.cmd == sdk["cmd"]
    assert ours.cwd == sdk["cwd"]
    assert ours.env == sdk["env"]
    assert "--permission-prompt-tool" in ours.cmd  # can_use_tool routed over stdio


def _options(tmp_path: Path, **extra) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=tmp_path, can_use_tool=_allow, session_id="44444444-4444-4444-4444-444444444444", **extra
    )


@pytest.mark.anyio
async def test_matches_sdk_with_file_checkpointing(tmp_path: Path, monkeypatch, fake_cli):
    options = _options(tmp_path, enable_file_checkpointing=True)
    sdk = await _sdk_spawn(options, monkeypatch)
    ours = build_cli_spawn(options)
    assert ours.env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] == "true"
    assert (ours.cmd, ours.cwd, ours.env) == (sdk["cmd"], sdk["cwd"], sdk["env"])


@pytest.mark.anyio
async def test_matches_sdk_filters_inherited_claudecode(tmp_path: Path, monkeypatch, fake_cli):
    monkeypatch.setenv("CLAUDECODE", "1")
    options = _options(tmp_path)
    sdk = await _sdk_spawn(options, monkeypatch)
    ours = build_cli_spawn(options)
    assert "CLAUDECODE" not in ours.env
    assert (ours.cmd, ours.cwd, ours.env) == (sdk["cmd"], sdk["cwd"], sdk["env"])


@pytest.mark.anyio
async def test_matches_sdk_with_caller_session_state_env(tmp_path: Path, monkeypatch, fake_cli):
    options = _options(tmp_path, env={"CLAUDE_CODE_SDK_READS_SESSION_STATE": "0"})
    sdk = await _sdk_spawn(options, monkeypatch)
    ours = build_cli_spawn(options)
    assert ours.env["CLAUDE_CODE_SDK_READS_SESSION_STATE"] == "0"
    assert (ours.cmd, ours.cwd, ours.env) == (sdk["cmd"], sdk["cwd"], sdk["env"])


@pytest.mark.anyio
@pytest.mark.parametrize("option_env", [{}, {"TRACESTATE": "own=1"}])
async def test_matches_sdk_with_active_trace_context(
    tmp_path: Path, monkeypatch, fake_cli, option_env
):
    from opentelemetry import propagate

    def fake_inject(carrier, *args, **kwargs):
        carrier["traceparent"] = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        carrier["tracestate"] = "x=1"

    monkeypatch.setattr(propagate, "inject", fake_inject)
    monkeypatch.setenv("TRACESTATE", "stale=1")
    monkeypatch.setenv("TRACEPARENT", "00-stale-stale-00")
    options = _options(tmp_path, env=option_env)
    sdk = await _sdk_spawn(options, monkeypatch)
    ours = build_cli_spawn(options)
    assert ours.env["TRACEPARENT"].startswith("00-0af7")
    assert (ours.cmd, ours.cwd, ours.env) == (sdk["cmd"], sdk["cwd"], sdk["env"])
