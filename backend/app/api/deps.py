"""FastAPI dependencies: authentication, database sessions, settings, pagination.

``get_current_user`` is the single entry point for identity in the application. Routes
never read a user id from a path/query/body — they depend on this, so the id is always
the ``sub`` of a JWKS-verified Supabase token.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import UnauthenticatedError, ValidationError
from app.core.logging import bind_request_context
from app.core.security import AuthenticatedUser, SupabaseTokenVerifier, extract_bearer_token
from app.db.session import get_db

# --------------------------------------------------------------------------- settings
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_token_verifier(request: Request) -> SupabaseTokenVerifier:
    """Retrieve the process-wide token verifier built during application startup."""
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:  # pragma: no cover - only if startup was skipped
        verifier = SupabaseTokenVerifier(get_settings())
        request.app.state.token_verifier = verifier
    return verifier


TokenVerifierDep = Annotated[SupabaseTokenVerifier, Depends(get_token_verifier)]


# -------------------------------------------------------------------------- database
DbSession = Annotated[AsyncSession, Depends(get_db)]


# -------------------------------------------------------------------- authentication
async def get_current_user(
    request: Request,
    verifier: TokenVerifierDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """Resolve the authenticated Supabase user, or raise 401.

    The token is taken from the ``Authorization`` header only. A ``user_id`` supplied in a
    request body or query string is ignored everywhere in the codebase.
    """
    token = extract_bearer_token(authorization)
    if token is None:
        raise UnauthenticatedError(
            "Provide a Supabase access token as 'Authorization: Bearer <token>'."
        )

    user = await verifier.verify(token)

    # Correlate every subsequent log line with the authenticated user.
    bind_request_context(user_id=str(user.id))
    request.state.user_id = str(user.id)
    return user


async def get_current_user_optional(
    request: Request,
    verifier: TokenVerifierDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser | None:
    """Like :func:`get_current_user` but returns ``None`` instead of raising.

    Only for endpoints that genuinely vary for anonymous callers (e.g. a future public
    catalog view). All personal-data endpoints must use ``get_current_user``.
    """
    token = extract_bearer_token(authorization)
    if token is None:
        return None
    try:
        user = await verifier.verify(token)
    except UnauthenticatedError:
        return None
    bind_request_context(user_id=str(user.id))
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OptionalUser = Annotated[AuthenticatedUser | None, Depends(get_current_user_optional)]


# ------------------------------------------------------------------------- pagination
class Pagination:
    """Stable ``limit``/``offset`` pagination parameters."""

    __slots__ = ("limit", "offset")

    def __init__(self, limit: int, offset: int) -> None:
        self.limit = limit
        self.offset = offset


def get_pagination(
    settings: SettingsDep,
    limit: Annotated[int | None, Query(ge=1, le=1000, description="Page size")] = None,
    offset: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
) -> Pagination:
    """Validate and clamp pagination inputs.

    ``limit`` is clamped to ``settings.max_page_limit`` so a client cannot ask for the
    entire catalog in one request.
    """
    effective = settings.default_page_limit if limit is None else limit
    if effective < 1:
        raise ValidationError("limit must be at least 1", details={"limit": effective})
    return Pagination(limit=min(effective, settings.max_page_limit), offset=offset)


Paginated = Annotated[Pagination, Depends(get_pagination)]


# ------------------------------------------------------------------- request helpers
def get_request_id(request: Request) -> str:
    """The request id assigned by the logging middleware."""
    return getattr(request.state, "request_id", "")


def get_device_id(
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> str | None:
    """Optional client-supplied device identifier, used by the sync protocol.

    Purely informational: it attributes the origin of a change and is never used for
    authentication or authorisation.
    """
    return x_device_id


DeviceId = Annotated[str | None, Depends(get_device_id)]


async def db_session_scope() -> AsyncIterator[AsyncSession]:  # pragma: no cover - re-export
    """Alias kept for readability in service constructors."""
    async for session in get_db():
        yield session


def parse_uuid(value: str, *, field: str = "id") -> uuid.UUID:
    """Parse a path/body UUID, raising a 422 rather than a bare ValueError."""
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            f"'{field}' must be a valid UUID.",
            details={field: value},
        ) from exc
