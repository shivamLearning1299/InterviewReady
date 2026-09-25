"""Daily plan and revision queue repositories."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import RevisionNotFoundError
from app.db.models import DailyPlan, DailyPlanItem, DSAProblem, RevisionQueueItem
from app.utils.datetime_utils import utcnow
from app.utils.upsert import build_upsert_statement


class DailyPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_date(
        self, *, user_id: uuid.UUID, plan_date: date, with_items: bool = True
    ) -> DailyPlan | None:
        stmt = select(DailyPlan).where(
            DailyPlan.user_id == user_id,
            DailyPlan.date_key == plan_date,
            DailyPlan.deleted_at.is_(None),
        )
        if with_items:
            # Eager-load so serialising the plan never triggers lazy IO.
            stmt = stmt.options(selectinload(DailyPlan.items))
        return await self.session.scalar(stmt)

    async def create_plan(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        timezone: str,
        problem_ids: list[str] | None = None,
        generated_by: str = "scheduler_v1",
        lld_topic_id: uuid.UUID | None = None,
        hld_topic_id: uuid.UUID | None = None,
    ) -> DailyPlan:
        """Insert the day's plan.

        ``problem_ids`` is ``NOT NULL`` in the existing schema and is read by pre-existing
        clients, so it is always written — the normalised ``daily_plan_items`` rows are
        added afterwards by :meth:`add_items`.
        """
        plan = DailyPlan(
            user_id=user_id,
            date_key=plan_date,
            timezone=timezone,
            generated_by=generated_by,
            problem_ids=list(problem_ids or []),
            lld_topic_id=lld_topic_id,
            hld_topic_id=hld_topic_id,
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list_plans(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[DailyPlan], int]:
        base = select(DailyPlan).where(
            DailyPlan.user_id == user_id, DailyPlan.deleted_at.is_(None)
        )
        if start_date:
            base = base.where(DailyPlan.date_key >= start_date)
        if end_date:
            base = base.where(DailyPlan.date_key <= end_date)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )
        stmt = (
            base.options(selectinload(DailyPlan.items))
            .order_by(DailyPlan.date_key.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.scalars(stmt)).all()), total

    async def add_items(self, plan: DailyPlan, items: list[dict[str, Any]]) -> list[DailyPlanItem]:
        """Insert plan items and mirror their problem ids into ``plan.problem_ids``.

        The legacy JSONB column is kept in sync here rather than by the caller, so it can
        never drift from ``daily_plan_items``.
        """
        rows = [DailyPlanItem(plan_id=plan.id, user_id=plan.user_id, **item) for item in items]
        self.session.add_all(rows)
        await self.session.flush()

        problem_ids = [row.problem_id for row in rows if row.problem_id]
        if problem_ids:
            existing = list(plan.problem_ids or [])
            # Preserve order, drop duplicates: the array is a set-like summary of the plan.
            merged = list(dict.fromkeys([*existing, *problem_ids]))
            plan.problem_ids = merged
            await self.session.flush()

        return rows

    async def get_item(
        self, *, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> DailyPlanItem | None:
        return await self.session.scalar(
            select(DailyPlanItem).where(
                DailyPlanItem.id == item_id,
                DailyPlanItem.user_id == user_id,
                DailyPlanItem.deleted_at.is_(None),
            )
        )

    async def set_item_completion(
        self, item: DailyPlanItem, *, is_completed: bool
    ) -> DailyPlanItem:
        item.is_completed = is_completed
        item.completed_at = utcnow() if is_completed else None
        item.version = (item.version or 1) + 1
        item.updated_at = utcnow()
        await self.session.flush()
        return item

    async def completion_counts(self, *, user_id: uuid.UUID, plan_id: uuid.UUID) -> dict[str, tuple[int, int]]:
        """``item_type -> (completed, total)`` in one aggregate query."""
        stmt = (
            select(
                DailyPlanItem.item_type,
                func.count(),
                func.count().filter(DailyPlanItem.is_completed.is_(True)),
            )
            .where(
                DailyPlanItem.user_id == user_id,
                DailyPlanItem.plan_id == plan_id,
                DailyPlanItem.deleted_at.is_(None),
            )
            .group_by(DailyPlanItem.item_type)
        )
        return {
            item_type: (int(completed), int(total))
            for item_type, total, completed in (await self.session.execute(stmt)).all()
        }

    async def problem_counts_for_plan(
        self, *, user_id: uuid.UUID, plan_id: uuid.UUID
    ) -> dict[str, int]:
        """``item_type -> number of distinct problems`` for summary responses."""
        stmt = (
            select(DailyPlanItem.item_type, func.count(func.distinct(DailyPlanItem.problem_id)))
            .where(
                DailyPlanItem.user_id == user_id,
                DailyPlanItem.plan_id == plan_id,
                DailyPlanItem.problem_id.is_not(None),
            )
            .group_by(DailyPlanItem.item_type)
        )
        return {item_type: int(count) for item_type, count in (await self.session.execute(stmt)).all()}

    async def list_items_with_problems(
        self,
        *,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        item_type: str | None = None,
    ) -> list[tuple[DailyPlanItem, DSAProblem | None]]:
        """Plan items joined to their problem metadata in one query.

        Returns tuples rather than ORM relationships so the response builder can stay a
        plain function instead of triggering lazy loads.
        """
        stmt = (
            select(DailyPlanItem, DSAProblem)
            .outerjoin(DSAProblem, DSAProblem.id == DailyPlanItem.problem_id)
            .where(
                DailyPlanItem.user_id == user_id,
                DailyPlanItem.plan_id == plan_id,
                DailyPlanItem.deleted_at.is_(None),
            )
            .order_by(DailyPlanItem.position.asc())
        )
        if item_type:
            stmt = stmt.where(DailyPlanItem.item_type == item_type)
        return [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]

    async def list_recent_problem_ids(
        self, *, user_id: uuid.UUID, since: date, item_types: tuple[str, ...] = ("dsa_new",)
    ) -> set[str]:
        """Problems already assigned as new in recent plans.

        This is what stops the scheduler re-assigning the same question day after day.
        """
        stmt = select(DailyPlanItem.problem_id).join(
            DailyPlan, DailyPlan.id == DailyPlanItem.plan_id
        ).where(
            DailyPlanItem.user_id == user_id,
            DailyPlanItem.problem_id.is_not(None),
            DailyPlanItem.item_type.in_(item_types),
            DailyPlan.date_key >= since,
        )
        return {row for row in (await self.session.scalars(stmt)).all() if row}

    async def mark_completed(self, *, user_id: uuid.UUID, plan_id: uuid.UUID) -> None:
        await self.session.execute(
            update(DailyPlan)
            .where(DailyPlan.id == plan_id, DailyPlan.user_id == user_id)
            .values(status="completed", version=DailyPlan.version + 1, updated_at=func.now())
        )

    async def upsert_plan_by_id(
        self,
        *,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        values: dict[str, Any],
    ) -> DailyPlan:
        payload = {"id": plan_id, "user_id": user_id, **values}
        stmt = build_upsert_statement(
            DailyPlan, payload, conflict_columns=["id"], increment_version=True
        )
        return (await self.session.execute(stmt)).scalars().one()


class RevisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, user_id: uuid.UUID, revision_id: uuid.UUID) -> RevisionQueueItem:
        revision = await self.session.scalar(
            select(RevisionQueueItem).where(
                RevisionQueueItem.id == revision_id,
                RevisionQueueItem.user_id == user_id,
                RevisionQueueItem.deleted_at.is_(None),
            )
        )
        if revision is None:
            raise RevisionNotFoundError()
        return revision

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        bucket: str | None = None,
        completed: bool | None = False,
        now: datetime | None = None,
        problem_ids: list[str] | None = None,
    ) -> tuple[list[tuple[RevisionQueueItem, DSAProblem | None]], int]:
        """List revisions with problem metadata joined in, plus a status bucket filter."""
        reference = now or utcnow()

        base = (
            select(RevisionQueueItem, DSAProblem)
            .outerjoin(DSAProblem, DSAProblem.id == RevisionQueueItem.problem_id)
            .where(
                RevisionQueueItem.user_id == user_id,
                RevisionQueueItem.deleted_at.is_(None),
            )
        )

        if completed is not None:
            base = base.where(RevisionQueueItem.completed.is_(completed))

        if bucket == "due":
            base = base.where(
                RevisionQueueItem.completed.is_(False),
                RevisionQueueItem.due_at <= reference,
            )
        elif bucket == "overdue":
            # Overdue means more than a day past due, so "due today" is not alarming.
            base = base.where(
                RevisionQueueItem.completed.is_(False),
                RevisionQueueItem.due_at < reference - timedelta(days=1),
            )
        elif bucket == "upcoming":
            base = base.where(
                RevisionQueueItem.completed.is_(False),
                RevisionQueueItem.due_at > reference,
            )

        if problem_ids:
            base = base.where(RevisionQueueItem.problem_id.in_(problem_ids))

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )

        # Overdue/highest-priority first, then earliest due.
        stmt = (
            base.order_by(
                RevisionQueueItem.completed.asc(),
                RevisionQueueItem.priority.desc(),
                RevisionQueueItem.due_at.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]
        return rows, total

    async def list_for_problem(
        self, *, user_id: uuid.UUID, problem_id: str, limit: int = 20
    ) -> list[RevisionQueueItem]:
        stmt = (
            select(RevisionQueueItem)
            .where(
                RevisionQueueItem.user_id == user_id,
                RevisionQueueItem.problem_id == problem_id,
                RevisionQueueItem.deleted_at.is_(None),
            )
            .order_by(RevisionQueueItem.due_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_open_for_problem(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> RevisionQueueItem | None:
        """The pending revision for a problem, if one exists."""
        return await self.session.scalar(
            select(RevisionQueueItem)
            .where(
                RevisionQueueItem.user_id == user_id,
                RevisionQueueItem.problem_id == problem_id,
                RevisionQueueItem.completed.is_(False),
                RevisionQueueItem.deleted_at.is_(None),
            )
            .order_by(RevisionQueueItem.due_at.asc())
            .limit(1)
        )

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        due_at: datetime,
        reason: str,
        priority: int = 3,
        interval_days: int | None = None,
        confidence_before: int | None = None,
        notes: str | None = None,
    ) -> RevisionQueueItem:
        revision = RevisionQueueItem(
            user_id=user_id,
            problem_id=problem_id,
            due_at=due_at,
            reason=reason,
            priority=priority,
            interval_days=interval_days,
            confidence_before=confidence_before,
            notes=notes,
        )
        self.session.add(revision)
        await self.session.flush()
        return revision

    async def upsert_open_revision(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        due_at: datetime,
        reason: str,
        priority: int = 3,
        interval_days: int | None = None,
        confidence_before: int | None = None,
    ) -> RevisionQueueItem:
        """Reschedule an existing open revision instead of stacking duplicates.

        Without this, hitting "schedule revision" twice would leave two pending rows for
        the same problem and inflate the due count.
        """
        existing = await self.get_open_for_problem(user_id=user_id, problem_id=problem_id)
        if existing is not None:
            existing.due_at = due_at
            existing.reason = reason
            existing.priority = priority
            existing.interval_days = interval_days
            existing.confidence_before = confidence_before
            existing.version = (existing.version or 1) + 1
            existing.updated_at = utcnow()
            await self.session.flush()
            return existing

        return await self.create(
            user_id=user_id,
            problem_id=problem_id,
            due_at=due_at,
            reason=reason,
            priority=priority,
            interval_days=interval_days,
            confidence_before=confidence_before,
        )

    async def complete(
        self,
        revision: RevisionQueueItem,
        *,
        result: str,
        confidence_after: int | None = None,
        notes: str | None = None,
    ) -> RevisionQueueItem:
        """Mark a revision done. Idempotent: a completed revision is left untouched."""
        if revision.completed:
            return revision

        revision.completed = True
        revision.completed_at = utcnow()
        revision.result = result
        if confidence_after is not None:
            revision.confidence_before = revision.confidence_before
        if notes is not None:
            revision.notes = notes
        revision.version = (revision.version or 1) + 1
        revision.updated_at = utcnow()
        await self.session.flush()
        return revision

    async def due_counts(self, *, user_id: uuid.UUID, now: datetime | None = None) -> dict[str, int]:
        """``due`` / ``overdue`` / ``upcoming`` counts in a single query."""
        reference = now or utcnow()
        day_ago = reference - timedelta(days=1)

        stmt = select(
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    RevisionQueueItem.due_at <= reference,
                )
            ),
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    RevisionQueueItem.due_at < day_ago,
                )
            ),
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    RevisionQueueItem.due_at > reference,
                )
            ),
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    func.date(RevisionQueueItem.due_at) == func.date(reference),
                )
            ),
        ).where(
            RevisionQueueItem.user_id == user_id,
            RevisionQueueItem.deleted_at.is_(None),
        )

        row = (await self.session.execute(stmt)).one()
        return {
            "due": int(row[0] or 0),
            "overdue": int(row[1] or 0),
            "upcoming": int(row[2] or 0),
            "due_today": int(row[3] or 0),
        }

    async def list_due_for_plan(
        self, *, user_id: uuid.UUID, now: datetime, limit: int
    ) -> list[RevisionQueueItem]:
        stmt = (
            select(RevisionQueueItem)
            .where(
                RevisionQueueItem.user_id == user_id,
                RevisionQueueItem.completed.is_(False),
                RevisionQueueItem.due_at <= now,
                RevisionQueueItem.deleted_at.is_(None),
            )
            .order_by(RevisionQueueItem.priority.desc(), RevisionQueueItem.due_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def completed_count_since(
        self, *, user_id: uuid.UUID, since: datetime
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    RevisionQueueItem.user_id == user_id,
                    RevisionQueueItem.completed.is_(True),
                    RevisionQueueItem.completed_at >= since,
                    RevisionQueueItem.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def upsert_by_id(
        self, *, user_id: uuid.UUID, revision_id: uuid.UUID, values: dict[str, Any]
    ) -> RevisionQueueItem:
        payload = {"id": revision_id, "user_id": user_id, **values}
        stmt = build_upsert_statement(
            RevisionQueueItem, payload, conflict_columns=["id"], increment_version=True
        )
        return (await self.session.execute(stmt)).scalars().one()
