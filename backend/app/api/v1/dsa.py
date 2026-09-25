"""DSA catalog, progress, attempts, notes, code and per-problem revisions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.core.constants import Difficulty, ProblemStatus
from app.schemas.common import ProgressSummary
from app.schemas.dsa import (
    AttemptCreateRequest,
    AttemptResponse,
    AttemptUpdateRequest,
    CodeSnippetCreate,
    CodeSnippetResponse,
    CodeSnippetUpdate,
    DSAProblemDetail,
    DSAProblemSummary,
    ProblemNotesResponse,
    ProblemNotesUpsert,
    ProgressResponse,
    ProgressUpdateRequest,
    RevisionCreateRequest,
    RevisionResponse,
)
from app.utils.pagination import DeletedResponse, Page

router = APIRouter(prefix="/dsa", tags=["dsa"])


def _progress_summary(progress) -> ProgressSummary:
    """Map a progress row onto the compact summary embedded in listings."""
    if progress is None:
        return ProgressSummary()
    return ProgressSummary(
        status=progress.status,
        attempts=progress.attempts,
        confidence=progress.confidence,
        is_favorite=progress.is_favorite,
        next_revision_at=progress.next_revision_date,
        solved_at=progress.solved_date,
        total_time_spent_minutes=progress.time_spent_minutes,
    )


# =============================================================== CATALOG
@router.get(
    "/problems",
    response_model=Page[DSAProblemSummary],
    summary="Browse the DSA catalog",
    description=(
        "Paged catalog listing with the caller's own progress merged into each row.\n\n"
        "Filters combine with AND. `search` matches the title, slug and primary topic; "
        "`pattern` and `company` match against their array columns; `status` uses the "
        "catalog's own statuses and treats `not_started` as 'no progress row yet'."
    ),
)
async def list_problems(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    search: str | None = Query(default=None, max_length=200, description="Title/slug/topic text"),
    topic: str | None = Query(default=None, max_length=100),
    pattern: str | None = Query(default=None, max_length=100, description="e.g. 'Sliding Window'"),
    difficulty: Difficulty | None = Query(default=None),
    status_filter: ProblemStatus | None = Query(
        default=None, alias="status", description="Filter by the caller's progress status"
    ),
    company: str | None = Query(default=None, max_length=100),
    revision_due: bool = Query(default=False, description="Only problems whose revision is due"),
    source: str | None = Query(default=None, max_length=50),
    favorites_only: bool = Query(default=False),
    order_by: str = Query(
        default="curriculum",
        pattern="^(curriculum|difficulty|title|importance|recent)$",
        description="Sort order",
    ),
) -> Page[DSAProblemSummary]:
    from app.utils.datetime_utils import utcnow

    rows, total = await services.catalog.list_with_progress(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        order_by=order_by,
        search=search,
        topic=topic,
        pattern=pattern,
        difficulty=difficulty.value if difficulty else None,
        status=status_filter.value if status_filter else None,
        company=company,
        source=source,
        revision_due=revision_due,
        favorites_only=favorites_only,
        now=utcnow(),
    )

    items = [
        DSAProblemSummary(
            id=problem.id,
            created_at=problem.created_at,
            updated_at=problem.updated_at,
            version=getattr(problem, "version", 1),
            title=problem.title,
            slug=problem.slug,
            external_url=problem.external_url,
            source=problem.source,
            difficulty=problem.difficulty,
            primary_topic=problem.primary_topic,
            secondary_topics=list(problem.secondary_topics or []),
            patterns=list(problem.patterns or []),
            companies=list(problem.companies or []),
            problem_type=problem.problem_type,
            order_index=problem.order_index,
            importance=problem.importance,
            estimated_minutes=problem.estimated_minutes,
            is_active=problem.is_active,
            progress=_progress_summary(progress),
        )
        for problem, progress in rows
    ]

    return Page[DSAProblemSummary](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/problems/{problem_id}",
    response_model=DSAProblemDetail,
    summary="One problem, with everything the detail screen needs",
    description=(
        "Returns the problem's metadata plus the caller's progress, notes, code snippets, "
        "attempt history and revisions — assembled from a fixed number of queries "
        "regardless of how much data the user has."
    ),
    responses={404: {"description": "Problem not found"}},
)
async def get_problem(
    current_user: CurrentUser,
    services: ServicesDep,
    problem_id: str,
) -> DSAProblemDetail:
    problem, progress = await services.catalog.get_with_progress(
        user_id=current_user.id, problem_id=problem_id
    )

    notes = await services.notes.get(user_id=current_user.id, problem_id=problem_id)
    snippets = await services.code.list_for_dsa(user_id=current_user.id, problem_id=problem_id)
    attempts, _ = await services.attempts.list_for_problem(
        user_id=current_user.id, problem_id=problem_id, limit=20, offset=0
    )
    revisions = await services.revisions.list_for_problem(
        user_id=current_user.id, problem_id=problem_id
    )

    return DSAProblemDetail(
        id=problem.id,
        created_at=problem.created_at,
        updated_at=problem.updated_at,
        version=getattr(problem, "version", 1),
        title=problem.title,
        slug=problem.slug,
        external_url=problem.external_url,
        source=problem.source,
        difficulty=problem.difficulty,
        primary_topic=problem.primary_topic,
        secondary_topics=list(problem.secondary_topics or []),
        patterns=list(problem.patterns or []),
        companies=list(problem.companies or []),
        problem_type=problem.problem_type,
        order_index=problem.order_index,
        importance=problem.importance,
        estimated_minutes=problem.estimated_minutes,
        is_active=problem.is_active,
        hints=problem.hints,
        progress=_progress_summary(progress),
        notes=notes,
        code_snippets=snippets,
        attempts=attempts,
        revisions=revisions,
    )


@router.get(
    "/topics",
    summary="All topics with totals",
    description="Topic slugs with problem counts, for filter dropdowns and the stats screen.",
)
async def list_topics(current_user: CurrentUser, services: ServicesDep) -> dict:
    counts = await services.catalog.count_by_topic()
    topics = await services.catalog.list_topics()
    return {
        "items": [
            {
                "slug": topic.slug,
                "name": topic.name,
                "category": topic.category,
                "order_index": topic.order_index,
                "problem_count": counts.get(topic.slug, counts.get(topic.name, 0)),
            }
            for topic in topics
        ]
    }


@router.get(
    "/filters",
    summary="Available filter values",
    description="Distinct patterns and companies present in the catalog.",
)
async def list_filters(current_user: CurrentUser, services: ServicesDep) -> dict:
    return {
        "patterns": await services.catalog.distinct_patterns(),
        "companies": await services.catalog.distinct_companies(),
        "difficulties": [item.value for item in Difficulty],
        "statuses": [item.value for item in ProblemStatus],
    }


# =============================================================== PROGRESS
@router.put(
    "/problems/{problem_id}/progress",
    response_model=ProgressResponse,
    summary="Create or update progress for a problem",
    description=(
        "UPSERT semantics: the progress row is created on first write.\n\n"
        "Timestamps are derived server-side rather than trusted from the client — moving to "
        "`solved` sets `solved_at` and schedules the first revision using the configured "
        "spaced-repetition ladder, `needs_revision` brings the problem back tomorrow at "
        "maximum priority, and moving back to `not_started` clears the derived dates."
    ),
)
async def update_progress(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: ProgressUpdateRequest,
    problem_id: str,
    client_timezone: ClientTimezone = None,
) -> ProgressResponse:
    return await services.progress.upsert(
        user_id=current_user.id,
        problem_id=problem_id,
        payload=payload,
        timezone=client_timezone,
    )


# =============================================================== ATTEMPTS
@router.post(
    "/problems/{problem_id}/attempts",
    response_model=AttemptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log an attempt",
    description=(
        "Records an attempt and folds its consequences into progress in one transaction: "
        "the attempt counter and total time advance, and the outcome decides whether the "
        "problem becomes solved, stays in progress, or is flagged for revision."
    ),
)
async def create_attempt(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: AttemptCreateRequest,
    problem_id: str,
    client_timezone: ClientTimezone = None,
) -> AttemptResponse:
    return await services.attempts.create(
        user_id=current_user.id,
        problem_id=problem_id,
        payload=payload,
        timezone=client_timezone,
    )


@router.get(
    "/problems/{problem_id}/attempts",
    response_model=Page[AttemptResponse],
    summary="Attempt history for a problem",
)
async def list_attempts(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    problem_id: str,
) -> Page[AttemptResponse]:
    await services.catalog.get_with_progress(user_id=current_user.id, problem_id=problem_id)
    items, total = await services.attempts.list_for_problem(
        user_id=current_user.id,
        problem_id=problem_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page[AttemptResponse](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.patch(
    "/problems/{problem_id}/attempts/{attempt_id}",
    response_model=AttemptResponse,
    summary="Amend a logged attempt",
    description="Corrects an attempt's outcome, timing or notes. Progress is not recomputed.",
)
async def update_attempt(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: AttemptUpdateRequest,
    problem_id: str,
    attempt_id: uuid.UUID,
) -> AttemptResponse:
    return await services.attempts.update(
        user_id=current_user.id,
        problem_id=problem_id,
        attempt_id=attempt_id,
        payload=payload,
    )


# =============================================================== NOTES
@router.get(
    "/problems/{problem_id}/notes",
    response_model=ProblemNotesResponse | None,
    summary="Notes for a problem",
    description="Returns `null` rather than a 404 when the user has not written notes yet.",
)
async def get_notes(
    current_user: CurrentUser,
    services: ServicesDep,
    problem_id: str,
) -> ProblemNotesResponse | None:
    await services.catalog.get_with_progress(user_id=current_user.id, problem_id=problem_id)
    return await services.notes.get(user_id=current_user.id, problem_id=problem_id)


@router.put(
    "/problems/{problem_id}/notes",
    response_model=ProblemNotesResponse,
    summary="Write or replace notes",
    description=(
        "UPSERT semantics, one notes document per problem. Fields omitted from the payload "
        "are left unchanged."
    ),
)
async def upsert_notes(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: ProblemNotesUpsert,
    problem_id: str,
) -> ProblemNotesResponse:
    return await services.notes.upsert(
        user_id=current_user.id, problem_id=problem_id, payload=payload
    )


# =============================================================== CODE
@router.get(
    "/problems/{problem_id}/code",
    response_model=list[CodeSnippetResponse],
    summary="Code snippets for a problem",
    description="Multiple snippets per problem are supported; at most one is `is_primary`.",
)
async def list_code(
    current_user: CurrentUser,
    services: ServicesDep,
    problem_id: str,
) -> list[CodeSnippetResponse]:
    await services.catalog.get_with_progress(user_id=current_user.id, problem_id=problem_id)
    return await services.code.list_for_dsa(user_id=current_user.id, problem_id=problem_id)


@router.post(
    "/problems/{problem_id}/code",
    response_model=CodeSnippetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a code snippet",
    description=(
        "Code is stored verbatim for the user's own reference. It is never compiled, "
        "linted or executed."
    ),
)
async def create_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: CodeSnippetCreate,
    problem_id: str,
) -> CodeSnippetResponse:
    return await services.code.create_for_dsa(
        user_id=current_user.id, problem_id=problem_id, payload=payload
    )


@router.put(
    "/problems/{problem_id}/code/{snippet_id}",
    response_model=CodeSnippetResponse,
    summary="Update a code snippet",
)
async def update_code(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: CodeSnippetUpdate,
    problem_id: str,
    snippet_id: uuid.UUID,
) -> CodeSnippetResponse:
    return await services.code.update(
        user_id=current_user.id,
        snippet_id=snippet_id,
        payload=payload,
        expected_context=("dsa", problem_id),
    )


@router.delete(
    "/problems/{problem_id}/code/{snippet_id}",
    response_model=DeletedResponse,
    summary="Delete a code snippet",
    description=(
        "Soft delete: the snippet is tombstoned so that offline devices learn about the "
        "removal on their next sync pull."
    ),
)
async def delete_code(
    current_user: CurrentUser,
    services: ServicesDep,
    problem_id: str,
    snippet_id: uuid.UUID,
) -> DeletedResponse:
    await services.code.delete(
        user_id=current_user.id, snippet_id=snippet_id, expected_context=("dsa", problem_id)
    )
    return DeletedResponse(id=str(snippet_id), message="Code snippet deleted")


# =============================================================== REVISIONS
@router.post(
    "/problems/{problem_id}/revision",
    response_model=RevisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a revision",
    description=(
        "Queues a problem for review. Reschedules rather than stacking: a problem only ever "
        "has one open revision, so calling this twice does not inflate the due count.\n\n"
        "Omitting `due_at` uses the configured interval for the problem's current confidence."
    ),
)
async def schedule_revision(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: RevisionCreateRequest,
    problem_id: str,
) -> RevisionResponse:
    return await services.revisions.schedule_manual(
        user_id=current_user.id, problem_id=problem_id, payload=payload
    )


__all__ = ["router"]
