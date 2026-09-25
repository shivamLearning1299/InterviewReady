"""Statistics and analytics service.

Assembles the dashboard payload from aggregated SQL. Nothing here loops over the user's
rows in Python: a user with 400 solved problems and a year of attempts must still get
``/stats/overview`` from a handful of indexed queries.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.activity import ActivityRepository
from app.repositories.stats import StatsRepository
from app.repositories.topics import HLDRepository, LLDRepository
from app.schemas.common import ActivityPoint, DifficultyBreakdown, StreakInfo, TopicBreakdown
from app.schemas.stats import (
    ActivityResponse,
    DifficultyStatsResponse,
    DSAStats,
    StatsOverviewResponse,
    StudyTimeStats,
    TopicStats,
    TopicStatsResponse,
)
from app.services.activity_service import ActivityService
from app.services.streak_service import StreakService
from app.utils.datetime_utils import day_bounds_utc, resolve_timezone, today_local, utcnow

logger = get_logger(__name__)

#: Range presets accepted by ``/stats/activity``.
RANGE_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}


class StatsService:
    def __init__(
        self,
        *,
        stats_repo: StatsRepository,
        activity_repo: ActivityRepository,
        activity_service: ActivityService,
        streak_service: StreakService,
        lld_repo: LLDRepository,
        hld_repo: HLDRepository,
        settings: Settings,
    ) -> None:
        self._stats = stats_repo
        self._activity_repo = activity_repo
        self._activity_service = activity_service
        self._streaks = streak_service
        self._lld = lld_repo
        self._hld = hld_repo
        self._settings = settings

    # ------------------------------------------------------------------- overview
    async def overview(
        self, *, user_id: uuid.UUID, timezone: str | None = None
    ) -> StatsOverviewResponse:
        """Everything the dashboard summary card needs, in one call."""
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        now = utcnow()
        today = today_local(tz)

        today_start, today_end = day_bounds_utc(today, tz)
        week_start = today - timedelta(days=today.weekday())
        week_start_dt, _ = day_bounds_utc(week_start, tz)
        month_start = today.replace(day=1)
        month_start_dt, _ = day_bounds_utc(month_start, tz)

        dsa_counts = await self._stats.dsa_progress_counts(user_id=user_id)
        lld_counts = await self._stats.topic_counts(user_id=user_id, kind="lld")
        hld_counts = await self._stats.topic_counts(user_id=user_id, kind="hld")
        revision_counts = await self._stats.revision_counts(
            user_id=user_id, now=now, day_start=today_start
        )
        study_minutes = await self._stats.study_minutes(
            user_id=user_id,
            today_start=today_start,
            today_end=today_end,
            week_start=week_start_dt,
            month_start=month_start_dt,
        )
        streak = await self._streaks.get_streak(user_id=user_id, timezone=str(tz))

        activity_totals = await self._stats.activity_totals(
            user_id=user_id, start=today - timedelta(days=29), end=today
        )

        return StatsOverviewResponse(
            dsa=DSAStats(
                total=dsa_counts["total"],
                solved=dsa_counts["solved"] + dsa_counts["mastered"],
                mastered=dsa_counts["mastered"],
                attempted=dsa_counts["attempted"],
                needs_revision=dsa_counts["needs_revision"],
                not_started=dsa_counts["not_started"],
            ),
            lld=TopicStats(
                completed=lld_counts["completed"],
                total=lld_counts["total"],
                mastered=lld_counts["mastered"],
                learning=lld_counts["learning"],
            ),
            hld=TopicStats(
                completed=hld_counts["completed"],
                total=hld_counts["total"],
                mastered=hld_counts["mastered"],
                learning=hld_counts["learning"],
            ),
            streak=streak,
            study_time=StudyTimeStats(
                today_minutes=study_minutes["today_minutes"],
                week_minutes=study_minutes["week_minutes"],
                month_minutes=study_minutes["month_minutes"],
                total_minutes=study_minutes["total_minutes"],
            ),
            revision_due=revision_counts["due"],
            revision_overdue=revision_counts["overdue"],
            problems_solved_today=activity_totals["problems_solved"],
            days_active_last_30=activity_totals["days_active_last_30"],
        )

    # -------------------------------------------------------------- DSA breakdowns
    async def topic_breakdown(
        self, *, user_id: uuid.UUID, limit: int | None = None
    ) -> TopicStatsResponse:
        rows = await self._stats.topic_breakdown(user_id=user_id, limit=limit)
        items = [
            TopicBreakdown(
                topic=row["topic"],
                total=row["total"],
                solved=row["solved"],
                mastered=row["mastered"],
                attempted=row["attempted"],
                needs_revision=row["needs_revision"],
                completion_percentage=row["completion_percentage"],
                average_confidence=row["average_confidence"],
            )
            for row in rows
        ]
        return TopicStatsResponse(items=items, total=len(items))

    async def difficulty_breakdown(self, *, user_id: uuid.UUID) -> DifficultyStatsResponse:
        rows = await self._stats.difficulty_breakdown(user_id=user_id)
        return DifficultyStatsResponse(
            items=[
                DifficultyBreakdown(
                    difficulty=row["difficulty"],
                    total=row["total"],
                    solved=row["solved"],
                    mastered=row["mastered"],
                    attempted=row["attempted"],
                    completion_percentage=row["completion_percentage"],
                )
                for row in rows
            ]
        )

    # --------------------------------------------------------------- activity series
    async def activity_series(
        self,
        *,
        user_id: uuid.UUID,
        range_key: str,
        timezone: str | None = None,
    ) -> ActivityResponse:
        """Dense time series for charts, with zero-filled gaps.

        Gaps are filled server-side so the client does not have to know how to pad a series
        — Swift Charts and Recharts both render a sparse series with misleading spacing.
        """
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        today = today_local(tz)
        days = RANGE_DAYS.get(range_key, 30)
        start = today - timedelta(days=days - 1)

        rows = await self._activity_repo.list_days(user_id=user_id, start=start, end=today)
        by_date = {row.activity_date: row for row in rows}

        items: list[ActivityPoint] = []
        cursor = start
        while cursor <= today:
            row = by_date.get(cursor)
            items.append(
                ActivityPoint(
                    date=cursor,
                    problems_attempted=row.problems_attempted if row else 0,
                    problems_solved=row.problems_solved if row else 0,
                    revisions_completed=row.revisions_completed if row else 0,
                    study_minutes=row.study_minutes if row else 0,
                    activity_count=row.activity_count if row else 0,
                )
            )
            cursor += timedelta(days=1)

        totals = {
            "problems_attempted": sum(item.problems_attempted for item in items),
            "problems_solved": sum(item.problems_solved for item in items),
            "revisions_completed": sum(item.revisions_completed for item in items),
            "study_minutes": sum(item.study_minutes for item in items),
            "activity_count": sum(item.activity_count for item in items),
            "active_days": sum(1 for item in items if item.activity_count > 0),
        }

        return ActivityResponse(
            range=range_key,  # type: ignore[arg-type]
            start=start,
            end=today,
            granularity="day",
            items=items,
            totals=totals,
        )

    # --------------------------------------------------------------------- streaks
    async def streak(
        self, *, user_id: uuid.UUID, timezone: str | None = None
    ) -> StreakInfo:
        return await self._streaks.get_streak(user_id=user_id, timezone=timezone)

    # ------------------------------------------------------------------ mastery
    async def topic_mastery(self, *, user_id: uuid.UUID) -> dict[str, dict[str, int]]:
        """Per-status counts for LLD and HLD, used by the curriculum progress bars."""
        return {
            "lld": await self._lld.counts_by_status(user_id=user_id),
            "hld": await self._hld.counts_by_status(user_id=user_id),
        }


def date_range_for(range_key: str, *, timezone: str | None = None, settings: Settings | None = None) -> tuple[date, date]:
    """Expose the resolved range so a route can echo it without duplicating the maths."""
    tz_name = timezone or (settings.default_timezone if settings else "UTC")
    tz = resolve_timezone(tz_name)
    end = today_local(tz)
    return end - timedelta(days=RANGE_DAYS.get(range_key, 30) - 1), end


__all__ = ["RANGE_DAYS", "StatsService", "date_range_for"]
