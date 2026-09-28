"""Application assembly: settings, database, middleware and routes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from vibing import db
from vibing.agent.sdk_client import clean_inherited_env
from vibing.api import router
from vibing.config import Settings, load_settings
from vibing.security import HostOriginMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Without `settings`, they are read from the environment at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clean_inherited_env()
        app.state.settings = settings or load_settings()
        db.init_db(app.state.settings.db_path)
        yield

    app = FastAPI(title="Vini7 Vibing", lifespan=lifespan)
    app.add_middleware(HostOriginMiddleware)
    app.include_router(router)
    return app


app = create_app()
