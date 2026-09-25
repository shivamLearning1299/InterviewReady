"""Offline synchronisation for the iOS client."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.v1.dependencies import CurrentUser, ServicesDep
from app.schemas.sync import (
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncStatusResponse,
)

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post(
    "/push",
    response_model=SyncPushResponse,
    summary="Push queued offline changes",
    description=(
        "Applies a batch of mutations made while the device was offline.\n\n"
        "**Idempotent per `mutation_id`.** The id is recorded in an idempotency ledger with "
        "a unique constraint, so replaying a push returns the original result "
        "(`skipped_duplicate`) instead of applying the write twice. This is what makes it "
        "safe for the client to retry after a timeout.\n\n"
        "**Optimistic concurrency.** Each mutation may state the `base_version` it last "
        "saw. If the record has moved on, the result is `conflict` and includes the "
        "server's **current record** so the client can merge rather than silently "
        "overwrite another device's change.\n\n"
        "A rejected mutation does not fail the rest of the batch: each is applied in its "
        "own savepoint and reported individually."
    ),
)
async def push(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: SyncPushRequest,
) -> SyncPushResponse:
    return await services.sync.push(user_id=current_user.id, payload=payload)


@router.get(
    "/pull",
    response_model=SyncPullResponse,
    summary="Pull changes since a cursor",
    description=(
        "Returns every change to the caller's data after `cursor`, oldest first.\n\n"
        "The cursor is a **server-issued sequence number** (`next_cursor`), never a device "
        "timestamp: two changes made in the same millisecond still get distinct ordered "
        "cursors, and deletions are represented explicitly so they propagate to other "
        "devices. Pass `0` on a first sync to receive everything.\n\n"
        "When `has_more` is true, immediately call again with the returned `next_cursor`."
    ),
)
async def pull(
    current_user: CurrentUser,
    services: ServicesDep,
    cursor: int = Query(default=0, ge=0, description="Cursor from a previous pull"),
    limit: int | None = Query(default=None, ge=1, le=500),
    device_id: str | None = Query(default=None, max_length=120),
) -> SyncPullResponse:
    return await services.sync.pull(
        user_id=current_user.id, cursor=cursor, limit=limit, device_id=device_id
    )


@router.get(
    "/status",
    response_model=SyncStatusResponse,
    summary="Sync state",
    description="Server cursor, last change time and this device's last sync time.",
)
async def status(
    current_user: CurrentUser,
    services: ServicesDep,
    device_id: str | None = Query(default=None, max_length=120),
) -> SyncStatusResponse:
    return await services.sync.status(user_id=current_user.id, device_id=device_id)


__all__ = ["router"]
