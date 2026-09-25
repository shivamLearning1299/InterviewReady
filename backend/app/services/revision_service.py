"""Revision queue service.

Wraps :class:`RevisionPolicy` with persistence. The policy owns *when* something is due;
this owns the consequences of a review completing:

* bump the progress row's ``revision_count`` and ``confidence``;
* write ``next_revision_date`` so the scheduler sees the new due time;
* queue the next revision in the ladder (unless the user opted out);
* record the activity day for streaks.

Completion is idempotent: reviewing an already-completed item returns it unchanged rather
than double-incrementing the ladder, which matters because the offline client may replay
the request.
"""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.constants import ProblemStatus, RevisionReason
from app.core.logging import get_logger
from app.db.models import DSAProblem, RevisionQueueItem
from app.repositories.catalog import DSAProblemRepository
from app.repositories.dsa import ProblemProgressRepository
from app.repositories.planning import RevisionRepository
from app.schemas.dsa import (
    ProgressResponse,
    RevisionCompleteRequest,
    RevisionCompleteResponse,
    RevisionCreateRequest,
    RevisionResponse,
)
from app.services.activity_service import ActivityService
from app.services.revision_policy import RevisionPolicy
from app.utils.datetime_utils import utcnow

logger = get_logger(__name__)


class RevisionService:
    def __init__(
        self,
        *,
        revision_repo: RevisionRepository,
        progress_repo: ProblemProgressRepository,
        catalog_repo: DSAProblemRepository,
        activity_service: ActivityService,
        revision_policy: RevisionPolicy,
        settings: Settings,
    ) -> None:
        self._revisions = revision_repo
        self._progress = progress_repo
        self._catalog = catalog_repo
        self._activity = activity_service
        self._policy = revision_policy
        self._settings = settings

    # ----------------------------------------------------------------------- read
    async def list_revisions(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        bucket: str | None = None,
        completed: bool | None = False,
        problem_ids: list[str] | None = None,
    ) -> tuple[list[RevisionResponse], int]:
        rows, total = await self._revisions.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
            bucket=bucket,
            completed=completed,
            problem_ids=problem_ids,
        )
        return [self._to_response(revision, problem) for revision, problem in rows], total

    async def list_for_problem(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> list[RevisionResponse]:
        rows = await self._revisions.list_for_problem(user_id=user_id, problem_id=problem_id)
        problems = await self._catalog.get_by_ids([problem_id])
        problem = problems.get(problem_id)
        return [self._to_response(row, problem) for row in rows]

    async def due_summary(self, *, user_id: uuid.UUID) -> dict[str, int]:
        return await self._revisions.due_counts(user_id=user_id)

    # ------------------------------------------------------------------ scheduling
    async def schedule_manual(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        payload: RevisionCreateRequest,
    ) -> RevisionResponse:
        """Manually schedule (or reschedule) a revision for a problem."""
        problem, progress = await self._catalog.get_with_progress(
            user_id=user_id, problem_id=problem_id
        )

        confidence = progress.confidence if progress else None
        revision_count = progress.revision_count if progress else 0

        if payload.due_at is not None:
            due_at = payload.due_at
            if due_at.tzinfo is None:
                # A naive timestamp from a client is treated as UTC rather than rejected:
                # the alternative is a confusing 422 for a value the client believes is fine.
                from app.utils.datetime_utils import UTC_TZ

                due_at = due_at.replace(tzinfo=UTC_TZ)
            interval_days = max(0, (due_at - utcnow()).days)
        else:
            due_at, interval_days = self._policy.next_due_at(
                confidence=confidence, revision_count=revision_count
            )

        reason = payload.reason or RevisionReason.MANUAL.value
        priority = payload.priority or self._policy.priority_for(
            confidence=confidence, reason=reason
        )

        revision = await self._revisions.upsert_open_revision(
            user_id=user_id,
            problem_id=problem_id,
            due_at=due_at,
            reason=reason,
            priority=priority,
            interval_days=interval_days,
            confidence_before=confidence,
        )

        if payload.notes is not None:
            revision.notes = payload.notes

        # Keep the progress row's single "next due" instant aligned with the queue.
        if progress is not None:
            progress.next_revision_date = due_at
            progress.version = (progress.version or 1) + 1

        await self._revisions.session.commit()
        return self._to_response(revision, problem)

    # -------------------------------------------------------------------- completing
    async def complete(
        self,
        *,
        user_id: uuid.UUID,
        revision_id: uuid.UUID,
        payload: RevisionCompleteRequest,
        timezone: str | None = None,
    ) -> RevisionCompleteResponse:
        """Record a completed review and queue the next one.

        Idempotent: if the revision is already complete, the stored result is returned
        without advancing the ladder again.
        """
        revision = await self._revisions.get(user_id=user_id, revision_id=revision_id)

        if revision.completed:
            logger.info("Revision already completed; returning stored result")
            problem = (await self._catalog.get_by_ids([revision.problem_id])).get(
                revision.problem_id
            )
            return RevisionCompleteResponse(
                revision=self._to_response(revision, problem),
                progress=None,
                next_revision=None,
                interval_days=revision.interval_days,
                message="Revision was already recorded",
            )

        now = utcnow()
        progress = await self._progress.get(user_id=user_id, problem_id=revision.problem_id)

        confidence_after = (
            payload.confidence if payload.confidence is not None else (progress.confidence if progress else None)
        )
        revision_count_before = progress.revision_count if progress else 0

        await self._revisions.complete(
            revision,
            result=payload.result,
            confidence_after=confidence_after,
            notes=payload.notes,
        )

        # Update the progress row: ladder position, confidence, recency.
        progress_values: dict = {
            "last_reviewed_date": now,
            "revision_count": revision_count_before + (0 if payload.result == "failed" else 1),
        }
        if confidence_after is not None:
            progress_values["confidence"] = confidence_after

        if payload.result == "failed":
            # A failed review means the problem is not yet solid.
            progress_values["status"] = ProblemStatus.NEEDS_REVISION.value
        elif progress is not None and progress.status == ProblemStatus.NEEDS_REVISION.value:
            # Recovering from needs_revision; mastery is a separate deliberate signal.
            progress_values["status"] = ProblemStatus.SOLVED.value
            if progress.revision_count + 1 >= 4 and (confidence_after or 0) >= 4:
                progress_values["status"] = ProblemStatus.MASTERED.value
        elif progress is None:
            # Reviewing a problem that has no progress row yet creates one, and `status` is
            # NOT NULL in the pre-existing schema. A successful review means it is solved.
            progress_values["status"] = ProblemStatus.SOLVED.value
        else:
            # An already-solved (or mastered) problem keeps its status; reviewing it again
            # must not silently demote mastery back to solved.
            progress_values["status"] = progress.status

        # Queue the next revision.
        next_revision = None
        interval_days = None
        if payload.schedule_next:
            schedule = self._policy.schedule_after_review(
                result=payload.result,
                confidence=confidence_after,
                revision_count_before=revision_count_before,
                from_time=now,
            )
            next_revision = await self._revisions.create(
                user_id=user_id,
                problem_id=revision.problem_id,
                due_at=schedule.due_at,
                reason=schedule.reason,
                priority=schedule.priority,
                interval_days=schedule.interval_days,
                confidence_before=confidence_after,
            )
            interval_days = schedule.interval_days
            progress_values["next_revision_date"] = schedule.due_at
        else:
            progress_values["next_revision_date"] = None

        updated_progress = await self._progress.upsert(
            user_id=user_id, problem_id=revision.problem_id, values=progress_values
        )

        await self._activity.record(
            user_id=user_id,
            timezone=timezone,
            activity_count=1,
            revisions_completed=1,
            problems_solved=1 if payload.result == "success" else 0,
        )

        await self._revisions.session.commit()

        problem = (await self._catalog.get_by_ids([revision.problem_id])).get(revision.problem_id)

        logger.info(
            "Revision completed",
            extra={
                "problem_id": revision.problem_id,
                "result": payload.result,
                "next_interval_days": interval_days,
            },
        )

        return RevisionCompleteResponse(
            revision=self._to_response(revision, problem),
            progress=self._progress_response(updated_progress),
            next_revision=(
                self._to_response(next_revision, problem) if next_revision is not None else None
            ),
            interval_days=interval_days,
            message=(
                "Revision recorded"
                if payload.result != "failed"
                else "Revision recorded — this one comes back tomorrow"
            ),
        )

    # -------------------------------------------------------------- housekeeping
    async def promote_stale_problems(
        self, *, user_id: uuid.UUID, limit: int = 10
    ) -> int:
        """Queue reviews for solved problems that have gone stale.

        Without this, a user who has solved everything and cleared their queue would see an
        empty revision list forever, even though there is plenty worth reviewing.
        """
        due = await self._progress.list_due_revisions(
            user_id=user_id, before=utcnow(), limit=limit
        )
        queued = 0
        for progress in due:
            if progress.status not in (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value):
                continue
            confidence = progress.confidence
            await self._revisions.upsert_open_revision(
                user_id=user_id,
                problem_id=progress.problem_id,
                due_at=utcnow(),
                reason=RevisionReason.LONG_TIME_SINCE_REVIEW.value,
                priority=self._policy.priority_for(
                    confidence=confidence, reason=RevisionReason.LONG_TIME_SINCE_REVIEW.value
                ),
                interval_days=self._policy.interval_days(
                    confidence=confidence, revision_count=progress.revision_count
                ),
                confidence_before=confidence,
            )
            queued += 1

        if queued:
            await self._revisions.session.commit()
        return queued

    # -------------------------------------------------------------------- mapping
    @staticmethod
    def _to_response(
        revision: RevisionQueueItem, problem: DSAProblem | None = None
    ) -> RevisionResponse:
        return RevisionResponse(
            id=revision.id,
            user_id=revision.user_id,
            created_at=revision.created_at,
            updated_at=revision.updated_at,
            version=revision.version,
            problem_id=revision.problem_id,
            due_at=revision.due_at,
            reason=revision.reason,
            priority=revision.priority,
            completed=revision.completed,
            completed_at=revision.completed_at,
            result=revision.result,
            confidence_before=revision.confidence_before,
            interval_days=revision.interval_days,
            notes=revision.notes,
            problem_title=problem.title if problem else None,
            problem_slug=problem.slug if problem else None,
            problem_difficulty=problem.difficulty if problem else None,
            problem_topic=problem.primary_topic if problem else None,
        )

    @staticmethod
    def _progress_response(progress) -> ProgressResponse | None:
        if progress is None:
            return None
        return ProgressResponse(
            id=progress.id,
            user_id=progress.user_id,
            created_at=progress.created_at,
            updated_at=progress.updated_at,
            version=progress.version,
            problem_id=progress.problem_id,
            status=progress.status,
            attempts=progress.attempts,
            confidence=progress.confidence,
            revision_count=progress.revision_count,
            first_attempt_at=progress.first_attempt_date,
            solved_at=progress.solved_date,
            last_reviewed_at=progress.last_reviewed_date,
            next_revision_at=progress.next_revision_date,
            total_time_spent_minutes=progress.time_spent_minutes,
            is_favorite=progress.is_favorite,
        )


__all__ = ["RevisionService"]
