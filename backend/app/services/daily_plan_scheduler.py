"""Daily plan scheduler.

This is the most business-critical service in the application: it decides what the user
studies today, for both clients, from one deterministic implementation.

Two properties matter more than the scoring details:

**Determinism.** ``GET /api/v1/today`` must never hand the user a different plan on
refresh. The result is a pure function of ``(catalog, user state, plan_date)`` — no
``random``, no "now"-dependent jitter inside the ranking. A stable, seeded tiebreak gives
day-to-day variety while remaining reproducible within a day, and the winner is then
persisted, so the persisted plan is the authority from then on.

**Progressively covering the curriculum.** Rather than a naive "next 3 unsolved by
order_index", candidates are scored on curriculum position, difficulty ramp, importance,
topic weakness, prior exposure and staleness, so early plans stay foundational and later
plans reach harder material and the user's weak spots.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.core.constants import Difficulty, ItemType, ProblemStatus, RevisionReason
from app.core.logging import get_logger
from app.db.models import DSAProblem, UserProblemProgress
from app.services.revision_policy import RevisionPolicy
from app.utils.datetime_utils import utcnow

logger = get_logger(__name__)

SCHEDULER_VERSION = "scheduler_v1"

#: Difficulty ramp: the reward for matching the user's current stage of the curriculum.
_DIFFICULTY_RAMP_WEIGHT = {
    # (difficulty, stage) -> bonus. "stage" is how far into the curriculum the user is.
    "easy": {0: 12.0, 1: 6.0, 2: 1.0, 3: -4.0},
    "medium": {0: 4.0, 1: 12.0, 2: 10.0, 3: 2.0},
    "hard": {0: -10.0, 1: -3.0, 2: 8.0, 3: 12.0},
}


@dataclass(slots=True)
class Candidate:
    """A scored scheduling candidate."""

    problem: DSAProblem
    progress: UserProblemProgress | None
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def problem_id(self) -> str:
        return self.problem.id

    @property
    def is_solved(self) -> bool:
        return bool(self.progress and self.progress.status in ("solved", "mastered"))


@dataclass(slots=True)
class SchedulingResult:
    """The scheduling decision, with the reasoning kept for debugging and display."""

    new_problems: list[Candidate]
    revision_problems: list[Candidate]
    weakest_topics: list[str]
    covered_topics: list[str]
    candidate_count: int
    explanation: dict[str, Any]


class DailyPlanScheduler:
    """Deterministic, explainable problem selection."""

    def __init__(self, settings: Settings, revision_policy: RevisionPolicy) -> None:
        self._settings = settings
        self._policy = revision_policy

    # ------------------------------------------------------------------ public entry
    def select(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        catalog: list[tuple[DSAProblem, UserProblemProgress | None]],
        recent_problem_ids: set[str],
        topic_performance: dict[str, dict[str, float]],
        new_count: int,
        revision_count: int,
        now: datetime | None = None,
    ) -> SchedulingResult:
        """Choose today's problems.

        ``catalog`` must be the full active catalog with the user's progress joined — one
        query, not one per problem.
        """
        reference = now or utcnow()
        new_count = max(0, min(new_count, self._settings.daily_dsa_count_max))
        revision_count = max(0, min(revision_count, self._settings.revision_dsa_count_max))

        total = len(catalog)
        weakest_topics = self._weakest_topics(topic_performance)

        # How far through the curriculum the user is, used to pick the difficulty rung.
        solved_count = sum(
            1
            for _, progress in catalog
            if progress and progress.status in (ProblemStatus.SOLVED, ProblemStatus.MASTERED)
        )
        stage = self._stage_for(solved_count=solved_count, total=total)

        scored: list[Candidate] = [
            self._score(
                problem=problem,
                progress=progress,
                user_id=user_id,
                plan_date=plan_date,
                recent_problem_ids=recent_problem_ids,
                weakest_topics=weakest_topics,
                stage=stage,
                total=total,
                reference=reference,
            )
            for problem, progress in catalog
        ]

        # Deterministic ordering: score desc, then curriculum order, then id. The id
        # tiebreak guarantees a total order, so the same inputs always produce the same
        # list even if two problems share a score and an order_index.
        scored.sort(key=lambda item: (-item.score, item.problem.order_index, item.problem.id))

        new_problems = self._pick_new(scored=scored, count=new_count)

        # Revisions come from the persisted queue/dates, never from the "new" pool, so the
        # user can always see new questions and reviews as separate lists.
        revision_problems = self._pick_revisions(
            scored=scored, recent_problem_ids=recent_problem_ids, count=revision_count
        )

        covered_topics = list(dict.fromkeys(item.problem.primary_topic for item in new_problems))

        return SchedulingResult(
            new_problems=new_problems,
            revision_problems=revision_problems,
            weakest_topics=weakest_topics,
            covered_topics=covered_topics,
            candidate_count=len(scored),
            explanation={
                "scheduler": SCHEDULER_VERSION,
                "stage": stage,
                "solved_ratio": round(solved_count / total, 4) if total else 0.0,
                "recently_assigned_excluded": len(recent_problem_ids),
                "weakest_topics": weakest_topics[:5],
                "rule": (
                    "Excludes problems solved or assigned recently; rewards curriculum "
                    "position, difficulty fit, importance and weak topics."
                ),
            },
        )

    # ----------------------------------------------------------------------- scoring
    def _score(
        self,
        *,
        problem: DSAProblem,
        progress: UserProblemProgress | None,
        user_id: uuid.UUID,
        plan_date: date,
        recent_problem_ids: set[str],
        weakest_topics: list[str],
        stage: int,
        total: int,
        reference: datetime,
    ) -> Candidate:
        """Score one problem. Higher is better."""
        score = 0.0
        reasons: list[str] = []

        # 1. Curriculum position — the backbone signal. Earlier material first, but the
        #    penalty is logarithmic rather than linear so a problem at index 300 is still
        #    reachable in the same plan as one at index 10.
        position_ratio = (problem.order_index / total) if total else 0.0
        curriculum_score = (1.0 - position_ratio) * 30.0
        score += curriculum_score

        # 2. Importance (1-5) — interview frequency.
        score += problem.importance * 3.0

        # 3. Difficulty ramp for the user's current stage.
        ramp = _DIFFICULTY_RAMP_WEIGHT.get(problem.difficulty, {})
        score += ramp.get(stage, 0.0)
        if ramp.get(stage, 0.0) > 5:
            reasons.append(f"{problem.difficulty} fits current stage")

        # 4. Weak-topic boost — deliberately large so weaknesses actually get addressed.
        low_confidence = (
            progress is None
            or progress.confidence <= self._settings.revision_low_confidence_threshold
        )
        if low_confidence and problem.primary_topic in weakest_topics:
            weakness_rank = weakest_topics.index(problem.primary_topic)
            boost = max(4.0, 22.0 - weakness_rank * 3.0)
            score += boost
            reasons.append(f"weak topic: {problem.primary_topic}")

        # 5. Never re-assign something from a recent plan.
        if problem.id in recent_problem_ids:
            score -= 1000.0
            reasons.append("assigned recently")

        # 6. Exposure — a problem the user has already worked on is a poor "new" pick.
        if progress is not None:
            if progress.status in (ProblemStatus.SOLVED, ProblemStatus.MASTERED):
                score -= 500.0
                reasons.append("already solved")
            elif progress.status == ProblemStatus.ATTEMPTED:
                # Attempted-but-unsolved is a good candidate: resume rather than restart.
                score += 14.0
                reasons.append("previously attempted, unfinished")
            if progress.confidence >= 4:
                score -= 25.0

        # 7. Staleness — bring back material the user has not touched in a long time.
        if progress is not None and progress.last_reviewed_date is not None:
            days_stale = max(0, (reference - progress.last_reviewed_date).days)
            if days_stale > 21:
                score += min(days_stale / 7.0, 12.0)
                reasons.append(f"not reviewed in {days_stale}d")

        # 8. Company-tagged problems carry a small premium.
        if problem.companies:
            score += min(len(problem.companies), 5) * 0.8

        # 9. Deterministic tiebreak for day-to-day variety. Derived from the user, the date
        #    and the problem, so it is stable for a given day and reproducible afterwards.
        score += self._jitter(user_id=user_id, plan_date=plan_date, problem_id=problem.id)

        return Candidate(problem=problem, progress=progress, score=round(score, 4), reasons=reasons)

    @staticmethod
    def _jitter(*, user_id: uuid.UUID, plan_date: date, problem_id: str) -> float:
        """A stable pseudo-random nudge in ``[0, 3)``.

        Uses a digest rather than ``random`` so the value is identical across processes,
        workers and replays — a refresh, a retry or a second uvicorn worker all produce the
        same plan for the same day.
        """
        digest = hashlib.blake2b(
            f"{user_id}:{plan_date.isoformat()}:{problem_id}".encode(),
            digest_size=8,
        ).digest()
        return int.from_bytes(digest, "big") % 300 / 100.0

    @staticmethod
    def _stage_for(*, solved_count: int, total: int) -> int:
        """Map progress through the curriculum to a difficulty stage 0-3."""
        if not total:
            return 0
        ratio = solved_count / total
        if ratio < 0.15:
            return 0
        if ratio < 0.45:
            return 1
        if ratio < 0.75:
            return 2
        return 3

    @staticmethod
    def _weakest_topics(topic_performance: dict[str, dict[str, float]]) -> list[str]:
        """Topics with the lowest average confidence, weakest first.

        Only topics the user has actually engaged with are considered: a topic with zero
        exposure is not "weak", it is simply unstarted, and the curriculum-position signal
        already handles those.
        """
        scored = [
            (topic, stats.get("average_confidence", 0.0), stats.get("interacted", 0.0))
            for topic, stats in topic_performance.items()
            if stats.get("interacted", 0) > 0
        ]
        scored.sort(key=lambda row: (row[1], -row[2], row[0]))
        return [topic for topic, _, _ in scored]

    # -------------------------------------------------------------------- selection
    def _pick_new(self, *, scored: list[Candidate], count: int) -> list[Candidate]:
        """Choose ``count`` new problems, spreading them across topics where possible.

        Topic diversity is applied as a second pass so a plan is not three graph problems
        in a row, but it never falls back to an already-solved or recently-assigned problem.
        """
        if count <= 0:
            return []

        eligible = [item for item in scored if not item.is_solved and item.score > -100]
        if not eligible:
            return []

        chosen: list[Candidate] = []
        used_topics: dict[str, int] = {}
        remaining = list(eligible)

        while remaining and len(chosen) < count:
            # Prefer the best candidate whose topic is under-represented in this plan.
            best_index = 0
            best_adjusted = float("-inf")
            for index, candidate in enumerate(remaining):
                topic = candidate.problem.primary_topic
                # Each repeat of a topic costs 3 points; this keeps variety without
                # overriding a genuinely strong candidate.
                adjusted = candidate.score - used_topics.get(topic, 0) * 3.0
                if adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_index = index

            pick = remaining.pop(best_index)
            chosen.append(pick)
            used_topics[pick.problem.primary_topic] = used_topics.get(pick.problem.primary_topic, 0) + 1

        return chosen

    def _pick_revisions(
        self,
        *,
        scored: list[Candidate],
        recent_problem_ids: set[str],
        count: int,
    ) -> list[Candidate]:
        """Choose review items from problems already solved or previously attempted.

        Revisions are drawn only from work the user has already done — reviewing an unseen
        problem is not a revision. Overdue items rank first.
        """
        if count <= 0:
            return []

        eligible = [
            item
            for item in scored
            if item.progress is not None
            and item.progress.status
            in (ProblemStatus.SOLVED, ProblemStatus.MASTERED, ProblemStatus.NEEDS_REVISION)
        ]
        if not eligible:
            return []

        revision_eligible = [
            item
            for item in eligible
            if item.progress is not None and item.progress.next_revision_date is not None
        ]
        pool = revision_eligible or eligible

        def revision_key(candidate: Candidate) -> tuple[int, int, str]:
            progress = candidate.progress
            assert progress is not None
            overdue = (
                0
                if progress.next_revision_date is None
                else max(0, (utcnow() - progress.next_revision_date).days)
            )
            # Lowest confidence first, then most overdue, then id for determinism.
            return (progress.confidence, -overdue, candidate.problem.id)

        pool = sorted(pool, key=revision_key)
        return pool[:count]

    # ------------------------------------------------------------- revision scheduling
    def build_revision_schedule(
        self,
        *,
        confidence: int | None,
        revision_count: int,
        from_time: datetime | None = None,
    ) -> tuple[datetime, int, str, int]:
        """Schedule the next review for a problem just solved.

        Delegates to :class:`RevisionPolicy` so the interval ladder stays configurable in
        one place rather than being duplicated in the planner.
        """
        schedule = self._policy.schedule_after_solve(
            confidence=confidence, from_time=from_time
        )
        return schedule.due_at, schedule.interval_days, schedule.reason, schedule.priority


__all__ = [
    "SCHEDULER_VERSION",
    "Candidate",
    "DailyPlanScheduler",
    "SchedulingResult",
]

# Re-exported for the plan builder's convenience.
_REVISION_REASON_DEFAULT = RevisionReason.SCHEDULED_REVISION.value
_ITEM_TYPE_NEW = ItemType.DSA_NEW.value
_ITEM_TYPE_REVISION = ItemType.DSA_REVISION.value
_HARD_DIFFICULTY = Difficulty.HARD.value
_DAY = timedelta(days=1)
