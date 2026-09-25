"""LLD and HLD curriculum services.

Both areas share the same three concerns — progress, notes and code — so the logic lives in
one generic service parameterised by the repository, and the two public services differ
only in which repository and note schema they bind.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Generic, TypeVar

from app.core.config import Settings
from app.core.constants import CodeContextType, TopicStatus
from app.core.logging import get_logger
from app.repositories.dsa import CodeSnippetRepository
from app.repositories.topics import HLDRepository, LLDRepository
from app.schemas.hld import (
    HLDCodeSnippetResponse,
    HLDTopicDetail,
    HLDTopicSummary,
)
from app.schemas.lld import (
    LLDCodeSnippetResponse,
    LLDTopicDetail,
    LLDTopicSummary,
)
from app.services.activity_service import ActivityService
from app.services.revision_policy import RevisionPolicy
from app.utils.datetime_utils import utcnow

logger = get_logger(__name__)

Repo = TypeVar("Repo")

#: Statuses that mean the topic is done for progress-bar purposes.
_COMPLETED_STATUSES = (TopicStatus.COMPLETED.value, TopicStatus.MASTERED.value)


class TopicService(Generic[Repo]):
    """Shared progress/notes/code logic for one curriculum."""

    context_type: str = CodeContextType.LLD.value

    def __init__(
        self,
        *,
        repo: Repo,
        snippet_repo: CodeSnippetRepository,
        activity_service: ActivityService,
        revision_policy: RevisionPolicy,
        settings: Settings,
    ) -> None:
        self._repo = repo  # type: ignore[assignment]
        self._snippets = snippet_repo
        self._activity = activity_service
        self._policy = revision_policy
        self._settings = settings

    # ----------------------------------------------------------------------- list
    async def list_topics(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        search: str | None = None,
        category: str | None = None,
        status: str | None = None,
        is_active: bool | None = True,
        order_by: str = "curriculum",
    ) -> tuple[list[Any], int]:
        rows, total = await self._repo.list_with_progress(
            user_id=user_id,
            limit=limit,
            offset=offset,
            search=search,
            category=category,
            status=status,
            is_active=is_active,
            order_by=order_by,
        )
        return [self._to_summary(topic, progress) for topic, progress in rows], total

    async def get_detail(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID
    ) -> Any:
        topic, progress = await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)
        notes = await self._repo.get_notes(user_id=user_id, topic_id=topic_id)
        snippets = await self._snippets.list_for_context(
            user_id=user_id, context_type=self.context_type, context_id=str(topic_id)
        )

        detail = self._to_detail(topic, progress)
        detail.notes = self._notes_response(notes) if notes else None
        detail.code_snippets = [self._snippet_response(snippet) for snippet in snippets]
        return detail

    # ------------------------------------------------------------------- progress
    async def update_progress(
        self,
        *,
        user_id: uuid.UUID,
        topic_id: uuid.UUID,
        payload: Any,
        timezone: str | None = None,
    ) -> Any:
        """Upsert topic progress, deriving dates from the status transition."""
        # Ensures the topic exists and belongs to the active curriculum.
        await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)

        existing = await self._repo.get_progress(user_id=user_id, topic_id=topic_id)
        now = utcnow()
        values: dict[str, Any] = {}

        if payload.status is not None:
            status = payload.status.value if hasattr(payload.status, "value") else payload.status
            values["status"] = status
            # `lld_progress`/`hld_progress` name this column `last_reviewed_at`. The legacy
            # `user_problem_progress` table uses `last_reviewed_date`, so the two are easy to
            # confuse — passing the wrong name raises "Unconsumed column names".
            values["last_reviewed_at"] = now

            if status in _COMPLETED_STATUSES:
                if existing is None or getattr(existing, "completed_at", None) is None:
                    values["completed_at"] = now
                confidence = payload.confidence if payload.confidence is not None else (
                    existing.confidence if existing else None
                )
                schedule = self._policy.schedule_after_solve(confidence=confidence, from_time=now)
                values["next_revision_at"] = schedule.due_at
            elif status == TopicStatus.NEEDS_REVISION.value:
                values["next_revision_at"] = now + timedelta(days=1)
            elif status == TopicStatus.NOT_STARTED.value:
                values["completed_at"] = None
                values["next_revision_at"] = None

        if payload.confidence is not None:
            values["confidence"] = payload.confidence

        if payload.time_spent_minutes is not None:
            prior = getattr(existing, "total_time_spent_minutes", 0) if existing else 0
            values["total_time_spent_minutes"] = prior + max(0, payload.time_spent_minutes)

        if payload.schedule_revision and existing is not None:
            confidence = payload.confidence if payload.confidence is not None else existing.confidence
            schedule = self._policy.schedule_after_solve(confidence=confidence, from_time=now)
            values["next_revision_at"] = schedule.due_at

        if not values:
            if existing is not None:
                return self._progress_response(existing)
            values = {"status": TopicStatus.NOT_STARTED.value}

        row = await self._repo.upsert_progress(user_id=user_id, topic_id=topic_id, values=values)

        if values.get("status") in _COMPLETED_STATUSES:
            await self._activity.record(
                user_id=user_id,
                timezone=timezone,
                activity_count=1,
                topics_completed=1,
            )

        await self._repo.session.commit()
        return self._progress_response(row)

    # ---------------------------------------------------------------------- notes
    async def get_notes(self, *, user_id: uuid.UUID, topic_id: uuid.UUID) -> Any | None:
        await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)
        notes = await self._repo.get_notes(user_id=user_id, topic_id=topic_id)
        return self._notes_response(notes) if notes else None

    async def upsert_notes(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, payload: Any
    ) -> Any:
        await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)

        values = payload.model_dump(exclude_unset=True)
        notes = await self._repo.upsert_notes(
            user_id=user_id, topic_id=topic_id, values=values
        )
        await self._repo.session.commit()
        return self._notes_response(notes)

    # ----------------------------------------------------------------------- code
    async def list_code(self, *, user_id: uuid.UUID, topic_id: uuid.UUID) -> list[Any]:
        await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)
        snippets = await self._snippets.list_for_context(
            user_id=user_id, context_type=self.context_type, context_id=str(topic_id)
        )
        return [self._snippet_response(snippet) for snippet in snippets]

    async def create_code(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, payload: Any
    ) -> Any:
        await self._repo.get_with_progress(user_id=user_id, topic_id=topic_id)
        snippet = await self._snippets.create(
            user_id=user_id,
            context_type=self.context_type,
            context_id=str(topic_id),
            problem_id=None,
            values=payload.model_dump(),
        )
        await self._snippets.session.commit()
        return self._snippet_response(snippet)

    async def update_code(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, snippet_id: uuid.UUID, payload: Any
    ) -> Any:
        snippet = await self._snippets.get(user_id=user_id, snippet_id=snippet_id)
        if snippet.context_type != self.context_type or snippet.context_id != str(topic_id):
            from app.core.exceptions import ValidationError

            raise ValidationError("That code snippet belongs to a different topic.")

        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not values:
            return self._snippet_response(snippet)

        updated = await self._snippets.update(snippet, values)
        await self._snippets.session.commit()
        return self._snippet_response(updated)

    async def delete_code(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, snippet_id: uuid.UUID
    ) -> None:
        snippet = await self._snippets.get(user_id=user_id, snippet_id=snippet_id)
        if snippet.context_type != self.context_type or snippet.context_id != str(topic_id):
            from app.core.exceptions import ValidationError

            raise ValidationError("That code snippet belongs to a different topic.")

        await self._snippets.soft_delete(snippet)
        await self._snippets.session.commit()

    # -------------------------------------------------------------------- mapping
    # Overridden by the concrete subclasses; kept abstract-ish so a missing override is a
    # clear AttributeError rather than a silently wrong response shape.
    def _to_summary(self, topic: Any, progress: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _to_detail(self, topic: Any, progress: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _notes_response(self, notes: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _progress_response(self, progress: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _snippet_response(self, snippet: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

class LLDService(TopicService[LLDRepository]):
    context_type = CodeContextType.LLD.value

    def _to_summary(self, topic: Any, progress: Any) -> LLDTopicSummary:
        from app.schemas.lld import LLDProgressSummary

        return LLDTopicSummary(
            id=topic.id,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
            version=getattr(topic, "version", 1),
            title=topic.title,
            slug=topic.slug,
            category=topic.category,
            description=topic.description,
            difficulty=topic.difficulty,
            estimated_minutes=topic.estimated_minutes,
            order_index=topic.order_index,
            is_active=topic.is_active,
            key_concepts=list(topic.key_concepts or []),
            progress=LLDProgressSummary(
                status=progress.status if progress else "not_started",
                confidence=progress.confidence if progress else None,
                completed_at=getattr(progress, "completed_at", None) if progress else None,
                next_revision_at=getattr(progress, "next_revision_at", None) if progress else None,
                last_reviewed_at=getattr(progress, "last_reviewed_at", None) if progress else None,
                total_time_spent_minutes=(
                    getattr(progress, "total_time_spent_minutes", 0) if progress else 0
                ),
            ),
        )

    def _to_detail(self, topic: Any, progress: Any) -> LLDTopicDetail:
        from app.schemas.lld import LLDProgressSummary

        return LLDTopicDetail(
            id=topic.id,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
            version=getattr(topic, "version", 1),
            title=topic.title,
            slug=topic.slug,
            category=topic.category,
            description=topic.description,
            learning_objectives=list(topic.learning_objectives or []),
            key_concepts=list(topic.key_concepts or []),
            external_url=topic.external_url,
            difficulty=topic.difficulty,
            estimated_minutes=topic.estimated_minutes,
            order_index=topic.order_index,
            is_active=topic.is_active,
            progress=(
                LLDProgressSummary(
                    status=progress.status,
                    confidence=progress.confidence,
                    completed_at=getattr(progress, "completed_at", None),
                    next_revision_at=getattr(progress, "next_revision_at", None),
                    last_reviewed_at=getattr(progress, "last_reviewed_at", None),
                    total_time_spent_minutes=getattr(progress, "total_time_spent_minutes", 0),
                )
                if progress
                else None
            ),
            notes=None,
            code_snippets=[],
        )

    def _notes_response(self, notes: Any) -> Any:
        from app.schemas.lld import LLDNotesResponse

        return LLDNotesResponse(
            id=notes.id,
            user_id=notes.user_id,
            created_at=notes.created_at,
            updated_at=notes.updated_at,
            version=notes.version,
            lld_topic_id=notes.lld_topic_id,
            summary=notes.summary,
            design_explanation=notes.design_explanation,
            class_responsibilities=notes.class_responsibilities,
            relationships=notes.relationships,
            design_notes=getattr(notes, "design_notes", None),
            mistakes=notes.mistakes,
            revision_notes=notes.revision_notes,
            patterns_used=list(notes.patterns_used or []),
            class_diagram=notes.class_diagram,
        )

    def _progress_response(self, progress: Any) -> Any:
        from app.schemas.lld import LLDProgressResponse

        return LLDProgressResponse(
            id=progress.id,
            user_id=progress.user_id,
            created_at=progress.created_at,
            updated_at=progress.updated_at,
            version=progress.version,
            lld_topic_id=progress.lld_topic_id,
            status=progress.status,
            confidence=progress.confidence,
            revision_count=progress.revision_count,
            last_reviewed_at=progress.last_reviewed_at,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            total_time_spent_minutes=progress.total_time_spent_minutes,
        )

    def _snippet_response(self, snippet: Any) -> LLDCodeSnippetResponse:
        return LLDCodeSnippetResponse(
            id=snippet.id,
            user_id=snippet.user_id,
            created_at=snippet.created_at,
            updated_at=snippet.updated_at,
            version=snippet.version,
            context_type=snippet.context_type,
            context_id=snippet.context_id,
            title=snippet.title,
            language=snippet.language,
            code=snippet.code,
            is_primary=snippet.is_primary,
        )


class HLDService(TopicService[HLDRepository]):
    context_type = CodeContextType.HLD.value

    def _to_summary(self, topic: Any, progress: Any) -> HLDTopicSummary:
        from app.schemas.hld import HLDProgressSummary

        return HLDTopicSummary(
            id=topic.id,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
            version=getattr(topic, "version", 1),
            title=topic.title,
            slug=topic.slug,
            category=topic.category,
            description=topic.description,
            difficulty=topic.difficulty,
            estimated_minutes=topic.estimated_minutes,
            order_index=topic.order_index,
            is_active=topic.is_active,
            key_concepts=list(topic.key_concepts or []),
            progress=HLDProgressSummary(
                status=progress.status if progress else "not_started",
                confidence=progress.confidence if progress else None,
                completed_at=getattr(progress, "completed_at", None) if progress else None,
                next_revision_at=getattr(progress, "next_revision_at", None) if progress else None,
                last_reviewed_at=getattr(progress, "last_reviewed_at", None) if progress else None,
                total_time_spent_minutes=(
                    getattr(progress, "total_time_spent_minutes", 0) if progress else 0
                ),
            ),
        )

    def _to_detail(self, topic: Any, progress: Any) -> HLDTopicDetail:
        from app.schemas.hld import HLDProgressSummary

        return HLDTopicDetail(
            id=topic.id,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
            version=getattr(topic, "version", 1),
            title=topic.title,
            slug=topic.slug,
            category=topic.category,
            description=topic.description,
            learning_objectives=list(topic.learning_objectives or []),
            key_concepts=list(topic.key_concepts or []),
            external_url=topic.external_url,
            difficulty=topic.difficulty,
            estimated_minutes=topic.estimated_minutes,
            order_index=topic.order_index,
            is_active=topic.is_active,
            progress=(
                HLDProgressSummary(
                    status=progress.status,
                    confidence=progress.confidence,
                    completed_at=getattr(progress, "completed_at", None),
                    next_revision_at=getattr(progress, "next_revision_at", None),
                    last_reviewed_at=getattr(progress, "last_reviewed_at", None),
                    total_time_spent_minutes=getattr(progress, "total_time_spent_minutes", 0),
                )
                if progress
                else None
            ),
            notes=None,
            code_snippets=[],
        )

    def _notes_response(self, notes: Any) -> Any:
        from app.schemas.hld import HLDNotesResponse

        return HLDNotesResponse(
            id=notes.id,
            user_id=notes.user_id,
            created_at=notes.created_at,
            updated_at=notes.updated_at,
            version=notes.version,
            hld_topic_id=notes.hld_topic_id,
            functional_requirements=notes.functional_requirements,
            non_functional_requirements=notes.non_functional_requirements,
            capacity_estimation=notes.capacity_estimation,
            apis=notes.apis,
            data_model=notes.data_model,
            high_level_architecture=notes.high_level_architecture,
            database_choice=notes.database_choice,
            caching=notes.caching,
            queues=notes.queues,
            scaling=notes.scaling,
            failure_handling=notes.failure_handling,
            tradeoffs=notes.tradeoffs,
            final_notes=notes.final_notes,
            interview_notes=getattr(notes, "interview_notes", None),
            mistakes=getattr(notes, "mistakes", None),
        )

    def _progress_response(self, progress: Any) -> Any:
        from app.schemas.hld import HLDProgressResponse

        return HLDProgressResponse(
            id=progress.id,
            user_id=progress.user_id,
            created_at=progress.created_at,
            updated_at=progress.updated_at,
            version=progress.version,
            hld_topic_id=progress.hld_topic_id,
            status=progress.status,
            confidence=progress.confidence,
            revision_count=progress.revision_count,
            last_reviewed_at=progress.last_reviewed_at,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            total_time_spent_minutes=progress.total_time_spent_minutes,
        )

    def _snippet_response(self, snippet: Any) -> HLDCodeSnippetResponse:
        return HLDCodeSnippetResponse(
            id=snippet.id,
            user_id=snippet.user_id,
            created_at=snippet.created_at,
            updated_at=snippet.updated_at,
            version=snippet.version,
            context_type=snippet.context_type,
            context_id=snippet.context_id,
            title=snippet.title,
            language=snippet.language,
            code=snippet.code,
            is_primary=snippet.is_primary,
        )


__all__ = ["HLDService", "LLDService", "TopicService"]
