"""Progress analytics and streaks."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.dependencies import ClientTimezone, CurrentUser, ServicesDep
from app.schemas.stats import (
    ActivityRange,
    ActivityResponse,
    DifficultyStatsResponse,
    StatsOverviewResponse,
    StreakResponse,
    TopicStatsResponse,
)

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/overview",
    response_model=StatsOverviewResponse,
    summary="Dashboard overview",
    description=(
        "One call for the whole summary card: DSA status counts, LLD/HLD completion, the "
        "current streak, study minutes for today/week/month and the revision backlog.\n\n"
        "Every figure is aggregated in SQL — a user with 400 solved problems and a year of "
        "attempts gets the same handful of indexed queries as a new user."
    ),
)
async def overview(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
) -> StatsOverviewResponse:
    return await services.stats.overview(
        user_id=current_user.id, timezone=client_timezone
    )


@router.get(
    "/dsa/topics",
    response_model=TopicStatsResponse,
    summary="Progress by topic",
    description=(
        "Per-topic totals, solved/mastered counts, completion percentage and average "
        "confidence. Topics the user has not touched are included with zeroes so a chart "
        "has no gaps."
    ),
)
async def topic_stats(
    current_user: CurrentUser,
    services: ServicesDep,
    limit: int | None = Query(default=None, ge=1, le=200),
) -> TopicStatsResponse:
    return await services.stats.topic_breakdown(user_id=current_user.id, limit=limit)


@router.get(
    "/dsa/difficulty",
    response_model=DifficultyStatsResponse,
    summary="Progress by difficulty",
    description="Easy / medium / hard completion breakdown, ordered easiest first.",
)
async def difficulty_stats(
    current_user: CurrentUser, services: ServicesDep
) -> DifficultyStatsResponse:
    return await services.stats.difficulty_breakdown(user_id=current_user.id)


@router.get(
    "/activity",
    response_model=ActivityResponse,
    summary="Activity time series",
    description=(
        "Dense, chart-ready daily series (gaps zero-filled server-side) of problems "
        "attempted/solved, revisions completed and study minutes, plus period totals."
    ),
)
async def activity_stats(
    current_user: CurrentUser,
    services: ServicesDep,
    range_key: ActivityRange = Query(
        default="30d", alias="range", description="7d | 30d | 90d | 1y"
    ),
    client_timezone: ClientTimezone = None,
) -> ActivityResponse:
    return await services.stats.activity_series(
        user_id=current_user.id, range_key=range_key, timezone=client_timezone
    )


@router.get(
    "/streak",
    response_model=StreakResponse,
    summary="Current streak",
    description=(
        "The streak as computed by the server, which is the single source of truth for both "
        "clients. A streak stays alive until a whole day is missed, so it does not appear "
        "broken before the user has studied that day."
    ),
)
async def streak_stats(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
) -> StreakResponse:
    streak = await services.stats.streak(
        user_id=current_user.id, timezone=client_timezone
    )
    thresholds = services.streaks.thresholds()
    return StreakResponse(
        current=streak.current,
        longest=streak.longest,
        last_active_date=streak.last_active_date,
        today_active=streak.today_active,
        min_minutes_required=thresholds["min_minutes"],
        timezone=client_timezone or services.settings.default_timezone,
    )


@router.get(
    "/mastery",
    summary="LLD/HLD mastery counts",
    description="Per-status topic counts for both design curricula, for progress bars.",
)
async def mastery_stats(current_user: CurrentUser, services: ServicesDep) -> dict:
    return await services.stats.topic_mastery(user_id=current_user.id)


__all__ = ["router"]
