"""Publishes `project.git` when a project's repositories change."""

import asyncio
import logging
from contextlib import closing
from pathlib import Path
from typing import Any

from claudio_maestro import db, gitinfo, projects
from claudio_maestro.events import EventHub
from claudio_maestro.gitfetch import registry as fetch_registry

logger = logging.getLogger(__name__)

# The periodic fetch looks for repositories that are due this often (or every interval,
# when that is shorter), so the first pass comes soon after someone connects.
FETCH_TICK_SECONDS = 15.0
# "Verificar agora" gives up on slow remotes after this long.
MANUAL_FETCH_LIMIT_SECONDS = 45.0


class GitMonitor:
    def __init__(
        self, db_path: Path, hub: EventHub, fetch: gitinfo.FetchUpstream | None = None
    ) -> None:
        self._db_path = db_path
        self._hub = hub
        # Looked up when used, so tests can replace `gitinfo.fetch_upstream`.
        self._fetch = fetch
        self._last: dict[int, tuple[list[dict[str, Any]], bool]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _project_path(self, project_id: int) -> Path | None:
        with closing(db.connect(self._db_path)) as conn:
            try:
                project = projects.get_project(conn, project_id)
            except projects.ProjectNotFoundError:
                return None
        return Path(project.path) if project.available else None

    async def refresh_project(self, project_id: int, force: bool = False) -> None:
        """Read the project's repositories and publish them if anything changed.

        With `force` it publishes even when the summary is the same: the end of a
        turn may have edited a file that was already modified, which changes its
        diff and line counts but nothing in the summary.
        """
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            path = await asyncio.to_thread(self._project_path, project_id)
            if path is None:
                self._last.pop(project_id, None)
                return
            found, limit_reached = await gitinfo.project_repos_scan(path)
            repos = [repo.to_dict() for repo in found]
            if not force and self._last.get(project_id) == (repos, limit_reached):
                return
            self._last[project_id] = (repos, limit_reached)
            self._hub.publish(
                {"session_id": None, "seq": 0, "type": "project.git",
                 "data": {"project_id": project_id, "repos": repos, "limit_reached": limit_reached}}
            )

    async def fetch_project(
        self,
        project_id: int,
        *,
        interval: float | None = None,
        limit: float | None = None,
    ) -> bool:
        """Fetch the upstream of the project's repositories, then publish the result.

        Without `interval` every repository is fetched at once; with it, only those whose
        wait is over (see `FetchRegistry.due`). A repository without upstream is skipped
        by the fetch itself. `limit` bounds the whole operation (the fetches that did not
        finish are stopped; None: no limit). Returns whether anything was fetched or failed.
        """
        path = await asyncio.to_thread(self._project_path, project_id)
        if path is None:
            return False
        last = self._last.get(project_id)
        if interval is not None and last is not None:
            # The periodic pass reuses the repositories of the last refresh (at most
            # `git_refresh_interval_seconds` old) instead of walking the folders every tick.
            repos = [Path(repo["path"]) for repo in last[0]]
        else:
            repos, _ = await asyncio.to_thread(gitinfo.discover_scan, path)
        if interval is not None:
            repos = [repo for repo in repos if fetch_registry.due(repo, interval)]
        if not repos:
            return False
        fetch = self._fetch or gitinfo.fetch_upstream

        async def one(repo: Path) -> str:
            return await fetch_registry.fetch(repo, lambda: fetch(repo))

        try:
            async with asyncio.timeout(limit):
                results = await asyncio.gather(*(one(repo) for repo in repos))
        except TimeoutError:
            logger.warning("A busca no remoto do projeto %s passou de %s s.", project_id, limit)
            results = ["failed"]
        changed = any(result != "skipped" for result in results)
        if changed:
            await self.refresh_project(project_id)
        return changed

    async def fetch_due(self, interval: float) -> None:
        """One pass of the periodic fetch over every available project."""

        def available() -> list[int]:
            with closing(db.connect(self._db_path)) as conn:
                return [p.id for p in projects.list_projects(conn) if p.available]

        project_ids = await asyncio.to_thread(available)
        results = await asyncio.gather(
            *(self.fetch_project(pid, interval=interval) for pid in project_ids),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error("Falha ao buscar do remoto", exc_info=result)

    async def run_fetch_periodic(self, interval: float) -> None:
        """Fetch upstreams every `interval` seconds while some WebSocket is connected.

        The first pass comes as soon as someone connects. 0 turns it off. A repository
        whose last try failed waits longer (see `FetchRegistry.due`).
        """
        if interval <= 0:
            return
        tick = min(interval, FETCH_TICK_SECONDS)
        while True:
            if self._hub.connection_count > 0:
                try:
                    await self.fetch_due(interval)
                except Exception:
                    logger.exception("Falha ao buscar do remoto")
            await asyncio.sleep(tick)

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
