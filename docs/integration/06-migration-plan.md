# Migration plan (all agents) — Phases 3 to 7

Priority order, per the brief: **(1)** compatibility with working code, **(2)** one shared API
contract, **(3)** user-data safety, **(4)** web/iOS sync, **(5)** AI quality, **(6)** offline
reliability, **(7)** maintainability, **(8)** performance.

Status: Phases 1–2 complete. Phases 3–7 not started.

### Alembic revision chain (applied order — source of truth: `backend/alembic/versions/`)

| Revision | File | Contents | State |
|---|---|---|---|
| `0001_existing_schema_adaptation` | `0001_existing_schema_adaptation.py` | Baseline: additive adaptation of the pre-existing Supabase schema | applied |
| `0002_new_tables` | `0002_new_tables_..._topics_and_analytics_.py` | New tables for planning, sync, AI, topics and analytics | applied |
| `0003_progress_status_default` | `0003_progress_status_default.py` | Default for `user_problem_progress.status` | applied |
| `0004_progress_check_constraints` | `0004_progress_check_constraints.py` | The two missing `user_problem_progress` CHECK constraints (+ data repair) — see §3.5 | **exists, verified on real Postgres** |
| `0005_ai_context_id_text` | `0005_ai_context_id_text.py` | Widen `ai_conversations.context_id` `uuid → text` for the DSA slug path | **exists** |

The chain is linear: `0001 → 0002 → 0003 → 0004_progress_check_constraints → 0005_ai_context_id_text`
(`0005` sets `down_revision = "0004_progress_check_constraints"`).

**Naming collision to resolve before the AI/RAG work.** The AI/RAG migration planned in §3.1 and
CN-004 is *also* referred to as "migration 0004" in this document and in `09-ai-implementation-spec.md`.
The identifier `0004` is now taken by `0004_progress_check_constraints`, so the AI/RAG migration must
be re-numbered to **`0006`** (or later) when it is written, and its `down_revision` set to
`0005_ai_context_id_text`. No AI/RAG migration file exists today.

---

## Phase 3 — Backend stabilization (Agent 2)

### 3.1 Additive migration (planned as `0006`; was mis-numbered `0004`) — AI/RAG foundation
* `CREATE EXTENSION IF NOT EXISTS vector`
* `knowledge_chunks` per `05-contract-ai.md` §6, with the dedupe unique index.
* Additive columns: `ai_conversations.conversation_summary text`,
  `ai_messages.page_context jsonb`, `ai_messages.actions jsonb`,
  plus `ai_tutor_actions` (id, user_id, conversation_id, message_id, type, target jsonb,
  value text, status, applied_at, created_at) for the action lifecycle.
* Guarded and reversible, backed up first via `scripts/backup_public_schema.py`.

**Data safety:** additive only. No column dropped, no row rewritten.

### 3.2 New services
`ContextBuilder`, `EmbeddingProvider` (protocol) + `GeminiEmbeddingProvider`,
`ChunkingService`, `RetrievalService` (hybrid RRF), `TutorActionService`, `KnowledgeIndexService`.

### 3.3 New routes
`POST /ai/chat/stream`, `POST /ai/actions/{id}/execute`, `POST /ai/actions/{id}/reject`.
Additive `page_context` on the chat request and `actions` on the chat response.

### 3.4 Tests to add
* Embedding provider batching + `content_hash` short-circuit (no re-embed when unchanged).
* Chunking: structured fields produce separate chunks; prose gets overlap; structured fields do not.
* Retrieval: RRF ordering, and **user isolation** — user A never retrieves user B's vectors.
* Action safety: cross-user target rejected, non-editable field rejected, unknown action type
  rejected, invalid enum value rejected, stale `version` rejected.
* Streaming: terminates with exactly one `done`/`error`.

### 3.5 CHECK constraints — DONE and verified (was "deferred/blocked")
The declared-but-missing CHECK constraints on `user_problem_progress` are **no longer deferred
and no longer blocked**. Migration **`0004_progress_check_constraints`** creates them, and it has
been run and verified against a **real Postgres** instance:

* `ck_user_problem_progress_status_valid` — `status IN ('not_started','attempted','solved',
  'needs_revision','mastered')`, exactly the predicate and name `app/db/models/dsa.py` declares
  (created through `op.f()` so the metadata naming convention is not applied twice).
* `ck_user_problem_progress_confidence_range` — `confidence BETWEEN 0 AND 5`.

The migration first repairs pre-existing data (`notStarted → not_started`,
`needsRevision → needs_revision`, anything else off-vocabulary → `not_started`, confidence
clamped to 0–5), so the `ALTER TABLE` cannot fail on rows already written by the old iOS client.
This resolves the self-contradiction between §3.0 (which ordered the constraint created) and the
previous text here (which called it deferred/blocked): §3.0 was right, and 0004 delivers it.

**The ordering caveat still stands.** 0004 must be applied to a LIVE database only *after* every
writing client has been corrected to emit the canonical enum values (Phase 3.0 item 1, the iOS
`ProblemStatus` raw-value change). Applied while a client still writes `"notStarted"`, the
constraint turns currently-succeeding writes into production `IntegrityError`s instead of client
validation messages. The data repair inside 0004 makes *existing* rows valid; only client
behaviour keeps new rows valid.

---

## Phase 3.0 — Stop the silent corruption (Agent 1 + Agent 2, do this FIRST)

This is the only work that touches live user data correctness, so it precedes everything else.
All three items are small.

1. **Enum raw values** (`02-audit-ios.md` §6). Today iOS writes `"notStarted"` /
   `"needsRevision"` and Postgres accepts them because the CHECK constraint was never created.
   Then fix the backend: create `ck_user_problem_progress_status_valid` so it can never
   recur.
2. **Five catalog ids** → real slugs. `best-time-stock` → `best-time-to-buy-and-sell-stock`,
   `subarray-sum` → `subarray-sum-equals-k`, `islands` → `number-of-islands`.
   `binary-search` and `next-greater` have **no** catalog match — decide whether to add them to
   `app/seed_data/dsa_problems.json` or drop them from the iOS starter catalog.
3. **`context_type` / `context_id`** on iOS snippet writes, so new rows are not orphaned.

Existing rows already written with wrong enum values must be repaired by a one-off mapping
(`notStarted → not_started`, `needsRevision → needs_revision`). Confirm the current count first —
`user_problem_progress` held 1 row at last inspection.

---

## Phase 4 — React integration (Agent 3)

1. Generate TypeScript API types from `/openapi.json`; assert `contract.ts` against them in CI
   (fixes the drift risk in `03-audit-react.md` §4.3).
2. Verify the backend enforces `user_settings.timezone` over the `X-Timezone` header.
3. Build the `PageContext` builder: one function per `page_type`, reading unsaved drafts from
   component state (never from the server).
4. Wire `actions` from the chat response into an Apply/Dismiss UI.
5. Add a diff view for `update_code` / large `set_field` changes. Never auto-overwrite code.
6. Consume `/ai/chat/stream` via SSE.
7. Remove any remaining locally-derived business values; keep only presentation.

---

## Phase 5 — AI foundation (Agent 4)

Reference client is the **website**.

1. `GeminiEmbeddingProvider` (`gemini-embedding-2`, 768).
2. `ChunkingService` — structure-aware for LLD/HLD fields; prose rules for notes.
3. `KnowledgeIndexService` — seed global curriculum (`user_id = NULL`) for `dsa_problems`,
   `lld_topics`, `hld_topics`; index personal notes/snippets on write via `content_hash`.
4. `RetrievalService` — pgvector + FTS → RRF → metadata filter → top 5–8.
5. `ContextBuilder` — the five-part assembly in `05-contract-ai.md` §8.
6. Conversation summary maintenance.
7. `TutorActionService` + the three action routes.
8. Streaming endpoint.

Acceptance: brief scenarios 1, 2, 5, 6, 7.

---

## Phase 6 — iOS migration (Agent 1)

**Do not rewrite UI.** Insert the abstraction layer underneath it.

```
Existing SwiftUI  →  Repository  →  APIClient  →  FastAPI  →  Supabase
        ↕
     SwiftData (offline cache)
```

1. `Networking/APIClient.swift` — URLSession + async/await, bearer token from `AuthService`,
   snake_case↔camelCase decoding, `APIError` mapped from the backend error envelope.
2. Repositories: `DSARepository`, `DesignRepository`, `ProgressRepository`, `SyncRepository`.
3. Delete `SupabaseProgressRepository`, `SupabaseDesignRepository`,
   `SupabaseSupplementalRepository` and the five hand-written `Remote*` DTOs.
4. Replace the select-everything sync with a mutation queue:
   * client-generated `mutation_id` per queued change,
   * stored `lastPullCursor`, `deviceIdentifier`, `device_type = "ios"`,
   * `POST /sync/push` then `GET /sync/pull` until `has_more == false`,
   * `base_version` on updates, handle `conflict` via `server_record`.
5. Add `version` to local models so `base_version` can be sent.
6. Migrate `DesignTopic` → `lld_progress`/`lld_notes` + `hld_progress`/`hld_notes`, matching by
   **slug**. Requires the `design_topics` backfill (`scripts/backfill_design_topics.py`).
7. Delete `DailyPlanService`, `revisionDate(for:)`, `currentStreak`, client-side stats; read
   `/today`, `/revisions`, `/stats/*`. Remove the hardcoded `3` and `400`.
8. Replace hardcoded seed lists with the server catalog.

**Offline must not regress:** view downloaded DSA, write code, write notes, change progress,
study LLD/HLD with no network — all queued.

---

## Phase 7 — iOS AI (Agent 1)

Only after web AI behaviour is stable, using the **exact same** contract.

1. `AI/PageContext.swift`, `AI/TutorAction.swift`, `AI/TutorResponse.swift` — mirror
   `05-contract-ai.md` exactly, JSON-compatible.
2. `Services/AI/AITutorService.swift`, `AIStreamClient.swift` (URLSession byte stream over SSE).
3. Apply/Dismiss UI; `UISheetPresentationController`-style diff for code changes.
4. Replace the current tutor call: `POST {AI_BACKEND_URL}/api/chat` with
   `{question, topic, notes, code}` → `{"message": "…"}` becomes
   `POST /api/v1/ai/chat` with the full request shape. `AI_BACKEND_URL` is currently empty in
   `Secrets.xcconfig`, so the tutor is disabled — it should point at the FastAPI base URL.

Acceptance: brief scenarios 3, 4, plus 1/2/5/6/7 repeated from iOS.

---

## Critical integration tests (system level)

| # | Scenario | Owner |
|---|---|---|
| 1 | Web: unsaved Python code on Subarray Sum Equals K → "Why is my approach wrong?" → AI receives the unsaved code | 3 + 4 |
| 2 | "Add this explanation to mistakes." → `append_field → mistakes` → Apply → persisted | 3 + 4 |
| 3 | Open iOS later → updated mistakes appear via sync | 1 |
| 4 | iOS offline: write notes + change status → reconnect → syncs → website reflects | 1 |
| 5 | "Have I made this DFS mistake before?" → pgvector + FTS retrieves personal history | 4 |
| 6 | HLD Notification System → "What am I missing?" → AI identifies missing `failure_handling` | 4 |
| 7 | "Add retry strategy and DLQ under failure handling." → action targets `hld.failure_handling` | 4 |

Scenario 4 is the highest-risk one: it depends on Phase 6 step 4 (the mutation queue) and on
`lld_*`/`hld_*` being live, so it cannot pass before step 6.

---

## Performance guardrails

* No N+1 queries; statistics stay SQL-side (they already are).
* Never load a whole chat history — summary + last 8–12.
* Never send all vectors to the LLM — top 5–8 chunks only.
* `content_hash` prevents re-embedding unchanged content.
* No client polling: sync on launch, on reconnect, and after a mutation batch.
* 768-dim vectors and semantic content only, to respect Supabase Free storage.

---

## Contract change notes (required by `00-README.md`)

### CN-001 — `page_context` added to the AI chat request
```
WHAT CHANGED   POST /ai/chat accepts a new optional "page_context" object.
WHY            The tutor must see unsaved drafts, selected text and focused field.
BACKWARD COMPATIBLE?   yes — optional field, absent means today's behaviour.
AFFECTED CLIENTS       React, iOS, AI, backend
REQUIRED MIGRATION     none for clients; backend ignores it until Phase 5.
```

### CN-002 — `actions` added to the AI chat response
```
WHAT CHANGED   POST /ai/chat returns a new "actions": [] array of TutorActions.
WHY            The tutor proposes edits the user applies explicitly.
BACKWARD COMPATIBLE?   yes — additive; an empty array when nothing is proposed.
AFFECTED CLIENTS       React, iOS, AI, backend
REQUIRED MIGRATION     none; clients may ignore until they render Apply/Dismiss.
```

### CN-003 — three new AI endpoints
```
WHAT CHANGED   POST /ai/chat/stream, POST /ai/actions/{id}/execute,
               POST /ai/actions/{id}/reject.
WHY            Streaming, and a safe human-in-the-loop apply step for AI edits.
BACKWARD COMPATIBLE?   yes — pure additions.
AFFECTED CLIENTS       React, iOS, AI, backend
REQUIRED MIGRATION     none.
```

### CN-004 — `knowledge_chunks` table + pgvector
```
WHAT CHANGED   New table knowledge_chunks with vector(768); new migration (re-numbered
               0006 — the id 0004 is taken by 0004_progress_check_constraints; see the
               revision chain above).
WHY            Hybrid retrieval for the contextual tutor.
BACKWARD COMPATIBLE?   yes — additive table, no existing table altered.
AFFECTED CLIENTS       backend, AI
REQUIRED MIGRATION     alembic upgrade head; then index the global curriculum.
```

### CN-005 — iOS enum raw values corrected (breaking on the wire)
```
WHAT CHANGED   iOS ProblemStatus raw values become not_started / needs_revision
               (were notStarted / needsRevision). New DesignStatus enum added.
WHY            Match the frozen shared enum vocabulary; existing values are corrupt
               in the database today.
BACKWARD COMPATIBLE?   no — this is a deliberate wire-value change on the client.
AFFECTED CLIENTS       iOS (producer), backend (consumer), React (reader)
REQUIRED MIGRATION     One-off UPDATE mapping notStarted→not_started and
               needsRevision→needs_revision on user_problem_progress (and any
               design_topics rows). The constraint that prevents recurrence now exists:
               migration 0004_progress_check_constraints creates
               ck_user_problem_progress_status_valid (and
               ck_user_problem_progress_confidence_range) and performs the same data repair.
               Correct the clients BEFORE applying 0004 to a live database — see §3.5.
```

### CN-006 — iOS stops writing to Postgres directly
```
WHAT CHANGED   iOS all application data flows through FastAPI. design_topics is retired
               in favour of lld_*/hld_* entities.
WHY            FastAPI is the authoritative application layer; two write paths caused
               the divergence catalogued in 07-gap-analysis.md.
BACKWARD COMPATIBLE?   yes for the database — RLS and the existing tables stay in place.
AFFECTED CLIENTS       iOS, React, backend
REQUIRED MIGRATION     Backfill design_topics → lld_*/hld_* matched by slug, then stop
               writing design_topics. Keep the legacy physical table (do not drop).
```

---

## Deployment: connection strings (verified 2026-09-26)

**The direct database host is IPv6-only.** `dig db.<ref>.supabase.co A` returns *nothing*;
`AAAA` returns `2406:da12:...`. Render's default networking is IPv4-only, so a deploy
configured against the direct host cannot resolve it — it fails outright rather than
degrading, and the failure appears only at deploy time.

Both variables must therefore use the pooler (Supabase dashboard > Connect > Session pooler):

```
DATABASE_URL        -> aws-0-<region>.pooler.supabase.com:6543   (transaction mode: the app)
DATABASE_URL_DIRECT -> aws-0-<region>.pooler.supabase.com:5432   (session mode: migrations)
```

Notes:

* The pooler username is `postgres.<project-ref>` — with the dot. Plain `postgres` is rejected.
* Session mode (5432) supports DDL, so migrations work through it.
* **The region must be confirmed in the dashboard.** It cannot be inferred reliably from the
  direct host's AAAA address, and a wrong region fails as a connection error that looks like
  a credentials problem.

## Migrations against a high-latency link

Two settings caused repeated migration failures and are now fixed:

1. **`statement_timeout` on migration connections** (`alembic/env.py`). Migrations previously
   inherited the application's `DB_STATEMENT_TIMEOUT_MS=30000`. That budget is sized for an
   HTTP request, not for `ALTER TABLE ... ADD CONSTRAINT`, which must validate the constraint
   against every existing row. Against a remote pooler (measured ~3s round trip) the statement
   was cancelled:
   `asyncpg.exceptions.QueryCanceledError: canceling statement due to statement timeout`.
   Migrations now set their own 10-minute ceiling. Note asyncpg requires this as a **string**
   (`Dict[str, str]`); an int raises `ClientConfigurationError`.

2. **`idle_in_transaction_session_timeout = 5min`** (database-level setting, now applied).
   Without it, a leaked `idle in transaction` session holds locks indefinitely and blocks DDL.
   This happened: an `ALTER TABLE` waited 2m53s on a transaction that had been idle 28 minutes,
   held by a local dev server that had been left running. The lock only released when that
   process was stopped. With this setting, PostgreSQL reclaims such sessions itself.

**Operational rule: stop local servers before running migrations.** DDL needs an exclusive
lock, and any long-lived idle transaction will block it for as long as it lives.
