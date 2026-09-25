"""Declare the ``user_problem_progress`` CHECK constraints the ORM already advertises.

Why
---
``app/db/models/dsa.py`` declares two ``CHECK`` constraints on this table::

    CheckConstraint("status IN ('not_started','attempted','solved','needs_revision','mastered')",
                    name="status_valid")
    CheckConstraint("confidence BETWEEN 0 AND 5", name="confidence_range")

which — through the metadata naming convention ``ck_%(table_name)s_%(constraint_name)s``
in ``app/db/base.py`` — resolve to the PostgreSQL names

    ck_user_problem_progress_status_valid
    ck_user_problem_progress_confidence_range

No migration ever created them. ``schema_snapshot.json`` shows a ``status_valid`` CHECK
only on the *new* sibling tables (``ck_lld_progress_status_valid``,
``ck_hld_progress_status_valid``); on ``user_problem_progress`` — the pre-existing,
adapted table — the constraint is absent from the live database.

Consequence: a client that writes progress directly (the offline sync path, a
service-role script, a hand-run ``INSERT``) can persist any string it likes in
``status`` or any integer in ``confidence``. The API's service layer validates those
fields, but the database does not, so the invalid row is silently accepted and every
later read has to defend against vocabulary it can no longer trust. The same applies to
``confidence``, where the ladder code assumes a 0-5 range.

This migration closes that gap:

1. It repairs any value already stored outside the canonical vocabulary, *before* the
   constraint is created, so the ``ALTER TABLE`` cannot fail on pre-existing bad rows.
2. It then adds both constraints, guarded so the migration is safe to re-run.

Ordering matters. Run this **after** every writing client has been corrected to emit the
canonical enum values. Applied first, this constraint would reject writes that currently
succeed, and the failure would surface as an ``IntegrityError`` in production rather than
as a validation message in the client. The repair step makes the existing data valid; only
client behaviour can keep it valid going forward.

Revision ID: 0004_progress_check_constraints
Revises: 0003_progress_status_default
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_progress_check_constraints"
down_revision: str | None = "0003_progress_status_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "user_problem_progress"

STATUS_CONSTRAINT = "ck_user_problem_progress_status_valid"
CONFIDENCE_CONSTRAINT = "ck_user_problem_progress_confidence_range"

# The canonical vocabulary, written exactly as the ORM declares it.
STATUS_VALUES = ("not_started", "attempted", "solved", "needs_revision", "mastered")
STATUS_IN_SQL = "'not_started','attempted','solved','needs_revision','mastered'"


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------
def _constraint_exists(name: str) -> bool:
    """True when the constraint is already attached to the table.

    Scoped to the table as well as the name, so a same-named constraint on an unrelated
    table can never make this migration skip its work.
    """
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name "
                "AND conrelid = 'public.user_problem_progress'::regclass)"
            ),
            {"name": name},
        ).scalar()
    )


def _create_check_constraint_if_missing(name: str, condition: str) -> None:
    if _constraint_exists(name):
        return
    op.create_check_constraint(name, TABLE, condition)


# ---------------------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------------------
def upgrade() -> None:
    # 1. Repair existing data first. The constraint is added afterwards, so on a database
    #    that already holds a non-canonical value the ALTER TABLE still succeeds.
    #
    #    The two literal rewrites below are the camelCase spellings a direct-writing
    #    client is known to emit; they are pure aliases, so no information is lost.
    op.execute(f"UPDATE public.{TABLE} SET status = 'not_started' WHERE status = 'notStarted'")
    op.execute(
        f"UPDATE public.{TABLE} SET status = 'needs_revision' WHERE status = 'needsRevision'"
    )

    # Anything else outside the vocabulary (an unknown enum name, a stray casing, a NULL
    # from a pre-0003 row) folds to 'not_started' — the same value migration 0003 made the
    # column's default, and how the application already interprets "no real progress yet".
    op.execute(
        f"UPDATE public.{TABLE} SET status = 'not_started' "
        f"WHERE status IS NULL OR status NOT IN ({STATUS_IN_SQL})"
    )

    # Confidence is NOT NULL DEFAULT 3 in the existing table, but a direct write could
    # still have pushed a value outside 0-5 (or a NULL, on an older schema revision).
    # Clamp rather than reset: the row keeps the closest in-range value.
    op.execute(
        f"UPDATE public.{TABLE} SET confidence = GREATEST(0, LEAST(5, confidence)) "
        "WHERE confidence IS NOT NULL AND confidence NOT BETWEEN 0 AND 5"
    )
    op.execute(f"UPDATE public.{TABLE} SET confidence = 3 WHERE confidence IS NULL")

    # 2. Now the ORM's own constraints, exactly as declared — names and predicates match
    #    ``app/db/models/dsa.py``, so autogenerate sees no drift afterwards.
    _create_check_constraint_if_missing(STATUS_CONSTRAINT, f"status IN ({STATUS_IN_SQL})")
    _create_check_constraint_if_missing(CONFIDENCE_CONSTRAINT, "confidence BETWEEN 0 AND 5")


# ---------------------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------------------
def downgrade() -> None:
    """Drop both constraints by name.

    Data is deliberately left untouched: the repair in ``upgrade`` already rewrote the
    offending values, and inventing the old (invalid) ones back would be worse than
    leaving the repaired values in place.
    """
    op.execute(f"ALTER TABLE public.{TABLE} DROP CONSTRAINT IF EXISTS {STATUS_CONSTRAINT}")
    op.execute(f"ALTER TABLE public.{TABLE} DROP CONSTRAINT IF EXISTS {CONFIDENCE_CONSTRAINT}")
