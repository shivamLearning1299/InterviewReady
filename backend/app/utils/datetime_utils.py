"""Timezone-aware date/time helpers.

All timestamps stored in PostgreSQL are ``timestamptz`` (UTC). A *study day* is a
calendar day in the user's own timezone, which is why every "today"/streak/plan decision
goes through :func:`local_day` rather than using ``date.today()`` directly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.logging import get_logger

logger = get_logger(__name__)

UTC_TZ = ZoneInfo("UTC")


def utcnow() -> datetime:
    """Current instant as a timezone-aware UTC datetime.

    Always use this instead of ``datetime.utcnow()``, which returns a naive datetime and
    silently corrupts comparisons against ``timestamptz`` columns.
    """
    return datetime.now(UTC)


def resolve_timezone(name: str | None, *, fallback: str = "UTC") -> ZoneInfo:
    """Resolve an IANA timezone name, falling back rather than raising."""
    for candidate in (name, fallback):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Unknown timezone, falling back", extra={"timezone": candidate})
    return UTC_TZ


def to_local(moment: datetime, timezone: ZoneInfo) -> datetime:
    """Convert an instant (or naive datetime treated as UTC) into ``timezone``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(timezone)


def local_day(moment: datetime | None, timezone: ZoneInfo, *, default: date | None = None) -> date:
    """The calendar date that ``moment`` falls on in ``timezone``."""
    if moment is None:
        return default if default is not None else utcnow().astimezone(timezone).date()
    return to_local(moment, timezone).date()


def today_local(timezone: ZoneInfo | str | None = None) -> date:
    """Today's date from the user's perspective."""
    tz = resolve_timezone(timezone if isinstance(timezone, str) else None)
    return utcnow().astimezone(tz).date()


def day_bounds_utc(day: date, timezone: ZoneInfo) -> tuple[datetime, datetime]:
    """Inclusive-start / exclusive-end UTC instants bracketing a local calendar day.

    Used to aggregate "today's study minutes" without doing timezone maths in SQL.
    """
    start_local = datetime.combine(day, time.min, tzinfo=timezone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def days_between(later: datetime, earlier: datetime) -> int:
    """Whole days from ``earlier`` to ``later`` (never negative)."""
    delta = later - earlier
    return max(0, delta.days)


def start_of_local_day(moment: datetime, timezone: ZoneInfo) -> datetime:
    """Midnight local time on the day ``moment`` falls on, as an aware datetime."""
    return datetime.combine(local_day(moment, timezone), time.min, tzinfo=timezone)


def ensure_aware(moment: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime, or pass through as-is."""
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def is_past(moment: datetime | None, *, now: datetime | None = None) -> bool:
    if moment is None:
        return False
    reference = now or utcnow()
    return (ensure_aware(moment) or reference) <= reference


def clamp_minutes(value: int | float | None, *, maximum: int = 24 * 60) -> int:
    """Clamp a duration into a sane range; used so a stuck timer cannot log 40 hours."""
    if value is None:
        return 0
    return max(0, min(round(value), maximum))
