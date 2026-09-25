"""DSA catalog, progress, attempt, notes and code schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from app.core.constants import (
    AttemptOutcome,
    Difficulty,
    Language,
    ProblemStatus,
)
from app.schemas.common import CatalogModel, ORMModel, ProgressSummary, TimestampedModel

# --------------------------------------------------------------------------- catalog


class DSAProblemSummary(CatalogModel):
    """Catalog row as returned by the list endpoint, with the caller's progress merged in.

    ``progress`` is always populated — it is aggregated in the same query as the catalog
    page, so listing 50 problems does not trigger 50 extra round trips.
    """

    title: str
    slug: str
    external_url: str | None = None
    source: str
    difficulty: str
    primary_topic: str
    secondary_topics: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    problem_type: str = "algorithmic"
    order_index: int = 0
    importance: int = 3
    estimated_minutes: int = 30
    is_active: bool = True
    progress: ProgressSummary = Field(default_factory=ProgressSummary)


class DSAProblemDetail(CatalogModel):
    """Everything the detail screen needs, in one response."""

    title: str
    slug: str
    external_url: str | None = None
    source: str
    difficulty: str
    primary_topic: str
    secondary_topics: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    problem_type: str = "algorithmic"
    order_index: int = 0
    importance: int = 3
    estimated_minutes: int = 30
    is_active: bool = True
    hints: list[Any] | None = None

    progress: ProgressSummary | None = None
    notes: ProblemNotesResponse | None = None
    code_snippets: list[CodeSnippetResponse] = Field(default_factory=list)
    attempts: list[AttemptResponse] = Field(default_factory=list)
    revisions: list[RevisionResponse] = Field(default_factory=list)


# -------------------------------------------------------------------------- progress


class ProgressUpdateRequest(BaseModel):
    """Payload for ``PUT /dsa/problems/{id}/progress``.

    Every field is optional except that at least one must be present; the endpoint behaves
    as an UPSERT and derives the relevant dates from the values supplied.
    """

    status: ProblemStatus | None = None
    confidence: int | None = Field(default=None, ge=0, le=5)
    time_spent_minutes: int | None = Field(
        default=None,
        ge=0,
        le=24 * 60,
        description="Minutes to add to the accumulated total for this problem.",
    )
    attempts: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None
    notes: str | None = Field(default=None, description="Short inline note, not the notes document.")
    schedule_revision: bool | None = Field(
        default=None,
        description="Force a revision to be scheduled even for a solved problem.",
    )

    @field_validator("status")
    @classmethod
    def _normalise_status(cls, value: ProblemStatus | None) -> ProblemStatus | None:
        return value


class ProgressResponse(TimestampedModel):
    user_id: uuid.UUID
    problem_id: str
    status: str
    attempts: int
    confidence: int | None = None
    revision_count: int
    first_attempt_at: datetime | None = None
    solved_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    next_revision_at: datetime | None = None
    total_time_spent_minutes: int
    is_favorite: bool


# -------------------------------------------------------------------------- attempts


class AttemptCreateRequest(BaseModel):
    """``started_at``/``completed_at`` default to server time when omitted.

    Clients should send them only when recording a session that already happened offline.
    """

    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    outcome: AttemptOutcome | None = None
    notes: str | None = Field(default=None, max_length=20_000)
    update_progress: bool = Field(
        default=True,
        description="Also update the parent progress row (attempt count, status, dates).",
    )
    confidence: int | None = Field(
        default=None,
        ge=0,
        le=5,
        description="Optional confidence to record on the parent progress row.",
    )


class AttemptUpdateRequest(BaseModel):
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    outcome: AttemptOutcome | None = None
    notes: str | None = Field(default=None, max_length=20_000)


class AttemptResponse(TimestampedModel):
    user_id: uuid.UUID
    problem_id: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_minutes: int | None = None
    outcome: str | None = None
    notes: str | None = None


# ----------------------------------------------------------------------------- notes


class ProblemNotesUpsert(BaseModel):
    approach: str | None = Field(default=None, max_length=50_000)
    notes: str | None = Field(default=None, max_length=50_000)
    mistakes: str | None = Field(default=None, max_length=50_000)
    revision_notes: str | None = Field(default=None, max_length=50_000)
    time_complexity: str | None = Field(default=None, max_length=120)
    space_complexity: str | None = Field(default=None, max_length=120)


class ProblemNotesResponse(TimestampedModel):
    user_id: uuid.UUID
    problem_id: str
    approach: str | None = None
    notes: str | None = None
    mistakes: str | None = None
    revision_notes: str | None = None
    time_complexity: str | None = None
    space_complexity: str | None = None


# ------------------------------------------------------------------------------ code


LanguageValue = Annotated[str, Field(description="One of: " + ", ".join(item.value for item in Language))]


class CodeSnippetCreate(BaseModel):
    code: str = Field(max_length=200_000)
    language: Language = Language.PYTHON
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool = False


class CodeSnippetUpdate(BaseModel):
    code: str | None = Field(default=None, max_length=200_000)
    language: Language | None = None
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool | None = None


class CodeSnippetResponse(TimestampedModel):
    user_id: uuid.UUID
    context_type: str
    # A string, not a UUID: for DSA this holds the problem *slug* (the catalog's primary
    # key is ``text``), while LLD/HLD snippets hold a topic UUID. The column is TEXT and
    # must accommodate both.
    context_id: str
    problem_id: str | None = None
    title: str | None = None
    language: str
    code: str
    is_primary: bool


# -------------------------------------------------------------------------- revisions
# Declared here (rather than in a separate module) so the DSA detail response can embed
# them without a circular import; the revisions router imports them from here too.


class RevisionCreateRequest(BaseModel):
    due_at: datetime | None = Field(
        default=None,
        description="When to review. Defaults to the confidence-based interval from now.",
    )
    reason: str = Field(default="manual", max_length=40)
    priority: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=5_000)


class RevisionResponse(TimestampedModel):
    user_id: uuid.UUID
    problem_id: str
    due_at: datetime
    reason: str
    priority: int
    completed: bool
    completed_at: datetime | None = None
    result: str | None = None
    confidence_before: int | None = None
    interval_days: int | None = None
    notes: str | None = None
    problem_title: str | None = None
    problem_slug: str | None = None
    problem_difficulty: str | None = None
    problem_topic: str | None = None


class RevisionCompleteRequest(BaseModel):
    result: str = Field(default="success", description="One of: success, failed, partial")
    confidence: int | None = Field(default=None, ge=0, le=5)
    notes: str | None = Field(default=None, max_length=5_000)
    schedule_next: bool = Field(
        default=True, description="Queue the next revision using the spaced-repetition ladder."
    )

    @field_validator("result")
    @classmethod
    def _valid_result(cls, value: str) -> str:
        allowed = {"success", "failed", "partial"}
        if value not in allowed:
            raise ValueError(f"result must be one of: {', '.join(sorted(allowed))}")
        return value


class RevisionCompleteResponse(BaseModel):
    revision: RevisionResponse
    progress: ProgressResponse | None = None
    next_revision: RevisionResponse | None = None
    interval_days: int | None = None
    message: str = "Revision recorded"


# --------------------------------------------------------------------------- filters


class DSAProblemFilters(ORMModel):
    """Resolved filter values for the catalog listing."""

    search: str | None = None
    topic: str | None = None
    pattern: str | None = None
    difficulty: Difficulty | None = None
    status: ProblemStatus | None = None
    company: str | None = None
    revision_due: bool | None = None
    source: str | None = None
    is_active: bool | None = True
    favorites_only: bool = False


# Resolve the forward references used by DSAProblemDetail.
DSAProblemDetail.model_rebuild()
