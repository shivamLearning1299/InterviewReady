"""LLD topic, progress, notes and code schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.constants import LLDCategory, TopicStatus
from app.schemas.common import ORMModel, TimestampedModel


class LLDProgressSummary(BaseModel):
    status: str = "not_started"
    confidence: int | None = None
    completed_at: datetime | None = None
    next_revision_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    total_time_spent_minutes: int = 0


class LLDTopicSummary(TimestampedModel):
    title: str
    slug: str
    category: str
    description: str | None = None
    difficulty: str = "medium"
    estimated_minutes: int = 60
    order_index: int = 0
    is_active: bool = True
    key_concepts: list[str] = Field(default_factory=list)
    progress: LLDProgressSummary = Field(default_factory=LLDProgressSummary)


class LLDNotesResponse(TimestampedModel):
    user_id: uuid.UUID
    lld_topic_id: uuid.UUID
    summary: str | None = None
    design_explanation: str | None = None
    class_responsibilities: str | None = None
    relationships: str | None = None
    design_notes: str | None = None
    mistakes: str | None = None
    revision_notes: str | None = None
    patterns_used: list[str] = Field(default_factory=list)
    class_diagram: list[Any] | None = None


class LLDTopicDetail(TimestampedModel):
    title: str
    slug: str
    category: str
    description: str | None = None
    learning_objectives: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    external_url: str | None = None
    difficulty: str = "medium"
    estimated_minutes: int = 60
    order_index: int = 0
    is_active: bool = True
    progress: LLDProgressSummary | None = None
    notes: LLDNotesResponse | None = None
    code_snippets: list[LLDCodeSnippetResponse] = Field(default_factory=list)


class LLDProgressUpdateRequest(BaseModel):
    status: TopicStatus | None = None
    confidence: int | None = Field(default=None, ge=0, le=5)
    time_spent_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    schedule_revision: bool | None = None


class LLDProgressResponse(TimestampedModel):
    user_id: uuid.UUID
    lld_topic_id: uuid.UUID
    status: str
    confidence: int | None = None
    revision_count: int
    last_reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    next_revision_at: datetime | None = None
    total_time_spent_minutes: int


class LLDNotesUpsert(BaseModel):
    summary: str | None = Field(default=None, max_length=50_000)
    design_explanation: str | None = Field(default=None, max_length=50_000)
    class_responsibilities: str | None = Field(default=None, max_length=50_000)
    relationships: str | None = Field(default=None, max_length=50_000)
    design_notes: str | None = Field(default=None, max_length=50_000)
    mistakes: str | None = Field(default=None, max_length=50_000)
    revision_notes: str | None = Field(default=None, max_length=50_000)
    patterns_used: list[str] | None = None
    class_diagram: list[Any] | None = None


class LLDCodeSnippetPayload(BaseModel):
    code: str = Field(max_length=200_000)
    language: str = Field(default="python", max_length=30)
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool = False


class LLDCodeSnippetUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=200_000)
    language: str | None = Field(default=None, max_length=30)
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool | None = None


class LLDCodeSnippetResponse(TimestampedModel):
    user_id: uuid.UUID
    context_type: str
    context_id: uuid.UUID
    title: str | None = None
    language: str
    code: str
    is_primary: bool


class LLDFilters(ORMModel):
    search: str | None = None
    category: LLDCategory | None = None
    status: TopicStatus | None = None
    is_active: bool | None = True


LLDTopicDetail.model_rebuild()
