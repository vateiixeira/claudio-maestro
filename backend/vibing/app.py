"""Application assembly: settings, database, middleware and routes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI

from vibing import db
from vibing.agent.base import AgentFactory
from vibing.agent.sdk_client import clean_inherited_env
from vibing.api import router
from vibing.config import Settings, load_settings
from vibing.events import EventHub
from vibing.security import HostOriginMiddleware
from vibing.sessions import HistoryExists, RenameSession, SessionManager


def create_app(
    settings: Settings | None = None,
    agent_factory: AgentFactory | None = None,
    history_exists: HistoryExists | None = None,
    rename_session: RenameSession | None = None,
) -> FastAPI:
    """Build the app. Without `settings`, they are read from the environment at startup.

    `agent_factory`, `history_exists` and `rename_session` default to the real SDK; tests pass fakes.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clean_inherited_env()
        app.state.settings = settings or load_settings()
        db.init_db(app.state.settings.db_path)
        app.state.hub = EventHub()
        app.state.sessions = SessionManager(
            app.state.settings.db_path,
            app.state.hub.publish,
            agent_factory=agent_factory,
            history_exists=history_exists,
            rename_session=rename_session,
            idle_timeout=app.state.settings.idle_timeout_seconds,
            finished_after_days=app.state.settings.finished_after_days,
        )
        sweep = asyncio.create_task(
            app.state.sessions.run_idle_sweep(app.state.settings.idle_sweep_interval_seconds)
        )
        try:
            yield
        finally:
            sweep.cancel()
            with suppress(asyncio.CancelledError):
                await sweep
            await app.state.sessions.shutdown()

    app = FastAPI(title="Vini7 Vibing", lifespan=lifespan)
    app.add_middleware(HostOriginMiddleware)
    app.include_router(router)
    return app


app = create_app()
