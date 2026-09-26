"""Widen ``ai_conversations.context_id`` to TEXT so the DSA tutor can work at all.

Why
---
``ai_conversations.context_id`` was created as ``uuid``. That is correct for LLD and HLD —
``lld_topics.id`` and ``hld_topics.id`` are UUIDs — but it is impossible for DSA, because
``dsa_problems.id`` is the problem **slug** (a TEXT primary key chosen deliberately so the
pre-existing ``problem_id text`` columns join without rewriting user data).

The failure was silent in the worst way: the React DSA workspace sends
``context_id: "two-sum"``, Pydantic rejected it at the boundary with a 422, and every DSA
tutor request failed while LLD/HLD kept working. Nothing in the logs pointed at the cause.

The service already treated the value as a string — its DSA branch reads
``str(context_id)`` — so TEXT matches what the code was always doing.

Widening ``uuid`` -> ``text`` is lossless: every existing UUID renders as its canonical
text form and casts back unchanged. The index is recreated because its operator class
changes.

Revision ID: 0005
Revises: 0004_progress_check_constraints
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ai_context_id_text"
down_revision: str | None = "0004_progress_check_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_conversations"
INDEX = "ix_ai_conversations_user_id_context"


def upgrade() -> None:
    # The index is dropped first: PostgreSQL cannot alter the type of a column that an
    # index depends on.
    op.drop_index(INDEX, table_name=TABLE)
    op.alter_column(
        TABLE,
        "context_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        type_=sa.String(300),
        existing_nullable=True,
        postgresql_using="context_id::text",
    )
    op.create_index(INDEX, TABLE, ["user_id", "context_type", "context_id"])


def downgrade() -> None:
    """Narrow back to UUID.

    Only safe when no row holds a non-UUID value (i.e. no DSA conversation exists). A slug
    cannot be cast to a UUID, so such rows are nulled rather than failing the whole
    migration — the conversation itself is preserved, only the context link is dropped.
    """
    op.execute(
        f"UPDATE public.{TABLE} SET context_id = NULL "
        "WHERE context_id IS NOT NULL AND context_id !~* "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
    )
    op.drop_index(INDEX, table_name=TABLE)
    op.alter_column(
        TABLE,
        "context_id",
        existing_type=sa.String(300),
        type_=sa.dialects.postgresql.UUID(as_uuid=True),
        existing_nullable=True,
        postgresql_using="context_id::uuid",
    )
    op.create_index(INDEX, TABLE, ["user_id", "context_type", "context_id"])
