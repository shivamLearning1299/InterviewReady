"""HLD topic, progress, notes and code schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import HLDCategory, TopicStatus
from app.schemas.common import ORMModel, TimestampedModel


class HLDProgressSummary(BaseModel):
    status: str = "not_started"
    confidence: int | None = None
    completed_at: datetime | None = None
    next_revision_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    total_time_spent_minutes: int = 0


class HLDTopicSummary(TimestampedModel):
    title: str
    slug: str
    category: str
    description: str | None = None
    difficulty: str = "hard"
    estimated_minutes: int = 90
    order_index: int = 0
    is_active: bool = True
    key_concepts: list[str] = Field(default_factory=list)
    progress: HLDProgressSummary = Field(default_factory=HLDProgressSummary)


class HLDNotesResponse(TimestampedModel):
    """All 13 design sections plus the user's supplementary notes."""

    user_id: uuid.UUID
    hld_topic_id: uuid.UUID
    functional_requirements: str | None = None
    non_functional_requirements: str | None = None
    capacity_estimation: str | None = None
    apis: str | None = None
    data_model: str | None = None
    high_level_architecture: str | None = None
    database_choice: str | None = None
    caching: str | None = None
    queues: str | None = None
    scaling: str | None = None
    failure_handling: str | None = None
    tradeoffs: str | None = None
    final_notes: str | None = None
    interview_notes: str | None = None
    mistakes: str | None = None


class HLDTopicDetail(TimestampedModel):
    title: str
    slug: str
    category: str
    description: str | None = None
    learning_objectives: list[str] = Field(default_factory=list)
    key_concepts: list[str] = Field(default_factory=list)
    external_url: str | None = None
    difficulty: str = "hard"
    estimated_minutes: int = 90
    order_index: int = 0
    is_active: bool = True
    progress: HLDProgressSummary | None = None
    notes: HLDNotesResponse | None = None
    code_snippets: list[HLDCodeSnippetResponse] = Field(default_factory=list)


class HLDProgressUpdateRequest(BaseModel):
    status: TopicStatus | None = None
    confidence: int | None = Field(default=None, ge=0, le=5)
    time_spent_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    schedule_revision: bool | None = None


class HLDProgressResponse(TimestampedModel):
    user_id: uuid.UUID
    hld_topic_id: uuid.UUID
    status: str
    confidence: int | None = None
    revision_count: int
    last_reviewed_at: datetime | None = None
    completed_at: datetime | None = None
    next_revision_at: datetime | None = None
    total_time_spent_minutes: int


class HLDNotesUpsert(BaseModel):
    functional_requirements: str | None = Field(default=None, max_length=50_000)
    non_functional_requirements: str | None = Field(default=None, max_length=50_000)
    capacity_estimation: str | None = Field(default=None, max_length=50_000)
    apis: str | None = Field(default=None, max_length=50_000)
    data_model: str | None = Field(default=None, max_length=50_000)
    high_level_architecture: str | None = Field(default=None, max_length=50_000)
    database_choice: str | None = Field(default=None, max_length=50_000)
    caching: str | None = Field(default=None, max_length=50_000)
    queues: str | None = Field(default=None, max_length=50_000)
    scaling: str | None = Field(default=None, max_length=50_000)
    failure_handling: str | None = Field(default=None, max_length=50_000)
    tradeoffs: str | None = Field(default=None, max_length=50_000)
    final_notes: str | None = Field(default=None, max_length=50_000)
    interview_notes: str | None = Field(default=None, max_length=50_000)
    mistakes: str | None = Field(default=None, max_length=50_000)


class HLDCodeSnippetPayload(BaseModel):
    code: str = Field(max_length=200_000)
    language: str = Field(default="python", max_length=30)
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool = False


class HLDCodeSnippetUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=200_000)
    language: str | None = Field(default=None, max_length=30)
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool | None = None


class HLDCodeSnippetResponse(TimestampedModel):
    user_id: uuid.UUID
    context_type: str
    context_id: uuid.UUID
    title: str | None = None
    language: str
    code: str
    is_primary: bool


class HLDFilters(ORMModel):
    search: str | None = None
    category: HLDCategory | None = None
    status: TopicStatus | None = None
    is_active: bool | None = True


HLDTopicDetail.model_rebuild()
