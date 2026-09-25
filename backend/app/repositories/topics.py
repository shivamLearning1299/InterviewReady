"""LLD and HLD curriculum repositories.

Both curricula share the same shape — a catalog of topics plus per-user progress, notes
and code — so the query logic lives in shared helpers and the two public repositories
differ only in the models they bind.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import TopicNotFoundError
from app.db.models import HLDNote, HLDProgress, HLDTopic, LLDNote, LLDProgress, LLDTopic
from app.utils.upsert import build_upsert_statement

TopicT = TypeVar("TopicT")
ProgressT = TypeVar("ProgressT")
NoteT = TypeVar("NoteT")


class TopicCommonRepository(Generic[TopicT, ProgressT, NoteT]):
    """Shared implementation for the LLD and HLD curricula."""

    topic_model: type[TopicT]
    progress_model: type[ProgressT]
    note_model: type[NoteT]
    #: Name of the FK column on the progress/notes table, e.g. ``lld_topic_id``.
    topic_fk: str

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------------------------------------------------- catalog
    def _joined_select(self, user_id: uuid.UUID) -> Any:
        """Catalog rows LEFT JOINed to this user's progress.

        One row per topic, so listing 50 topics is a single round trip.
        """
        progress = aliased(self.progress_model)
        # Resolve the FK off the *alias*, not the base class. Using the unaliased model here
        # emits an ON clause that references ``lld_progress`` while the FROM clause uses the
        # ``lld_progress_1`` alias, which PostgreSQL rejects outright.
        topic_fk = getattr(progress, self.topic_fk)
        join_condition = and_(
            topic_fk == self.topic_model.id,
            progress.user_id == user_id,
            progress.deleted_at.is_(None),
        )
        return select(self.topic_model, progress).outerjoin(progress, join_condition)

    async def list_with_progress(
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
    ) -> tuple[list[tuple[Any, Any]], int]:
        base = self._joined_select(user_id)
        progress_entity = base.selected_columns[1]

        conditions: list[Any] = []
        if is_active is not None:
            conditions.append(self.topic_model.is_active.is_(is_active))

        if search:
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(self.topic_model.title).like(term),
                    func.lower(self.topic_model.slug).like(term),
                    func.lower(func.coalesce(self.topic_model.description, "")).like(
                        term
                    ),
                )
            )

        if category:
            normalized = category.value if hasattr(category, "value") else category
            conditions.append(self.topic_model.category == normalized)

        if status:
            normalized = status.value if hasattr(status, "value") else status
            if normalized == "not_started":
                conditions.append(
                    or_(progress_entity.id.is_(None), progress_entity.status == "not_started")
                )
            else:
                conditions.append(progress_entity.status == normalized)

        if conditions:
            base = base.where(*conditions)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )

        if order_by == "category":
            ordering = [
                self.topic_model.category.asc(),
                self.topic_model.order_index.asc(),
            ]
        elif order_by == "title":
            ordering = [self.topic_model.title.asc()]
        elif order_by == "recent":
            ordering = [
                progress_entity.updated_at.desc().nullslast(),
                self.topic_model.order_index.asc(),
            ]
        else:
            ordering = [self.topic_model.order_index.asc()]

        stmt = base.order_by(*ordering).limit(limit).offset(offset)
        rows = [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]
        return rows, total

    async def get_with_progress(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID
    ) -> tuple[Any, Any]:
        stmt = (
            self._joined_select(user_id)
            .where(self.topic_model.id == topic_id)
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise TopicNotFoundError()
        return row[0], row[1]

    async def list_all_topic_ids(self, *, active_only: bool = True) -> list[uuid.UUID]:
        stmt = select(self.topic_model.id)
        if active_only:
            stmt = stmt.where(self.topic_model.is_active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    # -------------------------------------------------------------------- progress
    async def get_progress(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID
    ) -> Any | None:
        return await self.session.scalar(
            select(self.progress_model).where(
                self.progress_model.user_id == user_id,
                getattr(self.progress_model, self.topic_fk) == topic_id,
                self.progress_model.deleted_at.is_(None),
            )
        )

    async def upsert_progress(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, values: dict[str, Any]
    ) -> Any:
        payload = {"user_id": user_id, self.topic_fk: topic_id, **values}
        stmt = build_upsert_statement(
            self.progress_model,
            payload,
            conflict_columns=["user_id", self.topic_fk],
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def list_progress_map(
        self, *, user_id: uuid.UUID
    ) -> dict[uuid.UUID, Any]:
        rows = (
            await self.session.scalars(
                select(self.progress_model).where(
                    self.progress_model.user_id == user_id,
                    self.progress_model.deleted_at.is_(None),
                )
            )
        ).all()
        return {getattr(row, self.topic_fk): row for row in rows}

    # ----------------------------------------------------------------------- notes
    async def get_notes(self, *, user_id: uuid.UUID, topic_id: uuid.UUID) -> Any | None:
        return await self.session.scalar(
            select(self.note_model).where(
                self.note_model.user_id == user_id,
                getattr(self.note_model, self.topic_fk) == topic_id,
                self.note_model.deleted_at.is_(None),
            )
        )

    async def upsert_notes(
        self, *, user_id: uuid.UUID, topic_id: uuid.UUID, values: dict[str, Any]
    ) -> Any:
        payload = {"user_id": user_id, self.topic_fk: topic_id, **values}
        stmt = build_upsert_statement(
            self.note_model,
            payload,
            conflict_columns=["user_id", self.topic_fk],
        )
        return (await self.session.execute(stmt)).scalars().one()

    # ------------------------------------------------------------------ scheduling
    async def list_due_for_scheduling(
        self, *, user_id: uuid.UUID, now: datetime, limit: int = 50
    ) -> list[Any]:
        stmt = (
            select(self.progress_model)
            .where(
                self.progress_model.user_id == user_id,
                self.progress_model.deleted_at.is_(None),
                self.progress_model.next_revision_at.is_not(None),
                self.progress_model.next_revision_at <= now,
            )
            .order_by(self.progress_model.next_revision_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def counts_by_status(self, *, user_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(self.progress_model.status, func.count())
            .where(
                self.progress_model.user_id == user_id,
                self.progress_model.deleted_at.is_(None),
            )
            .group_by(self.progress_model.status)
        )
        return {status: int(count) for status, count in (await self.session.execute(stmt)).all()}


class LLDRepository(TopicCommonRepository[LLDTopic, LLDProgress, LLDNote]):
    topic_model = LLDTopic
    progress_model = LLDProgress
    note_model = LLDNote
    topic_fk = "lld_topic_id"


class HLDRepository(TopicCommonRepository[HLDTopic, HLDProgress, HLDNote]):
    topic_model = HLDTopic
    progress_model = HLDProgress
    note_model = HLDNote
    topic_fk = "hld_topic_id"
