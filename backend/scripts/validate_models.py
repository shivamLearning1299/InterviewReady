"""Validate that every ORM model configures cleanly and produces the expected DDL.

Run with::

    .venv/bin/python -m scripts.validate_models

This catches the class of errors that otherwise surface only at runtime or during a
migration: unresolved relationship targets, ambiguous foreign keys, duplicate constraint
names, and columns with no PostgreSQL type.
"""

from __future__ import annotations

import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from app.db.base import Base
from app.db.models import *  # noqa: F403  (import side effects register the models)


def main() -> int:
    tables = sorted(Base.metadata.tables)
    print(f"Registered {len(tables)} tables")

    try:
        configure_mappers()
    except Exception as exc:
        print(f"FAIL mapper configuration: {exc}")
        return 1

    dialect = postgresql.dialect()
    failures: list[str] = []

    for name in tables:
        table = Base.metadata.tables[name]
        try:
            str(CreateTable(table).compile(dialect=dialect))
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue

        columns = {col.name for col in table.columns}
        required = {"id", "created_at", "updated_at", "version"}
        if name not in {"sync_changes", "sync_mutations", "user_activity_days"}:
            missing = required - columns
            if missing:
                print(f"  note: {name} is missing {sorted(missing)}")

    if failures:
        print("\nFAILED tables:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("All tables compiled successfully.")
    for name in tables:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
