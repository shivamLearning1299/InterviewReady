# Agent 2 — Backend audit (Phase 1)

Project: `~/Desktop/interviewready/backend` — FastAPI 1.0.0, Python 3.12, SQLAlchemy 2.0
async, asyncpg, Alembic. 26 public tables (6 pre-existing + 20 added), 3 migrations.

## 1. Existing — working

### Routers and services (do not recreate)

| Router file | Prefix | Service | Repository |
|---|---|---|---|
| `users.py` | — | `UserService` | `repositories/user.py` |
| `today.py` | — | `DailyPlanService`, `DailyPlanScheduler` | `repositories/planning.py` |
| `dsa.py` | `/dsa` | `DSAService` | `repositories/dsa.py`, `repositories/catalog.py` |
| `revisions.py` | `/revisions` | `RevisionService`, `RevisionPolicy` | `repositories/planning.py` |
| `lld.py` | `/lld` | `TopicService` | `repositories/topics.py` |
| `hld.py` | `/hld` | `TopicService` | `repositories/topics.py` |
| `study_sessions.py` | `/study-sessions` | `StudySessionService` | `repositories/activity.py` |
| `stats.py` | `/stats` | `StatsService`, `StreakService` | `repositories/stats.py` |
| `sync.py` | `/sync` | `SyncService` | `repositories/sync.py`, `repositories/devices.py` |
| `ai.py` | `/ai` | `AITutorService` + `services/ai/*` | `repositories/ai.py` |
| `settings.py` | `/settings` | `UserService` | `repositories/user.py` |

Layering is already `Router → Service → Repository → PostgreSQL`. Routers parse and shape;
they hold no business logic. Services are injected per-request via
`app/api/v1/services.py` + `dependencies.py`. Every personal endpoint derives the user id
from the verified token.

### Authentication — complete, correct, do not touch

`SupabaseTokenVerifier` (`app/core/security.py`) validates Supabase access tokens against the
project JWKS. `app/core/jwks.py` implements a JWKS client over **httpx** rather than PyJWT's
`PyJWKClient`, because the latter uses `urllib` and fails with `CERTIFICATE_VERIFY_FAILED`
on macOS (incomplete system cert store). It has a TTL cache, refetch-on-unknown-key,
stale-serve during an outage, and **explicitly rejects all `HS*` algorithms**.

→ This is the reason iOS can send its existing Supabase token to FastAPI unchanged.

### Sync protocol — complete and correct

`POST /api/v1/sync/push`, `GET /api/v1/sync/pull`, `GET /api/v1/sync/status`.

* `mutation_id` idempotency via `unique(user_id, mutation_id)` in `sync_mutations`.
* Cursor is `sync_changes.seq` — a `BIGINT IDENTITY`, not a timestamp, so same-millisecond
  changes stay distinct and deletions are representable.
* Per-mutation savepoints: one bad record cannot roll back the batch.
* `IntegrityError` is split into *unique violation* (→ `skipped_duplicate`) and everything
  else (→ `rejected`). A NOT NULL/CHECK violation must never be reported as a duplicate.
* 11 entity handlers: `problem_progress`, `problem_attempt`, `problem_notes`, `code_snippet`,
  `revision`, `lld_progress`, `lld_notes`, `hld_progress`, `hld_notes`, `study_session`,
  `user_settings`.

### Idempotent writes

`app/utils/upsert.py` builds `INSERT ... ON CONFLICT DO UPDATE`, bumps `version`, refreshes
`updated_at`, and injects server defaults **for the insert path only** (writing an injected
default into `DO UPDATE` would reset stored values).

### Tests

285 tests across 10 modules in `tests/`.

## 2. Broken / latent

Verified against `schema_report.md` and `schema_snapshot.json`:

1. **The ORM declares CHECK constraints on adapted tables that no migration ever created.**
   `user_problem_progress` declares `status_valid` and `confidence_range`;
   `code_snippets` declares `context_type_valid` and `language_valid`; `study_sessions`
   declares `session_type_valid`. `schema_snapshot.json` shows `status_valid` exists **only**
   on `ck_lld_progress_status_valid` and `ck_hld_progress_status_valid`. Consequence: an
   invalid enum value from a direct-writing client is stored silently instead of failing
   loudly. This is the mechanism behind the iOS `"notStarted"` bug.
2. **`user_problem_progress.problem_id` has no CHECK against the catalog.** The model comment
   says "the service layer validates ids against the catalog on write instead". Confirm that
   is actually enforced on every write path, including sync entity handlers.
3. **`design_topics` is unmapped but live.** `schema_report.md`: *"tables in the database that
   the ORM does not map: `design_topics` (leave in place; do not drop)"*. iOS still writes it.
4. **`GET /api/v1/ai/actions` returns a menu, not action objects.** The frontend contract in
   the brief expects `POST /api/v1/ai/actions/{id}/execute` and `/reject`. Neither exists.
5. **No streaming endpoint.** `POST /api/v1/ai/chat/stream` does not exist.
6. **`AI_PROVIDER` defaults to `gemini`, `AI_MODEL=gemini-2.0-flash`, `AI_API_KEY` empty** in
   `.env.example`. Tutor returns 503 when unconfigured — by design, non-fatal.
7. **`promote-stale` is request-triggered, not scheduled.** Documented limitation; a nightly
   `pg_cron` call is the natural next step.

## 3. Old architecture to remove

* Nothing in the backend itself. The legacy surface is **client-side**: iOS writes directly to
  Postgres via PostgREST, and the web client can run in a mock mode that is not the backend.
* `design_topics` must be drained by a backfill before it can be retired
  (`scripts/backfill_design_topics.py` exists).

## 4. Missing (required by the frozen contract)

| Need | Status |
|---|---|
| `POST /api/v1/ai/chat/stream` (SSE) | **must add** |
| `POST /api/v1/ai/actions/{id}/execute` | **must add** |
| `POST /api/v1/ai/actions/{id}/reject` | **must add** |
| `knowledge_chunks` table + pgvector | **must add** |
| `EmbeddingProvider` abstraction | **must add** |
| `RetrievalService` (hybrid RRF) | **must add** |
| `ContextBuilder` (PageContext assembly) | **must add** |
| `TutorActionService` (validate → authorize → apply) | **must add** |
| `conversation_summary` on `ai_conversations` | **must add** (additive column) |
| `page_context` + `actions` on `ai_messages` | **must add** (additive columns) |

Everything else in the brief's target contract already exists. See `04-contract-openapi.md`
for the line-by-line mapping — notably `PUT` is already used for progress/notes (the brief
writes `PUT` for some and `PATCH` for none; the existing verbs are preserved).

## 5. Needs migration

* Additive migration `0004`: `knowledge_chunks` + `vector` extension + indexes; additive
  columns on `ai_conversations` / `ai_messages`.
* Decide whether to finally **create the declared CHECK constraints** on the five adapted
  tables (see §2.1). Recommended: yes, after the iOS enum fix lands, so the database starts
  rejecting divergence instead of accepting it.

## 6. Data-safety rules for this agent

* Migrations are additive and guarded; `EXCLUDED_SCHEMAS` protects `auth`/`storage`/etc.;
  `AUTOGENERATE_EXCLUDED_TABLES` prevents autogenerate from dropping the `auth.users` FKs.
* A verified backup precedes every migration
  (`scripts/backup_public_schema.py`, proven restorable with `ON_ERROR_STOP=1`).
* Live state: revision `0003`, zero drift, 90 DSA / 20 LLD / 20 HLD seeded, 6/6 `auth.users`
  FKs intact.
