"""Shared response envelopes and cross-cutting Pydantic models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ORMModel(BaseModel):
    """Base for schemas populated from SQLAlchemy objects."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedModel(ORMModel):
    """Standard columns present on every mutable user-owned row."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    version: int = 1


class CatalogModel(ORMModel):
    """Base for catalog rows whose primary key is a slug, not a UUID.

    ``dsa_problems`` is keyed by ``text`` (the slug) so that the pre-existing
    ``problem_id text`` columns in ``user_problem_progress``/``problem_notes``/
    ``code_snippets`` join to it without rewriting any stored user data. Those schemas
    therefore cannot inherit :class:`TimestampedModel`, whose ``id`` is a ``UUID``.
    """

    id: str
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    auth: bool
    detail: str | None = None
    auth_config: dict[str, Any] | None = None


class ErrorDetail(BaseModel):
    code: str = Field(examples=["PROBLEM_NOT_FOUND"])
    message: str = Field(examples=["DSA problem not found"])
    details: Any = None


class ErrorResponse(BaseModel):
    """The single error shape used by every endpoint."""

    error: ErrorDetail = Field(
        examples=[
            {
                "code": "PROBLEM_NOT_FOUND",
                "message": "DSA problem not found",
                "details": None,
            }
        ]
    )


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None


class ProgressSummary(BaseModel):
    """Per-row progress embedded in catalog listings."""

    status: str = "not_started"
    attempts: int = 0
    confidence: int | None = None
    is_favorite: bool = False
    next_revision_at: datetime | None = None
    solved_at: datetime | None = None
    total_time_spent_minutes: int = 0


class DifficultyBreakdown(BaseModel):
    difficulty: str
    total: int
    solved: int
    mastered: int
    attempted: int
    completion_percentage: float


class TopicBreakdown(BaseModel):
    topic: str
    total: int
    solved: int
    mastered: int
    attempted: int
    needs_revision: int
    completion_percentage: float
    average_confidence: float | None = None


class ActivityPoint(BaseModel):
    """One bucket in a time-series response, chart-ready for React/Swift."""

    date: date
    problems_attempted: int = 0
    problems_solved: int = 0
    revisions_completed: int = 0
    study_minutes: int = 0
    activity_count: int = 0


class StreakInfo(BaseModel):
    current: int = 0
    longest: int = 0
    last_active_date: date | None = None
    today_active: bool = False


class DateRange(BaseModel):
    start: date
    end: date


class DecimalSafeModel(BaseModel):
    """Rounds floats in responses to avoid 4.100000000000001 style noise in charts."""

    @field_serializer("*", when_used="json")
    def _round_floats(self, value: Any) -> Any:  # pragma: no cover - formatting only
        if isinstance(value, float):
            return round(value, 4)
        return value
