"""DSA catalog queries.

The listing query is the one that matters for performance. It joins the user's progress
in a single statement and returns ``(DSAProblem, UserProblemProgress | None)`` row tuples,
so rendering a 50-item page costs one round trip instead of one per problem.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.constants import ProblemStatus
from app.core.exceptions import ProblemNotFoundError
from app.db.models import DSAProblem, DSATopic, UserProblemProgress
from app.repositories.base import BaseRepository


class DSAProblemRepository(BaseRepository[DSAProblem]):
    """Catalog queries.

    Problem ids are ``str`` (the slug), matching the pre-existing ``problem_id text``
    columns throughout the database. See ``docs/SCHEMA_MAPPING.md``.
    """

    model = DSAProblem

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------ base builders
    @staticmethod
    def _apply_filters(
        stmt: Select[Any],
        *,
        user_id: uuid.UUID,
        progress_join: Any,
        search: str | None = None,
        topic: str | None = None,
        pattern: str | None = None,
        difficulty: str | None = None,
        status: str | None = None,
        company: str | None = None,
        source: str | None = None,
        is_active: bool | None = True,
        favorites_only: bool = False,
        revision_due: bool = False,
        now: datetime | None = None,
    ) -> Select[Any]:
        """Apply every catalog filter, in one place so list and count stay in sync."""
        conditions: list[Any] = []

        if is_active is not None:
            conditions.append(DSAProblem.is_active.is_(is_active))

        if search:
            # Match title first-class; slug/topic matching keeps "arrays" finding
            # "Two Sum (arrays)" style slugs without needing a second request.
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(DSAProblem.title).like(term),
                    func.lower(DSAProblem.slug).like(term),
                    func.lower(DSAProblem.primary_topic).like(term),
                )
            )

        if topic:
            # Match either the primary topic or any secondary topic.
            conditions.append(
                or_(
                    func.lower(DSAProblem.primary_topic) == topic.strip().lower(),
                    DSAProblem.secondary_topics.any(topic.strip().lower()),
                )
            )

        if pattern:
            # PostgreSQL `@>` containment against the ARRAY column.
            conditions.append(DSAProblem.patterns.contains([pattern]))

        if difficulty:
            conditions.append(DSAProblem.difficulty == difficulty)

        if company:
            case_insensitive = func.lower(func.array_to_string(DSAProblem.companies, ","))
            conditions.append(case_insensitive.like(f"%{company.strip().lower()}%"))

        if source:
            conditions.append(DSAProblem.source == source)

        if favorites_only:
            conditions.append(progress_join.is_favorite.is_(True))

        if status:
            normalized = status.value if hasattr(status, "value") else status
            if normalized == ProblemStatus.NOT_STARTED.value:
                # "not_started" must include problems with no progress row at all.
                conditions.append(
                    or_(
                        progress_join.id.is_(None),
                        progress_join.status == ProblemStatus.NOT_STARTED.value,
                    )
                )
            else:
                conditions.append(progress_join.status == normalized)

        if revision_due and now is not None:
            conditions.append(
                and_(
                    # The pre-existing column is `next_revision_date`, not `..._at`.
                    progress_join.next_revision_date.is_not(None),
                    progress_join.next_revision_date <= now,
                )
            )

        return stmt.where(*conditions) if conditions else stmt

    def _progress_joined_select(self, user_id: uuid.UUID, *, include_deleted: bool = False) -> Any:
        """``SELECT dsa_problems.*, user_problem_progress.*`` for one user.

        A LEFT JOIN is required (not an inner join) so unsolved problems still appear in
        the catalog. ``populate_existing`` is not needed because the progress entity is
        built per row by SQLAlchemy's entity deduplication, not from the identity map.
        """
        progress = aliased(UserProblemProgress)
        join_condition = and_(
            progress.problem_id == DSAProblem.id,
            progress.user_id == user_id,
        )
        if not include_deleted:
            join_condition = and_(join_condition, progress.deleted_at.is_(None))

        return select(DSAProblem, progress).outerjoin(progress, join_condition)

    # ------------------------------------------------------------------------- queries
    async def list_with_progress(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        order_by: str = "curriculum",
        search: str | None = None,
        topic: str | None = None,
        pattern: str | None = None,
        difficulty: str | None = None,
        status: str | None = None,
        company: str | None = None,
        source: str | None = None,
        is_active: bool | None = True,
        favorites_only: bool = False,
        revision_due: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[tuple[DSAProblem, UserProblemProgress | None]], int]:
        """Return one page of catalog rows plus the total matching count."""
        base = self._progress_joined_select(user_id)
        base = self._apply_filters(
            base,
            user_id=user_id,
            progress_join=base.selected_columns[1],
            search=search,
            topic=topic,
            pattern=pattern,
            difficulty=difficulty,
            status=status,
            company=company,
            source=source,
            is_active=is_active,
            favorites_only=favorites_only,
            revision_due=revision_due,
            now=now,
        )

        # Total is computed on the filtered set before ordering/paging. `count(*)` over a
        # LEFT JOIN is safe here because the join is 1:1 on (user_id, problem_id).
        count_stmt = select(func.count()).select_from(base.order_by(None).subquery())
        total = int(await self.session.scalar(count_stmt) or 0)

        if order_by == "difficulty":
            ordering = [
                # easy -> medium -> hard
                func.array_position(["easy", "medium", "hard"], DSAProblem.difficulty),
                DSAProblem.order_index,
            ]
        elif order_by == "title":
            ordering = [DSAProblem.title.asc()]
        elif order_by == "importance":
            ordering = [DSAProblem.importance.desc(), DSAProblem.order_index.asc()]
        elif order_by == "recent":
            ordering = [base.selected_columns[1].updated_at.desc().nullslast(), DSAProblem.order_index]
        else:  # curriculum (default): the seeded teaching order
            ordering = [DSAProblem.order_index.asc(), DSAProblem.title.asc()]

        stmt = base.order_by(*ordering).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        rows = [(row[0], row[1]) for row in result.all()]
        return rows, total

    async def get_with_progress(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> tuple[DSAProblem, UserProblemProgress | None]:
        """Single problem plus the caller's progress, or 404."""
        stmt = self._progress_joined_select(user_id).where(DSAProblem.id == problem_id).limit(1)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise ProblemNotFoundError()

        problem: DSAProblem = row[0]
        if not problem.is_active:
            # An inactive problem is hidden from the catalog, but a detail page may still be
            # reached from a saved link; treat it as not found rather than leaking it.
            raise ProblemNotFoundError()
        return problem, row[1]

    async def get_by_slug(self, slug: str) -> DSAProblem | None:
        return await self.session.scalar(
            select(DSAProblem).where(DSAProblem.slug == slug).limit(1)
        )

    async def get_by_ids(self, problem_ids: list[str]) -> dict[str, DSAProblem]:
        """Batch-load problems by id (used by the plan/detail join paths)."""
        if not problem_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(DSAProblem).where(DSAProblem.id.in_(problem_ids))
            )
        ).all()
        return {problem.id: problem for problem in rows}

    async def existing_ids(self, problem_ids: list[str]) -> set[str]:
        """Which of the supplied ids actually exist in the catalog."""
        if not problem_ids:
            return set()
        rows = await self.session.scalars(
            select(DSAProblem.id).where(DSAProblem.id.in_(problem_ids))
        )
        return set(rows.all())

    async def list_all_for_scheduling(
        self,
        *,
        user_id: uuid.UUID,
        limit: int | None = None,
    ) -> list[tuple[DSAProblem, UserProblemProgress | None]]:
        """Active catalog plus the user's progress, ordered for the scheduler.

        The daily planner needs the whole curriculum plus progress to score candidates.
        This is a single query by design — the alternative (one query per candidate) is
        exactly the N+1 the requirements forbid.
        """
        stmt = self._progress_joined_select(user_id).where(DSAProblem.is_active.is_(True))
        stmt = stmt.order_by(DSAProblem.order_index.asc(), DSAProblem.difficulty.asc())
        if limit:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    # --------------------------------------------------------------------- aggregation
    async def count_by_topic(self, *, active_only: bool = True) -> dict[str, int]:
        """Total problems per primary topic."""
        stmt = select(DSAProblem.primary_topic, func.count()).group_by(DSAProblem.primary_topic)
        if active_only:
            stmt = stmt.where(DSAProblem.is_active.is_(True))
        return {topic: int(count) for topic, count in (await self.session.execute(stmt)).all()}

    async def count_by_difficulty(self, *, active_only: bool = True) -> dict[str, int]:
        stmt = select(DSAProblem.difficulty, func.count()).group_by(DSAProblem.difficulty)
        if active_only:
            stmt = stmt.where(DSAProblem.is_active.is_(True))
        return {difficulty: int(count) for difficulty, count in (await self.session.execute(stmt)).all()}

    async def list_topics(self, *, active_only: bool = True) -> list[DSATopic]:
        stmt = select(DSATopic).order_by(DSATopic.order_index.asc(), DSATopic.name.asc())
        if active_only:
            stmt = stmt.where(DSATopic.is_active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def distinct_patterns(self) -> list[str]:
        """Every distinct pattern in the catalog, for filter dropdowns."""
        stmt = select(func.distinct(func.unnest(DSAProblem.patterns)))
        return sorted(
            pattern for pattern in (await self.session.scalars(stmt)).all() if pattern
        )

    async def distinct_companies(self) -> list[str]:
        stmt = select(func.distinct(func.unnest(DSAProblem.companies)))
        return sorted(
            company for company in (await self.session.scalars(stmt)).all() if company
        )

    async def curriculum_position_map(self) -> dict[str, int]:
        """``problem_id -> order_index`` for the whole catalog.

        The planner uses this to prefer earlier curriculum material without embedding
        catalogue SQL in the scheduling logic.
        """
        stmt = select(DSAProblem.id, DSAProblem.order_index).where(DSAProblem.is_active.is_(True))
        return {row[0]: int(row[1]) for row in (await self.session.execute(stmt)).all()}
