"""REST routes."""

from fastapi import APIRouter

from vibing.api import activity, app_state, editor, fs, git, health, projects, sessions, ws

router = APIRouter()
router.include_router(health.router)
router.include_router(projects.router)
router.include_router(fs.router)
router.include_router(sessions.router)
router.include_router(activity.router)
router.include_router(app_state.router)
router.include_router(git.router)
router.include_router(editor.router)
router.include_router(ws.router)
