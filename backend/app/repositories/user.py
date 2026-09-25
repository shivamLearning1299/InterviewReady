"""Per-user settings and device-independent user preferences."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import UserSettings
from app.utils.upsert import build_upsert_statement


class UserSettingsRepository:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def get(self, *, user_id: uuid.UUID) -> UserSettings | None:
        return await self.session.scalar(
            select(UserSettings).where(
                UserSettings.user_id == user_id, UserSettings.deleted_at.is_(None)
            )
        )

    async def upsert(
        self, *, user_id: uuid.UUID, values: dict[str, Any], defaults: dict[str, Any] | None = None
    ) -> UserSettings:
        """Create the row on first write, update it afterwards.

        Only the keys actually supplied are written, so ``PUT /settings`` behaves as a
        merge: a client that omits ``ai_preferences`` does not wipe it. This matters for
        the iOS client, which sends a partial payload after an offline change.
        """
        payload: dict[str, Any] = {"user_id": user_id, **(defaults or {}), **values}
        stmt = build_upsert_statement(
            UserSettings,
            payload,
            conflict_columns=["user_id"],
            update_columns=[key for key in values if key not in {"user_id"}],
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def get_or_create_defaults(
        self, *, user_id: uuid.UUID, defaults: dict[str, Any]
    ) -> UserSettings:
        """Read the row, creating it with the given defaults if it does not exist yet."""
        existing = await self.get(user_id=user_id)
        if existing is not None:
            return existing
        return await self.upsert(user_id=user_id, values={}, defaults=defaults)
