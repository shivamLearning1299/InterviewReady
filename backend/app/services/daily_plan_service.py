"""Daily plan orchestration.

``get_or_create_today`` is the entry point behind ``GET /api/v1/today``. It is safe under
concurrency and idempotent across refreshes:

1. Read the persisted plan for ``(user_id, today)``. If it exists, return it — this is the
   common path and it is a single indexed lookup.
2. Otherwise compute a plan inside a transaction and insert it.
3. If the insert loses a race (``unique(user_id, date_key)``), re-read and return the
   winner's row instead of erroring.

The result is that a plan is generated **at most once per user per day**, and refreshing
the endpoint returns byte-identical data.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.constants import ItemType
from app.core.logging import get_logger
from app.db.models import DailyPlan, UserSettings
from app.repositories.activity import ActivityRepository
from app.repositories.catalog import DSAProblemRepository
from app.repositories.dsa import ProblemProgressRepository
from app.repositories.planning import DailyPlanRepository, RevisionRepository
from app.schemas.common import ProgressSummary
from app.schemas.today import (
    DailyPlanDetail,
    PlanGenerationDebug,
    RevisionDueSummary,
    TodayItem,
    TodayResponse,
    TodaySection,
)
from app.services.daily_plan_scheduler import (
    SCHEDULER_VERSION,
    Candidate,
    DailyPlanScheduler,
)
from app.services.streak_service import StreakService
from app.utils.datetime_utils import resolve_timezone, today_local

logger = get_logger(__name__)

#: How many days back a problem is considered "recently assigned" and therefore skipped.
RECENT_PLAN_LOOKBACK_DAYS = 14


class DailyPlanService:
    def __init__(
        self,
        *,
        plan_repo: DailyPlanRepository,
        catalog_repo: DSAProblemRepository,
        progress_repo: ProblemProgressRepository,
        revision_repo: RevisionRepository,
        settings: Settings,
        scheduler: DailyPlanScheduler,
        streak_service: StreakService,
        activity_repo: ActivityRepository,
    ) -> None:
        self._plan_repo = plan_repo
        self._catalog_repo = catalog_repo
        self._progress_repo = progress_repo
        self._revision_repo = revision_repo
        self._settings = settings
        self._scheduler = scheduler
        self._streak_service = streak_service
        self._activity_repo = activity_repo

    # ----------------------------------------------------------------- public entry
    async def get_or_create_today(
        self,
        *,
        user_id: uuid.UUID,
        user_settings: UserSettings | None = None,
        timezone: str | None = None,
    ) -> TodayResponse:
        """Return today's plan, generating and persisting it on first request of the day."""
        tz_name = timezone or (user_settings.timezone if user_settings else None)
        tz = resolve_timezone(tz_name or self._settings.default_timezone)
        today = today_local(tz)

        plan = await self._plan_repo.get_by_date(user_id=user_id, plan_date=today)
        if plan is None:
            plan = await self._generate_plan(
                user_id=user_id, plan_date=today, tz=tz, user_settings=user_settings
            )
            # The plan has to outlive this request. Without an explicit commit the
            # request-scoped session rolls back when it closes, so every request would
            # generate a different plan and ``daily_plans`` would never hold a row — the
            # exact opposite of the "generate once per day" contract this method promises.
            await self._plan_repo.session.commit()

        return await self._build_today_response(
            user_id=user_id, plan=plan, tz=tz, user_settings=user_settings
        )

    async def get_plan_for_date(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        timezone: str | None = None,
    ) -> TodayResponse | None:
        """Fetch a historical plan. Returns ``None`` when no plan exists for that day."""
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        plan = await self._plan_repo.get_by_date(user_id=user_id, plan_date=plan_date)
        if plan is None:
            return None
        return await self._build_today_response(user_id=user_id, plan=plan, tz=tz)

    async def list_plans(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[DailyPlanDetail], int]:
        plans, total = await self._plan_repo.list_plans(
            user_id=user_id,
            limit=limit,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
        )

        summaries: list[DailyPlanDetail] = []
        for plan in plans:
            items = list(plan.items)
            summary = DailyPlanDetail(
                id=plan.id,
                user_id=plan.user_id,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
                version=plan.version,
                plan_date=plan.date_key,
                timezone=plan.timezone,
                status=plan.status,
                generated_by=plan.generated_by,
                total_items=len(items),
                completed_items=sum(1 for item in items if item.is_completed),
                dsa=TodaySection(
                    total=sum(
                        1
                        for item in items
                        if item.item_type in (ItemType.DSA_NEW.value, ItemType.DSA_REVISION.value)
                    ),
                    completed=sum(
                        1
                        for item in items
                        if item.item_type
                        in (ItemType.DSA_NEW.value, ItemType.DSA_REVISION.value)
                        and item.is_completed
                    ),
                ),
                lld=TodaySection(
                    total=sum(1 for item in items if item.item_type == ItemType.LLD.value),
                    completed=sum(
                        1
                        for item in items
                        if item.item_type == ItemType.LLD.value and item.is_completed
                    ),
                ),
                hld=TodaySection(
                    total=sum(1 for item in items if item.item_type == ItemType.HLD.value),
                    completed=sum(
                        1
                        for item in items
                        if item.item_type == ItemType.HLD.value and item.is_completed
                    ),
                ),
            )
            summaries.append(summary)

        return summaries, total

    # ------------------------------------------------------------------- generation
    async def _generate_plan(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        tz: ZoneInfo,
        user_settings: UserSettings | None,
    ) -> DailyPlan:
        """Compute and persist a plan. Concurrency-safe via the unique constraint."""
        # Full catalog + this user's progress, in one query.
        catalog = await self._catalog_repo.list_all_for_scheduling(user_id=user_id)
        if not catalog:
            # Seeding has not run yet. Create an empty plan rather than erroring, so the
            # client still gets a valid response shape.
            logger.warning("Catalog is empty; creating an empty daily plan")
            return await self._insert_plan(
                user_id=user_id, plan_date=plan_date, tz=tz, candidates=[], revisions=[]
            )

        recent_problem_ids = await self._plan_repo.list_recent_problem_ids(
            user_id=user_id,
            since=plan_date - timedelta(days=RECENT_PLAN_LOOKBACK_DAYS),
        )
        topic_performance = await self._progress_repo.topic_performance(user_id=user_id)

        new_count = self._settings.dsa_daily_count(
            user_settings.daily_dsa_count if user_settings else None
        )
        revision_count = self._settings.revision_daily_count(
            user_settings.daily_revision_count if user_settings else None
        )

        result = self._scheduler.select(
            user_id=user_id,
            plan_date=plan_date,
            catalog=catalog,
            recent_problem_ids=recent_problem_ids,
            topic_performance=topic_performance,
            new_count=new_count,
            revision_count=revision_count,
        )

        return await self._insert_plan(
            user_id=user_id,
            plan_date=plan_date,
            tz=tz,
            candidates=result.new_problems,
            revisions=result.revision_problems,
            explanation=result.explanation,
        )

    async def _insert_plan(
        self,
        *,
        user_id: uuid.UUID,
        plan_date: date,
        tz: ZoneInfo,
        candidates: list[Candidate],
        revisions: list[Candidate],
        explanation: dict | None = None,
    ) -> DailyPlan:
        """Persist the plan and its items, tolerating a concurrent insert."""
        problem_ids = [candidate.problem_id for candidate in candidates]

        try:
            # savepoint: a losing race must not poison the outer transaction.
            async with self._plan_repo.session.begin_nested():
                plan = await self._plan_repo.create_plan(
                    user_id=user_id,
                    plan_date=plan_date,
                    timezone=str(tz),
                    problem_ids=problem_ids,
                    generated_by=SCHEDULER_VERSION,
                )

                items = [
                    self._plan_item_payload(candidate, index, ItemType.DSA_NEW.value)
                    for index, candidate in enumerate(candidates)
                ] + [
                    self._plan_item_payload(
                        candidate, len(candidates) + index, ItemType.DSA_REVISION.value
                    )
                    for index, candidate in enumerate(revisions)
                ]

                if items:
                    await self._plan_repo.add_items(plan, items)
        except IntegrityError:
            # Another request (or another worker) generated today's plan first. Return
            # theirs rather than a 500 — this is the expected outcome of a race.
            logger.info("Daily plan generation lost a race; returning the existing plan")
            existing = await self._plan_repo.get_by_date(user_id=user_id, plan_date=plan_date)
            if existing is not None:
                return existing
            raise

        # Reload with items eagerly attached so the response builder never triggers lazy IO.
        refreshed = await self._plan_repo.get_by_date(user_id=user_id, plan_date=plan_date)
        assert refreshed is not None
        return refreshed

    @staticmethod
    def _plan_item_payload(candidate: Candidate, position: int, item_type: str) -> dict:
        return {
            "item_type": item_type,
            "position": position,
            "problem_id": candidate.problem_id,
            "title": candidate.problem.title,
            "difficulty": candidate.problem.difficulty,
            "reason": "; ".join(candidate.reasons[:2]) or None,
            "score": candidate.score,
            "estimated_minutes": candidate.problem.estimated_minutes,
        }

    # ---------------------------------------------------------------- response builder
    async def _build_today_response(
        self,
        *,
        user_id: uuid.UUID,
        plan: DailyPlan,
        tz: ZoneInfo,
        user_settings: UserSettings | None = None,
    ) -> TodayResponse:
        """Assemble the ``/today`` payload.

        Every collection is fetched with one query per concern (items+problems together,
        revisions, progress, streak, study minutes) — never per row.
        """
        rows = await self._plan_repo.list_items_with_problems(
            user_id=user_id, plan_id=plan.id
        )

        problem_ids = [problem.id for _, problem in rows if problem is not None]
        progress_map = await self._progress_repo.get_by_problem_ids(
            user_id=user_id, problem_ids=problem_ids
        )

        sections: dict[str, TodaySection] = {
            ItemType.DSA_NEW.value: TodaySection(),
            ItemType.DSA_REVISION.value: TodaySection(),
            ItemType.LLD.value: TodaySection(),
            ItemType.HLD.value: TodaySection(),
        }

        total_estimated = 0
        for item, problem in rows:
            section = sections.setdefault(item.item_type, TodaySection())
            section.total += 1
            if item.is_completed:
                section.completed += 1
            if item.estimated_minutes:
                total_estimated += item.estimated_minutes

            progress = progress_map.get(item.problem_id) if item.problem_id else None
            section.items.append(
                TodayItem(
                    id=item.id,
                    item_type=item.item_type,
                    position=item.position,
                    problem_id=item.problem_id,
                    topic_id=item.topic_id,
                    title=problem.title if problem else item.title,
                    slug=problem.slug if problem else None,
                    difficulty=problem.difficulty if problem else item.difficulty,
                    primary_topic=problem.primary_topic if problem else None,
                    patterns=list(problem.patterns) if problem else [],
                    external_url=problem.external_url if problem else None,
                    estimated_minutes=item.estimated_minutes,
                    reason=item.reason,
                    is_completed=item.is_completed,
                    completed_at=item.completed_at,
                    progress=self._progress_summary(progress),
                )
            )

        revision_counts = await self._revision_repo.due_counts(user_id=user_id)
        streak = await self._streak_service.get_streak(user_id=user_id, timezone=str(tz))

        today = today_local(tz)
        activity = await self._activity_repo.get_day(user_id=user_id, activity_date=today)
        study_minutes_today = activity.study_minutes if activity else 0

        dsa_section = sections[ItemType.DSA_NEW.value]
        revision_section = sections[ItemType.DSA_REVISION.value]

        total_items = len(rows)
        completed_items = sum(1 for item, _ in rows if item.is_completed)

        return TodayResponse(
            date=plan.date_key,
            timezone=plan.timezone,
            plan_id=plan.id,
            status=plan.status,
            generated_at=plan.created_at,
            is_completed=bool(total_items) and completed_items == total_items,
            streak=streak,
            dsa=dsa_section,
            lld=sections[ItemType.LLD.value],
            hld=sections[ItemType.HLD.value],
            revisions=revision_section,
            revisions_due=revision_counts.get("due", 0),
            revision_summary=RevisionDueSummary(
                total=revision_counts.get("due", 0),
                overdue=revision_counts.get("overdue", 0),
                due_today=revision_counts.get("due_today", 0),
                upcoming=revision_counts.get("upcoming", 0),
            ),
            study_minutes_today=study_minutes_today,
            active_session_id=None,
            total_estimated_minutes=total_estimated,
        )

    @staticmethod
    def _progress_summary(progress) -> Any:
        if progress is None:
            return ProgressSummary()
        return ProgressSummary(
            status=progress.status,
            attempts=progress.attempts,
            confidence=progress.confidence,
            is_favorite=progress.is_favorite,
            next_revision_at=progress.next_revision_date,
            solved_at=progress.solved_date,
            total_time_spent_minutes=progress.time_spent_minutes,
        )

    # --------------------------------------------------------------------- debugging
    async def explain_today(
        self, *, user_id: uuid.UUID, timezone: str | None = None
    ) -> PlanGenerationDebug:
        """Non-sensitive diagnostics for why today's plan looks the way it does."""
        tz = resolve_timezone(timezone or self._settings.default_timezone)
        today = today_local(tz)

        catalog = await self._catalog_repo.list_all_for_scheduling(user_id=user_id)
        topic_performance = await self._progress_repo.topic_performance(user_id=user_id)
        recent_problem_ids = await self._plan_repo.list_recent_problem_ids(
            user_id=user_id,
            since=today - timedelta(days=RECENT_PLAN_LOOKBACK_DAYS),
        )

        result = self._scheduler.select(
            user_id=user_id,
            plan_date=today,
            catalog=catalog,
            recent_problem_ids=recent_problem_ids,
            topic_performance=topic_performance,
            new_count=self._settings.daily_dsa_count_default,
            revision_count=self._settings.revision_dsa_count_default,
        )

        return PlanGenerationDebug(
            candidate_count=result.candidate_count,
            new_problem_count=len(result.new_problems),
            revision_count=len(result.revision_problems),
            weak_topics=result.weakest_topics[:10],
            covered_topics=result.covered_topics,
            scoring_version=SCHEDULER_VERSION,
            explanation=result.explanation,
        )
