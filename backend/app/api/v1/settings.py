"""Per-user preferences and device registration."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.dependencies import ClientTimezone, CurrentUser, ServicesDep
from app.schemas.settings import (
    UserDeviceResponse,
    UserDeviceUpsert,
    UserSettingsResponse,
    UserSettingsUpdate,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "",
    response_model=UserSettingsResponse,
    summary="Read settings",
    description=(
        "Returns the caller's preferences, creating them with defaults on first access so a "
        "client never has to handle a 'not configured' state. Defaults include "
        "`daily_dsa_count = 3`."
    ),
)
async def get_settings_endpoint(
    current_user: CurrentUser,
    services: ServicesDep,
    client_timezone: ClientTimezone = None,
) -> UserSettingsResponse:
    return await services.settings_service.get(
        user_id=current_user.id, timezone_hint=client_timezone
    )


@router.put(
    "",
    response_model=UserSettingsResponse,
    summary="Update settings",
    description=(
        "Merge-update: only the supplied fields change. Values are validated against the "
        "server's configured bounds, so a client cannot set an unreasonable daily question "
        "count, an unknown language or an invalid timezone."
    ),
)
async def update_settings_endpoint(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: UserSettingsUpdate,
    client_timezone: ClientTimezone = None,
) -> UserSettingsResponse:
    return await services.settings_service.update(
        user_id=current_user.id, payload=payload, timezone_hint=client_timezone
    )


@router.get(
    "/devices",
    summary="Registered sync devices",
    description="Minimal device records — identifier, type and last sync time only.",
)
async def list_devices(current_user: CurrentUser, services: ServicesDep) -> dict:
    devices = await services.device_repo.list_for_user(user_id=current_user.id)
    return {
        "items": [
            UserDeviceResponse(
                id=device.id,
                created_at=device.created_at,
                updated_at=device.updated_at,
                version=device.version,
                user_id=device.user_id,
                device_identifier=device.device_identifier,
                device_type=device.device_type,
                display_name=device.display_name,
                last_sync_at=device.last_sync_at,
                last_pull_cursor=device.last_pull_cursor,
            )
            for device in devices
        ]
    }


@router.put(
    "/devices",
    response_model=UserDeviceResponse,
    summary="Register or refresh a device",
    description=(
        "Idempotent per `(user_id, device_identifier)`. Only the information needed to "
        "attribute changes and display 'last synced' is stored — no hardware fingerprint."
    ),
)
async def upsert_device(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: UserDeviceUpsert,
) -> UserDeviceResponse:
    device = await services.device_repo.upsert(
        user_id=current_user.id,
        device_identifier=payload.device_identifier,
        device_type=(
            payload.device_type.value
            if hasattr(payload.device_type, "value")
            else payload.device_type
        ),
        display_name=payload.display_name,
    )
    await services.session.commit()
    return UserDeviceResponse(
        id=device.id,
        created_at=device.created_at,
        updated_at=device.updated_at,
        version=device.version,
        user_id=device.user_id,
        device_identifier=device.device_identifier,
        device_type=device.device_type,
        display_name=device.display_name,
        last_sync_at=device.last_sync_at,
        last_pull_cursor=device.last_pull_cursor,
    )


__all__ = ["router"]
