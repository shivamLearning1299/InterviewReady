"""Server-timed study sessions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.v1.dependencies import ClientTimezone, CurrentUser, Paginated, ServicesDep
from app.core.constants import SessionType
from app.schemas.study import (
    StudySessionResponse,
    StudySessionStartRequest,
    StudySessionStopRequest,
)
from app.utils.pagination import Page

router = APIRouter(prefix="/study-sessions", tags=["study-sessions"])


@router.post(
    "/start",
    response_model=StudySessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a study session",
    description=(
        "Opens a timer.\n\n"
        "**Idempotent by design:** if a session is already running, that session is "
        "returned instead of creating a second one — a double-tap, or a retried request "
        "from the offline queue, will not spawn two timers. A partial unique index enforces "
        "the same guarantee in the database."
    ),
)
async def start_session(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: StudySessionStartRequest,
    client_timezone: ClientTimezone = None,
) -> StudySessionResponse:
    return await services.study_sessions.start(
        user_id=current_user.id, payload=payload, timezone=client_timezone
    )


@router.post(
    "/{session_id}/stop",
    response_model=StudySessionResponse,
    summary="Stop a study session",
    description=(
        "Closes the timer and records the duration **measured by the server**.\n\n"
        "Note there is no duration field in the request body: elapsed time is derived from "
        "server timestamps so neither client can inflate study time, and a backgrounded app "
        "still reports honest minutes. Long sessions are capped rather than rejected.\n\n"
        "Idempotent: stopping again returns the originally recorded duration."
    ),
)
async def stop_session(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: StudySessionStopRequest,
    session_id: uuid.UUID,
    client_timezone: ClientTimezone = None,
) -> StudySessionResponse:
    return await services.study_sessions.stop(
        user_id=current_user.id,
        session_id=session_id,
        payload=payload,
        timezone=client_timezone,
    )


@router.get(
    "",
    response_model=Page[StudySessionResponse],
    summary="Study session history",
)
async def list_sessions(
    current_user: CurrentUser,
    services: ServicesDep,
    pagination: Paginated,
    session_type: SessionType | None = Query(default=None),
    context_id: uuid.UUID | None = Query(default=None),
    running_only: bool = Query(default=False),
) -> Page[StudySessionResponse]:
    items, total = await services.study_sessions.list_sessions(
        user_id=current_user.id,
        limit=pagination.limit,
        offset=pagination.offset,
        session_type=session_type.value if session_type else None,
        context_id=context_id,
        running_only=running_only,
    )
    return Page[StudySessionResponse](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/running",
    response_model=StudySessionResponse | None,
    summary="The currently running session",
    description="Lets a client restore its timer after a relaunch. Returns `null` if idle.",
)
async def get_running_session(
    current_user: CurrentUser, services: ServicesDep
) -> StudySessionResponse | None:
    return await services.study_sessions.get_running(user_id=current_user.id)


__all__ = ["router"]
