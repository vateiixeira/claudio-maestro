"""Native folder picker (zenity) run through an injected process starter."""

import asyncio
import os
from pathlib import Path

import pytest

from claudio_maestro import picker


class FakeProcess:
    def __init__(self, code: int = 0, out: bytes = b"", err: bytes = b"", hang: bool = False):
        self.returncode: int | None = None if hang else code
        self._out = out
        self._err = err
        self._hang = hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(3600)
        return self._out, self._err

    def kill(self):
        self.killed = True
        self.returncode = -9

    async def wait(self):
        return self.returncode


class Spawner:
    def __init__(self, process: FakeProcess | None = None, error: Exception | None = None):
        self.process = process
        self.error = error
        self.calls: list[tuple[tuple, dict]] = []

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error:
            raise self.error
        return self.process


@pytest.mark.anyio
async def test_argv_is_a_list_without_shell(tmp_path: Path):
    spawner = Spawner(FakeProcess(0, b"/x\n"))
    initial = tmp_path / "Área de trabalho"
    await picker.pick_folder(initial, spawn=spawner)
    argv, kwargs = spawner.calls[0]
    assert argv == ("zenity", "--file-selection", "--directory", f"--filename={initial}/")
    assert kwargs.get("stdin") == asyncio.subprocess.DEVNULL
    assert "shell" not in kwargs


@pytest.mark.anyio
async def test_returns_chosen_path(tmp_path: Path):
    chosen = tmp_path / "pasta com espaço"
    spawner = Spawner(FakeProcess(0, os.fsencode(chosen) + b"\n"))
    assert await picker.pick_folder(tmp_path, spawn=spawner) == str(chosen)


@pytest.mark.anyio
async def test_cancel_returns_none(tmp_path: Path):
    assert await picker.pick_folder(tmp_path, spawn=Spawner(FakeProcess(1))) is None


@pytest.mark.anyio
async def test_empty_output_returns_none(tmp_path: Path):
    assert await picker.pick_folder(tmp_path, spawn=Spawner(FakeProcess(0, b"\n"))) is None


@pytest.mark.anyio
async def test_missing_zenity_is_unavailable(tmp_path: Path):
    spawner = Spawner(error=FileNotFoundError("zenity"))
    with pytest.raises(picker.PickerUnavailableError):
        await picker.pick_folder(tmp_path, spawn=spawner)


@pytest.mark.anyio
async def test_no_display_is_unavailable(tmp_path: Path):
    spawner = Spawner(FakeProcess(1, b"", b"Gtk-WARNING: cannot open display: \n"))
    with pytest.raises(picker.PickerUnavailableError):
        await picker.pick_folder(tmp_path, spawn=spawner)


@pytest.mark.anyio
async def test_other_failure_is_an_error(tmp_path: Path):
    with pytest.raises(picker.PickerError):
        await picker.pick_folder(tmp_path, spawn=Spawner(FakeProcess(255, b"", b"boom")))


@pytest.mark.anyio
async def test_timeout_kills_process(tmp_path: Path):
    process = FakeProcess(hang=True)
    with pytest.raises(picker.PickerTimeoutError):
        await picker.pick_folder(tmp_path, timeout=0.05, spawn=Spawner(process))
    assert process.killed


@pytest.mark.anyio
async def test_cancellation_kills_process(tmp_path: Path):
    process = FakeProcess(hang=True)
    task = asyncio.create_task(picker.pick_folder(tmp_path, spawn=Spawner(process)))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed


def test_default_timeout_is_five_minutes():
    assert picker.PICK_TIMEOUT == 300
