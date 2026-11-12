"""Invalidation scope is independent from unchanged summary counts."""

import asyncio
from types import SimpleNamespace

from claudio_maestro import gitinfo
from claudio_maestro.gitmonitor import GitMonitor


def test_unknown_refs_signature_keeps_reconciling(tmp_path, monkeypatch):
    events = []
    monitor = GitMonitor(tmp_path / "unused.db", SimpleNamespace(publish=events.append))
    monkeypatch.setattr(monitor, "_project_path", lambda _id: tmp_path)

    async def scan(_root):
        return [SimpleNamespace(to_dict=lambda: {"path": str(tmp_path), "refs_signature": None})], False

    monkeypatch.setattr(gitinfo, "project_repos_scan", scan)

    async def refresh():
        await monitor.refresh_project(1)
        await monitor.refresh_project(1)

    asyncio.run(refresh())
    assert len(events) == 2
    assert events[-1]["data"]["changed_repos"] == [str(tmp_path)]


def test_generic_force_invalidates_even_identical_summary(tmp_path, monkeypatch):
    events = []
    monitor = GitMonitor(tmp_path / "unused.db", SimpleNamespace(publish=events.append))
    monkeypatch.setattr(monitor, "_project_path", lambda _id: tmp_path)

    async def scan(_root):
        return [SimpleNamespace(to_dict=lambda: {"path": str(tmp_path), "refs_signature": "same"})], False

    monkeypatch.setattr(gitinfo, "project_repos_scan", scan)

    async def refresh():
        await monitor.refresh_project(1)
        await monitor.refresh_project(1)
        await monitor.refresh_project(1, force=True)

    asyncio.run(refresh())
    assert len(events) == 2
    assert events[-1]["data"]["changed_repos"] is None
