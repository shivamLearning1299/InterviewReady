"""HLD curriculum catalog plus the user's per-topic progress and sectioned notes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)

_TOPIC_STATUS_SQL = "'not_started','learning','completed','needs_revision','mastered'"
_HLD_CATEGORY_SQL = "'fundamentals','system_design'"


class HLDTopic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A high-level design topic: a distributed-systems fundamental or a system design."""

    __tablename__ = "hld_topics"
    __table_args__ = (
        CheckConstraint(f"category IN ({_HLD_CATEGORY_SQL})", name="category_valid"),
        Index("ix_hld_topics_category_order_index", "category", "order_index"),
    )

    title: Mapped[str] = mapped_column(String(250), nullable=False)
    slug: Mapped[str] = mapped_column(String(250), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'system_design'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_objectives: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    key_concepts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'hard'")
    )
    estimated_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("90")
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    progress = relationship(
        "HLDProgress",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes = relationship(
        "HLDNote",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HLDTopic {self.slug}>"


class HLDProgress(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """Per-user HLD topic state. One row per ``(user_id, hld_topic_id)``."""

    __tablename__ = "hld_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "hld_topic_id"),
        CheckConstraint(f"status IN ({_TOPIC_STATUS_SQL})", name="status_valid"),
        CheckConstraint("confidence IS NULL OR (confidence BETWEEN 0 AND 5)", name="confidence_range"),
        Index("ix_hld_progress_user_id_next_revision_at", "user_id", "next_revision_at"),
        Index("ix_hld_progress_user_id_status", "user_id", "status"),
        Index("ix_hld_progress_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    hld_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hld_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'not_started'")
    )
    confidence: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_revision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    total_time_spent_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    topic = relationship("HLDTopic", back_populates="progress")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HLDProgress topic={self.hld_topic_id} status={self.status}>"


class HLDNote(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """The 13-section design document a candidate fills in while practising HLD."""

    __tablename__ = "hld_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "hld_topic_id"),
        Index("ix_hld_notes_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    hld_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("hld_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -- structured design sections ---------------------------------------------
    functional_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    non_functional_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity_estimation: Mapped[str | None] = mapped_column(Text, nullable=True)
    apis: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    high_level_architecture: Mapped[str | None] = mapped_column(Text, nullable=True)
    database_choice: Mapped[str | None] = mapped_column(Text, nullable=True)
    caching: Mapped[str | None] = mapped_column(Text, nullable=True)
    queues: Mapped[str | None] = mapped_column(Text, nullable=True)
    scaling: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_handling: Mapped[str | None] = mapped_column(Text, nullable=True)
    tradeoffs: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    interview_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mistakes: Mapped[str | None] = mapped_column(Text, nullable=True)

    topic = relationship("HLDTopic", back_populates="notes")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HLDNote topic={self.hld_topic_id}>"


__all__ = ["HLDNote", "HLDProgress", "HLDTopic"]
