"""Spaced-repetition policy.

This module is the single definition of "when should this be reviewed next". It is used
by the revision service, the daily planner and the sync path, and it is deliberately free
of database access so it can be unit-tested directly.

The ladder is **configuration, not code**: ``REVISION_INTERVALS_JSON`` maps a confidence
score (0-5) to a list of day-intervals, indexed by how many revisions have already been
completed for that item. Changing the study algorithm therefore means changing
configuration, and both React and iOS get the new behaviour without a client release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.config import Settings
from app.core.constants import RevisionReason
from app.utils.datetime_utils import utcnow


@dataclass(frozen=True, slots=True)
class RevisionSchedule:
    """The decision produced by the policy for one item."""

    due_at: datetime
    interval_days: int
    reason: str
    priority: int


class RevisionPolicy:
    """Configurable, deterministic interval selection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # --------------------------------------------------------------------- intervals
    def interval_days(self, *, confidence: int | None, revision_count: int) -> int:
        """Days until the next review.

        ``revision_count`` indexes into the confidence's ladder and is clamped to the last
        entry, so an item reviewed many times keeps the maximum interval rather than
        running off the end of the list.
        """
        ladder = self._settings.intervals_for_confidence(confidence)
        index = max(0, min(revision_count, len(ladder) - 1))
        return ladder[index]

    def next_due_at(
        self,
        *,
        confidence: int | None,
        revision_count: int,
        from_time: datetime | None = None,
    ) -> tuple[datetime, int]:
        """Absolute due time plus the interval used, for a successful review."""
        base = from_time or utcnow()
        days = self.interval_days(confidence=confidence, revision_count=revision_count)
        return base + timedelta(days=days), days

    def failure_retry_at(self, *, from_time: datetime | None = None) -> tuple[datetime, int]:
        """A failed review comes back tomorrow — the shortest interval in the ladder."""
        base = from_time or utcnow()
        # Deliberately hardcoded to 1 day: failing a review should always bring the item
        # back immediately, regardless of how the configurable ladder is tuned.
        return base + timedelta(days=1), 1

    # --------------------------------------------------------------------- priority
    def priority_for(self, *, confidence: int | None, reason: str | None = None) -> int:
        """Higher means "show this first". 1 (low) .. 5 (urgent)."""
        score = 0 if confidence is None else max(0, min(confidence, 5))

        if reason == RevisionReason.FAILED_ATTEMPT.value:
            return 5
        if reason == RevisionReason.LOW_CONFIDENCE.value:
            return 5
        if reason == RevisionReason.MANUAL.value:
            return 4
        if reason == RevisionReason.LONG_TIME_SINCE_REVIEW.value:
            return 4

        # Scheduled revisions inherit priority from how shaky the user felt.
        return {0: 5, 1: 4, 2: 4, 3: 3, 4: 2, 5: 1}.get(score, 3)

    # ----------------------------------------------------------------------- reasons
    def reason_after_review(
        self, *, result: str, confidence: int | None
    ) -> str:
        """Why the next revision exists, given how the current one went."""
        if result == "failed":
            return RevisionReason.FAILED_ATTEMPT.value
        if confidence is not None and confidence <= self._settings.revision_low_confidence_threshold:
            return RevisionReason.LOW_CONFIDENCE.value
        return RevisionReason.SCHEDULED_REVISION.value

    # -------------------------------------------------------------------- decisions
    def schedule_after_review(
        self,
        *,
        result: str,
        confidence: int | None,
        revision_count_before: int,
        from_time: datetime | None = None,
    ) -> RevisionSchedule:
        """Plan the next review for an item just reviewed.

        A failed review schedules tomorrow with maximum priority; success follows the
        configured ladder. ``revision_count_before`` is the count *prior* to this review,
        so the first successful review lands on the first rung of the ladder.
        """
        if result == "failed":
            due_at, interval = self.failure_retry_at(from_time=from_time)
            return RevisionSchedule(
                due_at=due_at,
                interval_days=interval,
                reason=RevisionReason.FAILED_ATTEMPT.value,
                priority=5,
            )

        # A "partial" result should not advance the ladder as far as a clean success.
        effective_count = revision_count_before if result == "partial" else revision_count_before + 1
        due_at, interval = self.next_due_at(
            confidence=confidence,
            revision_count=effective_count,
            from_time=from_time,
        )
        reason = self.reason_after_review(result=result, confidence=confidence)
        return RevisionSchedule(
            due_at=due_at,
            interval_days=interval,
            reason=reason,
            priority=self.priority_for(confidence=confidence, reason=reason),
        )

    def schedule_after_solve(
        self,
        *,
        confidence: int | None,
        from_time: datetime | None = None,
    ) -> RevisionSchedule:
        """First revision for a newly solved problem."""
        reason = (
            RevisionReason.LOW_CONFIDENCE.value
            if confidence is not None
            and confidence <= self._settings.revision_low_confidence_threshold
            else RevisionReason.SCHEDULED_REVISION.value
        )
        return RevisionSchedule(
            due_at=self.next_due_at(confidence=confidence, revision_count=0, from_time=from_time)[0],
            interval_days=self.interval_days(confidence=confidence, revision_count=0),
            reason=reason,
            priority=self.priority_for(confidence=confidence, reason=reason),
        )

    # -------------------------------------------------------------------- staleness
    def is_stale(
        self,
        *,
        last_reviewed_at: datetime | None,
        reference: datetime | None = None,
    ) -> bool:
        """Whether an item has gone untouched long enough to deserve review.

        Used by the planner to pull problems back into circulation when the user has no
        scheduled revisions left, so revision never goes idle.
        """
        if last_reviewed_at is None:
            return False
        now = reference or utcnow()
        elapsed = now - last_reviewed_at
        return elapsed >= timedelta(days=self._settings.revision_ladder_max_interval)

    def describe_ladder(self) -> dict[str, list[int]]:
        """Expose the configured ladder so a client can show "next review in N days"."""
        return {
            confidence: list(intervals)
            for confidence, intervals in self._settings.revision_intervals.items()
        }
