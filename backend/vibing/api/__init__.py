"""REST routes."""

from fastapi import APIRouter

from vibing.api import app_state, fs, health, projects, sessions, ws

router = APIRouter()
router.include_router(health.router)
router.include_router(projects.router)
router.include_router(fs.router)
router.include_router(sessions.router)
router.include_router(app_state.router)
router.include_router(ws.router)
