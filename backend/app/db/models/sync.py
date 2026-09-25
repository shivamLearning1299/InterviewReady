"""Offline sync: the change log, the mutation idempotency ledger, and device registry.

The cursor is ``sync_changes.seq`` — a single global BIGINT identity column. Using one
ordered log rather than per-row ``updated_at`` solves three problems at once:

* identical timestamps no longer collapse two distinct changes into one cursor slot;
* device clock skew is irrelevant, because ordering comes from the server's sequence;
* deletions get a first-class representation, which a "latest updated_at" cursor cannot
  express without a tombstone scan of every table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin

_CHANGE_OPERATION_SQL = "'upsert','delete'"
_DEVICE_TYPE_SQL = "'ios','web','android','other'"


class SyncChange(UUIDPrimaryKeyMixin, Base):
    """Append-only, per-user change log that powers ``GET /api/v1/sync/pull``.

    Written inside the same transaction as the mutation it describes, so a change can
    never be recorded for a write that rolled back (and vice versa).
    """

    __tablename__ = "sync_changes"
    __table_args__ = (
        # The single index that matters: "this user's changes after cursor N, in order".
        Index("ix_sync_changes_user_id_seq", "user_id", "seq"),
        Index("ix_sync_changes_user_id_entity", "user_id", "entity"),
    )

    # Global monotonic sequence — the cursor authority for every device.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)

    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full row snapshot for upserts; ``None`` for deletes (the client removes the record).
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Device that originated the change, so a client can skip echoing its own write.
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SyncChange seq={self.seq} {self.entity}:{self.operation}>"


class SyncMutation(UUIDPrimaryKeyMixin, Base):
    """Idempotency ledger for ``POST /api/v1/sync/push``.

    ``unique(user_id, mutation_id)`` is what makes a retried push safe: replaying a
    mutation returns the original result instead of applying the write twice.
    """

    __tablename__ = "sync_mutations"
    __table_args__ = (
        UniqueConstraint("user_id", "mutation_id"),
        Index("ix_sync_mutations_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    mutation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    record_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False)
    # Result envelope returned to the client for this mutation (replayed verbatim on retry).
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SyncMutation {self.mutation_id} {self.status}>"


class UserDevice(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    """A device that syncs this user's data.

    Deliberately minimal — only what is needed to attribute changes and show "last synced".
    No hardware identifiers, advertising ids, or anything not strictly necessary.
    """

    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_identifier"),
        CheckConstraint(f"device_type IN ({_DEVICE_TYPE_SQL})", name="device_type_valid"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    device_identifier: Mapped[str] = mapped_column(String(120), nullable=False)
    device_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'ios'")
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_pull_cursor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserDevice {self.device_type} {self.device_identifier}>"


__all__ = ["SyncChange", "SyncMutation", "UserDevice"]
