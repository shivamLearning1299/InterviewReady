# InterviewReady — Summary of Work

A complete backend API for an interview-preparation platform: **DSA**, **Low-Level Design**,
**High-Level Design**, spaced-repetition revision tracking, progress analytics, offline device
synchronisation, and an AI tutor.

**The defining constraint:** this was not built against an empty database. Six tables and real
user data already existed in Supabase. The schema was **adapted and reused**, never replaced —
no user data was migrated, rewritten, or lost.

---

## Deliverables at a glance

| Deliverable | Result |
|---|---|
| Runtime | Python 3.12, FastAPI, SQLAlchemy 2.0 async, asyncpg |
| Endpoints | **69** operations, all documented in OpenAPI |
| Database | **26** tables (6 pre-existing + 20 added), 24 mapped in the ORM |
| Migrations | **3**, all additive, guarded, and reversible |
| Code | ~16,800 lines (`app/`), across 9 model modules, 11 repositories, 10 schema modules, 13 services (+6 in `services/ai/`), 11 routers |
| Tests | **285** passing across 10 modules (~3,000 lines) |
| Lint | Clean across `app/`, `scripts/`, `alembic/`, `tests/` |
| Docs | `README.md`, `ARCHITECTURE.md`, `WALKTHROUGH.md`, `docs/SCHEMA_MAPPING.md` |
| Deploy | `Dockerfile` (multi-stage, non-root), `render.yaml`, `.dockerignore` |
| Live state | revision `0003`, zero schema drift, 90 DSA + 20 LLD + 20 HLD seeded |

---

## What was built, layer by layer

### Foundation

- **Configuration** — `pydantic-settings` with a cached singleton. Normalises Supabase's
  `postgresql://` into `postgresql+asyncpg://`, derives the JWKS URL and expected issuer from
  `SUPABASE_URL`, and makes every tunable (plan size, revision ladder, rate limit) configuration
  rather than code.
- **Logging** — JSON and console formatters, request-id and user-id contextvars, and a redaction
  filter so tokens and passwords can never reach the log.
- **Errors** — an `AppError` hierarchy mapping to HTTP status codes, plus handler-level
  translation of `IntegrityError` constraint names into specific API codes.
- **Database session** — async engine with `statement_cache_size=0` for pooler compatibility,
  a request-scoped dependency that rolls back on failure, and a helper that publishes
  `app.current_user_id` for RLS.

### Authentication

`SupabaseTokenVerifier` validates Supabase access tokens against the project's JWKS.

**A macOS-specific problem drove a non-obvious design decision.** PyJWT's built-in
`PyJWKClient` uses `urllib`, which fails with `CERTIFICATE_VERIFY_FAILED` on macOS because the
system certificate store is incomplete. `httpx` works, because it bundles `certifi`. So
`app/core/jwks.py` implements a JWKS client over httpx, with a TTL cache, refetch-on-unknown-key,
stale-serve during an outage, and an explicit rejection of all `HS*` algorithms.

### Data layer

- **24 tables** mapped across 9 modules. Catalog tables use **text primary keys (slugs)** so the
  pre-existing `problem_id text` columns join directly — no user data rewrite.
- **The five adapted tables are treated as read-only by autogenerate.** This is what stops a
  later `alembic revision --autogenerate` from proposing to drop the `auth.users` foreign keys
  or narrow `text` back to `varchar(n)`.
- Every relationship onto a reused table is `viewonly=True` with an explicit `primaryjoin`,
  because there are no foreign keys pointing at `dsa_problems` (existing rows may predate the
  catalog).
- **Idempotent writes by construction.** A shared upsert helper builds
  `INSERT ... ON CONFLICT DO UPDATE`, bumps `version`, refreshes `updated_at`, fills in NOT NULL
  defaults the payload omitted, and guarantees the returned object reflects the write.

### Domain logic

| Service | Responsibility |
|---|---|
| `RevisionPolicy` | The spaced-repetition ladder, as configuration. Indexes into a per-confidence ladder and clamps at the top. |
| `DailyPlanScheduler` | Scores the whole catalog and picks a plan. Deterministic — see below. |
| `DailyPlanService` | Generate-once-per-day with savepoint-protected concurrency handling. |
| `RevisionService` | Records outcomes, advances the ladder, promotes stale problems. |
| `StreakService` | Current and longest streaks, with the "yesterday still counts" rule. |
| `SyncService` | 10 entity handlers, mutation ledger, optimistic concurrency, server-authoritative cursor. |
| `StatsService` | All aggregates computed in SQL, not in Python. |
| `AITutorService` | Context assembly from the user's own data, provider abstraction, per-user rate limiting. |

### API surface

11 routers, one per feature, with services injected via a per-request container. Routers parse and
shape; they contain no business logic. Every personal endpoint gets the user id from the verified
token — never from a path, query or body.

---

## The three design decisions that matter most

### 1. Reuse the existing schema; never rewrite user data

The catalog's primary key is the problem **slug**, matching the pre-existing
`problem_id text` columns. The alternative — introducing UUID keys and backfilling — would have
meant rewriting every user's rows. Instead, six tables were extended with additive columns and
backfilled in place.

Result: **6/6 `auth.users` foreign keys intact, 0 columns lost, all row counts unchanged, zero
drift.**

### 2. Idempotency as a database guarantee, not application best-effort

The iOS client replays queued offline mutations after a crash, a retry, or a network blip.
Handling that in application code is where data gets duplicated or lost. Instead:

- every mutation carries a client-generated `mutation_id`, recorded in `sync_mutations` with a
  unique constraint on `(user_id, mutation_id)` — a replay returns the **stored** result;
- the pull cursor is a `bigint` **identity column**, not a timestamp, so two changes in the same
  millisecond still get distinct, ordered cursor values and deletions are representable;
- conflicts are detected by comparing `base_version` and return the **server's** current record so
  the client can merge rather than blindly retry.

### 3. Determinism instead of randomness

`GET /today` must return the same plan all day, across processes, workers and retries. So the
tie-break is not `random` — it is a BLAKE2b digest of `(user_id, plan_date, problem_id)`:

```python
digest = hashlib.blake2b(f"{user_id}:{plan_date}:{problem_id}".encode(), digest_size=8).digest()
return int.from_bytes(digest, "big") % 300 / 100.0   # stable nudge in [0, 3)
```

Same inputs ⇒ same plan on every worker, forever. The plan is then committed, so a refresh
returns the stored plan rather than regenerating it.

---

## Verification

### Live Supabase project

```
revision                : 0003_progress_status_default
public tables           : 26  (6 → 26)
legacy rows             : preserved (two-sum progress intact)
legacy auth.users FKs   : 6 / 6
alembic drift           : zero
seeded                  : 90 DSA / 16 topics / 20 LLD / 20 HLD
```

Before applying migrations I took a **verified** backup: `scripts/backup_public_schema.py` dumps
the `public` schema and I proved it restorable by restoring into a scratch database with
`ON_ERROR_STOP=1` — zero errors, all 6 tables, the data row, and all 6 foreign keys intact.

That script exists because `pg_dump` **refuses to dump a newer server than itself**, so the
PostgreSQL 16 client on this machine cannot dump the PostgreSQL 17 Supabase instance.

### Server smoke test

```
/health          200  {"status":"ok"}
/health/ready    200  database:true  auth:true
/docs            200  Swagger UI
/redoc           200
/openapi.json    200  69 endpoints, SupabaseBearer scheme
```

Seven probed endpoints (`/me`, `/today`, `/settings`, `/export`, `/lld`, `/sync/status`,
`/stats/overview`) all correctly returned **401** without a token.

---

## Bugs found and fixed

The test suite was worth writing: it caught **16 real defects**, and most were invisible in
manual testing against the live database.

### Blocking (every call to the endpoint failed)

| # | Bug | Impact |
|---|---|---|
| 1 | `DSAProblemSummary` inherited a `UUID` id, but the catalog's key is the **slug** | `GET /dsa/problems` returned **500 on every call** |
| 2 | Same mistake on `CodeSnippetResponse.context_id` | Every code-snippet response **500** |
| 3 | ON clause referenced `lld_progress` while FROM used the alias `lld_progress_1` | **All LLD and HLD listing** failed |
| 4 | Three repositories computed `total` then returned only the rows | **Every paginated endpoint** crashed with `ValueError` |
| 5 | `GET /today` created the plan but never committed | A **new plan on every request**; `daily_plans` stayed empty |
| 6 | `GET /today` fetched user settings, then passed `None` | The user's **`daily_dsa_count` was silently ignored** |

Bug 5 is the one to remember: the endpoint looked correct in isolation and returned plausible
data. Only asserting *stability across two requests* exposed it.

### Data integrity

| # | Bug | Impact |
|---|---|---|
| 7 | `status` was the only NOT NULL column with no default | **Every partial UPSERT failed** — PostgreSQL validates NOT NULL on the proposed insert row *before* detecting the conflict |
| 8 | Revision completion wrote a progress row without `status` | A plain successful review returned **409** |
| 9 | `revision_due` filter and `promote-stale` used `next_revision_at` | The column is `next_revision_date`; both paths were broken |
| 10 | Topic progress wrote `last_reviewed_date` | LLD/HLD use `last_reviewed_at` — both **500** |
| 11 | Alembic passed the URL through `configparser` unescaped | A `%` in the password (`%40`) aborted with *"invalid interpolation syntax"* — **migrations could not run at all** |

Bug 7 had the widest blast radius: it silently broke the sync protocol, because an offline client
that pushes only a changed field is exactly the partial-payload case. It needed a three-part fix —
a migration adding the default, the model mirroring it, and the upsert helper injecting defaults
**for the insert path only** (writing them into `DO UPDATE` would have reset stored values).

### Correctness and robustness

| # | Bug | Impact |
|---|---|---|
| 12 | `ruff --fix` removed an import that was still used | Latent `NameError` in the notes path |
| 13 | Constraint violations logged the driver message via `extra={...}` | Console formatter dropped it — violations logged as a bare *"Integrity error"* with no detail |
| 14 | Upserts didn't refresh the returned ORM object | A stale `version` could break optimistic concurrency |
| 15 | `reconcile`-style upsert missing `populate_existing` | Same class of staleness |
| 16 | Schema inspector compared type names as raw strings | **24 false "mismatches"** (`JSONB` vs `jsonb`) |

### Three apparent bugs that were my own test harness

Worth recording, because chasing them cost more time than the real bugs:

1. **Cross-event-loop connections** — the session-scoped engine was used from per-test loops.
   Needed `NullPool` *and* `asyncio_default_test_loop_scope = "session"`.
2. **Ambient environment leakage** — a shell that had sourced the real `.env` exported the real
   `SUPABASE_URL`, so `setdefault` didn't override it and the auth tests validated the wrong
   issuer.
3. **A shared session identity map** — production gives every HTTP request its own session; the
   suite shared one so the work could be rolled back. A later request then read an object cached
   by an earlier one, making conflict detection look broken when it worked. Fixed by resetting the
   identity map per request in the client fixtures.

Each was fixed in the harness rather than worked around, because a test that doesn't model
production semantics will hide the next real bug too.

---

## Repositories: how the database was protected

Three independent safeguards, each catching a different failure mode:

| Safeguard | Prevents |
|---|---|
| `process_revision_directives` | Autogenerate emitting `DROP TABLE` / `DROP COLUMN` unless `ALLOW_DESTRUCTIVE_MIGRATIONS=1` |
| `EXCLUDED_SCHEMAS` | Touching `auth`, `storage`, `extensions`, `realtime`, … |
| `AUTOGENERATE_EXCLUDED_TABLES` | Proposing to drop `auth.users` FKs or narrow `text` → `varchar(n)` on the five adapted tables |
| Verified backup before every migration | Anything the above miss |

---

## Known limitations

Documented rather than hidden:

1. **`db.<ref>.supabase.co` is IPv6-only** — no A record, so IPv4-only hosts (some CI, Render's
   default networking) cannot resolve it. Use the session pooler for `DATABASE_URL` there.
2. **`promote-stale` is request-triggered, not scheduled** — exposed as an endpoint so it needs no
   scheduler; a nightly `pg_cron` call is the natural next step.
3. **Rate limiting lives in Postgres** — correct and infrastructure-free; Redis would be cheaper at
   very high volume.
4. **Search is `ILIKE`, not `tsvector`** — fine for a few hundred problems.
5. **`design_topics` is retained but unread** — kept so no data is destroyed, with a script to copy
   it across on demand.
6. **Models declare narrower types than the legacy `text` columns** (e.g. `VARCHAR(300)` vs `text`).
   Harmless — narrower declarations are never emitted — and the inspector now reports the 9
   genuine cases honestly instead of as drift.
7. **RLS is enabled but unpolicied** on some tables. Inert, because the app connects as a
   privileged role. `scripts/sql/rls_hardening.sql` provides the least-privilege alternative.
8. **No copyrighted content** — the catalog stores metadata only (titles, slugs, topics, patterns,
   external links).

---

## Repository layout

```
InterviewReady/
├── backend/           ← this deliverable
│   ├── app/
│   ├── alembic/versions/
│   ├── scripts/
│   ├── tests/
│   ├── docs/
│   ├── README.md          setup, API reference, deploy
│   ├── ARCHITECTURE.md    design and data model
│   ├── WALKTHROUGH.md     guided code tour
│   ├── Dockerfile
│   └── render.yaml
└── frontend/          ← separate pre-existing React app
```

`frontend/` is a separate Vite + React + TanStack Query + Radix + Monaco application with its own
feature folders (`dsa`, `lld`, `hld`, `revision`, `today`, `stats`, `ai`, `settings`), an API layer
under `src/api/endpoints/`, and a mock layer under `src/mocks/`. It was not part of this work and
is not covered by the backend test suite.

---

## How to start

```bash
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # fill in DATABASE_URL, DATABASE_URL_DIRECT, SUPABASE_URL
alembic upgrade head
python -m scripts.seed_curriculum
uvicorn app.main:app --reload
```

Then <http://localhost:8000/docs>. For a guided tour of the code, read `WALKTHROUGH.md` next.
