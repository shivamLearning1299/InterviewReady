"""Today's plan and daily plan history."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Path, Query, status

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.core.exceptions import DailyPlanNotFoundError
from app.schemas.today import (
    DailyPlanDetail,
    DailyPlanItemUpdateRequest,
    PlanGenerationDebug,
    TodayResponse,
)
from app.utils.pagination import DeletedResponse, Page

router = APIRouter()


@router.get(
    "/today",
    response_model=TodayResponse,
    summary="Today's plan",
    description=(
        "The home-screen payload: today's DSA questions, LLD/HLD focus, due revisions and "
        "the current streak.\n\n"
        "If today's plan does not exist it is generated and persisted on this request. "
        "Calling the endpoint repeatedly on the same day returns the **same** plan — "
        "generation is anchored to `(user_id, date)` and guarded by a unique constraint, so "
        "a refresh (or two simultaneous requests) can never produce a different plan or a "
        "duplicate."
    ),
)
async def get_today(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
) -> TodayResponse:
    user_settings = await services.settings_service.get_or_default(
        user_id=current_user.id, timezone_hint=client_timezone
    )
    return await services.daily_plans.get_or_create_today(
        user_id=current_user.id,
        # Pass the row through: the planner reads `daily_dsa_count` and
        # `daily_revision_count` from it. Swallowing it here would silently ignore the
        # user's preferences and always generate the default-sized plan.
        user_settings=user_settings,
        timezone=client_timezone or user_settings.timezone,
    )


@router.get(
    "/today/explain",
    response_model=PlanGenerationDebug,
    summary="Why today's plan looks the way it does",
    description=(
        "Non-sensitive diagnostics describing how the scheduler chose today's questions: "
        "the candidate pool size, the detected weak topics, and the scoring version. "
        "Intended for the client's debug panel."
    ),
)
async def explain_today(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
) -> PlanGenerationDebug:
    return await services.daily_plans.explain_today(
        user_id=current_user.id, timezone=client_timezone
    )


@router.get(
    "/daily-plans",
    response_model=Page[DailyPlanDetail],
    summary="Daily plan history",
    description="Past plans, newest first, with per-section completion counts.",
)
async def list_daily_plans(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    start_date: str | None = Query(default=None, description="ISO date, inclusive lower bound"),
    end_date: str | None = Query(default=None, description="ISO date, inclusive upper bound"),
) -> Page[DailyPlanDetail]:
    from datetime import date as date_type

    def _parse(value: str | None) -> date_type | None:
        if not value:
            return None
        try:
            return date_type.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{value}' is not an ISO date (expected YYYY-MM-DD).",
            ) from exc

    items, total = await services.daily_plans.list_plans(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        start_date=_parse(start_date),
        end_date=_parse(end_date),
    )
    return Page[DailyPlanDetail](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/daily-plans/{plan_date}",
    response_model=TodayResponse,
    summary="A specific day's plan",
    description="Returns the persisted plan for that date, including its completion state.",
    responses={404: {"description": "No plan exists for that date"}},
)
async def get_daily_plan(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
    plan_date: str = Path(description="ISO date (YYYY-MM-DD)"),
) -> TodayResponse:
    from datetime import date as date_type

    try:
        parsed = date_type.fromisoformat(plan_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{plan_date}' is not an ISO date (expected YYYY-MM-DD).",
        ) from exc

    result = await services.daily_plans.get_plan_for_date(
        user_id=current_user.id, plan_date=parsed, timezone=client_timezone
    )
    if result is None:
        raise DailyPlanNotFoundError(f"No daily plan exists for {plan_date}.")
    return result


@router.patch(
    "/daily-plans/items/{item_id}",
    response_model=DailyPlanDetail,
    summary="Mark a plan item complete",
    description=(
        "Clients tick items off here, or implicitly by updating problem progress. "
        "Idempotent: setting the same state twice is a no-op."
    ),
)
async def update_plan_item(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: DailyPlanItemUpdateRequest,
    item_id: uuid.UUID,
) -> DailyPlanDetail:
    from app.db.models import DailyPlan

    item = await services.plan_repo.get_item(user_id=current_user.id, item_id=item_id)
    if item is None:
        raise DailyPlanNotFoundError("That plan item does not exist.")

    if item.is_completed != payload.is_completed:
        await services.plan_repo.set_item_completion(item, is_completed=payload.is_completed)
        if payload.is_completed:
            # Completing a plan item is meaningful study activity.
            await services.activity.record(user_id=current_user.id, activity_count=1)
        await services.session.commit()

    # Re-read the owning plan to return the updated section counts.
    plan = await services.session.get(DailyPlan, item.plan_id)
    if plan is None:  # pragma: no cover - the FK guarantees it exists
        raise DailyPlanNotFoundError("The owning plan no longer exists.")

    summaries, _ = await services.daily_plans.list_plans(
        user_id=current_user.id,
        limit=1,
        offset=0,
        start_date=plan.date_key,
        end_date=plan.date_key,
    )
    if not summaries:  # pragma: no cover - just queried it directly
        raise DailyPlanNotFoundError("The owning plan no longer exists.")
    return summaries[0]


@router.delete(
    "/daily-plans/items/{item_id}",
    response_model=DeletedResponse,
    summary="Remove an item from today's plan",
    description="Soft-deletes the item so the removal propagates to other devices on sync.",
)
async def delete_plan_item(
    current_user: CurrentUser,
    services: ServicesDep,
    item_id: uuid.UUID,
) -> DeletedResponse:
    from app.utils.datetime_utils import utcnow

    item = await services.plan_repo.get_item(user_id=current_user.id, item_id=item_id)
    if item is None:
        raise DailyPlanNotFoundError("That plan item does not exist.")

    item.deleted_at = utcnow()
    item.version = (item.version or 1) + 1
    await services.session.commit()

    return DeletedResponse(id=str(item_id), message="Plan item removed")


__all__ = ["router"]
