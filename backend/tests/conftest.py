from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vibing.app import create_app

APP_ORIGIN = "http://localhost:6600"
BACKEND_URL = "http://127.0.0.1:6660"


@pytest.fixture
def anyio_backend() -> str:
    """Async tests (`@pytest.mark.anyio`) run on asyncio only."""
    return "asyncio"


@pytest.fixture(autouse=True)
def no_real_sdk_history(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default history functions must never reach the real SDK in tests."""
    monkeypatch.setattr("vibing.history.sdk_list_sessions", lambda directory: [])
    monkeypatch.setattr(
        "vibing.history.sdk_get_session_messages", lambda session_id, directory: []
    )
    monkeypatch.setattr(
        "vibing.history.sdk_read_tool_results", lambda session_id, directory: {}
    )
    monkeypatch.setattr(
        "vibing.history.sdk_session_file_mtime", lambda session_id, directory: None
    )
    monkeypatch.setattr(
        "vibing.history.sdk_session_file_exists", lambda session_id, directory: None
    )
    monkeypatch.setattr("vibing.history.sdk_read_transcript", lambda session_id, directory: None)
    monkeypatch.setattr("vibing.history.sdk_read_edits", lambda session_id, directory: [])
    monkeypatch.setattr("vibing.history.sdk_read_context", lambda session_id, directory: None)
    monkeypatch.setattr(
        "vibing.history.sdk_get_session_info", lambda session_id, directory: None
    )
    monkeypatch.setattr("vibing.history.sdk_folder_signature", lambda directory: None)
    monkeypatch.setattr("vibing.history.sdk_session_file", lambda session_id, directory: None)

    async def no_worktrees(repo):
        return []

    # The index would start git processes on every sync; slow and racy against the app's
    # startup sync. Tests of `git_worktrees` itself use history_fakes.REAL_GIT_WORKTREES.
    monkeypatch.setattr("vibing.history.git_worktrees", no_worktrees)
    monkeypatch.setattr(
        "vibing.sessions.sdk_rename_session", lambda session_id, title, directory: None
    )
    monkeypatch.setattr("vibing.sessions.sdk_history_exists", lambda session_id, cwd: False)

    def no_real_agent(options):
        raise RuntimeError("Os testes não podem criar o cliente real do SDK.")

    monkeypatch.setattr("vibing.sessions.default_agent_factory", no_real_agent)


@pytest.fixture(autouse=True)
def no_real_folder_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The native folder picker (zenity) is never opened in tests."""

    async def no_real_zenity(*argv, **kwargs):
        raise FileNotFoundError("zenity")

    monkeypatch.setattr("vibing.picker.default_spawn", no_real_zenity)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point home and data dirs to temporary folders in every test."""
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    monkeypatch.setenv("VIBING_HOME", str(home))
    monkeypatch.setenv("VIBING_DATA_DIR", str(data))
    # The CLI history watcher never looks at the real ~/.claude.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return (tmp_path / "home").resolve()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def client():
    """Client that looks like the frontend: valid Host and Origin."""
    with TestClient(
        create_app(), base_url=BACKEND_URL, headers={"origin": APP_ORIGIN, "x-vibing": "1"}
    ) as c:
        yield c
