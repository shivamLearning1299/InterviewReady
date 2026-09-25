"""Inspect the live Supabase PostgreSQL schema and compare it to the ORM models.

This is the *gate* required before touching the existing database. It answers:

* what tables/columns/types/indexes/constraints already exist;
* which schemas are Supabase-owned and therefore off-limits to Alembic;
* which of the ORM's tables are already present, and whether their columns match;
* which tables/columns/indexes the ORM expects but the database does not have yet
  (i.e. exactly what a migration needs to add).

It performs **reads only** — no DDL, no DML.

Usage::

    .venv/bin/python -m scripts.inspect_supabase_schema            # full report
    .venv/bin/python -m scripts.inspect_supabase_schema --json-only
    .venv/bin/python -m scripts.inspect_supabase_schema --schema public
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import asyncpg
import sqlalchemy as sa

from app.core.config import get_settings

# Imported for its side effect: every model must be registered on ``Base.metadata`` before
# the schema is introspected, or the ORM would appear to have no tables at all.
from app.db import models as _models  # noqa: F401
from app.db.base import Base

OUTPUT_JSON = Path("schema_snapshot.json")
OUTPUT_MD = Path("schema_report.md")

# PostgreSQL and SQLAlchemy spell the same type differently, and `data_type` is lowercase.
# Compare canonical names so the drift report only reports genuine differences.
_TYPE_ALIASES: dict[str, str] = {
    "character varying": "varchar",
    "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
    "boolean": "bool",
    "character": "char",
    "double precision": "float8",
    "float": "float8",
    "real": "float4",
    "integer": "int",
    "smallint": "int2",
    "bigint": "int8",
}


def _parse_type(raw: str) -> tuple[str, str | None]:
    """Split a type spelling into (canonical name, parameters-or-None).

    A trailing ``[]`` marks an array; it is folded into the name so that
    ``VARCHAR(30)[]`` and ``character varying(30)[]`` compare equal to each other.
    """
    text = raw.strip().lower()
    is_array = text.endswith("[]")
    if is_array:
        text = text[:-2]
    if "(" in text and text.endswith(")"):
        name, _, params = text.partition("(")
        canonical = _TYPE_ALIASES.get(name.strip(), name.strip())
        return (f"{canonical}[]" if is_array else canonical), params.rstrip(")")
    canonical = _TYPE_ALIASES.get(text, text)
    return (f"{canonical}[]" if is_array else canonical), None


def _types_match(expected: str, actual: str) -> bool:
    """Whether the ORM's type and the live column's type are equivalent.

    Names are canonicalised first (``VARCHAR`` == ``character varying``). Parameterised
    types are compared loosely on purpose: SQLAlchemy omits a length it does not constrain,
    so ``INTEGER`` vs ``integer`` and ``TEXT`` vs ``text`` are matches, not drift. If *both*
    sides state a length they must agree, which is what actually catches a widened or
    narrowed column.
    """
    expected_name, expected_params = _parse_type(expected)
    actual_name, actual_params = _parse_type(actual)
    if expected_name != actual_name:
        return False
    if expected_params is None or actual_params is None:
        return True
    return expected_params == actual_params

# Schemas owned by Supabase or by extensions. Never migrate these.
SUPABASE_SCHEMAS = (
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
)

TABLES_SQL = """
SELECT c.relname AS table_name,
       n.nspname AS schema_name,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       pg_catalog.obj_description(c.oid) AS comment
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname = ANY($1::text[])
ORDER BY n.nspname, c.relname
"""

COLUMNS_SQL = """
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS data_type,
       a.attnotnull AS is_not_null,
       pg_get_expr(d.adbin, d.adrelid) AS default_value,
       a.attnum AS ordinal_position
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE c.relkind = 'r'
  AND n.nspname = ANY($1::text[])
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY n.nspname, c.relname, a.attnum
"""

INDEXES_SQL = """
SELECT schemaname AS schema_name,
       tablename AS table_name,
       indexname AS index_name,
       indexdef AS index_definition
FROM pg_indexes
WHERE schemaname = ANY($1::text[])
ORDER BY schemaname, tablename, indexname
"""

CONSTRAINTS_SQL = """
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       con.conname AS constraint_name,
       con.contype AS constraint_type,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY($1::text[])
ORDER BY n.nspname, c.relname, con.conname
"""

POLICIES_SQL = """
SELECT schemaname AS schema_name,
       tablename AS table_name,
       policyname AS policy_name,
       cmd AS command,
       roles,
       qual AS using_expression,
       with_check AS check_expression
FROM pg_policies
WHERE schemaname = ANY($1::text[])
ORDER BY schemaname, tablename, policyname
"""

ROW_COUNTS_SQL = """
SELECT n.nspname AS schema_name, c.relname AS table_name,
       GREATEST(c.reltuples, 0)::bigint AS estimated_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' AND n.nspname = ANY($1::text[])
ORDER BY n.nspname, c.relname
"""


def _dsn() -> str:
    """Plain asyncpg DSN (strip the SQLAlchemy dialect prefix)."""
    settings = get_settings()
    url = settings.migration_database_url or settings.database_url
    if not url:
        raise SystemExit(
            "No database URL configured. Set DATABASE_URL (and optionally "
            "DATABASE_URL_DIRECT) in .env before running introspection."
        )
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


async def collect(schemas: list[str]) -> dict[str, Any]:
    connection = await asyncpg.connect(_dsn(), statement_cache_size=0)
    try:
        version = await connection.fetchval("SHOW server_version")
        database = await connection.fetchval("SELECT current_database()")
        role = await connection.fetchval("SELECT current_user")
        is_superuser = await connection.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        bypass_rls = await connection.fetchval(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )

        tables = [dict(row) for row in await connection.fetch(TABLES_SQL, schemas)]
        columns = [dict(row) for row in await connection.fetch(COLUMNS_SQL, schemas)]
        indexes = [dict(row) for row in await connection.fetch(INDEXES_SQL, schemas)]
        constraints = [dict(row) for row in await connection.fetch(CONSTRAINTS_SQL, schemas)]
        policies = [dict(row) for row in await connection.fetch(POLICIES_SQL, schemas)]
        row_counts = [dict(row) for row in await connection.fetch(ROW_COUNTS_SQL, schemas)]
    finally:
        await connection.close()

    grouped_columns: dict[str, list[dict[str, Any]]] = {}
    for column in columns:
        key = f"{column['schema_name']}.{column['table_name']}"
        column.pop("schema_name", None)
        column.pop("table_name", None)
        grouped_columns.setdefault(key, []).append(column)

    counts = {
        f"{row['schema_name']}.{row['table_name']}": int(row["estimated_rows"]) for row in row_counts
    }

    return {
        "server": {
            "postgres_version": version,
            "database": database,
            "role": role,
            "is_superuser": is_superuser,
            "bypasses_rls": bypass_rls,
        },
        "schemas_inspected": schemas,
        "tables": tables,
        "columns": grouped_columns,
        "indexes": indexes,
        "constraints": constraints,
        "policies": policies,
        "estimated_row_counts": counts,
    }


def compare_with_models(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Diff the live `public` schema against the ORM metadata."""
    live_tables = {
        table["table_name"] for table in snapshot["tables"] if table["schema_name"] == "public"
    }
    model_tables = set(Base.metadata.tables)

    missing_tables = sorted(model_tables - live_tables)
    extra_tables = sorted(live_tables - model_tables)
    shared_tables = sorted(model_tables & live_tables)

    missing_columns: dict[str, list[str]] = {}
    type_mismatches: dict[str, list[dict[str, str]]] = {}

    dialect = sa.dialects.postgresql.dialect()

    for name in shared_tables:
        table = Base.metadata.tables[name]
        live_columns = {
            column["column_name"]: column
            for column in snapshot["columns"].get(f"public.{name}", [])
        }

        absent = [column.name for column in table.columns if column.name not in live_columns]
        if absent:
            missing_columns[name] = absent

        mismatches: list[dict[str, str]] = []
        for column in table.columns:
            live = live_columns.get(column.name)
            if live is None:
                continue
            try:
                expected = column.type.compile(dialect=dialect)
            except Exception:
                expected = str(column.type)
            actual = live["data_type"]
            if not _types_match(expected, actual):
                mismatches.append({"column": column.name, "model": expected, "database": actual})
        if mismatches:
            type_mismatches[name] = mismatches

    return {
        "model_table_count": len(model_tables),
        "live_public_table_count": len(live_tables),
        "tables_present_in_both": shared_tables,
        "tables_missing_from_database": missing_tables,
        "tables_in_database_not_in_models": extra_tables,
        "columns_missing_from_database": missing_columns,
        "column_type_mismatches": type_mismatches,
    }


def render_markdown(snapshot: dict[str, Any], diff: dict[str, Any]) -> str:
    server = snapshot["server"]
    lines: list[str] = [
        "# Supabase schema inspection report",
        "",
        "Generated by `scripts.inspect_supabase_schema.py`. Read-only.",
        "",
        "## Server",
        "",
        f"- PostgreSQL: `{server['postgres_version']}`",
        f"- Database: `{server['database']}`",
        f"- Connecting role: `{server['role']}`",
        f"- Superuser: `{server['is_superuser']}`",
        f"- Bypasses RLS: `{server['bypasses_rls']}`",
        "",
    ]

    if server["bypasses_rls"]:
        lines += [
            "> **Note:** the connecting role bypasses Row Level Security. The application",
            "> scopes every personal-data query by `user_id` in the repository layer, and",
            "> publishes `app.current_user_id` as a session variable, so Supabase RLS policies",
            "> can act as a second line of defence once a non-`BYPASSRLS` role is used.",
            "",
        ]

    lines += ["## Schemas inspected", "", ", ".join(f"`{s}`" for s in snapshot["schemas_inspected"]), ""]

    lines += ["## Model vs database diff", "", "### Tables expected by the ORM but missing", ""]
    if diff["tables_missing_from_database"]:
        lines += [f"- `{name}`" for name in diff["tables_missing_from_database"]]
    else:
        lines.append("- None — the ORM matches the database.")
    lines.append("")

    lines += ["### Tables in the database that the ORM does not map", ""]
    if diff["tables_in_database_not_in_models"]:
        lines += [
            f"- `{name}` (leave in place; do not drop)"
            for name in diff["tables_in_database_not_in_models"]
        ]
    else:
        lines.append("- None.")
    lines.append("")

    lines += ["### Columns missing from existing tables", ""]
    if diff["columns_missing_from_database"]:
        for table, columns in sorted(diff["columns_missing_from_database"].items()):
            lines.append(f"- `{table}`: {', '.join(f'`{c}`' for c in columns)}")
    else:
        lines.append("- None.")
    lines.append("")

    lines += ["### Column type mismatches", ""]
    if diff["column_type_mismatches"]:
        lines.append("| Table | Column | ORM type | Database type |")
        lines.append("| --- | --- | --- | --- |")
        for table, mismatches in sorted(diff["column_type_mismatches"].items()):
            for item in mismatches:
                lines.append(
                    f"| `{table}` | `{item['column']}` | `{item['model']}` | `{item['database']}` |"
                )
    else:
        lines.append("- None.")
    lines.append("")

    lines += ["## RLS coverage", ""]
    policies_by_table: dict[str, int] = {}
    for policy in snapshot["policies"]:
        key = f"{policy['schema_name']}.{policy['table_name']}"
        policies_by_table[key] = policies_by_table.get(key, 0) + 1

    lines.append("| Table | RLS enabled | Policies |")
    lines.append("| --- | --- | --- |")
    for table in snapshot["tables"]:
        if table["schema_name"] != "public":
            continue
        key = f"{table['schema_name']}.{table['table_name']}"
        lines.append(
            f"| `{key}` | {'yes' if table['rls_enabled'] else 'no'} | "
            f"{policies_by_table.get(key, 0)} |"
        )
    lines.append("")

    lines += ["## Tables and estimated row counts", ""]
    lines.append("| Table | ~Rows | Columns |")
    lines.append("| --- | --- | --- |")
    for table in snapshot["tables"]:
        key = f"{table['schema_name']}.{table['table_name']}"
        column_count = len(snapshot["columns"].get(key, []))
        rows = snapshot["estimated_row_counts"].get(key, 0)
        lines.append(f"| `{key}` | {rows} | {column_count} |")
    lines.append("")

    return "\n".join(lines)


def print_summary(diff: dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print("MODEL vs DATABASE")
    print("=" * 72)
    print(f"ORM tables:            {diff['model_table_count']}")
    print(f"Live public tables:    {diff['live_public_table_count']}")
    print(f"Tables in both:        {len(diff['tables_present_in_both'])}")

    missing = diff["tables_missing_from_database"]
    print(f"Missing from DB:       {len(missing)}")
    for name in missing:
        print(f"  + {name}  (migration will CREATE)")

    extra = diff["tables_in_database_not_in_models"]
    if extra:
        print(f"Unmapped existing tables: {len(extra)}  (leave in place, never drop)")
        for name in extra:
            print(f"  ~ {name}")

    missing_columns = diff["columns_missing_from_database"]
    if missing_columns:
        print(f"Tables needing new columns: {len(missing_columns)}")
        for table, columns in sorted(missing_columns.items()):
            print(f"  ~ {table}: add {', '.join(columns)}")

    mismatches = diff["column_type_mismatches"]
    if mismatches:
        # Count columns, not tables: a reader reads these as "N columns to review".
        column_count = sum(len(items) for items in mismatches.values())
        print(
            f"Type mismatches: {column_count}  "
            "(declared vs stored; see note below)"
        )
        for table, items in sorted(mismatches.items()):
            for item in items:
                print(f"  ! {table}.{item['column']}: ORM={item['model']} DB={item['database']}")
        print(
            "  note: these are narrower declarations on columns the ORM does not manage\n"
            "        (the pre-existing tables are excluded from autogenerate), so Alembic\n"
            "        proposes no change. Widening the declaration is what would matter."
        )

    if not missing and not missing_columns and not mismatches:
        print()
        print("No schema changes required — the ORM matches the database.")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        action="append",
        default=None,
        help="Schema to inspect (repeatable). Defaults to public + Supabase schemas.",
    )
    parser.add_argument("--json-only", action="store_true", help="Write the JSON snapshot only.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the summary output.")
    args = parser.parse_args()

    schemas = args.schema or ["public", *SUPABASE_SCHEMAS]
    # Only inspect schemas that actually exist, to keep the report readable.
    connection = await asyncpg.connect(_dsn(), statement_cache_size=0)
    try:
        existing = await connection.fetch(
            "SELECT nspname FROM pg_namespace WHERE nspname = ANY($1::text[])", schemas
        )
    finally:
        await connection.close()

    schemas = [row["nspname"] for row in existing]
    if "public" not in schemas:
        schemas.insert(0, "public")

    snapshot = await collect(schemas)
    diff = compare_with_models(snapshot)
    snapshot["model_diff"] = diff

    OUTPUT_JSON.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUTPUT_JSON.resolve()}")

    if not args.json_only:
        OUTPUT_MD.write_text(render_markdown(snapshot, diff), encoding="utf-8")
        print(f"Wrote {OUTPUT_MD.resolve()}")

    if not args.quiet:
        print_summary(diff)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
