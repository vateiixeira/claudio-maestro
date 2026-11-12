"""`pytest -n auto`: every core on the CI, half of them on a developer's machine."""

import conftest
import pytest


@pytest.fixture(autouse=True)
def sixteen_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    monkeypatch.setattr("os.process_cpu_count", lambda: 16)


def test_local_run_uses_half_the_cores():
    assert conftest.pytest_xdist_auto_num_workers(None) == 8


def test_single_core_still_gets_one_worker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("os.process_cpu_count", lambda: 1)
    assert conftest.pytest_xdist_auto_num_workers(None) == 1


def test_unknown_core_count_gets_one_worker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("os.process_cpu_count", lambda: None)
    assert conftest.pytest_xdist_auto_num_workers(None) == 1


def test_ci_leaves_the_choice_to_xdist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CI", "true")
    assert conftest.pytest_xdist_auto_num_workers(None) is None


def test_explicit_worker_count_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "3")
    assert conftest.pytest_xdist_auto_num_workers(None) is None
