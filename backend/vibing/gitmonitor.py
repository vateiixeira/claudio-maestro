"""Publishes `project.git` when a project's repositories change."""

import asyncio
import logging
from contextlib import closing
from pathlib import Path
from typing import Any

from vibing import db, gitinfo, projects
from vibing.events import EventHub

logger = logging.getLogger(__name__)


class GitMonitor:
    def __init__(self, db_path: Path, hub: EventHub) -> None:
        self._db_path = db_path
        self._hub = hub
        self._last: dict[int, tuple[list[dict[str, Any]], bool]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _project_path(self, project_id: int) -> Path | None:
        with closing(db.connect(self._db_path)) as conn:
            try:
                project = projects.get_project(conn, project_id)
            except projects.ProjectNotFoundError:
                return None
        return Path(project.path) if project.available else None

    async def refresh_project(self, project_id: int) -> None:
        """Read the project's repositories and publish them if anything changed."""
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            path = await asyncio.to_thread(self._project_path, project_id)
            if path is None:
                self._last.pop(project_id, None)
                return
            found, limit_reached = await gitinfo.project_repos_scan(path)
            repos = [repo.to_dict() for repo in found]
            if self._last.get(project_id) == (repos, limit_reached):
                return
            self._last[project_id] = (repos, limit_reached)
            self._hub.publish(
                {"session_id": None, "seq": 0, "type": "project.git",
                 "data": {"project_id": project_id, "repos": repos, "limit_reached": limit_reached}}
            )

    async def refresh_all(self) -> None:
        def ids() -> list[int]:
            with closing(db.connect(self._db_path)) as conn:
                return [p.id for p in projects.list_projects(conn)]

        project_ids = await asyncio.to_thread(ids)
        for stale in set(self._last) - set(project_ids):
            self._last.pop(stale, None)
            self._locks.pop(stale, None)
        await asyncio.gather(*(self.refresh_project(pid) for pid in project_ids))

    async def run_periodic(self, interval: float) -> None:
        """Refresh every `interval` seconds while some WebSocket is connected."""
        while True:
            await asyncio.sleep(interval)
            if self._hub.connection_count == 0:
                continue
            try:
                await self.refresh_all()
            except Exception:
                logger.exception("Falha ao atualizar o estado do git")
