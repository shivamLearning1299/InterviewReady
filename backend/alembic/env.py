"""Alembic migration environment (async SQLAlchemy).

Design decisions worth knowing before editing this file:

* **Async engine.** Alembic runs through ``connection.run_sync`` against an asyncpg engine,
  because the application's models and the migrations must use the same driver stack.
* **Direct URL.** Migrations use ``DATABASE_URL_DIRECT`` (port 5432) rather than the
  runtime pooler URL, because DDL through PgBouncer/Supavisor transaction pooling is
  unreliable and DDL cannot be prepared-statement cached.
* **Supabase schemas are excluded.** ``include_object`` filters out ``auth``, ``storage``,
  ``extensions`` and the rest, so autogenerate can never propose dropping or altering
  objects owned by the platform.
* **Destructive operations are blocked by default.** ``process_revision_directives``
  refuses to emit ``DROP TABLE`` / ``DROP COLUMN`` unless the operator explicitly sets
  ``ALLOW_DESTRUCTIVE_MIGRATIONS=1``. Per the project requirement, existing tables and
  user data must never be dropped automatically.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the `app` package importable when Alembic is invoked from the backend directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.db.base import Base
from app.db import models as _models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# ``set_main_option`` writes through configparser, which treats ``%`` as an interpolation
# marker. Supabase passwords are frequently URL-encoded (``%40`` for ``@``), which would
# otherwise abort with "invalid interpolation syntax". Doubling the percent is
# configparser's own escape, so the value round-trips to the real URL.
config.set_main_option("sqlalchemy.url", settings.migration_database_url.replace("%", "%%"))

target_metadata = Base.metadata

# Schemas owned by Supabase (or by extensions). Alembic must never touch these.
EXCLUDED_SCHEMAS: frozenset[str] = frozenset(
    {
        "auth",
        "storage",
        "realtime",
        "extensions",
        "graphql",
        "graphql_public",
        "vault",
        "supabase_migrations",
        "supabase_functions",
        "pgbouncer",
        "cron",
        "net",
        "pgsodium",
        "pgsodium_masks",
        "information_schema",
        "pg_catalog",
        "pg_toast",
    }
)

# Tables Alembic should not manage even inside `public`.
#
# * `spatial_ref_sys` and `schema_migrations` are Supabase/extension bookkeeping.
# * `alembic_version` is Alembic's own version table.
# * `design_topics` is a PRE-EXISTING user-owned table that the API deliberately does not
#   map: its shape (one row per design topic with flat `notes`/`code`/`requirements`
#   columns) cannot represent HLD's 13 sections or LLD's class-responsibility breakdown.
#   The normalised `lld_*`/`hld_*` tables replace it, and
#   `scripts/backfill_design_topics.py` copies the data across. It must never be dropped.
EXCLUDED_TABLES: frozenset[str] = frozenset(
    {
        "spatial_ref_sys",
        "schema_migrations",
        "alembic_version",
        "design_topics",
    }
)

# Pre-existing tables that the ORM maps but that Alembic must NOT try to autogenerate
# diffs for.
#
# Autogenerate only knows what the models declare. For these tables the models
# intentionally under-declare reality — they carry no `auth.users(id)` foreign key, and
# some columns are narrower (`varchar(n)` vs `text`) or differently typed than the live
# column. Without this exclusion, autogenerate proposes
#   * dropping the `user_id -> auth.users(id)` foreign keys, and
#   * narrowing `text` columns to `varchar(n)`,
# both of which would alter real user data for no benefit.
#
# Changes to these tables are therefore written by hand in migration ``0001`` (and any
# future hand-written migration), where each step is guarded and backfilled deliberately.
AUTOGENERATE_EXCLUDED_TABLES: frozenset[str] = frozenset(
    {
        "user_problem_progress",
        "problem_notes",
        "code_snippets",
        "daily_plans",
        "study_sessions",
    }
)


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Filter the objects Alembic may consider.

    Returning ``False`` for a pre-existing table also suppresses *modifications* to it,
    which is what prevents autogenerate from proposing to drop its existing foreign keys
    or narrow its columns.
    """
    schema = getattr(obj, "schema", None)
    if schema and schema in EXCLUDED_SCHEMAS:
        return False

    if type_ == "table" and name in EXCLUDED_TABLES:
        return False

    if type_ == "table" and name in AUTOGENERATE_EXCLUDED_TABLES:
        return False

    # Never let autogenerate manage Supabase's own migration bookkeeping tables.
    return not (type_ == "table" and name and name.startswith("supabase_"))


def _is_destructive(op: Any) -> str | None:
    """Return a description when a migration op would destroy existing objects."""
    op_name = type(op).__name__.lower()
    if op_name in {"droptableop", "dropcolumnop", "dropconstraintop", "dropindexop"}:
        target = (
            getattr(op, "table_name", None)
            or getattr(op, "index_name", None)
            or getattr(op, "constraint_name", None)
            or "?"
        )
        return f"{op_name} on {target}"
    return None


def process_revision_directives(
    context_: Any,
    revision: Any,
    directives: list[Any],
) -> None:
    """Block destructive autogenerated operations unless explicitly allowed."""
    if os.getenv("ALLOW_DESTRUCTIVE_MIGRATIONS") == "1":
        return

    destructive: list[str] = []
    for directive in directives:
        for op in getattr(directive, "upgrade_ops", None).ops if getattr(directive, "upgrade_ops", None) else []:
            found = _is_destructive(op)
            if found:
                destructive.append(found)

    if destructive:
        raise RuntimeError(
            "Refusing to generate a destructive migration:\n  "
            + "\n  ".join(destructive)
            + "\n\nThis project must never drop existing Supabase tables or user data.\n"
            "Write the additive migration by hand, or set ALLOW_DESTRUCTIVE_MIGRATIONS=1 "
            "if you are certain."
        )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=settings.migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="public",
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
        include_object=include_object,
        version_table="alembic_version",
        version_table_schema="public",
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.migration_database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # Same pooler workaround as the application engine.
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "server_settings": {"application_name": "interviewready-alembic"},
        },
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
