"""The ``/api/v1`` router.

Every feature router is mounted here with a shared tag list so the generated OpenAPI
document is grouped and navigable.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    dsa,
    hld,
    lld,
    revisions,
    settings,
    stats,
    study_sessions,
    sync,
    today,
    users,
)

api_router = APIRouter()

# Ordering here is the order sections appear in /docs.
api_router.include_router(users.router, tags=["user"])
api_router.include_router(today.router, tags=["today"])
api_router.include_router(dsa.router)
api_router.include_router(revisions.router)
api_router.include_router(lld.router)
api_router.include_router(hld.router)
api_router.include_router(study_sessions.router)
api_router.include_router(stats.router)
api_router.include_router(sync.router)
api_router.include_router(ai.router)
api_router.include_router(settings.router)

__all__ = ["api_router"]
