# Frozen contract — PageContext, TutorAction, AI I/O, Sync (Phase 2, Agent 4)

Status: **frozen**. Changes require a contract change note (see `00-README.md`).

## 1. PageContext

Sent by the client with every AI request. React and iOS may model it differently internally,
but the **JSON on the wire is identical**.

```json
{
  "page_type": "dsa_problem",
  "entity_type": "dsa",
  "entity_id": "subarray-sum-equals-k",
  "active_tab": "code",
  "selected_text": null,
  "focused_field": "mistakes",
  "draft_fields": { "approach": "...", "mistakes": "..." },
  "code": { "language": "python", "content": "..." }
}
```

| Field | Type | Notes |
|---|---|---|
| `page_type` | enum | `today \| dsa_problem \| dsa_catalog \| lld_topic \| hld_topic \| revisions \| stats \| settings \| general` |
| `entity_type` | enum | `dsa \| lld \| hld \| plan \| revision \| none` |
| `entity_id` | string \| null | **TEXT slug for DSA** (`dsa_problems.id` is the slug), UUID for LLD/HLD topics |
| `active_tab` | string \| null | e.g. `overview \| code \| notes` |
| `selected_text` | string \| null | user's highlighted text |
| `focused_field` | string \| null | `approach \| mistakes \| notes \| revision_notes \| requirements \| architecture \| tradeoffs \| failure_handling \| …` |
| `draft_fields` | object \| null | **unsaved** editor contents, keyed by field name |
| `code` | object \| null | `{language, content}` — unsaved code |

Rules:
* `entity_id` for DSA is the slug, **not** a UUID. This trips clients up; see §5.
* `draft_fields` and `code` carry unsaved state. Without them scenario 1 in the brief fails.
* Never send the user's whole database.

## 2. AI request / response

### Request — `POST /api/v1/ai/chat`

```json
{
  "context_type": "dsa",
  "context_id": "subarray-sum-equals-k",
  "message": "Why is my approach wrong?",
  "action": "general",
  "selected_code": "…",
  "snippet_id": null,
  "conversation_id": null,
  "include_history": true,
  "page_context": { "…PageContext…" }
}
```

`page_context` is the **new optional additive field**. `context_type` / `action` /
`selected_code` / `snippet_id` / `conversation_id` / `include_history` are unchanged, so existing
React calls keep working.

`context_id` is a **string**, not a UUID (`str | None`, `max_length=300` in
`app/schemas/ai.py::AIChatRequest`; `String(300)` on `ai_conversations.context_id`). It carries
either a **DSA problem slug** (e.g. `"two-sum"`, `"subarray-sum-equals-k"`) or an **LLD/HLD topic
UUID**. It is text because `dsa_problems.id` is the problem slug — a TEXT primary key — so a UUID
column could never address a DSA problem; migration `0005_ai_context_id_text` widened the column
`uuid → text` to make the DSA tutor work. The same rule governs `PageContext.entity_id` in §1:
DSA is a slug, LLD/HLD is a UUID, and both go on the wire as strings.

### Response — `POST /api/v1/ai/chat`

```json
{
  "conversation_id": "uuid",
  "message": { "role": "assistant", "content": "…", "action": "general", "provider": "gemini", "model": "…" },
  "context_used": { "…summary, never the full prompt…" },
  "is_new_conversation": false,
  "actions": [ { "…TutorAction…" } ]
}
```

`actions` is a **new additive field** (empty list when none). Existing clients ignore it.

### Streaming — `POST /api/v1/ai/chat/stream` (new)

`text/event-stream`. Event sequence:

```
event: token      data: {"text": "Sliding "}
event: token      data: {"text": "window "}
event: actions    data: {"actions": [ …TutorAction… ]}
event: done       data: {"conversation_id": "uuid", "message_id": "uuid"}
event: error      data: {"code": "AI_UNAVAILABLE", "message": "…"}
```

* Structured `actions` are emitted **after** the token stream, never inline.
* Must terminate with exactly one `done` or `error`.
* Compatible with `URLSession` byte streams (iOS) and `EventSource`/`fetch` (React).

## 3. TutorAction

```json
{
  "id": "uuid",
  "type": "append_field",
  "target": { "entity_type": "dsa", "entity_id": "subarray-sum-equals-k", "field": "mistakes" },
  "value": "Sliding window is unreliable when negative values are present…",
  "status": "pending"
}
```

Allowed `type` values (frozen):

| `type` | Target | Meaning |
|---|---|---|
| `set_field` | any editable field | replace the field's value |
| `append_field` | any editable field | append to the field |
| `replace_selection` | any editable field | replace `selected_text` only |
| `create_note` | entity | create/overwrite the entity's note document |
| `create_code_snippet` | dsa/lld/hld | new snippet |
| `update_code` | dsa/lld/hld | modify an existing snippet |
| `set_confidence` | dsa/lld/hld | 0–5 |
| `set_status` | dsa/lld/hld | must be a valid enum for that entity |
| `schedule_revision` | dsa | set the next revision date |
| `create_revision_note` | dsa | write the revision-notes field |

`status ∈ pending | applied | rejected | failed`.

**Rule:** the model never emits SQL. An action is a *proposal*; `TutorActionService` authorizes,
validates and applies it (§4).

## 4. Action lifecycle

```
LLM → TutorAction(pending) → TutorActionService
                                    ├─ authorize: JWT sub owns the target resource
                                    ├─ validate: entity exists, field editable, type allowed,
                                    │            payload shape valid, version acceptable
                                    ├─ apply:   repository write (+ version bump)
                                    └─ audit:   persist the action row
```

* `POST /api/v1/ai/actions/{id}/execute` — apply a pending action. Idempotent per action id.
  Returns the applied action plus the resulting record.
* `POST /api/v1/ai/actions/{id}/reject` — mark rejected. No write.
* Actions are persisted so an action can be executed from a *different device* than the one that
  generated it (scenario 3 in the brief).
* `GET /api/v1/ai/actions` is unchanged (static menu) — see `04-contract-openapi.md` §1.

## 5. Sync contract (Agent 1 ↔ Agent 2)

Already implemented and frozen. iOS must adopt it as-is.

```json
{
  "device_id": "uuid",
  "device_type": "ios",
  "mutations": [
    {
      "mutation_id": "uuid",
      "entity": "problem_progress",
      "operation": "upsert",
      "record_id": "uuid",
      "base_version": 3,
      "payload": {}
    }
  ]
}
```

* `POST /api/v1/sync/push` → `{results[], applied_count, conflict_count, duplicate_count,
  rejected_count, server_cursor, server_time}`.
* `GET /api/v1/sync/pull?cursor=N&limit=N&device_id=X` → `{changes[], next_cursor, has_more,
  server_time, remaining}`.
* `mutation_id` is idempotent (`unique(user_id, mutation_id)`); a replay returns
  `skipped_duplicate`.
* `base_version` mismatch → `conflict`, and the **server's current record** is returned in
  `server_record` so the client merges instead of blindly retrying.
* Cursor is the server's `sync_changes.seq` (bigint identity). **Never** a device timestamp.
* Entities (11 of 11 now have a handler — `study_session` is genuinely supported):
  `problem_progress`, `problem_attempt`, `problem_notes`, `code_snippet`, `revision`,
  `lld_progress`, `lld_notes`, `hld_progress`, `hld_notes`, `study_session`, `user_settings`.
  `SyncEntity` declares 11 values and `SyncService._handlers()` registers all 11; the earlier
  state — `study_session` declared but unhandled, so a push returned `UNSUPPORTED_ENTITY` — is
  fixed by `_upsert_study_session` (start/complete shapes, server-measured duration).

Note: `design_topics` is deliberately **not** an entity. iOS's `DesignTopic` must be remapped to
the `lld_*` / `hld_*` entities.

## 6. RAG schema (Agent 4, new table)

```sql
knowledge_chunks (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid null,              -- NULL = global curriculum
  source_type      text not null,          -- dsa_problem | lld_topic | hld_topic | note | snippet | conversation_summary
  source_id        text not null,          -- slug or uuid
  section          text not null,          -- "requirements", "failure_handling", …
  content          text not null,
  embedding        vector(768),
  metadata         jsonb not null default '{}'::jsonb,
  content_hash     text not null,          -- skip re-embedding when unchanged
  embedding_model  text not null,          -- "gemini-embedding-2"
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
)
```

* `embedding_model = 'gemini-embedding-2'`, `vector(768)`.
* Retrieval: `WHERE user_id IS NULL OR user_id = :current_user` — a user's vectors are never
  returned to another user.
* Unique on `(source_type, source_id, section, coalesce(user_id, '00000000-…'))` to prevent
  duplicate chunks; `content_hash` short-circuits re-embedding. **PostgreSQL 17+**: this is
  realised as two partial unique indexes over the raw `user_id` column, with
  `ON CONFLICT (source_type, source_id, section, user_id) WHERE user_id IS [NOT] NULL` — see
  CN-007. No extra column is added. A portable `user_bucket`-style alternative for PG < 17
  is also described in CN-007.
* Cosine similarity. Exact search first; add HNSW + `vector_cosine_ops` only when latency
  demands it.

### Hybrid retrieval

```
query ─┬─ pgvector cosine top-K
       └─ PostgreSQL full-text search top-K
                  ↓
            RRF merge (k=60)
                  ↓
        metadata filter (user_id isolation)
                  ↓
              top 5–8 chunks
```

### Embed vs never embed

**Embed:** concept explanations, patterns, the user's approach/mistakes/learnings/revision notes,
LLD design decisions + responsibilities + patterns + tradeoffs, all **15** `hld_notes` text
fields — `functional_requirements`, `non_functional_requirements`, `capacity_estimation`,
`apis`, `data_model`, `high_level_architecture`, `database_choice`, `caching`, `queues`,
`scaling`, `failure_handling`, `tradeoffs`, `final_notes`, `interview_notes`, `mistakes` — and
occasional conversation summaries.

**Never embed:** status, attempts, confidence, dates, streak, progress %, revision-due dates,
study minutes, raw DB metadata, and every individual chat message.

### Chunking

Structure-aware: each HLD/LLD structured field is its own chunk (`"URL Shortener / Caching"`).
Continuous prose: target 350–600 tokens, max ~700, overlap 50–80 tokens. **No overlap between
already-separated structured fields.**

## 7. Conversation memory

* `ai_conversations` + `ai_messages` hold the transcript.
* New additive column `ai_conversations.conversation_summary` (text, null).
* New additive columns `ai_conversations.summary_watermark_message_id` (uuid, null) and
  `ai_conversations.summary_version` (int, not null, default 0). The summary's position and
  generation count are recorded explicitly; a stored timestamp alone is not sufficient — see
  CN-008.
* Prompt context = summary + last 8–12 relevant messages. Never the whole history.
* The LLM is never the source of truth for prior API calls.

## 8. Context assembly (order matters)

```
1. current unsaved PageContext
2. structured DB info for the entity
3. relevant hybrid RAG chunks
4. conversation summary
5. recent messages (8–12)
```

Never send the user's entire database.


## Contract change notes

### CN-007 — `knowledge_chunks` dedupe uses partial unique indexes, not a `user_bucket` column
```
WHAT CHANGED   §6's dedupe key (source_type, source_id, section, coalesce(user_id, sentinel))
               is realised as TWO partial unique indexes on the raw user_id column:
                 CREATE UNIQUE INDEX uq_knowledge_chunks_global
                   ON knowledge_chunks (source_type, source_id, section)
                   WHERE user_id IS NULL;
                 CREATE UNIQUE INDEX uq_knowledge_chunks_user
                   ON knowledge_chunks (source_type, source_id, section, user_id)
                   WHERE user_id IS NOT NULL;
               and the upsert targets them with, per partition,
                 ON CONFLICT (source_type, source_id, section) WHERE user_id IS NULL
                 ON CONFLICT (source_type, source_id, section, user_id) WHERE user_id IS NOT NULL
               The proposal's knowledge_chunks.user_bucket uuid GENERATED ALWAYS AS (...)
               STORED column is REJECTED and is not part of the contract.
WHY            Executable compilation on SQLAlchemy 2.0.54 proves an expression index is not
               needed. str(stmt.compile(dialect=postgresql.dialect())) emits the COALESCE
               target verbatim, and the index_where= form emits both partial targets verbatim:
                 ON CONFLICT (source_type, source_id, section, user_id) WHERE user_id IS NULL
                 ON CONFLICT (source_type, source_id, section, user_id) WHERE user_id IS NOT NULL
               Each matches its partial unique index exactly, so PostgreSQL infers it and no
               hand-written constraint= fallback (nor any DDL drift) is required. The
               generated column additionally costs 16 B/row on every row of every read path
               to solve a problem that exists on one write path, and it changes the table's
               visible shape for every future reader. (It was never unsound: SQLAlchemy omits
               Computed columns from the INSERT column list, verified.)
BACKWARD COMPATIBLE?   yes — §6 gains no column and no table change; the dedupe semantics are
               identical to the frozen key. Only the index realisation is pinned.
AFFECTED CLIENTS       backend, AI (indexer). No wire change; React and iOS are unaffected.
REQUIRED MIGRATION     In 0004, create the two partial unique indexes above instead of
               uq_knowledge_chunks_identity, and run the §5.5 dedupe DELETE before creating
               them. Upsert call sites pass index_where per partition; index_elements must
               include user_id whenever index_where is set (a bare
               index_elements=[source_type, source_id, section] + index_where=... compiles but
               omits user_id from the inferred target).
               PORTABILITY: partial-index inference in ON CONFLICT requires PostgreSQL 17+.
               If the deployment is PG < 17, the portable fallback is the proposal's
               user_bucket column (now permitted here as a documented alternative, never as a
               requirement) or a constraint="uq_..." target; that choice must be recorded in
               06-migration-plan.md before 0004 is written.
```

### CN-008 — conversation-memory watermark columns added to `ai_conversations`
```
WHAT CHANGED   ai_conversations gains summary_watermark_message_id (uuid, null) and
               summary_version (int, not null, default 0), alongside the already-frozen
               conversation_summary (text, null).
WHY            The summary's coverage boundary must be an opaque message ID, not a timestamp.
               AIMessage is soft-deleted and can be replayed; created_at ties in the same
               transaction / on a replayed turn, so "messages with created_at > watermark"
               can drop an unseen turn (ties) or silently shrink the window when the
               watermark message itself is soft-deleted (every remaining message now sorts
               before it, so the window empties and early turns are lost with no summary
               covering them). A monotonic message ID makes the boundary stable under both.
               summary_version makes "the summary lags the transcript" observable, so a
               failed regeneration is detectable rather than a silent double-count.
BACKWARD COMPATIBLE?   yes — two additive nullable/defaulted columns; no existing client reads
               ai_conversations directly.
AFFECTED CLIENTS       backend, AI
REQUIRED MIGRATION     Add both columns in 0004. Backfill: leave the watermark NULL and
               summary_version at 0 for existing conversations (NULL means "summarise the
               whole thread"). Window predicate becomes
               `id <= summary_watermark_message_id` over an ordered, soft-delete-stable
               message ordering; the summary call is triggered by message count / token
               thresholds only, never by a timestamp comparison.
```

### CN-009 — §6 HLD embeddable field count corrected 13 → 15
```
WHAT CHANGED   §6 "Embed vs never embed" now names all 15 HLD text fields instead of
               implying 13.
WHY            05-contract-ai.md §6 said 13; the implementation spec said 15. The model is
               authoritative: backend/app/db/models/hld.py HLDNote defines 15 Mapped[str]
               Text fields — functional_requirements, non_functional_requirements,
               capacity_estimation, apis, data_model, high_level_architecture,
               database_choice, caching, queues, scaling, failure_handling, tradeoffs,
               final_notes, interview_notes, mistakes. The 13 are the design sections; the
               last two (interview_notes, mistakes) are reflective fields attached after
               them and are equally embeddable. The docstring's own "13-section design
               document" is a naming artefact, not a field count. Consequence: HLD chunk
               volume is up to 15 per topic (not 13), which the spec's storage budget
               already assumes.
BACKWARD COMPATIBLE?   yes — documentation and chunk-count correction only; no schema or wire
               change.
AFFECTED CLIENTS       backend, AI
REQUIRED MIGRATION     none. 09-ai-implementation-spec.md is already consistent; it is frozen
               as written and must not be edited.
```
