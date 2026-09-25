"""Master DSA problem catalog.

Metadata only — title, slug, classification and a link to the original problem. We do not
store LeetCode/GFG problem statements or solutions, so the catalog stays free of
copyrighted text while still driving the scheduler.

The primary key is ``text`` (the slug), matching the pre-existing ``problem_id text``
columns in ``user_problem_progress``, ``problem_notes``, ``code_snippets`` and
``daily_plans.problem_ids``. See ``docs/SCHEMA_MAPPING.md``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import Difficulty
from app.db.base import Base, StringPrimaryKeyMixin


class DSAProblem(StringPrimaryKeyMixin, Base):
    """A single interview question in the catalog.

    ``dsa_problems`` is a new table (the existing database has no catalog), seeded from
    ``app/seed_data/dsa_problems.json`` with slug-stable idempotent upserts.
    """

    __tablename__ = "dsa_problems"
    __table_args__ = (
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="difficulty_valid"),
        Index("ix_dsa_problems_slug", "slug", unique=True),
        # Drives "browse by topic, easiest first" and the scheduler's curriculum walk.
        Index("ix_dsa_problems_primary_topic_order_index", "primary_topic", "order_index"),
        Index("ix_dsa_problems_difficulty_order_index", "difficulty", "order_index"),
        # GIN indexes so `patterns @> ARRAY[...]` and `companies && ARRAY[...]` stay fast.
        Index("ix_dsa_problems_patterns_gin", "patterns", postgresql_using="gin"),
        Index("ix_dsa_problems_companies_gin", "companies", postgresql_using="gin"),
    )

    # -- identity ---------------------------------------------------------------
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Kept in sync with `id` by the seed script; exposed because the API contract and seed
    # data both refer to problems by slug.
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'leetcode'")
    )

    # -- classification ---------------------------------------------------------
    difficulty: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'medium'")
    )
    primary_topic: Mapped[str] = mapped_column(String(100), nullable=False)
    secondary_topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    patterns: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    companies: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    problem_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'algorithmic'")
    )

    # -- scheduling metadata ----------------------------------------------------
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # 1-5; how central the problem is to an interview-ready curriculum.
    importance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    estimated_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    hints: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # -- relationships ----------------------------------------------------------
    # These carry no foreign key, because `problem_id` in the pre-existing tables holds
    # values that may predate the catalog. Each join is therefore declared explicitly and
    # marked `viewonly`: the ORM may read through them, but persistence is always driven by
    # the repositories so a stale relationship can never produce a surprise write.
    progress = relationship(
        "UserProblemProgress",
        primaryjoin="DSAProblem.id == foreign(UserProblemProgress.problem_id)",
        back_populates="problem",
        viewonly=True,
        lazy="selectin",
    )
    attempts = relationship(
        "ProblemAttempt",
        primaryjoin="DSAProblem.id == foreign(ProblemAttempt.problem_id)",
        back_populates="problem",
        viewonly=True,
    )
    notes = relationship(
        "ProblemNote",
        primaryjoin="DSAProblem.id == foreign(ProblemNote.problem_id)",
        back_populates="problem",
        viewonly=True,
    )
    revisions = relationship(
        "RevisionQueueItem",
        primaryjoin="DSAProblem.id == foreign(RevisionQueueItem.problem_id)",
        back_populates="problem",
        viewonly=True,
    )
    plan_items = relationship(
        "DailyPlanItem",
        primaryjoin="DSAProblem.id == foreign(DailyPlanItem.problem_id)",
        back_populates="problem",
        viewonly=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DSAProblem {self.id} ({self.difficulty})>"


class DSATopic(StringPrimaryKeyMixin, Base):
    """Normalized topic list backing filter dropdowns and stats labels.

    ``dsa_problems.primary_topic`` stays free text so a seed can never fail on an unknown
    topic name, while this table gives clients stable display names and ordering.
    """

    __tablename__ = "dsa_topics"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default=text("'general'")
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DSATopic {self.id}>"


DIFFICULTY_VALUES = tuple(item.value for item in Difficulty)

__all__ = ["DIFFICULTY_VALUES", "DSAProblem", "DSATopic"]
