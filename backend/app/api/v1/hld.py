"""High-level design curriculum, progress, notes and code."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.core.constants import HLDCategory, TopicStatus
from app.schemas.hld import (
    HLDCodeSnippetPayload,
    HLDCodeSnippetResponse,
    HLDCodeSnippetUpdate,
    HLDNotesResponse,
    HLDNotesUpsert,
    HLDProgressResponse,
    HLDProgressUpdateRequest,
    HLDTopicDetail,
    HLDTopicSummary,
)
from app.utils.pagination import DeletedResponse, Page

router = APIRouter(prefix="/hld", tags=["hld"])


@router.get(
    "",
    response_model=Page[HLDTopicSummary],
    summary="Browse the HLD curriculum",
    description=(
        "Topics grouped by category (`fundamentals`, `system_design`) with the caller's "
        "progress merged into each row."
    ),
)
async def list_topics(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    search: str | None = Query(default=None, max_length=200),
    category: HLDCategory | None = Query(default=None),
    status_filter: TopicStatus | None = Query(default=None, alias="status"),
    order_by: str = Query(default="curriculum", pattern="^(curriculum|category|title|recent)$"),
) -> Page[HLDTopicSummary]:
    items, total = await services.hld.list_topics(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        search=search,
        category=category.value if category else None,
        status=status_filter.value if status_filter else None,
        order_by=order_by,
    )
    return Page[HLDTopicSummary](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/{topic_id}",
    response_model=HLDTopicDetail,
    summary="One HLD topic",
    description=(
        "Topic metadata plus the caller's progress, the 13-section design document and any "
        "saved diagrams/code."
    ),
)
async def get_topic(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> HLDTopicDetail:
    return await services.hld.get_detail(user_id=current_user.id, topic_id=topic_id)


@router.put(
    "/{topic_id}/progress",
    response_model=HLDProgressResponse,
    summary="Update HLD progress",
    description="UPSERT semantics; dates are derived server-side from the status transition.",
)
async def update_progress(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: HLDProgressUpdateRequest,
    topic_id: uuid.UUID,
    client_timezone: ClientTimezone = None,
) -> HLDProgressResponse:
    return await services.hld.update_progress(
        user_id=current_user.id,
        topic_id=topic_id,
        payload=payload,
        timezone=client_timezone,
    )


@router.get(
    "/{topic_id}/notes",
    response_model=HLDNotesResponse | None,
    summary="HLD design document",
    description="Returns `null` when the user has not started this design yet.",
)
async def get_notes(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> HLDNotesResponse | None:
    return await services.hld.get_notes(user_id=current_user.id, topic_id=topic_id)


@router.put(
    "/{topic_id}/notes",
    response_model=HLDNotesResponse,
    summary="Write the HLD design document",
    description=(
        "UPSERT semantics covering all 13 sections: functional and non-functional "
        "requirements, capacity estimation, APIs, data model, high-level architecture, "
        "database choice, caching, queues, scaling, failure handling, tradeoffs and final "
        "notes."
    ),
)
async def upsert_notes(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: HLDNotesUpsert,
    topic_id: uuid.UUID,
) -> HLDNotesResponse:
    return await services.hld.upsert_notes(
        user_id=current_user.id, topic_id=topic_id, payload=payload
    )


@router.get(
    "/{topic_id}/code",
    response_model=list[HLDCodeSnippetResponse],
    summary="HLD diagrams and code",
    description="Diagrams saved as text (e.g. Mermaid) or snippets, stored verbatim.",
)
async def list_code(
    current_user: CurrentUser, services: ServicesDep, topic_id: uuid.UUID
) -> list[HLDCodeSnippetResponse]:
    return await services.hld.list_code(user_id=current_user.id, topic_id=topic_id)


@router.post(
    "/{topic_id}/code",
    response_model=HLDCodeSnippetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an HLD diagram or snippet",
)
async def create_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: HLDCodeSnippetPayload,
    topic_id: uuid.UUID,
) -> HLDCodeSnippetResponse:
    return await services.hld.create_code(
        user_id=current_user.id, topic_id=topic_id, payload=payload
    )


@router.put(
    "/{topic_id}/code/{snippet_id}",
    response_model=HLDCodeSnippetResponse,
    summary="Update an HLD diagram or snippet",
)
async def update_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: HLDCodeSnippetUpdate,
    topic_id: uuid.UUID,
    snippet_id: uuid.UUID,
) -> HLDCodeSnippetResponse:
    return await services.hld.update_code(
        user_id=current_user.id,
        topic_id=topic_id,
        snippet_id=snippet_id,
        payload=payload,
    )


@router.delete(
    "/{topic_id}/code/{snippet_id}",
    response_model=DeletedResponse,
    summary="Delete an HLD diagram or snippet",
)
async def delete_code(
    current_user: CurrentUser,
    services: ServicesDep,
    topic_id: uuid.UUID,
    snippet_id: uuid.UUID,
) -> DeletedResponse:
    await services.hld.delete_code(
        user_id=current_user.id, topic_id=topic_id, snippet_id=snippet_id
    )
    return DeletedResponse(id=str(snippet_id), message="Code snippet deleted")


__all__ = ["router"]
