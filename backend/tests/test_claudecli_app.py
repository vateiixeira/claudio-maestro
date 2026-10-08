"""The app wires the chosen `claude` into the SDK clients."""

import time
from pathlib import Path

from conftest import BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.agent.base import AgentOptions
from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.claudecli import ClaudeCliResolver
from claudio_maestro.config import Settings


class FakeResolver(ClaudeCliResolver):
    def __init__(self, path: str | None) -> None:
        super().__init__(
            env={},
            bundled_version="2.1.284",
            which=lambda name: path,
            run_version=lambda p: "2.1.292 (Claude Code)",
        )
        self.refreshes: list[bool] = []
        self.periodic: list[float] = []

    async def refresh(self, force: bool = False):
        self.refreshes.append(force)
        return await super().refresh(force)

    async def run_periodic(self, interval, sleep=None):
        self.periodic.append(interval)


def deny(*args, **kwargs):
    raise AssertionError


def settings(home: Path, data_dir: Path) -> Settings:
    return Settings(home_dir=home, data_dir=data_dir, update_check=False, usage_check=False)


def test_real_agent_reads_the_choice_at_startup_and_uses_it(home, data_dir):
    resolver = FakeResolver("/opt/bin/claude")
    app = create_app(
        settings=settings(home, data_dir),
        claude_cli=resolver,
        agentd=False,
        refresh_models=False,
        plan_sweep=False,
    )
    with TestClient(app, base_url=BACKEND_URL) as client:
        assert resolver.refreshes == [False]
        assert resolver.periodic == [600]
        assert client.app.state.claude_cli is resolver
        options = AgentOptions(cwd=home, session_id="x", resume=False, can_use_tool=deny)
        sdk_client = client.app.state.sessions.agent_factory(options)
        assert sdk_client.sdk_options.cli_path == "/opt/bin/claude"


def test_fake_agent_does_not_read_the_choice(home, data_dir):
    resolver = FakeResolver("/opt/bin/claude")
    app = create_app(
        settings=settings(home, data_dir), claude_cli=resolver, agent_factory=FakeAgentFactory()
    )
    with TestClient(app, base_url=BACKEND_URL):
        assert resolver.refreshes == []
        assert resolver.periodic == []


def test_default_resolver_exists(home, data_dir):
    app = create_app(settings=settings(home, data_dir), agent_factory=FakeAgentFactory())
    with TestClient(app, base_url=BACKEND_URL) as client:
        assert isinstance(client.app.state.claude_cli, ClaudeCliResolver)
        assert client.app.state.claude_cli.cli_path() is None


def test_real_agent_with_models_refresh_never_connects_to_the_real_sdk(
    home, data_dir, sdk_connect_attempts
):
    # At startup the models refresh builds a throwaway client with `sdk_agent_factory`; the
    # conftest cuts the SDK's `connect` and records the attempt instead of starting `claude`.
    resolver = FakeResolver("/opt/bin/claude")
    app = create_app(
        settings=settings(home, data_dir), claude_cli=resolver, agentd=False, plan_sweep=False
    )
    with TestClient(app, base_url=BACKEND_URL):
        deadline = time.monotonic() + 5
        while not sdk_connect_attempts and time.monotonic() < deadline:
            time.sleep(0.02)
    assert len(sdk_connect_attempts) == 1
