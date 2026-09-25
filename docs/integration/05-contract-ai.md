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

`page_context` is the **new optional additive field**. `context_type` / `context_id` / `action`
/ `selected_code` / `snippet_id` / `conversation_id` / `include_history` are unchanged, so
existing React calls keep working.

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
* Entities: `problem_progress`, `problem_attempt`, `problem_notes`, `code_snippet`, `revision`,
  `lld_progress`, `lld_notes`, `hld_progress`, `hld_notes`, `study_session`, `user_settings`.

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
  duplicate chunks; `content_hash` short-circuits re-embedding.
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
LLD design decisions + responsibilities + patterns + tradeoffs, HLD requirements / data model /
database choice / caching / scaling / queues / failure handling / tradeoffs, and occasional
conversation summaries.

**Never embed:** status, attempts, confidence, dates, streak, progress %, revision-due dates,
study minutes, raw DB metadata, and every individual chat message.

### Chunking

Structure-aware: each HLD/LLD structured field is its own chunk (`"URL Shortener / Caching"`).
Continuous prose: target 350–600 tokens, max ~700, overlap 50–80 tokens. **No overlap between
already-separated structured fields.**

## 7. Conversation memory

* `ai_conversations` + `ai_messages` hold the transcript.
* New additive column `ai_conversations.conversation_summary` (text, null).
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
