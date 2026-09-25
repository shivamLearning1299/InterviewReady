"""User identity and export endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status

from app.api.v1.dependencies import CurrentUser, ServicesDep
from app.schemas.common import UserResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The authenticated user",
    description=(
        "Returns the identity asserted by the verified Supabase access token. The id comes "
        "from the token's `sub` claim — never from a value supplied by the client."
    ),
)
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse(id=current_user.id, email=current_user.email)


@router.get(
    "/export",
    summary="Export all of the user's data",
    description=(
        "Returns a portable JSON dump of everything the caller owns: progress, attempts, "
        "notes, code, revisions, plans, LLD/HLD work, study history and settings. "
        "Access tokens, refresh tokens and provider credentials are never included."
    ),
)
async def export_data(
    current_user: CurrentUser,
    services: ServicesDep,
    include_conversations: bool = Query(
        default=True, description="Include AI conversation summaries."
    ),
) -> Response:
    """Export is written straight to a JSON response rather than modelled as a schema.

    The payload is a heterogeneous, user-defined shape whose exact keys are the point; a
    rigid Pydantic model would add churn without adding validation value. It is streamed
    with a content-disposition hint so the browser can save it directly.
    """
    import json

    payload = await services.export.export_all(
        user_id=current_user.id, include_conversations=include_conversations
    )

    return Response(
        content=json.dumps(payload, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="interviewready-export-{current_user.id}.json"'
            )
        },
        status_code=status.HTTP_200_OK,
    )


__all__ = ["router"]
