"""Seed script for the interview curriculum.

Idempotent by **stable slug**: rerunning updates catalog metadata in place rather than
inserting duplicates, so a re-run after editing a JSON file is always safe.

Guarantees this script provides:

* Never run automatically at application startup — seeding is an explicit operator action.
* Never deletes. Problems absent from the JSON are deactivated (``is_active = false``) only
  when ``--prune`` is passed; otherwise they are left completely untouched, so a
  user's existing progress can never be orphaned.
* ``--dry-run`` reports what would change without writing.

Usage::

    .venv/bin/python -m scripts.seed_curriculum                 # seed everything
    .venv/bin/python -m scripts.seed_curriculum --dry-run       # preview
    .venv/bin/python -m scripts.seed_curriculum --only dsa      # one catalog
    .venv/bin/python -m scripts.seed_curriculum --prune         # deactivate removed rows
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import DSAProblem, DSATopic, HLDTopic, LLDTopic
from app.db.session import session_scope
from app.utils.datetime_utils import utcnow

SEED_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data"

#: Columns refreshed from JSON on every run. Deliberately excludes `created_at`.
DSA_MUTABLE = (
    "title",
    "slug",
    "external_url",
    "source",
    "difficulty",
    "primary_topic",
    "secondary_topics",
    "patterns",
    "companies",
    "problem_type",
    "order_index",
    "importance",
    "estimated_minutes",
    "is_active",
)

TOPIC_MUTABLE = (
    "title",
    "slug",
    "category",
    "description",
    "learning_objectives",
    "key_concepts",
    "external_url",
    "difficulty",
    "estimated_minutes",
    "order_index",
    "is_active",
)


@dataclass
class SeedStats:
    """Counters reported at the end of a run."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: SeedStats) -> None:
        self.inserted += other.inserted
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.deactivated += other.deactivated
        self.skipped += other.skipped
        self.errors.extend(other.errors)


def load_json(filename: str) -> list[dict[str, Any]]:
    path = SEED_DIR / filename
    if not path.exists():
        raise SystemExit(f"Seed file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{filename} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SystemExit(f"{filename} must contain a JSON array")
    return data


def validate_slug(entry: dict[str, Any], *, filename: str, index: int) -> str:
    slug = str(entry.get("slug") or "").strip()
    if not slug:
        raise SystemExit(f"{filename}[{index}] has no 'slug' — slugs are the stable key")
    # A slug must be filesystem- and URL-safe; the catalog primary key is the slug itself.
    if any(ch in slug for ch in (" ", "/", "\\", "?", "#", "&")):
        raise SystemExit(f"{filename}[{index}] slug '{slug}' contains unsafe characters")
    return slug


# --------------------------------------------------------------------------- DSA
async def seed_dsa(*, dry_run: bool, prune: bool, stats: SeedStats) -> None:
    local = SeedStats()
    entries = load_json("dsa_problems.json")
    print(f"[dsa]  loaded {len(entries)} problems from JSON")

    async with session_scope() as session:
        existing_rows = (
            await session.scalars(select(DSAProblem).order_by(DSAProblem.order_index.asc()))
        ).all()
        existing = {row.id: row for row in existing_rows}

        seen_slugs: set[str] = set()
        order_index = 0

        for index, entry in enumerate(entries):
            slug = validate_slug(entry, filename="dsa_problems.json", index=index)
            if slug in seen_slugs:
                local.errors.append(f"duplicate slug in dsa_problems.json: {slug}")
                local.skipped += 1
                continue
            seen_slugs.add(slug)

            order_index += 1

            payload: dict[str, Any] = {
                # The slug is both the primary key and the `slug` column, which is what
                # lets existing `problem_id text` rows join without migration.
                "id": slug,
                "slug": slug,
                "title": str(entry.get("title") or slug.replace("-", " ").title()),
                "external_url": entry.get("external_url"),
                "source": entry.get("source") or "leetcode",
                "difficulty": entry.get("difficulty") or "medium",
                "primary_topic": entry.get("primary_topic") or "general",
                "secondary_topics": list(entry.get("secondary_topics") or []),
                "patterns": list(entry.get("patterns") or []),
                "companies": list(entry.get("companies") or []),
                "problem_type": entry.get("problem_type") or "algorithmic",
                "order_index": int(entry.get("order_index") or order_index),
                "importance": int(entry.get("importance") or 3),
                "estimated_minutes": int(entry.get("estimated_minutes") or 30),
                "is_active": bool(entry.get("is_active", True)),
                "hints": entry.get("hints"),
            }

            current = existing.get(slug)

            if current is None:
                local.inserted += 1
                if dry_run:
                    print(f"       + insert {slug}")
                    continue
                session.add(DSAProblem(**payload))
                continue

            changed = [
                key
                for key in DSA_MUTABLE
                if key != "slug" and getattr(current, key) != payload.get(key)
            ]
            if changed:
                local.updated += 1
                if dry_run:
                    print(f"       ~ update {slug} ({', '.join(changed)})")
                    continue
                for key in changed:
                    setattr(current, key, payload.get(key))
                current.updated_at = utcnow()
            else:
                local.unchanged += 1

        # Ensure every primary topic exists in the topics table, for filter dropdowns.
        topic_slugs = sorted(
            {entry.get("primary_topic") for entry in entries if entry.get("primary_topic")}
            | {
                topic
                for entry in entries
                for topic in (entry.get("secondary_topics") or [])
                if topic
            }
        )
        existing_topics = set(await session.scalars(select(DSATopic.slug)))
        new_topics = [slug for slug in topic_slugs if slug not in existing_topics]

        if new_topics and not dry_run:
            for position, slug in enumerate(new_topics):
                session.add(
                    DSATopic(
                        id=slug,
                        slug=slug,
                        name=slug.replace("_", " ").replace("-", " ").title(),
                        order_index=position,
                    )
                )
        if new_topics:
            print(f"[dsa]  + {len(new_topics)} new topic rows")

        # Deactivate rather than delete. A delete would cascade to user progress.
        if prune:
            removed = [slug for slug in existing if slug not in seen_slugs]
            if removed:
                local.deactivated += len(removed)
                print(f"[dsa]  deactivating {len(removed)} problem(s) no longer in JSON")
                if not dry_run:
                    for slug in removed:
                        existing[slug].is_active = False
                        existing[slug].updated_at = utcnow()

        if not dry_run:
            await session.commit()

    # Fold this catalog's counters into the run totals, then report them per-catalog so
    # the numbers are unambiguous when seeding all three catalogs in one go.
    stats.merge(local)
    print(
        f"[dsa]  inserted={local.inserted} updated={local.updated} "
        f"unchanged={local.unchanged} deactivated={local.deactivated}"
    )


# ------------------------------------------------------------------- LLD / HLD
async def seed_topics(
    *, kind: str, dry_run: bool, prune: bool, stats: SeedStats
) -> None:
    local = SeedStats()
    if kind == "lld":
        model = LLDTopic
        filename = "lld_topics.json"
    else:
        model = HLDTopic
        filename = "hld_topics.json"

    entries = load_json(filename)
    print(f"[{kind}]  loaded {len(entries)} topics from JSON")

    async with session_scope() as session:
        existing_rows = (await session.scalars(select(model))).all()
        existing = {row.slug: row for row in existing_rows}

        seen: set[str] = set()
        order_index = 0

        for index, entry in enumerate(entries):
            slug = validate_slug(entry, filename=filename, index=index)
            if slug in seen:
                local.errors.append(f"duplicate slug in {filename}: {slug}")
                local.skipped += 1
                continue
            seen.add(slug)
            order_index += 1

            payload = {
                "title": str(entry.get("title") or slug.replace("-", " ").title()),
                "slug": slug,
                "category": entry.get("category") or (
                    "fundamentals" if kind == "lld" else "system_design"
                ),
                "description": entry.get("description"),
                "learning_objectives": list(entry.get("learning_objectives") or []),
                "key_concepts": list(entry.get("key_concepts") or []),
                "external_url": entry.get("external_url"),
                "difficulty": entry.get("difficulty") or (
                    "medium" if kind == "lld" else "hard"
                ),
                "estimated_minutes": int(
                    entry.get("estimated_minutes") or (60 if kind == "lld" else 90)
                ),
                "order_index": int(entry.get("order_index") or order_index),
                "is_active": bool(entry.get("is_active", True)),
            }

            current = existing.get(slug)

            if current is None:
                local.inserted += 1
                if dry_run:
                    print(f"       + insert {slug}")
                    continue
                session.add(model(**payload))
                continue

            changed = [
                key
                for key in TOPIC_MUTABLE
                if key != "slug" and getattr(current, key) != payload.get(key)
            ]
            if changed:
                local.updated += 1
                if dry_run:
                    print(f"       ~ update {slug} ({', '.join(changed)})")
                    continue
                for key in changed:
                    setattr(current, key, payload.get(key))
                current.updated_at = utcnow()
            else:
                local.unchanged += 1

        if prune:
            removed = [slug for slug in existing if slug not in seen]
            if removed:
                local.deactivated += len(removed)
                print(f"[{kind}]  deactivating {len(removed)} topic(s) no longer in JSON")
                if not dry_run:
                    for slug in removed:
                        existing[slug].is_active = False
                        existing[slug].updated_at = utcnow()

        if not dry_run:
            await session.commit()

    stats.merge(local)
    print(
        f"[{kind}]  inserted={local.inserted} updated={local.updated} "
        f"unchanged={local.unchanged} deactivated={local.deactivated}"
    )


# ------------------------------------------------------------------------ report
async def report() -> None:
    async with session_scope() as session:
        async def count(model) -> int:
            return int(await session.scalar(select(func.count()).select_from(model)) or 0)

        print()
        print("=" * 64)
        print("CATALOG TOTALS")
        print("=" * 64)
        print(f"dsa_problems : {await count(DSAProblem)}")
        print(f"dsa_topics   : {await count(DSATopic)}")
        print(f"lld_topics   : {await count(LLDTopic)}")
        print(f"hld_topics   : {await count(HLDTopic)}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["dsa", "lld", "hld"], default=None)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Deactivate catalog rows missing from JSON (never deletes)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_connectable:
        print("DATABASE_URL is not configured. Set it in .env before seeding.")
        return 1

    started = datetime.now()
    stats = SeedStats()

    if args.dry_run:
        print("DRY RUN — no changes will be written\n")

    if args.only in (None, "dsa"):
        await seed_dsa(dry_run=args.dry_run, prune=args.prune, stats=stats)
    if args.only in (None, "lld"):
        await seed_topics(kind="lld", dry_run=args.dry_run, prune=args.prune, stats=stats)
    if args.only in (None, "hld"):
        await seed_topics(kind="hld", dry_run=args.dry_run, prune=args.prune, stats=stats)

    elapsed = (datetime.now() - started).total_seconds()

    print()
    print("=" * 64)
    print(f"SUMMARY  ({elapsed:.2f}s)")
    print("=" * 64)
    print(f"inserted     : {stats.inserted}")
    print(f"updated      : {stats.updated}")
    print(f"unchanged    : {stats.unchanged}")
    print(f"deactivated  : {stats.deactivated}")
    print(f"skipped      : {stats.skipped}")

    if stats.errors:
        print(f"\nWARNINGS ({len(stats.errors)}):")
        for error in stats.errors[:20]:
            print(f"  - {error}")

    if not args.dry_run:
        await report()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
