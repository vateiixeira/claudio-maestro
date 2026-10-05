"""REST routes."""

from fastapi import APIRouter

from claudio_maestro.api import (
    activity,
    app_state,
    digest,
    editor,
    fs,
    git,
    groups,
    health,
    plans,
    projects,
    sessions,
    suggestions,
    updates,
    ws,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(projects.router)
router.include_router(fs.router)
router.include_router(sessions.router)
router.include_router(plans.router)
router.include_router(digest.router)
router.include_router(groups.router)
router.include_router(activity.router)
router.include_router(app_state.router)
router.include_router(git.router)
router.include_router(editor.router)
router.include_router(suggestions.router)
router.include_router(updates.router)
router.include_router(ws.router)
