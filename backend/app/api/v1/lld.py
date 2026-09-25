"""Low-level design curriculum, progress, notes and code."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.core.constants import LLDCategory, TopicStatus
from app.schemas.lld import (
    LLDCodeSnippetPayload,
    LLDCodeSnippetResponse,
    LLDCodeSnippetUpdate,
    LLDNotesResponse,
    LLDNotesUpsert,
    LLDProgressResponse,
    LLDProgressUpdateRequest,
    LLDTopicDetail,
    LLDTopicSummary,
)
from app.utils.pagination import DeletedResponse, Page

router = APIRouter(prefix="/lld", tags=["lld"])


@router.get(
    "",
    response_model=Page[LLDTopicSummary],
    summary="Browse the LLD curriculum",
    description=(
        "Topics grouped by category (`fundamentals`, `design_patterns`, `design_exercises`) "
        "with the caller's progress merged into each row."
    ),
)
async def list_topics(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    search: str | None = Query(default=None, max_length=200),
    category: LLDCategory | None = Query(default=None),
    status_filter: TopicStatus | None = Query(default=None, alias="status"),
    order_by: str = Query(default="curriculum", pattern="^(curriculum|category|title|recent)$"),
) -> Page[LLDTopicSummary]:
    items, total = await services.lld.list_topics(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        search=search,
        category=category.value if category else None,
        status=status_filter.value if status_filter else None,
        order_by=order_by,
    )
    return Page[LLDTopicSummary](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/{topic_id}",
    response_model=LLDTopicDetail,
    summary="One LLD topic",
    description="Topic metadata plus the caller's progress, notes and saved diagrams/code.",
)
async def get_topic(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> LLDTopicDetail:
    return await services.lld.get_detail(user_id=current_user.id, topic_id=topic_id)


@router.put(
    "/{topic_id}/progress",
    response_model=LLDProgressResponse,
    summary="Update LLD progress",
    description=(
        "UPSERT semantics. Reaching `completed`/`mastered` stamps `completed_at` and "
        "schedules a revision; `needs_revision` brings the topic back tomorrow."
    ),
)
async def update_progress(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: LLDProgressUpdateRequest,
    topic_id: uuid.UUID,
    client_timezone: ClientTimezone = None,
) -> LLDProgressResponse:
    return await services.lld.update_progress(
        user_id=current_user.id,
        topic_id=topic_id,
        payload=payload,
        timezone=client_timezone,
    )


@router.get(
    "/{topic_id}/notes",
    response_model=LLDNotesResponse | None,
    summary="LLD notes",
    description="Returns `null` when the user has not written notes for this topic yet.",
)
async def get_notes(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> LLDNotesResponse | None:
    return await services.lld.get_notes(user_id=current_user.id, topic_id=topic_id)


@router.put(
    "/{topic_id}/notes",
    response_model=LLDNotesResponse,
    summary="Write LLD notes",
    description=(
        "UPSERT semantics covering the summary, design explanation, class "
        "responsibilities, relationships, patterns used and a structured class diagram."
    ),
)
async def upsert_notes(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: LLDNotesUpsert,
    topic_id: uuid.UUID,
) -> LLDNotesResponse:
    return await services.lld.upsert_notes(
        user_id=current_user.id, topic_id=topic_id, payload=payload
    )


@router.get(
    "/{topic_id}/code",
    response_model=list[LLDCodeSnippetResponse],
    summary="LLD code snippets",
)
async def list_code(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> list[LLDCodeSnippetResponse]:
    return await services.lld.list_code(user_id=current_user.id, topic_id=topic_id)


@router.post(
    "/{topic_id}/code",
    response_model=LLDCodeSnippetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an LLD snippet",
)
async def create_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: LLDCodeSnippetPayload,
    topic_id: uuid.UUID,
) -> LLDCodeSnippetResponse:
    return await services.lld.create_code(
        user_id=current_user.id, topic_id=topic_id, payload=payload
    )


@router.put(
    "/{topic_id}/code/{snippet_id}",
    response_model=LLDCodeSnippetResponse,
    summary="Update an LLD snippet",
)
async def update_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: LLDCodeSnippetUpdate,
    topic_id: uuid.UUID,
    snippet_id: uuid.UUID,
) -> LLDCodeSnippetResponse:
    return await services.lld.update_code(
        user_id=current_user.id,
        topic_id=topic_id,
        snippet_id=snippet_id,
        payload=payload,
    )


@router.delete(
    "/{topic_id}/code/{snippet_id}",
    response_model=DeletedResponse,
    summary="Delete an LLD snippet",
)
async def delete_code(
    current_user: CurrentUser,
    services: ServicesDep,
    topic_id: uuid.UUID,
    snippet_id: uuid.UUID,
) -> DeletedResponse:
    await services.lld.delete_code(
        user_id=current_user.id, topic_id=topic_id, snippet_id=snippet_id
    )
    return DeletedResponse(id=str(snippet_id), message="Code snippet deleted")


__all__ = ["router"]
