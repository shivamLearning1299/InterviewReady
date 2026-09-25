"""Helpers for idempotent writes.

Every user-facing write in this application is an UPSERT: the iOS client replays queued
offline changes, the web client retries failed requests, and the sync protocol explicitly
allows duplicate mutations. Building the ``ON CONFLICT DO UPDATE`` clauses in one place
keeps that behaviour consistent and keeps ``version`` bumps and ``updated_at`` refreshes
from being forgotten in one service but not another.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.elements import ColumnClause

from app.utils.datetime_utils import utcnow

#: Columns that must never be overwritten by an upsert payload.
IMMUTABLE_COLUMNS: frozenset[str] = frozenset(
    {"id", "user_id", "created_at", "updated_at", "version"}
)


def apply_server_defaults(model: Any, values: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Fill in column defaults for NOT NULL columns the payload omits.

    ``INSERT ... ON CONFLICT DO UPDATE`` validates the *proposed* insert row before it
    looks for a conflict, so a partial payload fails outright even when the row already
    exists and the missing column would not have been updated. Concretely, pushing only
    ``confidence`` to ``user_problem_progress`` raised::

        null value in column "status" ... violates not-null constraint

    Returns the augmented payload plus the set of keys that were injected, so the caller
    can keep them out of the ``DO UPDATE`` clause. That distinction is essential: a default
    exists to populate a *new* row, and writing it over an existing value would reset the
    user's data (e.g. silently returning a solved problem to ``not_started``).
    """
    injected: set[str] = set()
    for column in model.__table__.columns:
        name = column.name
        if name in values or column.primary_key:
            continue
        if column.nullable or column.server_default is None:
            continue
        values[name] = column.server_default.arg
        injected.add(name)
    return values, injected


def build_upsert_statement(
    model: Any,
    values: dict[str, Any],
    *,
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
    increment_version: bool = True,
) -> Any:
    """Build a PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` statement.

    ``version`` and ``updated_at`` are updated automatically, so an upserted row always
    advances the optimistic-concurrency counter the sync protocol depends on.
    """
    values, injected = apply_server_defaults(model, dict(values))
    stmt = pg_insert(model).values(**values)

    if update_columns is None:
        existing_columns = set(model.__table__.columns.keys())
        update_columns = [
            key
            for key in values
            # Only touch columns the caller actually supplied. Defaults injected above are
            # for the insert path only.
            if key not in IMMUTABLE_COLUMNS
            and key not in conflict_columns
            and key not in injected
            and key in existing_columns
        ]

    update_values: dict[str, Any] = {
        column: stmt.excluded[column] for column in update_columns
    }
    update_values["updated_at"] = func.now()

    if increment_version:
        version_column: ColumnClause = model.version
        update_values["version"] = version_column + 1

    return stmt.on_conflict_do_update(
        index_elements=conflict_columns,
        set_=update_values,
    ).returning(model)


async def upsert_returning(
    session: AsyncSession,
    model: Any,
    values: dict[str, Any],
    *,
    conflict_columns: list[str],
    update_columns: list[str] | None = None,
) -> Any:
    """Execute an upsert and return the resulting ORM instance.

    Uses ``returning(model)`` so the caller gets the post-write row (including the bumped
    ``version``) without issuing a second SELECT — one round trip instead of two on the
    hottest write paths.

    ``populate_existing`` guarantees the returned object reflects this statement's result
    rather than a stale copy already present in the session's identity map. Without it, a
    session that loaded the row earlier would keep returning the pre-upsert ``version``,
    which would break the optimistic-concurrency checks the sync protocol depends on.
    """
    stmt = build_upsert_statement(
        model,
        values,
        conflict_columns=conflict_columns,
        update_columns=update_columns,
    ).execution_options(populate_existing=True)
    result = await session.execute(stmt)
    return result.scalars().one()


def not_deleted(model: Any) -> ColumnElement[bool]:
    """``deleted_at IS NULL`` filter for models that carry a tombstone."""
    return model.deleted_at.is_(None)


def is_null_or_after(column: Any, moment: datetime) -> ColumnElement[bool]:
    """``column IS NULL OR column > moment`` — used for 'never reviewed or stale'."""
    return column.is_(None) | (column > moment)


async def exists_for_user(
    session: AsyncSession,
    model: Any,
    *,
    user_id: Any,
    **filters: Any,
) -> bool:
    """Cheap existence check, always scoped to one user."""
    stmt = select(func.count()).select_from(model).where(model.user_id == user_id)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    return bool(await session.scalar(stmt))


def merge_defined(current: Any, updates: dict[str, Any]) -> dict[str, Any]:
    """Return ``updates`` without the keys whose value is ``None``.

    ``PUT`` on notes is a full replace, but ``PATCH``-style partial payloads should not
    null out fields the client simply omitted. Callers that genuinely want to clear a
    field pass an empty string.
    """
    return {key: value for key, value in updates.items() if value is not None}


def now_or(value: datetime | None) -> datetime:
    return value or utcnow()
