# InterviewReady — Architecture

Deep knowledge transfer for anyone maintaining, extending, or reviewing this backend.

This document explains **why** the system is shaped the way it is. For setup and the endpoint
list see `README.md`; for a guided tour of the code see `WALKTHROUGH.md`.

---

## Contents

1. [The governing constraint](#1-the-governing-constraint)
2. [System context](#2-system-context)
3. [Layered architecture](#3-layered-architecture)
4. [Request lifecycle](#4-request-lifecycle)
5. [Data model](#5-data-model)
6. [The existing-schema adaptation](#6-the-existing-schema-adaptation)
7. [Idempotency and the upsert strategy](#7-idempotency-and-the-upsert-strategy)
8. [Offline synchronisation](#8-offline-synchronisation)
9. [Spaced repetition](#9-spaced-repetition)
10. [The daily-plan scheduler](#10-the-daily-plan-scheduler)
11. [Activity and streaks](#11-activity-and-streaks)
12. [The AI tutor](#12-the-ai-tutor)
13. [Authentication and authorisation](#13-authentication-and-authorisation)
14. [Errors and observability](#14-errors-and-observability)
15. [Migration strategy](#15-migration-strategy)
16. [Testing architecture](#16-testing-architecture)
17. [Configuration surface](#17-configuration-surface)
18. [Deliberate non-decisions](#18-deliberate-non-decisions)
19. [Known constraints and risks](#19-known-constraints-and-risks)
20. [Extension guide](#20-extension-guide)

---

## 1. The governing constraint

Every design decision in this codebase follows from one fact:

> **The database already existed, contained real user data, and was not allowed to change
> destructively.**

Six tables — `user_problem_progress`, `problem_notes`, `code_snippets`, `daily_plans`,
`study_sessions`, `design_topics` — were already populated in Supabase, with foreign keys to
`auth.users` and RLS enabled.

Three consequences ripple through everything:

1. **The catalog's primary key must be the problem slug**, because the existing columns are
   `problem_id text`. Introducing UUID keys would have required rewriting every user's rows.
2. **Reused tables cannot be ORM-managed by migrations.** Autogenerate would see `varchar(300)`
   where the database has `text` and propose narrowing it; it would also propose dropping the
   `auth.users` foreign keys, because the ORM declares no relationships onto them.
3. **Application-side invariants must tolerate pre-existing data.** Existing rows may reference
   problems that no longer exist in the catalog, so relationships onto the catalog are
   `viewonly` and every join is a `LEFT JOIN`.

The alternative design — a fresh schema with a data migration — was rejected because it risks
user data for no functional gain.

---

## 2. System context

```
┌──────────────────────────┐        ┌──────────────────────────┐
│  iOS client (offline-    │        │  React web client        │
│  first, queues mutations)│        │  (Vite, TanStack Query)  │
└────────────┬─────────────┘        └────────────┬─────────────┘
             │  Bearer <supabase access token>   │
             └───────────────┬───────────────────┘
                             ▼
              ┌──────────────────────────────┐
              │   InterviewReady API         │
              │   FastAPI, stateless, N replicas
              └───┬──────────┬───────────┬───┘
                  │          │           │
       ┌──────────▼──┐  ┌────▼────────┐  │
       │ Supabase    │  │ Supabase    │  │
       │ Postgres    │  │ Auth (JWKS) │  │
       │ (26 tables) │  │             │  │
       └─────────────┘  └─────────────┘  │
                                         │
                            ┌────────────▼────────────┐
                            │ AI provider (Gemini or  │
                            │ Groq) — external,       │
                            │ best-effort, never on   │
                            │ the critical path       │
                            └─────────────────────────┘
```

**Three external dependencies:** PostgreSQL, Supabase Auth (JWKS over HTTPS), and an AI provider.

**Notably absent:** Redis, Celery, Kafka, Kubernetes. Every correctness guarantee is obtained from
the database instead — unique constraints for idempotency, an identity column for the sync cursor,
a counter table for rate limiting, and a persisted plan row for determinism. This was a deliberate
trade: fewer moving parts to operate, at the cost of a little database load.

---

## 3. Layered architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Routers            app/api/v1/*.py                          │
│  Parse, validate, authorise, shape. No business logic.       │
└───────────────────────────┬──────────────────────────────────┘
                            │  Services container (per request)
┌───────────────────────────▼──────────────────────────────────┐
│  Services           app/services/*.py                        │
│  All decisions. The only layer that commits.                 │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Repositories       app/repositories/*.py                    │
│  The only layer that writes SQL. All queries take user_id.   │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Models             app/db/models/*.py                       │
│  Schema of record. 24 tables across 9 modules.               │
└──────────────────────────────────────────────────────────────┘
```

### Why the split earns its keep

**Routers are disposable.** `app/api/v1/dsa.py` is 500 lines of signatures, docstrings and
response shaping — no branching on business rules. Adding a `PATCH /notes` endpoint is ~15 lines.

**Services are testable without HTTP.** `RevisionPolicy` and `DailyPlanScheduler` are pure: given
settings and inputs they return a decision. That is why `test_units.py` covers the ladder,
scheduler determinism and streak maths with no database at all.

**Repositories are the audit surface.** Because every query lives in 11 modules and every method
takes `user_id`, checking that tenant isolation holds is reviewing 11 files, not 15.

### Enforced conventions

| Rule | Enforced by |
|---|---|
| The user id comes only from a verified token | `get_current_user` is the only identity source; no route accepts a `user_id` parameter |
| Every personal query filters on `user_id` | Repository signatures make it required |
| Services own `commit()` | Repositories never commit |
| Timestamps are server-derived | Services compute `utcnow()`; no client timestamp is trusted |
| One error envelope | All failures route through `error_response()` |

---

## 4. Request lifecycle

```
1.  RequestContextMiddleware
      • assign/propagate X-Request-ID
      • bind request_id to a contextvar (so every log line carries it)

2.  SecurityHeadersMiddleware
      • X-Content-Type-Options, X-Frame-Options, Referrer-Policy

3.  CORS  (production: no wildcard)

4.  Route dependency resolution
      • get_settings()            cached singleton
      • get_db()                  request-scoped AsyncSession
      • get_current_user()        Bearer → JWKS verify → AuthenticatedUser
      • get_services()            build the Services container
      • on success: bind user_id to a contextvar

5.  Route handler
      • validate payload (pydantic)
      • call one service method; return a schema

6.  Service → Repository → SQL
      • service decides, commits when the change is durable

7.  Response
      • serialise, log method/path/status/duration

8.  Teardown
      • rollback on exception, then close the session
```

### Session scoping

The session is created per request and closed in a `finally`. It is **never** cached on
`app.state`, because a cached session would outlive the request that owns it and leak state
across requests under concurrency.

`error_handlers.py` installs handlers for `AppError`, `RequestValidationError`,
`StarletteHTTPException`, `IntegrityError`, `OperationalError`/`InterfaceError` (503),
`SQLAlchemyError` (500) and bare `Exception` (500). Registering a handler for bare `Exception`
is what guarantees the envelope holds even for a bug in the error path itself.

---

## 5. Data model

26 tables. Grouped by concern:

```
Catalog (read-only to users)
  dsa_problems ─ TEXT pk = slug
  dsa_topics   ─ TEXT pk = slug
  lld_topics ─┐
  hld_topics ─┘  UUID pk

Per-user practice data
  user_problem_progress  ← pre-existing
  problem_attempts
  problem_notes          ← pre-existing
  code_snippets          ← pre-existing, now polymorphic
  revision_queue
  lld_progress / lld_notes
  hld_progress / hld_notes

Planning
  daily_plans            ← pre-existing
  daily_plan_items

Activity
  study_sessions         ← pre-existing
  user_activity_days     ← derived rollup

Sync
  sync_changes           ← bigint seq IDENTITY = the cursor
  sync_mutations         ← idempotency ledger
  user_devices

AI
  ai_conversations
  ai_messages
  ai_rate_limits         ← composite pk (user_id, window_start)

Settings
  user_settings
```

### Key relationships

```
auth.users
   │  (6 foreign keys from the pre-existing tables — preserved)
   ├── user_problem_progress ──┐
   ├── problem_notes           │  NO FOREIGN KEY, by design:
   ├── code_snippets           │  pre-existing rows may reference
   ├── daily_plans             │  problems that predate the catalog.
   ├── study_sessions          │  Declared as viewonly relationships
   └── design_topics (unused)  │  with explicit primaryjoins.
                               ▼
                          dsa_problems
                          (TEXT pk = slug)
```

That missing foreign key is the single most important thing to understand about the data model.
It exists because the catalog was added *after* the user tables, so referential integrity is
enforced by the application — `ProgressService` validates the problem exists before writing, so a
typo cannot create orphan progress.

### Why `dsa_problems` has a text primary key

The pre-existing columns are `problem_id text` in four tables, plus inside
`daily_plans.problem_ids` (a JSONB array). Making the catalog's key the same type means all of
them join directly:

```sql
-- Works because both sides are text.
SELECT p.*, progress.*
FROM dsa_problems p
LEFT JOIN user_problem_progress progress
       ON progress.problem_id = p.id AND progress.user_id = $1
```

The slug (`"two-sum"`) is also stable across reseeds, so it is a natural key, not a surrogate.

### Polymorphic code snippets

`code_snippets.problem_id` was made nullable and given two extra columns:

- `context_type` ∈ `dsa | lld | hld` (defaulted to `dsa`, backfilled as `dsa`)
- `context_id` **text** — the problem slug for DSA, the topic UUID for LLD/HLD

One table serves three curricula. The column is text precisely because it holds either a slug or
a UUID; typing it as `uuid` in the response schema caused a 500 on every DSA snippet request until
it was fixed.

---

## 6. The existing-schema adaptation

Migration `0001` is the most delicate file in the repository. It is hand-written and every step is
guarded:

```python
add_column_if_missing(table, sa.Column("version", sa.Integer(), nullable=True))
op.execute(f"UPDATE public.{table} SET version = 1 WHERE version IS NULL")
op.alter_column(table, "version", nullable=False, server_default=sa.text("1"))
```

The three-step pattern — **add nullable → backfill → tighten** — is what lets the migration run
against a populated table. Adding a NOT NULL column with no default to a table containing rows
fails immediately.

Guards used throughout: `_table_exists`, `_column_exists`, `_constraint_exists`, `_index_exists`,
`add_column_if_missing`, `make_nullable_if_needed`, `create_index_if_missing`. They make the
migration **idempotent and safe against a database that has already drifted**.

### What was added to each table

| Table | Added | Backfilled |
|---|---|---|
| `user_problem_progress` | `created_at`, `version`, `deleted_at`, `revision_count`, `is_favorite` | `created_at` from `updated_at`; `version=1`; `revision_count=0`; `is_favorite=false` |
| `problem_notes` | `created_at`, `version`, `deleted_at` | Same pattern |
| `code_snippets` | `title`, `is_primary`, `context_type`, `context_id`, timestamps; `problem_id` → nullable | `context_type='dsa'`, `context_id = problem_id` |
| `daily_plans` | `status`, `timezone`, `generated_by`, `notes`, timestamps; `UNIQUE (user_id, date_key)` | `status='active'`, `timezone='UTC'` |
| `study_sessions` | `session_type`, `started_at`, `ended_at`, `duration_minutes`, `context_id`, `context_label`, `note`, `device_id`, timestamps | Mapped from legacy `date`/`minutes`/`area` |

Note that legacy columns were **kept, not dropped**. `study_sessions.date`, `.minutes` and `.area`
still exist, because other (pre-existing) clients read them. New columns coexist; the API only
uses the new ones. That is why a session insert satisfies both old and new readers.

### Why migration 0001 can't run offline

`alembic upgrade head --sql` fails for `0001` with
`AttributeError: 'NoneType' object has no attribute 'scalar'`, because the migration introspects
live state via `op.get_bind()`. That is inherent to a guarded migration — it must ask the
database what already exists. Use `--sql` for `0002`, or review `0001` directly.

### Why migrating an empty database fails

`relation "daily_plans" does not exist`. `0001` **adapts** the pre-existing tables rather than
creating them, and `0002` references them. On Supabase they already exist; for a local database,
load `tests/fixtures/legacy_schema.sql` first — which is exactly what the test suite does.

---

## 7. Idempotency and the upsert strategy

Every user-facing write is an UPSERT. `app/utils/upsert.py` builds them in one place so `version`
bumps and `updated_at` refreshes can never be forgotten in one service but not another.

```python
stmt = pg_insert(model).values(**values)
stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=update_values)
stmt = stmt.returning(model)
return await session.execute(stmt.execution_options(populate_existing=True))
```

### The subtle part: NOT NULL defaults on partial payloads

PostgreSQL validates the **proposed insert row** before it looks for a conflict. So this fails
even though the row exists and the update wouldn't touch `status`:

```sql
INSERT INTO user_problem_progress (id, user_id, problem_id, confidence)
VALUES (..., 'two-sum', 4)
ON CONFLICT (user_id, problem_id) DO UPDATE SET confidence = excluded.confidence;
-- ERROR: null value in column "status" violates not-null constraint
```

This mattered because an offline client that syncs only a changed field produces exactly this
shape. The fix is `apply_server_defaults`, which fills in defaults for omitted NOT NULL columns —
and critically, **keeps them out of the `DO UPDATE` clause**:

```python
values, injected = apply_server_defaults(model, dict(values))
update_columns = [
    key for key in values
    if key not in IMMUTABLE_COLUMNS
    and key not in conflict_columns
    and key not in injected        # ← without this, a partial update would RESET the value
    and key in existing_columns
]
```

Without that exclusion, syncing only `confidence` would silently return a solved problem to
`not_started`. A default exists to populate a *new* row; writing it over an existing value
destroys user data.

Three layers defend this:

1. **Migration `0003`** gives `user_problem_progress.status` the `DEFAULT 'not_started'` its
   sibling columns already had. It was the only NOT NULL column without one.
2. **The model mirrors it** (`server_default=text("'not_started'")`) so the ORM agrees.
3. **`apply_server_defaults`** generalises it to every model, so the next partial column can't
   reintroduce the bug.

### `IMMUTABLE_COLUMNS`

`id`, `user_id`, `created_at`, `updated_at`, `version` are never overwritten by a payload.
`version` is incremented by the statement itself, making it a monotonic optimistic-concurrency
counter.

---

## 8. Offline synchronisation

The hardest correctness problem in the system. A phone in airplane mode queues mutations and
replays them later; a replay may arrive twice, out of order, or after the server has moved on.

```
Client queues                    Server applies
─────────────                    ──────────────
{uuid, entity, op, payload,      ┌─ mutation_id seen before?  → return STORED result
 base_version, client_ts}        ├─ base_version behind?      → conflict + server_record
        │                        ├─ constraint violated?      → rejected, with reason
        ▼                        └─ otherwise                 → applied
POST /sync/push  (batch)
        │
        ▼
sync_mutations  ── UNIQUE (user_id, mutation_id)  ← the idempotency guarantee
```

### Guarantee 1 — replay safety

Each mutation carries a client-generated `mutation_id`. Before processing, the whole batch is
looked up in one query:

```python
already = await self._sync.get_mutations(user_id=user_id, mutation_ids=[m.mutation_id for m in payload.mutations])
```

A replay returns the **stored** result verbatim, including the original `version`. The client
cannot distinguish a replay from the original response, which is exactly right. The unique
constraint on `(user_id, mutation_id)` is the real guarantee — a race between two concurrent
pushes loses the insert and is reported as a duplicate, not as an error.

### Guarantee 2 — the cursor is an identity column, not a timestamp

`sync_changes.seq` is a `BIGINT GENERATED ... AS IDENTITY`. The pull cursor is its value.

A timestamp cursor has three fatal problems: two changes in the same millisecond collide,
clock skew makes ordering unreliable, and deletions are invisible. An identity column gives
strict monotonic ordering per database, and the change log stores deletions as explicit
`operation='delete'` rows — so a device that was offline for a week learns about them.

```python
changes = await self._sync.pull_changes(user_id=user_id, cursor=cursor, limit=page_size + 1)
has_more = len(changes) > page_size          # one extra row detects "more" without COUNT
next_cursor = page[-1].seq if page else cursor
```

The `+1` fetch is a small but real optimisation: it answers "is there more?" without a second
round trip.

### Guarantee 3 — conflicts return the server's record

When `base_version` doesn't match, the response includes `server_record` — the authoritative
current row. Without it a client can only retry blindly and clobber the other device's change.
With it, the client merges and retries with the correct `base_version`.

### Deletes are soft everywhere

`deleted_at` tombstones. A hard delete would be invisible to `/sync/pull`, so a deleted row would
survive forever in every other device's local store. Every read path filters
`deleted_at IS NULL`.

### Entity coverage

10 handlers, keyed by `SyncEntity`:

| Entity | Notes |
|---|---|
| `problem_progress`, `problem_notes` | Keyed by `(user_id, problem_id)` |
| `code_snippet`, `problem_attempt`, `revision` | Keyed by client-supplied `record_id`, so devices agree on identity |
| `lld_progress`, `lld_notes`, `hld_progress`, `hld_notes` | Routed through the generic topic repository; require `topic_id` |
| `user_settings` | Single row per user |

An unknown entity is **rejected per mutation**, not as a batch failure — a newer client pushing a
field an older server doesn't know yet must not lose the rest of the batch. That is also why
`_field_filter` silently drops unrecognised keys, and why `SyncMutationResult` is per-mutation.

A savepoint per mutation means one bad record cannot roll back the whole batch:

```python
async with self._sync.session.begin_nested():     # savepoint per mutation
    result = await self._apply_mutation(...)
    await self._sync.record_mutation(...)          # data + change-log write stay atomic
```

Note what happens on `IntegrityError`: if the constraint is the mutation ledger it is a duplicate;
**any other** constraint violation is a rejection. Treating a NOT NULL violation as a duplicate
would claim success while discarding the user's change — the worst possible outcome.

---

## 9. Spaced repetition

The ladder is **configuration, not code** (`REVISION_INTERVALS`, JSON):

```
confidence 0 → [1]                    confidence 3 → [3, 7, 16, 35]
confidence 1 → [1, 3]                 confidence 4 → [5, 14, 35, 75, 150]
confidence 2 → [2, 5, 12]             confidence 5 → [7, 21, 60, 120, 240, 365]
```

`revision_count` indexes into the ladder for that confidence, clamped to the last rung — so a
problem reviewed many times keeps the maximum interval rather than running off the end.

```python
ladder = self._settings.intervals_for_confidence(confidence)
index = max(0, min(revision_count, len(ladder) - 1))
return ladder[index]
```

### Derived, not duplicated

`revision_ladder_max_interval` is computed from the ladder by a model validator
(`object.__setattr__`), so the staleness threshold can never disagree with the intervals:

```python
longest = max(max(v) for v in self.revision_intervals.values())
object.__setattr__(self, "revision_ladder_max_interval", longest or 365)
```

### Deliberate exceptions to the ladder

- **A failed review always returns in 1 day.** Hardcoded, ignoring the ladder entirely — failing
  is the strongest signal, and a well-understood problem should not wait 21 days after a failure.
- **`partial` does not advance the ladder as far as success.**
- **Mastery is a separate deliberate signal**, not an automatic promotion. `revision_service`
  preserves an existing `mastered` status rather than demoting it back to `solved` on review —
  otherwise reviewing a mastered problem would lose the user's deliberate progress.

### Priority

`priority_for(confidence, reason)` ranks low-confidence and failed items above scheduled ones, so
the revision queue surfaces the items most at risk first.

### Where reviews come from

1. Solving a problem → `schedule_after_solve` (reason `low_confidence` or `scheduled_revision`).
2. Completing a review → `schedule_after_review` (advances the ladder).
3. Manually → `POST /dsa/problems/{id}/revision`.
4. `promote_stale_problems` → queues reviews for solved problems untouched beyond the ladder's
   maximum interval (reason `long_time_since_review`). Without this a user who solved everything
   would see an empty queue forever.

---

## 10. The daily-plan scheduler

`DailyPlanScheduler.select()` scores the whole catalog and picks a plan. It is the most
algorithmically interesting part of the system.

### Scoring

| # | Signal | Weight | Rationale |
|---|---|---|---|
| 1 | Curriculum position | `(1 - ratio) × 30` | Earlier material first — the backbone signal |
| 2 | Importance (1–5) | `× 3.0` | Interview frequency |
| 3 | Difficulty ramp for stage | per-stage table | Match difficulty to progress |
| 4 | Weak-topic boost | `max(4, 22 − rank×3)` | Deliberately large, so weaknesses get addressed |
| 5 | Recently assigned | **−1000** | Effectively excludes; never re-assign |
| 6 | Already worked on | −500 / +14 / −25 | A worked problem is a poor *new* pick |
| 7 | Staleness | `min(days/7, 12)` | Bring back untouched material |
| 8 | Company-tagged | `min(count, 5) × 0.8` | Small premium |
| 9 | Deterministic jitter | +[0, 3) | Day-to-day variety |

The −1000 for "recently assigned" is intentionally an order of magnitude larger than anything
else: it must dominate, not merely nudge.

### Determinism

The tie-break is a hash, never `random`:

```python
digest = hashlib.blake2b(f"{user_id}:{plan_date}:{problem_id}".encode(), digest_size=8).digest()
return int.from_bytes(digest, "big") % 300 / 100.0
```

Why this matters: with two uvicorn workers, a user refreshing the page could hit a different
worker. With `random`, the plan would change. With a hash of stable inputs, every worker,
process and replay computes the **same** value — so the plan is reproducible even before
persistence.

### Difficulty staging

```python
ratio < 0.15 → stage 0    ratio < 0.45 → stage 1
ratio < 0.75 → stage 2    otherwise    → stage 3
```

Guarded against `total == 0` — dividing by zero here would break the first request on a fresh
install.

### Weak-topic detection

Topics ranked by **average confidence**, not completion:

```python
scored = [(t, s["average_confidence"], s["interacted"]) for t, s in perf.items() if s["interacted"] > 0]
scored.sort(key=lambda r: (r[1], -r[2], r[0]))   # confidence ↑, exposure ↓, name ↑
```

A topic with zero exposure is **excluded** — it is unstarted, not weak, and curriculum position
already handles it. Sorting by name as the final key keeps the ordering deterministic.

### Selection passes

`_pick_new` applies topic diversity as a **second pass**, so a plan isn't three graph problems in
a row — but it never falls back to a solved or recently-assigned problem. `_pick_revisions`
prioritises by staleness.

### Concurrency

Two requests can generate the same day's plan simultaneously. The `UNIQUE (user_id, date_key)`
constraint is the arbiter:

```python
try:
    async with session.begin_nested():       # savepoint: a losing race must not poison the transaction
        plan = await create_plan(...)
except IntegrityError:
    existing = await get_by_date(...)        # return theirs rather than a 500
```

The savepoint matters: without it, the losing `IntegrityError` would abort the transaction and the
subsequent `SELECT` would fail.

### Persistence

After generating, the service **commits**:

```python
if plan is None:
    plan = await self._generate_plan(...)
    await self._plan_repo.session.commit()
```

This was missing originally, and the consequence was severe: every request minted a **new** plan
and `daily_plans` stayed permanently empty. The endpoint looked correct in isolation — it returned
plausible data — and only a test asserting stability across two requests caught it.

`RECENT_PLAN_LOOKBACK_DAYS = 14` feeds signal 5. `SCHEDULER_VERSION` is stored on every plan
(`generated_by`), so changing the algorithm doesn't silently invalidate stored plans.

---

## 11. Activity and streaks

`user_activity_days` is a **derived rollup**, not a source of truth:

```
study_sessions, daily_plan_items, problem_progress, revision_queue
                              ↓  recompute
                    user_activity_days (per local date)
```

`ActivityService.record()` recomputes `is_active` from thresholds (`streak_min_minutes`,
`streak_min_activities`) rather than incrementing a counter. Deriving is idempotent; incrementing
drifts and double-counts on replay.

**Dates are local, not UTC.** A user studying at 23:30 in Kolkata is on the same calendar day; in
UTC they would be on the next. Timezone comes from `X-Timezone`, falling back to the user's
setting, then the default.

Streak rules:

- **"Yesterday still counts."** A streak is not broken until a full day is missed, so the current
  streak survives unless the last active date is older than yesterday.
- `_longest_run` is an O(n log n) sort plus an O(n) scan using `itertools.pairwise` — cheap enough
  to run on every `/stats/overview`.
- Only **meaningful** events count: a status transition or a completed plan item. A favourite
  toggle or a confidence tweak must not extend a streak — otherwise the metric is meaningless.

---

## 12. The AI tutor

An `AIProvider` **Protocol** with three implementations:

| Provider | Transport |
|---|---|
| `gemini` (default) | REST over httpx, key in a header |
| `groq` | REST over httpx |
| `stub` | Deterministic, offline — used by tests and for local development |

`build_provider(settings)` is used by both `main.py` and the test fixtures, so the test wiring is
identical to production.

### Grounding

`TutorContext` assembles the user's **own** data — problem metadata, their notes, their code,
their progress — and `build_system_prompt` renders it into the prompt. `select_entity_fields`
and `select_note_fields` restrict which fields are sent, so a prompt never leaks more than the
task needs. `context_used` in the response reports what was actually included, which makes
"why did it answer that?" debuggable.

### Rate limiting without Redis

`ai_rate_limits` has a composite primary key `(user_id, window_start)`. An UPSERT increments the
counter for the current window:

```sql
INSERT INTO ai_rate_limits (...) VALUES (...)
ON CONFLICT (user_id, window_start) DO UPDATE SET request_count = ai_rate_limits.request_count + 1
```

A composite PK makes the counter naturally per-user and per-window. Exceeding the limit returns
429 with `Retry-After`. A unique constraint was removed from this table during development
because it duplicated the primary key.

### The AI is never on the critical path

If `AI_API_KEY` is missing, `main.py` logs a warning and sets `app.state.ai_provider = None`. The
app starts, every other endpoint works, and only `/ai/*` reports the tutor unavailable. Startup
never fails because an optional integration is unconfigured.

---

## 13. Authentication and authorisation

### Token verification

```
Authorization: Bearer <jwt>
        ↓
SupabaseTokenVerifier.verify()
        ↓
HttpxJWKSClient.get_signing_key_from_jwt(token)   ← cached, refetch on unknown kid
        ↓
jwt.decode(..., algorithms=ALLOWED_ALGORITHMS, audience=..., issuer=..., leeway=10)
        ↓
AuthenticatedUser(id=<sub>, email, role, session_id, claims)
```

Checked: signature, `exp`, `aud`, `iss`, and that `role != "anon"`. `_to_user` rejects the anon
role explicitly, so the publishable key's role cannot reach authenticated endpoints.

### Why not PyJWT's `PyJWKClient`

It uses `urllib`, which fails on macOS with `CERTIFICATE_VERIFY_FAILED: unable to get local issuer
certificate` — the system certificate store is incomplete. `httpx` works because it bundles
`certifi`. `app/core/jwks.py` therefore implements the client over httpx, with:

- a TTL cache (600 s default);
- **refetch on unknown `kid`**, so key rotation needs no restart;
- **stale-serve during an outage** — a rotated key already held is still valid, and rejecting every
  request during a brief JWKS blip is far worse;
- a 10 s negative cache, so a broken auth server doesn't make every request wait for a timeout;
- `_ALLOWED_ALGORITHMS` rejecting every `HS*` variant, which is the algorithm-confusion defence.

This was found by testing against the **real** Supabase project. A mocked JWKS would never have
surfaced it.

### Authorisation

There is no role system because there is no need for one. Ownership *is* the authorisation model:
every personal query is scoped by `user_id` from the token, so cross-user access is structurally
impossible rather than policy-enforced. `test_*_is_isolated_between_users` tests exist for every
domain, and cross-user deletes return **404** rather than 403 — a 403 would confirm the record
exists.

### RLS

Enabled on some tables with no policies, which means only the service role can read them. The API
connects as a privileged role, so it is unaffected. `set_current_user` publishes
`app.current_user_id` via `set_config(..., true)` — transaction-local, so it cannot leak to the
next request on a pooled connection. `scripts/sql/rls_hardening.sql` provides a `NOBYPASSRLS` role
and policies for a least-privilege deployment.

---

## 14. Errors and observability

### One envelope

```json
{"error": {"code": "UNAUTHENTICATED", "message": "...", "details": null}}
```

`AppError` subclasses carry `status_code` and `code`, so raising the right exception produces the
right response. Handlers exist for every exception type including bare `Exception`.

`IntegrityError` translation maps **constraint names** to specific codes
(`uq_daily_plans_user_id_plan_date` → `DAILY_PLAN_EXISTS`,
`uq_sync_mutations_user_id_mutation_id` → `DUPLICATE_MUTATION`). The constraints are
load-bearing for correctness, so their violation deserves a precise code.

### Logging

- JSON in production (`LOG_JSON=true`), readable console in development.
- `request_id_ctx` and `user_id_ctx` contextvars mean every line carries correlation without
  threading parameters through every function.
- `SENSITIVE_KEYS` redaction — tokens and passwords cannot reach the log. The middleware
  deliberately does **not** log the Authorization header.
- **Lesson learned:** `logger.warning("Integrity error", extra={"detail": ...})` produced a bare
  *"Integrity error"* with no constraint name, because the console formatter only renders
  configured extras. Interpolating into the message (`logger.warning("Integrity error: %s", ...)`)
  is now the convention for values needed while debugging.

### Health

- `/health` — liveness, no dependencies.
- `/health/ready` — reports `database` and `auth` booleans, `detail`, and `auth_config`. It
  constructs the verifier lazily, so readiness is accurate even if startup short-circuited. It
  **never** reports secret values — only whether configuration is present.

---

## 15. Migration strategy

Three revisions:

| Revision | Kind | Purpose |
|---|---|---|
| `0001_existing_schema_adaptation` | hand-written, guarded | Adapt the 6 pre-existing tables |
| `0002_new_tables` | autogenerated | 19 new tables, 53 indexes |
| `0003_progress_status_default` | hand-written | `DEFAULT 'not_started'` for partial upserts |

### Four independent safeguards

| Safeguard | Prevents |
|---|---|
| `process_revision_directives` | Autogenerate emitting `DROP TABLE`/`DROP COLUMN` unless `ALLOW_DESTRUCTIVE_MIGRATIONS=1` |
| `EXCLUDED_SCHEMAS` | Touching `auth`, `storage`, `extensions`, `realtime`, … |
| `AUTOGENERATE_EXCLUDED_TABLES` | Proposing to drop `auth.users` FKs or narrow `text` → `varchar(n)` on the 5 adapted tables |
| Verified backup | Anything the above miss |

`AUTOGENERATE_EXCLUDED_TABLES` deserves emphasis. Without it, the ORM's `varchar(300)` on
`problem_notes.problem_id` would make autogenerate propose narrowing the live `text` column —
a destructive change on a column holding user data. Excluding those tables from comparison is
what makes `alembic revision --autogenerate` safe to run.

### The escaping trap

```python
config.set_main_option("sqlalchemy.url", settings.migration_database_url.replace("%", "%%"))
```

`set_main_option` writes through `configparser`, which treats `%` as an interpolation marker.
Supabase passwords are frequently URL-encoded (`%40` for `@`), so without this the migration
aborts with *"invalid interpolation syntax"* and **migrations cannot run at all**. Doubling is
`configparser`'s own escape, so the value round-trips.

### Backup before migrating

`scripts/backup_public_schema.py` exists because `pg_dump` **refuses to dump a newer server than
itself** — the PostgreSQL 16 client cannot dump the PostgreSQL 17 Supabase instance. The script
reproduces the dump with `asyncpg`, the dependency already present, and was verified by restoring
into a scratch database with `ON_ERROR_STOP=1`.

Two traps it handles: UNIQUE constraints already produce a backing index, so emitting
`pg_indexes` entries naively caused *"relation already exists"* on restore; and values are quoted
through one central function so a value containing a quote cannot break the statement.

---

## 16. Testing architecture

**285 tests, 10 modules.** The split is deliberate:

| Layer | Modules | Needs a DB? |
|---|---|---|
| Pure logic | `test_units.py`, `test_auth.py` | No |
| HTTP + SQL | everything else | Yes |

### Skip, don't fail

`pytest_collection_modifyitems` skips every `db`-marked test when `TEST_DATABASE_URL` is unset, so
`pytest` works on a machine with no database (`51 passed, 231 skipped`) instead of erroring.

### Real migrations, not `create_all`

`apply_migrations` drops `public` and `auth`, loads `tests/fixtures/legacy_schema.sql`, **then**
runs `alembic upgrade head`. A broken migration therefore fails the suite — which is the point.

### Rollback isolation

Each test runs inside a transaction that is rolled back. To make that work while services call
`session.commit()`, the fixture replaces `commit` with a `flush`. `NullPool` plus
`asyncio_default_test_loop_scope = "session"` are **both** required, or the session-scoped engine
is "attached to a different loop".

### The identity-map lesson

Production gives every HTTP request its own session. The suite shares one so the work can be rolled
back — but a shared identity map means a later request can read an object cached by an earlier one,
making conflict detection look broken when it works. The client fixtures therefore reset the
identity map before every request:

```python
async def _reset(_request: httpx.Request) -> None:
    await reset_session_identity_map(db_session)   # flush + expunge_all
```

`expunge_all` rather than `expire_all` — expiring triggers lazy IO outside the greenlet and raises
`MissingGreenlet`.

The general principle: **a test harness that doesn't model production semantics will hide the next
real bug.** Three apparent bugs turned out to be harness artefacts, and each was fixed in the
harness rather than worked around.

### Why auth is tested twice

Route tests override `get_current_user` (the same seam the real check uses), which is fast but
bypasses verification. So `test_auth.py` tests the verifier **directly** with locally generated EC
keys: wrong-key rejection, HS256 rejection, `alg=none` rejection, expiry, wrong issuer, wrong
audience, anon role, malformed tokens. Real crypto, no network.

### No test touches the real project

A throwaway database and a fake `SUPABASE_URL`. The settings fixture **assigns** env vars rather
than `setdefault`-ing them, because a shell that has sourced the real `.env` has already exported
the real `SUPABASE_URL` — which made the auth tests validate the wrong issuer.

---

## 17. Configuration surface

`app/core/config.py` holds every tunable. Nothing that a product owner might want to change is
hardcoded in a service.

| Area | Settings |
|---|---|
| Spaced repetition | `REVISION_INTERVALS`, `REVISION_LOW_CONFIDENCE_THRESHOLD` |
| Plan size | `DAILY_DSA_COUNT_DEFAULT`/`_MAX`, `REVISION_DSA_COUNT_DEFAULT`/`_MAX` |
| Streaks | `STREAK_MIN_MINUTES`, `STREAK_MIN_ACTIVITIES` |
| Pagination | `DEFAULT_PAGE_LIMIT`, `MAX_PAGE_LIMIT` |
| Sync | `SYNC_PULL_PAGE_SIZE`, `SYNC_PULL_MAX_PAGE_SIZE`, `SYNC_MAX_MUTATIONS_PER_PUSH` |
| AI | `AI_PROVIDER`, `AI_MODEL`, `AI_API_KEY`, `AI_RATE_LIMIT_PER_HOUR`, `AI_MAX_HISTORY_MESSAGES`, `AI_TIMEOUT_SECONDS` |
| Auth | `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_JWT_AUDIENCE`, `SUPABASE_JWKS_CACHE_SECONDS` |
| Export | `EXPORT_MAX_ROWS` |

`get_settings()` is `@lru_cache`d so it's cheap to depend on, and tests clear the cache to
re-point it.

### Derived values

Computed, never duplicated: `migration_database_url` (falls back to `DATABASE_URL`),
`resolved_jwks_url`, `jwt_issuer`, `is_connectable`, and `revision_ladder_max_interval` (derived
from the ladder). `supabase_anon_key` uses `AliasChoices` so both `SUPABASE_PUBLISHABLE_KEY` and
the legacy `SUPABASE_ANON_KEY` work.

---

## 18. Deliberate non-decisions

Each of these was considered and rejected, with reasoning. Revisit them consciously.

| Not built | Why | When to revisit |
|---|---|---|
| Redis / Celery | Correctness comes from Postgres constraints, not from more infrastructure | Sustained >1000 req/s, or background work exceeding a request |
| Token refresh endpoint | Clients refresh via Supabase directly; the API stays stateless | If token handling needs to be centralised |
| Scheduler for `promote-stale` | Exposed as an endpoint so it needs no cron | Add a nightly `pg_cron` call |
| `tsvector` search | `ILIKE` is fine for a few hundred problems | Catalog > ~5k rows |
| UUID keys for the catalog | Would require rewriting every user's `problem_id` | Never within this schema |
| `create_all` in tests | Migrations are the schema of record; `create_all` would hide migration bugs | Never |
| Roles / permissions | Ownership *is* the model; cross-user access is structurally impossible | If shared/team features appear |

---

## 19. Known constraints and risks

**Highest-impact, in order:**

1. **`db.<ref>.supabase.co` is IPv6-only.** No A record. Works on IPv6-capable hosts; fails DNS on
   IPv4-only networks (some CI runners, Render's default). *Mitigation:* use the session pooler for
   `DATABASE_URL`.

2. **`%` in the database password must stay URL-encoded.** `alembic/env.py` escapes it for
   `configparser`. A future refactor that removes that `.replace("%", "%%")` breaks all migrations.

3. **`AUTOGENERATE_EXCLUDED_TABLES` is load-bearing.** Removing it lets a routine
   `--autogenerate` propose dropping `auth.users` FKs and narrowing `text` columns.

4. **The catalog has no foreign key from the user tables.** Referential integrity is
   application-enforced. Any new write path must validate the problem exists — `ProgressService`
   and `SyncService` both do.

5. **`status` on `user_problem_progress` is NOT NULL with a default only since `0003`.** A database
   restored from a pre-`0003` dump will fail partial upserts. Verify
   `alembic_version = 0003_progress_status_default`.

6. **Models declare narrower types than the live `text` columns.** Harmless (narrower is never
   emitted) but the drift report lists 9 cases. Widening a declaration is the only thing that would
   matter.

7. **`design_topics` is retained but unread.** Intentional, so no data is destroyed.
   `backfill_design_topics.py` copies it across on demand.

8. **RLS is enabled but unpolicied.** Inert while the app uses a privileged role.

9. **`ai_auto_reveal_solution` is stored but not enforced server-side.** Honoured by the client.

10. **Rate limiting is per-user per-hour in Postgres.** A high-volume deployment would want Redis.

---

## 20. Extension guide

### Adding an endpoint

1. **Schema** — add request/response models in `app/schemas/<domain>.py`. Catalog rows keyed by
   slug must extend `CatalogModel`, not `TimestampedModel` (whose `id` is a `UUID`).
2. **Repository** — add the query in `app/repositories/<domain>.py`, always taking `user_id`.
3. **Service** — add the decision in `app/services/<domain>.py`, and commit if it writes.
4. **Router** — add the route, `response_model`, and a docstring description.
5. **Test** — add a test in `tests/test_<domain>.py`. Add an isolation test if it touches user
   data.

### Adding a table

1. Model in `app/db/models/<group>.py`, registered in `models/__init__.py`.
2. `alembic revision --autogenerate -m "..."` — **read the generated file**. Confirm it only
   creates; the guard blocks drops, but review anyway.
3. If it's a reused/pre-existing table, add it to `AUTOGENERATE_EXCLUDED_TABLES`.
4. If it has a NOT NULL column without a default, add one now or partial upserts will fail.
5. `python -m scripts.validate_models`, then `alembic upgrade head`.
6. Add the table to `ALL_TABLES` in `tests/conftest.py` if it should be truncated between runs.

### Adding a sync entity

1. Add the value to `SyncEntity`.
2. Add a handler to `_handlers()`.
3. Handle **delete** in `_apply_delete` — soft delete, so other devices learn about it.
4. Add the entity to the parametrised coverage test in `test_sync.py`.

### Adding an AI provider

Implement the `AIProvider` Protocol (`name`, `chat`), add a branch to `build_provider`, and set
`AI_PROVIDER`. Keep it off the critical path — startup must not fail if it's unconfigured.

### Changing the scheduler

Change the weights, then **bump `SCHEDULER_VERSION`**. It's stored on every plan as
`generated_by`, so existing plans remain attributable to the algorithm that produced them.
`test_units.py` pins determinism; keep it passing.

### Changing the revision ladder

Edit `REVISION_INTERVALS` — it's configuration. `revision_ladder_max_interval` re-derives
automatically. Do **not** hardcode a ladder in a service.

---

## Appendix: file map for orientation

| Concern | File |
|---|---|
| App factory, lifespan, health | `app/main.py` |
| All tunables | `app/core/config.py` |
| Token verification | `app/core/security.py` |
| JWKS over httpx | `app/core/jwks.py` |
| Error envelope and mapping | `app/api/error_handlers.py` |
| Identity, pagination deps | `app/api/deps.py` |
| Upsert + NOT NULL defaults | `app/utils/upsert.py` |
| The scheduler | `app/services/daily_plan_scheduler.py` |
| Plan generation and persistence | `app/services/daily_plan_service.py` |
| Spaced repetition | `app/services/revision_policy.py` |
| Offline sync | `app/services/sync_service.py` |
| Streaks | `app/services/streak_service.py` |
| Existing-schema adaptation | `alembic/versions/0001_existing_schema_adaptation.py` |
| Migration safety guards | `alembic/env.py` |
| Test harness | `tests/conftest.py` |
| Legacy schema fixture | `tests/fixtures/legacy_schema.sql` |
