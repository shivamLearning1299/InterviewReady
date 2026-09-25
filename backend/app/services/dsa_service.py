"""DSA progress, attempts, notes and code services.

These hold the write-side business rules that the routes must not contain:

* which timestamps a status transition implies;
* when a revision should be scheduled;
* keeping the attempts counter, the attempt log and the activity ledger consistent.

Several of these operations must be atomic together — "mark solved + schedule a revision +
record the activity day" is one logical write — so the service owns the transaction and
commits once.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from app.core.config import Settings
from app.core.constants import AttemptOutcome, CodeContextType, ItemType, ProblemStatus
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.db.models import CodeSnippet, ProblemAttempt, ProblemNote, UserProblemProgress
from app.repositories.catalog import DSAProblemRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemAttemptRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.planning import DailyPlanRepository, RevisionRepository
from app.schemas.dsa import (
    AttemptCreateRequest,
    AttemptResponse,
    AttemptUpdateRequest,
    CodeSnippetCreate,
    CodeSnippetResponse,
    CodeSnippetUpdate,
    ProblemNotesResponse,
    ProblemNotesUpsert,
    ProgressResponse,
    ProgressUpdateRequest,
)
from app.services.activity_service import ActivityService
from app.services.revision_policy import RevisionPolicy
from app.utils.datetime_utils import clamp_minutes, utcnow

logger = get_logger(__name__)

#: Outcomes that mean the problem is effectively complete.
_SOLVED_OUTCOMES = {
    AttemptOutcome.SOLVED.value,
    AttemptOutcome.SOLVED_WITH_HINT.value,
    AttemptOutcome.REVISION_SUCCESS.value,
}

#: Outcomes that should pull the problem back into the revision queue.
_FAILED_OUTCOMES = {
    AttemptOutcome.GAVE_UP.value,
    AttemptOutcome.PARTIAL.value,
    AttemptOutcome.REVISION_FAILED.value,
}


class ProgressService:
    """Owns ``user_problem_progress`` writes."""

    def __init__(
        self,
        *,
        progress_repo: ProblemProgressRepository,
        catalog_repo: DSAProblemRepository,
        revision_repo: RevisionRepository,
        plan_repo: DailyPlanRepository,
        activity_service: ActivityService,
        revision_policy: RevisionPolicy,
        settings: Settings,
    ) -> None:
        self._progress_repo = progress_repo
        self._catalog_repo = catalog_repo
        self._revision_repo = revision_repo
        self._plan_repo = plan_repo
        self._activity = activity_service
        self._policy = revision_policy
        self._settings = settings

    # ----------------------------------------------------------------------- read
    async def get_progress(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> UserProblemProgress | None:
        return await self._progress_repo.get(user_id=user_id, problem_id=problem_id)

    # ---------------------------------------------------------------------- write
    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        payload: ProgressUpdateRequest,
        timezone: str | None = None,
    ) -> ProgressResponse:
        """Apply a progress update.

        Upsert semantics: the row is created on first write. Timestamps are derived from
        the transition rather than trusted from the client:

        * moving to ``attempted`` or later sets ``first_attempt_date`` if unset;
        * moving to ``solved``/``mastered`` sets ``solved_date`` and schedules a revision;
        * ``needs_revision`` keeps the problem in the queue with high priority.
        """
        # Validate the problem exists so a typo cannot create orphan progress.
        problem, _ = await self._catalog_repo.get_with_progress(
            user_id=user_id, problem_id=problem_id
        )

        existing = await self._progress_repo.get(user_id=user_id, problem_id=problem_id)
        now = utcnow()

        values: dict[str, Any] = {}
        revision_scheduled = False

        if payload.status is not None:
            status = payload.status.value if hasattr(payload.status, "value") else payload.status
            values["status"] = status

            if status == ProblemStatus.NOT_STARTED.value:
                # Resetting: clear the derived timestamps so the UI is not misleading.
                values["first_attempt_date"] = None
                values["solved_date"] = None
                values["next_revision_date"] = None
            else:
                if existing is None or existing.first_attempt_date is None:
                    values["first_attempt_date"] = now

                if status in (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value):
                    if existing is None or existing.solved_date is None:
                        values["solved_date"] = now
                    values["last_reviewed_date"] = now

                    confidence = (
                        payload.confidence
                        if payload.confidence is not None
                        else (existing.confidence if existing else None)
                    )
                    schedule = self._policy.schedule_after_solve(
                        confidence=confidence, from_time=now
                    )
                    values["next_revision_date"] = schedule.due_at
                    await self._revision_repo.upsert_open_revision(
                        user_id=user_id,
                        problem_id=problem_id,
                        due_at=schedule.due_at,
                        reason=schedule.reason,
                        priority=schedule.priority,
                        interval_days=schedule.interval_days,
                        confidence_before=confidence,
                    )
                    revision_scheduled = True

                elif status == ProblemStatus.NEEDS_REVISION.value:
                    # Bring it back tomorrow at maximum priority.
                    due_at = now + timedelta(days=1)
                    values["next_revision_date"] = due_at
                    await self._revision_repo.upsert_open_revision(
                        user_id=user_id,
                        problem_id=problem_id,
                        due_at=due_at,
                        reason="low_confidence",
                        priority=5,
                        interval_days=1,
                        confidence_before=payload.confidence,
                    )
                    revision_scheduled = True

        if payload.confidence is not None:
            values["confidence"] = payload.confidence

        if payload.is_favorite is not None:
            values["is_favorite"] = payload.is_favorite

        if payload.attempts is not None:
            values["attempts"] = payload.attempts

        if payload.time_spent_minutes is not None:
            prior = existing.time_spent_minutes if existing else 0
            values["time_spent_minutes"] = prior + clamp_minutes(payload.time_spent_minutes)

        # An explicit request to schedule, even without a status change.
        if payload.schedule_revision and not revision_scheduled:
            confidence = (
                payload.confidence
                if payload.confidence is not None
                else (existing.confidence if existing else None)
            )
            schedule = self._policy.schedule_after_solve(confidence=confidence, from_time=now)
            values["next_revision_date"] = schedule.due_at
            await self._revision_repo.upsert_open_revision(
                user_id=user_id,
                problem_id=problem_id,
                due_at=schedule.due_at,
                reason="manual",
                priority=schedule.priority,
                interval_days=schedule.interval_days,
                confidence_before=confidence,
            )

        if not values:
            # Nothing to change; return current state (or a default) rather than writing.
            if existing is not None:
                return self._to_response(existing)
            values = {"status": ProblemStatus.NOT_STARTED.value}

        row = await self._progress_repo.upsert(
            user_id=user_id, problem_id=problem_id, values=values
        )

        # Marking a problem solved should also tick it off today's plan if it is there.
        if values.get("status") in (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value):
            await self._complete_plan_item_for_problem(user_id=user_id, problem_id=problem_id)

        # Record the meaningful event for streaks. Not "any write": a favourite toggle or a
        # confidence tweak should not extend a streak.
        if values.get("status") is not None and values["status"] != ProblemStatus.NOT_STARTED.value:
            await self._activity.record(
                user_id=user_id,
                timezone=timezone,
                activity_count=1,
                problems_solved=(
                    1
                    if values["status"] in (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value)
                    else 0
                ),
                problems_attempted=(
                    1 if values["status"] == ProblemStatus.ATTEMPTED.value else 0
                ),
            )

        await self._progress_repo.session.commit()

        logger.info(
            "Progress updated",
            extra={
                "problem_id": problem.id,
                "status": row.status,
                "revision_scheduled": revision_scheduled,
            },
        )
        return self._to_response(row)

    async def _complete_plan_item_for_problem(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> None:
        """Mark today's plan item complete when its problem is solved elsewhere."""
        from app.utils.datetime_utils import today_local

        today = today_local(self._settings.default_timezone)
        plan = await self._plan_repo.get_by_date(user_id=user_id, plan_date=today)
        if plan is None:
            return

        for item in plan.items:
            if item.problem_id == problem_id and not item.is_completed:
                await self._plan_repo.set_item_completion(item, is_completed=True)

    @staticmethod
    def _to_response(row: UserProblemProgress) -> ProgressResponse:
        return ProgressResponse(
            id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
            problem_id=row.problem_id,
            status=row.status,
            attempts=row.attempts,
            confidence=row.confidence,
            revision_count=row.revision_count,
            first_attempt_at=row.first_attempt_date,
            solved_at=row.solved_date,
            last_reviewed_at=row.last_reviewed_date,
            next_revision_at=row.next_revision_date,
            total_time_spent_minutes=row.time_spent_minutes,
            is_favorite=row.is_favorite,
        )


class AttemptService:
    """Owns ``problem_attempts`` writes and their effect on progress."""

    def __init__(
        self,
        *,
        attempt_repo: ProblemAttemptRepository,
        progress_repo: ProblemProgressRepository,
        catalog_repo: DSAProblemRepository,
        revision_repo: RevisionRepository,
        activity_service: ActivityService,
        revision_policy: RevisionPolicy,
    ) -> None:
        self._attempts = attempt_repo
        self._progress = progress_repo
        self._catalog = catalog_repo
        self._revisions = revision_repo
        self._activity = activity_service
        self._policy = revision_policy

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        payload: AttemptCreateRequest,
        timezone: str | None = None,
    ) -> AttemptResponse:
        """Log an attempt and roll its consequences into progress in one transaction."""
        await self._catalog.get_with_progress(user_id=user_id, problem_id=problem_id)

        now = utcnow()
        started_at = payload.started_at or now
        completed_at = payload.completed_at

        # Default the completion time from the recorded duration when the client omitted it.
        if completed_at is None and payload.duration_minutes is not None:
            completed_at = started_at + timedelta(minutes=payload.duration_minutes)
        if completed_at is None and payload.outcome is not None:
            completed_at = now

        duration = payload.duration_minutes
        if duration is None and completed_at is not None:
            duration = clamp_minutes((completed_at - started_at).total_seconds() / 60)
            # A zero-minute attempt is almost always a data-entry artifact; record 1 so the
            # logs stay useful rather than full of empty rows.
            duration = duration or 1

        attempt = await self._attempts.create(
            user_id=user_id,
            problem_id=problem_id,
            values={
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_minutes": duration,
                "outcome": payload.outcome.value if payload.outcome else None,
                "notes": payload.notes,
            },
        )

        if payload.update_progress:
            await self._apply_to_progress(
                user_id=user_id,
                problem_id=problem_id,
                outcome=payload.outcome.value if payload.outcome else None,
                duration_minutes=duration or 0,
                confidence=payload.confidence,
                completed_at=completed_at or now,
            )

        await self._activity.record(
            user_id=user_id,
            timezone=timezone,
            activity_count=1,
            study_minutes=duration or 0,
            problems_attempted=1,
            problems_solved=1 if (payload.outcome and payload.outcome.value in _SOLVED_OUTCOMES) else 0,
        )

        await self._attempts.session.commit()
        return self._to_response(attempt)

    async def _apply_to_progress(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        outcome: str | None,
        duration_minutes: int,
        confidence: int | None,
        completed_at: Any,
    ) -> None:
        """Fold an attempt's outcome into the progress row."""
        existing = await self._progress.get(user_id=user_id, problem_id=problem_id)

        values: dict[str, Any] = {
            "attempts": (existing.attempts if existing else 0) + 1,
            "time_spent_minutes": (existing.time_spent_minutes if existing else 0)
            + max(duration_minutes, 0),
        }

        if existing is None or existing.first_attempt_date is None:
            values["first_attempt_date"] = completed_at

        if confidence is not None:
            values["confidence"] = confidence

        effective_confidence = (
            confidence if confidence is not None else (existing.confidence if existing else None)
        )

        if outcome in _SOLVED_OUTCOMES:
            values["status"] = ProblemStatus.SOLVED.value
            if existing is None or existing.solved_date is None:
                values["solved_date"] = completed_at
            values["last_reviewed_date"] = completed_at

            schedule = self._policy.schedule_after_solve(
                confidence=effective_confidence, from_time=completed_at
            )
            values["next_revision_date"] = schedule.due_at
            await self._revisions.upsert_open_revision(
                user_id=user_id,
                problem_id=problem_id,
                due_at=schedule.due_at,
                reason=schedule.reason,
                priority=schedule.priority,
                interval_days=schedule.interval_days,
                confidence_before=effective_confidence,
            )

        elif outcome in _FAILED_OUTCOMES:
            # Do not downgrade a previously solved problem on one bad retry, but do mark it
            # for revision so the weakness is visible.
            already_solved = existing is not None and existing.status in (
                ProblemStatus.SOLVED.value,
                ProblemStatus.MASTERED.value,
            )
            values["status"] = (
                ProblemStatus.NEEDS_REVISION.value
                if already_solved
                else ProblemStatus.ATTEMPTED.value
            )
            due_at = completed_at + timedelta(days=1)
            values["next_revision_date"] = due_at
            await self._revisions.upsert_open_revision(
                user_id=user_id,
                problem_id=problem_id,
                due_at=due_at,
                reason="failed_attempt",
                priority=5,
                interval_days=1,
                confidence_before=effective_confidence,
            )

        elif existing is None or existing.status == ProblemStatus.NOT_STARTED.value:
            values["status"] = ProblemStatus.ATTEMPTED.value

        await self._progress.upsert(user_id=user_id, problem_id=problem_id, values=values)

    async def list_for_problem(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[AttemptResponse], int]:
        attempts, total = await self._attempts.list_for_problem(
            user_id=user_id, problem_id=problem_id, limit=limit, offset=offset
        )
        return [self._to_response(attempt) for attempt in attempts], total

    async def update(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        attempt_id: uuid.UUID,
        payload: AttemptUpdateRequest,
    ) -> AttemptResponse:
        attempt = await self._attempts.get(user_id=user_id, attempt_id=attempt_id)

        if attempt.problem_id != problem_id:
            # The attempt belongs to a different problem: treat it as not found rather than
            # silently editing the wrong row.
            raise ValidationError("Attempt does not belong to this problem.")

        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not values:
            return self._to_response(attempt)

        # Recompute the duration when the client changed the completion time.
        if "completed_at" in values and values["completed_at"] is not None:
            start = values.get("started_at", attempt.started_at)
            values["duration_minutes"] = clamp_minutes(
                (values["completed_at"] - start).total_seconds() / 60
            )

        updated = await self._attempts.update(attempt, values)
        await self._attempts.session.commit()
        return self._to_response(updated)

    @staticmethod
    def _to_response(attempt: ProblemAttempt) -> AttemptResponse:
        return AttemptResponse(
            id=attempt.id,
            user_id=attempt.user_id,
            created_at=attempt.created_at,
            updated_at=attempt.updated_at,
            version=attempt.version,
            problem_id=attempt.problem_id,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            duration_minutes=attempt.duration_minutes,
            outcome=attempt.outcome,
            notes=attempt.notes,
        )


class NotesService:
    """Owns ``problem_notes`` writes.

    The underlying columns are ``NOT NULL DEFAULT ''``, so ``None`` is normalised to an
    empty string rather than being sent to the database.
    """

    def __init__(self, *, notes_repo: ProblemNotesRepository, catalog_repo: DSAProblemRepository) -> None:
        self._notes = notes_repo
        self._catalog = catalog_repo

    async def get(self, *, user_id: uuid.UUID, problem_id: str) -> ProblemNotesResponse | None:
        note = await self._notes.get(user_id=user_id, problem_id=problem_id)
        return self._to_response(note) if note else None

    async def upsert(
        self, *, user_id: uuid.UUID, problem_id: str, payload: ProblemNotesUpsert
    ) -> ProblemNotesResponse:
        await self._catalog.get_with_progress(user_id=user_id, problem_id=problem_id)

        supplied = payload.model_dump(exclude_unset=True)
        values = {key: (value if value is not None else "") for key, value in supplied.items()}
        if not values:
            existing = await self._notes.get(user_id=user_id, problem_id=problem_id)
            if existing is not None:
                return self._to_response(existing)
            values = {}

        note = await self._notes.upsert(user_id=user_id, problem_id=problem_id, values=values)
        await self._notes.session.commit()
        return self._to_response(note)

    @staticmethod
    def _to_response(note: ProblemNote) -> ProblemNotesResponse:
        return ProblemNotesResponse(
            id=note.id,
            user_id=note.user_id,
            created_at=note.created_at,
            updated_at=note.updated_at,
            version=note.version,
            problem_id=note.problem_id,
            approach=note.approach or None,
            notes=note.notes or None,
            mistakes=note.mistakes or None,
            revision_notes=note.revision_notes or None,
            time_complexity=note.time_complexity or None,
            space_complexity=note.space_complexity or None,
        )


class CodeSnippetService:
    """Owns ``code_snippets`` writes for DSA, LLD and HLD.

    Storage only — nothing here compiles, lints or executes the code.
    """

    def __init__(
        self,
        *,
        snippet_repo: CodeSnippetRepository,
        catalog_repo: DSAProblemRepository | None = None,
    ) -> None:
        self._snippets = snippet_repo
        self._catalog = catalog_repo

    async def list_for_dsa(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> list[CodeSnippetResponse]:
        rows = await self._snippets.list_for_context(
            user_id=user_id,
            context_type=CodeContextType.DSA.value,
            context_id=problem_id,
        )
        return [self._to_response(row) for row in rows]

    async def list_for_topic(
        self, *, user_id: uuid.UUID, context_type: str, topic_id: uuid.UUID
    ) -> list[CodeSnippetResponse]:
        rows = await self._snippets.list_for_context(
            user_id=user_id,
            context_type=context_type,
            context_id=str(topic_id),
        )
        return [self._to_response(row) for row in rows]

    async def create_for_dsa(
        self, *, user_id: uuid.UUID, problem_id: str, payload: CodeSnippetCreate
    ) -> CodeSnippetResponse:
        if self._catalog is not None:
            await self._catalog.get_with_progress(user_id=user_id, problem_id=problem_id)

        snippet = await self._snippets.create(
            user_id=user_id,
            context_type=CodeContextType.DSA.value,
            context_id=problem_id,
            problem_id=problem_id,
            values=payload.model_dump(),
        )
        await self._snippets.session.commit()
        return self._to_response(snippet)

    async def create_for_topic(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        topic_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> CodeSnippetResponse:
        snippet = await self._snippets.create(
            user_id=user_id,
            context_type=context_type,
            context_id=str(topic_id),
            problem_id=None,
            values=payload,
        )
        await self._snippets.session.commit()
        return self._to_response(snippet)

    async def update(
        self,
        *,
        user_id: uuid.UUID,
        snippet_id: uuid.UUID,
        payload: CodeSnippetUpdate | dict[str, Any],
        expected_context: tuple[str, str] | None = None,
    ) -> CodeSnippetResponse:
        snippet = await self._snippets.get(user_id=user_id, snippet_id=snippet_id)

        if expected_context is not None:
            # Prevent a client from editing a snippet through the wrong resource path.
            context_type, context_id = expected_context
            if snippet.context_type != context_type or snippet.context_id != context_id:
                raise ValidationError("That code snippet belongs to a different resource.")

        values = (
            payload.model_dump(exclude_unset=True, exclude_none=True)
            if hasattr(payload, "model_dump")
            else {key: value for key, value in payload.items() if value is not None}
        )
        if not values:
            return self._to_response(snippet)

        updated = await self._snippets.update(snippet, values)
        await self._snippets.session.commit()
        return self._to_response(updated)

    async def delete(
        self,
        *,
        user_id: uuid.UUID,
        snippet_id: uuid.UUID,
        expected_context: tuple[str, str] | None = None,
    ) -> None:
        snippet = await self._snippets.get(user_id=user_id, snippet_id=snippet_id)

        if expected_context is not None:
            context_type, context_id = expected_context
            if snippet.context_type != context_type or snippet.context_id != context_id:
                raise ValidationError("That code snippet belongs to a different resource.")

        # Soft delete: an offline device must be able to learn about the removal on pull.
        await self._snippets.soft_delete(snippet)
        await self._snippets.session.commit()

    @staticmethod
    def _to_response(snippet: CodeSnippet) -> CodeSnippetResponse:
        return CodeSnippetResponse(
            id=snippet.id,
            user_id=snippet.user_id,
            created_at=snippet.created_at,
            updated_at=snippet.updated_at,
            version=snippet.version,
            context_type=snippet.context_type,
            context_id=snippet.context_id,
            problem_id=snippet.problem_id,
            title=snippet.title,
            language=snippet.language,
            code=snippet.code,
            is_primary=snippet.is_primary,
        )


__all__ = [
    "_ITEM_TYPE_NEW",
    "AttemptService",
    "CodeSnippetService",
    "NotesService",
    "ProgressService",
]

# Kept for symmetry with the plan builder.
_ITEM_TYPE_NEW = ItemType.DSA_NEW.value
