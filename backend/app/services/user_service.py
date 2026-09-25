"""Per-user settings and portable data export."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import UserSettings
from app.repositories.activity import ActivityRepository
from app.repositories.ai import AIConversationRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemAttemptRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.planning import DailyPlanRepository, RevisionRepository
from app.repositories.topics import HLDRepository, LLDRepository
from app.repositories.user import UserSettingsRepository
from app.schemas.settings import UserSettingsResponse, UserSettingsUpdate
from app.utils.datetime_utils import utcnow

logger = get_logger(__name__)

#: Defaults applied when a user has no settings row yet.
_FALLBACK_TIMEZONE = "UTC"


class SettingsService:
    def __init__(
        self,
        *,
        settings_repo: UserSettingsRepository,
        settings: Settings,
    ) -> None:
        self._repo = settings_repo
        self._settings = settings

    def _defaults(self, *, timezone: str | None = None) -> dict[str, Any]:
        return {
            "daily_dsa_count": self._settings.daily_dsa_count_default,
            "daily_revision_count": self._settings.revision_dsa_count_default,
            "include_lld_daily": True,
            "include_hld_daily": True,
            "revision_enabled": True,
            "ai_auto_reveal_solution": False,
            "timezone": timezone or self._settings.default_timezone or _FALLBACK_TIMEZONE,
            "preferred_languages": ["python"],
            "theme": "system",
        }

    async def get(
        self, *, user_id: uuid.UUID, timezone_hint: str | None = None
    ) -> UserSettingsResponse:
        """Read settings, creating them with defaults on first access.

        Creating a row on read makes the client's life simpler (no "not configured" state)
        and means a user who never touches the settings screen still has a well-defined
        timezone for the planner.
        """
        row = await self._repo.get(user_id=user_id)
        if row is None:
            row = await self._repo.upsert(
                user_id=user_id, values={}, defaults=self._defaults(timezone=timezone_hint)
            )
            await self._repo.session.commit()

        return self._to_response(row)

    async def update(
        self, *, user_id: uuid.UUID, payload: UserSettingsUpdate, timezone_hint: str | None = None
    ) -> UserSettingsResponse:
        """Merge-update settings.

        Only the supplied fields change, so a client sending just ``theme`` does not wipe
        the user's AI preferences.
        """
        values = payload.model_dump(exclude_unset=True, exclude_none=True)
        row = await self._repo.upsert(
            user_id=user_id, values=values, defaults=self._defaults(timezone=timezone_hint)
        )
        await self._repo.session.commit()
        return self._to_response(row)

    async def get_or_default(
        self, *, user_id: uuid.UUID, timezone_hint: str | None = None
    ) -> UserSettingsResponse:
        """Read without creating — used on hot paths that must not write."""
        row = await self._repo.get(user_id=user_id)
        if row is None:
            return UserSettingsResponse(
                id=uuid.UUID(int=0),
                user_id=user_id,
                created_at=utcnow(),
                updated_at=utcnow(),
                version=0,
                daily_dsa_count=self._settings.daily_dsa_count_default,
                daily_revision_count=self._settings.revision_dsa_count_default,
                include_lld_daily=True,
                include_hld_daily=True,
                revision_enabled=True,
                ai_auto_reveal_solution=False,
                timezone=timezone_hint or self._settings.default_timezone or _FALLBACK_TIMEZONE,
                preferred_languages=["python"],
                theme="system",
            )
        return self._to_response(row)

    @staticmethod
    def _to_response(row: UserSettings) -> UserSettingsResponse:
        return UserSettingsResponse(
            id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            version=row.version,
            daily_dsa_count=row.daily_dsa_count,
            daily_revision_count=row.daily_revision_count,
            include_lld_daily=row.include_lld_daily,
            include_hld_daily=row.include_hld_daily,
            daily_plan_preferences=row.daily_plan_preferences,
            revision_preferences=row.revision_preferences,
            revision_enabled=row.revision_enabled,
            ai_preferences=row.ai_preferences,
            ai_auto_reveal_solution=row.ai_auto_reveal_solution,
            timezone=row.timezone,
            preferred_languages=list(row.preferred_languages or []),
            theme=row.theme,
        )


class ExportService:
    """Produces the user's portable data dump.

    Everything returned belongs to the caller and is fetched with a ``user_id`` filter.
    Access tokens, refresh tokens, provider API keys and other users' data are never
    included — there is no code path here that could read them.
    """

    def __init__(
        self,
        *,
        progress_repo: ProblemProgressRepository,
        attempt_repo: ProblemAttemptRepository,
        notes_repo: ProblemNotesRepository,
        snippet_repo: CodeSnippetRepository,
        revision_repo: RevisionRepository,
        plan_repo: DailyPlanRepository,
        lld_repo: LLDRepository,
        hld_repo: HLDRepository,
        activity_repo: ActivityRepository,
        conversation_repo: AIConversationRepository,
        settings_repo: UserSettingsRepository,
        settings: Settings,
    ) -> None:
        self._progress = progress_repo
        self._attempts = attempt_repo
        self._notes = notes_repo
        self._snippets = snippet_repo
        self._revisions = revision_repo
        self._plans = plan_repo
        self._lld = lld_repo
        self._hld = hld_repo
        self._activity = activity_repo
        self._conversations = conversation_repo
        self._settings_repo = settings_repo
        self._settings = settings

    async def export_all(self, *, user_id: uuid.UUID, include_conversations: bool = True) -> dict[str, Any]:
        """Build the export payload."""
        limit = self._settings.export_max_rows

        progress_rows = await self._progress_rows(user_id=user_id, limit=limit)
        notes_rows = await self._notes_rows(user_id=user_id, limit=limit)
        snippet_rows = await self._snippet_rows(user_id=user_id, limit=limit)
        attempt_rows = await self._attempt_rows(user_id=user_id, limit=limit)
        revision_rows = await self._revision_rows(user_id=user_id, limit=limit)
        plan_rows = await self._plan_rows(user_id=user_id, limit=limit)

        # ``_topic_rows`` already joins each topic to this user's progress and reports
        # status/confidence, so no separate progress query is needed here.
        lld_topics = await self._topic_rows(user_id=user_id, repo=self._lld, kind="lld")
        hld_topics = await self._topic_rows(user_id=user_id, repo=self._hld, kind="hld")

        activity_rows = await self._activity.list_days(user_id=user_id)
        settings_row = await self._settings_repo.get(user_id=user_id)

        payload: dict[str, Any] = {
            "exported_at": utcnow(),
            "user_id": user_id,
            "schema_version": 1,
            "problem_progress": progress_rows,
            "attempt_history": attempt_rows,
            "notes": notes_rows,
            "code_snippets": snippet_rows,
            "revisions": revision_rows,
            "daily_plans": plan_rows,
            "lld_topics": lld_topics,
            "lld_notes": await self._note_rows(user_id=user_id, repo=self._lld, kind="lld"),
            "hld_topics": hld_topics,
            "hld_notes": await self._note_rows(user_id=user_id, repo=self._hld, kind="hld"),
            "study_sessions": await self._session_rows(user_id=user_id, limit=limit),
            "activity": [
                {
                    "date": row.activity_date.isoformat(),
                    "activity_count": row.activity_count,
                    "study_minutes": row.study_minutes,
                    "problems_solved": row.problems_solved,
                    "problems_attempted": row.problems_attempted,
                    "revisions_completed": row.revisions_completed,
                    "is_active": row.is_active,
                }
                for row in activity_rows
            ],
            "settings": self._settings_row(settings_row),
        }

        if include_conversations:
            # Conversations are the user's own content, but can be large, so they are
            # optional and summarised rather than dumped message-by-message.
            conversations, _ = await self._conversations.list_for_user(
                user_id=user_id, limit=limit, offset=0
            )
            payload["ai_conversations"] = [
                {
                    "id": str(conversation.id),
                    "title": conversation.title,
                    "context_type": conversation.context_type,
                    "message_count": conversation.message_count,
                    "created_at": conversation.created_at.isoformat(),
                    "updated_at": conversation.updated_at.isoformat(),
                }
                for conversation, _ in conversations
            ]

        # Sanity assertions: nothing here may leak another user's rows or a secret.
        for key in ("problem_progress", "attempt_history", "notes", "code_snippets", "revisions"):
            for row in payload.get(key, []):
                assert str(row.get("user_id")) == str(user_id), (key, "user_id mismatch")
                for forbidden in ("access_token", "refresh_token", "api_key", "password"):
                    assert forbidden not in row, (key, forbidden)

        logger.info(
            "Export generated",
            extra={
                "progress": len(progress_rows),
                "notes": len(notes_rows),
                "snippets": len(snippet_rows),
                "plans": len(plan_rows),
            },
        )

        return payload

    # ------------------------------------------------------------------ row builders
    @staticmethod
    def _iso(value: Any) -> Any:
        return value.isoformat() if hasattr(value, "isoformat") else value

    async def _progress_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        rows = await self._progress.list_solved_problem_ids(user_id=user_id)
        # The repository returns ids; fetch the full rows through the scheduler query path
        # so the export includes timestamps and counters, not just ids.
        from sqlalchemy import select

        from app.db.models import UserProblemProgress

        result = await self._progress.session.scalars(
            select(UserProblemProgress)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .limit(limit)
        )
        return [
            {
                "problem_id": row.problem_id,
                "user_id": str(row.user_id),
                "status": row.status,
                "attempts": row.attempts,
                "confidence": row.confidence,
                "revision_count": row.revision_count,
                "time_spent_minutes": row.time_spent_minutes,
                "is_favorite": row.is_favorite,
                "first_attempt_date": self._iso(row.first_attempt_date),
                "solved_date": self._iso(row.solved_date),
                "last_reviewed_date": self._iso(row.last_reviewed_date),
                "next_revision_date": self._iso(row.next_revision_date),
                "created_at": self._iso(row.created_at),
                "updated_at": self._iso(row.updated_at),
                "version": row.version,
            }
            for row in result.all()
        ][:limit] if rows is not None else []

    async def _attempt_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.db.models import ProblemAttempt

        result = await self._attempts.session.scalars(
            select(ProblemAttempt)
            .where(ProblemAttempt.user_id == user_id, ProblemAttempt.deleted_at.is_(None))
            .order_by(ProblemAttempt.started_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "problem_id": row.problem_id,
                "started_at": self._iso(row.started_at),
                "completed_at": self._iso(row.completed_at),
                "duration_minutes": row.duration_minutes,
                "outcome": row.outcome,
                "notes": row.notes,
            }
            for row in result.all()
        ]

    async def _notes_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        rows, _ = await self._notes.list_for_user(user_id=user_id, limit=limit, offset=0)
        return [
            {
                "problem_id": row.problem_id,
                "user_id": str(row.user_id),
                "approach": row.approach,
                "notes": row.notes,
                "mistakes": row.mistakes,
                "revision_notes": row.revision_notes,
                "time_complexity": row.time_complexity,
                "space_complexity": row.space_complexity,
                "updated_at": self._iso(row.updated_at),
                "version": row.version,
            }
            for row in rows
        ]

    async def _snippet_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.db.models import CodeSnippet

        result = await self._snippets.session.scalars(
            select(CodeSnippet)
            .where(CodeSnippet.user_id == user_id, CodeSnippet.deleted_at.is_(None))
            .limit(limit)
        )
        return [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "context_type": row.context_type,
                "context_id": row.context_id,
                "problem_id": row.problem_id,
                "title": row.title,
                "language": row.language,
                "code": row.code,
                "is_primary": row.is_primary,
                "created_at": self._iso(row.created_at),
                "updated_at": self._iso(row.updated_at),
                "version": row.version,
            }
            for row in result.all()
        ]

    async def _revision_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        rows, _ = await self._revisions.list_for_user(
            user_id=user_id, limit=limit, offset=0, completed=None
        )
        return [
            {
                "id": str(revision.id),
                "user_id": str(revision.user_id),
                "problem_id": revision.problem_id,
                "due_at": self._iso(revision.due_at),
                "reason": revision.reason,
                "priority": revision.priority,
                "completed": revision.completed,
                "completed_at": self._iso(revision.completed_at),
                "result": revision.result,
                "interval_days": revision.interval_days,
                "notes": revision.notes,
            }
            for revision, _problem in rows
        ]

    async def _plan_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        plans, _ = await self._plans.list_plans(user_id=user_id, limit=limit, offset=0)
        return [
            {
                "id": str(plan.id),
                "user_id": str(plan.user_id),
                "date_key": plan.date_key.isoformat(),
                "timezone": plan.timezone,
                "status": plan.status,
                "problem_ids": list(plan.problem_ids or []),
                "items": [
                    {
                        "item_type": item.item_type,
                        "position": item.position,
                        "problem_id": item.problem_id,
                        "title": item.title,
                        "is_completed": item.is_completed,
                        "completed_at": self._iso(item.completed_at),
                    }
                    for item in plan.items
                ],
            }
            for plan in plans
        ]

    async def _topic_rows(self, *, user_id: uuid.UUID, repo: Any, kind: str) -> list[dict[str, Any]]:
        progress_map = await repo.list_progress_map(user_id=user_id)
        rows, _ = await repo.list_with_progress(user_id=user_id, limit=1000, offset=0)
        fk = "lld_topic_id" if kind == "lld" else "hld_topic_id"
        return [
            {
                "topic_id": str(topic.id),
                "title": topic.title,
                "slug": topic.slug,
                "category": topic.category,
                "status": (
                    progress_map[topic.id].status
                    if topic.id in progress_map
                    else "not_started"
                ),
                "confidence": (
                    getattr(progress_map[topic.id], "confidence", None)
                    if topic.id in progress_map
                    else None
                ),
                "topic_key": fk,
            }
            for topic, _progress in rows
        ]

    async def _note_rows(self, *, user_id: uuid.UUID, repo: Any, kind: str) -> list[dict[str, Any]]:
        progress_map = await repo.list_progress_map(user_id=user_id)
        rows: list[dict[str, Any]] = []
        for topic_id in progress_map:
            notes = await repo.get_notes(user_id=user_id, topic_id=topic_id)
            if notes is None:
                continue
            data = notes.to_dict()
            data["user_id"] = str(notes.user_id)
            rows.append({key: self._iso(value) for key, value in data.items()})
        return rows

    async def _session_rows(self, *, user_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from app.db.models import StudySession

        result = await self._activity.session.scalars(
            select(StudySession)
            .where(StudySession.user_id == user_id, StudySession.deleted_at.is_(None))
            .order_by(StudySession.started_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "session_type": row.session_type,
                "context_id": row.context_id,
                "context_label": row.context_label,
                "started_at": self._iso(row.started_at),
                "ended_at": self._iso(row.ended_at),
                "duration_minutes": row.duration_minutes,
                "note": row.note,
            }
            for row in result.all()
        ]

    @staticmethod
    def _settings_row(row: UserSettings | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "daily_dsa_count": row.daily_dsa_count,
            "daily_revision_count": row.daily_revision_count,
            "include_lld_daily": row.include_lld_daily,
            "include_hld_daily": row.include_hld_daily,
            "revision_enabled": row.revision_enabled,
            "ai_auto_reveal_solution": row.ai_auto_reveal_solution,
            "timezone": row.timezone,
            "preferred_languages": list(row.preferred_languages or []),
            "theme": row.theme,
        }


__all__ = ["ExportService", "SettingsService"]
