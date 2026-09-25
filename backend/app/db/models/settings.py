"""Per-user preferences consumed by the daily planner, revision engine and tutor."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionMixin,
)


class UserSettings(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, SoftDeleteMixin, Base):
    """One settings row per Supabase user.

    ``user_id`` intentionally carries no foreign key. The canonical user table lives in
    Supabase's ``auth`` schema, which is owned by the platform: adding an FK from our
    ``public`` schema into ``auth`` would couple our migrations to Supabase internals and
    break if the auth schema is ever restructured. Referential integrity for the user id
    comes from the verified JWT instead.
    """

    __tablename__ = "user_settings"
    __table_args__ = (
        Index("ix_user_settings_user_id_updated_at", "user_id", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, unique=True)

    # -- daily plan -------------------------------------------------------------
    daily_dsa_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    daily_revision_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    include_lld_daily: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    include_hld_daily: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    daily_plan_preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # -- revision ---------------------------------------------------------------
    revision_preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    revision_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    # -- ai ---------------------------------------------------------------------
    ai_preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_auto_reveal_solution: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # -- misc -------------------------------------------------------------------
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    preferred_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, server_default=text("'{python}'::varchar[]")
    )
    theme: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'system'"))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserSettings user={self.user_id}>"


__all__ = ["UserSettings"]
