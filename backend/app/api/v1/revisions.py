"""Spaced-repetition revision queue."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.schemas.dsa import RevisionCompleteRequest, RevisionCompleteResponse, RevisionResponse
from app.utils.pagination import Page

router = APIRouter(prefix="/revisions", tags=["revisions"])


@router.get(
    "",
    response_model=Page[RevisionResponse],
    summary="List revisions",
    description=(
        "The caller's revision queue.\n\n"
        "`bucket` narrows the view: `due` (due now or earlier), `overdue` (more than a day "
        "past due) or `upcoming` (not yet due). Omit it and set `completed=false` for the "
        "whole outstanding queue in priority order."
    ),
)
async def list_revisions(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    bucket: str | None = Query(
        default=None,
        pattern="^(due|overdue|upcoming)$",
        description="Due / overdue / upcoming view",
    ),
    completed: bool | None = Query(
        default=False, description="Filter by completion. Pass null/omit `bucket` for all."
    ),
) -> Page[RevisionResponse]:
    items, total = await services.revisions.list_revisions(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        bucket=bucket,
        completed=completed,
    )
    return Page[RevisionResponse](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/summary",
    summary="Revision counts",
    description="Due / overdue / due-today / upcoming counts for badges and the Today screen.",
)
async def revision_summary(current_user: CurrentUser, services: ServicesDep) -> dict:
    counts = await services.revisions.due_summary(user_id=current_user.id)
    return {
        "due": counts.get("due", 0),
        "overdue": counts.get("overdue", 0),
        "due_today": counts.get("due_today", 0),
        "upcoming": counts.get("upcoming", 0),
    }


@router.post(
    "/{revision_id}/complete",
    response_model=RevisionCompleteResponse,
    summary="Complete a revision",
    description=(
        "Records the outcome of a review and queues the next one on the spaced-repetition "
        "ladder.\n\n"
        "**Idempotent.** Completing an already-completed revision returns the stored result "
        "without advancing the ladder, so an offline client can safely replay the request.\n\n"
        "A `failed` result brings the item back tomorrow at maximum priority, regardless of "
        "how the interval ladder is configured."
    ),
)
async def complete_revision(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: RevisionCompleteRequest,
    revision_id: uuid.UUID,
    client_timezone: ClientTimezone = None,
) -> RevisionCompleteResponse:
    return await services.revisions.complete(
        user_id=current_user.id,
        revision_id=revision_id,
        payload=payload,
        timezone=client_timezone,
    )


@router.post(
    "/promote-stale",
    summary="Queue reviews for stale problems",
    description=(
        "Finds solved problems that have not been reviewed for longer than the ladder's "
        "maximum interval and queues them. Keeps revision useful for a user who has cleared "
        "their queue."
    ),
)
async def promote_stale(
    current_user: CurrentUser,
    services: ServicesDep,
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    queued = await services.revisions.promote_stale_problems(
        user_id=current_user.id, limit=limit
    )
    return {"queued": queued, "message": f"Queued {queued} stale problem(s) for revision"}


__all__ = ["router"]
