"""Async SQLAlchemy engine / session management.

Two things in here matter operationally:

1. **Supabase pooler compatibility.** Supabase's Supavisor transaction pooler (port 6543)
   does not support the prepared statements asyncpg creates by default, so
   ``statement_cache_size=0`` and ``prepared_statement_cache_size=0`` are mandatory.
   Without them asyncpg intermittently raises
   ``InvalidSQLStatementNameError`` / ``DuplicatePreparedStatementError``.
2. **RLS defense-in-depth.** ``set_current_user`` publishes the verified JWT subject as a
   PostgreSQL session variable so row-level-security policies can reference it via
   ``current_setting('app.current_user_id', true)``. The application also scopes every
   query explicitly in the repository layer; the GUC is the second line of defence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _connect_args(settings: Settings) -> dict[str, Any]:
    """asyncpg connect args that keep Supabase's pooler happy."""
    args: dict[str, Any] = {
        # Required behind Supavisor / PgBouncer in transaction mode.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        # Fail fast instead of hanging a worker on a dead connection.
        "timeout": 30,
        "command_timeout": max(settings.db_statement_timeout_ms / 1000, 5),
        "server_settings": {
            "application_name": "interviewready-api",
            # Guard against a runaway analytics query pinning the shared pool.
            "statement_timeout": str(settings.db_statement_timeout_ms),
        },
    }
    return args


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build an :class:`AsyncEngine` from settings (no caching — used by tests too)."""
    settings = settings or get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Copy .env.example to .env and set it."
        )

    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        connect_args=_connect_args(settings),
    )


def get_engine() -> AsyncEngine:
    """Process-wide engine singleton."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Process-wide session factory singleton.

    ``expire_on_commit=False`` matters for async: attribute refresh after commit would
    otherwise trigger implicit IO on an object being serialised outside the session.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    Rolls back on any exception so a failed request can never leave a partial
    transaction on a pooled connection.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for scripts and background tasks."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def set_current_user(session: AsyncSession, user_id: str | None) -> None:
    """Publish the authenticated user id for RLS policies.

    ``set_config(..., true)`` is transaction-local, so it cannot leak to the next
    request that borrows the same pooled connection.
    """
    if not user_id:
        return
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )


async def ping(session: AsyncSession) -> bool:
    """Cheap liveness probe used by ``/health/ready``."""
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover - depends on infrastructure
        logger.warning("Database readiness probe failed", exc_info=True)
        return False


async def dispose_engine() -> None:
    """Release pooled connections on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("Database engine disposed")
    _engine = None
    _session_factory = None


__all__ = [
    "create_engine",
    "dispose_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
    "ping",
    "session_scope",
    "set_current_user",
]
