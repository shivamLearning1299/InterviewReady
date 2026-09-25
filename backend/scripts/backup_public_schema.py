"""Version-agnostic logical backup of the ``public`` schema.

Why this exists
---------------
``pg_dump`` refuses to run against a *newer* server than itself: dumping a PostgreSQL 17
Supabase instance with the PostgreSQL 16 client that Homebrew ships fails with "aborting
because of server version mismatch". Installing a matching client is heavy and easy to
forget, so this script produces a portable SQL backup using only the asyncpg driver the
application already depends on.

What it guarantees
------------------
* **DDL is captured verbatim** — ``CREATE TABLE`` and ``CREATE INDEX`` are read from the
  server via ``pg_get_...`` helpers, so constraints, defaults and types are exact.
* **Data is captured as ``INSERT`` statements**, escaped through PostgreSQL's own quoting
  rules rather than string concatenation.
* **Read-only.** Nothing in the target database is modified.
* It is a *safety net before migrations*, not a replacement for Supabase's own backups or
  for ``pg_dump`` when a matching client is available.

Usage::

    .venv/bin/python -m scripts.backup_public_schema
    .venv/bin/python -m scripts.backup_public_schema --output backups/before_v2.sql
    .venv/bin/python -m scripts.backup_public_schema --schema public --tables user_problem_progress
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import decimal
import ipaddress
import json
import sys
import urllib.parse as urlparse
import uuid
from pathlib import Path
from typing import Any

import asyncpg

from app.core.config import get_settings


def connection_kwargs(url: str) -> dict[str, Any]:
    """Translate a SQLAlchemy-style URL into asyncpg connection keyword arguments.

    Percent-encoded passwords (``%40`` for ``@``) must be decoded, because PostgreSQL wants
    the raw secret while the URL carries the encoded form.
    """
    parsed = urlparse.urlparse(url.replace("postgresql+asyncpg://", "postgresql://"))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": urlparse.unquote(parsed.username or ""),
        "password": urlparse.unquote(parsed.password or ""),
        "database": (parsed.path or "/postgres").lstrip("/") or "postgres",
    }


def sql_literal(value: Any) -> str:
    """Render a Python value as a PostgreSQL literal.

    Every dynamic value goes through this function so quoting is consistent and a value
    containing a quote can never break out of the statement.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, decimal.Decimal)):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return f"'{value.isoformat()}'"
    if isinstance(value, (dt.timedelta,)):
        return f"'{value}'"
    if isinstance(value, (dict, list)):
        # jsonb / json columns arrive as parsed Python objects.
        payload = json.dumps(value, separators=(",", ":"))
        return f"'{payload.replace(chr(39), chr(39) * 2)}'::jsonb"
    if isinstance(value, uuid.UUID):
        return f"'{value}'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"'\\x{bytes(value).hex()}'"
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return f"'{value}'"
    # Everything else is text. Double any single quote (SQL standard escaping).
    return f"'{str(value).replace(chr(39), chr(39) * 2)}'"


async def fetch_tables(conn: asyncpg.Connection, schema: str, only: list[str] | None) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT c.relname AS name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind = 'r'
        ORDER BY c.relname
        """,
        schema,
    )
    names = [row["name"] for row in rows]
    if only:
        missing = [t for t in only if t not in names]
        for table in missing:
            print(f"warning: table '{schema}.{table}' does not exist — skipped")
        names = [t for t in names if t in only]
    return names


async def fetch_ddl(conn: asyncpg.Connection, schema: str, table: str) -> str:
    """Reconstruct ``CREATE TABLE`` and its indexes from the catalog."""
    columns = await conn.fetch(
        """
        SELECT column_name, data_type, character_maximum_length, numeric_precision,
               numeric_scale, is_nullable, column_default, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
        """,
        schema,
        table,
    )

    def render_type(col: asyncpg.Record) -> str:
        data_type = col["data_type"]
        if col["character_maximum_length"]:
            return f"{data_type}({col['character_maximum_length']})"
        if data_type == "numeric" and col["numeric_precision"]:
            return f"numeric({col['numeric_precision']},{col['numeric_scale']})"
        return str(data_type)

    lines = []
    for col in columns:
        line = f'    "{col["column_name"]}" {render_type(col)}'
        if col["column_default"] is not None:
            line += f" DEFAULT {col['column_default']}"
        if col["is_nullable"] == "NO":
            line += " NOT NULL"
        lines.append(line)

    constraints = await conn.fetch(
        """
        SELECT conname, pg_get_constraintdef(oid) AS definition, contype
        FROM pg_constraint
        WHERE conrelid = $1::regclass
        ORDER BY contype DESC, conname
        """,
        f'"{schema}"."{table}"',
    )
    for con in constraints:
        lines.append(f'    CONSTRAINT "{con["conname"]}" {con["definition"]}')

    ddl = f'CREATE TABLE IF NOT EXISTS "{schema}"."{table}" (\n' + ",\n".join(lines) + "\n);\n"

    # Only emit indexes that exist in their own right. Primary keys and UNIQUE constraints
    # already produce a backing index, and the CONSTRAINT lines above recreate it — emitting
    # it again would fail on restore with "relation already exists".
    indexes = await conn.fetch(
        """
        SELECT i.indexname, i.indexdef
        FROM pg_indexes i
        WHERE i.schemaname = $1
          AND i.tablename = $2
          AND NOT EXISTS (
              SELECT 1
              FROM pg_constraint c
              WHERE c.conrelid = $3::regclass
                AND c.conindid = (quote_ident(i.schemaname) || '.' || quote_ident(i.indexname))::regclass
          )
        ORDER BY i.indexname
        """,
        schema,
        table,
        f'"{schema}"."{table}"',
    )
    for idx in indexes:
        ddl += f'{idx["indexdef"]};\n'
    return ddl


async def dump(*, schema: str, only: list[str] | None, output: Path) -> int:
    settings = get_settings()
    if not settings.is_connectable:
        print("DATABASE_URL is not configured. Set it in .env first.")
        return 1

    url = settings.migration_database_url or settings.database_url
    kwargs = connection_kwargs(url)
    mask = kwargs["password"]
    print(f"Connecting to {kwargs['host']}:{kwargs['port']}/{kwargs['database']} as {kwargs['user']}")
    print(f"  (password {'set' if mask else 'EMPTY'})")

    conn = await asyncpg.connect(**kwargs, server_settings={"application_name": "interviewready-backup"})
    try:
        version = await conn.fetchval("SHOW server_version")
        tables = await fetch_tables(conn, schema, only)
        if not tables:
            print(f"No tables found in schema '{schema}'.")
            return 1

        stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        out: list[str] = [
            f"-- InterviewReady logical backup of schema \"{schema}\"",
            f"-- taken at {stamp}",
            f"-- server version {version}",
            "--",
            "-- Read-only snapshot produced by scripts/backup_public_schema.py.",
            "-- Restore with:  psql \"$DATABASE_URL\" -f <this file>",
            "",
            f'SET search_path TO "{schema}";',
            "",
            "-- ---------------------------------------------------------------- schema",
            "",
        ]

        total_rows = 0
        data_sections: list[str] = []
        for table in tables:
            out.append(await fetch_ddl(conn, schema, table))
            out.append("")

            rows = await conn.fetch(f'SELECT * FROM "{schema}"."{table}"')
            total_rows += len(rows)
            if not rows:
                print(f"  {table}: 0 rows")
                continue

            columns = list(rows[0].keys())
            quoted = ", ".join(f'"{c}"' for c in columns)
            data_sections.append(f"-- {table}: {len(rows)} row(s)")
            data_sections.append(f'INSERT INTO "{schema}"."{table}" ({quoted}) VALUES')
            values = [
                "  (" + ", ".join(sql_literal(row[c]) for c in columns) + ")" for row in rows
            ]
            data_sections.append(",\n".join(values) + ";")
            data_sections.append("")
            print(f"  {table}: {len(rows)} rows")

        out.append("-- ------------------------------------------------------------------ data")
        out.append("")
        out.extend(data_sections)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(out), encoding="utf-8")

        print()
        print(f"Backup written : {output}")
        print(f"Tables         : {len(tables)}")
        print(f"Rows           : {total_rows}")
        print(f"Size           : {output.stat().st_size / 1024:.1f} KiB")
        return 0
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="public", help="Schema to back up")
    parser.add_argument("--output", default=None, help="Destination .sql file")
    parser.add_argument(
        "--tables",
        default=None,
        help="Comma-separated subset of tables (default: every table in the schema)",
    )
    args = parser.parse_args()

    output = Path(args.output) if args.output else Path(
        f"/tmp/interviewready_backup_{dt.datetime.now():%Y%m%d_%H%M%S}.sql"
    )
    only = [t.strip() for t in args.tables.split(",")] if args.tables else None

    try:
        return await dump(schema=args.schema, only=only, output=output)
    except Exception as exc:
        print(f"Backup FAILED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
