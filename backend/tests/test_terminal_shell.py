"""Choice of the terminal shell: bash needs 4.4 (the `PS0` of the marks), otherwise zsh."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

from claudio_maestro import terminal as terminal_module
from claudio_maestro.terminal import TerminalStartError, _pick_shell


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No fixed path of the machine takes part; the PATH is empty until a test sets it."""
    terminal_module._BASH_VERSIONS.clear()
    monkeypatch.setattr(terminal_module, "BASH_FALLBACKS", ())
    monkeypatch.setattr(terminal_module, "ZSH_FALLBACK", str(tmp_path / "nowhere" / "zsh"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.delenv("SHELL", raising=False)
    yield
    terminal_module._BASH_VERSIONS.clear()


def fake_bash(folder: Path, version: str, name: str = "bash") -> Path:
    """An executable `bash` that prints `version` and logs one line per query."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(f"#!/bin/sh\necho x >> '{folder}/{name}.log'\nprintf '{version}'\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def fake_zsh(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "zsh"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def set_path(monkeypatch: pytest.MonkeyPatch, *folders: Path) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join(str(folder) for folder in folders))


def test_old_shell_bash_loses_to_a_new_bash_in_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = fake_bash(tmp_path / "system", "3.2")
    new = fake_bash(tmp_path / "brew", "5.2")
    set_path(monkeypatch, tmp_path / "brew")
    monkeypatch.setenv("SHELL", str(old))
    assert _pick_shell(None) == str(new)


def test_shell_bash_wins_when_it_is_new_enough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mine = fake_bash(tmp_path / "mine", "4.4")
    fake_bash(tmp_path / "brew", "5.2")
    set_path(monkeypatch, tmp_path / "brew")
    monkeypatch.setenv("SHELL", str(mine))
    assert _pick_shell(None) == str(mine)


def test_old_bash_and_zsh_picks_zsh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bash(tmp_path / "bin", "3.2")
    zsh = fake_zsh(tmp_path / "bin")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("SHELL", str(tmp_path / "bin" / "bash"))
    assert _pick_shell(None) == str(zsh)


def test_only_an_old_bash_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bash(tmp_path / "bin", "3.2")
    set_path(monkeypatch, tmp_path / "bin")
    with pytest.raises(TerminalStartError, match="bash 4.4"):
        _pick_shell(None)


def test_no_shell_at_all_is_an_error() -> None:
    with pytest.raises(TerminalStartError, match="zsh"):
        _pick_shell(None)


def test_broken_bash_does_not_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    broken = folder / "bash"
    broken.write_text("#!/bin/sh\nprintf 'not a version'\n")
    broken.chmod(0o755)
    zsh = fake_zsh(folder)
    set_path(monkeypatch, folder)
    assert _pick_shell(None) == str(zsh)


def test_hanging_bash_does_not_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    slow = folder / "bash"
    slow.write_text("#!/bin/sh\nexec sleep 30\n")
    slow.chmod(0o755)
    zsh = fake_zsh(folder)
    set_path(monkeypatch, folder)
    monkeypatch.setattr(terminal_module, "BASH_CHECK_SECONDS", 0.2)
    assert _pick_shell(None) == str(zsh)


def test_homebrew_bash_is_found_outside_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    brew = fake_bash(tmp_path / "opt", "5.2")
    fake_zsh(tmp_path / "bin")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setattr(terminal_module, "BASH_FALLBACKS", (str(tmp_path / "nope"), str(brew)))
    assert _pick_shell(None) == str(brew)


def test_path_bash_wins_over_homebrew_and_zsh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inpath = fake_bash(tmp_path / "bin", "5.0")
    fake_zsh(tmp_path / "bin")
    brew = fake_bash(tmp_path / "opt", "5.2")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setattr(terminal_module, "BASH_FALLBACKS", (str(brew),))
    assert _pick_shell(None) == str(inpath)


def test_shell_zsh_is_kept_even_with_a_good_bash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_bash(tmp_path / "bin", "5.2")
    zsh = fake_zsh(tmp_path / "zbin")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("SHELL", str(zsh))
    assert _pick_shell(None) == str(zsh)


def test_named_zsh_comes_from_the_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zsh = fake_zsh(tmp_path / "bin")
    set_path(monkeypatch, tmp_path / "bin")
    assert _pick_shell("zsh") == str(zsh)


def test_missing_zsh_falls_back_to_the_bash_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bash = fake_bash(tmp_path / "bin", "5.2")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("SHELL", str(tmp_path / "gone" / "zsh"))
    assert _pick_shell(None) == str(bash)


def test_system_zsh_is_the_last_resort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bash(tmp_path / "bin", "3.2")
    system = fake_zsh(tmp_path / "system")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setattr(terminal_module, "ZSH_FALLBACK", str(system))
    assert _pick_shell(None) == str(system)


def test_other_shell_is_treated_like_an_undefined_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bash = fake_bash(tmp_path / "bin", "5.2")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    assert _pick_shell(None) == str(bash)


def test_version_is_asked_once_per_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bash = fake_bash(tmp_path / "bin", "5.2")
    set_path(monkeypatch, tmp_path / "bin")
    monkeypatch.setenv("SHELL", str(bash))
    for _ in range(3):
        assert _pick_shell(None) == str(bash)
    assert (tmp_path / "bin" / "bash.log").read_text().count("x") == 1


def test_version_check_uses_a_list_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        seen.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="5.2", stderr="")

    monkeypatch.setattr(terminal_module.subprocess, "run", fake_run)
    assert terminal_module._bash_version("/x/bash") == (5, 2)
    args = seen["args"]
    assert isinstance(args, list) and args[:4] == ["/x/bash", "--norc", "--noprofile", "-c"]
    assert not seen.get("shell")
    assert seen["timeout"] == terminal_module.BASH_CHECK_SECONDS
    assert seen["stdin"] == subprocess.DEVNULL
    env = seen["env"]
    assert isinstance(env, dict) and "SHELL" not in env and "HOME" not in env


def test_a_timeout_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first run of a binary can be slow (Gatekeeper on macOS); the next try may work."""
    folder = tmp_path / "bin"
    folder.mkdir()
    slow = folder / "bash"
    slow.write_text("#!/bin/sh\nexec sleep 30\n")
    slow.chmod(0o755)
    monkeypatch.setattr(terminal_module, "BASH_CHECK_SECONDS", 0.2)
    assert terminal_module._bash_version(str(slow)) is None
    slow.write_text("#!/bin/sh\nprintf 5.2\n")
    assert terminal_module._bash_version(str(slow)) == (5, 2)


def test_a_missing_file_is_not_cached(tmp_path: Path) -> None:
    path = tmp_path / "bash"
    assert terminal_module._bash_version(str(path)) is None
    path.write_text("#!/bin/sh\nprintf 5.2\n")
    path.chmod(0o755)
    assert terminal_module._bash_version(str(path)) == (5, 2)


def test_an_invalid_answer_is_cached(tmp_path: Path) -> None:
    folder = tmp_path / "bin"
    bash = fake_bash(folder, "not a version")
    assert terminal_module._bash_version(str(bash)) is None
    assert terminal_module._bash_version(str(bash)) is None
    assert (folder / "bash.log").read_text().count("x") == 1
