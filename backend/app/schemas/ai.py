"""AI tutor request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import AIAction, AIContextType
from app.schemas.common import TimestampedModel


class AIChatRequest(BaseModel):
    context_type: AIContextType = AIContextType.GENERAL
    context_id: uuid.UUID | None = Field(
        default=None, description="Problem id (dsa) or topic id (lld/hld)."
    )
    message: str = Field(min_length=1, max_length=8_000)
    action: AIAction = AIAction.GENERAL
    selected_code: str | None = Field(
        default=None,
        max_length=100_000,
        description="Code the user highlighted, when relevant to the action.",
    )
    snippet_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Continue an existing conversation. Omit to start a new one."
    )
    include_history: bool = True


class AIMessageResponse(TimestampedModel):
    role: str
    content: str
    action: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict[str, Any] | None = None
    selected_code: str | None = None
    error: str | None = None


class AIChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: AIMessageResponse
    context_used: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary of the context sent to the model — never the full prompt.",
    )
    is_new_conversation: bool = False


class AIConversationSummary(TimestampedModel):
    title: str | None = None
    context_type: str
    context_id: uuid.UUID | None = None
    context_label: str | None = None
    provider: str | None = None
    model: str | None = None
    message_count: int = 0
    last_message_at: datetime | None = None
    preview: str | None = None


class AIConversationDetail(AIConversationSummary):
    messages: list[AIMessageResponse] = Field(default_factory=list)


class AIActionsResponse(BaseModel):
    """Lets a client render the tutor's action menu without hardcoding it."""

    actions: list[dict[str, str]] = Field(default_factory=list)
    context_types: list[str] = Field(default_factory=list)
    provider: str
    model: str
    enabled: bool = True
