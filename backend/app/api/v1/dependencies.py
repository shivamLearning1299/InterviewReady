"""Shared router dependencies.

The ``ServicesDep``/``CurrentUser`` aliases keep route signatures readable while making the
dependency on a request-scoped session explicit.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.api.deps import CurrentUser, DbSession, Paginated, SettingsDep
from app.api.v1.services import Services, get_services


def _services(
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> Services:
    return get_services(request, session, settings)


ServicesDep = Annotated[Services, Depends(_services)]


def get_client_timezone(
    x_timezone: Annotated[
        str | None,
        Header(
            alias="X-Timezone",
            description=(
                "Optional IANA timezone of the client (e.g. 'Asia/Kolkata'). Used to resolve "
                "'today' for plans, streaks and activity. Falls back to the user's saved "
                "setting, then the server default."
            ),
        ),
    ] = None,
) -> str | None:
    """Client-declared timezone.

    Advisory only: it influences which calendar day counts as "today", never authentication
    or authorisation.
    """
    return x_timezone


ClientTimezone = Annotated[str | None, Depends(get_client_timezone)]

__all__ = [
    "ClientTimezone",
    "CurrentUser",
    "DbSession",
    "Paginated",
    "ServicesDep",
    "SettingsDep",
]
