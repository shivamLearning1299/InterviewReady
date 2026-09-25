# InterviewReady — Desktop ↔ iOS integration analysis

**Scope.** Two codebases, one database, one backend server.

| | Desktop project | iOS project |
|---|---|---|
| Path | `~/Desktop/interviewready` | `~/interviewready` |
| Role | FastAPI backend + React/Vite web frontend | SwiftUI + SwiftData app |
| Supabase project | `qkuxfobfqioilwbjpvyf` | `qkuxfobfqioilwbjpvyf` (same) |
| Write path today | FastAPI → Postgres (privileged role) | supabase-swift → PostgREST (anon key + RLS) |

**Headline:** they already share one database and one Supabase project — but they write to it through
two completely different protocols, and they disagree about identity, conflict resolution, table
layout, and enum vocabulary. Nothing is broken *yet* only because the database is essentially empty
(`dsa_problems` = 90 seeded rows; `user_problem_progress` = 1 row; `design_topics` = 0 rows).

Evidence: `backend/schema_report.md`, `backend/schema_snapshot.json`, `backend/app/db/models/*`,
`interviewready/InterviewReady/**`.

---

## 1. Verified divergences

### 1.1 Enum vocabulary — iOS writes statuses the backend cannot parse
`AppModels.swift` declares `ProblemStatus` as `notStarted, attempted, solved, needsRevision, mastered`
and writes `progress.status = status.rawValue` straight to Postgres.

The backend's vocabulary (`core/constants.py`) is `not_started, attempted, solved, needs_revision, mastered`.

Postgres will **not** stop this: `user_problem_progress` is a pre-existing table, and although the ORM
declares `CheckConstraint("status IN (...)")`, no migration ever created it — `schema_snapshot.json`
shows `ck_*_status_valid` exists only on the *new* `lld_progress` / `hld_progress` tables. So iOS's
`notStarted` / `needsRevision` are stored happily, then `ProblemStatus("notStarted")` raises on the
server and the rows are invisible to stats, streaks and the scheduler. A silent data-quality failure,
not a loud one — the worst kind.

### 1.2 Conflict key mismatch — the same row is identified differently
| | Backend | iOS |
|---|---|---|
| Conflict target | `unique(user_id, problem_id)` | primary key `id` |
| `id` origin | `gen_random_uuid()` | client `UUID()` per device |

iOS calls `.upsert(RemoteProgress(...))` with **no** `onConflict`, so PostgREST conflicts on `id`.
The live table carries `UNIQUE (user_id, problem_id)` (confirmed in the snapshot). Two devices each
creating progress for `two-sum` therefore produce different `id`s and collide on that unique
constraint — or, if the constraint were absent, silently create duplicate progress rows.

### 1.3 Clock authority — last-write-wins on an untrusted clock
iOS resolves conflicts with `remoteRow.updatedAt > row.updatedAt`, where `updatedAt` is the device's
clock. The backend deliberately never trusts a device clock (server-authoritative `updated_at`,
and a `bigint` identity cursor precisely because timestamps are unreliable). A device with a fast
clock wins every conflict permanently.

### 1.4 No optimistic concurrency on iOS
The backend's entire sync contract is `base_version` → integer `version` bumped on every write.
No iOS model has a `version` field, and no iOS DTO sends `base_version`.

### 1.5 LLD/HLD: the wrong table entirely
* **iOS** keeps all design work in `design_topics` — one table with an `area` column (`dsa`/`lld`/`hld`),
  keyed by locally-invented `UUID()`s, seeded from its own hardcoded title lists ("OOP", "SOLID",
  "Parking Lot", …).
* **Backend** splits this into `lld_topics` + `hld_topics` (UUID PKs, unique `slug`, seeded from
  `app/seed_data/*.json`, 20 + 20 topics) plus `lld_progress`/`lld_notes`/`hld_progress`/`hld_notes`
  keyed by `(user_id, lld_topic_id)`.

`design_topics` is still physical but the backend ORM does not map it — `schema_report.md` lists it
under "tables in the database that the ORM does not map: *leave in place; do not drop*". So every LLD
and HLD note, status and revision date the iOS app records is **write-only**: invisible to the web UI,
to stats, and to the backend forever.

### 1.6 Column names diverge within the same database
| Concept | `user_problem_progress` (pre-existing) | `lld_progress`/`hld_progress` (new) |
|---|---|---|
| last reviewed | `last_reviewed_date` | `last_reviewed_at` |
| next revision | `next_revision_date` | `next_revision_at` |

iOS wrote `last_reviewed_date`/`next_revision_date` into `design_topics`, mirroring the DSA naming.
The backend's own bug list records this exact confusion as bug #10 ("Topic progress wrote
`last_reviewed_date` — LLD/HLD use `last_reviewed_at`").

### 1.7 `daily_plans`: two schedulers, one row per day
Both write `daily_plans`, which is `unique(user_id, date_key)` — so they will overwrite each other
once per day.

| | Backend | iOS |
|---|---|---|
| Computed | server-side (`DailyPlanScheduler`) | on-device (`DailyPlanService.makePlan`) |
| Tie-break | deterministic BLAKE2b of `user_id:plan_date:problem_id` | ordering only |
| Guarantee | generate-once-per-day, committed | insert-if-absent, race-prone |
| Extra columns | `status`, `timezone`, `generated_by`, `version`, `created_at`, `deleted_at` | none of these |
| Child rows | normalized `daily_plan_items` (type, position, completion, reason, score) | none |
| LLD/HLD refs | FK to `lld_topics`/`hld_topics` | its own `DesignTopic` UUIDs → reference nothing |

### 1.8 Two different spaced-repetition ladders
* iOS: `confidence <= 2 → 1 day · confidence == 3 → 3 days · else → 7 days`.
* Backend: configurable per-confidence ladder in `REVISION_INTERVALS_JSON`
  (e.g. confidence 3 → `[3, 7, 16, 35]` indexed by completed revisions, clamped at the top).

Same review, two different `next_revision_date` values, each writer overwriting the other.

### 1.9 `code_snippets` rows iOS inserts are invisible to the backend
Migration `0001` added `context_type` (default `'dsa'`), `context_id` (default `''`), `title`,
`is_primary`, and backfilled existing rows so `context_id = problem_id`. iOS posts only
`problem_id / language / code / updated_at`, so its new rows land with `context_id = ''` and are
skipped by every backend snippet endpoint, which queries by context.

### 1.10 Catalog mismatch — 5 of the 8 iOS problems do not exist server-side
`dsa_problems.id` is the **slug** (TEXT), seeded with 90 rows. Three iOS ids match; five do not:

| iOS `problem.id` | In backend catalog? | Likely intended |
|---|---|---|
| `two-sum`, `valid-anagram`, `valid-parentheses` | yes | — |
| `best-time-stock` | no | `best-time-to-buy-and-sell-stock` |
| `binary-search` | no | *(no match found)* |
| `subarray-sum` | no | `subarray-sum-equals-k` |
| `next-greater` | no | *(no match found)* |
| `islands` | no | `number-of-islands` |

Every progress/note/snippet row iOS writes against those five becomes an orphan the backend cannot
join to a problem.

### 1.11 iOS implements 5 of the backend's 11 sync entities
Backend sync entities: `problem_progress`, `problem_attempt`, `problem_notes`, `code_snippet`,
`revision`, `lld_progress`, `lld_notes`, `hld_progress`, `hld_notes`, `study_session`, `user_settings`.
iOS writes: progress, notes, snippets, study sessions — plus `design_topics`, which is not an entity.

Never written by iOS: the **entire revision queue**, `problem_attempts` (iOS keeps only an integer
counter), all four LLD/HLD entities, and `user_settings`.

### 1.12 Streaks computed two different ways
* iOS: client-side, from `solvedDate` values, requiring a *solved* problem on each consecutive day.
* Backend: materialized `user_activity_days`, any qualifying activity, configurable minimum, plus a
  "yesterday still counts" rule.

### 1.13 No device registration or cursor
`user_devices` tracks `device_identifier` + `last_pull_cursor` so a client can skip echoing its own
writes and resume an interrupted pull. iOS has no device id at all (only the *web* client persists
`ir-device-id`). The backend therefore cannot distinguish iOS devices.

### 1.14 AI tutor contract differs
| | Request | Response |
|---|---|---|
| iOS | `POST {AI_BACKEND_URL}/api/chat` — `{question, topic, notes, code}` | `{"message": "..."}` |
| Backend | `POST /api/v1/ai/chat` — `{context_type, context_id, message, action, selected_code, conversation_id, include_history}` | `{conversation_id, message:{role, content, …}, context_used, is_new_conversation}` |

`AI_BACKEND_URL` is empty in `Secrets.xcconfig`, so the tutor is currently disabled on iOS.

---

## 2. What is already compatible (good news)

* **Same Supabase project** — auth users are shared today.
* **Auth token is reusable.** The backend verifies Supabase JWTs against the project JWKS and requires
  `aud = authenticated`, rejecting all `HS*`. supabase-swift 2.55.2 `signIn(email:password:)` yields
  exactly that. iOS can send its existing access token to FastAPI **unchanged** — no new auth flow.
* `Difficulty` (`easy|medium|hard`) and `StudyArea` (`dsa|lld|hld`) already match backend vocabulary.
* `user_problem_progress.confidence` (0–5, default 3) and `attempts` agree.
* `problem_notes` columns match the backend exactly (`approach`, `notes`, `time_complexity`,
  `space_complexity`, `mistakes`, `revision_notes`).
* Every pre-existing table still has `user_id` FK → `auth.users` intact, and the catalog PK was chosen
  as TEXT specifically so `problem_id text` columns join without rewriting rows.

---

## 3. Recommended integration path

**Phase 0 — decide the ownership rule (blocks everything).** For each table, exactly one component
owns writes. The natural split: backend owns `daily_plans`, `revision_queue`, `user_activity_days`,
`lld_*`/`hld_*`; clients own their own notes/snippets/progress via the sync API. Without this, two
schedulers keep fighting over one row per day.

**Phase 1 — stop the bleeding (small, high value).**
1. Map iOS statuses to the backend vocabulary (`notStarted → not_started`, `needsRevision → needs_revision`).
2. Point the 5 mismatched problem ids at real slugs.
3. Add `context_id` (= `problem_id`) and `context_type='dsa'` to the iOS snippet DTO.

**Phase 2 — move iOS writes behind FastAPI.** Replace the direct PostgREST repositories
(`SupabaseProgressRepository`, `SupabaseDesignRepository`, `SupabaseSupplementalRepository`) with a
REST client against `/api/v1`:
* `POST /sync/push` with a client-generated `mutation_id` per change → replaces per-row upsert, and
  gives idempotent replay for free.
* `GET /sync/pull?cursor=…` with a stored `next_cursor` → replaces the full-table select + timestamp diff.
* `GET /sync/status` + `POST` device registration (`user_devices`) → gives the client an identity.
* Send `base_version` on updates and honour `conflict` results (`server_record` is returned to merge).

**Phase 3 — migrate design topics.** Map iOS `DesignTopic` → `lld_progress`/`lld_notes` +
`hld_progress`/`hld_notes`, matching topics by **slug**, not by client UUID. Requires a one-time
backfill from `design_topics` (the backend ships `scripts/backfill_design_topics.py`). The iOS local
title lists should be replaced by the seeded catalog (`lld_topics.json` / `hld_topics.json`).

**Phase 4 — delete the duplication.** Once the backend owns plan generation, revision intervals and
streaks, remove `DailyPlanService.makePlan`, the local `revisionDate(for:)` ladder, and the client-side
streak computation so there is one source of truth.

---

## 4. Open decisions for you

1. Does iOS become a thin client of FastAPI (recommended), or do both keep writing directly and we
   add DB-level triggers to reconcile? The former removes ~1.5k lines of duplicated logic.
2. Offline-first is a stated goal — confirm iOS adopts `/sync/push` + `/sync/pull` rather than
   direct PostgREST, since RLS-based direct writes cannot express idempotency or cursors.
3. Is the existing `user_problem_progress` row (and the legacy `design_topics` data) still wanted, or
   can it be discarded? This changes whether Phase 3 needs a backfill at all.
4. Should the CHECK constraints the ORM declares on the five adapted tables actually be created, so
   bad enum values fail loudly at the database instead of silently?
