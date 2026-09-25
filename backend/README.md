# InterviewReady — Backend API

A FastAPI backend for an interview-preparation platform covering **DSA**, **Low-Level Design**,
**High-Level Design**, spaced-repetition revision tracking, progress analytics, offline device
synchronisation, and an AI tutor.

Built on an **existing Supabase database**: the six pre-existing tables and all user data were
preserved, and the ORM was mapped onto them rather than replacing them. See
[Existing schema](#existing-schema-and-what-was-added).

---

## Contents

1. [Quick start](#quick-start)
2. [Folder structure](#folder-structure)
3. [Architecture](#architecture)
4. [API routes](#api-routes)
5. [Database tables](#database-tables)
6. [Migrations](#migrations)
7. [Supabase modifications required](#supabase-modifications-required)
8. [Environment variables](#environment-variables)
9. [Running the app](#running-the-app)
10. [Tests](#tests)
11. [Swagger / OpenAPI](#swagger--openapi)
12. [Seeding and other scripts](#seeding-and-other-scripts)
13. [Deployment (Render)](#deployment-render)
14. [Known TODOs](#known-todos)

---

## Quick start

```bash
cd backend

# 1. Python 3.12 (3.13+ is not supported by the pinned dependency set)
uv venv --python 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. Configure
cp .env.example .env
#    then fill in DATABASE_URL, DATABASE_URL_DIRECT and SUPABASE_URL

# 3. Create the schema
alembic upgrade head

# 4. Load the curriculum (idempotent)
python -m scripts.seed_curriculum

# 5. Run
uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Swagger UI: <http://localhost:8000/docs>
- Readiness: <http://localhost:8000/health/ready>

---

## Folder structure

```
backend/
├── alembic/
│   ├── env.py                     # async migration env; excludes Supabase-owned schemas
│   └── versions/
│       ├── 0001_existing_schema_adaptation.py   # additive baseline over the existing tables
│       ├── 0002_new_tables_...py                # 19 new tables
│       └── 0003_progress_status_default.py      # NOT NULL default for a partial upsert
├── app/
│   ├── api/
│   │   ├── deps.py                # auth, pagination, device-id dependencies
│   │   ├── error_handlers.py      # one error envelope for every failure mode
│   │   ├── middleware.py          # request-id, access logs, security headers
│   │   └── v1/                    # 15 route modules + service wiring
│   ├── core/
│   │   ├── config.py              # pydantic-settings; all tunables
│   │   ├── constants.py           # the enums shared by API and DB CHECK constraints
│   │   ├── exceptions.py          # AppError hierarchy -> HTTP status mapping
│   │   ├── jwks.py                # httpx JWKS client (see macOS TLS note)
│   │   ├── logging.py             # JSON/console logs, redaction, request correlation
│   │   └── security.py            # Supabase JWT verification
│   ├── db/
│   │   ├── base.py                # DeclarativeBase, naming convention, mixins
│   │   ├── session.py             # async engine, session factory, RLS GUC
│   │   └── models/                # 10 modules, 24 mapped tables
│   ├── repositories/              # 12 modules — the only place raw queries live
│   ├── schemas/                   # 11 modules — request/response contracts
│   ├── services/                  # 14 modules — all business logic
│   │   └── ai/                    # provider protocol + gemini / groq / stub
│   ├── utils/                     # upsert helper, pagination, datetimes
│   ├── seed_data/                 # dsa_problems.json, lld_topics.json, hld_topics.json
│   └── main.py                    # app factory, lifespan, health, middleware
├── docs/
│   ├── SCHEMA_MAPPING.md          # how the ORM maps onto the existing tables
│   └── existing_supabase_schema.sql
├── scripts/
│   ├── backup_public_schema.py    # version-agnostic logical backup
│   ├── backfill_design_topics.py  # one-way, idempotent legacy migration
│   ├── inspect_supabase_schema.py # read-only introspection / drift report
│   ├── seed_curriculum.py         # idempotent curriculum upserts
│   ├── validate_models.py         # compiles every table and mapper
│   └── sql/rls_hardening.sql      # optional NOBYPASSRLS app role
├── tests/                         # 282 tests, 10 modules
│   └── fixtures/legacy_schema.sql # recreates the pre-existing tables for tests
├── Dockerfile
├── render.yaml
├── alembic.ini
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── .env.example
```

---

## Architecture

```
Router  →  Service  →  Repository  →  Database
```

- **Routers** (`app/api/v1/`) only parse/validate input and shape responses. No business logic.
- **Services** (`app/services/`) own all decisions and are the only layer that commits.
- **Repositories** (`app/repositories/`) are the only layer that writes SQL.
- **Models** (`app/db/models/`) are the schema of record.

Cross-cutting rules:

- **The user id always comes from a verified JWT.** No endpoint accepts a `user_id` in a path,
  query string or body. Every personal query filters on `user_id`.
- **Writes are idempotent by design.** The iOS client replays queued offline mutations, so every
  user-facing write is an `INSERT ... ON CONFLICT DO UPDATE` with a monotonic `version`.
- **Timestamps are derived server-side**, never trusted from the client.
- **One error envelope**: `{"error": {"code", "message", "details"}}` for every failure.
- **No infra dependencies** beyond PostgreSQL. No Redis, Celery, Kafka or Kubernetes —
  correctness is obtained from the database (unique constraints, an identity-column cursor,
  a persisted rate-limit counter) rather than from extra moving parts.

---

## API routes

All endpoints are prefixed `/api/v1`. **69 operations total.**

Every route below requires `Authorization: Bearer <supabase-access-token>`.

### Account

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/me` | The authenticated identity |
| `GET` | `/export` | Full data export (GDPR-style backup) |
| `GET` `PUT` | `/settings` | Daily counts, timezone, theme, AI preferences |
| `GET` `PUT` | `/settings/devices` | Register/list sync devices |

### DSA

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/dsa/problems` | Paged catalog merged with the caller's progress |
| `GET` | `/dsa/problems/{problem_id}` | Detail + notes + code + attempts + revisions |
| `GET` | `/dsa/topics` | Curriculum topics |
| `GET` | `/dsa/filters` | Distinct patterns/companies/difficulties |
| `PUT` | `/dsa/problems/{problem_id}/progress` | Upsert progress; schedules a revision |
| `GET` `POST` | `/dsa/problems/{problem_id}/attempts` | Attempt history |
| `PATCH` | `.../attempts/{attempt_id}` | Amend an attempt |
| `GET` `PUT` | `/dsa/problems/{problem_id}/notes` | Structured notes |
| `GET` `POST` | `/dsa/problems/{problem_id}/code` | Code snippets |
| `PUT` `DELETE` | `.../code/{snippet_id}` | Update/delete a snippet |
| `POST` | `/dsa/problems/{problem_id}/revision` | Schedule a review |

### LLD and HLD

Identical shapes under `/lld` and `/hld`:

| Method | Path |
|---|---|
| `GET` | `/{lld\|hld}` |
| `GET` | `/{lld\|hld}/{topic_id}` |
| `PUT` | `/{lld\|hld}/{topic_id}/progress` |
| `GET` `PUT` | `/{lld\|hld}/{topic_id}/notes` |
| `GET` `POST` | `/{lld\|hld}/{topic_id}/code` |
| `PUT` `DELETE` | `/{lld\|hld}/{topic_id}/code/{snippet_id}` |

### Daily plan

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/today` | Today's plan, generated once and persisted |
| `GET` | `/today/explain` | Why the scheduler chose those problems (read-only) |
| `GET` | `/daily-plans` | Plan history |
| `GET` | `/daily-plans/{plan_date}` | A specific day's plan |
| `PATCH` `DELETE` | `/daily-plans/items/{item_id}` | Tick off / remove an item |

### Revisions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/revisions` | Queue, filterable by `bucket=due\|overdue\|upcoming` |
| `GET` | `/revisions/summary` | Badge counts |
| `POST` | `/revisions/{revision_id}/complete` | Record an outcome; idempotent |
| `POST` | `/revisions/promote-stale` | Queue reviews for stale solved problems |

### Study sessions

| Method | Path |
|---|---|
| `POST` | `/study-sessions/start` |
| `POST` | `/study-sessions/{session_id}/stop` |
| `GET` | `/study-sessions` |
| `GET` | `/study-sessions/running` |

### Statistics

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/stats/overview` | One dashboard payload |
| `GET` | `/stats/dsa/topics` | Per-topic counts |
| `GET` | `/stats/dsa/difficulty` | Per-difficulty counts |
| `GET` | `/stats/activity` | Time series (`7d`/`30d`/`90d`/`1y`), zero-filled |
| `GET` | `/stats/streak` | Current and longest streak |
| `GET` | `/stats/mastery` | Per-topic mastery |

### Offline sync

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/sync/push` | Apply a batch of offline mutations |
| `GET` | `/sync/pull` | Changes after a cursor, oldest first |
| `GET` | `/sync/status` | Server cursor and pending count |

### AI tutor

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ai/chat` | Ask a question, optionally grounded in a problem/topic |
| `GET` | `/ai/actions` | Supported actions and context types |
| `GET` | `/ai/conversations` | Conversation list with previews |
| `GET` `DELETE` | `/ai/conversations/{conversation_id}` | Fetch or delete |

### Unauthenticated

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/health/ready` | Readiness: database + auth, no secrets |

---

## Database tables

**26 tables in `public`.** Six pre-existed; twenty were added.

### Pre-existing (adapted, never replaced)

| Table | Notes |
|---|---|
| `user_problem_progress` | DSA progress. Columns added: `created_at`, `version`, `deleted_at`, `revision_count`, `is_favorite` |
| `problem_notes` | Added `created_at`, `version`, `deleted_at` |
| `code_snippets` | `problem_id` made nullable; added `context_type`, `context_id`, `title`, `is_primary`, timestamps |
| `daily_plans` | Added `status`, `timezone`, `generated_by`, `notes`, timestamps; `UNIQUE (user_id, date_key)` |
| `study_sessions` | Added `session_type`, `started_at`, `ended_at`, `duration_minutes`, `context_id`, `context_label`, `note`, `device_id`, timestamps |
| `design_topics` | **Left completely untouched** — superseded by the normalised LLD/HLD tables |

### Added

| Group | Tables |
|---|---|
| Catalog | `dsa_problems`, `dsa_topics` |
| LLD | `lld_topics`, `lld_progress`, `lld_notes` |
| HLD | `hld_topics`, `hld_progress`, `hld_notes` |
| Practice | `problem_attempts`, `revision_queue` |
| Planning | `daily_plan_items` |
| Activity | `user_activity_days` |
| Settings | `user_settings`, `user_devices` |
| Sync | `sync_changes`, `sync_mutations` |
| AI | `ai_conversations`, `ai_messages`, `ai_rate_limits` |
| Alembic | `alembic_version` |

---

## Migrations

Three migrations, applied with `alembic upgrade head`:

| Revision | Kind | What it does |
|---|---|---|
| `0001_existing_schema_adaptation` | hand-written, guarded | Adds columns/indexes/constraints to the six pre-existing tables and backfills existing rows. Every step is guarded with `_column_exists`/`_table_exists` helpers, so it is safe to run against a database that has already drifted. |
| `0002_new_tables` | autogenerated | Creates the 19 new tables and 53 indexes. |
| `0003_progress_status_default` | hand-written | Adds `DEFAULT 'not_started'` to `user_problem_progress.status`. |

Safety properties:

- **Additive only.** `upgrade()` in every revision contains no `DROP TABLE`, `DROP COLUMN`,
  `DROP CONSTRAINT`, `TRUNCATE` or `DELETE`.
- **`downgrade()` only removes what its own revision added** — never pre-existing data.
- **Destructive autogenerate is blocked.** `process_revision_directives` refuses to emit a
  destructive operation unless `ALLOW_DESTRUCTIVE_MIGRATIONS=1` is set explicitly.
- **Supabase-owned schemas are excluded** (`auth`, `storage`, `extensions`, `realtime`, …), so
  autogenerate can never propose altering platform objects.
- **The five adapted tables are excluded from autogenerate comparison**, which is what stops a
  later `alembic revision --autogenerate` from proposing to drop the `auth.users` foreign keys
  or narrow `text` back to `varchar(n)`.

Common commands:

```bash
alembic upgrade head                        # apply
alembic current                             # current revision
alembic downgrade -1                        # undo the last revision
alembic revision --autogenerate -m "..."    # generate (review before applying)
alembic upgrade head --sql > planned.sql    # print SQL without connecting
```

> **Migrating an empty database will fail** with `relation "daily_plans" does not exist`. This is
> expected: revision `0001` *adapts* the pre-existing tables rather than creating them. On
> Supabase those tables already exist. For a local database, load
> `tests/fixtures/legacy_schema.sql` first — that is exactly what the test suite does.

---

## Supabase modifications required

Everything below was already applied to the project. Reproduce it with `alembic upgrade head`.

### 1. Run the migrations

```bash
alembic upgrade head
```

This is the only required step. It leaves all six existing tables, their rows and their
`auth.users` foreign keys intact.

### 2. Seed the curriculum

```bash
python -m scripts.seed_curriculum
```

Inserts 90 DSA problems, 16 topics, 20 LLD topics and 20 HLD topics. Idempotent — a second run
reports `inserted=0 unchanged=130`.

### 3. Decide what to do with `design_topics` (optional)

`design_topics` held a flat per-topic note document that cannot represent either curriculum
(HLD needs 13 design sections; LLD needs a class-responsibility breakdown), so it is no longer
read or written. Its data is **not deleted**. To copy it into the new tables:

```bash
python -m scripts.backfill_design_topics --dry-run   # preview
python -m scripts.backfill_design_topics             # apply
```

Read-only on the source and idempotent. Rows whose `area` is unrecognised, or whose title
matches no seeded topic, are **reported and skipped** rather than force-fitted — the LLD/HLD
catalogues are shared by every user, so the script never inserts into them.

### 4. Row-Level Security (optional hardening)

RLS is currently enabled on some tables with no policies, which means only the service role can
read them. The API connects as a privileged role, so it is unaffected. If you deploy with a
least-privilege role, apply `scripts/sql/rls_hardening.sql`, which creates a `NOBYPASSRLS` role
and policies keyed on the `app.current_user_id` GUC that `app/db/session.py` sets per request.

### 5. Confirm the schema matches

```bash
python -m scripts.inspect_supabase_schema
```

Read-only. Compares the live database against the ORM and writes `schema_snapshot.json` and
`schema_report.md`.

---

## Environment variables

Copy `.env.example` to `.env`. Required values are marked **yes**.

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | **yes** | Async connection string for the app |
| `DATABASE_URL_DIRECT` | no | Non-pooler URL for Alembic. Falls back to `DATABASE_URL` |
| `SUPABASE_URL` | **yes** | Project URL. Derives the JWKS URL and expected issuer |
| `SUPABASE_PUBLISHABLE_KEY` | **yes** | Publishable/anon key. Alias `SUPABASE_ANON_KEY` also accepted |
| `TEST_DATABASE_URL` | no | Enables the DB-backed tests. Unset ⇒ they skip |
| `AI_PROVIDER` | no | `gemini` (default), `groq`, or `stub` |
| `AI_API_KEY` | no | Required when the provider is not `stub` |
| `AI_MODEL` | no | Model name override |
| `AI_RATE_LIMIT_PER_HOUR` | no | Per-user AI request cap (default 60) |
| `APP_ENV` | no | `development` / `staging` / `production` / `test` |
| `LOG_JSON` | no | `true` for structured logs (default in production) |
| `CORS_ORIGINS` | no | Comma-separated allowed origins |
| `DEFAULT_TIMEZONE` | no | Fallback when a client sends no timezone |
| `REVISION_INTERVALS` | no | The spaced-repetition ladder, as JSON |
| `DAILY_DSA_COUNT_DEFAULT` / `_MAX` | no | Plan size bounds |
| `REVISION_DSA_COUNT_DEFAULT` / `_MAX` | no | Revision-slot bounds |
| `SYNC_PULL_PAGE_SIZE` / `_MAX` | no | Sync page sizes |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | no | Connection pool sizing |

### `DATABASE_URL` vs `DATABASE_URL_DIRECT`

Both point at the same database but via different endpoints:

| | `DATABASE_URL` | `DATABASE_URL_DIRECT` |
|---|---|---|
| Used by | the running app | Alembic, schema inspector |
| Endpoint | pooler (`...pooler.supabase.com`) | direct (`db.<ref>.supabase.co`) |
| Why | many requests share few connections | DDL needs advisory locks and session state that transaction pooling breaks |

⚠️ **`db.<ref>.supabase.co` is IPv6-only.** It resolves to an AAAA record with no A record, so it
works on IPv6-capable hosts but fails on IPv4-only networks (some CI runners and PaaS defaults).
For maximum portability, use the **Session pooler** string from *Dashboard → Connect* for
`DATABASE_URL`.

> **Password encoding:** if your password contains special characters, URL-encode them (`@` →
> `%40`). Note that `%` must remain encoded inside the URL — `alembic/env.py` escapes it for
> `configparser`, which would otherwise reject the value as invalid interpolation syntax.

---

## Running the app

```bash
uvicorn app.main:app --reload                          # development
uvicorn app.main:app --host 0.0.0.0 --port 8000        # container
uvicorn app.main:app --workers 4                       # production
```

Startup does two things worth knowing about:

1. **Fetches the Supabase JWKS once** and caches it for `SUPABASE_JWKS_CACHE_SECONDS`
   (default 600). A JWKS outage at boot logs a warning but does not prevent startup; individual
   authenticated requests then fail closed with 401 rather than 500.
2. **Builds the AI provider.** If `AI_API_KEY` is missing the tutor is disabled with a warning
   and the rest of the API works normally — the AI is never on the critical path.

---

## Tests

```bash
# Unit tests only — no database needed
pytest tests/test_units.py tests/test_auth.py -q

# Everything (DB-backed tests skip unless TEST_DATABASE_URL is set)
TEST_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/interviewready_test" pytest -q

# With coverage
pytest --cov=app --cov-report=term-missing
```

**282 tests across 10 modules.**

| Module | Tests | Covers |
|---|---|---|
| `test_units.py` | 41 | Revision ladder, scheduler determinism, streak maths, config derivation |
| `test_auth.py` | 17 | Signature verification, algorithm confusion, expiry, issuer, audience, anon role |
| `test_harness.py` | 6 | Health, 401 enforcement, error envelope, route count |
| `test_dsa.py` | 43 | Catalog, progress, attempts, notes, code, revisions |
| `test_today.py` | 23 | Plan generation, determinism, idempotency, item mutation |
| `test_topics.py` | 24 | LLD and HLD (each assertion runs against both) |
| `test_stats.py` | 21 | Overview, breakdowns, activity series, streak, mastery |
| `test_sync.py` | 28 | Push, pull, idempotency, conflicts, cursor, entity coverage |
| `test_ai.py` | 25 | Validation, context grounding, conversations, rate limiting |
| `test_users.py` | 22 | Profile, settings, devices, export completeness and secrecy |

How the DB-backed tests work:

- The schema is built **by running the real migrations**, so a broken migration fails the suite.
- Each test runs inside a transaction that is **rolled back afterwards**, so tests are
  order-independent.
- Auth is overridden at the dependency layer (the same seam the real JWT check uses), which is
  why `test_auth.py` tests the verifier directly.
- **No test ever touches the real Supabase project.** The suite uses a throwaway database and a
  fake `SUPABASE_URL`.

---

## Swagger / OpenAPI

| | |
|---|---|
| Swagger UI | <http://localhost:8000/docs> |
| ReDoc | <http://localhost:8000/redoc> |
| Raw schema | <http://localhost:8000/openapi.json> |

The schema declares a `SupabaseBearer` security scheme, so **Authorize** in Swagger UI accepts a
Supabase access token directly:

1. Sign in to your Supabase project and copy an access token, or call
   `POST {SUPABASE_URL}/auth/v1/token?grant_type=password` with an email/password.
2. Click **Authorize**, paste the token, authorise.
3. Every endpoint now sends `Authorization: Bearer <token>`.

---

## Seeding and other scripts

All scripts are run as modules from `backend/` with the virtualenv active.

| Command | Purpose |
|---|---|
| `python -m scripts.seed_curriculum` | Idempotent curriculum upserts. Flags: `--dry-run`, `--prune`, `--only dsa\|lld\|hld` |
| `python -m scripts.backfill_design_topics` | One-way legacy migration. Flags: `--dry-run`, `--user <uuid>` |
| `python -m scripts.backup_public_schema` | Logical backup of the `public` schema. Flags: `--output`, `--tables`, `--schema` |
| `python -m scripts.inspect_supabase_schema` | Read-only drift report vs the ORM |
| `python -m scripts.validate_models` | Compile every table and configure all mappers |
| `alembic upgrade head` | Apply migrations |

`backup_public_schema.py` exists because `pg_dump` **refuses to dump a newer server than
itself** — dumping a PostgreSQL 17 Supabase instance with the PostgreSQL 16 client that
Homebrew ships fails with *"aborting because of server version mismatch"*. The script produces a
portable SQL backup using only the `asyncpg` dependency the app already needs:

```bash
python -m scripts.backup_public_schema --output backups/before_v2.sql
psql "$DATABASE_URL" -f backups/before_v2.sql      # restore
```

---

## Deployment (Render)

`render.yaml` provisions the service; `Dockerfile` is used as the build image.

1. Push the repository.
2. In Render: **New → Blueprint**, select the repo. `render.yaml` is read automatically.
3. Set the secret environment variables in the dashboard (they are marked `sync: false`):
   `DATABASE_URL`, `DATABASE_URL_DIRECT`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`,
   and `AI_API_KEY` if the tutor is enabled.
4. Deploy. The start command runs `alembic upgrade head` before `uvicorn`, so migrations apply
   on release.

Notes:

- Use the **Session pooler** URL for `DATABASE_URL` on Render, because Render's default
  networking is IPv4-only and `db.<ref>.supabase.co` is IPv6-only.
- The health check path is `/health/ready`.
- `APP_ENV=production` enables JSON logs and tightens CORS.

---

## Known TODOs

**Deliberately deferred, with the reasoning:**

1. **No refresh-token exchange.** The API verifies access tokens only. Clients refresh through
   Supabase's own `auth/v1/token` endpoint, which keeps the API stateless and free of token
   storage. A `/auth/refresh` proxy was out of scope.
2. **`promote-stale` is request-triggered, not scheduled.** It is exposed as an endpoint so it
   works without a scheduler. A nightly cron (or Supabase `pg_cron`) calling it would be the
   natural next step.
3. **Rate limiting is stored in Postgres.** A composite-PK counter table is correct and needs no
   extra infrastructure; at very high volume a Redis counter would be cheaper.
4. **No full-text search.** `search` uses `ILIKE`. Fine for a few hundred problems; `tsvector`
   would be the upgrade.
5. **`design_topics` is retained but unread.** Kept so no data is destroyed; `backfill_design_topics.py`
   copies it across on demand.
6. **RLS is enabled but unpolicied** on some tables. The app connects as a privileged role, so
   this is inert. `scripts/sql/rls_hardening.sql` provides the least-privilege alternative.
7. **Content is metadata only.** No problem statements or solutions are stored — only titles,
   slugs, topics, patterns and external links — so the curriculum carries no copyrighted text.
8. **`ai_auto_reveal_solution` is stored but not enforced.** It is persisted as a preference for
   the client to honour; server-side enforcement would need a per-request policy decision the
   provider protocol does not currently express.

**Verified working end-to-end against the real Supabase project:** 26 tables, 3 migrations, all
six legacy rows and `auth.users` foreign keys intact, zero schema drift, 90/20/20 seeded
curriculum items, and all live read paths (`/today` determinism, `/stats/*`, `/sync/*`,
`/lld`, `/hld`, `/export`) exercised against real data.
