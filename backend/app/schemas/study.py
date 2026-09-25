"""Study session schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import SessionType
from app.schemas.common import TimestampedModel


class StudySessionStartRequest(BaseModel):
    session_type: SessionType
    context_id: uuid.UUID | None = Field(
        default=None, description="Problem or topic being studied."
    )
    context_label: str | None = Field(default=None, max_length=300)
    device_id: str | None = Field(default=None, max_length=120)
    # Accepted for clients that queue the start offline, but capped to "not in the future"
    # when the server computes the duration.
    started_at: datetime | None = None


class StudySessionResponse(TimestampedModel):
    user_id: uuid.UUID
    session_type: str
    context_id: uuid.UUID | None = None
    context_label: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_minutes: int | None = None
    paused_minutes: int = 0
    note: str | None = None


class StudySessionStopRequest(BaseModel):
    """``duration_minutes`` is deliberately absent.

    Accumulated time is always derived from server timestamps, so neither frontend can
    inflate study time by sending its own timer value — and a backgrounded iOS app that
    missed a pause still reports the honest server-measured duration.
    """

    note: str | None = Field(default=None, max_length=10_000)
    ended_at: datetime | None = None
    update_progress: bool = Field(
        default=True,
        description="Add the measured minutes to the linked problem's progress total.",
    )


class StudySessionListFilters(BaseModel):
    session_type: SessionType | None = None
    context_id: uuid.UUID | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None
    running_only: bool = False
