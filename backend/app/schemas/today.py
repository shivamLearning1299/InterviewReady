"""Daily plan and ``/today`` schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, ProgressSummary, StreakInfo, TimestampedModel


class TodayItem(BaseModel):
    """A single row in today's plan, flattened for easy rendering."""

    id: uuid.UUID
    item_type: str
    position: int
    problem_id: str | None = None
    topic_id: uuid.UUID | None = None
    title: str | None = None
    slug: str | None = None
    difficulty: str | None = None
    primary_topic: str | None = None
    patterns: list[str] = Field(default_factory=list)
    external_url: str | None = None
    estimated_minutes: int | None = None
    reason: str | None = None
    is_completed: bool = False
    completed_at: datetime | None = None
    progress: ProgressSummary | None = None


class TodaySection(BaseModel):
    """Completion counter plus the items for one plan section."""

    completed: int = 0
    total: int = 0
    items: list[TodayItem] = Field(default_factory=list)


class RevisionDueSummary(BaseModel):
    total: int = 0
    overdue: int = 0
    due_today: int = 0
    upcoming: int = 0


class TodayResponse(BaseModel):
    """The most important response in the API: everything the home screen needs.

    Built from a persisted plan, so calling this endpoint repeatedly returns identical
    data for the same user on the same day.
    """

    date: date
    timezone: str
    plan_id: uuid.UUID | None = None
    status: str = "active"
    generated_at: datetime | None = None
    is_completed: bool = False

    streak: StreakInfo = Field(default_factory=StreakInfo)

    dsa: TodaySection = Field(default_factory=TodaySection)
    lld: TodaySection = Field(default_factory=TodaySection)
    hld: TodaySection = Field(default_factory=TodaySection)
    revisions: TodaySection = Field(default_factory=TodaySection)
    revisions_due: int = 0
    revision_summary: RevisionDueSummary = Field(default_factory=RevisionDueSummary)

    study_minutes_today: int = 0
    active_session_id: uuid.UUID | None = None
    total_estimated_minutes: int = 0


class DailyPlanSummary(TimestampedModel):
    user_id: uuid.UUID
    plan_date: date
    timezone: str
    status: str
    generated_by: str
    total_items: int = 0
    completed_items: int = 0


class DailyPlanDetail(DailyPlanSummary):
    dsa: TodaySection = Field(default_factory=TodaySection)
    lld: TodaySection = Field(default_factory=TodaySection)
    hld: TodaySection = Field(default_factory=TodaySection)
    revisions: TodaySection = Field(default_factory=TodaySection)


class DailyPlanItemUpdateRequest(BaseModel):
    """Mark a plan item done/undone from either client."""

    is_completed: bool


class PlanGenerationDebug(ORMModel):
    """Non-sensitive diagnostics explaining how today's plan was produced."""

    candidate_count: int = 0
    new_problem_count: int = 0
    revision_count: int = 0
    weak_topics: list[str] = Field(default_factory=list)
    covered_topics: list[str] = Field(default_factory=list)
    scoring_version: str = "scheduler_v1"
    explanation: dict[str, Any] = Field(default_factory=dict)
