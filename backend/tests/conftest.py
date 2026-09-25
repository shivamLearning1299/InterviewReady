"""Shared pytest fixtures for the InterviewReady backend test suite.

Design decisions
----------------
* **DB-backed tests are opt-in.** They run only when ``TEST_DATABASE_URL`` is set, so
  ``pytest`` never fails on a machine without PostgreSQL. Set it to a database that is
  safe to destroy — the session fixture truncates every table.
* **One schema build per session.** Alembic is applied once, then each test runs inside a
  nested transaction that is rolled back, so tests are order-independent and cannot leak
  state into each other.
* **Auth is stubbed at the dependency layer, not the HTTP layer.** ``get_current_user`` is
  overridden, which is exactly where the real JWT check lives. Routes therefore exercise
  the same code path as production apart from signature verification, which
  ``test_auth.py`` covers separately.
* **The app under test is the real app.** ``create_app()`` is used unchanged so middleware,
  error handlers and route wiring are all covered.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

#: A fake Supabase project URL. Tests must never point at a real project, and the value is
#: fixed so assertions on derived values (JWKS URL, issuer) are stable.
TEST_SUPABASE_URL = "https://test-project.supabase.co"


# --------------------------------------------------------------------------- utilities
def _test_database_url() -> str | None:
    """The test database URL, or ``None`` when tests should be skipped."""
    return os.environ.get("TEST_DATABASE_URL") or None


def _async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


#: Tables truncated between the schema build and the first test. Ordered is unnecessary
#: because TRUNCATE ... CASCADE handles dependencies.
ALL_TABLES = (
    "ai_messages",
    "ai_conversations",
    "ai_rate_limits",
    "sync_mutations",
    "sync_changes",
    "user_devices",
    "user_activity_days",
    "study_sessions",
    "daily_plan_items",
    "daily_plans",
    "revision_queue",
    "problem_attempts",
    "code_snippets",
    "problem_notes",
    "user_problem_progress",
    "lld_notes",
    "lld_progress",
    "hld_notes",
    "hld_progress",
    "user_settings",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every test marked ``db`` when no test database is configured."""
    if _test_database_url():
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set — DB-backed test skipped")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


# ------------------------------------------------------------------------- session setup
@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def apply_migrations(database_url: str) -> None:
    """Build the schema once, from a clean slate.

    Order matters and mirrors production: the pre-existing Supabase tables must exist
    *before* Alembic runs, because migration ``0001`` adapts those tables rather than
    creating them (and ``0002`` adds tables that reference them). ``tests/fixtures/
    legacy_schema.sql`` reproduces that starting point.

    Uses the real migration chain rather than ``metadata.create_all`` so the tests validate
    the migrations themselves — a broken migration must fail the suite.
    """
    import asyncpg

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parsed = urlparse(sync_url)

    async def prepare() -> None:
        conn = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=(parsed.path or "/postgres").lstrip("/") or "postgres",
        )
        try:
            # Rebuild from scratch so a stale database can never mask a migration error.
            await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
            await conn.execute("DROP SCHEMA IF EXISTS auth CASCADE")
            await conn.execute("CREATE SCHEMA public")
            legacy = (BACKEND_ROOT / "tests" / "fixtures" / "legacy_schema.sql").read_text()
            await conn.execute(legacy)
        finally:
            await conn.close()

    asyncio.run(prepare())

    env = {**os.environ, "DATABASE_URL": database_url, "DATABASE_URL_DIRECT": database_url}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head failed — the test database could not be prepared:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


@pytest.fixture(scope="session")
def settings(database_url: str, apply_migrations: None):
    """Application settings bound to the test database.

    Values are *assigned*, not ``setdefault``-ed: a developer shell that has sourced the real
    ``.env`` has already exported ``SUPABASE_URL``, and letting that leak in would make the
    auth tests depend on ambient environment. Tests must be reproducible regardless of what
    the calling shell happens to export.
    """
    os.environ["DATABASE_URL"] = database_url
    os.environ["DATABASE_URL_DIRECT"] = database_url
    os.environ["SUPABASE_URL"] = TEST_SUPABASE_URL
    os.environ["SUPABASE_PUBLISHABLE_KEY"] = "sb_publishable_test"
    os.environ["AI_PROVIDER"] = "stub"
    os.environ["APP_ENV"] = "test"

    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    return Settings(
        DATABASE_URL=database_url,
        DATABASE_URL_DIRECT=database_url,
        SUPABASE_URL=TEST_SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
        AI_PROVIDER="stub",
        APP_ENV="test",
    )


@pytest_asyncio.fixture(scope="session")
async def engine(settings) -> AsyncIterator[Any]:
    """Session-scoped engine pointing at the test database.

    ``NullPool`` is essential: tests each run in their own event loop, and a pooled
    connection created in one loop cannot be reused from another ("attached to a different
    loop"). Opening a fresh connection per checkout keeps each loop self-contained.
    """
    eng = create_async_engine(_async_url(settings.database_url), poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def clean_database(engine) -> None:
    """Empty every table once per session, before any test runs.

    Deliberately *not* ``autouse``: unit tests must not require a database, and an autouse
    session fixture would drag the whole schema build into every run.
    """
    async with engine.begin() as conn:
        for table in ALL_TABLES:
            await conn.execute(text(f'TRUNCATE TABLE public."{table}" CASCADE'))
        # auth.users is the FK target for legacy tables; remove test users too.
        await conn.execute(text("TRUNCATE TABLE auth.users CASCADE"))


@pytest_asyncio.fixture
async def connection(engine, clean_database) -> AsyncIterator[AsyncConnection]:
    """A connection wrapped in a transaction that is rolled back after the test."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def db_session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session bound to the test's transaction.

    Services call ``session.commit()``. Joining an external transaction means those commits
    land in the rolled-back outer transaction, so the database returns to its pre-test state
    while the code under test behaves exactly as it does in production.

    The session is *re-synced* before every HTTP request (see the client fixtures). In
    production each request gets its own session; sharing one here is what makes rollback
    possible, but a shared identity map would let a later request read a stale object that
    an earlier request's raw-SQL upsert had already changed. That discrepancy is invisible in
    real deployments and would mask genuine bugs, so it is eliminated rather than tolerated.
    """
    factory = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        original_commit = session.commit

        async def commit_without_ending_transaction() -> None:
            await session.flush()

        session.commit = commit_without_ending_transaction  # type: ignore[method-assign]
        try:
            yield session
        finally:
            session.commit = original_commit  # type: ignore[method-assign]


async def reset_session_identity_map(session: AsyncSession) -> None:
    """Drop cached ORM state so the next request re-reads from the database.

    Must be awaited from an async context — ``expire_all`` alone would trigger lazy IO on
    the next attribute access, which fails outside a greenlet.
    """
    await session.flush()
    session.expunge_all()


# -------------------------------------------------------------------------------- users
@pytest_asyncio.fixture
async def user_id(connection: AsyncConnection) -> uuid.UUID:
    """A user that exists in ``auth.users``, so legacy FKs are satisfied."""
    new_id = uuid.uuid4()
    await connection.execute(
        text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": str(new_id)}
    )
    return new_id


@pytest_asyncio.fixture
async def other_user_id(connection: AsyncConnection) -> uuid.UUID:
    """A second user, used to prove data isolation between accounts."""
    new_id = uuid.uuid4()
    await connection.execute(
        text("INSERT INTO auth.users (id) VALUES (:id)"), {"id": str(new_id)}
    )
    return new_id


@pytest.fixture
def current_user(user_id: uuid.UUID):
    """The identity returned by the stubbed auth dependency."""
    from app.core.security import AuthenticatedUser

    return AuthenticatedUser(
        id=user_id, email="student@example.com", role="authenticated", session_id="sess-1"
    )


@pytest.fixture
def as_other_user(other_user_id: uuid.UUID):
    from app.core.security import AuthenticatedUser

    return AuthenticatedUser(
        id=other_user_id, email="other@example.com", role="authenticated", session_id="sess-2"
    )


# ---------------------------------------------------------------------------- the client
@pytest_asyncio.fixture
async def client(
    settings, current_user, db_session: AsyncSession
) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client bound to the real ASGI app with auth and the DB session stubbed."""
    from app.api import deps
    from app.core.config import get_settings
    from app.db import session as db_module
    from app.main import create_app

    app = create_app()

    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.get_current_user] = lambda: current_user
    app.dependency_overrides[db_module.get_db] = lambda: db_session

    # The AI provider is normally built during lifespan; build the deterministic stub
    # through the same factory production uses so the wiring is identical.
    from app.services.ai.factory import build_provider

    app.state.ai_provider = build_provider(settings)
    app.state.token_verifier = None

    # Every request starts from a clean identity map, exactly as it would in production
    # where each request gets its own session. Without this, one request could read an
    # object cached by an earlier one and a regression would go unnoticed.
    async def _reset(_request: httpx.Request) -> None:
        await reset_session_identity_map(db_session)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", event_hooks={"request": [_reset]}
    ) as http:
        yield http

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """A client with no auth override, so real 401 behaviour is observable."""
    from app.api import deps
    from app.core.config import get_settings
    from app.db import session as db_module
    from app.main import create_app
    from app.services.ai.factory import build_provider

    app = create_app()
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[db_module.get_db] = lambda: db_session
    app.state.ai_provider = build_provider(settings)

    # Every request starts from a clean identity map, exactly as it would in production
    # where each request gets its own session. Without this, one request could read an
    # object cached by an earlier one and a regression would go unnoticed.
    async def _reset(_request: httpx.Request) -> None:
        await reset_session_identity_map(db_session)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", event_hooks={"request": [_reset]}
    ) as http:
        yield http

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def other_client(
    settings, as_other_user, db_session: AsyncSession
) -> AsyncIterator[httpx.AsyncClient]:
    """A client authenticated as a *second* user, for isolation tests."""
    from app.api import deps
    from app.core.config import get_settings
    from app.db import session as db_module
    from app.main import create_app
    from app.services.ai.factory import build_provider

    app = create_app()
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.get_current_user] = lambda: as_other_user
    app.dependency_overrides[db_module.get_db] = lambda: db_session
    app.state.ai_provider = build_provider(settings)

    # Every request starts from a clean identity map, exactly as it would in production
    # where each request gets its own session. Without this, one request could read an
    # object cached by an earlier one and a regression would go unnoticed.
    async def _reset(_request: httpx.Request) -> None:
        await reset_session_identity_map(db_session)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", event_hooks={"request": [_reset]}
    ) as http:
        yield http

    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- catalog data
@pytest_asyncio.fixture
async def seeded_catalog(db_session: AsyncSession) -> list[str]:
    """A small deterministic DSA catalog.

    Deliberately not the full seeded curriculum: tests should assert on data they control.
    """
    from app.db.models import DSATopic, DSAProblem

    topics = ["arrays", "strings", "graphs"]
    for index, slug in enumerate(topics):
        db_session.add(
            DSATopic(
                id=slug,
                name=slug.title(),
                slug=slug,
                description=f"{slug} problems",
                order_index=index,
            )
        )

    problems = [
        ("two-sum", "Two Sum", "arrays", "easy"),
        ("best-time-to-buy-and-sell-stock", "Best Time to Buy and Sell Stock", "arrays", "easy"),
        ("contains-duplicate", "Contains Duplicate", "arrays", "easy"),
        ("longest-substring-without-repeating-characters", "Longest Substring", "strings", "medium"),
        ("valid-anagram", "Valid Anagram", "strings", "easy"),
        ("number-of-islands", "Number of Islands", "graphs", "medium"),
        ("course-schedule", "Course Schedule", "graphs", "medium"),
        ("word-ladder", "Word Ladder", "graphs", "hard"),
    ]
    for index, (slug, title, topic, difficulty) in enumerate(problems):
        db_session.add(
            DSAProblem(
                id=slug,
                title=title,
                slug=slug,
                primary_topic=topic,
                difficulty=difficulty,
                source="leetcode",
                order_index=index,
                importance=3,
                estimated_minutes=30,
                is_active=True,
            )
        )
    await db_session.flush()
    return [slug for slug, *_ in problems]


@pytest_asyncio.fixture
async def seeded_topics(db_session: AsyncSession) -> dict[str, list[uuid.UUID]]:
    """A small LLD and HLD catalog, one topic each."""
    from app.db.models import HLDTopic, LLDTopic

    lld = [
        ("parking-lot", "Parking Lot", "fundamentals"),
        ("tic-tac-toe", "Tic Tac Toe", "design_exercises"),
    ]
    hld = [
        ("design-url-shortener", "URL Shortener", "system_design"),
        ("design-a-chat-system", "Chat System", "system_design"),
    ]

    lld_topics: list[LLDTopic] = []
    for index, (slug, title, category) in enumerate(lld):
        topic = LLDTopic(
            title=title, slug=slug, category=category, order_index=index, difficulty="medium"
        )
        db_session.add(topic)
        lld_topics.append(topic)

    hld_topics: list[HLDTopic] = []
    for index, (slug, title, category) in enumerate(hld):
        topic = HLDTopic(
            title=title, slug=slug, category=category, order_index=index, difficulty="hard"
        )
        db_session.add(topic)
        hld_topics.append(topic)

    # Ids are Python-side UUID defaults, so they only exist after a flush.
    await db_session.flush()
    return {
        "lld": [topic.id for topic in lld_topics],
        "hld": [topic.id for topic in hld_topics],
    }
