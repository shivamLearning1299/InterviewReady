"""Offline synchronisation schemas (push/pull protocol).

The contract is deliberately explicit about concurrency: a client states the ``base_version``
it last saw, and the server is the only authority on what the current version is. Conflicts
are reported *with the server's current record* so the client can merge intelligently rather
than silently losing a change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.constants import SyncEntity, SyncOperation

MutationStatus = Literal["applied", "skipped_duplicate", "conflict", "rejected"]


class SyncMutationPayload(BaseModel):
    """One queued offline change."""

    mutation_id: uuid.UUID = Field(
        description="Client-generated id. Replaying the same id must not duplicate data."
    )
    entity: SyncEntity
    operation: SyncOperation = SyncOperation.UPSERT
    record_id: uuid.UUID | None = Field(
        default=None, description="Target record id. Required for update/delete."
    )
    base_version: int | None = Field(
        default=None,
        ge=1,
        description="Version the client last saw. Omit to force-write (created-on-device rows).",
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    client_timestamp: datetime | None = Field(
        default=None,
        description="Advisory only. The server never uses a device clock for ordering.",
    )

    @field_validator("record_id", mode="after")
    @classmethod
    def _require_record_id_for_mutations(
        cls, value: uuid.UUID | None, info: Any
    ) -> uuid.UUID | None:
        operation = info.data.get("operation")
        if operation in (SyncOperation.UPDATE, SyncOperation.DELETE) and value is None:
            raise ValueError("record_id is required for update and delete operations")
        return value


class SyncPushRequest(BaseModel):
    device_id: str | None = Field(default=None, max_length=120)
    device_type: str | None = Field(default=None, max_length=20)
    mutations: list[SyncMutationPayload] = Field(min_length=1)

    @field_validator("mutations")
    @classmethod
    def _cap_mutations(cls, value: list[SyncMutationPayload]) -> list[SyncMutationPayload]:
        from app.core.config import get_settings

        maximum = get_settings().sync_max_mutations_per_push
        if len(value) > maximum:
            raise ValueError(
                f"Too many mutations in one request ({len(value)}). Maximum is {maximum}; "
                "split the batch and retry."
            )
        # A repeated mutation_id inside one batch is deliberately NOT rejected here. A
        # device that queued the same change twice (an offline retry, a double tap) must
        # still be able to drain its queue, and rejecting the whole batch would leave it
        # stuck retrying forever. The push handler de-duplicates: the first occurrence is
        # applied and later ones are reported as ``skipped_duplicate``.
        return value


class SyncMutationResult(BaseModel):
    mutation_id: uuid.UUID
    status: MutationStatus
    entity: str
    record_id: uuid.UUID | None = None
    version: int | None = None
    updated_at: datetime | None = None
    # Present on conflict: the authoritative server state, so the client can merge.
    server_record: dict[str, Any] | None = None
    # Present on rejection: why the mutation could not be applied.
    error_code: str | None = None
    message: str | None = None
    applied: bool = False


class SyncPushResponse(BaseModel):
    results: list[SyncMutationResult] = Field(default_factory=list)
    applied_count: int = 0
    conflict_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    # Cursor the client should use for its next pull.
    server_cursor: int | None = None
    server_time: datetime


class SyncChangeRecord(BaseModel):
    """One entry in the pull stream."""

    seq: int
    entity: str
    record_id: uuid.UUID
    operation: Literal["upsert", "delete"]
    version: int | None = None
    updated_at: datetime | None = None
    data: dict[str, Any] | None = None


class SyncPullResponse(BaseModel):
    changes: list[SyncChangeRecord] = Field(default_factory=list)
    next_cursor: int
    has_more: bool = False
    server_time: datetime
    # Total changes still pending after this page, when cheaply known.
    remaining: int | None = None


class SyncStatusResponse(BaseModel):
    server_cursor: int
    last_change_at: datetime | None = None
    last_sync_at: datetime | None = None
    pending_changes: int = 0
    server_time: datetime
