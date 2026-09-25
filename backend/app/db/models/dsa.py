"""User-owned DSA data: progress, attempts, notes and reusable code snippets.

Three of these four tables **already exist** in the Supabase database
(``user_problem_progress``, ``problem_notes``, ``code_snippets``). Their column names are
therefore reproduced exactly as found — including the ``_date`` suffix on timestamps and
``problem_id text`` — so no existing row has to be migrated.

The columns this application adds (``created_at``, ``version``, ``deleted_at`` and friends)
are added additively by migration ``0002``. See ``docs/SCHEMA_MAPPING.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)

_PROBLEM_STATUS_SQL = "'not_started','attempted','solved','needs_revision','mastered'"
_ATTEMPT_OUTCOME_SQL = (
    "'gave_up','partial','solved','solved_with_hint','revision_success','revision_failed'"
)
_LANGUAGE_SQL = "'python','java','swift','cpp','javascript','typescript','go','other'"
_CONTEXT_TYPE_SQL = "'dsa','lld','hld'"


class UserProblemProgress(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """Per-user state for one DSA problem — the row the scheduler and stats read.

    **Existing table.** Columns match the live schema; ``created_at``, ``version``,
    ``deleted_at``, ``revision_count`` and ``is_favorite`` are additive.

    ``confidence`` is ``NOT NULL DEFAULT 3`` in the existing table, so it is typed as
    non-nullable here rather than the nullable 0-5 range used elsewhere in the API.
    """

    __tablename__ = "user_problem_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "problem_id"),
        CheckConstraint(f"status IN ({_PROBLEM_STATUS_SQL})", name="status_valid"),
        CheckConstraint("confidence BETWEEN 0 AND 5", name="confidence_range"),
        # Scheduler hot path: "what is due for this user, soonest first".
        Index(
            "ix_user_problem_progress_user_id_next_revision_date",
            "user_id",
            "next_revision_date",
        ),
        Index("ix_user_problem_progress_user_id_status", "user_id", "status"),
        Index("ix_user_problem_progress_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # TEXT, not UUID: matches the existing column and the text primary key of dsa_problems.
    # No FK to dsa_problems: this column predates the catalog and already holds values
    # that the catalog seed may not yet contain. A FK would reject those existing rows.
    # The service layer validates ids against the catalog on write instead.
    problem_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # `not_started` mirrors the DEFAULT added by migration 0003. Without it, a partial
    # UPSERT (e.g. syncing only `confidence`) fails NOT NULL validation, because
    # PostgreSQL checks the proposed insert row before detecting the conflict.
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'not_started'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Existing column is NOT NULL DEFAULT 3; kept non-null to match.
    confidence: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("3"))

    # Existing `_date`-suffixed columns — names preserved deliberately.
    first_attempt_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    solved_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reviewed_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_revision_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    time_spent_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    # -- additive columns -------------------------------------------------------
    # Number of completed revisions; indexes the spaced-repetition ladder.
    revision_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    problem = relationship(
        "DSAProblem",
        primaryjoin="foreign(UserProblemProgress.problem_id) == DSAProblem.id",
        back_populates="progress",
        viewonly=True,
        lazy="selectin",
    )

    @property
    def is_solved(self) -> bool:
        return self.status in ("solved", "mastered")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserProblemProgress {self.problem_id} status={self.status}>"


class ProblemAttempt(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """A single timed attempt at a problem.

    **New table** — the existing schema has no attempt log, only a counter on progress.
    """

    __tablename__ = "problem_attempts"
    __table_args__ = (
        CheckConstraint(f"outcome IN ({_ATTEMPT_OUTCOME_SQL})", name="outcome_valid"),
        Index(
            "ix_problem_attempts_user_id_problem_id_started_at",
            "user_id",
            "problem_id",
            "started_at",
        ),
        Index("ix_problem_attempts_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # No FK to dsa_problems: this column predates the catalog and already holds values
    # that the catalog seed may not yet contain. A FK would reject those existing rows.
    # The service layer validates ids against the catalog on write instead.
    problem_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    problem = relationship(
        "DSAProblem",
        primaryjoin="foreign(ProblemAttempt.problem_id) == DSAProblem.id",
        back_populates="attempts",
        viewonly=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProblemAttempt {self.problem_id} outcome={self.outcome}>"


class ProblemNote(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """Free-form study notes for one problem; one row per ``(user_id, problem_id)``.

    **Existing table.** The six text columns are ``NOT NULL DEFAULT ''`` in the live
    schema, so this model keeps them non-nullable and the API never writes ``None`` — an
    omitted field is stored as an empty string.
    """

    __tablename__ = "problem_notes"
    __table_args__ = (
        UniqueConstraint("user_id", "problem_id"),
        Index("ix_problem_notes_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    # No FK to dsa_problems: this column predates the catalog and already holds values
    # that the catalog seed may not yet contain. A FK would reject those existing rows.
    # The service layer validates ids against the catalog on write instead.
    problem_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    approach: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    time_complexity: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("''")
    )
    space_complexity: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("''")
    )
    mistakes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    revision_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    problem = relationship(
        "DSAProblem",
        primaryjoin="foreign(ProblemNote.problem_id) == DSAProblem.id",
        back_populates="notes",
        viewonly=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProblemNote {self.problem_id}>"


class CodeSnippet(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """Raw source code — storage only, never compiled or executed.

    **Existing table**, extended to serve LLD and HLD as well as DSA:

    * ``problem_id`` became NULLABLE (an LLD/HLD snippet has no problem), and
    * ``context_type`` / ``context_id`` / ``title`` / ``is_primary`` were added.

    Existing rows are backfilled to ``context_type = 'dsa'`` with ``context_id`` copied
    from ``problem_id``, so the DSA convenience endpoints keep working against old data.
    """

    __tablename__ = "code_snippets"
    __table_args__ = (
        CheckConstraint(f"context_type IN ({_CONTEXT_TYPE_SQL})", name="context_type_valid"),
        CheckConstraint(f"language IN ({_LANGUAGE_SQL})", name="language_valid"),
        Index("ix_code_snippets_user_id_context", "user_id", "context_type", "context_id"),
        Index("ix_code_snippets_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)

    # Existing column, now nullable so topic snippets can live in the same table.
    # See the note on UserProblemProgress.problem_id: no FK, for the same reason.
    problem_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)

    # -- additive columns -------------------------------------------------------
    context_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'dsa'")
    )
    # Not a foreign key: the target table depends on `context_type`.
    context_id: Mapped[str] = mapped_column(String(300), nullable=False, server_default=text("''"))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    # Existing columns.
    language: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CodeSnippet {self.language} {self.context_type}:{self.context_id}>"


__all__ = ["CodeSnippet", "ProblemAttempt", "ProblemNote", "UserProblemProgress"]
