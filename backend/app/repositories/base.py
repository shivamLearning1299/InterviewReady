"""Shared repository behaviour."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    """Small, explicit repository base.

    Deliberately not an abstraction layer with dozens of generic methods: repositories in
    this codebase expose intent-named queries (``list_due_for_user``, ``upsert_progress``),
    which reads far better at the call site than ``find_all(**kwargs)``.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def flush(self) -> None:
        """Push pending changes so server defaults (ids, timestamps) are populated."""
        await self.session.flush()

    async def refresh(self, instance: Any) -> Any:
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: Any) -> None:
        """Hard delete. Prefer a soft-delete/tombstone for syncable user data."""
        await self.session.delete(instance)
        await self.session.flush()

    async def count_where(self, *conditions: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int(await self.session.scalar(stmt) or 0)

    async def get_or_raise(self, *conditions: Any, error: NotFoundError | None = None) -> Any:
        """Fetch exactly one row or raise the supplied (or generic) not-found error."""
        stmt = select(self.model).where(*conditions).limit(1)
        instance = await self.session.scalar(stmt)
        if instance is None:
            raise error or NotFoundError()
        return instance

    async def exists(self, *conditions: Any) -> bool:
        stmt = select(func.count()).select_from(self.model).where(*conditions)
        return bool(await self.session.scalar(stmt))
