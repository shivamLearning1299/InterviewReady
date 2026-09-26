"""AI tutor conversation storage and per-user rate limiting."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
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

_CONTEXT_TYPE_SQL = "'dsa','lld','hld','general'"
_ROLE_SQL = "'system','user','assistant'"


class AIConversation(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A tutor thread, optionally anchored to a problem or topic."""

    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint(f"context_type IN ({_CONTEXT_TYPE_SQL})", name="context_type_valid"),
        Index("ix_ai_conversations_user_id_updated_at", "user_id", "updated_at"),
        Index("ix_ai_conversations_user_id_context", "user_id", "context_type", "context_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    context_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'general'")
    )
    # Deliberately not FK-constrained: the target table varies with ``context_type``.
    #
    # TEXT, not UUID. `dsa_problems.id` is the problem SLUG (a TEXT primary key), while LLD
    # and HLD topics use UUIDs. Typing this column as UUID made the DSA tutor path
    # impossible: the client sends `context_id="two-sum"`, Pydantic rejected it with a 422
    # before it ever reached the service, and the service's DSA branch already treats the
    # value as `str(context_id)`. TEXT accepts both shapes.
    context_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    context_label: Mapped[str | None] = mapped_column(String(300), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages = relationship(
        "AIMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AIMessage.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIConversation {self.id} {self.context_type}>"


class AIMessage(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A single turn in a conversation."""

    __tablename__ = "ai_messages"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_SQL})", name="role_valid"),
        Index("ix_ai_messages_conversation_id_created_at", "conversation_id", "created_at"),
        Index("ix_ai_messages_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Which code snippet was attached to this turn, if any.
    selected_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Token/latency bookkeeping for the tutor, e.g. {"input_tokens": 120, "latency_ms": 830}
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation = relationship("AIConversation", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIMessage {self.role} {self.id}>"


class AIRateLimitCounter(TimestampMixin, Base):
    """Fixed-window per-user counter for the AI endpoints.

    A database-backed window is used instead of an in-process bucket because the app runs
    multiple uvicorn workers on one host and, in production, multiple Render instances —
    an in-memory counter would let a caller multiply their quota by the worker count.
    """

    __tablename__ = "ai_rate_limits"
    __table_args__ = (
        # No separate unique constraint: the composite primary key on
        # (user_id, window_start) already guarantees one row per user per window, so the
        # uniqueness check is free rather than a second index to maintain.
        Index("ix_ai_rate_limits_window_start", "window_start"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIRateLimitCounter user={self.user_id} count={self.request_count}>"


__all__ = ["AIConversation", "AIMessage", "AIRateLimitCounter"]
