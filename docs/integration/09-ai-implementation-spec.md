# Phase 5 — AI/RAG implementation specification (contextual tutor)

**Owner:** Agent 4 (AI/RAG engineer)
**Status:** implementation-ready specification. **No code in this document is applied to the
repository** — it is the exact design to implement, in a fixed order, after the RAG
migration lands.
**Implements against:** `docs/integration/05-contract-ai.md` (frozen contract), §3
`TutorAction`, §6 RAG schema, §7 conversation memory, §8 context assembly.
**Companion docs:** `docs/integration/06-migration-plan.md` Phase 5 (steps 1–8) and
performance guardrails; `docs/integration/04-contract-openapi.md` for the unchanged routes.

Verification basis: every model field, repository method, enum and settings key named below
was read from the live source tree (`app/db/models/*.py`, `app/services/**`, `app/core/**`).
Nothing is invented; where the contract is silent, this document makes the choice and says
why.

---

## 0. Module layout and dependency direction

New package `app/services/rag/` (imports point **down** only — `rag` may import
`app.services.ai.provider`, `app.services.ai.embedding_provider`; nothing in
`app.services.ai` may import `rag` except the tutor service, which imports `rag` lazily
inside functions):

| Module | Responsibility |
|---|---|
| `app/services/ai/embedding_provider.py` | `EmbeddingProvider` protocol, `EmbeddingResult`, `EmbeddingProviderConfigurationError`, `StubEmbeddingProvider` |
| `app/services/ai/gemini_embedding.py` | `GeminiEmbeddingProvider` (`gemini-embedding-2`, 768) |
| `app/services/ai/embedding_factory.py` | `build_embedding_provider(settings)` |
| `app/services/rag/chunking.py` | `ChunkingService` + `Chunk` dataclass + per-source field maps |
| `app/services/rag/hashing.py` | canonical text build + `content_hash` |
| `app/services/rag/index_service.py` | `KnowledgeIndexService` (global seed + per-user upsert, delete, rebuild) |
| `app/services/rag/retrieval_service.py` | `RetrievalService` (vector branch, FTS branch, RRF, filters) |
| `app/services/rag/context_builder.py` | `ContextBuilder` (five-part assembly + budget) |
| `app/services/ai/tutor_actions.py` | `TutorActionService` (validate → apply → audit) |
| `app/services/ai/conversation_summary.py` | summary regeneration policy + prompt |
| `app/repositories/knowledge.py` | `KnowledgeChunkRepository` (all SQL for `knowledge_chunks`) |
| `app/schemas/ai_actions.py` | `TutorAction`, `TutorActionTarget`, `AIActionRecord`, execute/reject responses |
| `alembic/versions/0004_ai_rag_foundation.py` | `vector` extension, `knowledge_chunks`, HNSW (deferred — see §5.6), `ai_conversations.conversation_summary`, `ai_conversation_summaries` watermark |

Wiring changes (only these three files are touched): `app/api/v1/services.py` gains
`self.knowledge`, `self.rag`, `self.context_builder`, `self.tutor_actions`,
`self.conversation_summary`; `app/api/v1/ai.py` gains `/chat/stream`, `/actions/{id}/execute`,
`/actions/{id}/reject`, `GET /ai/actions/pending`; `app/services/ai_tutor_service.py` gains
the optional `RAG` collaborators and the streaming path. `app/services/ai/prompts.py` is
extended, not rewritten.

---

## 1. Embedding provider

### 1.1 Protocol (`app/services/ai/embedding_provider.py`)

Mirrors `app/services/ai/provider.py` exactly: a `runtime_checkable` Protocol, dataclass
results, a dedicated configuration error class, and a stub implementation so tests and local
development never need a paid key.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable


@dataclass(slots=True)
class EmbeddingResult:
    """One embedding plus the bookkeeping the indexer persists."""

    vector: list[float]
    provider: str          # "gemini" | "stub"
    model: str             # "gemini-embedding-2" | "stub-embedding"
    dimensions: int        # 768 for the real provider
    usage: dict[str, Any] = field(default_factory=dict)  # {"input_tokens": int, "billable_chars": int}


@runtime_checkable
class EmbeddingProvider(Protocol):
    """The contract every embedding backend must satisfy."""

    name: str        # provider identifier, e.g. "gemini"
    model: str       # embedding model id, e.g. "gemini-embedding-2"
    dimensions: int  # must be 768 — the column is vector(768)

    async def embed(
        self,
        text: str,
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> EmbeddingResult:
        """Embed a single string.

        ``task_type`` is one of ``RETRIEVAL_DOCUMENT`` (indexing) or ``RETRIEVAL_QUERY``
        (search). The asymmetry matters: Gemini was trained with distinct task prefixes,
        so indexing with the query prefix silently degrades recall.
        """
        ...

    async def embed_batch(
        self,
        texts: Sequence[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[EmbeddingResult]:
        """Embed many strings, preserving input order.

        Callers pass at most ``settings.embedding_batch_size`` (default 16) texts. Larger
        inputs are chunked internally by the provider, but the indexer's own batcher is the
        one that bounds request size and cost — see §1.4.
        """
        ...

    async def health(self) -> dict[str, Any]:
        """Non-sensitive readiness information. Never returns the API key."""
        ...

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        ...


class EmbeddingProviderConfigurationError(RuntimeError):
    """Raised when an embedding provider is selected but not fully configured.

    Deliberately a sibling of ``AIProviderConfigurationError`` rather than the same class:
    chat and embeddings can be configured independently (Groq chat + Gemini embeddings is a
    legitimate combination) and the two failures must be distinguishable in logs.
    """
```

### 1.2 `GeminiEmbeddingProvider` (`app/services/ai/gemini_embedding.py`)

Modelled directly on `GeminiProvider`: raw REST over `httpx.AsyncClient`, key in the
`x-goog-api-key` header (never a query string), lazily created client shared across calls,
`aclose()` on shutdown.

```python
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-embedding-2"
DEFAULT_DIMENSIONS = 768
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.6          # identical to GeminiProvider: 0.6 * attempt


class GeminiEmbeddingProvider:
    name = "gemini"
    dimensions = DEFAULT_DIMENSIONS

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = "",
        timeout: float = 30.0,
        output_dimensionality: int = DEFAULT_DIMENSIONS,
    ) -> None:
        if not api_key:
            raise EmbeddingProviderConfigurationError(
                "EMBEDDING_API_KEY (or AI_API_KEY) is required when EMBEDDING_PROVIDER=gemini."
            )
        if output_dimensionality != DEFAULT_DIMENSIONS:
            raise EmbeddingProviderConfigurationError(
                f"knowledge_chunks.embedding is vector({DEFAULT_DIMENSIONS}); "
                f"output_dimensionality must be {DEFAULT_DIMENSIONS}."
            )
        ...
```

**Request shape (real Gemini embeddings REST surface, `v1beta`).**

Single: `POST {base}/models/{model}:embedContent`

```json
{
  "model": "models/gemini-embedding-2",
  "content": { "parts": [ { "text": "<chunk text>" } ] },
  "taskType": "RETRIEVAL_DOCUMENT",
  "outputDimensionality": 768
}
```

Batch: `POST {base}/models/{model}:batchEmbedContents`

```json
{
  "requests": [
    {
      "model": "models/gemini-embedding-2",
      "content": { "parts": [ { "text": "..." } ] },
      "taskType": "RETRIEVAL_DOCUMENT",
      "outputDimensionality": 768
    }
  ]
}
```

Response parsing: single → `payload["embedding"]["values"]`; batch →
`payload["embeddings"][i]["values"]`. `task_type` maps to `RETRIEVAL_DOCUMENT` when
indexing and `RETRIEVAL_QUERY` when embedding the search query; pass it on every call so the
two paths can never be mixed up by a refactor.

**Guardrails inside `_parse`:**
* If `len(values) != 768` → `EmbeddingProviderError` (`code="EMBEDDING_DIMENSION_MISMATCH"`),
  raised before any row is written. A mis-sized vector would otherwise fail the column type
  mid-transaction and abort a whole batch of otherwise-good chunks.
* Missing/empty `values` → `EmbeddingProviderError("The embedding provider returned an empty vector.")`.
* Reject empty input text locally (`EMBEDDING_EMPTY_INPUT`) rather than paying for a call.

### 1.3 Batch size, retry and backoff

| Knob | Value | Rationale |
|---|---|---|
| `settings.embedding_batch_size` | **16** | `batchEmbedContents` accepts more, but 16 keeps a single failure cheap to retry (≤16 chunks lost) and each request small enough to finish inside the 30 s read timeout. The indexer's batcher is the authority; the provider clamps to ≤64 as a defensive ceiling. |
| `settings.embedding_concurrency` | **3** | In-flight batches per worker. Gemini quotas are per-minute; 3 concurrent × 16 texts keeps throughput sane without a burst of 429s. Bounded by an `asyncio.Semaphore`. |
| `settings.embedding_timeout_seconds` | **30.0** | Shorter than the chat timeout (60 s): an embedding that has not answered in 30 s is not worth blocking an index job. |
| Attempts | **3** | Identical to `GeminiProvider`. |
| Backoff | `await asyncio.sleep(0.6 * attempt)` → 0.6 s, 1.2 s | Identical to `GeminiProvider`; no jitter because the indexer is a single low-rate background writer, not a thundering herd. |
| Retry on | `httpx.TimeoutException`, `httpx.HTTPError`, and status in `{408,429,500,502,503,504}` | Same set as chat. |
| Fail immediately on | `400` (bad request — retrying cannot help), `401`/`403` (`EmbeddingProviderError("The embedding provider rejected our credentials.")`), and any `values` length ≠ 768 | A deterministic error must not burn three attempts. |
| Partial-batch failure | The 16-text batch is retried as a whole; if it still fails, the batch is split into 8 + 8 and retried once. Anything still failing is recorded per chunk in `metadata`-free form (see below) and the job continues | One pathological chunk (e.g. an enormous paste) must not abort a 1 290-chunk global seed. |
| Per-chunk hard cap | `settings.embedding_max_chunk_chars = 8_000` | ~2 000 tokens, comfortably above the ~700-token prose max; a chunk above this is truncated on a paragraph boundary and logged at `WARNING` with `source_type`/`source_id`/`section`. Never silently dropped. |

### 1.4 Unconfigured-provider behaviour (degrade to 503, never fatal)

This mirrors `build_provider` + `main.py` §lifespan exactly:

1. `app/main.py` lifespan gains a second, independent build next to the chat provider:

```python
try:
    from app.services.ai.embedding_factory import build_embedding_provider
    app.state.embedding_provider = build_embedding_provider(settings)
except Exception as exc:                      # AIProviderConfigurationError included
    app.state.embedding_provider = None
    logger.warning("RAG embeddings are unavailable: %s", exc)
```

   A misconfigured embedding provider **must not** stop `ai_provider` from being built, and
   vice versa. Both `try` blocks are independent.

2. `build_embedding_provider(settings)`:

| `EMBEDDING_PROVIDER` | Behaviour |
|---|---|
| `gemini` (default) | `GeminiEmbeddingProvider(api_key=settings.embedding_api_key or settings.ai_api_key, model=settings.embedding_model or "gemini-embedding-2", base_url=settings.embedding_base_url, timeout=settings.embedding_timeout_seconds)` |
| `stub` | `StubEmbeddingProvider(dimensions=768)` — deterministic hash-seeded pseudo-vectors, `configured=True`. Used by tests and key-less local dev. |
| anything else | `raise EmbeddingProviderConfigurationError(f"Unknown EMBEDDING_PROVIDER '{...}'. Supported: gemini, stub.")` |

3. `KnowledgeIndexService` and `RetrievalService` treat `provider is None` as
   **unconfigured**, not as an error:

```python
def _require_provider(self) -> EmbeddingProvider:
    if self._provider is None:
        raise AIConfigurationError(
            "Semantic search is not configured on this server."
        )  # -> 503 {"error": {"code": "AI_NOT_CONFIGURED", ...}}
    return self._provider
```

   `AIConfigurationError` is reused verbatim from `app/core/exceptions.py`
   (`status_code=503`, `code="AI_NOT_CONFIGURED"`), so clients already handling a
   tutor-unavailable response handle a retrieval-unavailable response identically.

4. **Retrieval degrades, it does not fail the request.** In `ContextBuilder.build`, the RAG
   step is wrapped so an unconfigured or failing embedding provider produces
   `rag_chunks=[]` plus `context_used["rag"] = {"degraded": true, "reason": "AI_NOT_CONFIGURED"}`
   and the tutor answers from parts 1, 2, 4 and 5 only. Only the explicit
   `POST /ai/knowledge/reindex` route surfaces the 503 directly. Rationale: the tutor's core
   value (explain the current problem) does not depend on RAG; losing semantic recall is a
   quality regression, not a request failure.
5. Indexing jobs called from the seed script or an admin route **do** propagate the 503 —
   a silent no-op index would be a correctness bug.
6. Health: `GET /health/ready` reports
   `{"ai": {...}, "embeddings": {"provider": "gemini", "model": "gemini-embedding-2", "dimensions": 768, "configured": true, "reachable": null}}`
   — same "no active probe, it costs quota" convention as `GeminiProvider.health()`.

### 1.5 Settings additions (`app/core/config.py`)

```python
EmbeddingProviderName = Literal["gemini", "stub"]

embedding_provider: EmbeddingProviderName = "gemini"
embedding_api_key: str = ""                 # falls back to ai_api_key when empty
embedding_model: str = "gemini-embedding-2"
embedding_base_url: str = ""
embedding_timeout_seconds: float = 30.0
embedding_batch_size: int = 16
embedding_concurrency: int = 3
embedding_max_chunk_chars: int = 8_000
embedding_dimensions: int = 768             # asserted against the column at startup
rag_vector_top_k: int = 20
rag_fts_top_k: int = 20
rag_final_top_k: int = 6                    # contract says 5-8; 6 is the default
rag_rrf_k: int = 60
rag_min_score: float = 0.0                  # RRF score floor; 0.0 = keep the full window
ai_summary_message_threshold: int = 16
ai_summary_token_threshold: int = 1_500
ai_summary_target_tokens: int = 600
ai_context_budget_tokens: int = 6_000
ai_context_recent_messages: int = 12        # already configurable as ai_max_history_messages
ai_stream_max_tokens: int = 1_400
```

`embedding_provider: "gemini"` with an empty key reproduces today's chat behaviour: the
build raises at startup, the lifespan logs a warning, and every semantic feature returns a
clean 503 instead of a 500.

---

## 2. Chunking

`ChunkingService` is a pure function layer: no I/O, no DB, fully unit-testable.

```python
@dataclass(slots=True, frozen=True)
class Chunk:
    source_type: str          # dsa_problem | lld_topic | hld_topic | note | snippet | conversation_summary
    source_id: str            # DSA slug (TEXT) or lld/hld topic UUID as str
    section: str              # "requirements", "failure_handling", "approach" ...
    content: str              # the exact text that gets embedded
    chunk_index: int          # 0-based, disambiguates a prose field that splits into N parts
    token_estimate: int       # len(content) // 4  (see §2.5)
    metadata: dict[str, Any]  # see §2.4 — filterable, non-semantic facts only
```

### 2.1 Source types and `section` values

`section` is the stable, machine-readable label from `05-contract-ai.md` §6
(`"requirements"`, `"failure_handling"`, …). It must be **stable across re-indexing** — it is
part of the dedupe key, so renaming one silently creates orphaned chunks. The canonical
`section` for every field is the field name itself, except for the two documented overrides
below.

### 2.2 DSA — `app/db/models/dsa.py`

Two objects contribute chunks.

**(a) `DSAProblem` (catalog, `user_id = NULL`, global).** The catalog is metadata only: the
seed data (`app/seed_data/dsa_problems.json`, 90 problems) carries `title`, `slug`,
`difficulty`, `primary_topic`, `patterns`, `companies`, `importance`, `estimated_minutes`,
`external_url` — no problem statement, no solution. Embeddable fields, each **one chunk**:

| # | Field (`DSAProblem`) | `section` | Embeddable | Notes |
|---|---|---|---|---|
| 1 | `title` | `title` | ✅ | "Two Sum" — short, but it is the anchor text that makes a slug searchable by name |
| 2 | `primary_topic` | `primary_topic` | ✅ | Concept label ("arrays", "dynamic_programming") |
| 3 | `secondary_topics` (list) | `secondary_topics` | ✅ | Rendered as a comma-joined line |
| 4 | `patterns` (list) | `patterns` | ✅ | "Hash Map, Two Pointers" — the highest-value DSA retrieval signal |
| 5 | `companies` (list) | `companies` | ✅ | Comma-joined, capped at the first 20 |
| 6 | `difficulty` | `difficulty` | ❌ | **Never embedded** — a single enum word is pure noise in a vector (contract §6 "never embed: status, …"). Kept as filterable `metadata` only |
| 7 | `problem_type` | `problem_type` | ✅ | "algorithmic", "design" … |
| 8 | `importance` | — | ❌ | Numeric ranking; metadata only |
| 9 | `estimated_minutes` | — | ❌ | Numeric; metadata only |
| 10 | `is_active` | — | ❌ | Boolean; metadata only |
| 11 | `external_url`, `source` | — | ❌ | A URL is not semantic content and `source` ("leetcode") is a constant across the catalog |
| 12 | `hints` (JSONB, currently `NULL` for all 90 seeds) | `hint_{i}` | ✅ *(conditional)* | If a seed ever populates `DSAProblem.hints`, each hint becomes its own chunk (`hint_0`, `hint_1`, …). Empty/`NULL` → no chunk produced |

DSA catalog → **6 chunks per seeded problem** (title, primary_topic, secondary_topics,
patterns, companies, problem_type) plus 0 hint chunks today, because `DSAProblem.hints` is
`NULL` for every one of the 90 seeds. 90 × 6 = **540 global DSA chunks**.

**(b) `ProblemNote` (user-owned, `user_id = <user>`).** Each populated text field is its own
chunk, prose-chunked per §2.5:

| # | Field (`ProblemNote`) | `section` | Chunking |
|---|---|---|---|
| 1 | `approach` | `approach` | prose (350–600 target / ~700 max / 50–80 overlap) |
| 2 | `notes` | `notes` | prose |
| 3 | `mistakes` | `mistakes` | prose |
| 4 | `revision_notes` | `revision_notes` | prose |
| 5 | `time_complexity` | `time_complexity` | **structured, single chunk, no prose split** — `String(120)`, a Big-O expression |
| 6 | `space_complexity` | `space_complexity` | structured, single chunk, no prose split |

Fields deliberately excluded: `id`, `user_id`, `problem_id`, `created_at`, `updated_at`,
`version`, `deleted_at`. `time_complexity` / `space_complexity` **are** embedded (unlike
`DSAProblem.difficulty`) because the user wrote "O(n log n) two-pointer sweep after sorting",
which is semantic content the tutor can correct — whereas `difficulty='easy'` is a catalog
constant.

DSA per-user → **up to 6 chunks per problem the user has notes for.**

### 2.3 LLD — `app/db/models/lld.py`

**(a) `LLDTopic` (catalog, global).** Embeddable fields, each one chunk:

| # | Field (`LLDTopic`) | `section` | Embeddable | Notes |
|---|---|---|---|---|
| 1 | `title` | `title` | ✅ | "SOLID Principles" |
| 2 | `description` | `description` | ✅ | Prose, but capped in practice at ~500 chars (mean 80 chars in the seed); single chunk |
| 3 | `learning_objectives` (list) | `learning_objectives` | ✅ | One chunk, newline-joined bullets |
| 4 | `key_concepts` (list) | `key_concepts` | ✅ | "SRP, OCP, LSP, ISP, DIP" |
| 5 | `category` | `category` | ✅ | `fundamentals` / `design_patterns` / `design_exercises` — a meaningful concept label |
| 6 | `difficulty` | — | ❌ | Never embedded; metadata |
| 7 | `estimated_minutes`, `order_index`, `is_active` | — | ❌ | Numeric/boolean; metadata |
| 8 | `slug`, `external_url` | — | ❌ | Identifiers, not content |
| 9 | `id` | — | ❌ | It is `metadata.topic_id` |

LLD catalog → **5 chunks per topic.**

**(b) `LLDNote` (user-owned).** Every content-bearing field, each its own chunk:

| # | Field (`LLDNote`) | `section` | Chunking |
|---|---|---|---|
| 1 | `summary` | `summary` | prose |
| 2 | `design_explanation` | `design_explanation` | prose |
| 3 | `class_responsibilities` | `class_responsibilities` | prose |
| 4 | `relationships` | `relationships` | prose |
| 5 | `design_notes` | `design_notes` | prose |
| 6 | `mistakes` | `mistakes` | prose |
| 7 | `revision_notes` | `revision_notes` | prose |
| 8 | `patterns_used` (array) | `patterns_used` | structured, single chunk, no overlap (comma-joined) |
| 9 | `class_diagram` (JSONB) | `class_diagram` | **not embedded — see §11.1**; its semantic content is already in `class_responsibilities` + `relationships` |

Excluded: `id`, `user_id`, `lld_topic_id`, `created_at`, `updated_at`, `version`,
`deleted_at`.

LLD per-user → **up to 8 chunks per topic with notes.**

### 2.4 HLD — `app/db/models/hld.py`

**(a) `HLDTopic` (catalog, global).** Identical shape to `LLDTopic`:

| # | Field (`HLDTopic`) | `section` |
|---|---|---|
| 1 | `title` | `title` |
| 2 | `description` | `description` |
| 3 | `learning_objectives` (list) | `learning_objectives` |
| 4 | `key_concepts` (list) | `key_concepts` |
| 5 | `category` | `category` (`fundamentals` / `system_design`) |

Not embedded: `difficulty`, `estimated_minutes`, `order_index`, `is_active`, `slug`,
`external_url`, `id`.

HLD catalog → **5 chunks per topic** (20 topics → 100 chunks).

**(b) `HLDNote` (user-owned) — the 15-field design document.** Each of the 13 structured
design sections is its own chunk; these are the **real field names** read from
`app/db/models/hld.py`:

| # | Field (`HLDNote`) | `section` | Chunking |
|---|---|---|---|
| 1 | `functional_requirements` | `functional_requirements` | structured → single chunk, **no overlap** |
| 2 | `non_functional_requirements` | `non_functional_requirements` | structured, no overlap |
| 3 | `capacity_estimation` | `capacity_estimation` | structured, no overlap |
| 4 | `apis` | `apis` | structured, no overlap |
| 5 | `data_model` | `data_model` | structured, no overlap |
| 6 | `high_level_architecture` | `high_level_architecture` | structured, no overlap |
| 7 | `database_choice` | `database_choice` | structured, no overlap |
| 8 | `caching` | `caching` | structured, no overlap |
| 9 | `queues` | `queues` | structured, no overlap |
| 10 | `scaling` | `scaling` | structured, no overlap |
| 11 | `failure_handling` | `failure_handling` | structured, no overlap |
| 12 | `tradeoffs` | `tradeoffs` | structured, no overlap |
| 13 | `final_notes` | `final_notes` | structured, no overlap |
| 14 | `interview_notes` | `interview_notes` | structured, no overlap |
| 15 | `mistakes` | `mistakes` | structured, no overlap |

Note the count: this model has **15 text fields, not 13**. The 13 are the design sections
(`functional_requirements` … `final_notes`); `interview_notes` and `mistakes` are the two
reflective fields appended after them and are also embeddable. All 15 become chunks.

Excluded: `id`, `user_id`, `hld_topic_id`, `created_at`, `updated_at`, `version`,
`deleted_at`.

HLD per-user → **up to 15 chunks per topic with notes** (contract §6 lists HLD as
"requirements / data model / database choice / caching / scaling / queues / failure handling
/ tradeoffs", a subset of these 15).

**Two `section` overrides** (because `hld_notes` and `lld_notes` are different tables, no
collision exists — overrides are optional and only applied for readable labels):

* `hld_notes.mistakes` → `section = "mistakes"`.
* `lld_notes.revision_notes` → `section = "revision_notes"`, `lld_notes.mistakes` →
  `"mistakes"`. `problem_notes.mistakes` → `"mistakes"`. Because `source_type` is part of
  the dedupe key, three tables can all use `"mistakes"` safely.

### 2.5 Chunk boundaries

**Structured fields (LLD/HLD note sections and DSA complexity fields) — one field, one
chunk, no overlap, no splitting.**

* Boundary = the field's own value, rendered as a self-describing block:

```
<topic title> — <section label>

<field value>
```

  The topic title is prepended so the embedding of a section like `"caching"` is not a
  context-free wall of text ("Use Redis with a 60 s TTL for the redirect lookup") but is
  anchored to "URL Shortener / Caching". The prepended header is part of the hashed text and
  part of `content`; it is *not* stored in `metadata` twice (§2.6).
* A structured field whose value is `NULL`, whitespace-only, or shorter than
  `MIN_CHUNK_CHARS = 24` produces **no chunk**. An empty section must not create a phantom
  vector that then out-ranks real content on a weak query.
* There is **no length ceiling** on a structured field in the ordinary case: a
  `failure_handling` section up to ~8 000 chars stays one chunk because splitting it would
  destroy the field's identity and break the dedupe key. Above
  `embedding_max_chunk_chars` (8 000) the value is hard-truncated on a paragraph boundary
  and a `WARNING` is logged — truncation is visible, never silent, and never creates a
  second chunk with a different `section`.

**Continuous prose (`ProblemNote.approach` / `notes` / `mistakes` / `revision_notes`, and
every `LLDNote` prose field) — sliding window with overlap:**

| Parameter | Value | Rationale |
|---|---|---|
| Target tokens | **350–600** | A 350-token floor is the smallest window that reliably contains a complete reasoning chain ("I tried X because Y, but Z broke"); a 600-token ceiling keeps one chunk's dominant topic from drifting. |
| Hard maximum | **~700 tokens** | Matches `05-contract-ai.md` §6. Beyond this, the embedding's mean vector starts mixing two ideas. |
| Overlap | **50–80 tokens** (use **64**) | 64 ≈ 10–18 % of the window. Enough that a sentence cut by the boundary appears intact in the neighbouring chunk; small enough that a 500-token note produces 1 chunk, not 3. |
| Minimum chunk | **24 chars** | See above. |
| Boundary preference | paragraph (`\n\n`) → sentence (`. ` / `? ` / `! `) → word | Split as close as possible to the token target without cutting mid-sentence. |
| Token estimate | `len(text) // 4` | Documented approximation (`chars_per_token = 4`), consistent with the provider's own `usage` accounting. Exact tokenisation is not available without shipping a tokeniser, and chunk-boundary precision at ±10 % is acceptable here. |
| Oversized single paragraph | hard-split at the nearest word boundary at 700 tokens, still with 64-token overlap | A pasted wall of text must still produce bounded chunks. |

**Why structured fields get no overlap, and prose does — explicitly:**

1. *Identity.* A structured chunk is addressed by `(source_type, source_id, section)`. That
   triple is the unit the retriever reasons about — "the Notification System's
   `failure_handling` section". Overlap would either duplicate content into the neighbouring
   section (corrupting both) or require a per-chunk index inside the key, at which point the
   key no longer identifies a *field*, and the `content_hash` no-op in §3 stops working
   (every window would need its own hash, so an edit at the end of a field re-embeds every
   window).
2. *Self-containment.* An overlapping window exists because a prose boundary is arbitrary:
   the split point is chosen by a token counter, so it lands mid-argument and the missing
   context must be recoverable from the neighbour. A structured boundary is not arbitrary —
   the author (or the form) put the cut there. `caching` and `queues` are separate answers to
   separate prompts; repeating 64 tokens of `caching` at the top of `queues` adds no
   recoverable context, only duplicate retrieval hits.
3. *Retrieval precision.* Overlap inflates recall by making neighbours near-duplicates, so
   the vector branch returns the same idea twice and RRF then promotes it twice. For a
   `top-6` context budget, spending two slots on `scaling` means one fewer distinct section
   fits.
4. *Cost.* Every overlapping chunk is a billed embedding and a stored 768-float vector.
   Structured fields are the majority of chunks (§12), so overlap there is the expensive,
   low-value case.

Prose keeps overlap because the alternative — cutting an insight in half and retrieving only
the half — is a direct quality regression the user will notice ("you didn't have the second
half of my sentence").

### 2.6 Chunk metadata (filterable facts only)

`knowledge_chunks.metadata JSONB` carries what a *filter or a UI label* needs, never a
second copy of the content:

```json
{
  "title": "URL Shortener",
  "topic_slug": "url-shortener",
  "category": "system_design",
  "primary_topic": "dynamic_programming",
  "patterns": ["Hash Map", "Prefix Sum"],
  "difficulty": "hard",
  "language": "python",
  "snippet_id": "0b0c…",
  "note_version": 4,
  "field_chars": 1180,
  "truncated": false,
  "chunk_index": 0,
  "chunk_count": 1
}
```

Rules:
* Values are short scalars or short string arrays. **Never** a body of text.
* `note_version` is the `VersionMixin.version` of the source row at index time. It is
  informational (it powers "this chunk reflects note v4"); it is **not** the concurrency
  control mechanism — `content_hash` is.
* `patterns` is capped at 8 entries, `companies`/`key_concepts` at 20 — a filter helper, not
  a payload dump.
* Metadata is excluded from the hash (§3): a change to a display-only key must not trigger a
  re-embed.

### 2.7 Other source types

* `snippet` (`CodeSnippet.code`): only when
  `settings.rag_index_snippets = true` (default **false**). Code embeddings are weak, the
  chunk budget is better spent on prose, and a snippet's semantic content is usually
  restated in the notes. When enabled: one chunk per snippet, `section = "code"`,
  `metadata.language`, `metadata.snippet_id`; a snippet longer than
  `embedding_max_chunk_chars` is split on function/class boundaries at 700 tokens with
  64-token overlap (it is prose-like, not field-like, so it follows prose rules).
* `conversation_summary`: one chunk per regenerated summary, `section = "summary"`,
  `source_id = conversation_id`, `user_id = owner`. Only created when
  `settings.rag_index_conversation_summaries = true` (default **true** — the contract §6
  explicitly allows "occasional conversation summaries"). The summary is superseded in
  place (same `source_id`, same `section`, new `content_hash`), so a conversation
  contributes exactly one chunk, never a growing pile.


---

## 3. Content hash and re-embed avoidance

### 3.1 What is hashed

The hash covers **exactly the text that is embedded**, plus the identity and model that the
text is only valid for:

```
canonical = "\n".join([
    source_type,
    source_id,
    section,
    embedding_model,          # "gemini-embedding-2"
    str(dimensions),          # 768
    str(chunk_index),
    build_chunk_text(...),    # the header + body actually sent to the embedder, whitespace-normalised
])
content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()   # 64 lowercase hex chars
```

Decisions, each with a reason:

| Decision | Choice | Why |
|---|---|---|
| Algorithm | **SHA-256**, hex digest | Available in the stdlib (no new dependency), collision-resistant enough that a false "unchanged" verdict is not a real risk, and 64 chars fits a plain `text` column with room to spare. `blake2b` would be marginally faster; the workload is hundreds of chunks, so readability wins. |
| Whitespace | Normalise first: `\r\n`→`\n`, strip trailing spaces per line, collapse ≥3 blank lines to 1, `.strip()` | A save that only reformats whitespace must not re-embed. |
| `chunk_index` included | Yes | If a prose field grows from one chunk to two, chunk 0's text may be *unchanged* while its meaning changed (it is no longer the whole story). Including the index would force a re-embed of chunk 0 that is not needed… which is why the index is included **only** together with the trailing window — see the note below. |
| `metadata` excluded | Yes | A display label change must never trigger a paid call. |
| `note_version` excluded | Yes | Version bumps happen for any field write, including a field this chunk does not represent. The content hash is the authority; the version is a hint. |
| `embedding_model` + `dimensions` included | Yes | Switching models or dimensionality must invalidate every hash, otherwise old vectors silently mix with new ones in the same column. |

*Note on `chunk_index`:* for prose fields the text itself encodes position (a paragraph that
moves changes both chunks), so including the index is belt-and-braces. For structured fields
`chunk_index` is always `0`, so it is a constant and cannot cause spurious invalidation.

### 3.2 Where the check happens

Indexing is **upsert-by-hash**, never insert-then-fix. Every path goes through
`KnowledgeChunkRepository.upsert_chunk(...)`.

**Initial (global) index** — `KnowledgeIndexService.index_global_curriculum()`:

```python
for batch in batched(chunks, settings.embedding_batch_size):        # 16
    existing = await repo.get_hashes(
        source_type=batch.source_types,
        source_ids=batch.source_ids,
        sections=batch.sections,
        user_id=None,                                               # global partition
    )                                                               # {(source_type, source_id, section): content_hash}
    to_embed = [c for c in batch if existing.get(key(c)) != c.content_hash]
    if not to_embed:
        stats.skipped += len(batch)
        continue
    results = await provider.embed_batch([build_chunk_text(c) for c in to_embed],
                                         task_type="RETRIEVAL_DOCUMENT")
    for chunk, result in zip(to_embed, results, strict=True):
        await repo.upsert_chunk(chunk=chunk, embedding=result.vector,
                                embedding_model=result.model, user_id=None)
    stats.embedded += len(to_embed)
    await session.commit()
```

* One `SELECT` for the whole batch (not per chunk) — 16 chunks cost 1 read + 1 write round
  trip, so re-running the seed is cheap even when nothing changed.
* Idempotency: the seed can be run repeatedly. Second run performs **zero** embedding calls.
  This is the acceptance test for §3 — see §13.
* Progress is printed per batch: `embedded=N skipped=M failed=K`.

**On update** — after any write that can change semantic content:

| Trigger | Hook | Scope |
|---|---|---|
| `NotesService.upsert` (`PUT /dsa/problems/{id}/notes`) | post-commit, `app/services/dsa_service.py` | one `problem_id`, one user |
| `TopicService.upsert_notes` (`PUT /lld\|hld/topics/{id}/notes`) | post-commit, `app/services/topic_service.py` | one topic, one user |
| `TopicService.update_progress` / `ProgressService.upsert` | post-commit | **nothing to index** (progress/status/confidence are never embedded); the hook exists only so a future embeddable progress field has one insertion point |
| `CodeSnippetService.create/update/delete` | post-commit | the snippet's chunk, only when `rag_index_snippets=true` |
| `AIConversationRepository.touch` after summary regeneration | post-commit | the single `conversation_summary` chunk |

The hook is a single call — `KnowledgeIndexService.index_notes(user_id=..., source_type=...,
source_id=...)` — wrapped in `try/except Exception: logger.warning(...)`. **Indexing must
never fail the user's write.** The note is already committed; a retrieval index that lags by
one write is a quality issue, the write itself is not.

### 3.3 The no-op path when the hash is unchanged

```
chunk_text  ──►  normalise ──►  sha256  ──►  compare against stored content_hash
                                                │
                        unchanged ──────────────┴────────────── changed
                             │                                      │
     UPDATE knowledge_chunks                                   call embed_batch
       SET updated_at = now()                                   then
     WHERE id = :id            <-- metadata-only refresh          UPDATE/INSERT the row
     (no embedding call,                                            with the new vector
      no vector write,                                              and content_hash
      no embedding_model change)
```

Concretely, `upsert_chunk` is a single statement that encodes both paths:

```python
stmt = (
    pg_insert(KnowledgeChunk)
    .values(
        user_id=user_id, source_type=..., source_id=..., section=...,
        content=..., embedding=embedding, metadata_=chunk.metadata,
        content_hash=chunk.content_hash, embedding_model=model,
    )
    .on_conflict_do_update(
        index_elements=["source_type", "source_id", "section", "user_bucket"],
        set_={
            "content":        excluded.content,
            "embedding":      excluded.embedding,
            "metadata":       excluded.metadata,
            "content_hash":   excluded.content_hash,
            "embedding_model": excluded.embedding_model,
            "updated_at":     func.now(),
        },
        # Metadata-only refresh: the vector is left exactly as it is.
        where=KnowledgeChunk.content_hash != excluded.content_hash,
    )
    .returning(KnowledgeChunk.id, KnowledgeChunk.updated_at)
)
```

`index_elements` names `user_bucket`, the generated dedupe column from §5 — the conflict
target must be the same expression the unique index uses.

**A `NULL` return from the statement means "hash unchanged"** (the update was skipped), so
the caller knows it did not need to embed at all — this is the fast path the repository
exposes as `await repo.has_unchanged_hash(...)`. The indexer asks first and only embeds the
ones that come back changed, so in the steady state (a user re-saving identical notes) the
cost is one `SELECT` and nothing else. Zero embedding calls, zero vector writes, and
`updated_at` on the chunk does not move, so RAG recency signals stay honest.

### 3.4 Deletion and staleness

* A field cleared to `""` → the chunk is deleted
  (`DELETE FROM knowledge_chunks WHERE user_id=:uid AND source_type=:st AND source_id=:sid AND section = ANY(:sections)`).
  Empty sections must not survive as stale vectors.
* A prose field that shrank from 2 chunks to 1 → the indexer deletes every
  `section = :section` row, then re-inserts the new windows. Simpler and safer than trying to
  diff windows; the hash check still prevents re-embedding identical text within the new set.
* Deleting a note/progress row (`deleted_at` set) → its chunks are deleted in the same
  post-commit hook.

---

## 4. Hybrid retrieval

`RetrievalService.search(...)` runs the two branches, merges them with RRF, applies the
metadata filter, and returns at most `settings.rag_final_top_k`.

### 4.1 Branch A — vector (pgvector cosine)

Top-K: **20** (`settings.rag_vector_top_k`). 20 is chosen because the RRF window must be
wider than the final cut (6) by enough that a document ranked 15th by cosine but 2nd by
keyword still surfaces; and because with `top_k = 20`, an exact (non-HNSW) scan over a few
thousand rows is still sub-10 ms.

```sql
-- :vec is passed as a pgvector literal string, e.g. '[0.0123,-0.0044,...]'
SELECT
    kc.id,
    kc.source_type,
    kc.source_id,
    kc.section,
    kc.content,
    kc.metadata,
    kc.embedding_model,
    1 - (kc.embedding <=> CAST(:vec AS vector(768))) AS cosine_similarity
FROM knowledge_chunks AS kc
WHERE (kc.user_id IS NULL OR kc.user_id = CAST(:user_id AS uuid))
  AND kc.embedding IS NOT NULL
  AND (CAST(:source_types AS text[]) IS NULL
       OR kc.source_type = ANY(CAST(:source_types AS text[])))
  AND (CAST(:exclude_source_id AS text) IS NULL
       OR kc.source_id <> CAST(:exclude_source_id AS text))
ORDER BY kc.embedding <=> CAST(:vec AS vector(768))
LIMIT CAST(:k AS integer);          -- :k = 20
```

* `<=>` is cosine distance; `1 - distance` is returned as a readable similarity for logging
  and for the `context_used` summary. The **ordering is on the raw distance operator** —
  never on the derived expression — so the operator can use an HNSW
  `vector_cosine_ops` index if one is added later.
* `ORDER BY embedding <=> :vec` is the literal form the contract §6 prescribes; the `CAST`
  is required because asyncpg binds `:vec` as `text` unless a type is supplied.
* **Never** filter on `embedding_model` — instead, chunks whose
  `embedding_model <> settings.embedding_model` are **excluded at the top of the query**
  (`AND kc.embedding_model = CAST(:model AS text)`). Mixing vectors from two models in one
  cosine ranking is meaningless and silently produces garbage; this line makes the failure
  impossible. It is a hard equality, not an ordering hint.

SQLAlchemy form (`app/repositories/knowledge.py`), matching the house style in
`app/repositories/*.py`:

```python
distance = KnowledgeChunk.embedding.op("<=>")(cast(vector_literal, Vector(768)))
stmt = (
    select(
        KnowledgeChunk,
        (literal(1.0) - distance).label("cosine_similarity"),
        (literal(1.0) - distance).op("/")(literal(float(rrf_k + 1))).label("rrf_contribution"),
    )
    .where(*isolation_and_filters)
    .order_by(distance.asc())
    .limit(settings.rag_vector_top_k)
)
```

### 4.2 Branch B — PostgreSQL full-text search

Top-K: **20** (`settings.rag_fts_top_k`), symmetrical with the vector branch so neither
side dominates the RRF merge; `websearch_to_tsquery` gives users Google-style syntax
(`"retry strategy" OR DLQ -kafka`) without a parser of our own.

```sql
SELECT
    kc.id,
    kc.source_type,
    kc.source_id,
    kc.section,
    kc.content,
    kc.metadata,
    ts_rank_cd(
        to_tsvector('english', kc.content),
        websearch_to_tsquery('english', CAST(:q AS text)),
        32                                   -- rank normalisation flag: rank/(rank+1)
    ) AS fts_rank
FROM knowledge_chunks AS kc
WHERE (kc.user_id IS NULL OR kc.user_id = CAST(:user_id AS uuid))
  AND to_tsvector('english', kc.content)
      @@ websearch_to_tsquery('english', CAST(:q AS text))
  AND (CAST(:source_types AS text[]) IS NULL
       OR kc.source_type = ANY(CAST(:source_types AS text[])))
  AND (CAST(:exclude_source_id AS text) IS NULL
       OR kc.source_id <> CAST(:exclude_source_id AS text))
ORDER BY fts_rank DESC, kc.updated_at DESC
LIMIT CAST(:k AS integer);                   -- :k = 20
```

* `to_tsvector('english', kc.content)` is computed on the fly for now, which is why this
  branch is only acceptable at the current scale (a few thousand rows). The moment p95
  exceeds the latency budget, the fix is a `content_tsv tsvector` **generated column**
  (`GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`) plus
  `CREATE INDEX ... USING GIN (content_tsv)` — recorded as a deferred step in §5.6, with the
  query text unchanged apart from swapping the expression for the column.
* Query sanitation: the raw user message goes to `websearch_to_tsquery` **as-is**. It never
  parses to SQL and it never throws on malformed input (it degrades to a plain-`to_tsquery`
  behaviour); no manual escaping is added, because escaping would break the syntax it exists
  to support.
* If `websearch_to_tsquery` yields an empty tsquery (the message was all stop-words, e.g.
  "why is this wrong"), the branch returns 0 rows and RRF falls back to the vector branch
  alone. This is expected and must not be treated as an error.
* A per-term OR is **not** used; `websearch_to_tsquery` already implements the right default
  (AND of terms, OR for quoted alternatives).

### 4.3 RRF merge (k = 60)

Reciprocal Rank Fusion, written out explicitly:

```
score(d) = Σ over branches b ∈ {vector, fts} of  1 / (k + rank_b(d)),   k = 60

  rank_b(d) = 1-based position of document d in branch b's ordered result list
  if d does not appear in branch b, that branch contributes 0 (d is not penalised,
  it simply gains nothing)
```

With `k = 60` the two branches' contributions are:

| rank | 1/(60+rank) | ≈ |
|---|---|---|
| 1 | 1/61 | 0.01639 |
| 2 | 1/62 | 0.01613 |
| 5 | 1/65 | 0.01538 |
| 10 | 1/70 | 0.01429 |
| 20 | 1/80 | 0.01250 |

Properties this buys: (a) a document ranked **1st by both** branches scores 0.03279 — more
than double any single-branch winner, which is exactly the "agree on this" signal we want;
(b) a document ranked 1st by one branch and absent from the other (0.01639) still beats a
document ranked 20th by both (0.02500 → no: 0.01250 × 2 = 0.02500, which *is* higher) — so
consistent mid-rank agreement outranks a single top hit, i.e. recall beats a lucky keyword
match; (c) `k = 60` is the value the contract fixes, and it flattens the curve enough that
being 20th rather than 1st costs only ~24 % of the contribution, which prevents the vector
branch's top hit from monopolising the merge.

Implementation:

```python
def rrf_merge(
    branches: dict[str, list[Row]],     # {"vector": [...], "fts": [...]}
    *,
    k: int = 60,
) -> list[FusedHit]:
    scores: dict[uuid.UUID, float] = defaultdict(float)
    ranks:  dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    rows:   dict[uuid.UUID, Row] = {}

    for branch_name, hits in branches.items():
        for rank, hit in enumerate(hits, start=1):     # 1-based
            scores[hit.id] += 1.0 / (k + rank)
            ranks[hit.id][branch_name] = rank
            rows.setdefault(hit.id, hit)

    fused = [
        FusedHit(
            row=rows[chunk_id],
            rrf_score=score,
            ranks=ranks[chunk_id],
            # tie-breakers, in order: how many branches agreed, best single rank, recency
            branch_count=len(ranks[chunk_id]),
            best_rank=min(ranks[chunk_id].values()),
        )
        for chunk_id, score in scores.items()
    ]
    fused.sort(key=lambda h: (-h.rrf_score, -h.branch_count, h.best_rank))
    return fused
```

`branch_count` is the tie-breaker rather than recency on purpose: two branches agreeing is
stronger evidence of relevance than a newer chunk, and `updated_at` sorting would let a
recently-touched but irrelevant chunk win ties.

### 4.4 Metadata filter (isolation + scoping)

Applied **inside both SQL queries** (not after the merge, so each branch's `LIMIT k` is spent
on rows the caller is allowed to see) and then again defensively on the fused list:

```python
# 1. isolation — the user's own partition, plus the shared global curriculum
or_(KnowledgeChunk.user_id.is_(None), KnowledgeChunk.user_id == user_id)

# 2. model hygiene — never mix vectors from different embedding models
KnowledgeChunk.embedding_model == settings.embedding_model

# 3. source scoping — optional; DSA requests can restrict to dsa_problem/note/snippet
KnowledgeChunk.source_type.in_(source_types) if source_types else true()

# 4. self-exclusion — never retrieve the entity the user is currently editing
KnowledgeChunk.source_id != exclude_source_id if exclude_source_id else true()

# 5. post-merge guard (defence in depth)
[hit for hit in fused if hit.row.user_id is None or hit.row.user_id == user_id]
```

| Filter | Value for a DSA tutor request |
|---|---|
| `user_id` | the authenticated user (from `CurrentUser.id`) |
| `source_types` | `None` (all) — a DSA question may legitimately want an LLD paragraph about the same pattern |
| `exclude_source_id` | the current `context_id` (so the tutor is not handed the user's own current text back as if it were a memory) |
| `min_score` | `settings.rag_min_score` = 0.0 |

Final selection: take the fused list, apply `rag_min_score`, **cap at
`settings.rag_final_top_k = 6`**, and additionally **cap any single
`(source_type, source_id)` at 2 chunks** so one long note cannot occupy the whole slice. If
fewer than 5 survive (short curricula, weak query), that is fine — the contract says 5–8, and
3 good chunks beat 6 padded ones. Never pad from outside the filter to hit a number.

The retrieval result carries the provenance needed to render citations and to log without
content:

```python
@dataclass(slots=True)
class RetrievedChunk:
    id: uuid.UUID
    source_type: str
    source_id: str
    section: str
    content: str
    rrf_score: float
    ranks: dict[str, int]           # e.g. {"vector": 3, "fts": 11}
    metadata: dict[str, Any]
```

### 4.5 Exactness first, HNSW later

Per contract §6: **exact search first**. A sequential scan with `<=>` over ≤ ~2 000 rows is
single-digit milliseconds on the Supabase free tier and has 100 % recall — an ANN index at
this scale only *loses* quality. `vector_cosine_ops` HNSW is added only when p95 retrieval
latency exceeds 50 ms, as a separate migration, with `m=16, ef_construction=64` and
`SET LOCAL hnsw.ef_search = 40` per query. `EXPLAIN (ANALYZE, BUFFERS)` on the vector query
is a required part of the indexing acceptance test so the switch point is measured, not
guessed.


---

## 5. Unique index and duplicate prevention

### 5.1 The NULL problem

The contract's dedupe key is
`(source_type, source_id, section, coalesce(user_id, '00000000-…'))`. The reason the
`coalesce` is mandatory: in PostgreSQL, **`NULL` is not equal to `NULL`** in a unique index
(or in a `UNIQUE` constraint, or in an `ON CONFLICT` inference). Two global rows with
`user_id = NULL`, identical `source_type`/`source_id`/`section`, are therefore *distinct* to a
plain `UNIQUE (source_type, source_id, section, user_id)` index. The global curriculum — 90
DSA problems + 20 LLD topics + 20 HLD topics, all `user_id IS NULL` — is exactly the case
that would silently accumulate duplicates on every seed run. The `coalesce` collapses every
`NULL` to one sentinel UUID, so the index sees a real, comparable value.

### 5.2 DDL

`0004_ai_rag_foundation` performs the following. The sentinel is
`'00000000-0000-0000-0000-000000000000'`, a valid UUID that `gen_random_uuid()` can never
produce, so it cannot collide with a real user id.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NULL,                 -- NULL = global curriculum
    source_type      text NOT NULL
                     CHECK (source_type IN ('dsa_problem','lld_topic','hld_topic',
                                            'note','snippet','conversation_summary')),
    source_id        text NOT NULL,             -- DSA slug (TEXT) or topic UUID as text
    section          text NOT NULL,             -- "functional_requirements", "caching", ...
    content          text NOT NULL,
    embedding        vector(768),
    metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
    content_hash     text NOT NULL,
    embedding_model  text NOT NULL,             -- "gemini-embedding-2"

    -- Generated, STORED: the NULL-safe key that the unique index is built on.
    user_bucket      uuid GENERATED ALWAYS AS (
                         COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid)
                     ) STORED,

    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- The dedupe key from 05-contract-ai.md §6, expressed with a real (never-NULL) column so
-- a unique index can actually be built on it.
CREATE UNIQUE INDEX uq_knowledge_chunks_identity
    ON knowledge_chunks (source_type, source_id, section, user_bucket);

CREATE INDEX ix_knowledge_chunks_user_id_source
    ON knowledge_chunks (user_id, source_type, source_id);

CREATE INDEX ix_knowledge_chunks_source_lookup
    ON knowledge_chunks (source_type, source_id, section);

-- Optional for the FTS branch's future generated column; NOT created now (see 5.6).
-- CREATE INDEX ix_knowledge_chunks_content_gin
--     ON knowledge_chunks USING GIN (to_tsvector('english', content));
```

Why a `GENERATED ALWAYS AS (...) STORED` column rather than an expression index on
`COALESCE(user_id, ...)`:

* An expression index `ON knowledge_chunks (source_type, source_id, section, COALESCE(user_id, '00000000-...'::uuid))`
  also works and is a legitimate alternative — but PostgreSQL's `ON CONFLICT` inference
  requires the conflict target expression to match the index **textually**, which is
  brittle in SQLAlchemy: `pg_insert(...).on_conflict_do_update(index_elements=[...])` cannot
  express a `COALESCE(...)` target, so the upsert would have to fall back to
  `constraint="uq_knowledge_chunks_identity"` and hand-written DDL drift becomes likely.
  With a real `user_bucket` column, `index_elements=["source_type","source_id","section","user_bucket"]`
  is a plain column list and the ORM and the DDL can never disagree.
* The stored column costs 16 bytes per row — ~20 KB for the entire global curriculum. Free.
* `GENERATED ... STORED` cannot be written to explicitly, so `user_bucket` can never drift
  from `user_id`.

The SQLAlchemy model (`app/db/models/knowledge.py`):

```python
class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id", "section", "user_bucket",
                         name="uq_knowledge_chunks_identity"),
        Index("ix_knowledge_chunks_user_id_source", "user_id", "source_type", "source_id"),
        Index("ix_knowledge_chunks_source_lookup", "source_type", "source_id", "section"),
        CheckConstraint(
            "source_type IN ('dsa_problem','lld_topic','hld_topic','note','snippet','conversation_summary')",
            name="source_type_valid",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)   # TEXT, not UUID: DSA ids are slugs
    section: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False,
                                            server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    user_bucket: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        # Read-only mirror of COALESCE(user_id, <sentinel>) — the DB computes it.
        server_default=text("COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
        nullable=False,
        insert_default=None,
    )
```

`user_bucket` is declared with `Computed(...)` in SQLAlchemy so the ORM never includes it in
an `INSERT` column list:

```python
from sqlalchemy import Computed
user_bucket = mapped_column(
    PGUUID(as_uuid=True),
    Computed("COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid)", persisted=True),
    nullable=False,
)
```

### 5.3 What duplicate prevention actually buys

* Re-running the global seed is idempotent at the **database** level as well as the hash
  level — even a bug in the hash short-circuit cannot create two `hld_topic / <id> / caching`
  rows.
* Concurrent indexers (two uvicorn workers, or a seed running while a write hook fires)
  cannot race into duplicates: the second `INSERT` hits the unique index and the upsert's
  `ON CONFLICT` turns it into an update instead of an error.
* `ON CONFLICT` inference needs exactly this index; without it the `pg_insert(...).on_conflict_do_update(...)`
  call raises `InvalidColumnReference`.
* A user's chunk and a global chunk for the same `source_id`/`section` coexist legitimately
  (different `user_bucket`), which is what makes "my notes override the curriculum" possible
  in the ranking without any schema trickery.

### 5.4 Verifying it

```sql
-- Assert zero duplicates after a double seed run.
SELECT source_type, source_id, section, user_bucket, count(*)
FROM knowledge_chunks
GROUP BY 1,2,3,4
HAVING count(*) > 1;
-- expected: 0 rows

-- Assert the global partition is populated exactly once.
SELECT count(*) FROM knowledge_chunks WHERE user_id IS NULL;   -- expected: 1290 (see §12)
SELECT count(DISTINCT user_bucket) FROM knowledge_chunks WHERE user_id IS NULL;  -- expected: 1
```

### 5.5 Cleanup of pre-existing duplicates

If the table ever exists without the unique index (e.g. a hand-applied early version), the
migration's first statement is:

```sql
DELETE FROM knowledge_chunks kc
USING knowledge_chunks older
WHERE kc.id <> older.id
  AND kc.source_type  = older.source_type
  AND kc.source_id    = older.source_id
  AND kc.section      = older.section
  AND COALESCE(kc.user_id, '00000000-0000-0000-0000-000000000000'::uuid)
    = COALESCE(older.user_id, '00000000-0000-0000-0000-000000000000'::uuid)
  AND kc.updated_at < older.updated_at;     -- keep the newest of each identity
```

run **before** `CREATE UNIQUE INDEX`, otherwise the index creation fails on legacy data.

### 5.6 Deferred (deliberately not in 0004)

| Deferred item | Trigger to add it |
|---|---|
| `HNSW` index, `vector_cosine_ops` | vector-branch `EXPLAIN ANALYZE` p95 > 50 ms, or > ~20 k rows |
| Generated `content_tsv` + GIN index | FTS branch p95 > 30 ms (recomputing `to_tsvector` per row is the first thing to break) |
| `source_type`-partial indexes | a single source type dominating the table |
| Sharding/partitioning by `user_id` | > 500 k rows |
| `pg_trgm` fallback for typo'd keywords | users reporting missed exact-term searches |

---

## 6. User isolation

### 6.1 The clause (exact, repeated wherever chunks are read)

```sql
WHERE (user_id IS NULL OR user_id = CAST(:user_id AS uuid))
```

* `user_id IS NULL` → the shared global curriculum (identical for every user, contains no
  personal data).
* `user_id = :user_id` → the caller's own chunks.
* Anything else — **including another user's `user_id`** — is unreachable by construction.
  There is no query path in `KnowledgeChunkRepository` that takes a chunk id and returns the
  row without this predicate: `get_by_id(user_id=..., chunk_id=...)` includes it, and the
  private helper `_scoped(user_id)` is the only way a `SELECT` is built.

Reinforcement, because SQL is not the only place this can go wrong:

1. **Never** a `WHERE user_id = :uid` on the global branch — the `OR` is mandatory, and the
   global curriculum would disappear if it were dropped.
2. The predicate appears in **both** branches (§4.1, §4.2) *and* as a post-merge guard
   (§4.4) — three independent places. A future refactor that drops one still cannot leak.
3. The `user_id` value comes from `CurrentUser.id` (`app/api/v1/dependencies.py`), i.e. the
   verified Supabase JWT `sub`. It is **never** read from the request body, a query
   parameter, or `page_context`. The RAG request schema deliberately has no
   `user_id` field for a client to send.
4. `RetrievalService.search` asserts the guard after the merge and logs
   `ERROR RAG isolation violation` plus raises `ForbiddenError` if it ever sees a foreign row.
   A failing assertion here means a query bug, and it must be loud rather than silently
   filtered.
5. Chunk deletion for a re-index is scoped by `user_id` too, so user A's re-index can never
   delete user B's rows.
6. `knowledge_chunks` is written **only** by backend code paths using the service-role
   connection. There is no client-facing insert/update route.

### 6.2 The test that proves it

`tests/test_rag_isolation.py` (new), marker `db`, two real users:

```python
@pytest.mark.db
async def test_user_a_cannot_retrieve_user_b_chunks(services, two_users, session):
    user_a, user_b = two_users          # two distinct uuid.UUIDs, two JWTs
    secret = "My unique HLD mistake: I sized the Redis cluster before the write QPS."

    # --- arrange: B indexes a private note containing a highly distinctive phrase
    b_topic = await make_hld_topic(session)
    await services.knowledge.index_notes(
        user_id=user_b.id, source_type="note",
        source_id=str(b_topic.id), kind="hld",
    )
    # ensure the phrase is actually in B's chunk
    assert await session.scalar(
        select(func.count()).select_from(KnowledgeChunk)
        .where(KnowledgeChunk.user_id == user_b.id,
               KnowledgeChunk.content.ilike("%sized the Redis cluster%"))
    ) == 1

    # --- act: A searches for B's exact phrase, through the real service + real SQL
    hits = await services.rag.search(
        user_id=user_a.id,
        query="sized the Redis cluster before the write QPS",
        final_top_k=20,                 # deliberately huge: no top-K truncation to hide behind
        source_types=None,
    )

    # --- assert: nothing of B's comes back, in either branch
    assert all(hit.row.user_id != user_b.id for hit in hits)
    assert not any("sized the Redis cluster" in hit.content for hit in hits)

    # --- assert: the raw SQL itself refuses, i.e. it is not merely a post-filter
    raw = await session.execute(text("""
        SELECT count(*) FROM knowledge_chunks
        WHERE (user_id IS NULL OR user_id = CAST(:uid AS uuid))
          AND content ILIKE '%sized the Redis cluster%'
    """), {"uid": str(user_a.id)})
    assert raw.scalar_one() == 0

    # --- assert: the FTS branch alone is also isolated (branch-level proof)
    fts_only = await services.rag._fts_branch(
        user_id=user_a.id, query="sized the Redis cluster", k=50, source_types=None,
        exclude_source_id=None,
    )
    assert all(getattr(row, "user_id", None) != user_b.id for row in fts_only)

    # --- assert: the vector branch alone is also isolated
    vec_only = await services.rag._vector_branch(
        user_id=user_a.id, query="sized the Redis cluster", k=50, source_types=None,
        exclude_source_id=None,
    )
    assert all(getattr(row, "user_id", None) != user_b.id for row in vec_only)
```

Companion tests in the same file:

| Test | Assertion |
|---|---|
| `test_user_a_sees_global_curriculum` | A retrieves `user_id IS NULL` chunks (the `OR` half is not accidentally dropping the curriculum) |
| `test_user_b_retrieves_own_chunk` | The identical query **does** return B's chunk for B — proves the arrange step was valid and the isolation test is not passing for the wrong reason |
| `test_get_by_id_refuses_foreign_chunk` | `repo.get_by_id(user_id=A, chunk_id=<B's chunk>)` raises `NotFoundError`, not a leak + a permission error that reveals existence |
| `test_reindex_scoped_to_user` | A's re-index of a shared topic id leaves B's row for that topic untouched |
| `test_foreign_user_id_in_payload_is_ignored` | A request body carrying `"user_id": B` (a hostile client) has no effect: the schema has no such field, and the service uses `CurrentUser.id` |
| `test_isolation_violation_raises_forbidden` | Monkeypatching the post-merge guard to return a foreign row raises `ForbiddenError` and logs at `ERROR` |

### 6.3 Optional defence in depth: RLS

Supabase Row Level Security is **already** described as staying in place for the existing
tables (`06-migration-plan.md` CN-006). For `knowledge_chunks` the backend connects with a
service-role credential that bypasses RLS, so RLS is not the mechanism — the `WHERE` clause
is. If a future read path is ever exposed to a user-scoped token, the policy would be:

```sql
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY knowledge_chunks_read_own_or_global ON knowledge_chunks
    FOR SELECT USING (user_id IS NULL OR user_id = auth.uid());
```

Not enabled now, deliberately: enabling RLS on a table the service-role writes to adds a
failure mode ("writes mysteriously stop working") with no security benefit while every read
goes through FastAPI.


---

## 7. Context builder

### 7.1 Assembly order (contract §8, order matters)

`ContextBuilder.build(...)` assembles **exactly five parts, in this order**. The order is not
cosmetic: providers weight the beginning and end of a prompt more heavily, and the parts are
ordered by decreasing immediacy (what the user is looking at *right now* first, the oldest
conversational context last).

| # | Part | Source | Purpose |
|---|---|---|---|
| 1 | Current unsaved `PageContext` | the request body (`page_context`), never the DB | "Why is my approach wrong?" must be answered against the code the user has *not yet saved* — contract §1, scenario 1 |
| 2 | Structured DB info for the entity | `DSAProblemRepository.get_with_progress`, `LLDRepository/HLDRepository.get_with_progress` + notes | The durable, trusted facts: title, topic, patterns, the user's saved notes and progress |
| 3 | Relevant hybrid RAG chunks | `RetrievalService.search` (§4) | The user's own history and the curriculum: "have I made this mistake before?" — scenario 5 |
| 4 | Conversation summary | `ai_conversations.conversation_summary` | Everything said more than 12 turns ago, distilled to ~600 tokens |
| 5 | Recent messages (8–12) | `AIMessageRepository.recent_history` | Verbatim local context, exactly as today's `history_for_prompt` window |

The result is a `TutorContext` (existing class in `app/services/ai/prompts.py`) extended with
two new optional fields — `page_context: dict[str, Any] | None` and
`rag_chunks: list[dict[str, Any]]` — so `TutorContext.summary()` keeps working unchanged and
every existing consumer of `build_system_prompt` keeps compiling.

### 7.2 Rendered shape

`TutorContext.render()` gains two sections; the existing sections keep their current wording
so nothing already accepted changes. The final prompt is:

```
[BASE_SYSTEM_PROMPT]                        (existing, unchanged)

[ACTION_PROMPTS[action]]                    (existing, unchanged)

### What the user is looking at right now
The user's unsaved editor state. Treat this as the most current truth.
- page_type: dsa_problem
- active_tab: code
- focused_field: mistakes
- selected_text: "..."
- code (python):
```python
<unsaved code, truncated to MAX_CODE_CHARS = 20 000>
```
- draft fields (not yet saved):
**approach**
<draft approach, truncated per-part>
**mistakes**
<draft mistakes, truncated per-part>

### Problem context                            (existing section, part 2)
- title: Subarray Sum Equals K
- difficulty: medium
- primary_topic: arrays
- patterns: Prefix Sum, Hash Map
...
### The user's current progress                (existing section, part 2)
### The user's own notes                       (existing section, part 2)

### Related history and curriculum            (NEW — part 3)
Retrieved from the user's own notes and the curriculum. May be incomplete or
out of date; the sections above take precedence when they disagree.
Each excerpt is labelled with where it came from.

[1] your note — Subarray Sum Equals K / mistakes  (relevance 0.0291)
I keep forgetting to seed the hash map with {0: 1}, which breaks the
count when the prefix sum itself equals k.

[2] curriculum — URL Shortener / caching  (relevance 0.0274)
Use Redis with a 60 s TTL for the redirect lookup; ...

### Earlier in this conversation                (NEW — part 4)
<conversation_summary, ~600 tokens>

### Recent messages                              (part 5)
(last 8-12 turns, injected as provider turns rather than inside the system prompt)

[REVEAL_OVERRIDE]                              (existing, conditional)
```

Two rendering rules that matter:

* **Part 3 includes attribution.** Every chunk is prefixed with `your note — <title> /
  <section>` or `curriculum — <title> / <section>` and its RRF score, because the tutor's
  guardrail is "if the provided context is insufficient, say what you would need instead of
  guessing" — it can only honour that if it can tell "my own note" from "the shared
  curriculum". A chunk from another user can never appear here (§6).
* **Part 4 and 5 are never both empty.** If there is no summary but there are messages, only
  part 5 renders; if a conversation has been summarised down to zero recent messages (it
  cannot — the window keeps the last 12), part 4 carries the thread.
* Parts 4 and 5 **do not** use the "unsaved draft" warning wording: they are transcript, and
  labelling them as unreliable would make the tutor second-guess the user's own prior turns.

### 7.3 Token budget per part

Budget unit is tokens, estimated as `len(text) // 4` — the same approximation used in §2.5,
so the two systems cannot disagree about what "600 tokens" means.

| # | Part | Budget (tokens) | Hard floor | Overflow behaviour |
|---|---|---|---|---|
| 1 | `PageContext` | **1 200** | 200 | Code is truncated first (largest, most compressible), then `draft_fields` on a character boundary; `active_tab` / `focused_field` / `selected_text` are never dropped. `selected_code` is additionally capped at the existing `MAX_CODE_CHARS = 20 000` **characters** (~5 000 tokens) *before* the token budgeter sees it |
| 2 | Structured DB info | **1 200** | 300 | Existing per-field cap of 1 500 chars in `select_note_fields` stays; when the budget still overflows, note fields are dropped in reverse priority order (see below) |
| 3 | RAG chunks | **1 500** | 0 | Drop the lowest-RRF chunks one at a time until it fits. A chunk is never truncated mid-sentence — a half-chunk is worse than a missing one. Minimum useful: 0 (retrieval is an enhancement, not a precondition) |
| 4 | Conversation summary | **600** | 0 | The summariser is *told* to produce ≤ 600 tokens, so overflow here is a bug; if it happens, truncate at the last complete bullet |
| 5 | Recent messages | **1 500** | 0 | Drop the **oldest** message first, then re-check; never drop the final user turn (it is the actual question — it is also the message the provider reads as the prompt) |
| — | System prompt + action + guardrails | ~700 | — | Fixed, never budgeted away |
| — | Reserve for the model's reply | `ai_stream_max_tokens` = 1 400 | — | Never spent on input |
| | **Total input budget** | **`ai_context_budget_tokens` = 6 000** | | |

Sanity check: 1 200 + 1 200 + 1 500 + 600 + 1 500 + 700 = 6 700, which exceeds 6 000 by
design — the per-part numbers are **caps**, and the allocator enforces the total. In the
common case most parts are far under their cap (a short page context, 3 RAG chunks, no
summary), and the sum lands near 3 000.

### 7.4 Truncation priority when the total budget is exceeded

The allocator is: compute every part's natural size → if the sum is under budget, ship it
unchanged (the common case) → otherwise apply reductions **in this order**, re-checking the
total after each step and stopping as soon as it fits:

1. **Conversation summary → halve** (600 → 300 → 150 → 0). It is the most compressible part:
   it is already a paraphrase, so a shorter paraphrase loses the least information per token.
2. **RAG chunks → drop from the bottom of the RRF ranking**, one at a time, but **stop at 3
   chunks**. Below three, the retrieval step stops paying for itself and the prompt would be
   better off with the tokens spent on parts 1–2. (This is why the effective RAG minimum on
   overflow is 3, while the theoretical floor in the table is 0.)
3. **Draft fields → truncate each draft to 1 500 chars**, then drop the lowest-priority
   draft field entirely. Draft priority = `focused_field` first, then fields listed in the
   contract's `focused_field` enum order (`approach`, `mistakes`, `notes`, `revision_notes`,
   `requirements`, `architecture`, `tradeoffs`, `failure_handling`, …). The field the user is
   actually typing in is the last thing to go — losing it defeats the feature.
4. **Notes (part 2) → drop fields** in reverse priority: `design_notes`,
   `interview_notes`, `final_notes`, `secondary_topics`, `companies`, `key_concepts` first;
   `approach`, `mistakes`, `tradeoffs`, `failure_handling` last. `title`, `primary_topic`,
   `patterns`, `status`, `confidence` and `difficulty` are **never** dropped: they are the
   minimum viable context, and the tutor is explicitly told not to invent constraints.
5. **Unsaved code → truncate from the middle**, keeping the first 60 % and the last 40 %
   (the signature/imports at the top and the failing loop at the bottom are what matter),
   down to a 2 000-char floor, then drop to the 2 000-char tail only.
6. **Recent messages → shrink the window** 12 → 8 (the contract's floor), dropping oldest
   first, never the current turn.
7. If it *still* does not fit, log `WARNING context budget exceeded after all reductions`
   with the per-part sizes and ship the result anyway rather than failing the request. The
   provider's own context limit is the last backstop, and a too-long prompt is a bug to fix,
   not an error to show a user mid-conversation.

The inverse rule also matters: **never pad**. There is no "fill the budget" step. A prompt
with 2 800 useful tokens is better than the same prompt plus 3 200 tokens of low-relevance
chunks, and it is cheaper.

### 7.5 What is recorded in `context_used`

`AIChatResponse.context_used` is the only thing the client and logs see — never the prompt.
It is `TutorContext.summary()` extended with:

```json
{
  "context_type": "dsa",
  "has_entity": true,
  "entity_fields": ["companies", "difficulty", "patterns", "primary_topic", "title"],
  "notes_fields": ["approach", "mistakes"],
  "has_progress": true,
  "progress_status": "attempted",
  "has_code": true,
  "code_chars": 412,
  "history_messages": 9,
  "page_context": { "has_drafts": true, "draft_fields": ["approach", "mistakes"],
                    "has_selection": false, "has_unsaved_code": true, "active_tab": "code" },
  "rag": { "chunks": 5, "sources": ["note", "hld_topic"], "sections": ["mistakes", "caching"],
           "top_score": 0.0291, "branches": {"vector": 5, "fts": 3},
           "degraded": false },
  "summary": { "present": true, "tokens": 512, "version": 3 },
  "budget": { "used_tokens": 3410, "limit_tokens": 6000, "reductions": ["summary_halved"] }
}
```

Field names and counts only — no note text, no code, no chunk content. This keeps the log
stream free of private data while still making "why did the tutor miss X?" answerable.

---

## 8. Conversation summary

### 8.1 When it is regenerated

Two triggers, whichever fires first, evaluated **after** the assistant turn is persisted:

```
regenerate_summary  ⟺  messages_since_summary >= settings.ai_summary_message_threshold  (16)
                    OR  unreSummarised_tokens  >= settings.ai_summary_token_threshold     (1500)
```

**Message-count threshold: 16 messages (8 user/assistant exchanges).** Justification:

* The prompt window is 12 messages. Summarising at 16 means the summary is regenerated when
  the transcript has *just* grown past the window — i.e. at the first moment there is
  something the window can no longer carry. Summarising at 12 would regenerate on a thread
  that the window can still cover entirely; summarising at 24 would let four messages fall
  out of memory before anything recorded them.
* 8 (too eager) vs 40 (too lazy) are the realistic alternatives. 8 regenerates on nearly
  every third turn, roughly doubling the LLM calls for a long conversation; 40 means a
  ~20-exchange thread where the model has already lost the middle. 16 keeps the write
  amplification at roughly one extra call per 8 user turns — on a 60-request/hour rate limit
  (`ai_rate_limit_per_hour`) that is a bounded, small overhead.
* It is a power of two, which makes the "messages since summary" watermark arithmetic
  obvious and testable (`watermark % 2 == 0` boundaries).

**Token threshold: 1 500 unre-summarised tokens.** A single pasted 5 000-character note
followed by one question is 2 messages but ~2 500 tokens of substance; the count trigger
would never fire and the window would silently truncate a real answer. 1 500 is ~2.5× the
summary's own 600-token target, so it also guarantees the summary is always a genuine
compression and never a copy.

**Watermark.** `ai_conversations.conversation_summary` (text, nullable — contract §7) stores
the text. The *position* of the summary is stored alongside it as
`ai_conversations.summary_watermark_message_id uuid NULL` — a new additive column in
migration 0004 — because a message count alone is wrong when a conversation is soft-deleted
mid-thread or a device replays a sync. "Messages since summary" then means exactly: messages
in this conversation with `created_at > <that message's created_at>`. `summary_version int`
(also additive) increments on each regeneration so a summary can be traced to the transcript
state that produced it.

**Cost control.**

* The summary call is **not** rate-limited against the user's counter — it is a server-side
  maintenance call, and charging it would make a user hit their limit for reasons they did
  not cause. It is bounded instead by construction (≤ 1 per 8 exchanges).
* It runs **after** the assistant message is committed and the response is returned — on the
  streaming path, after the `done` event — so it never adds latency to the user's turn.
* It uses `settings.ai_model` but with `temperature=0.2` (deterministic, no creativity) and
  `max_tokens=700`.
* Failure to summarise is non-fatal: log `WARNING`, leave the previous summary and watermark
  in place, and retry on the next trigger. A stale summary is far better than a lost thread.
* When regeneration succeeds and `rag_index_conversation_summaries` is true, the single
  `conversation_summary` chunk is upserted (§2.7) — same `source_id`/`section`, so the
  conversation contributes one chunk, not a history of summaries.

### 8.2 Exact prompt shape

Two messages, no system prompt (the summariser is not the tutor and must not inherit the
pedagogy guardrails — it needs to be able to restate an answer the tutor only hinted at).

**Message 1 — `user`, the entire instruction (verbatim):**

```
You are compressing a transcript for a study-tutor application so it can be replayed
to the tutor later as background. You are not answering the student. You are writing
notes for whoever continues this conversation.

Produce a summary of the transcript between <TRANSCRIPT> and </TRANSCRIPT>.

Hard requirements:
- At most 600 tokens. Shorter is better.
- Use these five headed sections, in this order. Omit a section only if it has no content.
  Topics: the problems/topics discussed, by name.
  User's stated understanding: what the student said they already know, and any position
  they defended, even if it was wrong.
  Mistakes and gaps: concrete errors, misconceptions, or omissions identified so far.
  Advice already given: each suggestion or hint already delivered, one line each, so it is
  not repeated.
  Open threads: questions left unanswered and what the student said they would try next.
- Preserve the student's own terminology and the exact names of algorithms, patterns and
  system components. Do not paraphrase "prefix sum" into "cumulative sum".
- Write in the third person, present tense, about the student.
- No greetings, no preamble, no code blocks, no restatement of your instructions.
- Do not invent facts. If something is unclear, omit it rather than guessing.
```

**Message 2 — `user`, the payload:**

```
<PREVIOUS_SUMMARY>
{conversation_summary or "(none — this is the first summary)"}
</PREVIOUS_SUMMARY>

<TRANSCRIPT>
[user] Why is my approach wrong?
[assistant] Sliding window breaks when negative values are present because…
[user] So should I use prefix sums?
[assistant] Yes — and remember to seed the map with {0: 1}.
…
(only the messages after the previous watermark, oldest first, each line prefixed
 with [user] or [assistant]; assistant messages that carry error set are excluded,
 matching AIMessageRepository.recent_history's existing filter)
</TRANSCRIPT>
```

Notes on the shape:

* The instruction is a **user** message, not a system prompt, so it is portable across
  providers that handle `systemInstruction` differently (Gemini's `systemInstruction` is a
  separate REST field — see `GeminiProvider.chat`) and so a cached prefix is reused: the
  instruction block is byte-identical every time, which is what makes any future prompt
  caching pay off.
* **Instructing the model to include "advice already given"** is the single most valuable
  section: it is what stops the tutor from repeating the same hint on turn 20 that it gave
  on turn 3 — the concrete failure mode that makes a long tutor thread feel broken.
* The previous summary is fed back in so the new summary is an **incremental merge**, not a
  re-derivation; it also bounds the transcript passed in (previous summary ≈ 600 tokens +
  the new messages).
* Truncation guard: if the transcript for this call exceeds 4 000 tokens, it is itself
  trimmed to the **most recent** 4 000 tokens, because the old material is what the
  `<PREVIOUS_SUMMARY>` already covers.

### 8.3 The summarised window

`history_for_prompt(messages, max_messages=settings.ai_max_history_messages)` is unchanged
(12). The only change is that the window now starts **after** the watermark:

```python
recent = await self._messages.recent_history(
    user_id=user_id,
    conversation_id=conversation.id,
    limit=settings.ai_max_history_messages + 1,      # +1 to exclude the just-inserted turn
)
prior = [m for m in recent if m.id != user_message.id]
prior = [m for m in prior if m.created_at > summary_watermark_created_at]
history = [ChatMessage(role=t["role"], content=t["content"])
           for t in history_for_prompt(prior, max_messages=settings.ai_max_history_messages)]
```

Anything before the watermark is represented by the summary instead — never by both, which is
what would otherwise double the token cost of the middle of a conversation.


---

## 9. Tutor action validation

`TutorActionService` implements contract §3–§4. Its job, in contract order:
**authorize → validate → apply → audit.** The model emits a *proposal*; this service is the
only thing that can turn it into a write. The model never emits SQL, and no field name from
the model is ever interpolated into a query.

### 9.1 Schema

```python
class TutorActionTarget(BaseModel):
    entity_type: Literal["dsa", "lld", "hld"]
    entity_id: str                       # DSA slug, or topic UUID as text
    field: str | None = None

class TutorAction(BaseModel):
    id: uuid.UUID
    type: Literal["set_field", "append_field", "replace_selection", "create_note",
                  "create_code_snippet", "update_code", "set_confidence", "set_status",
                  "schedule_revision", "create_revision_note"]
    target: TutorActionTarget
    value: Any
    status: Literal["pending", "applied", "rejected", "failed"] = "pending"
    # provenance, additive to the contract's example JSON
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    error_code: str | None = None
    created_at: datetime
    applied_at: datetime | None = None
```

`GET /api/v1/ai/actions` (§1 of `04-contract-openapi.md`) stays a static menu. The persisted
proposals are exposed at a **new** route `GET /api/v1/ai/actions/pending?status=pending`
(and `?conversation_id=`), because reusing the existing route would silently change its
response type and break the clients that read it as `AIActionsResponse`.

### 9.2 Validation checklist (code-shaped pseudocode)

```python
class TutorActionService:
    #: Editable field per entity type. Anything not in this map is not writable by an action.
    EDITABLE_FIELDS: dict[str, frozenset[str]] = {
        # ProblemNote columns (app/db/models/dsa.py)
        "dsa": frozenset({"approach", "notes", "mistakes", "revision_notes",
                          "time_complexity", "space_complexity"}),
        # LLDNote columns (app/db/models/lld.py)
        "lld": frozenset({"summary", "design_explanation", "class_responsibilities",
                          "relationships", "design_notes", "mistakes", "revision_notes"}),
        # HLDNote columns (app/db/models/hld.py) — all 15
        "hld": frozenset({"functional_requirements", "non_functional_requirements",
                          "capacity_estimation", "apis", "data_model",
                          "high_level_architecture", "database_choice", "caching",
                          "queues", "scaling", "failure_handling", "tradeoffs",
                          "final_notes", "interview_notes", "mistakes"}),
    }
    NOTE_DOCUMENT_ENTITIES = frozenset({"dsa", "lld", "hld"})   # create_note is valid for all three
    SNIPPET_ENTITIES       = frozenset({"dsa", "lld", "hld"})   # create_code_snippet / update_code
    CONFIDENCE_ENTITIES    = frozenset({"dsa", "lld", "hld"})   # set_confidence
    SCHEDULE_ENTITIES      = frozenset({"dsa"})                 # schedule_revision is DSA-only
    REVISION_NOTE_ENTITIES = frozenset({"dsa"})                 # create_revision_note is DSA-only

    #: Fieldless action types (their target carries no `field`).
    FIELDLESS_TYPES = frozenset({"create_note", "create_code_snippet", "update_code",
                                 "set_confidence", "set_status", "schedule_revision"})

    STATUS_ENUMS = {                       # app/core/constants.py
        "dsa": frozenset({"not_started", "attempted", "solved", "needs_revision", "mastered"}),
        "lld": frozenset({"not_started", "learning", "completed", "needs_revision", "mastered"}),
        "hld": frozenset({"not_started", "learning", "completed", "needs_revision", "mastered"}),
    }

    async def execute(self, *, user_id: uuid.UUID, action_id: uuid.UUID,
                      expected_version: int | None) -> AppliedAction:

        # ---- 0. load the persisted proposal, scoped to the caller -----------------
        action = await self._actions.get(user_id=user_id, action_id=action_id)
        #    -> NotFoundError("ACTION_NOT_FOUND") if absent OR owned by someone else.
        #       Deliberately 404 rather than 403: a 403 would confirm the id exists.

        # ---- 1. idempotency (contract §4: "idempotent per action id") -------------
        if action.status == "applied":
            return AppliedAction(action=action, record=action.result, idempotent=True)
        if action.status == "rejected":
            raise ConflictError("This action was rejected and cannot be executed.",
                                code="ACTION_ALREADY_REJECTED")
        if action.status == "failed":
            raise ConflictError("This action already failed. Generate a new proposal.",
                                code="ACTION_ALREADY_FAILED")

        entity_type = action.target.entity_type          # schema guarantees the enum

        # ---- 2. ownership ---------------------------------------------------------
        #    The action row is already user-scoped (step 0). Now prove the TARGET is too.
        record = await self._load_entity(user_id=user_id, entity_type=entity_type,
                                        entity_id=action.target.entity_id)
        #    _load_entity uses the existing, already user-scoped repository calls:
        #      dsa -> DSAProblemRepository.get_with_progress(user_id, problem_id=slug)
        #      lld -> LLDRepository.get_with_progress(user_id, topic_id=UUID(slug))
        #      hld -> HLDRepository.get_with_progress(user_id, topic_id=UUID(slug))
        #    The curriculum catalog is global, so "ownership" means: the entity exists AND
        #    the user's own progress/notes row for it is what we are about to write.
        #    OwnershipError path:
        if record is None:
            raise NotFoundError("That item no longer exists.", code="ENTITY_NOT_FOUND")

        # defence in depth: the progress/notes row we will write must be the caller's
        progress = await self._load_progress(user_id=user_id, entity_type=entity_type,
                                            entity_id=action.target.entity_id)
        if progress is not None and progress.user_id != user_id:
            raise ForbiddenError("That record belongs to another user.", code="FORBIDDEN")

        # ---- 3. entity type allowed for this action type --------------------------
        if action.type == "schedule_revision"   and entity_type not in self.SCHEDULE_ENTITIES:
            raise ValidationError("schedule_revision applies to DSA problems only.",
                                  code="ACTION_NOT_ALLOWED_FOR_ENTITY")
        if action.type == "create_revision_note" and entity_type not in self.REVISION_NOTE_ENTITIES:
            raise ValidationError("create_revision_note applies to DSA problems only.",
                                  code="ACTION_NOT_ALLOWED_FOR_ENTITY")

        # ---- 4. field presence + field allow-list ---------------------------------
        if action.type in self.FIELDLESS_TYPES:
            if action.target.field not in (None, ""):
                raise ValidationError("This action type does not take a field.",
                                      code="ACTION_PAYLOAD_INVALID")
        else:
            field = action.target.field
            if not field:
                raise ValidationError("This action type requires a target field.",
                                      code="ACTION_FIELD_REQUIRED")
            if field not in self.EDITABLE_FIELDS[entity_type]:
                raise ValidationError(
                    f"'{field}' is not an editable field for {entity_type}.",
                    code="FIELD_NOT_EDITABLE",
                    details={"field": field, "editable": sorted(self.EDITABLE_FIELDS[entity_type])},
                )

        # ---- 5. payload shape, per action type ------------------------------------
        match action.type:
            case "set_field" | "append_field" | "create_revision_note":
                _require_str(action.value, max_len=50_000)          # note columns are Text
            case "replace_selection":
                _require_str(action.value, max_len=20_000)
                # The client told us what was selected; without it there is nothing to replace.
                if not action.selected_text or action.selected_text not in (await self._current_field_value(...)):
                    raise ValidationError("The selected text is no longer present in the field.",
                                          code="SELECTION_NOT_FOUND")
            case "create_note":
                _require_str(action.value, max_len=100_000)
            case "create_code_snippet":
                _require_dict(action.value, keys={"code", "language"},
                              optional={"title", "is_primary"})
                _require_str(action.value["code"], max_len=200_000)
                _require_enum(action.value["language"], LANGUAGE_VALUES)   # constants.LANGUAGE_VALUES
            case "update_code":
                _require_dict(action.value, keys={"snippet_id"}, optional={"code", "language", "title"})
                _require_uuid(action.value["snippet_id"])
                if action.value.get("language"):
                    _require_enum(action.value["language"], LANGUAGE_VALUES)
            case "set_confidence":
                _require_int(action.value, minimum=0, maximum=5)   # matches the DB CheckConstraint
            case "set_status":
                _require_enum(action.value, self.STATUS_ENUMS[entity_type])
            case "schedule_revision":
                _require_iso_datetime(action.value)
                _require_not_past(action.value, tolerance_days=0)   # a "revise it yesterday" proposal is a bug
            case _:
                raise ValidationError("Unsupported action type.", code="UNSUPPORTED_ACTION_TYPE")

        # ---- 6. target-specific referent checks -----------------------------------
        if action.type == "update_code":
            snippet = await self._snippets.get(user_id=user_id, snippet_id=action.value["snippet_id"])
            if snippet is None:
                raise NotFoundError("That snippet no longer exists.", code="SNIPPET_NOT_FOUND")
            if str(snippet.context_id) != str(action.target.entity_id) or snippet.context_type != entity_type:
                raise ValidationError("The snippet does not belong to this item.",
                                      code="ACTION_TARGET_MISMATCH")

        # ---- 7. version / concurrency --------------------------------------------
        #    expected_version is OPTIONAL. When the client supplies it (it has a row with
        #    `version` in hand), it is hard-checked; when it does not, we do NOT block —
        #    a tutor suggestion must not be un-executable because the user typed a character
        #    while reading it. Human-in-the-loop review is the mitigation, and the sync
        #    layer's base_version already protects offline writers.
        if expected_version is not None and progress is not None and progress.version != expected_version:
            raise ConflictError(
                "This item changed since the suggestion was made.",
                code="VERSION_CONFLICT",
                details={"expected_version": expected_version,
                         "current_version": progress.version,
                         "current_record": self._serialize(progress)},
            )

        # ---- 8. apply (delegated to the EXISTING services — no new write paths) ---
        result = await self._apply(user_id=user_id, action=action, entity_type=entity_type)

        # ---- 9. audit -------------------------------------------------------------
        await self._actions.mark_applied(action=action, result=result)
        await self._session.commit()          # service-level commit, matching NotesService.upsert
        return AppliedAction(action=action, record=result, idempotent=False)
```

**Step 8 delegates, it does not reimplement.** `set_field` / `append_field` /
`create_revision_note` call `NotesService.upsert` (dsa) or `TopicService.upsert_notes`
(lld/hld) with a single-key dict; `create_code_snippet` / `update_code` call
`CodeSnippetService.create_for_dsa|create_for_topic|update`; `set_confidence` / `set_status`
/ `schedule_revision` call `ProgressService.upsert` / `TopicService.update_progress`. That is
what makes the action path inherit today's validation, activity logging, revision scheduling
and version bumps for free — an action cannot produce a state a manual edit could not.

The audit row (`ai_actions`, new table in 0004) stores: `id`, `user_id`, `conversation_id`,
`message_id`, `type`, `entity_type`, `entity_id`, `field`, `value` (jsonb), `status`,
`error_code`, `result` (jsonb snapshot of the applied record), `created_at`, `applied_at`,
`version`. It is written **before** the apply (status `pending`) and updated after, so a
crash between the two leaves a `pending` row that is safely re-executable (idempotency check
in step 1 covers the retry).

### 9.3 Error codes (exact strings)

| Condition | HTTP | `error.code` |
|---|---|---|
| Proposal id unknown, or owned by another user | 404 | `ACTION_NOT_FOUND` |
| Target entity id not in the catalog / deleted | 404 | `ENTITY_NOT_FOUND` |
| Referenced snippet id unknown | 404 | `SNIPPET_NOT_FOUND` |
| Referenced conversation (on `reject`) unknown | 404 | `CONVERSATION_NOT_FOUND` |
| Target record belongs to another user (defence in depth) | 403 | `FORBIDDEN` |
| Action already applied (only reachable on a *different* action id) | — | *(200, `idempotent: true`)* |
| Action already rejected | 409 | `ACTION_ALREADY_REJECTED` |
| Action already failed | 409 | `ACTION_ALREADY_FAILED` |
| `base_version` / `expected_version` mismatch | 409 | `VERSION_CONFLICT` |
| Field not in the entity's editable set | 422 | `FIELD_NOT_EDITABLE` |
| Action type requires a field but none supplied | 422 | `ACTION_FIELD_REQUIRED` |
| Action type not supported for this entity type | 422 | `ACTION_NOT_ALLOWED_FOR_ENTITY` |
| `value` wrong type / too long / bad enum / bad date | 422 | `ACTION_PAYLOAD_INVALID` |
| `set_status` value not a valid enum for the entity | 422 | `STATUS_INVALID` |
| `set_confidence` outside 0–5 | 422 | `CONFIDENCE_OUT_OF_RANGE` |
| `schedule_revision` date in the past / unparseable | 422 | `REVISION_DATE_INVALID` |
| `replace_selection` target text no longer present | 409 | `SELECTION_NOT_FOUND` |
| `update_code` snippet belongs to another item | 422 | `ACTION_TARGET_MISMATCH` |
| Action type string outside the frozen enum | 422 | `UNSUPPORTED_ACTION_TYPE` |
| Apply raised a domain error (e.g. `AlreadyCompletedError`) | mapped through | that error's own code |
| Apply raised an unexpected exception | 500 | `ACTION_APPLY_FAILED` (action marked `failed`) |

Existing codes are reused wherever one already fits — `FORBIDDEN`, `NOT_FOUND`,
`VALIDATION_ERROR` are the base envelope codes from `app/core/exceptions.py`, and
`VERSION_CONFLICT` is already the code on `SyncConflictError`. New codes are
`ACTION_*`, `FIELD_NOT_EDITABLE`, `SELECTION_NOT_FOUND`, `STATUS_INVALID`,
`CONFIDENCE_OUT_OF_RANGE`, `REVISION_DATE_INVALID`, `ENTITY_NOT_FOUND`, `SNIPPET_NOT_FOUND`.

The `403`/`404` split is deliberate: a target the caller cannot see returns `404`
(`ACTION_NOT_FOUND`, `ENTITY_NOT_FOUND`) so ids do not leak, while a target that exists but
whose row belongs to someone else — which can only happen after a serious upstream bug —
returns `403 FORBIDDEN`.


---

## 10. Streaming

### 10.1 Route and transport

```python
@router.post("/chat/stream")
async def chat_stream(
    current_user: CurrentUser,
    services: ServicesDep,
    payload: AIChatRequest,
) -> StreamingResponse:
    return StreamingResponse(
        services.ai.chat_stream(user_id=current_user.id, payload=payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",       # stops nginx/Render's proxy buffering the stream
        },
    )
```

* **`POST` + SSE, not `EventSource`.** `EventSource` is GET-only, and the request carries a
  body (`message`, `page_context`, `context_id`) plus an `Authorization` header that
  `EventSource` cannot send. This is why the contract says "compatible with URLSession byte
  streams (iOS) and `EventSource`/`fetch` (React)" — React uses `fetch` + a
  `ReadableStream` reader, not `EventSource`. The wire format is standard SSE, so a client
  that wants `EventSource` can POST first and then GET a one-shot stream token; that is a
  client concern, not a server one.
* **Rate limiting happens before the stream opens** (`_enforce_rate_limit`, identical to
  `chat`), so a limited client gets a normal `429` JSON envelope rather than a stream that
  errors on its first event.
* **Errors before the first byte** (unknown `conversation_id` → `CONVERSATION_NOT_FOUND`,
  unconfigured provider → `AI_NOT_CONFIGURED`) are raised normally and produce the standard
  JSON envelope with the right status. Once the stream has started, an error can only be
  reported as an `error` event, because the status line is already sent.
* `AIProvider` has no streaming method today, and adding one to the Protocol would force
  every provider to implement it. Instead the streaming path is a **new optional protocol**
  checked at runtime:

```python
@runtime_checkable
class StreamingAIProvider(Protocol):
    async def stream(
        self,
        *,
        messages: list[ChatMessage],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:        # yields text deltas
        ...

# in chat_stream:
if isinstance(self.provider, StreamingAIProvider):
    delta_iter = self.provider.stream(...)         # real token streaming
else:
    result = await self.provider.chat(...)         # StubProvider / GroqProvider fallback
    delta_iter = _single_shot(result.content)      # yields the whole answer as one token
```

  `GeminiProvider` gains `stream()` against
  `POST {base}/models/{model}:streamGenerateContent?alt=sse`, parsing each `data: {...}`
  line and yielding `candidate.content.parts[*].text`. The stub and any provider without
  streaming degrade to a single-token event — the contract is unchanged, the client code is
  unchanged, and no provider is forced to implement streaming to keep working.

### 10.2 Exact event sequence

Happy path, one assistant action proposal:

```
event: token
data: {"text": "Sliding "}
                                   <-- blank line terminates every event, per the SSE spec

event: token
data: {"text": "window "}

event: token
data: {"text": "breaks when negative values are present."}

event: actions
data: {"actions": [{"id":"3f2c…","type":"append_field","target":{"entity_type":"dsa","entity_id":"subarray-sum-equals-k","field":"mistakes"},"value":"Sliding window is unreliable when negative values are present…","status":"pending"}]}

event: done
data: {"conversation_id":"9b1d…","message_id":"c47a…","usage":{"input_tokens":3180,"output_tokens":241}}

```

Failure paths:

```
event: token
data: {"text": "Sliding "}

event: error
data: {"code": "AI_UNAVAILABLE", "message": "The AI provider could not be reached."}

```

Rules, all enforced by a single wrapper:

1. **Order is fixed:** `token`* → (`actions` | absent) → `done` | `error`.
2. `actions` is emitted **after** the token stream and **before** `done` — never inline, never
   interleaved (contract §2). The reason is practical: a client that renders tokens as they
   arrive must not have a JSON object spliced into the middle of the visible text.
3. Exactly **one** terminal event, either `done` or `error`. A generator that yields `done`
   then raises must not produce a second terminal event — the `finally` block tracks
   `terminated = True` and swallows anything after it.
4. `actions` is emitted **only** when at least one action was parsed. An empty
   `{"actions": []}` is valid but is simply omitted, so the happy path for a pure
   explanation is three event types, not four.
5. `done` carries `conversation_id` and `message_id` — the client needs both to continue the
   thread and to reference the turn. `usage` is additive and may be absent for a provider
   that does not report it.
6. `error` carries the same `{code, message}` shape as the JSON error envelope's inner
   object, so the client's existing error mapping works unchanged.
7. No `id:` and no `retry:` fields are emitted. `retry:` would make the browser's
   `EventSource` reconnect and re-send a POST body it cannot re-send; `id:` would imply
   resumability we do not offer.
8. Heartbeat: if no token has been produced for 15 seconds, a comment line `: keep-alive`
   is yielded. Proxies on the free tier close idle connections at ~30 s, and Gemini can take
   several seconds before the first delta.

### 10.3 Yielding from FastAPI

```python
async def chat_stream(self, *, user_id: uuid.UUID, payload: AIChatRequest) -> AsyncIterator[str]:
    await self._enforce_rate_limit(user_id=user_id)                 # 429 before the stream

    conversation, _is_new = await self._resolve_or_create_conversation(user_id, payload)
    user_message = await self._messages.add(...)                    # user turn persisted first
    context       = await self._build_context(user_id=user_id, conversation=conversation, payload=payload)
    system_prompt = build_system_prompt(action=payload.action.value, context=context,
                                        auto_reveal_solution=await self._auto_reveal_enabled(user_id=user_id))
    history       = await self._prompt_history(user_id, conversation, user_message, context)

    collected: list[str] = []
    terminated = False
    try:
        async for delta in self._provider_stream(history, system_prompt):
            collected.append(delta)
            yield sse("token", {"text": delta})

        full_text = "".join(collected)

        # --- parse proposals out of the completed text (see 10.4) ------------------
        actions = await self._tutor_actions.parse_proposals(
            user_id=user_id, conversation_id=conversation.id, text=full_text,
            context_type=payload.context_type.value, context_id=payload.context_id,
        )

        # --- persist the assistant turn -------------------------------------------
        assistant_message = await self._messages.add(
            user_id=user_id, conversation_id=conversation.id, role="assistant",
            content=full_text, action=payload.action.value,
            provider=self.provider.name, model=self._settings.ai_model,
            usage=self._last_usage,
        )
        await self._conversations.touch(conversation, message_count_delta=2)
        await self._session.commit()

        if actions:
            yield sse("actions", {"actions": [a.model_dump(mode="json") for a in actions]})

        terminated = True
        yield sse("done", {"conversation_id": str(conversation.id),
                           "message_id": str(assistant_message.id),
                           "usage": self._last_usage or {}})
    except AIConfigurationError:
        terminated = True
        yield sse("error", {"code": "AI_NOT_CONFIGURED",
                            "message": "The AI tutor is not configured on this server."})
    except Exception as exc:
        logger.exception("Tutor stream failed")
        partial = "".join(collected)
        await self._messages.add(... role="assistant", content=partial, error=str(exc)[:500])
        await self._session.commit()
        terminated = True
        yield sse("error", {"code": "AI_UNAVAILABLE", "message": "The AI provider could not be reached."})
    finally:
        # Post-stream maintenance: never blocks the reply, never runs before `done`.
        if terminated and collected:
            try:
                await self._conversation_summary.maybe_regenerate(user_id, conversation)
            except Exception:
                logger.warning("Conversation summary regeneration failed", exc_info=True)


def sse(event: str, data: dict[str, Any]) -> str:
    """One SSE event. `data` is a single JSON line — never pretty-printed, because a
    newline inside `data:` would terminate the event early."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n\n"
```

Points that are easy to get wrong and are therefore called out:

* **The token deltas must be yielded as text, not accumulated into the DB mid-stream.** The
  assistant row is written once, after the stream completes, so a crash mid-stream does not
  leave a half-written message that a later reload renders as truncated advice.
* **`json.dumps(..., separators=(",", ":"))`** — compact, and `ensure_ascii=False` so a
  non-ASCII character in the user's code (or a `…`) does not inflate every event.
* **`data:` gets one line.** A token containing a literal `\n` is JSON-escaped, which is the
  point of putting the text in JSON rather than sending it raw.
* **The `finally` runs summary regeneration after `done` has been yielded** — by then the
  client has the answer, so even a slow summariser call costs the user nothing.
* Uvicorn/Starlette must not be allowed to buffer: the `X-Accel-Buffering: no` header plus
  `Cache-Control: no-transform` is what keeps the tokens arriving live behind the platform
  proxy.

### 10.4 How structured actions are emitted after the token stream

The contract requires that `actions` come after the tokens, so the proposals cannot be
streamed as they are "decided". Two supported production patterns, in order of preference:

**A. Sentinel-block parsing (default, works with every model).** The system prompt
(`build_system_prompt`) gains a short trailer:

```
When — and only when — the user's request implies a concrete edit to their notes,
progress, or code, end your reply with a single fenced block in exactly this form:

<<<ACTIONS>>>
[{"type": "append_field",
  "target": {"entity_type": "dsa", "entity_id": "subarray-sum-equals-k", "field": "mistakes"},
  "value": "Sliding window is unreliable when negative values are present."}]
<<<ACTIONS>>>

Rules: at most 3 actions. Every action must target the entity in the current context.
If no edit is implied, omit the block entirely. Never put anything after the block.
Nothing outside the block is ever treated as an action.
```

`_tutor_actions.parse_proposals` then:

```
1. find the LAST occurrence of  "<<<ACTIONS>>>"  ...  "<<<ACTIONS>>>" in the completed text
2. text_to_show    = everything before it, rstrip()
3. json_block      = the content between the sentinels
4. json.loads(json_block)  -> list[dict]        (on failure: log, treat as zero actions,
                                                 and still show the whole text to the user)
5. for each item: drop the model-supplied "id"; validate against TutorAction.model_validate
   (pydantic) -> any ValidationError drops that single action, never the whole reply
6. force  target.entity_type / target.entity_id  to the request's context_type/context_id
   (the model is NOT trusted for identity — see §9 step 2)
7. assign a server-generated UUID v4 per action, status="pending"
8. persist the ai_actions rows (status pending, before any execute)
9. return the list, and REMOVE the sentinel block from the text shown to the user
```

Step 6 is the security-critical one: a model that hallucinates
`"entity_id": "someone-elses-problem"` cannot make the action target that entity, and even if
it did, §9 step 2 would reject it. The model proposes *content*; the server decides *identity*.

Because the sentinel block is stripped before the text is persisted, the `content` stored in
`ai_messages` is the same prose the user saw, and a later reload of the thread does not
re-render the JSON. The token stream carries the sentinel and the JSON through to the client
(the client must hide it — the contract's clients render `token` events incrementally, so the
React/iOS side buffers from `<<<ACTIONS>>>` onward and discards it). To avoid that client
complexity, the streaming path buffers **only** from the sentinel: `_provider_stream` yields
deltas through a small state machine that stops forwarding once it sees `<<<ACTIONS>>>`, so
the client never receives the raw JSON at all and the `actions` event remains the only place
proposals appear. That is the recommended implementation.

**B. Response-schema tool-calling (optional, Gemini only).** `GeminiProvider.stream()` passes
`generationConfig.responseSchema` + `responseMimeType: application/json` for a second,
non-streamed call whose only job is to extract actions from the completed text. It is more
robust on structured output and costs one extra call; it is *not* required, and the sentinel
approach is the default so the behaviour is identical across `gemini`, `groq` and `stub`.

Either way the emitted `actions` payload is the frozen `TutorAction` shape, and the action
lifecycle continues through §9 with no further changes to the streaming path.


---

## 11. Anti-patterns

### 11.1 What must NOT be embedded

| Never embedded | Where it lives | Why |
|---|---|---|
| `UserProblemProgress.status`, `LLDProgress.status`, `HLDProgress.status` | `db/models/dsa.py`, `lld.py`, `hld.py` | A single enum token ("attempted") carries no semantics, and it changes constantly — every status flip would invalidate a hash and buy a paid embedding call for zero retrieval value. It is a **filter/metadata** value. |
| `attempts`, `confidence`, `revision_count`, `total_time_spent_minutes`, `time_spent_minutes` | progress tables | Numeric scalars. Cosine distance between `3` and `5` is meaningless; a vector for "4" retrieves nothing useful. |
| `first_attempt_date`, `solved_date`, `last_reviewed_date`, `next_revision_date`, `completed_at`, `last_reviewed_at`, `next_revision_at` | progress tables | Dates. "next revision 2026-10-03" is a scheduling fact, not a concept. Also PII-adjacent (when a person was studying). |
| `is_favorite`, `is_active`, `is_primary`, `order_index`, `importance`, `estimated_minutes`, `order_index` | catalog + progress | Booleans and ranking integers. Filters at best. |
| `difficulty` | `DSAProblem`, `LLDTopic`, `HLDTopic` | Same reason as `status`: a one-word enum. Keep it in `metadata.difficulty` so a filter can use it. |
| streak counts, study minutes, progress %, revision-due dates | `activity`, `study_sessions`, `stats` | Contract §6 lists these explicitly as never-embed. They are analytics, and they are the most sensitive rows in the database. |
| `external_url`, `slug`, `source`, `id`, `user_id`, `problem_id`, `context_id` | everywhere | Identifiers. A URL embedding retrieves URLs. |
| `content_hash`, `embedding_model`, `created_at`, `updated_at`, `version`, `deleted_at` | everywhere | Bookkeeping. Embedding them would also make the hash self-referential (the row would change whenever it changed). |
| `ProblemAttempt.notes` | `db/models/dsa.py` | A per-attempt scratch note, often "wrote it, forgot the base case, o(n^2)". It duplicates `ProblemNote.mistakes`, and indexing every attempt would multiply vectors by attempt count. Deliberately excluded unless a future settings flag opts in. |
| `LLDNote.class_diagram` (JSONB) | `db/models/lld.py` | Structured data — see 11.2. Its prose content is already captured by `class_responsibilities` and `relationships`. |
| `DSAProblem.hints` | `db/models/catalog.py` | Only skipped because it is `NULL` for all 90 seeds; **if** populated it *is* embeddable (§2.2). Not an anti-pattern, a conditional. |
| The whole row, serialised (`model_dump()` → JSON → embed) | — | The classic mistake. Serialising a `HLDNote` embeds column names, `null`s, UUIDs and timestamps alongside the writing, which dilutes the vector and can surface rows on queries about `null` or `id`. Chunk the **fields**, never the row. |

### 11.2 What must NOT be sent to the LLM

| Never sent | Why | What is sent instead |
|---|---|---|
| Structured numeric data — confidence, attempts, streaks, study minutes, progress %, revision counts | The model cannot reason usefully over raw counters, and a hallucinated "you're at 40 % confidence" is worse than no number. | A one-line natural-language digest in part 2: `status: attempted`, `confidence: 3`, `attempts: 2` — the *minimum* that changes the tutoring tone. Never the raw row. |
| Every chat message / the whole history | Contract §7: "Prompt context = summary + last 8–12 relevant messages. Never the whole history." A 200-message thread would blow the context window, cost ~50× more tokens, and add no value — the model already lost the thread's shape. | Conversation summary (part 4) + the last 8–12 messages (part 5). |
| All vectors / the raw RAG index | Never send `embedding` arrays, `content_hash`, `embedding_model`, or "here are all 1 290 chunks". The model gets the **6 retrieved chunks' text**, with attribution. | `RetrievalService.search(...)` top-6, rendered as prose excerpts (§7.2). |
| The user's other entities | `AITutorService` already loads exactly one entity per request, and that must not change. Sending the whole DSA catalog, or the user's other problems' notes, violates "never send the user's whole database" and leaks personal data into a third-party prompt for no benefit. | The single entity's context, plus the user's own history **only** through the retrieval step's top-6. |
| Other users' data | Contract §6: "a user's vectors are never returned to another user." | `WHERE (user_id IS NULL OR user_id = :current_user)` (§6). |
| Provider credentials, JWTs, `user_id` UUIDs, internal ids | Never needed by a model. A UUID in a prompt also invites the model to invent relationships between ids. | Titles and slugs only. |
| `content_hash`, `version`, `created_at`/`updated_at`, `deleted_at` | Bookkeeping; the model has no use for it and it is a fingerprint of internal state. | Nothing. |
| The full prompt, echoed back to the client | Client-facing responses carry `context_used` (a summary of field names and counts), never the prompt. Contract §2 already requires this. | `context_used` (§7.5). |
| The user's raw unsaved code *unless the action needs it* | Existing `_CODE_ACTIONS` gate stays: `explain_code`, `find_bug`, `complexity`. A general question does not need 20 000 characters of code attached. | Code only for those actions, capped at `MAX_CODE_CHARS = 20 000`, or the `page_context.code` when the user is actively editing. |
| Full tool/SQL access | "The model never emits SQL" (contract §3). No DB schema, no table names, no query text in any prompt. Actions are data, not statements. | The `TutorAction` JSON shape. |

### 11.3 Additional engineering anti-patterns to avoid

* **Embedding inside the user's write transaction.** The note write commits first; indexing
  happens after. A Gemini timeout must never roll back a saved note.
* **Re-embedding on every save.** The `content_hash` check runs *before* the embed call, not
  after (§3).
* **Retrieving without the self-exclusion filter.** Handing the tutor the user's own current
  `mistakes` text as a "retrieved memory" produces the surreal reply "I see you wrote X" when
  X is on screen. `exclude_source_id` prevents it.
* **Mixing embedding models in one vector column.** Always `embedding_model = :current` in
  both branches (§4.1).
* **Post-filtering isolation only after the merge.** It must be in both SQL queries (§6.1).
* **Streaming the action JSON into the visible answer.** See §10.4 — buffer from the
  sentinel.
* **Treating an empty FTS result as an error.** Stop-word-only queries are normal (§4.2).
* **Padding the RAG context to hit "8 chunks".** Three good chunks beat six padded ones
  (§4.4).
* **Charging the user's rate limit for a summary call.** It is server-side maintenance (§8.1).

---

## 12. Storage budget

768 dimensions is a decision, not an accident: it is the only size that keeps the global
curriculum plus a heavy personal corpus inside the Supabase **Free** tier's 500 MB database,
while still being a real semantic model.

### 12.1 Row sizes

| Component | Bytes |
|---|---|
| `embedding vector(768)` | `768 × 4 = 3 072 B` (pgvector stores `float4`) + ~8 B vector header ≈ **3 080 B** |
| `id`, `user_id` (`user_bucket`) | 32 B |
| `source_type`, `section`, `embedding_model` (short text, toasted out of line) | ~60 B inline |
| `content` (avg 600 chars) | ~600 B, TOASTed once > ~2 KB; typically inline |
| `metadata` jsonb (~180 B) + key overhead | ~250 B |
| `content_hash` (64 chars) + `created_at`/`updated_at` | ~130 B |
| Row header + null bitmap | 24 B |
| **Subtotal before index bloat** | **≈ 4 200 B** |
| Unique index `(source_type, source_id, section, user_bucket)` | ~90 B |
| `ix_knowledge_chunks_user_id_source` | ~50 B |
| `ix_knowledge_chunks_source_lookup` | ~70 B (long `source_id` text) |
| TOAST/overflow overhead (~8 %) | ~330 B |
| **Per-chunk total** | **≈ 4 750 B — call it 4.8 KB** |

### 12.2 Global curriculum (all `user_id = NULL`)

| Source | Rows | Chunks/row | Chunks |
|---|---|---|---|
| DSA problems (`dsa_problems.json`) | 90 | 6 (`title`, `primary_topic`, `secondary_topics`, `patterns`, `companies`, `problem_type`; 0 `hint_*` today) | **540** |
| LLD topics (`lld_topics.json`) | 20 | 5 (`title`, `description`, `learning_objectives`, `key_concepts`, `category`) | **100** |
| HLD topics (`hld_topics.json`) | 20 | 5 (`title`, `description`, `learning_objectives`, `key_concepts`, `category`) | **100** |
| **Total** | **130** | | **740** |

Per §2: DSA carries `title`, `primary_topic`, `secondary_topics`, `patterns`, `companies`,
`problem_type` = **6** chunks/problem → 90 × 6 = 540. LLD/HLD carry `title`, `description`,
`learning_objectives`, `key_concepts`, `category` = **5** → 20 × 5 = 100 each, 200 together.
Global total = **740 chunks**.

Storage: `740 × 4.8 KB ≈ 3.5 MB` of table + `740 × 3 KB = 2.2 MB` of vector. **≈ 3.5 MB
total**, about **0.7 % of the 500 MB free tier.** (Index-only bytes: ~0.2 MB.)

If DSA `hints` were later populated for all 90 problems with 3 hints each, that adds 270
chunks (+1.3 MB) — still negligible.

### 12.3 One heavy user

A deliberately pessimistic single-user corpus, the kind a 6-month active user accumulates:

| Source | Count | Chunks each | Chunks |
|---|---|---|---|
| DSA notes (`ProblemNote`: `approach`, `notes`, `mistakes`, `revision_notes` prose + `time_complexity`, `space_complexity`) | 400 problems with notes | 6 | **2 400** |
| LLD notes (`LLDNote`: 7 prose fields + `patterns_used`; `class_diagram` excluded) | 20 topics | 8 | **160** |
| HLD notes (`HLDNote`: 15 sections) | 20 topics | 15 | **300** |
| Code snippets (`rag_index_snippets = true`), avg 1.2 per problem | 400 problems | ~1.2 | **480** |
| Conversation summaries | 60 threads | 1 (superseded in place) | **60** |
| Prose fields that split into 2 windows instead of 1 (long `mistakes` / `failure_handling`) | ~10 % of the prose rows above | +~250 | **250** |
| **Heavy user total** | | | **≈ 3 650** |

Storage: `3 650 × 4.8 KB ≈ 17.5 MB`. Round to **~18 MB per heavy user**.

### 12.4 Justifying 768 dims on Supabase Free

| Scenario | Per-user vectors | Storage |
|---|---|---|
| Typical user (~1 000 chunks) | 1 000 | ~4.8 MB |
| Heavy user (as above) | 3 650 | ~18 MB |
| Global curriculum (shared, stored once) | 740 | ~3.5 MB |
| **10 heavy users + global** | 37 240 | **~180 MB** |
| **20 heavy users + global** | 73 740 | **~355 MB** |
| **25 heavy users + global** | 91 990 | **~444 MB** ← the free-tier ceiling |
| The same corpus at **1 536 dims** | 25 heavy users | `444 MB + (91 990 × 3 072 B) ≈ 727 MB` → **over the limit at ~15 users** |
| The same corpus at **3 072 dims** (a common default) | 25 heavy users | `444 MB + (91 990 × 9 216 B) ≈ 1.29 GB` → **over the limit at ~7 users** |

The arithmetic is what makes 768 the answer:

* Vector bytes scale **linearly with dimensions**, and for a text-heavy corpus the vector
  *is* the row — at 3 072 dims, 92 k chunks alone are ~850 MB of pure vector data, so the
  free tier runs out with single-digit user counts.
* 768 is only 25 % of 3 072 and 50 % of 1 536, so it buys 2–4× the headroom for the same
  corpus size: **≈ 90 000 chunks, roughly 25 heavy users, inside 500 MB.**
* Quality-wise, 768 is the recommended dimension for `gemini-embedding-2` (Matryoshka-style
  truncation from a larger space); truncating further to 256 or 512 would save another
  ~2 MB/user but measurably degrades retrieval on the long, technical prose these notes are.
  768 is the largest size that is *safe* at the target scale and the smallest that keeps
  retrieval quality — the crossing point, which is exactly why the contract fixes it.
* Every additional dimension multiplies the cost of the thing we have the most of. Keeping
  chunks semantic and small (750 total for the global curriculum, ~6–15 per user topic
  rather than one vector per row) matters more than any dimension choice; the budget above
  assumes the anti-patterns in §11 were avoided.
* Growth beyond the ceiling is handled by (a) trimming low-value chunks
  (`rag_index_snippets` back to false removes ~2.4 MB per heavy user), (b) dropping a
  conversation-summary chunk for archived threads, then (c) paid storage — in that order,
  because the first two are free and reversible.
* `EXPLAIN (ANALYZE, BUFFERS)` on the vector query, plus
  `SELECT pg_size_pretty(pg_total_relation_size('knowledge_chunks'))`, are part of the
  index acceptance test so the real number is measured rather than assumed.

---

## 13. Build order and acceptance tests

Implementation order (each step independently verifiable; nothing later is a prerequisite for
anything earlier):

| Step | Deliverable | Test |
|---|---|---|
| 0 | migration `0004` — `vector`, `knowledge_chunks`, unique index, `ai_actions`, `conversation_summary` + watermark columns | `alembic upgrade head` twice is a no-op; §5.4 duplicate queries return 0 rows |
| 1 | `EmbeddingProvider` + `GeminiEmbeddingProvider` + factory + lifecycle wiring | unconfigured → `503 AI_NOT_CONFIGURED`, app still boots (`test_ai.py` pattern) |
| 2 | `ChunkingService` | golden-file test: a fixture `HLDNote` produces exactly 15 chunks with the 15 named sections; a fixture `ProblemNote` produces ≤6; an empty field produces 0 |
| 3 | `hashing` + `KnowledgeIndexRepository` upsert | identical text twice → 1 embed call, 1 row; changed text → new `content_hash`, vector updated |
| 4 | `KnowledgeIndexService` — global seed | run twice: first `embedded=740`, second `embedded=0 skipped=740` |
| 5 | write hooks on `NotesService.upsert`, `TopicService.upsert_notes` | save notes → chunk exists within the same request's aftermath; provider failure → note still saved |
| 6 | `RetrievalService` | the two SQL queries return the expected rows on a fixture; RRF ordering matches a hand-computed table for a fixed input |
| 7 | isolation tests (§6.2) | all seven pass against a live DB (`pytest -m db`) |
| 8 | `ContextBuilder` | budget test: an over-long prompt triggers the documented reduction order; `context_used` contains no content |
| 9 | conversation summary | after 16 messages the summary regenerates once; the watermark advances; the prompt window starts after it |
| 10 | `TutorActionService` + the three routes | the error-code table in §9.3 is one parameterised test each; scenario 2 (append to `mistakes` → apply → persisted) and scenario 7 (`hld.failure_handling`) |
| 11 | `/chat/stream` | event order asserted on the raw byte stream: every `token` before any `actions`, exactly one terminal event, sentinel never leaks into a `token` |
| 12 | end-to-end | contract scenarios 1, 2, 5, 6, 7 from `06-migration-plan.md` |

Acceptance gates that must be green before Phase 5 is called done:

1. Contract scenarios **1, 2, 5, 6, 7** pass (Phase 5's stated acceptance set).
2. Re-running the global seed performs **zero** embedding calls.
3. `pytest -m db tests/test_rag_isolation.py` passes — user A never sees user B's chunks.
4. A tutor request with the embedding provider unconfigured returns a normal answer with
   `context_used.rag.degraded = true`, **not** a 5xx.
5. `GET /api/v1/ai/chat/stream` terminates with exactly one `done` on the happy path and
   exactly one `error` on a forced provider failure.
6. `pg_total_relation_size('knowledge_chunks')` after the global seed is < 10 MB.

---

## 14. Summary of concrete numbers

| Constant | Value | Where |
|---|---|---|
| Embedding dimensions | 768 | column, provider, settings |
| Embedding model | `gemini-embedding-2` | provider, `embedding_model` column |
| Embedding batch size | 16 | `embedding_batch_size` |
| Embedding concurrency | 3 | `embedding_concurrency` |
| Embedding retries / backoff | 3 attempts, `0.6 × attempt` s | mirrors `GeminiProvider` |
| Embedding timeout | 30 s | `embedding_timeout_seconds` |
| Prose chunk target / max / overlap | 350–600 / ~700 / 64 (50–80 allowed) | `ChunkingService` |
| Structured chunk | 1 field = 1 chunk, no overlap | `ChunkingService` |
| Vector branch top-K | 20 | `rag_vector_top_k` |
| FTS branch top-K | 20 | `rag_fts_top_k` |
| RRF constant | k = 60 | `rag_rrf_k` |
| Final chunks | 6 default (5–8 allowed), ≤2 per source entity | `rag_final_top_k` |
| Global chunks | 740 (90×6 DSA + 20×5 LLD + 20×5 HLD) | §12.2 |
| Global storage | ≈ 3.5 MB | §12.2 |
| Heavy-user chunks / storage | ≈ 3 650 / ≈ 18 MB | §12.3 |
| Dedupe key | `(source_type, source_id, section, coalesce(user_id, '00000000-0000-0000-0000-000000000000'::uuid))` | §5 |
| Isolation clause | `WHERE (user_id IS NULL OR user_id = :current_user)` | §6 |
| Context budget | 6 000 input tokens across 5 parts (§7.3) | `ai_context_budget_tokens` |
| Summary trigger | ≥16 messages **or** ≥1 500 unre-summarised tokens | `ai_summary_*` |
| Summary target | ≤600 tokens, 5 fixed sections | §8.2 |
| History window | last 12 (floor 8) | `ai_max_history_messages` |
| SSE terminal events | exactly one of `done` / `error`, after `actions` | §10.2 |

