"""Application assembly: settings, database, middleware and routes."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from claudio_maestro import db, gitinfo, history
from claudio_maestro.activity import ActivityReader, SessionFile
from claudio_maestro.agent.agentd_client import AgentdClient
from claudio_maestro.agent.base import AgentFactory
from claudio_maestro.agent.sdk_client import clean_inherited_env
from claudio_maestro.api import router
from claudio_maestro.api.editor import SpawnEditor, spawn_detached
from claudio_maestro.cliwatch import CliWatcher
from claudio_maestro.commands import CommandCatalog
from claudio_maestro.config import (
    Settings,
    app_ports,
    backend_port,
    claude_projects_dir,
    legacy_data_dir,
    load_settings,
)
from claudio_maestro.digest.model import DigestModel, SdkDigestModel
from claudio_maestro.digest.service import AGENT_DIR_NAME, DigestService
from claudio_maestro.events import EventHub
from claudio_maestro.filesearch import FileIndex
from claudio_maestro.frontend_static import mount_frontend
from claudio_maestro.gitmonitor import GitMonitor
from claudio_maestro.picker import PickFolder
from claudio_maestro.picker import pick_folder as system_pick_folder
from claudio_maestro.security import (
    BodySizeLimitMiddleware,
    HostOriginMiddleware,
    allowed_hosts,
    allowed_origins,
)
from claudio_maestro.sessions import HistoryExists, RenameSession, SessionManager
from claudio_maestro.updates import FetchRelease, UpdateChecker, fetch_latest_release
from claudio_maestro.usage import FetchUsage, UsageChecker
from claudio_maestro.usage import fetch_usage as default_fetch_usage

logger = logging.getLogger(__name__)


def publish_synced(publish: Callable[[dict[str, Any]], None], project_ids: set[int]) -> None:
    """Tell the frontend to reload these projects' sessions."""
    for project_id in sorted(project_ids):
        publish(
            {"session_id": None, "seq": 0, "type": "project.synced",
             "data": {"project_id": project_id}}
        )


def create_app(
    settings: Settings | None = None,
    agent_factory: AgentFactory | None = None,
    history_exists: HistoryExists | None = None,
    rename_session: RenameSession | None = None,
    list_sessions: history.ListSessions | None = None,
    get_session_messages: history.GetSessionMessages | None = None,
    read_tool_results: history.ReadToolResults | None = None,
    spawn_editor: SpawnEditor | None = None,
    pick_folder: PickFolder | None = None,
    refresh_models: bool | None = None,
    session_file: SessionFile | None = None,
    plan_sweep: bool | None = None,
    digest_model: DigestModel | None = None,
    ports: tuple[int, ...] | None = None,
    frontend_dir: Path | None = None,
    agentd: bool | None = None,
    fetch_release: FetchRelease | None = None,
    git_fetch: gitinfo.FetchUpstream | None = None,
    fetch_usage: FetchUsage | None = None,
) -> FastAPI:
    """Build the app. Without `settings`, they are read from the environment at startup.

    `agent_factory`, `history_exists`, `rename_session`, `list_sessions` and
    `get_session_messages` default to the real SDK; tests pass fakes.
    `refresh_models` turns on the periodic refresh of the models list, which starts
    a throwaway agent client: by default it runs only with the real agent, so
    tests with a fake factory keep seeing only the clients of their sessions.
    `plan_sweep` turns on the periodic reread of plan progress (same default).
    `digest_model` defaults to the real SDK; the agent only calls it when enabled or asked.
    `ports`: (Vite, backend[, preview]); None reads `MAESTRO_DEV_PORT`, `MAESTRO_PORT` and `MAESTRO_PREVIEW_PORT`.
    `frontend_dir`: the built frontend to serve at the root; None (development) serves only the API.
    `agentd`: keep sessions across restarts. None turns it on only with the real agent and
    when `MAESTRO_AGENTD` is not `0`.
    `fetch_release` replaces the GitHub read of the latest release (tests pass fakes).
    `git_fetch` replaces `gitinfo.fetch_upstream`, the one thing that reaches a git remote.
    `fetch_usage` replaces the read of the subscription usage (tests pass fakes).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clean_inherited_env()
        app.state.settings = settings or load_settings()
        db.init_db(app.state.settings.db_path)
        app.state.hub = EventHub()
        app.state.spawn_editor = spawn_editor or spawn_detached
        app.state.pick_folder = pick_folder or system_pick_folder
        # Only one system folder picker open at a time.
        app.state.pick_lock = asyncio.Lock()
        app.state.git_monitor = GitMonitor(
            app.state.settings.db_path, app.state.hub, fetch=git_fetch
        )
        app.state.updates = UpdateChecker(
            app.state.hub.publish,
            enabled=app.state.settings.update_check,
            fetch=fetch_release or fetch_latest_release,
        )
        app.state.usage = UsageChecker(
            app.state.hub.publish,
            enabled=app.state.settings.usage_check,
            fetch=fetch_usage or default_fetch_usage,
        )
        # One-off tasks (e.g. syncing a new project), cancelled on shutdown.
        app.state.background = set()

        def refresh_git(project_id: int) -> None:
            task = asyncio.create_task(
                app.state.git_monitor.refresh_project(project_id, force=True)
            )
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)

        def on_turn_end(project_id: int) -> None:
            refresh_git(project_id)
            if app.state.usage.wants_refresh():
                task = asyncio.create_task(app.state.usage.refresh())
                app.state.background.add(task)
                task.add_done_callback(app.state.background.discard)

        use_agentd = agentd if agentd is not None else agent_factory is None
        new_through_agentd = os.environ.get("MAESTRO_AGENTD", "1") != "0"
        app.state.agentd = (
            AgentdClient(app.state.settings.data_dir, spawn_allowed=new_through_agentd)
            if use_agentd else None
        )
        app.state.sessions = SessionManager(
            app.state.settings.db_path,
            app.state.hub.publish,
            agent_factory=agent_factory,
            history_exists=history_exists,
            rename_session=rename_session,
            idle_timeout=app.state.settings.idle_timeout_seconds,
            finished_after_days=app.state.settings.finished_after_days,
            list_sessions=list_sessions,
            get_session_messages=get_session_messages,
            read_tool_results=read_tool_results,
            on_turn_end=on_turn_end,
            agentd=app.state.agentd,
            agentd_new_sessions=new_through_agentd,
        )
        try:
            await app.state.sessions.reattach_all()
        except Exception:
            # Sessions that could not be reattached show as interrupted; the app must start.
            logger.exception("Falha ao religar as sessões do agentd")
        app.state.commands = CommandCatalog(app.state.sessions.agent_factory)
        app.state.files = FileIndex()
        app.state.activity = ActivityReader(app.state.settings.db_path, session_file)
        agent_dir = (app.state.settings.data_dir / AGENT_DIR_NAME).resolve()
        # Sessions of the digest agent made before the rename live under the old folder.
        legacy_agent_dir = (
            legacy_data_dir(app.state.settings.home_dir) / AGENT_DIR_NAME
        ).resolve()
        app.state.digest = DigestService(
            app.state.settings.db_path,
            app.state.sessions,
            app.state.hub.publish,
            digest_model or SdkDigestModel(agent_dir),
        )
        app.state.history = history.HistoryIndex(
            app.state.settings.db_path,
            list_sessions or history.sdk_list_sessions,
            on_change=app.state.sessions.refresh_records,
            on_projects_changed=lambda ids: publish_synced(app.state.hub.publish, ids),
            is_in_use=app.state.sessions.in_use,
            ignored_dirs=[agent_dir, legacy_agent_dir],
        )
        tasks = [
            asyncio.create_task(
                app.state.sessions.run_idle_sweep(app.state.settings.idle_sweep_interval_seconds)
            ),
            asyncio.create_task(
                app.state.history.run_periodic(app.state.settings.history_sync_interval_seconds)
            ),
            asyncio.create_task(
                app.state.git_monitor.run_periodic(
                    app.state.settings.git_refresh_interval_seconds
                )
            ),
            asyncio.create_task(
                app.state.updates.run_periodic(
                    app.state.settings.update_check_delay_seconds,
                    app.state.settings.update_check_interval_seconds,
                )
            ),
            asyncio.create_task(
                app.state.usage.run_periodic(
                    app.state.settings.usage_check_delay_seconds,
                    app.state.settings.usage_check_interval_seconds,
                )
            ),
            asyncio.create_task(
                app.state.git_monitor.run_fetch_periodic(
                    app.state.settings.git_fetch_interval_seconds
                )
            ),
            asyncio.create_task(app.state.digest.run()),
        ]
        if refresh_models if refresh_models is not None else agent_factory is None:
            tasks.append(
                asyncio.create_task(
                    app.state.sessions.run_models_refresh(
                        app.state.settings.models_refresh_interval_seconds
                    )
                )
            )
        if plan_sweep if plan_sweep is not None else agent_factory is None:
            tasks.append(
                asyncio.create_task(
                    app.state.sessions.run_plan_sweep(
                        app.state.settings.plan_sweep_interval_seconds
                    )
                )
            )
        claude_projects = (
            app.state.settings.claude_projects_dir or claude_projects_dir()
        )
        app.state.cli_watch_task = asyncio.create_task(
            CliWatcher(
                claude_projects, app.state.history, app.state.sessions,
                # Tests that inject a fake listing keep using it.
                session_info=(
                    None if list_sessions is not None
                    else lambda sid, cwd: history.sdk_get_session_info(sid, cwd)
                ),
            ).run()
        )
        tasks.append(app.state.cli_watch_task)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            for task in list(app.state.background):
                task.cancel()
            for task in list(app.state.background):
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.sessions.shutdown()
            if app.state.agentd is not None:
                await app.state.agentd.aclose()

    app = FastAPI(title="Cláudio Maestro", lifespan=lifespan)
    ports = ports or app_ports(backend_port())
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        HostOriginMiddleware,
        allowed_hosts=allowed_hosts(ports),
        allowed_origins=allowed_origins(ports),
    )
    app.include_router(router)
    if frontend_dir is not None:
        # Registered after the API so its routes win.
        mount_frontend(app, frontend_dir)
    return app


app = create_app()
