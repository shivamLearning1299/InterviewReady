"""Aggregated analytics queries.

Every method here computes its result in SQL. The stats endpoints are called on app
launch, so they must not iterate the user's history in Python — an approach that works
fine with 50 problems and collapses at 400 solved problems across a year of attempts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DSAProblem,
    HLDProgress,
    HLDTopic,
    LLDProgress,
    LLDTopic,
    ProblemAttempt,
    RevisionQueueItem,
    StudySession,
    UserActivityDay,
    UserProblemProgress,
)


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------- DSA counts
    async def dsa_progress_counts(self, *, user_id: uuid.UUID) -> dict[str, int]:
        """Problem counts per status plus the totals needed for the overview card."""
        status_stmt = (
            select(UserProblemProgress.status, func.count())
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .group_by(UserProblemProgress.status)
        )
        counts = {
            status: int(count) for status, count in (await self.session.execute(status_stmt)).all()
        }

        counted = sum(counts.values())
        total_problems = int(
            await self.session.scalar(
                select(func.count()).select_from(DSAProblem).where(DSAProblem.is_active.is_(True))
            )
            or 0
        )

        return {
            "total": total_problems,
            "solved": counts.get("solved", 0),
            "mastered": counts.get("mastered", 0),
            "attempted": counts.get("attempted", 0),
            "needs_revision": counts.get("needs_revision", 0),
            "not_started": max(total_problems - counted, 0),
        }

    async def topic_breakdown(self, *, user_id: uuid.UUID, limit: int | None = None) -> list[dict[str, Any]]:
        """Per-topic totals, solved counts and average confidence, in one grouped query."""
        totals_stmt = (
            select(DSAProblem.primary_topic, func.count())
            .where(DSAProblem.is_active.is_(True))
            .group_by(DSAProblem.primary_topic)
        )
        totals = {
            topic: int(count) for topic, count in (await self.session.execute(totals_stmt)).all()
        }

        progress_stmt = (
            select(
                DSAProblem.primary_topic,
                func.count().filter(UserProblemProgress.status == "solved"),
                func.count().filter(UserProblemProgress.status == "mastered"),
                func.count().filter(UserProblemProgress.status == "attempted"),
                func.count().filter(UserProblemProgress.status == "needs_revision"),
                func.avg(UserProblemProgress.confidence),
            )
            .join(DSAProblem, DSAProblem.id == UserProblemProgress.problem_id)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .group_by(DSAProblem.primary_topic)
        )

        rows = (await self.session.execute(progress_stmt)).all()
        results: list[dict[str, Any]] = []

        for topic, solved, mastered, attempted, needs_revision, avg_confidence in rows:
            total = totals.get(topic, 0)
            # "solved" in the DSA status sense includes mastered problems that were later
            # promoted, so completed = solved + mastered for progress purposes.
            completed = int(solved or 0) + int(mastered or 0)
            results.append(
                {
                    "topic": topic,
                    "total": total,
                    "solved": completed,
                    "mastered": int(mastered or 0),
                    "attempted": int(attempted or 0),
                    "needs_revision": int(needs_revision or 0),
                    "completion_percentage": round(
                        (completed / total * 100) if total else 0.0, 2
                    ),
                    "average_confidence": (
                        round(float(avg_confidence), 2) if avg_confidence is not None else None
                    ),
                }
            )

        # Include topics the user has never touched, so the chart has no gaps.
        known = {row["topic"] for row in results}
        for topic, total in totals.items():
            if topic not in known:
                results.append(
                    {
                        "topic": topic,
                        "total": total,
                        "solved": 0,
                        "mastered": 0,
                        "attempted": 0,
                        "needs_revision": 0,
                        "completion_percentage": 0.0,
                        "average_confidence": None,
                    }
                )

        results.sort(key=lambda row: (-row["completion_percentage"], row["topic"]))
        return results[:limit] if limit else results

    async def difficulty_breakdown(self, *, user_id: uuid.UUID) -> list[dict[str, Any]]:
        totals_stmt = (
            select(DSAProblem.difficulty, func.count())
            .where(DSAProblem.is_active.is_(True))
            .group_by(DSAProblem.difficulty)
        )
        totals = {
            difficulty: int(count)
            for difficulty, count in (await self.session.execute(totals_stmt)).all()
        }

        progress_stmt = (
            select(
                DSAProblem.difficulty,
                func.count().filter(UserProblemProgress.status == "solved"),
                func.count().filter(UserProblemProgress.status == "mastered"),
                func.count().filter(UserProblemProgress.status == "attempted"),
            )
            .join(DSAProblem, DSAProblem.id == UserProblemProgress.problem_id)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .group_by(DSAProblem.difficulty)
        )

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for difficulty, solved, mastered, attempted in (await self.session.execute(progress_stmt)).all():
            total = totals.get(difficulty, 0)
            completed = int(solved or 0) + int(mastered or 0)
            seen.add(difficulty)
            results.append(
                {
                    "difficulty": difficulty,
                    "total": total,
                    "solved": completed,
                    "mastered": int(mastered or 0),
                    "attempted": int(attempted or 0),
                    "completion_percentage": round((completed / total * 100) if total else 0.0, 2),
                }
            )

        for difficulty, total in totals.items():
            if difficulty not in seen:
                results.append(
                    {
                        "difficulty": difficulty,
                        "total": total,
                        "solved": 0,
                        "mastered": 0,
                        "attempted": 0,
                        "completion_percentage": 0.0,
                    }
                )

        order = {"easy": 0, "medium": 1, "hard": 2}
        results.sort(key=lambda row: order.get(row["difficulty"], 99))
        return results

    # ------------------------------------------------------------------ LLD / HLD
    async def topic_counts(
        self, *, user_id: uuid.UUID, kind: str
    ) -> dict[str, int]:
        """Progress counts for the LLD or HLD curriculum."""
        if kind == "lld":
            total = int(
                await self.session.scalar(
                    select(func.count()).select_from(LLDTopic).where(LLDTopic.is_active.is_(True))
                )
                or 0
            )
            stmt: Select[Any] = (
                select(LLDProgress.status, func.count())
                .where(LLDProgress.user_id == user_id, LLDProgress.deleted_at.is_(None))
                .group_by(LLDProgress.status)
            )
        else:
            total = int(
                await self.session.scalar(
                    select(func.count()).select_from(HLDTopic).where(HLDTopic.is_active.is_(True))
                )
                or 0
            )
            stmt = (
                select(HLDProgress.status, func.count())
                .where(HLDProgress.user_id == user_id, HLDProgress.deleted_at.is_(None))
                .group_by(HLDProgress.status)
            )

        counts = {status: int(count) for status, count in (await self.session.execute(stmt)).all()}
        return {
            "total": total,
            "completed": counts.get("completed", 0) + counts.get("mastered", 0),
            "mastered": counts.get("mastered", 0),
            "learning": counts.get("learning", 0),
            "needs_revision": counts.get("needs_revision", 0),
            "not_started": max(total - sum(counts.values()), 0),
        }

    # --------------------------------------------------------------------- revisions
    async def revision_counts(
        self, *, user_id: uuid.UUID, now: datetime, day_start: datetime
    ) -> dict[str, int]:
        stmt = select(
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    RevisionQueueItem.due_at <= now,
                )
            ),
            func.count().filter(
                and_(
                    RevisionQueueItem.completed.is_(False),
                    RevisionQueueItem.due_at < day_start,
                )
            ),
            func.count().filter(RevisionQueueItem.completed.is_(True)),
        ).where(
            RevisionQueueItem.user_id == user_id,
            RevisionQueueItem.deleted_at.is_(None),
        )
        row = (await self.session.execute(stmt)).one()
        return {
            "due": int(row[0] or 0),
            "overdue": int(row[1] or 0),
            "completed": int(row[2] or 0),
        }

    # ------------------------------------------------------------------ study time
    async def study_minutes(
        self,
        *,
        user_id: uuid.UUID,
        today_start: datetime,
        today_end: datetime,
        week_start: datetime,
        month_start: datetime,
    ) -> dict[str, int]:
        """Today/week/month/total study minutes from completed sessions."""
        stmt = select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                StudySession.started_at >= today_start,
                                StudySession.started_at < today_end,
                            ),
                            StudySession.duration_minutes,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (StudySession.started_at >= week_start, StudySession.duration_minutes),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (StudySession.started_at >= month_start, StudySession.duration_minutes),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(StudySession.duration_minutes), 0),
        ).where(
            StudySession.user_id == user_id,
            StudySession.deleted_at.is_(None),
            StudySession.duration_minutes.is_not(None),
        )
        row = (await self.session.execute(stmt)).one()
        return {
            "today_minutes": int(row[0] or 0),
            "week_minutes": int(row[1] or 0),
            "month_minutes": int(row[2] or 0),
            "total_minutes": int(row[3] or 0),
        }

    # -------------------------------------------------------------------- activity
    async def activity_totals(
        self, *, user_id: uuid.UUID, start: date, end: date
    ) -> dict[str, int]:
        stmt = select(
            func.coalesce(func.sum(UserActivityDay.study_minutes), 0),
            func.coalesce(func.sum(UserActivityDay.problems_solved), 0),
            func.coalesce(func.sum(UserActivityDay.problems_attempted), 0),
            func.coalesce(func.sum(UserActivityDay.revisions_completed), 0),
            func.count(),
        ).where(
            UserActivityDay.user_id == user_id,
            UserActivityDay.activity_date >= start,
            UserActivityDay.activity_date <= end,
        )
        row = (await self.session.execute(stmt)).one()
        return {
            "study_minutes": int(row[0] or 0),
            "problems_solved": int(row[1] or 0),
            "problems_attempted": int(row[2] or 0),
            "revisions_completed": int(row[3] or 0),
            "days_active_last_30": int(row[4] or 0),
        }

    async def problems_solved_today(self, *, user_id: uuid.UUID, today: date) -> int:
        value = await self.session.scalar(
            select(UserActivityDay.problems_solved).where(
                UserActivityDay.user_id == user_id,
                UserActivityDay.activity_date == today,
            )
        )
        return int(value or 0)

    async def attempt_totals_since(
        self, *, user_id: uuid.UUID, since: datetime | None = None
    ) -> dict[str, int]:
        stmt = select(ProblemAttempt.outcome, func.count()).where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.deleted_at.is_(None),
        )
        if since:
            stmt = stmt.where(ProblemAttempt.started_at >= since)
        stmt = stmt.group_by(ProblemAttempt.outcome)
        return {
            (outcome or "unknown"): int(count)
            for outcome, count in (await self.session.execute(stmt)).all()
        }

    async def problems_needing_revision(self, *, user_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    UserProblemProgress.user_id == user_id,
                    UserProblemProgress.status == "needs_revision",
                    UserProblemProgress.deleted_at.is_(None),
                )
            )
            or 0
        )
