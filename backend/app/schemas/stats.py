"""Statistics and streak schemas."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ActivityPoint, DifficultyBreakdown, StreakInfo, TopicBreakdown


class DSAStats(BaseModel):
    total: int = 0
    solved: int = 0
    mastered: int = 0
    attempted: int = 0
    needs_revision: int = 0
    not_started: int = 0


class TopicStats(BaseModel):
    completed: int = 0
    total: int = 0
    mastered: int = 0
    learning: int = 0


class StudyTimeStats(BaseModel):
    today_minutes: int = 0
    week_minutes: int = 0
    month_minutes: int = 0
    total_minutes: int = 0


class StatsOverviewResponse(BaseModel):
    """Single aggregate payload behind the analytics dashboard."""

    dsa: DSAStats = Field(default_factory=DSAStats)
    lld: TopicStats = Field(default_factory=TopicStats)
    hld: TopicStats = Field(default_factory=TopicStats)
    streak: StreakInfo = Field(default_factory=StreakInfo)
    study_time: StudyTimeStats = Field(default_factory=StudyTimeStats)
    revision_due: int = 0
    revision_overdue: int = 0
    problems_solved_today: int = 0
    days_active_last_30: int = 0


class TopicStatsResponse(BaseModel):
    items: list[TopicBreakdown] = Field(default_factory=list)
    total: int = 0


class DifficultyStatsResponse(BaseModel):
    items: list[DifficultyBreakdown] = Field(default_factory=list)


ActivityRange = Literal["7d", "30d", "90d", "1y"]


class ActivityResponse(BaseModel):
    """Time-series data ready to plot directly in Swift Charts / Recharts."""

    range: ActivityRange
    start: date
    end: date
    granularity: Literal["day", "week", "month"] = "day"
    items: list[ActivityPoint] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


class StreakResponse(StreakInfo):
    min_minutes_required: int = 1
    timezone: str = "UTC"
