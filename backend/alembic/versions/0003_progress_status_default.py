"""Give ``user_problem_progress.status`` the same default its sibling columns have.

Why
---
The pre-existing table declares ``status text NOT NULL`` with **no** default, while every
other non-nullable column on it (``attempts``, ``confidence``, ``revision_count``,
``is_favorite``) has one.

That asymmetry is a latent hazard for an UPSERT-based API. PostgreSQL evaluates ``NOT NULL``
on the proposed insert row *before* it checks for a conflict, so ``INSERT ... ON CONFLICT DO
UPDATE`` fails outright when a caller supplies a partial payload — even when the row already
exists and the update would not have touched ``status``. Concretely, a client syncing only
``confidence`` produced::

    null value in column "status" of relation "user_problem_progress" violates not-null
    constraint

``not_started`` is the correct default: it is in the table's own ``CHECK`` vocabulary and it
is already how the application interprets a problem with no progress row.

This migration is additive — it only attaches a default. No data is rewritten and no
existing value can change, because a default is applied solely when the column is omitted.

Revision ID: 0003
Revises: 0002_new_tables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_progress_status_default"
down_revision: str | None = "0002_new_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "user_problem_progress"


def upgrade() -> None:
    # Backfill any row that somehow holds NULL before the constraint is tightened. On a
    # healthy database this touches nothing.
    op.execute(f"UPDATE public.{TABLE} SET status = 'not_started' WHERE status IS NULL")
    op.alter_column(
        TABLE,
        "status",
        existing_type=sa.String(30),
        existing_nullable=False,
        server_default=sa.text("'not_started'"),
    )


def downgrade() -> None:
    """Detach the default. Deliberately does not touch stored data."""
    op.alter_column(
        TABLE,
        "status",
        existing_type=sa.String(30),
        existing_nullable=False,
        server_default=None,
    )
