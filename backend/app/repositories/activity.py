"""Study session and daily activity ledger repositories."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StudySessionNotFoundError
from app.db.models import StudySession, UserActivityDay
from app.utils.datetime_utils import utcnow


class StudySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> StudySession:
        session_row = await self.session.scalar(
            select(StudySession).where(
                StudySession.id == session_id,
                StudySession.user_id == user_id,
                StudySession.deleted_at.is_(None),
            )
        )
        if session_row is None:
            raise StudySessionNotFoundError()
        return session_row

    async def find(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> StudySession | None:
        """Look up a session without raising when it is absent.

        ``get`` raises ``StudySessionNotFoundError``, which is right for a REST endpoint
        where a missing row is a 404. The sync handler needs the opposite: an upsert has to
        distinguish "create" from "update", and a fresh create has no existing row. Using
        ``get`` there would turn every insert into a rejection.
        """
        return await self.session.scalar(
            select(StudySession).where(
                StudySession.id == session_id,
                StudySession.user_id == user_id,
                StudySession.deleted_at.is_(None),
            )
        )

    async def get_running(self, *, user_id: uuid.UUID) -> StudySession | None:
        """The user's currently running session, if any.

        A partial unique index enforces at most one, so this is a single-row lookup.
        """
        return await self.session.scalar(
            select(StudySession)
            .where(
                StudySession.user_id == user_id,
                StudySession.ended_at.is_(None),
                StudySession.deleted_at.is_(None),
            )
            .order_by(StudySession.started_at.desc())
            .limit(1)
        )

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        session_type: str,
        context_id: str | None = None,
        context_label: str | None = None,
        started_at: datetime | None = None,
        device_id: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> StudySession:
        """Open a new session.

        The pre-existing ``date``, ``minutes`` and ``area`` columns are populated too:
        ``date`` gets the start instant (defaulting to now), ``minutes`` starts at 0 because
        the existing column is ``NOT NULL``, and ``area`` mirrors ``session_type`` so any
        existing reader of the legacy column still sees a sensible value.
        """
        start = started_at or utcnow()
        session_row = StudySession(
            # A session queued offline already has an id assigned by the device. Honouring
            # it is what lets the client correlate its local row with the server's after a
            # push (see `UUIDPrimaryKeyMixin`: ids are generated client-side precisely so
            # offline devices can pre-assign them). Without this the server would mint a
            # new id and the client could never match the two.
            **({"id": session_id} if session_id is not None else {}),
            user_id=user_id,
            session_type=session_type,
            area=session_type,
            date=start,
            minutes=0,
            context_id=context_id,
            context_label=context_label,
            started_at=start,
            device_id=device_id,
        )
        self.session.add(session_row)
        await self.session.flush()
        return session_row

    async def stop(
        self,
        session_row: StudySession,
        *,
        ended_at: datetime,
        duration_minutes: int,
        note: str | None = None,
    ) -> StudySession:
        session_row.ended_at = ended_at
        session_row.duration_minutes = duration_minutes
        # Keep the legacy NOT NULL column authoritative for existing readers.
        session_row.minutes = duration_minutes
        if note is not None:
            session_row.note = note
        session_row.version = (session_row.version or 1) + 1
        session_row.updated_at = utcnow()
        await self.session.flush()
        return session_row

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        session_type: str | None = None,
        context_id: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        running_only: bool = False,
    ) -> tuple[list[StudySession], int]:
        base = select(StudySession).where(
            StudySession.user_id == user_id, StudySession.deleted_at.is_(None)
        )
        if session_type:
            base = base.where(StudySession.session_type == session_type)
        if context_id:
            base = base.where(StudySession.context_id == context_id)
        if started_after:
            base = base.where(StudySession.started_at >= started_after)
        if started_before:
            base = base.where(StudySession.started_at <= started_before)
        if running_only:
            base = base.where(StudySession.ended_at.is_(None))

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )
        stmt = base.order_by(StudySession.started_at.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all()), total

    async def minutes_in_range(
        self, *, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> int:
        value = await self.session.scalar(
            select(func.coalesce(func.sum(StudySession.duration_minutes), 0)).where(
                StudySession.user_id == user_id,
                StudySession.ended_at.is_not(None),
                StudySession.ended_at >= start,
                StudySession.ended_at < end,
                StudySession.deleted_at.is_(None),
            )
        )
        return int(value or 0)


class ActivityRepository:
    """Maintains ``user_activity_days``, the materialised streak ledger."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_activity(
        self,
        *,
        user_id: uuid.UUID,
        activity_date: date,
        timezone: str,
        activity_count_delta: int = 1,
        study_minutes_delta: int = 0,
        problems_solved_delta: int = 0,
        problems_attempted_delta: int = 0,
        revisions_completed_delta: int = 0,
        topics_completed_delta: int = 0,
    ) -> UserActivityDay:
        """Idempotently increment today's counters.

        An UPSERT with ``col = table.col + excluded.col`` is used rather than a
        read-modify-write, so two concurrent requests (a study session stopping while a
        problem is marked solved) cannot lose an increment.
        """
        stmt = (
            pg_insert(UserActivityDay)
            .values(
                user_id=user_id,
                activity_date=activity_date,
                timezone=timezone,
                activity_count=max(activity_count_delta, 0),
                study_minutes=max(study_minutes_delta, 0),
                problems_solved=max(problems_solved_delta, 0),
                problems_attempted=max(problems_attempted_delta, 0),
                revisions_completed=max(revisions_completed_delta, 0),
                topics_completed=max(topics_completed_delta, 0),
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "activity_date"],
                set_={
                    "activity_count": UserActivityDay.activity_count + activity_count_delta,
                    "study_minutes": UserActivityDay.study_minutes + study_minutes_delta,
                    "problems_solved": UserActivityDay.problems_solved + problems_solved_delta,
                    "problems_attempted": UserActivityDay.problems_attempted
                    + problems_attempted_delta,
                    "revisions_completed": UserActivityDay.revisions_completed
                    + revisions_completed_delta,
                    "topics_completed": UserActivityDay.topics_completed + topics_completed_delta,
                    "is_active": True,
                    "version": UserActivityDay.version + 1,
                    "updated_at": func.now(),
                },
            )
            .returning(UserActivityDay)
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def get_day(
        self, *, user_id: uuid.UUID, activity_date: date
    ) -> UserActivityDay | None:
        return await self.session.scalar(
            select(UserActivityDay).where(
                UserActivityDay.user_id == user_id,
                UserActivityDay.activity_date == activity_date,
            )
        )

    async def list_days(
        self,
        *,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
        active_only: bool = False,
    ) -> list[UserActivityDay]:
        stmt = select(UserActivityDay).where(UserActivityDay.user_id == user_id)
        if start:
            stmt = stmt.where(UserActivityDay.activity_date >= start)
        if end:
            stmt = stmt.where(UserActivityDay.activity_date <= end)
        if active_only:
            stmt = stmt.where(UserActivityDay.is_active.is_(True))
        stmt = stmt.order_by(UserActivityDay.activity_date.asc())
        return list((await self.session.scalars(stmt)).all())

    async def active_dates_desc(
        self, *, user_id: uuid.UUID, limit: int = 400
    ) -> list[date]:
        """Most recent active dates, newest first — the input to streak calculation."""
        stmt = (
            select(UserActivityDay.activity_date)
            .where(
                UserActivityDay.user_id == user_id,
                UserActivityDay.is_active.is_(True),
            )
            .order_by(UserActivityDay.activity_date.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def recompute_is_active(
        self, *, user_id: uuid.UUID, min_minutes: int, min_activities: int
    ) -> int:
        """Re-derive ``is_active`` for a user's days from the raw counters.

        Needed when the streak thresholds change in configuration: the materialised flags
        would otherwise keep reflecting the old rules.
        """
        result = await self.session.execute(
            update(UserActivityDay)
            .where(UserActivityDay.user_id == user_id)
            .values(
                is_active=and_(
                    UserActivityDay.study_minutes >= min_minutes,
                    UserActivityDay.activity_count >= min_activities,
                ),
                version=UserActivityDay.version + 1,
                updated_at=func.now(),
            )
        )
        return int(result.rowcount or 0)

    async def count_active_days(
        self, *, user_id: uuid.UUID, start: date, end: date
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    UserActivityDay.user_id == user_id,
                    UserActivityDay.is_active.is_(True),
                    UserActivityDay.activity_date >= start,
                    UserActivityDay.activity_date <= end,
                )
            )
            or 0
        )

    async def upsert_day_by_id(
        self, *, user_id: uuid.UUID, values: dict[str, Any]
    ) -> UserActivityDay:
        stmt = pg_insert(UserActivityDay).values(user_id=user_id, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "activity_date"],
            set_={
                key: stmt.excluded[key]
                for key in values
                if key not in {"user_id", "activity_date", "created_at"}
            }
            | {"version": UserActivityDay.version + 1, "updated_at": func.now()},
        ).returning(UserActivityDay)
        return (await self.session.execute(stmt)).scalars().one()
