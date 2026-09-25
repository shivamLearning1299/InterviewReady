"""Baseline: additive changes to the pre-existing Supabase schema.

This migration **does not create any of the tables that already exist** in the project's
Supabase database (``user_problem_progress``, ``problem_notes``, ``code_snippets``,
``design_topics``, ``daily_plans``, ``study_sessions``). Those are left exactly as they
are, with their data intact.

It performs only additive work:

1. Adds ``created_at`` / ``version`` / ``deleted_at`` where the offline-sync protocol and
   optimistic concurrency need them, plus the few feature columns the API requires.
2. Relaxes ``code_snippets.problem_id`` to NULLABLE so LLD/HLD snippets can share the table.
3. Adds ``daily_plans`` uniqueness on ``(user_id, date_key)`` — the guarantee that makes
   ``GET /api/v1/today`` generate a plan at most once per day.
4. Backfills the new columns from existing data so no row is left in a broken state.

Every step is guarded with ``IF NOT EXISTS`` / ``IF EXISTS`` so the migration is safe to
re-run against a database that already has some of these columns.

Nothing is dropped and no data is deleted.

Revision ID: 0001_existing_schema_adaptation
Revises:
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_existing_schema_adaptation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------
def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :name)"
            ),
            {"name": table},
        ).scalar()
    )


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column)"
            ),
            {"table": table, "column": column},
        ).scalar()
    )


def _constraint_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :name)"),
            {"name": name},
        ).scalar()
    )


def _index_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
            {"name": name},
        ).scalar()
    )


def add_column_if_missing(table: str, column: sa.Column) -> None:
    if _table_exists(table) and not _column_exists(table, column.name):
        op.add_column(table, column)


def make_nullable_if_needed(table: str, column: str) -> None:
    """Relax a NOT NULL column to NULLABLE, checking first so the migration is repeatable.

    Needed because ``code_snippets.problem_id`` must accept LLD/HLD snippets, which have no
    problem. The column type is read from the live catalogue rather than assumed, so the
    migration does not hardcode ``text``.
    """
    if not _table_exists(table) or not _column_exists(table, column):
        return

    is_nullable = op.get_bind().execute(
        sa.text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar()

    if is_nullable == "NO":
        data_type = op.get_bind().execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).scalar()
        op.alter_column(
            table,
            column,
            existing_type=sa.Text() if data_type == "text" else None,
            nullable=True,
        )


def create_index_if_missing(name: str, table: str, columns: list[str], **kwargs: object) -> None:
    if _table_exists(table) and not _index_exists(name):
        op.create_index(name, table, columns, **kwargs)


# ---------------------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------------------
def upgrade() -> None:
    _adapt_user_problem_progress()
    _adapt_problem_notes()
    _adapt_code_snippets()
    _adapt_daily_plans()
    _adapt_study_sessions()


def _adapt_user_problem_progress() -> None:
    """Add sync/version columns, a revision counter and a favourites flag."""
    table = "user_problem_progress"
    if not _table_exists(table):
        return

    add_column_if_missing(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(
        table, sa.Column("revision_count", sa.Integer(), nullable=True)
    )
    add_column_if_missing(table, sa.Column("is_favorite", sa.Boolean(), nullable=True))

    # Backfill before tightening constraints, so existing rows stay valid.
    op.execute(
        f"UPDATE public.{table} SET created_at = COALESCE(created_at, updated_at, now()) "
        "WHERE created_at IS NULL"
    )
    op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")
    op.execute(f"UPDATE public.{table} SET revision_count = 0 WHERE revision_count IS NULL")
    op.execute(f"UPDATE public.{table} SET is_favorite = false WHERE is_favorite IS NULL")

    op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))
    op.alter_column(table, "revision_count", nullable=False, server_default=sa.text("0"))
    op.alter_column(table, "is_favorite", nullable=False, server_default=sa.text("false"))

    # The existing table has no unique constraint on (user_id, problem_id), but the API
    # upserts on that pair. Add it only if the existing data permits it.
    if not _constraint_exists("uq_user_problem_progress_user_id_problem_id"):
        duplicates = op.get_bind().execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT user_id, problem_id FROM public.{table} "
                "GROUP BY user_id, problem_id HAVING COUNT(*) > 1) AS dupes"
            )
        ).scalar()
        if not duplicates:
            op.create_unique_constraint(
                "uq_user_problem_progress_user_id_problem_id",
                table,
                ["user_id", "problem_id"],
            )
        else:  # pragma: no cover - depends on live data
            # Do not delete the user's rows. Report loudly instead; the API's upsert still
            # works, it just cannot rely on the database to reject duplicates.
            print(
                f"WARNING: {duplicates} duplicate (user_id, problem_id) groups in {table}. "
                "Skipping the unique constraint. Review duplicates manually."
            )

    create_index_if_missing(
        "ix_user_problem_progress_user_id_next_revision_date",
        table,
        ["user_id", "next_revision_date"],
    )
    create_index_if_missing("ix_user_problem_progress_user_id_status", table, ["user_id", "status"])
    create_index_if_missing(
        "ix_user_problem_progress_user_id_updated_at", table, ["user_id", "updated_at"]
    )


def _adapt_problem_notes() -> None:
    """Add the sync/version columns to notes."""
    table = "problem_notes"
    if not _table_exists(table):
        return

    add_column_if_missing(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        f"UPDATE public.{table} SET created_at = COALESCE(created_at, updated_at, now()) "
        "WHERE created_at IS NULL"
    )
    op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")

    op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))

    if not _constraint_exists("uq_problem_notes_user_id_problem_id"):
        duplicates = op.get_bind().execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT user_id, problem_id FROM public.{table} "
                "GROUP BY user_id, problem_id HAVING COUNT(*) > 1) AS dupes"
            )
        ).scalar()
        if not duplicates:
            op.create_unique_constraint(
                "uq_problem_notes_user_id_problem_id", table, ["user_id", "problem_id"]
            )
        else:  # pragma: no cover
            print(
                f"WARNING: {duplicates} duplicate (user_id, problem_id) groups in {table}. "
                "Skipping the unique constraint."
            )

    create_index_if_missing("ix_problem_notes_user_id_updated_at", table, ["user_id", "updated_at"])


def _adapt_code_snippets() -> None:
    """Extend the DSA-only snippet table to serve LLD and HLD too, without losing rows."""
    table = "code_snippets"
    if not _table_exists(table):
        return

    # An LLD/HLD snippet has no problem, so the column must become nullable.
    make_nullable_if_needed(table, "problem_id")

    add_column_if_missing(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("title", sa.String(200), nullable=True))
    add_column_if_missing(table, sa.Column("is_primary", sa.Boolean(), nullable=True))
    add_column_if_missing(table, sa.Column("context_type", sa.String(20), nullable=True))
    add_column_if_missing(table, sa.Column("context_id", sa.String(300), nullable=True))

    # Backfill: every pre-existing snippet belongs to a DSA problem, so mirror problem_id
    # into context_id. Without this, existing snippets would become unreachable.
    op.execute(
        f"UPDATE public.{table} SET context_type = 'dsa' WHERE context_type IS NULL"
    )
    op.execute(
        f"UPDATE public.{table} SET context_id = problem_id "
        "WHERE context_id IS NULL OR context_id = ''"
    )
    op.execute(f"UPDATE public.{table} SET created_at = COALESCE(created_at, updated_at, now()) "
               "WHERE created_at IS NULL")
    op.execute(f"UPDATE public.{table} SET is_primary = false WHERE is_primary IS NULL")
    op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")

    op.alter_column(table, "context_type", nullable=False, server_default=sa.text("'dsa'"))
    op.alter_column(table, "context_id", nullable=False, server_default=sa.text("''"))
    op.alter_column(table, "is_primary", nullable=False, server_default=sa.text("false"))
    op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))

    create_index_if_missing(
        "ix_code_snippets_user_id_context", table, ["user_id", "context_type", "context_id"]
    )
    create_index_if_missing("ix_code_snippets_user_id_updated_at", table, ["user_id", "updated_at"])


def _adapt_daily_plans() -> None:
    """Add plan state, ordering support and the per-day uniqueness guarantee."""
    table = "daily_plans"
    if not _table_exists(table):
        return

    add_column_if_missing(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("status", sa.String(20), nullable=True))
    add_column_if_missing(table, sa.Column("timezone", sa.String(64), nullable=True))
    add_column_if_missing(table, sa.Column("generated_by", sa.String(40), nullable=True))
    add_column_if_missing(table, sa.Column("notes", sa.Text(), nullable=True))

    op.execute(f"UPDATE public.{table} SET created_at = COALESCE(created_at, updated_at, now()) "
               "WHERE created_at IS NULL")
    op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")
    op.execute(f"UPDATE public.{table} SET status = 'active' WHERE status IS NULL")
    op.execute(f"UPDATE public.{table} SET timezone = 'UTC' WHERE timezone IS NULL")
    op.execute(f"UPDATE public.{table} SET generated_by = 'legacy' WHERE generated_by IS NULL")

    op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))
    op.alter_column(table, "status", nullable=False, server_default=sa.text("'active'"))
    op.alter_column(table, "timezone", nullable=False, server_default=sa.text("'UTC'"))
    op.alter_column(table, "generated_by", nullable=False, server_default=sa.text("'scheduler_v1'"))

    # The single most important constraint in the whole schema: it is what makes plan
    # generation idempotent under concurrent requests.
    if not _constraint_exists("uq_daily_plans_user_id_date_key"):
        duplicates = op.get_bind().execute(
            sa.text(
                f"SELECT COUNT(*) FROM (SELECT user_id, date_key FROM public.{table} "
                "GROUP BY user_id, date_key HAVING COUNT(*) > 1) AS dupes"
            )
        ).scalar()
        if not duplicates:
            op.create_unique_constraint(
                "uq_daily_plans_user_id_date_key", table, ["user_id", "date_key"]
            )
        else:  # pragma: no cover - depends on live data
            # Existing duplicates are the user's own plan history; never delete them.
            print(
                f"WARNING: {duplicates} duplicate (user_id, date_key) groups in {table}. "
                "Skipping the unique constraint. The service layer still guards generation "
                "with a SELECT-then-INSERT inside a transaction."
            )

    create_index_if_missing("ix_daily_plans_user_id_date_key", table, ["user_id", "date_key"])
    create_index_if_missing("ix_daily_plans_user_id_updated_at", table, ["user_id", "updated_at"])


def _adapt_study_sessions() -> None:
    """Add real timers to the legacy ``(date, minutes, area)`` session table.

    ``date``, ``minutes`` and ``area`` are left in place and kept populated by the
    repository, so anything already reading this table continues to work.
    """
    table = "study_sessions"
    if not _table_exists(table):
        return

    add_column_if_missing(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("session_type", sa.String(30), nullable=True))
    add_column_if_missing(table, sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing(table, sa.Column("duration_minutes", sa.Integer(), nullable=True))
    add_column_if_missing(table, sa.Column("context_id", sa.String(300), nullable=True))
    add_column_if_missing(table, sa.Column("context_label", sa.String(300), nullable=True))
    add_column_if_missing(table, sa.Column("note", sa.Text(), nullable=True))
    add_column_if_missing(table, sa.Column("device_id", sa.String(120), nullable=True))

    # Historical rows were completed sessions: `date` is the start and `minutes` the
    # duration. Map them onto the new timer columns so analytics see a consistent shape.
    op.execute(
        f"UPDATE public.{table} SET started_at = COALESCE(started_at, date, now()) "
        "WHERE started_at IS NULL"
    )
    op.execute(
        f"UPDATE public.{table} SET duration_minutes = COALESCE(duration_minutes, minutes) "
        "WHERE duration_minutes IS NULL"
    )
    op.execute(
        f"UPDATE public.{table} SET ended_at = COALESCE(ended_at, date + "
        "(COALESCE(minutes, 0) || ' minutes')::interval) "
        "WHERE ended_at IS NULL"
    )
    op.execute(
        f"UPDATE public.{table} SET session_type = COALESCE(session_type, area, 'dsa') "
        "WHERE session_type IS NULL"
    )
    op.execute(f"UPDATE public.{table} SET created_at = COALESCE(created_at, date, now()) "
               "WHERE created_at IS NULL")
    op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")

    op.alter_column(table, "session_type", nullable=False, server_default=sa.text("'dsa'"))
    op.alter_column(table, "started_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "created_at", nullable=False, server_default=sa.text("now()"))
    op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))

    create_index_if_missing("ix_study_sessions_user_id_date", table, ["user_id", "date"])
    create_index_if_missing("ix_study_sessions_user_id_started_at", table, ["user_id", "started_at"])
    create_index_if_missing("ix_study_sessions_user_id_updated_at", table, ["user_id", "updated_at"])

    # At most one running session per user. Historical rows all have ended_at set, so they
    # are unaffected by the partial index.
    if not _index_exists("uq_study_sessions_one_active_per_user"):
        op.execute(
            "CREATE UNIQUE INDEX uq_study_sessions_one_active_per_user "
            f"ON public.{table} (user_id) WHERE ended_at IS NULL AND deleted_at IS NULL"
        )


# ---------------------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------------------
def downgrade() -> None:
    """Remove only the columns this migration added.

    Deliberately narrow: it does **not** drop tables and does not touch the original
    columns, so downgrading cannot destroy pre-existing user data. Even so, prefer moving
    forward with a new migration over downgrading a database holding real users' work.
    """
    added: dict[str, list[str]] = {
        "user_problem_progress": ["created_at", "version", "deleted_at", "revision_count", "is_favorite"],
        "problem_notes": ["created_at", "version", "deleted_at"],
        "code_snippets": [
            "created_at", "version", "deleted_at", "title", "is_primary", "context_type", "context_id"
        ],
        "daily_plans": ["created_at", "version", "deleted_at", "status", "timezone", "generated_by", "notes"],
        "study_sessions": [
            "created_at", "version", "deleted_at", "session_type", "started_at", "ended_at",
            "duration_minutes", "context_id", "context_label", "note", "device_id",
        ],
    }

    for table, columns in added.items():
        if not _table_exists(table):
            continue
        for column in reversed(columns):
            if _column_exists(table, column):
                op.drop_column(table, column)
