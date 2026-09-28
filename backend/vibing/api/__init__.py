"""REST routes."""

from fastapi import APIRouter

from vibing.api import fs, health, projects

router = APIRouter()
router.include_router(health.router)
router.include_router(projects.router)
router.include_router(fs.router)
