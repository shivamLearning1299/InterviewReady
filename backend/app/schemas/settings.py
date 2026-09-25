"""Settings, export and device schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.core.constants import DeviceType, Language
from app.schemas.common import ORMModel, TimestampedModel


class UserSettingsResponse(TimestampedModel):
    user_id: uuid.UUID
    daily_dsa_count: int
    daily_revision_count: int
    include_lld_daily: bool
    include_hld_daily: bool
    daily_plan_preferences: dict[str, Any] | None = None
    revision_preferences: dict[str, Any] | None = None
    revision_enabled: bool
    ai_preferences: dict[str, Any] | None = None
    ai_auto_reveal_solution: bool
    timezone: str
    preferred_languages: list[str]
    theme: str


class UserSettingsUpdate(BaseModel):
    """Full-replace semantics, but every field is optional so clients can PATCH-style it.

    Limits are validated against the server's configured maxima so a client cannot set
    ``daily_dsa_count = 500`` and make the scheduler generate an unusable plan.
    """

    daily_dsa_count: int | None = Field(default=None, ge=1, le=50)
    daily_revision_count: int | None = Field(default=None, ge=0, le=100)
    include_lld_daily: bool | None = None
    include_hld_daily: bool | None = None
    daily_plan_preferences: dict[str, Any] | None = None
    revision_preferences: dict[str, Any] | None = None
    revision_enabled: bool | None = None
    ai_preferences: dict[str, Any] | None = None
    ai_auto_reveal_solution: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    preferred_languages: list[str] | None = None
    theme: str | None = Field(default=None, max_length=20)

    @field_validator("daily_dsa_count")
    @classmethod
    def _clamp_dsa_count(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(1, min(value, get_settings().daily_dsa_count_max))

    @field_validator("daily_revision_count")
    @classmethod
    def _clamp_revision_count(cls, value: int | None) -> int | None:
        if value is None:
            return None
        return max(0, min(value, get_settings().revision_dsa_count_max))

    @field_validator("preferred_languages")
    @classmethod
    def _valid_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        allowed = {item.value for item in Language}
        cleaned: list[str] = []
        for language in value:
            candidate = language.strip().lower()
            if not candidate:
                continue
            if candidate not in allowed:
                raise ValueError(
                    f"Unsupported language '{language}'. "
                    f"Allowed: {', '.join(sorted(allowed))}."
                )
            if candidate not in cleaned:
                cleaned.append(candidate)
        return cleaned or ["python"]

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value

    @field_validator("theme")
    @classmethod
    def _valid_theme(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in {"light", "dark", "system"}:
            raise ValueError("theme must be one of: light, dark, system")
        return value


class UserDeviceResponse(TimestampedModel):
    user_id: uuid.UUID
    device_identifier: str
    device_type: str
    display_name: str | None = None
    last_sync_at: datetime | None = None
    last_pull_cursor: int | None = None


class UserDeviceUpsert(BaseModel):
    device_identifier: str = Field(min_length=1, max_length=120)
    device_type: DeviceType = DeviceType.IOS
    display_name: str | None = Field(default=None, max_length=120)


class ExportResponse(ORMModel):
    """Portable export of everything the user owns. No tokens, no secrets."""

    exported_at: datetime
    user_id: uuid.UUID
    schema_version: int = 1
    problem_progress: list[dict[str, Any]]
    attempt_history: list[dict[str, Any]]
    notes: list[dict[str, Any]]
    code_snippets: list[dict[str, Any]]
    revisions: list[dict[str, Any]]
    lld_topics: list[dict[str, Any]]
    lld_notes: list[dict[str, Any]]
    hld_topics: list[dict[str, Any]]
    hld_notes: list[dict[str, Any]]
    study_sessions: list[dict[str, Any]]
    daily_plans: list[dict[str, Any]]
    settings: dict[str, Any] | None = None
    activity: list[dict[str, Any]] = Field(default_factory=list)
