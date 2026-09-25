"""FastAPI application factory and lifecycle.

Run locally with::

    uvicorn app.main:app --reload

Swagger UI is available at ``http://localhost:8000/docs`` and the raw schema at
``/openapi.json``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import SupabaseTokenVerifier
from app.db.session import dispose_engine, get_engine
from app.schemas.common import HealthResponse, ReadinessResponse

logger = get_logger(__name__)

DESCRIPTION = """
Backend API for **InterviewReady**, an interview-preparation platform covering DSA,
Low-Level Design, High-Level Design, spaced-repetition revision and an AI tutor.

### Authentication
Log in with Supabase Auth from the client, then send the resulting access token:

```
Authorization: Bearer <supabase_access_token>
```

The user id is always taken from the verified token's `sub` claim. A `user_id` sent in a
request body or query string is ignored.

### Errors
Every failure uses one envelope:

```json
{"error": {"code": "PROBLEM_NOT_FOUND", "message": "DSA problem not found", "details": null}}
```

### Offline sync
`POST /api/v1/sync/push` is idempotent per `mutation_id`, and `GET /api/v1/sync/pull`
returns changes after a server-issued cursor. Server versions and the server clock are
authoritative — never the device clock.
"""

TAGS_METADATA = [
    {"name": "system", "description": "Health and readiness probes."},
    {"name": "user", "description": "The authenticated user's identity."},
    {"name": "today", "description": "Today's plan and daily plan history."},
    {"name": "dsa", "description": "DSA catalog, progress, attempts, notes and code."},
    {"name": "revisions", "description": "Spaced-repetition queue."},
    {"name": "lld", "description": "Low-level design curriculum and user data."},
    {"name": "hld", "description": "High-level design curriculum and user data."},
    {"name": "study-sessions", "description": "Server-timed study sessions."},
    {"name": "stats", "description": "Progress analytics, topic mastery and streaks."},
    {"name": "ai", "description": "AI tutor chat and conversation history."},
    {"name": "sync", "description": "Offline device synchronisation."},
    {"name": "settings", "description": "Per-user preferences."},
    {"name": "export", "description": "Portable export of the user's own data."},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown: logging, auth verifier, database engine."""
    settings: Settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json, force=True)

    logger.info(
        "Starting application",
        extra={"env": settings.app_env, "debug": settings.debug},
    )

    # Built once and shared: the verifier holds a cached JWKS over an httpx client.
    verifier = SupabaseTokenVerifier(settings)
    app.state.token_verifier = verifier

    # The AI provider is built once too, so its HTTP connection pool is reused across
    # requests. A provider that is not configured is not fatal: the rest of the API keeps
    # working and the tutor endpoints return 503.
    try:
        from app.services.ai.factory import build_provider

        app.state.ai_provider = build_provider(settings)
    except Exception as exc:
        app.state.ai_provider = None
        logger.warning("AI tutor is unavailable: %s", exc)

    if verifier.configured:
        # Fetch the JWKS at boot so a misconfigured project URL or a legacy HS256-only
        # project is reported in the logs at startup rather than on the first user request.
        if await verifier.ensure_jwks_available():
            logger.info("Supabase JWKS loaded", extra=verifier.health())
        else:
            logger.warning(
                "Could not load the Supabase JWKS at startup. Authenticated requests will "
                "fail until it is reachable.",
                extra=verifier.health(),
            )
    else:
        logger.warning("SUPABASE_URL is not set — authenticated endpoints will return 401")

    if not settings.is_connectable:
        logger.warning(
            "DATABASE_URL is not set — database-backed endpoints will return 503",
        )
    else:
        # Fail fast on a bad URL/credentials instead of on the first request.
        try:
            get_engine()
        except Exception as exc:
            logger.error("Could not create the database engine", exc_info=exc)

    yield

    logger.info("Shutting down application")

    verifier: SupabaseTokenVerifier | None = getattr(app.state, "token_verifier", None)
    if verifier is not None:
        await verifier.aclose()

    provider = getattr(app.state, "ai_provider", None)
    if provider is not None:
        try:
            await provider.aclose()
        except Exception:
            logger.warning("AI provider shutdown raised", exc_info=True)

    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application (extracted so tests can construct their own)."""
    settings = settings or get_settings()

    app = FastAPI(
        title="InterviewReady API",
        description=DESCRIPTION,
        version="1.0.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
        openapi_tags=TAGS_METADATA,
        contact={"name": "InterviewReady"},
        license_info={"name": "Private"},
    )

    # Middleware runs in reverse registration order, so register the correlation-id
    # middleware last to guarantee it wraps everything else and stamps every response.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    if settings.cors_origins:
        if "*" in settings.cors_origins and settings.is_production:
            raise RuntimeError(
                "Wildcard CORS origin is not permitted in production. "
                "Set CORS_ORIGINS to the explicit frontend origins."
            )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Device-Id"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    else:
        logger.warning("No CORS origins configured — browser clients will be blocked")

    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    # ---------------------------------------------------------------- health (root)
    @app.get("/health", tags=["system"], summary="Liveness probe")
    async def health() -> HealthResponse:
        """Returns ``{"status": "ok"}`` whenever the process is serving traffic."""
        return HealthResponse(status="ok")

    @app.get("/health/ready", tags=["system"], summary="Readiness probe")
    async def health_ready() -> ReadinessResponse:
        """Verifies database connectivity and auth configuration.

        The token verifier is normally built during startup; it is constructed on demand
        here so readiness still reports accurately when lifespan events did not run (as in
        a direct ASGI test client).
        """
        from app.db.session import get_session_factory, ping

        settings_local = get_settings()

        verifier: SupabaseTokenVerifier | None = getattr(app.state, "token_verifier", None)
        if verifier is None:
            verifier = SupabaseTokenVerifier(settings_local)
            app.state.token_verifier = verifier

        auth_ok = verifier.configured

        if not settings_local.is_connectable:
            return ReadinessResponse(
                status="degraded",
                database=False,
                auth=auth_ok,
                detail="DATABASE_URL is not configured.",
                auth_config=verifier.health(),
            )

        factory = get_session_factory()
        async with factory() as session:
            database_ok = await ping(session)

        ready = database_ok and auth_ok
        detail = None
        if not ready:
            missing = []
            if not database_ok:
                missing.append("database")
            if not auth_ok:
                missing.append("SUPABASE_URL (authentication)")
            detail = "Unavailable: " + ", ".join(missing)

        return ReadinessResponse(
            status="ok" if ready else "degraded",
            database=database_ok,
            auth=auth_ok,
            detail=detail,
            auth_config=verifier.health(),
        )

    # ------------------------------------------------------------------ versioned API
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    # Give the OpenAPI schema a bearer-auth security scheme so /docs is usable directly.
    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=TAGS_METADATA,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "SupabaseBearer"
        ] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Supabase Auth access token. Obtain it from the Supabase client after "
                "sign-in; the backend verifies it against the project's public JWKS."
            ),
        }
        schema["security"] = [{"SupabaseBearer": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app


app = create_app()
