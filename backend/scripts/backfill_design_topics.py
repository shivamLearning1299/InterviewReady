"""One-way, idempotent backfill from the pre-existing ``design_topics`` table.

Background
----------
The Supabase database already contained ``public.design_topics``: one row per design topic
owned by a user, with flat ``notes``/``code``/``requirements``/``architecture``/``tradeoffs``
columns and an ``area`` discriminator.

That shape cannot represent either curriculum the API serves — HLD needs 13 distinct design
sections and LLD needs a class-responsibility breakdown — so the application uses the
normalised ``lld_topics``/``lld_progress``/``lld_notes`` and
``hld_topics``/``hld_progress``/``hld_notes`` tables instead, and ``design_topics`` is left
untouched.

This script copies the existing work across so nothing is orphaned.

Guarantees
----------
* **Read-only on the source.** ``design_topics`` is never modified or deleted.
* **Idempotent.** Rows are matched to a seeded curriculum topic and the corresponding
  progress/notes rows are only created when absent, so rerunning is a no-op.
* **Dry-run first.** ``--dry-run`` reports exactly what would be created, with accurate
  counters and no writes.
* **Never pollutes the shared curriculum.** ``lld_topics``/``hld_topics`` are global catalogs
  read by every user, so this script never inserts into them. A legacy row that matches no
  seeded topic is *skipped and reported*, never force-fitted and never silently dropped.

Usage::

    .venv/bin/python -m scripts.backfill_design_topics --dry-run
    .venv/bin/python -m scripts.backfill_design_topics
    .venv/bin/python -m scripts.backfill_design_topics --user <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import HLDNote, HLDProgress, HLDTopic, LLDNote, LLDProgress, LLDTopic
from app.db.session import session_scope

#: Legacy `area` values that belong to the low-level design curriculum.
LLD_AREAS = {
    "lld",
    "lld_",
    "low_level_design",
    "low-level-design",
    "low level design",
    "object_oriented",
    "object-oriented",
    "oops",
    "ooad",
}
#: Legacy `area` values that belong to the high-level design curriculum.
HLD_AREAS = {
    "hld",
    "hld_",
    "high_level_design",
    "high-level-design",
    "high level design",
    "system_design",
    "system-design",
    "sysdesign",
    "sys_design",
}

#: Legacy free-text `status` mapped onto the API's status vocabulary.
STATUS_MAP = {
    "not_started": "not_started",
    "not started": "not_started",
    "todo": "not_started",
    "pending": "not_started",
    "backlog": "not_started",
    "learning": "learning",
    "in_progress": "learning",
    "in progress": "learning",
    "started": "learning",
    "completed": "completed",
    "complete": "completed",
    "done": "completed",
    "needs_revision": "needs_revision",
    "needs revision": "needs_revision",
    "review": "needs_revision",
    "revision": "needs_revision",
    "mastered": "mastered",
}

_SOURCE_COLUMNS = """
    SELECT id, user_id, area, title, status, notes, code,
           requirements, architecture, tradeoffs,
           last_reviewed_date, next_revision_date, updated_at
    FROM public.design_topics
"""


@dataclass
class BackfillStats:
    source_rows: int = 0
    matched: int = 0
    matched_fuzzy: int = 0
    progress_created: int = 0
    progress_existing: int = 0
    notes_created: int = 0
    notes_existing: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    """Deterministic, stable slug — the basis for matching rows between runs."""
    normalised = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalised.strip("-")[:200] or "untitled"


def tokens(value: str) -> set[str]:
    """Significant words of a title, used for fuzzy matching."""
    stop = {"a", "an", "the", "of", "and", "or", "design", "system", "introduction", "to"}
    return {token for token in slugify(value).split("-") if token and token not in stop}


def classify_area(area: str | None) -> str | None:
    """Decide which curriculum a legacy ``area`` belongs to, or ``None`` if unrecognised."""
    candidate = (area or "").strip().lower()
    if candidate in LLD_AREAS:
        return "lld"
    if candidate in HLD_AREAS:
        return "hld"
    # Substring fallback, because the legacy column is free text.
    if "lld" in candidate or "low" in candidate:
        return "lld"
    if "hld" in candidate or "high" in candidate or "system" in candidate:
        return "hld"
    return None


def match_topic(title: str, catalog: dict[str, Any]) -> tuple[Any | None, bool]:
    """Find the seeded topic for ``title``.

    Returns ``(topic, was_fuzzy)``. An exact slug match wins; otherwise the topic sharing the
    most significant words is used, provided the overlap is strong enough to trust. A weak
    match returns ``None`` rather than attaching notes to the wrong topic.
    """
    slug = slugify(title)
    exact = catalog.get(slug)
    if exact is not None:
        return exact, False

    wanted = tokens(title)
    if not wanted:
        return None, False

    best: Any | None = None
    best_score = 0.0
    for candidate_topic in catalog.values():
        candidate = tokens(candidate_topic.title)
        if not candidate:
            continue
        overlap = len(wanted & candidate) / len(wanted | candidate)
        if overlap > best_score:
            best_score = overlap
            best = candidate_topic

    # Require a majority overlap; anything less would be a guess.
    if best is not None and best_score >= 0.6:
        return best, True
    return None, False


async def fetch_source_rows(
    session: AsyncSession, user_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Read the legacy table. SELECT only — never writes to it."""
    if user_id is not None:
        statement = text(f"{_SOURCE_COLUMNS} WHERE user_id = :user_id ORDER BY user_id, area, title")
        params: dict[str, Any] = {"user_id": str(user_id)}
    else:
        statement = text(f"{_SOURCE_COLUMNS} ORDER BY user_id, area, title")
        params = {}

    result = await session.execute(statement, params)
    return [dict(row._mapping) for row in result.all()]


async def backfill(*, dry_run: bool, user_id: uuid.UUID | None, stats: BackfillStats) -> None:
    async with session_scope() as session:
        try:
            rows = await fetch_source_rows(session, user_id)
        except Exception as exc:
            print(f"Could not read public.design_topics: {exc}")
            print("Nothing to backfill (this is expected on a fresh database).")
            return

        stats.source_rows = len(rows)
        print(f"Found {len(rows)} row(s) in public.design_topics")
        if not rows:
            return

        # Preload the seeded catalogs once so matching is not a query per row.
        lld_by_slug = {topic.slug: topic for topic in await session.scalars(select(LLDTopic))}
        hld_by_slug = {topic.slug: topic for topic in await session.scalars(select(HLDTopic))}

        for row in rows:
            kind = classify_area(row["area"])
            if kind is None:
                stats.skipped += 1
                stats.warnings.append(
                    f"Row {row['id']}: unrecognised area '{row['area']}' — needs a manual decision"
                )
                continue

            title = row["title"] or "Untitled"
            catalog = lld_by_slug if kind == "lld" else hld_by_slug
            topic, fuzzy = match_topic(title, catalog)

            if topic is None:
                # These catalogs are shared by every user, so we never insert here.
                stats.skipped += 1
                stats.warnings.append(
                    f"Row {row['id']}: {kind.upper()} '{title}' matches no seeded topic — "
                    f"add it to the curriculum and rerun, or migrate it by hand"
                )
                continue

            stats.matched += 1
            stats.matched_fuzzy += int(fuzzy)

            if dry_run:
                await _report_dry_run(session, row, topic, kind=kind, fuzzy=fuzzy, stats=stats)
                continue

            await _migrate_progress(session, row, topic, kind=kind, stats=stats)
            await _migrate_notes(session, row, topic, kind=kind, stats=stats)

        if not dry_run:
            await session.commit()


async def _progress_exists(
    session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID, *, kind: str
) -> bool:
    model = LLDProgress if kind == "lld" else HLDProgress
    topic_column = model.lld_topic_id if kind == "lld" else model.hld_topic_id
    found = await session.scalar(
        select(model.id).where(model.user_id == user_id, topic_column == topic_id)
    )
    return found is not None


async def _notes_exists(
    session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID, *, kind: str
) -> bool:
    model = LLDNote if kind == "lld" else HLDNote
    topic_column = model.lld_topic_id if kind == "lld" else model.hld_topic_id
    found = await session.scalar(
        select(model.id).where(model.user_id == user_id, topic_column == topic_id)
    )
    return found is not None


async def _report_dry_run(
    session: AsyncSession,
    row: dict[str, Any],
    topic: Any,
    *,
    kind: str,
    fuzzy: bool,
    stats: BackfillStats,
) -> None:
    """Preview one row without writing, keeping the counters accurate."""
    progress_exists = await _progress_exists(session, row["user_id"], topic.id, kind=kind)
    notes_exists = await _notes_exists(session, row["user_id"], topic.id, kind=kind)

    stats.progress_existing += int(progress_exists)
    stats.progress_created += int(not progress_exists)
    stats.notes_existing += int(notes_exists)
    stats.notes_created += int(not notes_exists)

    how = "fuzzy title match" if fuzzy else "exact slug match"
    pending = [name for name, exists in (("progress", progress_exists), ("notes", notes_exists)) if not exists]
    detail = ", ".join(pending) if pending else "already migrated"

    print(
        f"  [dry-run] {row['user_id']} | {kind} | {row['title']!r} -> "
        f"'{topic.slug}' ({how}) — {detail}"
    )

    if row.get("code"):
        stats.warnings.append(_code_warning(row, kind))


async def _migrate_progress(
    session: AsyncSession, row: dict[str, Any], topic: Any, *, kind: str, stats: BackfillStats
) -> None:
    """Copy legacy status/dates onto the matching progress row, if not already present."""
    user_id = row["user_id"]
    if await _progress_exists(session, user_id, topic.id, kind=kind):
        stats.progress_existing += 1
        return

    status = _map_status(row.get("status"))
    common: dict[str, Any] = {
        "user_id": user_id,
        "status": status,
        # The legacy table has no confidence column; 3 matches the schema default.
        "confidence": 3,
        "last_reviewed_at": row.get("last_reviewed_date"),
        "completed_at": row.get("updated_at") if status in ("completed", "mastered") else None,
        "next_revision_at": row.get("next_revision_date"),
    }

    if kind == "lld":
        session.add(LLDProgress(lld_topic_id=topic.id, **common))
    else:
        session.add(HLDProgress(hld_topic_id=topic.id, **common))
    await session.flush()
    stats.progress_created += 1


async def _migrate_notes(
    session: AsyncSession, row: dict[str, Any], topic: Any, *, kind: str, stats: BackfillStats
) -> None:
    """Map the legacy flat columns onto the normalised note sections, if absent."""
    user_id = row["user_id"]
    if await _notes_exists(session, user_id, topic.id, kind=kind):
        stats.notes_existing += 1
        return

    if kind == "lld":
        session.add(
            LLDNote(
                user_id=user_id,
                lld_topic_id=topic.id,
                summary=row.get("requirements") or "",
                design_explanation=row.get("architecture") or "",
                relationships=row.get("tradeoffs") or "",
                design_notes=row.get("notes") or "",
            )
        )
    else:
        session.add(
            HLDNote(
                user_id=user_id,
                hld_topic_id=topic.id,
                # Only the sections the legacy columns genuinely correspond to are filled.
                # Remaining HLD sections start empty rather than being invented.
                functional_requirements=row.get("requirements") or "",
                high_level_architecture=row.get("architecture") or "",
                tradeoffs=row.get("tradeoffs") or "",
                final_notes=row.get("notes") or "",
            )
        )
    await session.flush()
    stats.notes_created += 1

    if row.get("code"):
        stats.warnings.append(_code_warning(row, kind))


def _code_warning(row: dict[str, Any], kind: str) -> str:
    return (
        f"Row {row['id']}: legacy `code` column has no home in the notes table — "
        f"move it to a {kind} code snippet if it is still needed"
    )


def _map_status(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return STATUS_MAP.get(candidate, "learning" if candidate else "not_started")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    parser.add_argument("--user", default=None, help="Only backfill one user's rows (UUID)")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.is_connectable:
        print("DATABASE_URL is not configured. Set it in .env first.")
        return 1

    target_user: uuid.UUID | None = None
    if args.user:
        try:
            target_user = uuid.UUID(args.user)
        except ValueError:
            print(f"--user must be a UUID, got '{args.user}'")
            return 1

    if args.dry_run:
        print("DRY RUN — nothing will be written\n")

    stats = BackfillStats()
    await backfill(dry_run=args.dry_run, user_id=target_user, stats=stats)

    print()
    print("=" * 64)
    print("BACKFILL SUMMARY" + ("  (DRY RUN)" if args.dry_run else ""))
    print("=" * 64)
    print(f"source rows read      : {stats.source_rows}")
    matched = f"{stats.matched}"
    if stats.matched_fuzzy:
        matched += f" ({stats.matched_fuzzy} fuzzy)"
    print(f"matched to a topic    : {matched}")
    progress = f"{stats.progress_created}"
    if stats.progress_existing:
        progress += f" (already existed: {stats.progress_existing})"
    print(f"progress rows created : {progress}")
    notes = f"{stats.notes_created}"
    if stats.notes_existing:
        notes += f" (already existed: {stats.notes_existing})"
    print(f"notes rows created    : {notes}")
    print(f"skipped               : {stats.skipped}")
    print()
    print("public.design_topics was NOT modified — it is kept intact.")
    print("lld_topics/hld_topics were NOT modified — they are shared by all users.")

    if stats.warnings:
        print(f"\nNEEDS REVIEW ({len(stats.warnings)}):")
        for warning in stats.warnings:
            print(f"  - {warning}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
