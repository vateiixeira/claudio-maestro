"""Folder selection must never mix profiles or touch credential files."""

import json
import os
from dataclasses import replace

import pytest
from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.claudeprofile import (
    ProfileError,
    profile_environment,
    read_selection,
    save_selection,
    validate_folder,
)
from claudio_maestro.config import claude_config_dir, load_settings

HEADERS = {"origin": APP_ORIGIN, "x-maestro": "1"}


def test_folder_validation(home, tmp_path):
    folder = home / ".claude-api"
    folder.mkdir()
    assert validate_folder("~/.claude-api", home) == folder
    assert validate_folder(str(folder), home) == folder
    (home / "alias").symlink_to(folder, target_is_directory=True)
    assert validate_folder(str(home / "alias"), home) == folder
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / "escape").symlink_to(outside, target_is_directory=True)
    for raw in [
        "",
        ".claude-api",
        str(outside),
        str(home / "escape"),
        str(home / "missing"),
        "a\x00b",
        str(home),
    ]:
        with pytest.raises(ProfileError):
            validate_folder(raw, home)
    (home / "file").write_text("not a directory")
    with pytest.raises(ProfileError):
        validate_folder(str(home / "file"), home)


def test_saved_folder_isolated_and_reset_returns_original(home, data_dir):
    original = load_settings()
    folder = home / ".claude-api"
    folder.mkdir()
    credentials = folder / ".credentials.json"
    credentials.write_text('{"secret":"never read or copy"}')
    save_selection(data_dir, str(folder), home)
    selected = load_settings()
    assert selected.claude_config_dir == folder
    assert selected.claude_projects_dir == folder / "projects"
    assert selected.data_dir != original.data_dir
    assert selected.data_dir.is_relative_to(data_dir / "profiles")
    assert selected.profile_root == data_dir
    assert load_settings().data_dir == selected.data_dir
    assert credentials.read_text() == '{"secret":"never read or copy"}'
    assert not selected.data_dir.exists()  # startup creates the data, selecting doesn't
    save_selection(data_dir, None, home)
    assert load_settings().data_dir == original.data_dir
    assert load_settings().claude_config_dir == original.claude_config_dir


def test_default_folder_uses_existing_data(home, data_dir):
    original = load_settings()
    folder = original.claude_config_dir
    folder.mkdir(parents=True, exist_ok=True)
    # Original environment path may live outside MAESTRO_HOME; selecting a custom
    # folder still must stay inside the home boundary.
    save_selection(data_dir, None, home)
    assert load_settings().data_dir == data_dir


def test_default_profile_preserves_unset_config_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    settings = load_settings()
    with profile_environment(settings):
        assert "CLAUDE_CONFIG_DIR" not in os.environ


def test_selected_profile_identity_survives_different_launch_environment(
    home, data_dir, monkeypatch
):
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    first = load_settings()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(folder))
    second = load_settings()
    assert second.data_dir == first.data_dir
    assert second.data_dir != data_dir


def test_invalid_saved_selection_fails_closed(home, data_dir):
    data_dir.mkdir()
    (data_dir / "claude-profile.json").write_text('{"folder":"/outside"}')
    with pytest.raises(ProfileError):
        load_settings()


def test_invalid_encoding_is_a_profile_error(data_dir):
    data_dir.mkdir()
    (data_dir / "claude-profile.json").write_bytes(b"\xff")
    with pytest.raises(ProfileError):
        load_settings()
    (data_dir / "claude-profile.json").write_text("broken json")
    with pytest.raises(ProfileError):
        load_settings()


def test_environment_lasts_for_lifespan_and_restores_even_on_error(
    home, data_dir, monkeypatch
):
    original_env = os.environ["CLAUDE_CONFIG_DIR"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "original-test-secret")
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    settings = load_settings()
    with pytest.raises(RuntimeError):
        with profile_environment(settings):
            assert claude_config_dir() == folder
            assert "ANTHROPIC_API_KEY" not in os.environ
            raise RuntimeError("startup failure")
    assert os.environ["CLAUDE_CONFIG_DIR"] == original_env
    assert os.environ["ANTHROPIC_API_KEY"] == "original-test-secret"


def test_long_unicode_path_roundtrips(home, data_dir):
    folder = home.joinpath(*["😀" * 45 for _ in range(17)])
    folder.mkdir(parents=True)
    save_selection(data_dir, str(folder), home)
    assert read_selection(data_dir, home) == folder


def test_custom_profile_clears_inherited_provider_in_spawn(home, data_dir, monkeypatch):
    from claude_agent_sdk import ClaudeAgentOptions

    from claudio_maestro.agent.spawn import build_cli_spawn

    inherited = {
        "ANTHROPIC_BASE_URL": "https://old-gateway.invalid",
        "ANTHROPIC_API_KEY": "old-test-key",
        "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_USE_VERTEX": "1",
        "CLAUDE_CODE_USE_FOUNDRY": "1",
        "CLAUDE_CODE_SKIP_VERTEX_AUTH": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "old-test-oauth",
    }
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    with profile_environment(load_settings()):
        spec = build_cli_spawn(ClaudeAgentOptions(cwd=str(home)))
        assert spec.env["CLAUDE_CONFIG_DIR"] == str(folder)
        assert all(key not in spec.env for key in inherited)
        assert all(
            value not in str(spec.cmd) for value in inherited.values() if len(value) > 1
        )
    assert all(os.environ[key] == value for key, value in inherited.items())


def test_api_save_is_pending_until_restart_and_can_cancel(home, data_dir):
    folder = home / ".claude-api"
    folder.mkdir()
    factory = FakeAgentFactory()
    settings = replace(
        load_settings(), routines_scheduler=False, remote_reconnect=False
    )
    app = create_app(settings=settings, agent_factory=factory)
    with TestClient(app, base_url=BACKEND_URL, headers=HEADERS) as client:
        initial = client.get("/api/claude-profile").json()
        response = client.put("/api/claude-profile", json={"folder": str(folder)})
        assert response.status_code == 200
        state = response.json()
        assert state["active_folder"] == initial["active_folder"]
        assert state["selected_folder"] == str(folder)
        assert state["restart_required"] is True
        assert claude_config_dir() == settings.claude_config_dir
        assert client.get("/api/claude-profile").json() == state
        assert (
            client.put("/api/claude-profile", json={"folder": None}).json()[
                "restart_required"
            ]
            is False
        )
        assert (
            client.put("/api/claude-profile", json={"folder": "/etc"}).status_code
            == 400
        )
        assert (
            client.put("/api/claude-profile", json={"folder": 123}).status_code == 422
        )
        assert (
            client.get("/api/claude-profile", headers={"x-maestro": ""}).status_code
            == 403
        )
        assert (
            client.put(
                "/api/claude-profile",
                json={"folder": None},
                headers={"origin": "https://other.test"},
            ).status_code
            == 403
        )
        assert factory.clients == []


def test_same_folder_explicit_profile_still_needs_restart(home, data_dir, monkeypatch):
    folder = home / ".claude"
    folder.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(folder))
    settings = replace(
        load_settings(), routines_scheduler=False, remote_reconnect=False
    )
    with TestClient(
        create_app(settings=settings, agent_factory=FakeAgentFactory()),
        base_url=BACKEND_URL,
        headers=HEADERS,
    ) as client:
        result = client.put("/api/claude-profile", json={"folder": str(folder)})
        assert result.status_code == 200
        assert result.json()["restart_required"] is True
    assert load_settings().data_dir != settings.data_dir


def test_invalid_pending_selection_can_be_reset(home, data_dir):
    settings = replace(
        load_settings(), routines_scheduler=False, remote_reconnect=False
    )
    with TestClient(
        create_app(settings=settings, agent_factory=FakeAgentFactory()),
        base_url=BACKEND_URL,
        headers=HEADERS,
    ) as client:
        (data_dir / "claude-profile.json").write_bytes(b"\xff")
        assert client.get("/api/claude-profile").status_code == 400
        response = client.put("/api/claude-profile", json={"folder": None})
        assert response.status_code == 200
        assert response.json()["restart_required"] is False


def test_restart_reads_selected_history_and_uses_separate_database(home, data_dir):
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    settings = replace(
        load_settings(), routines_scheduler=False, remote_reconnect=False
    )
    with TestClient(
        create_app(settings=settings, agent_factory=FakeAgentFactory()),
        base_url=BACKEND_URL,
        headers=HEADERS,
    ) as client:
        state = client.get("/api/claude-profile").json()
        assert state["active_folder"] == str(folder)
        assert state["restart_required"] is False
        assert client.app.state.settings.db_path.is_file()
        assert not (data_dir / "maestro.db").exists()
        assert claude_config_dir() == folder
    assert claude_config_dir() != folder
    assert json.loads((data_dir / "claude-profile.json").read_text()) == {
        "folder": str(folder)
    }
