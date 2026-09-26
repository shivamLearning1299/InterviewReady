"""Centralised, environment-driven application configuration.

Every tunable in the application funnels through :class:`Settings`. Business rules
(daily plan size, spaced-repetition ladder, streak thresholds) live here rather than
being hardcoded inside services, so the same behaviour is served to every client.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import (
    AliasChoices,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]
AIProviderName = Literal["gemini", "groq", "stub"]

# Confidence -> spaced-repetition ladder. Index is the number of *completed* revisions.
DEFAULT_REVISION_INTERVALS: dict[str, list[int]] = {
    "0": [1],
    "1": [1, 3],
    "2": [2, 5, 12],
    "3": [3, 7, 16, 35],
    "4": [5, 14, 35, 75, 150],
    "5": [7, 21, 60, 120, 240, 365],
}


def _normalise_async_driver(url: str) -> str:
    """Rewrite a libpq-style URL to the SQLAlchemy asyncpg dialect.

    Supabase hands out ``postgresql://...`` URLs; SQLAlchemy needs an explicit async
    driver. This keeps the value in ``.env`` copy-pasteable from the Supabase dashboard.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- application
    app_env: Environment = "development"
    app_name: str = "InterviewReady API"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = True

    # ------------------------------------------------------------------- database
    database_url: str = ""
    database_url_direct: str = ""
    test_database_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800
    db_echo: bool = False
    db_statement_timeout_ms: int = 30_000

    # --------------------------------------------------------------------- supabase
    supabase_url: str = ""
    supabase_anon_key: str = Field(
        default="",
        # Supabase renamed these keys: `anon` -> publishable (`sb_publishable_...`), and
        # `service_role` -> secret. Both names are accepted so an existing .env keeps
        # working. The value is only ever used for diagnostics — never to authorise a
        # request, which is always the user's verified JWT.
        validation_alias=AliasChoices(
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
            "supabase_anon_key",
        ),
    )
    supabase_jwks_url: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_jwks_cache_seconds: int = 600

    # ------------------------------------------------------------------------ cors
    #
    # `NoDecode` is load-bearing. For a complex type like `list[str]`, pydantic-settings
    # calls `json.loads()` on the environment value *before* any validator runs. A
    # comma-separated list is not valid JSON, so the parse raised
    #
    #     SettingsError: error parsing value for field "cors_origins"
    #                              from source "EnvSettingsSource"
    #
    # and `_split_origins` below was never reached — the field could not be set from the
    # environment at all, by any format except a JSON array.
    #
    # That went unnoticed locally because `.env` does not define CORS_ORIGINS, so the
    # default factory was used. It surfaced only when deploying, where the variable must be
    # set — i.e. it would have failed the first production deploy.
    #
    # `NoDecode` hands the raw string to the validator, which accepts comma-separated,
    # JSON-array, and single-value forms.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"],
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
    )

    # -------------------------------------------------------------------- ai tutor
    ai_provider: AIProviderName = "gemini"
    ai_api_key: str = ""
    ai_model: str = "gemini-2.0-flash"
    ai_base_url: str = ""
    ai_timeout_seconds: float = 60.0
    ai_max_history_messages: int = 12
    ai_rate_limit_per_hour: int = 60

    # ------------------------------------------------------- business rules / knobs
    default_timezone: str = "UTC"
    daily_dsa_count_default: int = 3
    daily_dsa_count_max: int = 15
    revision_dsa_count_default: int = 5
    revision_dsa_count_max: int = 25
    streak_min_minutes: int = 1
    streak_min_activities: int = 1
    revision_intervals: dict[str, list[int]] = Field(
        default_factory=lambda: dict(DEFAULT_REVISION_INTERVALS)
    )
    revision_low_confidence_threshold: int = 2
    #: Longest interval in the ladder. Derived from ``revision_intervals`` by the validator
    #: below rather than configured separately, so the two can never disagree.
    revision_ladder_max_interval: int = 365
    sync_pull_page_size: int = 200
    sync_pull_max_page_size: int = 500
    sync_max_mutations_per_push: int = 200
    default_page_limit: int = 50
    max_page_limit: int = 200
    export_max_rows: int = 20_000

    # -------------------------------------------------------------------- frontend
    frontend_url: str = "http://localhost:5173"

    # ---------------------------------------------------------------- normalisation
    @field_validator("database_url", "database_url_direct", "test_database_url", mode="after")
    @classmethod
    def _to_async_driver(cls, value: str) -> str:
        return _normalise_async_driver(value.strip()) if value else ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            raw = value.strip()
            # Tolerate a JSON array for parity with other list-valued settings.
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:  # pragma: no cover - defensive
                    parsed = None
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value

    @field_validator("revision_intervals", mode="before")
    @classmethod
    def _parse_intervals(cls, value: Any) -> Any:
        if value is None or value == "":
            return dict(DEFAULT_REVISION_INTERVALS)
        if isinstance(value, str):
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError("REVISION_INTERVALS_JSON must be a JSON object")
            return parsed
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _validate_revision_ladder(self) -> Settings:
        longest = 0
        for confidence, intervals in self.revision_intervals.items():
            try:
                key = int(confidence)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"revision_intervals keys must be integers 0-5, got {confidence!r}"
                ) from exc
            if not 0 <= key <= 5:
                raise ValueError(f"revision_intervals key out of range: {key}")
            if not intervals or any(int(i) <= 0 for i in intervals):
                raise ValueError(
                    f"revision_intervals[{key}] must be a non-empty list of positive days"
                )
            longest = max(longest, max(int(i) for i in intervals))

        # Keep the derived staleness threshold in step with the configured ladder.
        object.__setattr__(self, "revision_ladder_max_interval", longest or 365)
        return self

    # ------------------------------------------------------------------- computed
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def migration_database_url(self) -> str:
        """Direct (non-pooler) URL preferred for Alembic; falls back to the runtime URL."""
        return self.database_url_direct or self.database_url

    @property
    def resolved_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if not self.supabase_url:
            return ""
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        if not self.supabase_url:
            return ""
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def jwks_uri_host(self) -> str:
        """Host used to validate that a token's issuer matches our Supabase project."""
        if not self.supabase_url:
            return ""
        return urlparse(self.supabase_url).hostname or ""

    @property
    def is_connectable(self) -> bool:
        return bool(self.database_url)

    def dsa_daily_count(self, user_value: int | None) -> int:
        """Clamp a user's preferred daily question count to a sane range."""
        if user_value is None:
            return self.daily_dsa_count_default
        return max(1, min(int(user_value), self.daily_dsa_count_max))

    def revision_daily_count(self, user_value: int | None) -> int:
        if user_value is None:
            return self.revision_dsa_count_default
        return max(0, min(int(user_value), self.revision_dsa_count_max))

    def intervals_for_confidence(self, confidence: int | None) -> list[int]:
        """Return the spaced-repetition ladder for a 0-5 confidence score."""
        score = 0 if confidence is None else max(0, min(int(confidence), 5))
        return [int(day) for day in self.revision_intervals[str(score)]]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (cached so it is cheap to depend on)."""
    return Settings()


SettingsDep = Annotated[Settings, Field()]
