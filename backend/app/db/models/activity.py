"""Study sessions and the per-day activity ledger that drives streaks.

``study_sessions`` **already exists** with a very different shape from the API contract:

    Existing:  id, user_id, date timestamptz, minutes int, area text, updated_at
    Needed:    start/stop timers, session_type, a running state, a link to a problem

Both are reconciled on one table. ``date`` and ``area`` are the original columns and are
kept populated (``date`` = start instant, ``area`` = session type) so anything already
reading this table keeps working; ``minutes`` stays ``NOT NULL`` and holds ``0`` while a
session is still running. The timer columns the API needs are additive.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)

_SESSION_TYPE_SQL = "'dsa','lld','hld','revision','mock_interview'"


class StudySession(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A timed study block.

    ``date``, ``minutes`` and ``area`` are the pre-existing columns; ``area`` mirrors
    ``session_type`` so existing readers of the legacy column still see a meaningful value.

    ``duration_minutes`` is computed server-side on stop, never taken from a client timer,
    so a backgrounded app or a tampered device clock cannot inflate study time.
    """

    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint(f"session_type IN ({_SESSION_TYPE_SQL})", name="session_type_valid"),
        Index("ix_study_sessions_user_id_date", "user_id", "date"),
        Index("ix_study_sessions_user_id_started_at", "user_id", "started_at"),
        Index("ix_study_sessions_user_id_updated_at", "user_id", "updated_at"),
        # Enforce "at most one running session per user" in the database itself, so a
        # double-tap on "start" cannot open two timers.
        Index(
            "uq_study_sessions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL AND deleted_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    # -- existing columns -------------------------------------------------------
    # Legacy "when did this happen" instant. Set to the session start.
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # NOT NULL in the existing schema; holds 0 until the session is stopped, at which point
    # it equals `duration_minutes`.
    minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Legacy free-text category. Mirrors `session_type` for backwards compatibility.
    area: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'dsa'"))

    # -- additive columns -------------------------------------------------------
    session_type: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'dsa'")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Not FK-constrained: the target is a problem or a topic depending on session_type.
    context_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    context_label: Mapped[str | None] = mapped_column(String(300), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    @property
    def is_running(self) -> bool:
        return self.ended_at is None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StudySession {self.session_type} running={self.is_running}>"


class UserActivityDay(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    """One row per user per local calendar day that had meaningful study activity.

    **New table.** Materialised deliberately: a streak is read on every app launch and must
    never be recomputed by scanning attempts, revisions and study sessions. Clients never
    calculate a streak themselves — they read what this table produces.
    """

    __tablename__ = "user_activity_days"
    __table_args__ = (
        UniqueConstraint("user_id", "activity_date"),
        Index("ix_user_activity_days_user_id_activity_date", "user_id", "activity_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))

    activity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    study_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    problems_solved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    problems_attempted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    revisions_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    topics_completed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Denormalised for cheap "was this day active?" filtering.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserActivityDay {self.activity_date} minutes={self.study_minutes}>"


__all__ = ["StudySession", "UserActivityDay"]
