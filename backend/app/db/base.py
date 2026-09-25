"""Declarative base, naming conventions and the reusable model mixins.

Every table in the application is created from this metadata, so the naming convention
below is what guarantees consistent, predictable constraint names in PostgreSQL — which
in turn lets Alembic produce stable, reviewable autogenerate diffs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Constraint naming template — required for deterministic Alembic autogenerate output.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Async-aware declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Shallow column dump — used by sync/export payload builders."""
        excluded = exclude or set()
        return {
            column.key: getattr(self, column.key)
            for column in self.__table__.columns
            if column.key not in excluded
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUID surrogate key generated client-side so offline devices can pre-assign ids."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class StringPrimaryKeyMixin:
    """TEXT primary key for the DSA catalog.

    The pre-existing ``public`` schema references problems as ``problem_id text`` in
    ``user_problem_progress``, ``problem_notes``, ``code_snippets`` and inside
    ``daily_plans.problem_ids`` (a JSONB array). Making the catalog's primary key the same
    type means those existing rows join directly, with no rewriting of user data.

    The value is the problem slug (``"two-sum"``), which is also stable across reseeds.
    """

    id: Mapped[str] = mapped_column(String(300), primary_key=True)


class TimestampMixin:
    """Server-generated timestamps.

    Server-side defaults are deliberate: clients may have skewed or spoofed clocks, and
    the sync protocol treats server time as the authority.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class VersionMixin:
    """Optimistic-concurrency counter incremented on every mutation.

    Required by the offline sync protocol: a device sends the ``base_version`` it last
    saw, and the server rejects the write when the row has moved on.

    Version bumps are performed explicitly (``version = version + 1``) rather than via
    SQLAlchemy's ``version_id_col`` mapper argument, because several write paths go
    through ``INSERT ... ON CONFLICT DO UPDATE`` where a mapper-level check cannot see
    the existing row.
    """

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )


class SoftDeleteMixin:
    """Tombstone column so ``/sync/pull`` can report deletions to offline devices."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class SyncSequenceMixin:
    """Monotonic per-user change sequence.

    Retained for tables that opt into a row-local cursor. The primary sync cursor for
    this application is the global ``sync_changes.seq`` identity column instead, because
    a single ordered change log also captures deletions — which a row-local column
    cannot express.
    """

    sync_seq: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )


# Convenience base for "user-owned, syncable, versioned" rows.
class UserOwnedMixin(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Row that belongs to exactly one Supabase user and participates in sync."""


__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "SoftDeleteMixin",
    "StringPrimaryKeyMixin",
    "SyncSequenceMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "UserOwnedMixin",
    "VersionMixin",
]
