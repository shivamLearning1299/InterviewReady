"""Daily planning and the spaced-repetition revision queue.

``daily_plans`` **already exists**, and two of its properties shape this module:

* ``problem_ids jsonb NOT NULL`` — a JSON array of problem ids. The application keeps a
  normalised ``daily_plan_items`` table for ordering, typing and completion tracking, but
  **must also populate ``problem_ids``** on every insert, because the column is
  ``NOT NULL`` and pre-existing clients read it.
* ``date_key date`` — the plan's day column, named as found.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)

_ITEM_TYPE_SQL = "'dsa_new','dsa_revision','lld','hld'"
_PLAN_STATUS_SQL = "'active','completed','abandoned'"
_REVISION_REASON_SQL = (
    "'low_confidence','failed_attempt','scheduled_revision','manual','long_time_since_review'"
)


class DailyPlan(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """One plan per user per local calendar day.

    **Existing table.** ``date_key`` and ``problem_ids`` are the original columns;
    ``status``, ``timezone``, ``generated_by``, ``created_at``, ``version`` and
    ``deleted_at`` are additive.

    ``unique(user_id, date_key)`` is the correctness guarantee behind ``GET /api/v1/today``:
    concurrent requests race to insert, every loser re-reads the winner's row, so a plan is
    generated at most once per day and calling the endpoint repeatedly returns identical
    data.
    """

    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "date_key"),
        CheckConstraint(f"status IN ({_PLAN_STATUS_SQL})", name="status_valid"),
        Index("ix_daily_plans_user_id_date_key", "user_id", "date_key"),
        Index("ix_daily_plans_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    # Existing column: the plan's local calendar day.
    date_key: Mapped[date] = mapped_column(Date, nullable=False)

    # Existing column: `NOT NULL` JSON array of problem ids. Kept authoritative for the
    # legacy shape and written alongside `daily_plan_items` on every generation.
    problem_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    # Existing nullable columns reserved for a single LLD/HLD focus of the day.
    lld_topic_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    hld_topic_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # -- additive columns -------------------------------------------------------
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
    # Which scheduler version produced this plan, so quality changes are traceable.
    generated_by: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'scheduler_v1'")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    items = relationship(
        "DailyPlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DailyPlanItem.position",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DailyPlan {self.date_key} user={self.user_id}>"


class DailyPlanItem(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A single scheduled activity inside a daily plan.

    **New table.** ``daily_plans.problem_ids`` stores only a flat id array with no notion
    of ordering, type or completion, so this table carries that structure. The two are
    written together: ``problem_ids`` for compatibility, these rows for the application.
    """

    __tablename__ = "daily_plan_items"
    __table_args__ = (
        UniqueConstraint("plan_id", "item_type", "problem_id"),
        CheckConstraint(f"item_type IN ({_ITEM_TYPE_SQL})", name="item_type_valid"),
        Index("ix_daily_plan_items_plan_id_position", "plan_id", "position"),
        Index("ix_daily_plan_items_user_id_completed_at", "user_id", "completed_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("daily_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    problem_id: Mapped[str | None] = mapped_column(
        String(300),
        ForeignKey("dsa_problems.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Not FK-constrained: the target is lld_topics or hld_topics depending on item_type.
    topic_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Denormalised for rendering a plan without joining the catalog.
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Why the scheduler chose this item — shown in the UI as a short rationale.
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Deterministic scheduler score, kept for debugging plan quality.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan = relationship("DailyPlan", back_populates="items")
    problem = relationship(
        "DSAProblem",
        primaryjoin="foreign(DailyPlanItem.problem_id) == DSAProblem.id",
        back_populates="plan_items",
        viewonly=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DailyPlanItem {self.item_type} pos={self.position} done={self.is_completed}>"


class RevisionQueueItem(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A problem scheduled for review, with progress through the spaced-repetition ladder.

    **New table.** ``user_problem_progress.next_revision_date`` still holds the single
    "next due" instant used by the scheduler; this table records the full queue, including
    history of completed reviews.
    """

    __tablename__ = "revision_queue"
    __table_args__ = (
        CheckConstraint(f"reason IN ({_REVISION_REASON_SQL})", name="reason_valid"),
        # Primary read pattern: this user's outstanding revisions, soonest first.
        Index("ix_revision_queue_user_id_completed_due_at", "user_id", "completed", "due_at"),
        Index("ix_revision_queue_user_id_problem_id", "user_id", "problem_id"),
        Index("ix_revision_queue_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    problem_id: Mapped[str] = mapped_column(
        String(300),
        ForeignKey("dsa_problems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'scheduled_revision'")
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence_before: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    problem = relationship(
        "DSAProblem",
        primaryjoin="foreign(RevisionQueueItem.problem_id) == DSAProblem.id",
        back_populates="revisions",
        viewonly=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RevisionQueueItem {self.problem_id} due={self.due_at} done={self.completed}>"


__all__ = ["DailyPlan", "DailyPlanItem", "RevisionQueueItem"]
