"""Activity ledger service.

Owns the translation from "the user did something meaningful" to an increment on
``user_activity_days``. Every domain service calls into here rather than touching the
ledger directly, so the counters and the streak threshold rules stay in one place.
"""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import UserActivityDay
from app.repositories.activity import ActivityRepository
from app.utils.datetime_utils import resolve_timezone, today_local

logger = get_logger(__name__)


class ActivityService:
    def __init__(
        self,
        *,
        activity_repo: ActivityRepository,
        settings: Settings,
    ) -> None:
        self._repo = activity_repo
        self._settings = settings

    async def record(
        self,
        *,
        user_id: uuid.UUID,
        timezone: ZoneInfo | str | None = None,
        activity_date: date | None = None,
        activity_count: int = 1,
        study_minutes: int = 0,
        problems_solved: int = 0,
        problems_attempted: int = 0,
        revisions_completed: int = 0,
        topics_completed: int = 0,
    ) -> UserActivityDay:
        """Increment the day's counters.

        ``is_active`` is derived from the configured thresholds rather than being
        unconditionally true, so a day with only a zero-length session does not silently
        count towards a streak.
        """
        tz = timezone if isinstance(timezone, ZoneInfo) else resolve_timezone(
            timezone or self._settings.default_timezone
        )
        day = activity_date or today_local(tz)

        row = await self._repo.record_activity(
            user_id=user_id,
            activity_date=day,
            timezone=str(tz),
            activity_count_delta=max(activity_count, 0),
            study_minutes_delta=max(study_minutes, 0),
            problems_solved_delta=max(problems_solved, 0),
            problems_attempted_delta=max(problems_attempted, 0),
            revisions_completed_delta=max(revisions_completed, 0),
            topics_completed_delta=max(topics_completed, 0),
        )

        # A day can cross the threshold after several small activities, so recompute the
        # flag from the accumulated totals instead of assuming this call made it active.
        meets_minutes = row.study_minutes >= self._settings.streak_min_minutes
        meets_activities = row.activity_count >= self._settings.streak_min_activities
        should_be_active = meets_minutes or meets_activities

        if row.is_active != should_be_active:
            row.is_active = should_be_active
            await self._repo.session.flush()

        return row

    async def get_day(
        self, *, user_id: uuid.UUID, activity_date: date
    ) -> UserActivityDay | None:
        return await self._repo.get_day(user_id=user_id, activity_date=activity_date)

    async def list_range(
        self,
        *,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
        active_only: bool = False,
    ) -> list[UserActivityDay]:
        return await self._repo.list_days(
            user_id=user_id, start=start, end=end, active_only=active_only
        )

    async def active_dates(self, *, user_id: uuid.UUID) -> set[date]:
        return set(await self._repo.active_dates_desc(user_id=user_id))

    async def sync_thresholds(self, *, user_id: uuid.UUID) -> int:
        """Re-derive ``is_active`` after a streak-threshold configuration change."""
        return await self._repo.recompute_is_active(
            user_id=user_id,
            min_minutes=self._settings.streak_min_minutes,
            min_activities=self._settings.streak_min_activities,
        )
