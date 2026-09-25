"""LLD curriculum catalog plus the user's per-topic progress and notes."""

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
_LLD_CATEGORY_SQL = "'fundamentals','design_patterns','design_exercises'"


class LLDTopic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A low-level design topic: a fundamental, a pattern, or a design exercise."""

    __tablename__ = "lld_topics"
    __table_args__ = (
        CheckConstraint(f"category IN ({_LLD_CATEGORY_SQL})", name="category_valid"),
        Index("ix_lld_topics_category_order_index", "category", "order_index"),
    )

    title: Mapped[str] = mapped_column(String(250), nullable=False)
    slug: Mapped[str] = mapped_column(String(250), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'fundamentals'")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original, self-authored study prompts — never copied problem statements.
    learning_objectives: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    key_concepts: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'medium'")
    )
    estimated_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    progress = relationship(
        "LLDProgress",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes = relationship(
        "LLDNote",
        back_populates="topic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LLDTopic {self.slug}>"


class LLDProgress(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """Per-user LLD topic state. One row per ``(user_id, lld_topic_id)``."""

    __tablename__ = "lld_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "lld_topic_id"),
        CheckConstraint(f"status IN ({_TOPIC_STATUS_SQL})", name="status_valid"),
        CheckConstraint("confidence IS NULL OR (confidence BETWEEN 0 AND 5)", name="confidence_range"),
        Index("ix_lld_progress_user_id_next_revision_at", "user_id", "next_revision_at"),
        Index("ix_lld_progress_user_id_status", "user_id", "status"),
        Index("ix_lld_progress_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    lld_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lld_topics.id", ondelete="CASCADE"),
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

    topic = relationship("LLDTopic", back_populates="progress")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LLDProgress topic={self.lld_topic_id} status={self.status}>"


class LLDNote(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """One structured note document per ``(user_id, lld_topic_id)``."""

    __tablename__ = "lld_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "lld_topic_id"),
        Index("ix_lld_notes_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    lld_topic_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lld_topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    design_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    class_responsibilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    relationships: Mapped[str | None] = mapped_column(Text, nullable=True)
    design_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mistakes: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    patterns_used: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # Structured class/relationship map authored by the user, e.g.
    # [{"name": "Order", "responsibilities": "...", "collaborators": ["Payment"]}]
    class_diagram: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    topic = relationship("LLDTopic", back_populates="notes")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LLDNote topic={self.lld_topic_id}>"


__all__ = ["LLDNote", "LLDProgress", "LLDTopic"]
