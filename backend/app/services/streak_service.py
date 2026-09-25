"""Streak calculation.

Streaks are **server-authoritative**: neither React nor iOS computes one, so both clients
always show the same number. The input is the materialised ``user_activity_days`` ledger
rather than raw attempts/revisions/sessions, so this stays a single indexed read no matter
how much history the user accumulates.

The definition of an "active day" is configuration, not code:

* ``STREAK_MIN_MINUTES`` — study minutes required (default 1);
* ``STREAK_MIN_ACTIVITIES`` — meaningful activities required (default 1).

Changing either re-derives the stored flags via
``ActivityRepository.recompute_is_active``.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import UserActivityDay
from app.repositories.activity import ActivityRepository
from app.schemas.common import StreakInfo
from app.services.activity_service import ActivityService
from app.utils.datetime_utils import resolve_timezone, today_local, utcnow

logger = get_logger(__name__)


class StreakService:
    def __init__(
        self,
        *,
        activity_repo: ActivityRepository,
        activity_service: ActivityService,
        settings: Settings,
    ) -> None:
        self._repo = activity_repo
        self._activity_service = activity_service
        self._settings = settings

    async def get_streak(
        self,
        *,
        user_id,
        timezone: str | None = None,
    ) -> StreakInfo:
        """Current streak, longest streak and whether today already counts.

        ``current`` counts back from today. A streak is still "alive" if the user has not
        studied yet today but did yesterday — otherwise opening the app in the morning would
        show the streak as broken and demotivate the user before they have had a chance to
        study.
        """
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        today = today_local(tz)

        active_dates = set(await self._repo.active_dates_desc(user_id=user_id))
        if not active_dates:
            return StreakInfo(current=0, longest=0, last_active_date=None, today_active=False)

        today_active = today in active_dates
        last_active = max(active_dates)

        # Walk backwards from today (or yesterday when today is still untouched).
        cursor = today if today_active else today - timedelta(days=1)
        current = 0
        while cursor in active_dates:
            current += 1
            cursor -= timedelta(days=1)

        # A gap of more than one day means the streak is genuinely broken.
        if not today_active and last_active < today - timedelta(days=1):
            current = 0

        return StreakInfo(
            current=current,
            longest=self._longest_run(active_dates),
            last_active_date=last_active,
            today_active=today_active,
        )

    @staticmethod
    def _longest_run(active_dates: set[date]) -> int:
        """Longest consecutive run of active days in the whole history.

        A single backward walk with a running count: O(n log n) for the sort, O(n) for the
        scan. Cheap enough to run on every ``/stats/overview`` request.
        """
        if not active_dates:
            return 0

        ordered = sorted(active_dates)
        longest = 1
        run = 1
        for previous, current in pairwise(ordered):
            if current - previous == timedelta(days=1):
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        return longest

    async def record_study_day(
        self,
        *,
        user_id,
        timezone: str | None = None,
        study_minutes: int = 0,
        activity_count: int = 1,
    ) -> UserActivityDay:
        """Mark today as active in the user's local timezone."""
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        return await self._activity_service.record(
            user_id=user_id,
            timezone=tz,
            activity_count=activity_count,
            study_minutes=study_minutes,
        )

    async def streak_leaderboard_facts(self, *, user_id, timezone: str | None = None) -> dict:
        """Compact streak facts for embedding in ``/today`` and ``/stats/overview``."""
        streak = await self.get_streak(user_id=user_id, timezone=timezone)
        return {
            "current": streak.current,
            "longest": streak.longest,
            "today_active": streak.today_active,
            "last_active_date": streak.last_active_date,
            "computed_at": utcnow(),
        }

    def thresholds(self) -> dict[str, int]:
        """Expose the configured thresholds so a client can explain a broken streak."""
        return {
            "min_minutes": self._settings.streak_min_minutes,
            "min_activities": self._settings.streak_min_activities,
        }
