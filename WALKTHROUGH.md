# InterviewReady — Walkthrough

A guided tour of the backend, in the order you should read it. Each stop answers *what this does,
why it exists, and what will bite you if you change it.*

**Prerequisites:** read `SUMMARY.md` first, then `ARCHITECTURE.md` for the reasoning. This document
is the hands-on path through the code.

**Time:** ~2 hours end to end. Each stage is self-contained if you're short on time.

---

## Stage 0 — Get it running (10 min)

```bash
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Fill in three values in `.env`:

```bash
DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres
DATABASE_URL_DIRECT=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

Then:

```bash
alembic upgrade head
python -m scripts.seed_curriculum
uvicorn app.main:app --reload
```

Open <http://localhost:8000/docs>. Two checks:

```bash
curl -s localhost:8000/health/ready | python3 -m json.tool
# database: true, auth: true   ← if either is false, stop and fix it now
```

**If `alembic upgrade head` fails with `invalid interpolation syntax`:** your password contains a
`%`. URL-encode it (`%` → `%25`). This is the single most common first-run failure.

**If it fails with `relation "daily_plans" does not exist`:** you're pointing at an empty database.
Migration `0001` *adapts* the pre-existing tables; it doesn't create them. See
[Stage 10](#stage-10--migrations-15-min).

---

## Stage 1 — The entry point (15 min)

**Read:** `app/main.py`

```python
def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan, ...)
    ...
```

A factory rather than a module-level `app`, so tests can build an isolated instance and override
dependencies without sharing state.

### The lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    verifier = SupabaseTokenVerifier(settings)
    await verifier.ensure_jwks_available()      # warm the JWKS cache
    app.state.token_verifier = verifier

    try:
        app.state.ai_provider = build_provider(settings)
    except AIConfigurationError:
        app.state.ai_provider = None            # non-fatal: AI is never on the critical path
        logger.warning(...)

    yield

    await verifier.aclose()
    await dispose_engine()
```

Two things to internalise:

1. **JWKS is fetched once at boot** and cached. A failure logs a warning but does not abort startup
   — individual requests then fail closed with 401 rather than the whole service being down.
2. **The AI provider is optional.** If `AI_API_KEY` is absent, the app starts normally and only
   `/ai/*` reports the tutor unavailable. Startup must never fail because an optional integration
   is unconfigured.

### Custom OpenAPI

`openapi()` adds a `SupabaseBearer` security scheme so the **Authorize** button in Swagger accepts
a Supabase access token directly. Without it you'd hand-edit every request.

**Try this:** start the server, open `/docs`, click Authorize, paste a token, and call
`GET /api/v1/me`. That single flow exercises route → dependency → service → repository → database.

---

## Stage 2 — Configuration (15 min)

**Read:** `app/core/config.py`

`Settings(BaseSettings)` with a `@lru_cache`d `get_settings()`. Cached because it's a dependency of
almost everything and re-parsing env vars per request is wasteful.

### Normalisation

```python
def _normalise_async_driver(url: str) -> str:
    """Rewrite a libpq-style URL to the SQLAlchemy asyncpg dialect."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url
```

Supabase hands out `postgresql://`. SQLAlchemy needs an explicit async driver. Normalising here
means the value in `.env` stays copy-pasteable from the Supabase dashboard.

### Derived, never duplicated

```python
@property
def migration_database_url(self) -> str:
    """Direct (non-pooler) URL preferred for Alembic; falls back to the runtime URL."""
    return self.database_url_direct or self.database_url
```

Also `resolved_jwks_url`, `jwt_issuer`, `is_connectable`. The interesting one is
`revision_ladder_max_interval`, derived by a model validator so it can never disagree with the
ladder:

```python
longest = max(max(v) for v in self.revision_intervals.values())
object.__setattr__(self, "revision_ladder_max_interval", longest or 365)
```

`object.__setattr__` is required because pydantic models are frozen during validation.

### `AliasChoices`

```python
supabase_anon_key: str = Field(
    default="",
    validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY", "supabase_anon_key"),
)
```

Supabase renamed anon keys to publishable keys. Accepting both means neither existing nor new
deployments break.

**Try this:**

```bash
python -c "
from app.core.config import get_settings
s = get_settings()
print('db        :', s.database_url.split('@')[-1])
print('jwks      :', s.resolved_jwks_url)
print('ladder max:', s.revision_ladder_max_interval)
print('plan size :', s.dsa_daily_count(None), '-> clamped to', s.dsa_daily_count(9999))
"
```

That last line shows the clamping that stops a client requesting an unbounded plan.

---

## Stage 3 — The database session (15 min)

**Read:** `app/db/session.py`

### Pooler workarounds

```python
def _connect_args(settings) -> dict:
    return {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "command_timeout": settings.db_statement_timeout_ms / 1000,
    }
```

Both caches are **disabled** deliberately. Supabase's transaction-mode pooler (port 6543) routes
each statement to a possibly different backend connection, so a prepared statement cached on one
connection may not exist on the next — producing intermittent "prepared statement does not exist"
errors that are extremely hard to reproduce.

### Request scoping

```python
async def get_db() -> AsyncIterator[AsyncSession]:
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
```

Rollback on exception, always close. A failed request can never leave a partial transaction on a
pooled connection.

**Why services, not repositories, call `commit()`:** the session boundary is the request. A
repository that committed would make a multi-step service operation non-atomic.

### RLS helper

```python
async def set_current_user(session: AsyncSession, user_id: str | None) -> None:
    await session.execute(
        text("SELECT set_config('app.current_user_id', :uid, true)"),
        {"uid": str(user_id)},
    )
```

The `true` is the important part: `set_config(..., true)` is **transaction-local**, so it cannot
leak to the next request that borrows the same pooled connection.

---

## Stage 4 — Models and the big constraint (25 min)

**Read:** `app/db/models/catalog.py` then `app/db/models/dsa.py`

This is where the governing constraint becomes concrete. Read the module docstring of
`catalog.py` first:

> The primary key is `text` (the slug), matching the pre-existing `problem_id text` columns...
> so those existing rows join directly, with no rewriting of user data.

```python
class DSAProblem(StringPrimaryKeyMixin, Base):
    __tablename__ = "dsa_problems"
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    slug: Mapped[str] = mapped_column(String(300), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'medium'"))
    primary_topic: Mapped[str] = mapped_column(String(100), nullable=False)
    patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    importance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
```

### The missing foreign key

```python
progress = relationship(
    "UserProblemProgress",
    # No FK exists: pre-existing progress rows may reference problems that predate
    # the catalog. The join is declared explicitly and marked viewonly.
    primaryjoin="DSAProblem.id == foreign(UserProblemProgress.problem_id)",
    back_populates="problem",
    viewonly=True,
    lazy="selectin",
)
```

Three deliberate choices:

- **`viewonly=True`** — the ORM may read through it but never writes. Persistence is always driven
  by repositories, so a stale relationship can never cause a surprise write.
- **Explicit `primaryjoin`** — there's no FK for SQLAlchemy to infer from.
- **`lazy="selectin"`** — avoids N+1 when serialising a catalog page.

### `_PROBLEM_STATUS_SQL`

```python
_PROBLEM_STATUS_SQL = "'not_started','attempted','solved','needs_revision','mastered'"

class UserProblemProgress(...):
    __table_args__ = (
        CheckConstraint(f"status IN ({_PROBLEM_STATUS_SQL})", name="status_valid"),
        ...
    )
```

The CHECK vocabulary is shared with the Python enum via `app/core/constants.py`. If they diverge,
the database rejects a value the application thinks is valid.

### The NOT NULL trap

```python
status: Mapped[str] = mapped_column(
    String(30), nullable=False, server_default=text("'not_started'")
)
```

The `server_default` matters enormously. It was originally **absent** — the only NOT NULL column in
that table without one — and the consequence was that every partial upsert failed:

```sql
-- Fails with "null value in column status violates not-null constraint",
-- even though the row exists and this statement would not touch status.
INSERT INTO user_problem_progress (id, user_id, problem_id, confidence)
VALUES (..., 4)
ON CONFLICT (user_id, problem_id) DO UPDATE SET confidence = excluded.confidence;
```

PostgreSQL validates the **proposed insert row** before it checks for a conflict. See
[Stage 8](#stage-8--upserts-the-not-null-trap-25-min).

### The mixin convention

`TimestampedModel.id` is a **UUID**. `CatalogModel.id` is a **`str`** (the slug). A catalog schema
that inherits the wrong base produces a 500 on every request:

```
Input should be a valid UUID, invalid character: found 't' at 1 [input_value='two-sum']
```

**Rule to remember:** catalog rows keyed by slug extend `CatalogModel`. Everything else extends
`TimestampedModel`.

**Try this:**

```bash
python -m scripts.validate_models
```

It compiles every table and configures all mappers — catching a bad column definition before a
migration does.

---

## Stage 5 — Dependencies and identity (15 min)

**Read:** `app/api/deps.py`

```python
async def get_current_user(
    request: Request,
    verifier: TokenVerifierDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    token = extract_bearer_token(authorization)
    if token is None:
        raise UnauthenticatedError("Provide a Supabase access token as 'Authorization: Bearer <token>'.")

    user = await verifier.verify(token)
    bind_request_context(user_id=str(user.id))
    request.state.user_id = str(user.id)
    return user
```

**This is the only source of identity in the entire codebase.** No route accepts a `user_id`
parameter. That's what makes cross-user access structurally impossible rather than
policy-enforced — which is why it's worth grepping for:

```bash
grep -rn "user_id" app/api/v1/ | grep -v "current_user.id" | grep -v "^.*#" | head
```

Every hit should be a path parameter for a *record* (`item_id`, `topic_id`), never a user
identity.

### Why `Authorization` only

The token is read from the header only — never a query parameter or cookie. A token in a URL ends
up in access logs, browser history and `Referer` headers.

### Pagination clamping

```python
def get_pagination(settings, limit=None, offset=0) -> Pagination:
    effective = settings.default_page_limit if limit is None else limit
    return Pagination(limit=min(effective, settings.max_page_limit), offset=offset)
```

A client cannot request the entire catalog in one call.

---

## Stage 6 — Following one request end to end (25 min)

The best way to learn the layering is to trace a single write. Let's follow
`PUT /api/v1/dsa/problems/two-sum/progress`.

### 6.1 Router

**Read:** `app/api/v1/dsa.py`, the `update_progress` handler

```python
@router.put("/problems/{problem_id}/progress", response_model=ProgressResponse, ...)
async def update_progress(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: ProgressUpdateRequest,
    problem_id: str,
    timezone: ClientTimezone = None,
) -> ProgressResponse:
    return await services.progress.upsert(
        user_id=current_user.id, problem_id=problem_id, payload=payload, timezone=timezone,
    )
```

Note what's *absent*: no validation beyond pydantic, no branching, no database access. The
handler's job is dependency resolution and delegation.

`ServicesDep` is the container:

```python
def get_services(request: Request, session: AsyncSession, settings: Settings) -> Services:
    services = Services(session, settings)
    provider = getattr(request.app.state, "ai_provider", None)
    if provider is not None:
        services.ai._provider = provider   # reuse the process-wide provider
    return services
```

Built per request — deliberately **not** cached on `app.state`, because a cached container holds a
cached `AsyncSession`, and a session must never outlive its request.

### 6.2 Service

**Read:** `app/services/dsa_service.py`, `ProgressService.upsert`

The decision layer. Read it in order:

```python
# 1. Validate the problem exists. There is no FK, so this is the only thing
#    preventing orphan progress rows.
problem, _ = await self._catalog_repo.get_with_progress(user_id=user_id, problem_id=problem_id)

existing = await self._progress_repo.get(user_id=user_id, problem_id=problem_id)
now = utcnow()
values: dict[str, Any] = {}
```

```python
# 2. Derive timestamps from the TRANSITION, never from the client.
if payload.status is not None:
    status = payload.status.value if hasattr(payload.status, "value") else payload.status
    values["status"] = status

    if status == ProblemStatus.NOT_STARTED.value:
        values["first_attempt_date"] = None
        values["solved_date"] = None
        values["next_revision_date"] = None
    else:
        if existing is None or existing.first_attempt_date is None:
            values["first_attempt_date"] = now
```

The asymmetry is intentional: moving *forward* sets a timestamp if unset (idempotent — replaying
doesn't move it), while resetting *clears* the derived timestamps so the UI isn't misleading.

```python
        if status in (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value):
            ...
            # Solving schedules the first revision.
            schedule = self._policy.schedule_after_solve(confidence=confidence, from_time=now)
            values["next_revision_date"] = schedule.due_at
            await self._revision_repo.upsert_open_revision(...)
```

Solving a problem and scheduling its first review are **one atomic operation**. If they were
separate, a crash between them would leave a solved problem that never comes back for review.

```python
# 3. Empty payload → return current state, don't write.
if not values:
    if existing is not None:
        return self._to_response(existing)
    values = {"status": ProblemStatus.NOT_STARTED.value}
```

An empty PUT shouldn't bump `version`. If nothing exists, a default row is created so the response
is well-formed.

```python
# 4. Commit — the service owns durability.
await self._progress_repo.session.commit()
```

### 6.3 Repository

**Read:** `app/repositories/dsa.py`, `ProblemProgressRepository.upsert`

```python
async def upsert(self, *, user_id, problem_id, values, conflict_columns=None):
    payload = {"user_id": user_id, "problem_id": problem_id, **values}
    stmt = build_upsert_statement(
        UserProblemProgress, payload,
        conflict_columns=conflict_columns or ["user_id", "problem_id"],
    ).execution_options(populate_existing=True)
    return (await self.session.execute(stmt)).scalars().one()
```

`populate_existing=True` guarantees the returned object reflects **this statement's** result rather
than a stale copy in the session's identity map. Without it, a session that had loaded the row
earlier would keep returning the pre-upsert `version`, breaking optimistic concurrency.

### 6.4 Serialise back

```python
def _to_response(self, row) -> ProgressResponse:
    return ProgressResponse(
        ...,
        next_revision_at=row.next_revision_date,   # note: the API renames the column
        total_time_spent_minutes=row.time_spent_minutes,
    )
```

**Watch for the naming asymmetry.** The pre-existing `user_problem_progress` table uses
`*_date` suffixes (`first_attempt_date`, `solved_date`, `next_revision_date`), while the newer
LLD/HLD tables use `*_at` (`last_reviewed_at`, `next_revision_at`). The API normalises to `*_at`.

This asymmetry caused two real bugs: a filter on a non-existent `next_revision_at`, and LLD/HLD
progress writing a non-existent `last_reviewed_date`. Both returned 500s.

**Cheat sheet:**

| Concept | `user_problem_progress` | `lld_progress` / `hld_progress` |
|---|---|---|
| First attempt | `first_attempt_date` | — |
| Solved | `solved_date` | `completed_at` |
| Last reviewed | `last_reviewed_date` | `last_reviewed_at` |
| Next review | `next_revision_date` | `next_revision_at` |
| Total time | `time_spent_minutes` | `total_time_spent_minutes` |

**Try it:**

```bash
TOKEN="<your supabase access token>"
curl -s -X PUT localhost:8000/api/v1/dsa/problems/two-sum/progress \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"solved","confidence":3}' | python3 -m json.tool
```

Then run it again and compare `version` — it should increment, and the row should not duplicate.

---

## Stage 7 — Errors (15 min)

**Read:** `app/api/error_handlers.py`

```python
class ValidationError(AppError):
    status_code = 422      # literal, not Starlette's deprecated constant
    code = "VALIDATION_ERROR"
```

`AppError` subclasses carry `status_code` and `code`, so raising the right exception produces the
right response without a mapping table.

### Constraint names as API codes

```python
mappings = (
    ("uq_daily_plans_user_id_plan_date", "DAILY_PLAN_EXISTS", "A daily plan already exists for that date."),
    ("uq_sync_mutations_user_id_mutation_id", "DUPLICATE_MUTATION", "This mutation has already been applied."),
    ...
)
```

The constraints are load-bearing for correctness, so their violation gets a precise code. A
generic 409 would force the client to guess.

### The logging lesson

```python
# Good: the constraint appears in the log.
detail = str(getattr(exc, "orig", exc))
logger.warning("Integrity error: %s", detail[:400])

# Bad — this was the original code. The console formatter only renders configured
# extras, so this printed a bare "Integrity error" with no constraint name.
logger.warning("Integrity error", extra={"detail": detail[:400]})
```

That difference cost real debugging time: a constraint violation logged with no indication of
*which* constraint. When you need a value while debugging, interpolate it into the message.

### Bare `Exception`

```python
@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception", exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "...")
```

Guarantees the envelope holds even for a bug in the error path itself.

**Try it:**

```bash
# 401 — no token
curl -s localhost:8000/api/v1/me | python3 -m json.tool
# 422 — out-of-range confidence
curl -s -X PUT localhost:8000/api/v1/dsa/problems/two-sum/progress \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"confidence": 99}' | python3 -m json.tool
# 404 — unknown problem
curl -s localhost:8000/api/v1/dsa/problems/nope -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

All three must share the `{"error": {"code", "message", "details"}}` shape.

---

## Stage 8 — Upserts, the NOT NULL trap (25 min)

**Read:** `app/utils/upsert.py`

The single most important utility in the codebase.

```python
def build_upsert_statement(model, values, *, conflict_columns, update_columns=None, increment_version=True):
    values, injected = apply_server_defaults(model, dict(values))
    stmt = pg_insert(model).values(**values)

    if update_columns is None:
        update_columns = [
            key for key in values
            if key not in IMMUTABLE_COLUMNS
            and key not in conflict_columns
            and key not in injected          # ← the critical exclusion
            and key in existing_columns
        ]
    ...
    return stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_values).returning(model)
```

### Why `injected` must be excluded

```python
def apply_server_defaults(model, values) -> tuple[dict, set[str]]:
    """Fill in column defaults for NOT NULL columns the payload omits."""
    injected = set()
    for column in model.__table__.columns:
        if column.name in values or column.primary_key:
            continue
        if column.nullable or column.server_default is None:
            continue
        values[column.name] = column.server_default.arg
        injected.add(column.name)
    return values, injected
```

A default exists to populate a **new** row. If the same default were written in the `DO UPDATE`
clause, then syncing only `confidence` would silently reset `status` from `solved` back to
`not_started` — destroying the user's progress. That is the worst class of bug: silent data loss
that looks like success.

### Reproduce the trap (worth doing once)

Run this against a scratch database to see PostgreSQL's behaviour for yourself:

```sql
-- Set up
INSERT INTO user_problem_progress (id, user_id, problem_id, status)
VALUES (gen_random_uuid(), '<uid>', 'two-sum', 'solved');

-- The "update only confidence" case. Fails, even though status isn't being touched.
INSERT INTO user_problem_progress (id, user_id, problem_id, confidence)
VALUES (gen_random_uuid(), '<uid>', 'two-sum', 5)
ON CONFLICT (user_id, problem_id) DO UPDATE SET confidence = excluded.confidence;
-- ERROR: null value in column "status" violates not-null constraint
```

PostgreSQL validates the proposed insert row **before** detecting the conflict. Now check that the
live column actually has a default:

```sql
SELECT column_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'user_problem_progress' AND column_name = 'status';
-- should be: NO | 'not_started'::text
```

If `column_default` is NULL, your database predates migration `0003` and partial upserts will fail.
Check with `alembic current`.

### `upsert_returning`

```python
async def upsert_returning(session, model, values, *, conflict_columns, update_columns=None):
    stmt = build_upsert_statement(...).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalars().one()
```

One round trip instead of an INSERT plus a SELECT, on the hottest write paths.

---

## Stage 9 — The scheduler (35 min)

**Read:** `app/services/daily_plan_scheduler.py`

The most interesting algorithm here. Trace it via `select`.

### Determinism

```python
@staticmethod
def _jitter(*, user_id: uuid.UUID, plan_date: date, problem_id: str) -> float:
    digest = hashlib.blake2b(f"{user_id}:{plan_date.isoformat()}:{problem_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 300 / 100.0     # stable nudge in [0, 3)
```

Not `random`. Run the server with two workers and refresh the page: with `random`, a different
worker would produce a different plan. Hashing stable inputs means every worker computes the same
value, so the plan is reproducible **before** persistence is even considered. Persistence is the
second layer of the same guarantee.

### Scoring

```python
def _score(self, *, problem, progress, topic_position, total_topics, weakest_topics,
           recent_problem_ids, user_id, plan_date, stage) -> Candidate:
    score = 0.0

    # 1. Curriculum position — the backbone signal.
    curriculum_score = (1.0 - position_ratio) * 30.0
    score += curriculum_score

    # 2. Importance (1-5) — interview frequency.
    score += problem.importance * 3.0

    # 3. Difficulty ramp for the user's current stage.
    score += ramp.get(stage, 0.0)

    # 4. Weak-topic boost — deliberately large.
    if low_confidence and problem.primary_topic in weakest_topics:
        weakness_rank = weakest_topics.index(problem.primary_topic)
        score += max(4.0, 22.0 - weakness_rank * 3.0)

    # 5. Never re-assign something from a recent plan.
    if problem.id in recent_problem_ids:
        score -= 1000.0

    # 6-9. Exposure penalty, staleness bonus, company premium, deterministic jitter.
```

Signal 5 is an order of magnitude larger than any other weight — it must **dominate**, not merely
nudge. That's why it's −1000 rather than −50.

### Difficulty staging

```python
@staticmethod
def _stage_for(*, solved_count: int, total: int) -> int:
    if not total:
        return 0                        # guard: a fresh install must not divide by zero
    ratio = solved_count / total
    if ratio < 0.15: return 0
    if ratio < 0.45: return 1
    if ratio < 0.75: return 2
    return 3
```

### Weak topics

```python
@staticmethod
def _weakest_topics(topic_performance: dict[str, dict[str, float]]) -> list[str]:
    scored = [
        (topic, stats.get("average_confidence", 0.0), stats.get("interacted", 0.0))
        for topic, stats in topic_performance.items()
        if stats.get("interacted", 0) > 0        # ← unstarted topics are NOT weak
    ]
    scored.sort(key=lambda row: (row[1], -row[2], row[0]))   # confidence ↑, exposure ↓, name ↑
    return [topic for topic, _, _ in scored]
```

A topic with zero exposure is excluded — it's unstarted, not weak, and curriculum position already
handles it. Sorting by name as the final key keeps the result deterministic.

**Try it:**

```bash
curl -s localhost:8000/api/v1/today/explain -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Read-only — it must **not** create a plan. Verify:

```bash
curl -s localhost:8000/api/v1/daily-plans -H "Authorization: Bearer $TOKEN"
# total should still be 0 if you only called /explain
```

### Persistence: the bug worth understanding

**Read:** `app/services/daily_plan_service.py`, `get_or_create_today`

```python
plan = await self._plan_repo.get_by_date(user_id=user_id, plan_date=today)
if plan is None:
    plan = await self._generate_plan(user_id=user_id, plan_date=today, tz=tz, user_settings=user_settings)
    await self._plan_repo.session.commit()      # ← this line was MISSING
```

Without the commit, the request-scoped session rolls back on close. Every request minted a **new**
plan and `daily_plans` stayed permanently empty.

Why this is instructive: the endpoint *looked* correct. It returned a plausible plan with real
problem ids. Manual testing wouldn't catch it — you'd have to notice the plan_id changing between
two calls. The test that caught it asserts stability **across two requests**:

```python
async def test_today_is_idempotent_within_a_day(client, seeded_catalog):
    first = (await client.get("/api/v1/today")).json()
    second = (await client.get("/api/v1/today")).json()
    assert first["plan_id"] == second["plan_id"]
```

That's the pattern to copy: assert the **property**, not the shape.

### The race

```python
try:
    async with self._plan_repo.session.begin_nested():    # savepoint
        plan = await self._plan_repo.create_plan(...)
except IntegrityError:
    existing = await self._plan_repo.get_by_date(user_id=user_id, plan_date=today)
    if existing is not None:
        return existing      # return theirs rather than a 500
```

Two requests generating the same day's plan: the `UNIQUE (user_id, date_key)` constraint arbitrates.
The **savepoint** is essential — without it, the losing `IntegrityError` would abort the whole
transaction and the follow-up `SELECT` would fail with *"current transaction is aborted"*.

---

## Stage 10 — Migrations (15 min)

**Read:** `alembic/env.py`, then `alembic/versions/0001_existing_schema_adaptation.py`

### The four safeguards

```python
EXCLUDED_SCHEMAS = frozenset({"auth", "storage", "realtime", "extensions", ...})
EXCLUDED_TABLES = frozenset({"spatial_ref_sys", "schema_migrations", "alembic_version", "design_topics"})

# The five adapted tables. Excluded from autogenerate COMPARISON, so it can never propose
# dropping their auth.users FKs or narrowing text -> varchar(n).
AUTOGENERATE_EXCLUDED_TABLES = frozenset({
    "user_problem_progress", "problem_notes", "code_snippets", "daily_plans", "study_sessions",
})
```

**This is the most important file to understand before running `--autogenerate`.** Without
`AUTOGENERATE_EXCLUDED_TABLES`, a routine autogenerate would propose destructive changes to tables
holding user data, because the ORM declares `varchar(300)` where the database has `text`.

### The percent escape

```python
# configparser treats % as an interpolation marker; a URL-encoded password (%40 for @)
# would abort with "invalid interpolation syntax".
config.set_main_option("sqlalchemy.url", settings.migration_database_url.replace("%", "%%"))
```

Without this, migrations cannot run at all against a password containing `%`.

### The guarded pattern

```python
def add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _column_exists(table, column.name):
        op.add_column(table, column)

# Add nullable → backfill → tighten. This three-step sequence is what lets a migration
# run against a table that already contains rows.
add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")
op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))
```

Guards make the migration idempotent and safe against a database that has already drifted.

### Why 0001 can't run offline

```bash
alembic upgrade head --sql     # fails for 0001
# AttributeError: 'NoneType' object has no attribute 'scalar'
```

The migration introspects live state via `op.get_bind()`. That's inherent to a guarded migration —
it must ask the database what exists. Use `--sql` for `0002`, or read `0001` directly.

**Try it (on a scratch database, not production):**

```bash
createdb ir_walkthrough
export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/ir_walkthrough"
export DATABASE_URL_DIRECT="$DATABASE_URL"

# Recreate the pre-existing schema first — migration 0001 ADAPTS it.
psql -d ir_walkthrough -f tests/fixtures/legacy_schema.sql

alembic upgrade head
alembic current
psql -d ir_walkthrough -c "
SELECT conrelid::regclass AS table, confrelid::regclass AS ref
FROM pg_constraint WHERE contype='f' AND confrelid='auth.users'::regclass ORDER BY 1;"
# All six auth.users FKs must still be present.
```

Then confirm zero drift:

```bash
alembic revision --autogenerate -m "drift-check" --rev-id 9999_drift
cat alembic/versions/9999_drift*.py     # upgrade() must be empty
rm alembic/versions/9999_drift*.py
```

---

## Stage 11 — Offline sync (40 min)

**Read:** `app/services/sync_service.py`

The hardest correctness problem. Read the module docstring first — it explains the three
guarantees. Then trace `push`.

### Replay safety

```python
async def push(self, *, user_id, payload: SyncPushRequest) -> SyncPushResponse:
    # One lookup for the whole batch, not one query per mutation.
    already = await self._sync.get_mutations(
        user_id=user_id, mutation_ids=[m.mutation_id for m in payload.mutations]
    )

    for mutation in payload.mutations:
        if mutation.mutation_id in already:
            stored = already[mutation.mutation_id]
            results.append(SyncMutationResult(
                status="skipped_duplicate",
                version=(stored.result or {}).get("version"),   # the ORIGINAL version
                applied=False,
            ))
            continue
```

A replay returns the **stored** result, including the version from the original application. The
client cannot distinguish a replay from the original response — which is exactly right.

### Savepoint per mutation

```python
try:
    async with self._sync.session.begin_nested():
        result = await self._apply_mutation(user_id=user_id, mutation=mutation, device_id=payload.device_id)
        await self._sync.record_mutation(...)     # data + change-log write stay atomic
    results.append(result)
except IntegrityError as exc:
    if _is_unique_violation(exc):
        # The only IntegrityError that means "already applied" is a unique violation on
        # the idempotency ledger — a concurrent request committed the same mutation_id
        # between our lookup and this insert.
        results.append(SyncMutationResult(status="skipped_duplicate", ...))
    else:
        # A NOT NULL / CHECK / FK violation is NOT a duplicate. Reporting it as one
        # claims success while discarding the user's change.
        results.append(SyncMutationResult(status="rejected", error_code="CONSTRAINT_VIOLATION", ...))
```

The `else` branch matters. Treating a NOT NULL violation as a duplicate would silently discard the
user's data while reporting success.

### The cursor

**Read:** `SyncRepository.pull_changes`

```python
changes = await self._sync.pull_changes(user_id=user_id, cursor=cursor, limit=page_size + 1)
has_more = len(changes) > page_size          # one extra row detects "more" without COUNT
page = changes[:page_size]
next_cursor = page[-1].seq if page else cursor
```

`seq` is a `BIGINT GENERATED AS IDENTITY`. A timestamp cursor would break in three ways: same-
millisecond collisions, clock skew, and invisible deletions.

### Conflict detection

```python
@staticmethod
def _conflict_if_stale(*, mutation, current) -> SyncMutationResult | None:
    if mutation.base_version is None:
        return None      # an insert, or a client that doesn't track versions

    if current is None:
        return SyncMutationResult(status="conflict", error_code="RECORD_MISSING", ...)

    if server_version != mutation.base_version:
        return SyncMutationResult(
            status="conflict",
            version=server_version,
            server_record=SyncService._serialise(current),   # ← the client needs this to merge
            error_code="VERSION_CONFLICT",
        )
    return None
```

`server_record` is the whole point. Without it a client can only retry blindly and clobber the
other device's change.

### Why the delete path is soft

```python
"""Deletes are soft everywhere: a hard delete would be invisible to ``/sync/pull``,
leaving the deleted row alive in every other device's local store forever."""
```

**Try it:**

```bash
MUT_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
BODY='{"device_id":"dev-1","device_type":"ios","mutations":[{"mutation_id":"'$MUT_ID'","entity":"problem_progress","operation":"upsert","payload":{"problem_id":"two-sum","status":"solved"}}]}'

curl -s -X POST localhost:8000/api/v1/sync/push -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "$BODY" | python3 -m json.tool
# applied_count: 1

# Replay the SAME mutation_id:
curl -s -X POST localhost:8000/api/v1/sync/push -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "$BODY" | python3 -m json.tool
# duplicate_count: 1, applied_count: 0   ← the guarantee
```

---

## Stage 12 — Statistics and streaks (20 min)

**Read:** `app/services/stats_service.py`, then `app/services/streak_service.py`

### Aggregates in SQL

```python
async def topic_breakdown(self, *, user_id: uuid.UUID) -> TopicStatsResponse:
    rows = await self._stats_repo.topic_totals(user_id=user_id)
    ...
```

Every aggregate is computed in SQL. Pulling history over the wire to sum in Python would not scale,
and the planner calls `topic_performance` on every `/today` request.

### The rollup

```
study_sessions, daily_plan_items, problem_progress, revision_queue
                            ↓ recompute
                  user_activity_days (per local date)
```

```python
async def record(self, *, user_id, activity_count=1, ...) -> None:
    ...
    day.is_active = (
        day.study_minutes >= self._settings.streak_min_minutes
        and day.activity_count >= self._settings.streak_min_activities
    )
```

`is_active` is **recomputed**, not incremented. Deriving is idempotent; incrementing drifts and
double-counts on replay.

### Streaks

```python
ordered = sorted(active_dates)
longest = 1
run = 1
for previous, current in pairwise(ordered):
    if current - previous == timedelta(days=1):
        run += 1
        longest = max(longest, run)
    else:
        run = 1
```

Two rules worth knowing:

1. **"Yesterday still counts."** The current streak isn't broken until a full day is missed.
2. **Only meaningful events count.** A favourite toggle or a confidence tweak must not extend a
   streak, or the metric is meaningless. See the guard:

```python
# Record the meaningful event for streaks. Not "any write".
if values.get("status") is not None and values["status"] != ProblemStatus.NOT_STARTED.value:
    await self._activity.record(...)
```

### Timezones

Activity dates are **local**, not UTC. A user studying at 23:30 in Kolkata is on the same calendar
day; in UTC they'd be on the next one. The timezone comes from `X-Timezone`, then the user's
setting, then the default.

**Try it:**

```bash
curl -s "localhost:8000/api/v1/stats/activity?range=7d" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['items']), 'points'); print(d['items'][0])"
# 7 points, zero-filled (each with activity_count etc.)
```

Zero-filling matters: a gap must render as an explicit `0`, or charts silently mis-scale.

---

## Stage 13 — Authentication deep dive (25 min)

**Read:** `app/core/jwks.py`, then `app/core/security.py`

### Why not `PyJWKClient`

```python
"""PyJWT's ``PyJWKClient`` uses ``urllib``, which on macOS fails with
``SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``
because the system certificate store is incomplete. ``httpx`` works because it
bundles ``certifi``. This module therefore speaks JWKS over httpx...
"""
```

This was found by testing against the **real** Supabase project. A mocked JWKS would never have
surfaced it — a good argument for testing against reality at least once.

### The cache and its policies

```python
async def _get_jwk_set(self, *, force_refresh=False) -> PyJWKSet:
    if not force_refresh and self._cache is not None and self._cache.is_fresh(self._ttl):
        return self._cache.jwk_set

    # Short-circuit during an outage so a broken auth server doesn't make every
    # authenticated request wait for a timeout.
    if (self._last_failure_at and (time.monotonic() - self._last_failure_at) < NEGATIVE_CACHE_SECONDS
            and self._cache is None):
        raise jwt.exceptions.PyJWKClientConnectionError("...")

    async with self._lock:                 # concurrent burst -> one refetch
        if self._cache is not None and self._cache.is_fresh(self._ttl):
            return self._cache.jwk_set
        try:
            data = await self._fetch()
        except Exception as exc:
            self._last_failure_at = time.monotonic()
            self._consecutive_failures += 1
            if self._cache is not None:
                # Serve the stale set: a rotated key we already hold is still valid,
                # and rejecting every request during a brief blip is far worse.
                return self._cache.jwk_set
            raise PyJWKClientConnectionError(...) from exc
```

Four policies, each for a specific failure mode: TTL cache, negative cache, lock, stale-serve.

### Algorithm confusion defence

```python
# app/core/jwks.py
#: Algorithms accepted from a token header. HS* is deliberately absent.
_ALLOWED_ALGORITHMS = frozenset(
    {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}
)
```

`HS*` is **absent**. Without this, an attacker could sign a token with the public key as an HMAC
secret and have it accepted — the classic algorithm-confusion attack.

The client rejects a disallowed algorithm at the token-header stage, before any key lookup:

```python
if algorithm is not None and algorithm not in _ALLOWED_ALGORITHMS:
    raise jwt.exceptions.PyJWKClientError(f"Unsupported token signing algorithm: {algorithm}")
```

### Verification

```python
# app/core/security.py
ALLOWED_ALGORITHMS = ("ES256", "RS256", "ES384", "RS384", "ES512", "RS512")
REQUIRED_CLAIMS = ("exp", "sub", "iss")

signing_key = await self._resolve_signing_key(token)
claims = jwt.decode(
    token, signing_key.key,
    algorithms=list(ALLOWED_ALGORITHMS),
    audience=self._settings.supabase_jwt_audience or None,
    issuer=self._settings.jwt_issuer or None,
    options={"require": list(REQUIRED_CLAIMS), "verify_exp": True, "verify_aud": True, "verify_iss": True},
    leeway=10,
)
```

`sub` is in `REQUIRED_CLAIMS` because it becomes the user id used in every query. The `leeway=10`
tolerates minor clock skew between a client device and the server.

### Read the tests

**Read:** `tests/test_auth.py`

This is the module that matters most for security, because route tests override
`get_current_user` and therefore bypass verification entirely. Here, verification is tested
**directly** with locally generated EC keys — real crypto, no network:

- valid token accepted
- wrong-key token rejected
- **HS256 rejected** (algorithm confusion)
- **`alg=none` rejected**
- expired rejected
- wrong issuer rejected
- wrong audience rejected
- anon role rejected
- missing / non-UUID subject rejected
- malformed tokens rejected
- JWKS outage fails closed

**Try it:**

```bash
# Forge an HS256 token and confirm it is rejected.
python - <<'PY'
import jwt, time
token = jwt.encode(
    {"sub": "00000000-0000-0000-0000-000000000000", "aud": "authenticated",
     "iss": "https://<ref>.supabase.co/auth/v1", "exp": int(time.time()) + 3600},
    "attacker-secret", algorithm="HS256",
)
print(token)
PY
# Paste it into Swagger's Authorize box -> expect 401, not 200.
```

---

## Stage 14 — The AI tutor (20 min)

**Read:** `app/services/ai/provider.py`, then `stub.py`, then `prompts.py`, then `ai_tutor_service.py`

### The Protocol

```python
@runtime_checkable
class AIProvider(Protocol):
    name: str
    async def chat(self, *, messages: list[ChatMessage], system: str, **kwargs) -> ChatResult: ...
```

Three implementations: `gemini` (httpx REST), `groq` (httpx REST), `stub` (deterministic, offline).

### Why the stub is not just for tests

It makes local development possible with no API key and no network, and it makes the test suite
deterministic. Tests assert the **contract** — that context is assembled from the user's own data,
that limits are enforced, that conversations persist — without depending on any model's output.

### Grounding

```python
@dataclass
class TutorContext:
    context_type: str
    entity: dict | None = None
    notes: dict | None = None
    progress: dict | None = None
    code: str | None = None
    history: list[dict] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """What was actually sent — surfaced in the response for debuggability."""
```

`select_entity_fields` and `select_note_fields` restrict which fields go into the prompt, so a
request never sends more of the user's data than the task needs. `context_used` in the response
reports what was included, which makes "why did it answer that?" answerable.

### Rate limiting

```python
class AIRateLimitCounter(Base):
    __tablename__ = "ai_rate_limits"
    user_id: Mapped[uuid.UUID] = mapped_column(..., primary_key=True)
    window_start: Mapped[datetime] = mapped_column(..., primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
```

A **composite primary key** `(user_id, window_start)` makes the counter naturally per-user and
per-window, with an UPSERT incrementing it. No Redis needed.

**Try it:**

```bash
# With AI_PROVIDER=stub so no API key is needed.
for i in $(seq 1 5); do
  curl -s -o /dev/null -w "%{http_code} " -X POST localhost:8000/api/v1/ai/chat \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"message":"hint for two sum","action":"give_hint"}'
done; echo
```

---

## Stage 15 — The test suite (30 min)

**Read:** `tests/conftest.py`

Everything else in `tests/` is straightforward once you understand this file.

### Skip, don't fail

```python
def pytest_collection_modifyitems(config, items):
    if _test_database_url():
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)
```

`pytest` must work on a machine with no database. Without this you'd get collection errors.

### Real migrations

```python
async def prepare():
    await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
    await conn.execute("DROP SCHEMA IF EXISTS auth CASCADE")
    await conn.execute("CREATE SCHEMA public")
    legacy = (BACKEND_ROOT / "tests" / "fixtures" / "legacy_schema.sql").read_text()
    await conn.execute(legacy)
```

Order is essential: the pre-existing tables must exist **before** Alembic, because `0001` adapts
them and `0002` references them. Using the real migration chain (not `create_all`) means a broken
migration fails the suite — which is the point.

### Rollback isolation

```python
async def commit_without_ending_transaction() -> None:
    await session.flush()          # NOT commit
session.commit = commit_without_ending_transaction
```

Services call `commit()`. Since the session joins an outer transaction that is rolled back, tests
are order-independent. The `commit` → `flush` substitution is what makes that possible.

### The identity-map reset

```python
async def reset_session_identity_map(session: AsyncSession) -> None:
    await session.flush()
    session.expunge_all()
```

Registered as a request event-hook in each client fixture:

```python
async def _reset(_request: httpx.Request) -> None:
    await reset_session_identity_map(db_session)

transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
async with httpx.AsyncClient(transport=transport, base_url="http://test",
                             event_hooks={"request": [_reset]}) as http:
    yield http
```

Production gives every request its own session; the suite shares one so the work can be rolled
back. Without the reset, a later request reads an object cached by an earlier one, which made
conflict detection look broken when it worked correctly.

`expunge_all`, **not** `expire_all` — expiring triggers lazy IO outside the greenlet and raises
`MissingGreenlet`.

### Two settings that are both required

```toml
asyncio_default_fixture_loop_scope = "session"
asyncio_default_test_loop_scope = "session"
```

Plus `NullPool` on the test engine. An async engine is bound to the event loop that created it, so
a session-scoped engine used from per-test loops raises *"attached to a different loop"*.

### Real config, no leakage

```python
def settings(database_url, apply_migrations):
    os.environ["SUPABASE_URL"] = TEST_SUPABASE_URL     # assigned, NOT setdefault
    ...
    return Settings(DATABASE_URL=database_url, SUPABASE_URL=TEST_SUPABASE_URL, ...)
```

Assignment, not `setdefault`, because a shell that has sourced the real `.env` has already exported
the real `SUPABASE_URL` — which silently made the auth tests validate the wrong issuer.

### Run it

```bash
export TEST_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/interviewready_test"

pytest -q                                   # 285 passed
pytest tests/test_units.py -q               # no DB needed
pytest -q -p no:cacheprovider               # if caching gets in the way

# Watch a specific guarantee
pytest tests/test_sync.py -q -k "idempotency or conflict"
pytest tests/test_today.py -q -k "idempotent"
```

**Exercise:** break something deliberately and watch the suite catch it. For example, change
`_jitter` to use `random.random()` — `test_jitter_is_deterministic` fails immediately.

---

## Stage 16 — Scripts and operations (20 min)

**Read:** `scripts/seed_curriculum.py`, then `backfill_design_topics.py`, then `backup_public_schema.py`

### Seeding

```python
async def seed_dsa(*, dry_run, prune, stats):
    local = SeedStats()          # per-catalog counters
    ...
    stats.merge(local)
```

Per-catalog counters exist because the shared accumulator made the output misleading —
`[hld] inserted=130` was reporting a running total across all three catalogs.

Idempotency is by **slug**, so a reseed updates rather than duplicates:

```bash
python -m scripts.seed_curriculum --dry-run     # preview
python -m scripts.seed_curriculum               # inserted=130
python -m scripts.seed_curriculum               # inserted=0 unchanged=130   ← proof
```

### The backfill's restraint

```python
"""Never pollutes the shared curriculum. ``lld_topics``/``hld_topics`` are global catalogs
read by every user, so this script never inserts into them. A legacy row that matches no
seeded topic is *skipped and reported*, never force-fitted and never silently dropped."""
```

An early version created private `user-<id>-...` topics — which would have injected one user's
data into a catalog every user reads. Worth internalising: **when data is shared, a migration
must not invent rows.**

Matching is exact-slug first, then a fuzzy token overlap requiring ≥0.6 similarity:

```bash
python -m scripts.backfill_design_topics --dry-run
#   [dry-run] ... | hld | 'URL Shortener' -> 'design-url-shortener' (fuzzy title match)
#   [dry-run] ... | lld | 'Parking Lot'    -> 'parking-lot' (exact slug match)
```

### The backup script

```python
"""``pg_dump`` refuses to run against a *newer* server than itself: dumping a PostgreSQL 17
Supabase instance with the PostgreSQL 16 client fails with "aborting because of server
version mismatch". This script produces a portable SQL backup using only asyncpg.
"""
```

Two traps it handles:

1. **UNIQUE constraints already produce a backing index**, so naively emitting `pg_indexes`
   entries caused *"relation already exists"* on restore. Indexes backed by a constraint are
   filtered out.
2. **One central quoting function**, so a value containing a quote cannot break the statement.

**Always verify a backup by restoring it.** An unverified backup is not a backup:

```bash
python -m scripts.backup_public_schema --output /tmp/backup.sql
createdb ir_restore_check
psql -v ON_ERROR_STOP=1 -d ir_restore_check -f /tmp/backup.sql    # must be zero errors
```

`ON_ERROR_STOP=1` is essential — without it `psql` continues past errors and "succeeds" on a
partial restore.

### The inspector

```bash
python -m scripts.inspect_supabase_schema
```

Read-only drift report vs the ORM. It once reported **24 false mismatches** because it compared
type names as raw strings (`JSONB` vs `jsonb`). It now canonicalises spellings, compares widths
when both sides declare one, and reports the 9 genuine narrower-declaration cases with an
explanation rather than as drift.

---

## Stage 17 — Putting it together (30 min)

An end-to-end exercise that touches every layer.

### 1. Register a device

```bash
curl -s -X PUT localhost:8000/api/v1/settings/devices -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"device_identifier":"walkthrough-1","device_type":"ios","display_name":"Walkthrough"}'
```

### 2. Set preferences, then observe them change your plan

```bash
curl -s -X PUT localhost:8000/api/v1/settings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"daily_dsa_count": 2}'

curl -s localhost:8000/api/v1/today -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('dsa items:', d['dsa']['total'])"

# Now raise it
curl -s -X PUT localhost:8000/api/v1/settings -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"daily_dsa_count": 5}'
curl -s -X DELETE "localhost:8000/api/v1/daily-plans/$(date +%F)" -H "Authorization: Bearer $TOKEN" >/dev/null
curl -s localhost:8000/api/v1/today -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('dsa items:', d['dsa']['total'])"
```

This exercises config → service → scheduler → repository, and the plan-size clamping.

### 3. Solve a problem and watch the revision appear

```bash
curl -s -X PUT localhost:8000/api/v1/dsa/problems/two-sum/progress \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"solved","confidence":2}' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('status   :', d['status'])
print('version  :', d['version'])
print('next due :', d['next_revision_at'])"

curl -s localhost:8000/api/v1/revisions -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; print('queued revisions:', json.load(sys.stdin)['total'])"
```

Confidence 2 is at or below `revision_low_confidence_threshold`, so the scheduled reason should be
`low_confidence` rather than `scheduled_revision`.

### 4. Complete it and advance the ladder

```bash
REV=$(curl -s localhost:8000/api/v1/revisions -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['items'][0]['id'])")

curl -s -X POST "localhost:8000/api/v1/revisions/$REV/complete" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"result":"success","confidence":4}' | python3 -m json.tool
```

Then **run it again with the same id** — it must be idempotent and must not advance the ladder a
second time.

### 5. Verify the streak

```bash
curl -s localhost:8000/api/v1/stats/streak -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# current: 1, today_active: true
```

### 6. Export everything

```bash
curl -s localhost:8000/api/v1/export -H "Authorization: Bearer $TOKEN" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
for k in sorted(d): print(f'  {k:22} {len(d[k]) if isinstance(d[k], list) else d[k] if not isinstance(d[k], dict) else \"{...}\"}')"
```

### 7. Prove isolation

Create a second user in Supabase, get a token for them, and confirm every one of those calls
returns empty. That is the property the whole authorisation model rests on.

---

## The ten things to remember

1. **The catalog's primary key is the slug**, because the pre-existing columns are
   `problem_id text`. Schemas for it extend `CatalogModel`, not `TimestampedModel`.
2. **There is no foreign key from the user tables to the catalog.** Referential integrity is
   application-enforced; every new write path must validate the problem exists.
3. **`AUTOGENERATE_EXCLUDED_TABLES` is load-bearing.** Removing it lets a routine autogenerate
   propose destructive changes to tables holding user data.
4. **A NOT NULL column with no default breaks every partial upsert**, because PostgreSQL validates
   the proposed insert row before detecting the conflict. Defaults must be injected for the insert
   path **only** — never into `DO UPDATE`.
5. **Determinism comes from hashing, not `random`**, so every worker computes the same plan.
6. **`GET /today` must commit.** Without it, every request mints a new plan.
7. **The sync cursor is an identity column, not a timestamp**, and deletes are soft so other
   devices learn about them.
8. **The column naming differs between tables** (`*_date` on the legacy table, `*_at` on LLD/HLD).
   The API normalises to `*_at`.
9. **`%` in the database password must stay URL-encoded** — `alembic/env.py` escapes it for
   `configparser`. Removing that breaks all migrations.
10. **Verify a backup by restoring it.** An unverified backup is not a backup.

---

## Where to go next

| If you want to… | Read |
|---|---|
| Understand a design choice | `ARCHITECTURE.md` — each decision has its rationale |
| See the setup and endpoint list | `README.md` |
| Understand the schema adaptation | `docs/SCHEMA_MAPPING.md` |
| Work on offline sync | `app/services/sync_service.py` + Stage 11 here |
| Work on the scheduler | `app/services/daily_plan_scheduler.py` + Stage 9 here |
| Add a table or endpoint | `ARCHITECTURE.md` § 20 Extension guide |
| Fix a first-run failure | Stage 0 here |

### Exercises that build real understanding

1. **Break determinism on purpose.** Change `_jitter` to `random.random()` and watch
   `test_jitter_is_deterministic` fail. Revert.
2. **Remove the upsert's `injected` exclusion** and write a test that syncs only `confidence` after
   solving. Watch `status` reset to `not_started`. This is the silent-data-loss bug — worth seeing.
3. **Remove the commit in `get_or_create_today`** and run
   `pytest tests/test_today.py -k idempotent`. Watch it fail.
4. **Add a new sync entity** end to end (Stage 15 in `ARCHITECTURE.md` § 20), including a delete
   handler and a coverage test.
5. **Generate a drift revision** and confirm `upgrade()` is empty. Then temporarily remove
   `code_snippets` from `AUTOGENERATE_EXCLUDED_TABLES` and see what autogenerate proposes — this is
   exactly the destructive change the safeguard prevents.
