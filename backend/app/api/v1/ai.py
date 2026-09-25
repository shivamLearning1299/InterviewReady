"""AI tutor chat and conversation history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.v1.dependencies import CurrentUser, Paginated, ServicesDep
from app.core.constants import AIContextType
from app.schemas.ai import (
    AIActionsResponse,
    AIChatRequest,
    AIChatResponse,
    AIConversationDetail,
    AIConversationSummary,
)
from app.utils.pagination import DeletedResponse, Page

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post(
    "/chat",
    response_model=AIChatResponse,
    summary="Ask the AI tutor",
    description=(
        "Sends a message to the tutor and returns its reply.\n\n"
        "**Context is minimal by design.** Only the relevant entity is loaded for the given "
        "`context_type`: the problem's metadata, the user's own notes and progress for "
        "`dsa`; the topic and notes for `lld`/`hld`; nothing but the conversation for "
        "`general`. The user's entire database is never sent to the model.\n\n"
        "**Pedagogy.** The default behaviour is to give progressively stronger hints and "
        "explain the underlying pattern rather than reveal the solution. Full code is "
        "provided only when explicitly requested (or when `ai_auto_reveal_solution` is on "
        "in the user's settings).\n\n"
        "Omitting `conversation_id` starts a new thread. The request is rate limited per "
        "user; exceeding the limit returns 429."
    ),
    responses={
        429: {"description": "Per-user AI rate limit exceeded"},
        503: {"description": "The AI provider is not configured on this server"},
    },
)
async def chat(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: AIChatRequest,
) -> AIChatResponse:
    return await services.ai.chat(user_id=current_user.id, payload=payload)


@router.get(
    "/actions",
    response_model=AIActionsResponse,
    summary="Available tutor actions",
    description="Lets a client render the tutor menu without hardcoding it.",
)
async def list_actions(current_user: CurrentUser, services: ServicesDep) -> AIActionsResponse:
    data = await services.ai.available_actions()
    return AIActionsResponse(**data)


@router.get(
    "/conversations",
    response_model=Page[AIConversationSummary],
    summary="Conversation history",
    description="Newest first, each with a short preview of the latest assistant reply.",
)
async def list_conversations(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    context_type: AIContextType | None = Query(default=None),
) -> Page[AIConversationSummary]:
    items, total = await services.ai.list_conversations(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        context_type=context_type.value if context_type else None,
    )
    return Page[AIConversationSummary](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AIConversationDetail,
    summary="One conversation with its messages",
)
async def get_conversation(
    current_user: CurrentUser, services: ServicesDep, conversation_id: uuid.UUID
) -> AIConversationDetail:
    return await services.ai.get_conversation(
        user_id=current_user.id, conversation_id=conversation_id
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=DeletedResponse,
    summary="Delete a conversation",
    description=(
        "Soft delete: the thread and its messages are tombstoned so an offline device "
        "learns about the removal on its next sync pull."
    ),
)
async def delete_conversation(
    current_user: CurrentUser, services: ServicesDep, conversation_id: uuid.UUID
) -> DeletedResponse:
    await services.ai.delete_conversation(
        user_id=current_user.id, conversation_id=conversation_id
    )
    return DeletedResponse(id=str(conversation_id), message="Conversation deleted")


__all__ = ["router"]
