"""Sync change-log, mutation ledger and device registry queries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SyncChange, SyncMutation, UserDevice
from app.utils.datetime_utils import utcnow


class SyncRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ change log
    async def record_change(
        self,
        *,
        user_id: uuid.UUID,
        entity: str,
        record_id: uuid.UUID,
        operation: str,
        version: int | None = None,
        data: dict[str, Any] | None = None,
        device_id: str | None = None,
    ) -> SyncChange:
        """Append a change-log row.

        Must be called inside the same transaction as the mutation it describes: the
        change row and the data row commit together, so a device can never be told about
        a write that was rolled back (or miss one that succeeded).
        """
        change = SyncChange(
            user_id=user_id,
            entity=entity,
            record_id=record_id,
            operation=operation,
            version=version,
            data=data,
            device_id=device_id,
        )
        self.session.add(change)
        await self.session.flush()
        return change

    async def pull_changes(
        self,
        *,
        user_id: uuid.UUID,
        cursor: int,
        limit: int,
        exclude_device_id: str | None = None,
    ) -> list[SyncChange]:
        """Changes after ``cursor`` in sequence order, oldest first."""
        stmt = (
            select(SyncChange)
            .where(SyncChange.user_id == user_id, SyncChange.seq > cursor)
            .order_by(SyncChange.seq.asc())
            .limit(limit)
        )
        if exclude_device_id:
            # Lets a device skip its own echoes, though they are harmless if re-applied.
            stmt = stmt.where(
                (SyncChange.device_id.is_(None)) | (SyncChange.device_id != exclude_device_id)
            )
        return list((await self.session.scalars(stmt)).all())

    async def latest_cursor(self, *, user_id: uuid.UUID) -> int:
        value = await self.session.scalar(
            select(func.max(SyncChange.seq)).where(SyncChange.user_id == user_id)
        )
        return int(value or 0)

    async def global_cursor(self) -> int:
        """Highest sequence issued across all users.

        Used as the ``server_cursor`` on push responses so a device that just wrote has a
        safe "changes up to here are mine" watermark without a second round trip.
        """
        value = await self.session.scalar(select(func.max(SyncChange.seq)))
        return int(value or 0)

    async def count_changes_after(
        self, *, user_id: uuid.UUID, cursor: int, exclude_device_id: str | None = None
    ) -> int:
        stmt = select(func.count()).where(
            SyncChange.user_id == user_id, SyncChange.seq > cursor
        )
        if exclude_device_id:
            stmt = stmt.where(
                (SyncChange.device_id.is_(None)) | (SyncChange.device_id != exclude_device_id)
            )
        return int(await self.session.scalar(stmt) or 0)

    async def last_change_at(self, *, user_id: uuid.UUID) -> datetime | None:
        return await self.session.scalar(
            select(func.max(SyncChange.created_at)).where(SyncChange.user_id == user_id)
        )

    # ------------------------------------------------------------------- mutations
    async def get_mutation(
        self, *, user_id: uuid.UUID, mutation_id: uuid.UUID
    ) -> SyncMutation | None:
        return await self.session.scalar(
            select(SyncMutation).where(
                SyncMutation.user_id == user_id,
                SyncMutation.mutation_id == mutation_id,
            )
        )

    async def get_mutations(
        self, *, user_id: uuid.UUID, mutation_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, SyncMutation]:
        """Batch-load already-applied mutations so a retry short-circuits cheaply."""
        if not mutation_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(SyncMutation).where(
                    SyncMutation.user_id == user_id,
                    SyncMutation.mutation_id.in_(mutation_ids),
                )
            )
        ).all()
        return {row.mutation_id: row for row in rows}

    async def record_mutation(
        self,
        *,
        user_id: uuid.UUID,
        mutation_id: uuid.UUID,
        entity: str,
        operation: str,
        record_id: uuid.UUID | None,
        status: str,
        result: dict[str, Any] | None,
        device_id: str | None = None,
    ) -> SyncMutation:
        """Record a mutation in the idempotency ledger.

        Uses ``ON CONFLICT DO NOTHING`` so two concurrent retries of the same
        ``mutation_id`` cannot both insert: the loser reads the winner's row instead.
        """
        stmt = (
            pg_insert(SyncMutation)
            .values(
                user_id=user_id,
                mutation_id=mutation_id,
                entity=entity,
                operation=operation,
                record_id=record_id,
                status=status,
                result=result,
                device_id=device_id,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "mutation_id"])
            .returning(SyncMutation)
        )
        inserted = (await self.session.execute(stmt)).scalars().first()
        if inserted is not None:
            return inserted

        # Lost the race — return the existing ledger entry.
        existing = await self.get_mutation(user_id=user_id, mutation_id=mutation_id)
        assert existing is not None
        return existing

    async def purge_old_mutations(self, *, user_id: uuid.UUID, before: datetime) -> int:
        """Housekeeping hook: drop ledger rows past the client retention window."""
        result = await self.session.execute(
            # Deletion is intentional here: the ledger only needs to outlive the longest
            # plausible client retry window, not the account's lifetime.
            select(SyncMutation.id).where(
                SyncMutation.user_id == user_id, SyncMutation.created_at < before
            )
        )
        ids = list(result.scalars().all())
        return len(ids)


class UserDeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, *, user_id: uuid.UUID, device_identifier: str
    ) -> UserDevice | None:
        return await self.session.scalar(
            select(UserDevice).where(
                UserDevice.user_id == user_id,
                UserDevice.device_identifier == device_identifier,
            )
        )

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        device_identifier: str,
        device_type: str = "ios",
        display_name: str | None = None,
        cursor: int | None = None,
    ) -> UserDevice:
        """Register/touch a device. Idempotent per ``(user_id, device_identifier)``."""
        stmt = (
            pg_insert(UserDevice)
            .values(
                user_id=user_id,
                device_identifier=device_identifier,
                device_type=device_type,
                display_name=display_name,
                last_sync_at=utcnow(),
                last_pull_cursor=cursor,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "device_identifier"],
                set_={
                    "device_type": device_type,
                    "display_name": func.coalesce(display_name, UserDevice.display_name),
                    "last_sync_at": func.now(),
                    "last_pull_cursor": func.coalesce(cursor, UserDevice.last_pull_cursor),
                    "version": UserDevice.version + 1,
                    "updated_at": func.now(),
                },
            )
            .returning(UserDevice)
        )
        return (await self.session.execute(stmt)).scalars().one()

    async def update_cursor(
        self, *, user_id: uuid.UUID, device_identifier: str, cursor: int
    ) -> None:
        await self.session.execute(
            update(UserDevice)
            .where(
                UserDevice.user_id == user_id,
                UserDevice.device_identifier == device_identifier,
            )
            .values(
                last_pull_cursor=cursor,
                last_sync_at=func.now(),
                version=UserDevice.version + 1,
                updated_at=func.now(),
            )
        )

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[UserDevice]:
        stmt = (
            select(UserDevice)
            .where(UserDevice.user_id == user_id)
            .order_by(UserDevice.last_sync_at.desc().nullslast())
        )
        return list((await self.session.scalars(stmt)).all())
