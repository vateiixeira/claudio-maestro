"""Authentication selection must preserve conversations and application data."""

import os
from dataclasses import replace

import pytest
from conftest import APP_ORIGIN, BACKEND_URL
from fastapi.testclient import TestClient

from claudio_maestro.agent.fake import FakeAgentFactory
from claudio_maestro.app import create_app
from claudio_maestro.claudeprofile import (
    ProfileError,
    active_auth_folder,
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


def test_saved_folder_preserves_history_and_metadata(home, data_dir):
    original = load_settings()
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    selected = load_settings()
    assert selected.claude_auth_dir == folder
    assert selected.claude_config_dir == original.claude_config_dir
    assert selected.claude_projects_dir == original.claude_projects_dir
    assert selected.data_dir == original.data_dir
    assert selected.db_path == original.db_path
    assert not (data_dir / "profiles").exists()
    save_selection(data_dir, None, home)
    assert load_settings().claude_auth_dir is None
    assert load_settings().data_dir == original.data_dir


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
    assert second.data_dir == data_dir


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


def test_auth_scope_restores_even_on_error_without_mutating_env(
    home, data_dir, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "original-test-secret")
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    settings = load_settings()
    original_env = os.environ.copy()
    assert active_auth_folder() is None
    with pytest.raises(RuntimeError):
        with profile_environment(settings):
            assert active_auth_folder() == folder
            assert os.environ == original_env
            raise RuntimeError("startup failure")
    assert active_auth_folder() is None
    assert os.environ == original_env


def test_long_unicode_path_roundtrips(home, data_dir):
    component = "😀" * 45
    # macOS limits the entire path to 1024 bytes, including pytest's temporary
    # directory. Exercise a long Unicode path that the filesystem can create.
    path_budget = os.pathconf(home, "PC_PATH_MAX") - len(os.fsencode(home)) - 64
    depth = min(17, path_budget // (len(os.fsencode(component)) + 1))
    assert depth > 0
    folder = home.joinpath(*[component for _ in range(depth)])
    folder.mkdir(parents=True)
    save_selection(data_dir, str(folder), home)
    assert read_selection(data_dir, home) == folder


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
        assert initial["active_source"] == "default"
        response = client.put("/api/claude-profile", json={"folder": str(folder)})
        assert response.status_code == 200
        state = response.json()
        assert state["active_folder"] == initial["active_folder"]
        assert state["active_source"] == "default"
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
    assert load_settings().data_dir == settings.data_dir


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


def test_restart_preserves_existing_data_and_history(home, data_dir):
    original = replace(
        load_settings(), routines_scheduler=False, remote_reconnect=False
    )
    history = original.claude_projects_dir / "project" / "existing.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text("original transcript\n")
    with TestClient(
        create_app(settings=original, agent_factory=FakeAgentFactory()),
        base_url=BACKEND_URL,
        headers=HEADERS,
    ) as client:
        assert (
            client.put(
                "/api/state/preferences", json={"editor_command": ["test-editor"]}
            ).status_code
            == 200
        )
        projects = client.get("/api/projects").json()
    folder = home / ".claude-api"
    folder.mkdir()
    save_selection(data_dir, str(folder), home)
    settings = replace(
        load_settings(),
        routines_scheduler=False,
        remote_reconnect=False,
        usage_check=True,
    )
    with TestClient(
        create_app(settings=settings, agent_factory=FakeAgentFactory()),
        base_url=BACKEND_URL,
        headers=HEADERS,
    ) as client:
        state = client.get("/api/claude-profile").json()
        assert state["active_folder"] == str(folder)
        assert state["active_source"] == "api_folder"
        assert state["restart_required"] is False
        assert settings.db_path == original.db_path
        assert settings.claude_projects_dir == original.claude_projects_dir
        assert client.get("/api/projects").json() == projects
        assert client.get("/api/state").json()["preferences"]["editor_command"] == [
            "test-editor"
        ]
        assert claude_config_dir() == original.claude_config_dir
        assert active_auth_folder() == folder
        assert client.app.state.usage.snapshot()["enabled"] is False
    assert active_auth_folder() is None
    assert history.read_text() == "original transcript\n"
    assert not (folder / "projects").exists()
    assert not (data_dir / "profiles").exists()
