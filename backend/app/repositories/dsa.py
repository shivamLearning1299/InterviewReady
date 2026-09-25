"""User-owned DSA data repositories: progress, attempts, notes, code snippets.

Every method here takes ``user_id`` and filters on it. The upsert helpers bump ``version``
so the offline sync protocol always sees a monotonic counter.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AttemptNotFoundError, SnippetNotFoundError
from app.db.models import CodeSnippet, ProblemAttempt, ProblemNote, UserProblemProgress
from app.utils.datetime_utils import utcnow

# Both helpers are used: `upsert_returning` for the hot paths and
# `build_upsert_statement` for the two methods that need to customise the statement.
from app.utils.upsert import IMMUTABLE_COLUMNS, build_upsert_statement, upsert_returning


class ProblemProgressRepository:
    """CRUD for ``user_problem_progress``, always scoped to one user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> UserProblemProgress | None:
        return await self.session.scalar(
            select(UserProblemProgress).where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.problem_id == problem_id,
                UserProblemProgress.deleted_at.is_(None),
            )
        )

    async def get_by_problem_ids(
        self, *, user_id: uuid.UUID, problem_ids: list[str]
    ) -> dict[str, UserProblemProgress]:
        """Batch fetch, keyed by problem id. Avoids a query per problem."""
        if not problem_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(UserProblemProgress).where(
                    UserProblemProgress.user_id == user_id,
                    UserProblemProgress.problem_id.in_(problem_ids),
                    UserProblemProgress.deleted_at.is_(None),
                )
            )
        ).all()
        return {row.problem_id: row for row in rows}

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        values: dict[str, Any],
        conflict_columns: list[str] | None = None,
        preserve_columns: set[str] | None = None,
    ) -> UserProblemProgress:
        """UPSERT a progress row, bumping ``version`` on the update path.

        Routed through :func:`upsert_returning` so the returned instance is refreshed with
        ``populate_existing``. Building the statement directly here meant a session that had
        already loaded the row got the **pre-upsert** object back from the identity map — a
        stale ``version`` and stale field values — even though the row on disk had been
        updated. The sync service's optimistic-concurrency check reads that ``version``, so
        the conflict was missed and a stale write was reported as applied.

        ``preserve_columns`` names columns that must satisfy the INSERT — PostgreSQL
        validates NOT NULL on the proposed row before ``ON CONFLICT`` — but must not
        overwrite an existing value. Defaults injected for other NOT NULL columns are
        excluded automatically, so a partial payload cannot reset stored data.
        """
        keys = conflict_columns or ["user_id", "problem_id"]
        payload: dict[str, Any] = {
            "user_id": user_id,
            "problem_id": problem_id,
            **values,
        }

        # Computed from the caller's own keys only, so a server default injected for the
        # insert path can never make it into the DO UPDATE clause.
        skip = set(preserve_columns or ())
        update_columns = [
            key for key in payload if key not in IMMUTABLE_COLUMNS and key not in keys and key not in skip
        ]

        return await upsert_returning(
            self.session,
            UserProblemProgress,
            payload,
            conflict_columns=keys,
            update_columns=update_columns,
        )

    async def increment_time(
        self, *, user_id: uuid.UUID, problem_id: str, minutes: int
    ) -> None:
        """Atomically add study minutes without a read-modify-write race."""
        if minutes <= 0:
            return
        await self.session.execute(
            update(UserProblemProgress)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.problem_id == problem_id,
            )
            .values(
                total_time_spent_minutes=UserProblemProgress.total_time_spent_minutes + minutes,
                version=UserProblemProgress.version + 1,
                updated_at=func.now(),
            )
        )

    async def list_due_revisions(
        self,
        *,
        user_id: uuid.UUID,
        before: datetime,
        limit: int | None = None,
    ) -> list[UserProblemProgress]:
        """Problems whose scheduled revision date has arrived.

        Uses ``next_revision_date`` — the pre-existing column name in
        ``user_problem_progress`` (the LLD/HLD tables use ``next_revision_at``, but this
        legacy table predates them).
        """
        stmt = (
            select(UserProblemProgress)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
                UserProblemProgress.next_revision_date.is_not(None),
                UserProblemProgress.next_revision_date <= before,
            )
            .order_by(UserProblemProgress.next_revision_date.asc())
        )
        if limit:
            stmt = stmt.limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def list_solved_problem_ids(self, *, user_id: uuid.UUID) -> set[str]:
        """Ids of every problem this user has solved or mastered."""
        stmt = select(UserProblemProgress.problem_id).where(
            UserProblemProgress.user_id == user_id,
            UserProblemProgress.deleted_at.is_(None),
            UserProblemProgress.status.in_(("solved", "mastered")),
        )
        return set((await self.session.scalars(stmt)).all())

    async def count_by_status(self, *, user_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(UserProblemProgress.status, func.count())
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .group_by(UserProblemProgress.status)
        )
        return {status: int(count) for status, count in (await self.session.execute(stmt)).all()}

    async def recent_activity_dates(
        self, *, user_id: uuid.UUID, limit: int = 30
    ) -> list[datetime]:
        """Most recent progress updates — used by the planner to weight recent work."""
        stmt = (
            select(UserProblemProgress.updated_at)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .order_by(UserProblemProgress.updated_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def topic_performance(self, *, user_id: uuid.UUID) -> dict[str, dict[str, float]]:
        """Per-topic attempt/confidence aggregates for weak-topic detection.

        Aggregated in SQL rather than in Python so the planner can call it on every
        ``/today`` request without pulling the user's whole history over the wire.
        """
        from app.db.models import DSAProblem

        stmt = (
            select(
                DSAProblem.primary_topic,
                func.count(UserProblemProgress.id),
                func.avg(UserProblemProgress.confidence),
                func.sum(UserProblemProgress.attempts),
            )
            .join(DSAProblem, DSAProblem.id == UserProblemProgress.problem_id)
            .where(
                UserProblemProgress.user_id == user_id,
                UserProblemProgress.deleted_at.is_(None),
            )
            .group_by(DSAProblem.primary_topic)
        )
        result: dict[str, dict[str, float]] = {}
        for topic, count, avg_confidence, attempts in (await self.session.execute(stmt)).all():
            result[topic] = {
                "interacted": float(count or 0),
                "average_confidence": float(avg_confidence or 0.0),
                "total_attempts": float(attempts or 0),
            }
        return result


class ProblemAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_problem(
        self,
        *,
        user_id: uuid.UUID,
        problem_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ProblemAttempt], int]:
        base = select(ProblemAttempt).where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.problem_id == problem_id,
            ProblemAttempt.deleted_at.is_(None),
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )
        stmt = base.order_by(ProblemAttempt.started_at.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all()), total

    async def list_for_problems(
        self,
        *,
        user_id: uuid.UUID,
        problem_ids: list[str],
        per_problem_limit: int = 5,
    ) -> dict[uuid.UUID, list[ProblemAttempt]]:
        """Batch fetch recent attempts grouped by problem (detail screen aggregation)."""
        if not problem_ids:
            return {}
        stmt = (
            select(ProblemAttempt)
            .where(
                ProblemAttempt.user_id == user_id,
                ProblemAttempt.problem_id.in_(problem_ids),
                ProblemAttempt.deleted_at.is_(None),
            )
            .order_by(ProblemAttempt.problem_id, ProblemAttempt.started_at.desc())
        )
        grouped: dict[uuid.UUID, list[ProblemAttempt]] = {}
        for attempt in (await self.session.scalars(stmt)).all():
            bucket = grouped.setdefault(attempt.problem_id, [])
            if len(bucket) < per_problem_limit:
                bucket.append(attempt)
        return grouped

    async def get(
        self, *, user_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> ProblemAttempt:
        attempt = await self.session.scalar(
            select(ProblemAttempt).where(
                ProblemAttempt.id == attempt_id,
                ProblemAttempt.user_id == user_id,
                ProblemAttempt.deleted_at.is_(None),
            )
        )
        if attempt is None:
            raise AttemptNotFoundError()
        return attempt

    async def create(
        self, *, user_id: uuid.UUID, problem_id: str, values: dict[str, Any]
    ) -> ProblemAttempt:
        attempt = ProblemAttempt(user_id=user_id, problem_id=problem_id, **values)
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def update(self, attempt: ProblemAttempt, values: dict[str, Any]) -> ProblemAttempt:
        for key, value in values.items():
            setattr(attempt, key, value)
        attempt.version = (attempt.version or 1) + 1
        attempt.updated_at = utcnow()
        await self.session.flush()
        return attempt

    async def count_for_problem(
        self, *, user_id: uuid.UUID, problem_id: str
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    ProblemAttempt.user_id == user_id,
                    ProblemAttempt.problem_id == problem_id,
                    ProblemAttempt.deleted_at.is_(None),
                )
            )
            or 0
        )

    async def outcome_counts(
        self, *, user_id: uuid.UUID, since: datetime | None = None
    ) -> dict[str, int]:
        stmt = select(ProblemAttempt.outcome, func.count()).where(
            ProblemAttempt.user_id == user_id,
            ProblemAttempt.deleted_at.is_(None),
        )
        if since:
            stmt = stmt.where(ProblemAttempt.started_at >= since)
        stmt = stmt.group_by(ProblemAttempt.outcome)
        return {
            (outcome or "unknown"): int(count)
            for outcome, count in (await self.session.execute(stmt)).all()
        }


class ProblemNotesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, user_id: uuid.UUID, problem_id: str) -> ProblemNote | None:
        return await self.session.scalar(
            select(ProblemNote).where(
                ProblemNote.user_id == user_id,
                ProblemNote.problem_id == problem_id,
                ProblemNote.deleted_at.is_(None),
            )
        )

    async def upsert(
        self, *, user_id: uuid.UUID, problem_id: str, values: dict[str, Any]
    ) -> ProblemNote:
        payload = {"user_id": user_id, "problem_id": problem_id, **values}
        stmt = build_upsert_statement(
            ProblemNote, payload, conflict_columns=["user_id", "problem_id"]
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def list_for_user(
        self, *, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[ProblemNote], int]:
        base = select(ProblemNote).where(
            ProblemNote.user_id == user_id, ProblemNote.deleted_at.is_(None)
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )
        stmt = base.order_by(ProblemNote.updated_at.desc()).limit(limit).offset(offset)
        return list((await self.session.scalars(stmt)).all()), total


class CodeSnippetRepository:
    """Snippets for DSA, LLD and HLD, discriminated by ``context_type``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scoped(
        self, *, user_id: uuid.UUID, context_type: str, context_id: str
    ) -> Select[Any]:
        return select(CodeSnippet).where(
            CodeSnippet.user_id == user_id,
            CodeSnippet.context_type == context_type,
            CodeSnippet.context_id == context_id,
            CodeSnippet.deleted_at.is_(None),
        )

    async def list_for_context(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        context_id: str,
    ) -> list[CodeSnippet]:
        stmt = self._scoped(
            user_id=user_id, context_type=context_type, context_id=context_id
        ).order_by(CodeSnippet.is_primary.desc(), CodeSnippet.created_at.asc())
        return list((await self.session.scalars(stmt)).all())

    async def get(
        self, *, user_id: uuid.UUID, snippet_id: uuid.UUID
    ) -> CodeSnippet:
        snippet = await self.session.scalar(
            select(CodeSnippet).where(
                CodeSnippet.id == snippet_id,
                CodeSnippet.user_id == user_id,
                CodeSnippet.deleted_at.is_(None),
            )
        )
        if snippet is None:
            raise SnippetNotFoundError()
        return snippet

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        context_id: str,
        problem_id: str | None,
        values: dict[str, Any],
    ) -> CodeSnippet:
        # Only one snippet per context may be flagged primary.
        if values.get("is_primary"):
            await self._clear_primary(user_id=user_id, context_type=context_type, context_id=context_id)

        snippet = CodeSnippet(
            user_id=user_id,
            context_type=context_type,
            context_id=context_id,
            problem_id=problem_id,
            **values,
        )
        self.session.add(snippet)
        await self.session.flush()
        return snippet

    async def update(self, snippet: CodeSnippet, values: dict[str, Any]) -> CodeSnippet:
        if values.get("is_primary"):
            await self._clear_primary(
                user_id=snippet.user_id,
                context_type=snippet.context_type,
                context_id=snippet.context_id,
                exclude_id=snippet.id,
            )
        for key, value in values.items():
            setattr(snippet, key, value)
        snippet.version = (snippet.version or 1) + 1
        snippet.updated_at = utcnow()
        await self.session.flush()
        return snippet

    async def soft_delete(self, snippet: CodeSnippet) -> None:
        """Tombstone rather than hard-delete so offline clients learn about the removal."""
        snippet.deleted_at = utcnow()
        snippet.version = (snippet.version or 1) + 1
        await self.session.flush()

    async def _clear_primary(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        context_id: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        stmt = (
            update(CodeSnippet)
            .where(
                CodeSnippet.user_id == user_id,
                CodeSnippet.context_type == context_type,
                CodeSnippet.context_id == context_id,
                CodeSnippet.is_primary.is_(True),
            )
            .values(is_primary=False, updated_at=func.now())
        )
        if exclude_id:
            stmt = stmt.where(CodeSnippet.id != exclude_id)
        await self.session.execute(stmt)

    async def upsert_by_id(
        self,
        *,
        user_id: uuid.UUID,
        snippet_id: uuid.UUID,
        values: dict[str, Any],
    ) -> CodeSnippet:
        """Sync-path upsert keyed on the client-supplied id."""
        payload = {"id": snippet_id, "user_id": user_id, **values}
        stmt = build_upsert_statement(
            CodeSnippet, payload, conflict_columns=["id"], increment_version=True
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def soft_delete_by_id(self, *, user_id: uuid.UUID, snippet_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            update(CodeSnippet)
            .where(
                CodeSnippet.id == snippet_id,
                CodeSnippet.user_id == user_id,
                CodeSnippet.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), version=CodeSnippet.version + 1, updated_at=func.now())
        )
        return bool(result.rowcount)
