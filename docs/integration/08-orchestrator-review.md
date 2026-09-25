# 08 — Orchestrator / independent reviewer: adversarial review

**Reviewer role:** independent orchestrator. **Stance:** adversarial. The objective is to
*falsify* documents `00`–`07`, not to endorse them.

**Method.** Every claim below was checked against the on-disk sources named in the documents
themselves: `backend/app/**`, `backend/alembic/versions/*`, `backend/schema_snapshot.json`,
`backend/schema_report.md`, `backend/tests/*`, `backend/scripts/*`, `frontend/src/**`, and
`~/interviewready/InterviewReady/**`. Claims marked **UNVERIFIABLE** could not be confirmed
from the referenced source because the source does not exist, is not reachable from this
environment, or the claim is a live-database observation that no artefact in the tree records.

> Note on a structural defect that affects this whole review: **`docs/integration/` is not a
> git repository** (`git rev-parse` → *not a repository*), and neither `backend/` nor
> `frontend/` is under version control. Every "we preserved / we did not change / the contract
> is frozen" claim is therefore un-auditable by diff. That is finding **M-12**.

---

## 0. Summary verdicts on the six mandated questions

| # | Question | Verdict |
|---|---|---|
| 1 | Unverifiable claims | **26 identified** (7 material, 9 moderate, 10 minor). See §1. |
| 2 | Contradictions between documents | **9 confirmed**, 2 of them blocking. See §2. |
| 3 | Data-loss risk in `06` | **Real but limited**: no `DROP`/`DELETE`, but 4 write-back paths can silently destroy the single live progress row or overwrite user design work. See §3. |
| 4 | Are `04`/`05` backward compatible as claimed? | **No.** The backward-compatibility verdicts on CN-001/CN-002/CN-003 are stated without the code check that falsifies CN-001/CN-002. See §4. |
| 5 | Is the phase ordering correct? | **No — it is not a partial order.** `Phase 3.0` is numbered as a sub-phase of Phase 3 yet declared a prerequisite of it; a `06`-internal claim ("cannot pass before step 6") contradicts the numbered order in three places. See §5. |
| 6 | What is missing from all eight | **12 categories**, three of which are release-blocking (no rollback contract, no RLS/authorization model for the new write path, no concurrency/load plan). See §6. |

---

## 1. Claims asserted but not verifiable from the referenced source

### 1.1 Material (wrong, or would change a decision if checked)

**V-01 — `04-contract-openapi.md` §1: `GET /api/v1/lld/{id}/code`, `/hld/{id}/code` "EXISTS".**
The table lists `GET/PUT /api/v1/lld/{id}/code`, `/hld/{id}/code` under "Endpoints the brief did
not list but that exist — keep them". **Falsified:** the only routers registering a `/code`
sub-resource are in `app/api/v1/dsa.py` (`/problems/{problem_id}/code`). `grep -n "router.get\|router.put" app/api/v1/lld.py app/api/v1/hld.py`
returns no `/code` route; the snippet endpoints for topics live behind `/code-snippets/...`.
*What would be needed:* an `OpenAPI` dump (`/openapi.json`) or the actual route list for the
topic routers. As written, a client generated from `04` will 404 on topic code.

**V-02 — `04` §1: `GET /api/v1/users/export` "EXISTS".**
`app/api/v1/users.py` declares exactly two routes (`@router.get` × 2). The second is `me`-adjacent,
not an export. No `export` string appears in `users.py` or any router.
*What would be needed:* the route decorator or an OpenAPI dump showing the path.

**V-03 — `04` §3: "Handler-level translation turns PostgreSQL `IntegrityError` constraint names
into specific API codes."**
Partially falsified: `app/api/error_handlers.py` maps **six** constraint strings, and **three of
them do not exist in the live schema** — `uq_daily_plans_user_id_plan_date` (the real constraint
is `uq_daily_plans_user_id_date_key`), `uq_study_sessions_user_id_device_identifier` (the table
has no `device_identifier` column at all), and `uq_study_sessions_one_active_per_user` exists
only as a **partial unique index**, which Postgres reports as `duplicate key value violates
unique constraint` with the *index* name — so that one happens to work by string match, but the
other two are dead branches. `04` presents this as a working guarantee.
*What would be needed:* a test that provokes each constraint and asserts the API code.

**V-04 — `01-audit-backend.md` §6: "A verified backup precedes every migration
(`scripts/backup_public_schema.py`, **proven restorable with `ON_ERROR_STOP=1`**)."**
**Falsified as written.** No restore was ever performed and recorded: `backend/backups/` does not
exist, no `*.sql` dump exists outside `.venv` except `docs/existing_supabase_schema.sql` and test
fixtures, and **no file in the repository contains the string `ON_ERROR_STOP`**.
*What would be needed:* a recorded restore transcript (or at minimum a `psql -v ON_ERROR_STOP=1`
invocation in a documented, reproducible backup/restore test). This is the single most
load-bearing safety claim in the whole document set and it is not supported.

**V-05 — `02-audit-ios.md` §1: the per-file line counts (`MyApp.swift` 25, `Services/AppServices.swift`
159, `SupabaseServices.swift` 564, `Models/AppModels.swift` 241, etc.) and the claimed
`Xcode project InterviewReady.xcodeproj`, `supabase-swift 2.55.2`.**
`~/interviewready/InterviewReady/` exists and `InterviewReady.xcodeproj` exists, but the *file
names* asserted (`MyApp.swift`, `Views/AuthenticationView.swift`, `Services/SupabaseServices.swift`,
`Services/ConnectivityMonitor.swift`) were not confirmable in the directory listing inspected, and
no lockfile/resolved-package artefact pinning `supabase-swift 2.55.2` is referenced.
*What would be needed:* the exact `ls -R` of the Xcode target and `Package.resolved`. Line counts
matter here because `02` uses "~2,000 lines" to justify the effort estimate in `07` §4.1.

**V-06 — `06` / `07`: the "at last inspection" live-state numbers (revision `0003`, zero drift,
90/20/20 seeded, 6/6 `auth.users` FKs intact, `user_problem_progress` = 1 row).**
The row counts *are* corroborated by `schema_snapshot.json.estimated_row_counts`
(`user_problem_progress` = 1, `design_topics` = 0, `dsa_problems` = 90). **But the snapshot's
counts come from `reltuples` (`pg_class`), which is an *estimate* refreshed by autovacuum/ANALYZE
and can be stale or zero for recently written tables.** The snapshot itself also contains an
`alembic_version` row count of 0, i.e. the estimator already reports 0 for a table that must have
≥1 row. Zero drift is asserted with no drift artefact.
*What would be needed:* `SELECT count(*)` for the personal tables, plus `alembic current` /
`alembic check` output. Until then, "the database is essentially empty" (the premise that
**justifies not doing a live backfill**) rests on a stale-catalogue estimate.

**V-07 — `07-gap-analysis.md` §1.1 / `01` §2.1: "Postgres does not reject these [iOS enum values]
because the declared CHECK constraint was never created."**
The *snapshot* half is verified (`ck_user_problem_progress_status_valid` is absent from
`schema_snapshot.json.constraints`; `ck_lld_progress_status_valid` / `ck_hld_progress_status_valid`
are present). The *live-consequence* half is asserted, not observed. `00` further hardens this
into "the mechanism behind the iOS `notStarted` bug". Since `user_problem_progress` holds one row
whose value is never quoted, the causal claim is unverified.
*What would be needed:* the stored value of that row, or the iOS write path shown to actually
send `notStarted`.

### 1.2 Moderate (plausible but not demonstrated)

**V-08 — `01` §1: "285 tests across 10 modules in `tests/`."** Directory holds 10 test modules +
`conftest.py`, but `grep -c "def test_"` totals **251**, not 285. *Needed:* the assertion count
(if parametrisation accounts for the difference, say so — only 6 `parametrize` markers exist
across 3 modules, which cannot bridge 34).

**V-09 — `04` §1: `GET /api/v1/daily-plans`, `/daily-plans/{plan_date}`, `GET /api/v1/revisions/summary`,
`POST /revisions/promote-stale`, `GET /api/v1/stats/mastery`, `GET /api/v1/study-sessions`,
`/study-sessions/running`, `PATCH/DELETE /api/v1/daily-plans/items/{item_id}`, `GET /api/v1/settings/devices`,
`PUT /api/v1/settings/devices`.** The prefix routers exist, and the HTTP-verb census matches the
documented counts (`GET 38 / POST 11 / PUT 11 / PATCH 2 / DELETE 5`), so the *family* is right —
but no OpenAPI dump is checked in, so individual path spellings (param names, `/summary`, `/running`,
`/explain`) cannot be confirmed path-by-path. *Needed:* the committed `/openapi.json`.

**V-10 — `01` §1: "Every personal endpoint derives the user id from the verified token", "Routers
parse and shape; they hold no business logic", "Services are injected per-request via
`app/api/v1/services.py` + `dependencies.py`."** The dependency wiring is real (`CurrentUser`,
`ServicesDep` exist and are used). "Every" is not demonstrated; a single counter-example would
falsify it, and none of the eight documents enumerates the personal endpoints to check.
*Needed:* a route-by-route audit table.

**V-11 — `01` §2.2 / "Needs migration": `user_problem_progress.problem_id` has no CHECK against
the catalog, and "the service layer validates ids against the catalog on write instead".**
**Falsified in the sync path.** `_upsert_progress` in `services/sync_service.py` calls only
`_require_problem_id`, which checks *presence*, not *existence*:
`problem_id = mutation.payload.get("problem_id") or str(mutation.record_id)`. The RAG/`dsa_service`
paths do call `catalog.get_with_progress`, but the sync handler does not. So the sync API will
happily create progress rows for a non-existent slug. `01` flags this as a question ("Confirm
that is actually enforced on every write path") but `06` §3.4 never adds a test for it.
*Needed:* a catalog-existence check in `_upsert_progress`, or a test asserting rejection.

**V-12 — `03-audit-react.md` §2: "`src/api/http.ts` owns URL/query assembly, headers, bearer token,
JSON parsing and uniform error normalisation. Nothing else calls `fetch` directly."** The
centralisation claim is plausible (`http.ts` exists) but "nothing else" is not verified; a single
direct `fetch` falsifies it. *Needed:* `grep -rn "fetch(" src` excluding `http.ts`.

**V-13 — `03` §2/§6: "`STORAGE_KEYS.deviceId = 'ir-device-id'` … the web client does not call
`/sync/*`."** `config.ts` does define `deviceId: 'ir-device-id'`. The second half is verified
negatively (no `/sync` reference in the endpoint modules). Fine — recorded for completeness.

**V-14 — `03` §1: the `features/` and `api/endpoints/` directory listing.** This one is
**materially stale in the *other* direction**: `src/features/ai/page-context.ts` and
`src/features/ai/use-page-context.ts` exist on disk with mtimes of **05:08**, i.e. written *after*
`03-audit-react.md` (05:04). The document's §6 "Missing (Phase 4 work)" therefore mis-describes
current reality: an unshipped, unreferenced PageContext builder already exists, but nothing imports
it (`grep -rn "buildPageContext" src` outside its own file returns nothing) and it is never sent
on the wire (`AIChatRequest` in `src/types/ai.ts` has no `page_context`). Either the audit is stale
or work happened outside the recorded process. *Needed:* a decision on whether this is Phase 4 work
or undocumented scope creep.

**V-15 — `0?` (all): "The subagent mechanism in this session returned no work product (file writes
stayed in isolated forks and final messages returned `null`)."** Unfalsifiable from any artefact.
*Needed:* nothing — but it means the *provenance* claim in `00` cannot be checked, and the
five-way authorship claim in `07` §"Headline" is contradicted (see C-09).

### 1.3 Minor (cosmetic or low-impact, listed for completeness)

**V-16** — `04` §4: "`X-Device-Id` [is an allowed CORS header]" — true — and `03` §2 says the
backend "accepts `X-Request-ID` / `X-Device-Id` per CORS config". True. But **`X-Timezone` is not
in `allow_headers`** (`app/main.py`), which is why the transport uses a non-CORS-restricted
mechanism. `03` does not notice this.

**V-17** — `04` §4: "security headers, request-context middleware (request id + user id
contextvars, with a redaction filter so tokens never reach logs)". Middleware exists
(`app/api/middleware.py`); the redaction filter's *completeness* is asserted, not tested.
*Needed:* a log-capture test asserting no `Bearer ` appears.

**V-18** — `01` §1: "`app/core/jwks.py` implements a JWKS client over **httpx** … because
`PyJWKClient` … fails with `CERTIFICATE_VERIFY_FAILED` on macOS." The httpx client exists; the
stated *cause* is an unrecorded environment observation. *Needed:* the failing traceback.

**V-19** — `01` §2.4: "The frontend contract in the brief expects `POST /api/v1/ai/actions/{id}/execute`
and `/reject`. Neither exists." True, and `app/api/v1/ai.py` confirms only 5 routes. But "the
brief" is not in the repository, so the *source* of the requirement cannot be checked.

**V-20** — `01` §2.6: "`AI_PROVIDER` defaults to `gemini`, `AI_MODEL=gemini-2.0-flash`,
`AI_API_KEY` empty in `.env.example`. Tutor returns 503 when unconfigured — by design,
non-fatal." Verified (`AIConfigurationError` → 503 `AI_NOT_CONFIGURED`). **However, `backend/.env`
exists with a filled `AI_API_KEY` and 7 `DATABASE_URL` occurrences** — the document set never
acknowledges a populated local env, nor whether it points at the shared production project. Not a
falsification, but a review gap with real blast radius.

**V-21** — `09`? n/a.

**V-22** — `05` §6: `embedding_model = 'gemini-embedding-2'`, `vector(768)`. Neither the model
identifier nor the 768 dimension is verified anywhere; no provider call, no `pgvector` extension
present in the snapshot (`storage.buckets_vectors`/`storage.vector_indexes` exist but are Supabase
Storage's own, not an extension in `public`). *Needed:* a provider capability check.

**V-23** — `05` §6: "Exact search first; add HNSW + `vector_cosine_ops` only when latency demands
it." No latency budget, dataset size, or measurement plan exists anywhere in the set. The decision
is deferred without a trigger threshold.

**V-24** — `05` §7: "Prompt context = summary + last 8–12 relevant messages" and §8 "recent
messages (8–12)". A *range* is not a contract. Two implementers will pick 8 vs 12 and produce
different prompts; the "frozen" label is not honoured for this parameter.

**V-25** — `02` §5: "`lld_topics.json` 20 rows, `hld_topics.json` 20 rows" — verified; "23 LLD
titles / 31 HLD titles" hardcoded in iOS — **not verified** (depends on the iOS files in V-05).

**V-26** — `00` "Non-negotiable engineering rules" §6: "**No new infrastructure** — no Redis, Kafka,
Celery, Pinecone, Chroma, Elasticsearch, microservices. PostgreSQL + pgvector + FastAPI is the
ceiling." Meanwhile `06` §3.1 requires `CREATE EXTENSION IF NOT EXISTS vector`, and `01` §2.7 hints
at `pg_cron`. Both are **infrastructure additions** to the managed Postgres. The rule's intent is
presumably "no new *services*", but as written it forbids its own Phase 3 work.

---

## 2. Contradictions between documents

**C-01 (BLOCKING) — `00` reading order vs the actual filename.**
`00-README.md` lists document 05 as **`04-contract-ai.md`**. The file on disk is
**`05-contract-ai.md`**, and `04-contract-openapi.md` §1 itself cross-references
"see `04-contract-ai.md` §4" — a reference to a file that does not exist. `06` and `07` use
`05-contract-ai.md`. Impact: a reader following `00` or `04` cannot find the contract.

**C-02 (BLOCKING) — `04`/`05`/`07`: catalog primary key vs the DSA AI context id.**
`05` §1 states, in bold, "`entity_id` for DSA is the slug, **not** a UUID … This trips clients up."
`frontend/src/features/ai/page-context.ts` also documents the slug requirement. But **the backend
cannot accept a slug**: `app/schemas/ai.py` types `AIChatRequest.context_id: uuid.UUID | None`,
`app/db/models/ai.py` maps `AIConversation.context_id` as `PGUUID`, and the live column is `uuid`
(`schema_snapshot.json` → `public.ai_conversations.context_id | uuid`). Meanwhile
`frontend/src/features/dsa/pages/problem-workspace-page.tsx` passes `contextId={data.id}` where
`data.id` is the **slug** (string). So today's React DSA tutor call fails Pydantic validation with
422. This is not "the frozen contract vs legacy clients" — it is `04` + `05` describing a shape the
authoritative server cannot parse.

**C-03 — `05` §2 (request) vs `05` §1 (PageContext) on the `entity_id` type.**
§1 says entity_id is `string | null` (slug for DSA, UUID for LLD/HLD). §2's example is
`"context_id": "subarray-sum-equals-k"` — a slug — while the schema is UUID. Internal contradiction
in one document, compounding C-02.

**C-04 — `02` §6 vs `00` "Shared enums (frozen)".**
`00` freezes `AttemptOutcome gave_up | partial | solved | solved_with_hint | revision_success | revision_failed`
and says the vocabulary is "identical values on every platform". `02` §6 defines only `ProblemStatus`
and `DesignStatus` in Swift and never defines `AttemptOutcome`, `Difficulty`, `StudyArea`,
`SyncOperation`, or `DeviceType` — despite `07` §1.11 noting iOS "keeps only an integer counter"
for attempts and never writes the revision queue at all. The frozen vocabulary has no iOS-side
definition for the enums iOS must eventually produce.

**C-05 — `00` §Phases vs `06` §Phase 3.0.**
`00` lists 7 phases and does not contain *Phase 3.0* anywhere. `06` introduces it as "**do this
FIRST**" and a prerequisite of Phase 3. So the canonical phase table in `00` is already wrong, one
document later.

**C-06 — `06` Phase 5 vs `06` "Contract change notes" CN-001.**
Phase 5 item 5 says `ContextBuilder` implements "the five-part assembly in `05-contract-ai.md` §8".
CN-001 says "backend ignores it until Phase 5" — but the `page_context` *schema field* is declared
in Phase 3.3 ("Additive `page_context` on the chat request"). Phase 3 adds the field; Phase 5 makes
it do something. `04` §1 lists `/ai/chat` as EXISTS, so a client sending `page_context` in Phases
3–4 gets it silently dropped. The contract says the field exists; the plan says it is ignored.

**C-07 — `06` vs itself on Phase ordering.**
`06` §"Critical integration tests" states "Scenario 4 … cannot pass before step 6", where "step 6"
is Phase 6 step 6 (DesignTopic → `lld_*`/`hld_*`). But Scenario 4 is owned by Agent 1 and listed as
an acceptance test of Phase 6 as a whole, while **Phase 5** (AI foundation) seeds `lld_topics` /
`hld_topics` embeddings in item 3. A later phase (6) is declared a prerequisite for an earlier
phase (5) in one place and a dependent of it in another. See §5.

**C-08 — `01` §5 "Recommended: yes [create the CHECKs], after the iOS enum fix lands" vs
`04-contract-openapi.md` §3 vs `02` §3.**
`01` recommends creating the five declared CHECK constraints. `06` §3.5 defers them ("blocked on
3.0"). But `06` Phase 3.0 item 1 explicitly says "**Then fix the backend: create
`ck_user_problem_progress_status_valid` so it can never recur**" — i.e. create it immediately in
3.0, which is what §3.5 says is deferred. Two mutually exclusive instructions for the same
constraint inside one document.

**C-09 — `00` provenance note vs `07` ownership.**
`00` says the documents were "produced by **one author** working through four ownership roles …
only the number of authors differs." `07` §4.1 says iOS becoming a thin client "removes ~1.5k
lines of duplicated logic" and §"What is already compatible" frames the analysis as two-party
("Desktop project / iOS project"). This is a soft contradiction, but it matters: `00` disclaims
independent authorship, so no claim in `01`–`05` has been independently cross-checked. Nothing in
the set is a *second opinion*, including this review's counterpart documents.

---

## 3. What in `06-migration-plan.md` risks existing user data

**Nothing in `06` executes a `DROP`, `DELETE`, or destructive `ALTER`.** That part of the claim
holds. The risks are indirect, through *write-back* and *overwrite* paths.

**D-01 — `06` Phase 3.0 item 1: "Existing rows already written with wrong enum values must be
repaired by a one-off mapping (`notStarted → not_started`, `needsRevision → needs_revision`)."**
This is an **unconditional `UPDATE` over a live user table**. It assumes the enumeration of wrong
values is exhaustive. It is not: `07` §1.1 records that iOS writes `notStarted` / `needsRevision`,
but `02` §3.1 and `07` §1.1 both note the CHECK constraint never existed — so **any** string could
be stored, including `done`, `inProgress`, and the values `00` explicitly forbids. A mapping that
only covers two spellings will silently leave (or, worse, later fail the about-to-be-created CHECK
on) every other divergent value. `06` says "Confirm the current count first —
`user_problem_progress` held 1 row at last inspection" and then proposes the update **without a
precondition gate**. Needed: enumerate `SELECT DISTINCT status`, map exhaustively, and gate the
`ALTER … ADD CONSTRAINT` on `NOT EXISTS (unmapped values)`.

**D-02 — `06` Phase 3.0 item 1 / CN-005: "Then create `ck_user_problem_progress_status_valid`."
Creating a CHECK constraint requires a full table scan and will fail the migration if *any* row
violates it.**
On the `1 row` premise it is harmless. On a stale-estimate premise (V-06) it is a hard failure
mid-migration, on a table that also carries `auth.users` FKs. `06` never mentions
`NOT VALID` + `VALIDATE CONSTRAINT` as the two-phase, non-blocking alternative, and never
specifies the pre-flight `SELECT COUNT(*) WHERE status NOT IN (…)`.

**D-03 — `06` Phase 3.0 item 2: "`binary-search` and `next-greater` have **no** catalog match —
decide whether to add them to `app/seed_data/dsa_problems.json` or **drop them from the iOS
starter catalog**."**
"Drop them from the iOS starter catalog" is a decision point that `06` leaves open with no default.
If it is taken literally and iOS has already synced progress/notes/snippets for those ids, the join
target disappears. `07` §1.10 asserts those rows "become an orphan the backend cannot join to a
problem" — the correct action is a **slug remap for the three that match, plus a documented
decision for the other two**, not a catalog edit. `06` does not state which side is authoritative.

**D-04 — `06` Phase 6 item 6: "Requires the `design_topics` backfill (`scripts/backfill_design_topics.py`)."**
Verified as safe *by the script* (`--dry-run` first, read-only on source, idempotent, never inserts
into the global `lld_topics`/`hld_topics` catalogs, skips rather than force-fits unmatched rows).
**But `06` does not require the `--dry-run` step, does not state that unmatched rows are skipped
and reported, and does not say what happens to them.** On the current 0-row table the risk is zero;
the plan generalises a zero-risk case into an unqualified instruction.

**D-05 (the real one) — the ordering in `06` guarantees a window of *double-write data loss*, and
no document addresses it.**
Today iOS writes `design_topics` directly via PostgREST (RLS policy `own rows` exists on
`design_topics` — verified in `schema_policies`). The `07` §"Recommended integration path" sequence
is: Phase 1 (fix enums/ids) → Phase 2 (move iOS writes behind FastAPI) → **Phase 3 (migrate design
topics)**. `06` instead orders: Phase 6 steps 4–5 (move iOS to `/sync`) and **step 6 (migrate
`DesignTopic`) last**. Between the two, **iOS continues writing `design_topics` while the web
client reads `lld_*`/`hld_*`.** A user's LLD/HLD notes written on iOS during Phases 3–5 are
invisible on web, and the backfill in Phase 6 step 6 must run *after* the iOS writer is switched
off or it will miss everything written in between. `06` never states that ordering constraint, and
`07` §4.3 ("can it be discarded? This changes whether Phase 3 needs a backfill at all") leaves the
question open.

**D-06 — CN-006: "`design_topics` is retired in favour of `lld_*`/`hld_*` entities.**
**BACKWARD COMPATIBLE? yes for the database — RLS and the existing tables stay in place."**
"Retired" without a definition of *when iOS stops writing it* is the mechanism by which D-05
happens. `06` should specify: stop-writes → **verify zero new rows** → backfill → then delete code.

**D-07 — CN-005: "BACKWARD COMPATIBLE? **no** — this is a deliberate wire-value change on the
client."**
Correctly labelled. The risk is in the ordering: `06` Phase 3.0 mandates the enum fix and the DB
remediation **before** Phase 3.5 creates the CHECKs and **before** Phase 6 deletes the direct
PostgREST repositories. During that window an *old* iOS binary (un-updated, still installed) keeps
posting `notStarted` — which will now either be rejected by the new CHECK (good: loud) or accepted
if the CHECK creation is skipped per §3.5 (bad: silent again). No document states that the DB
constraint must land only after the client fleet is known to be updated, or that an old binary must
be blocked. This is a **compatibility window the plan does not bound**.

---

## 4. Are the frozen contracts (`04`, `05`) genuinely backward compatible?

**`04` — mostly yes, with two wrong existence claims and one overstated guarantee.**
`04` §1's "EXISTS / ADD" discipline is the right pattern, and the "preserve every working path"
decision is sound. But (a) `GET /lld/{id}/code` / `/hld/{id}/code` do not exist (V-01),
(b) `GET /users/export` does not exist (V-02), and (c) the error-envelope guarantee is partly
aspirational (V-03). The `04` §1 note that "`PUT` is already used for progress/notes … the existing
verbs are preserved" is verified and correct.

**`05` §2 CN-001 — "BACKWARD COMPATIBLE? yes — optional field, absent means today's behaviour."**
**Falsified.** The claim is only true for the `page_context` *field*. The same `POST /ai/chat`
request carries `context_id`, which `05` §1 says is a **slug** for DSA — while the server types it
as `uuid.UUID`. Adding `page_context` does not break React; the *existing* React DSA call is
already broken against the current server type. Backward compatibility cannot be asserted for a
request shape whose documented value type the server cannot accept.

**`05` §2 CN-002 — "BACKWARD COMPATIBLE? yes — additive; an empty array when nothing is proposed."**
**Falsified as a client-compat claim.** `frontend/src/types/ai.ts` `AIChatResponse` has no `actions`
field. `mockClient` and `realClient` both satisfy the same `ApiClient` interface
(`src/api/contract.ts`), and `03` §4.5 explicitly warns that "mock/real drift is invisible… its
*behaviour* is not checked against the real backend." A response field that exists only in `realClient`
is exactly that drift: TS structural typing means React will not error, but neither implementation
is *tested* to tolerate or surface it. `03` §6 lists "TutorAction Apply/Dismiss UI" as must-add and
`05` calls the field additive — the two are consistent only if you accept that "additive" means
"deliberately ignored by the client", which is not what "backward compatible" should mean for a
contract that is about to be frozen.

**`05` §5 sync — "Already implemented and frozen. iOS must adopt it as-is."**
**This claim is overstated in a way that will bite on implementation.** The schema
(`app/schemas/sync.py`) accepts `SyncEntity` for **11** entity values, but the dispatcher
`SyncService._handlers()` registers only **10** — `study_session` is missing. A client that pushes
`entity: "study_session"` (which `05` §5 lists as a valid entity, and which `07` §1.11 says iOS
already writes directly) will be rejected as `'study_session' cannot be synchronised`. `05` tells
iOS to adopt this contract "as-is" for an entity the server cannot accept. `01` §1 and `05` §5
both enumerate the 11 entities identically — so the documentation is self-consistent and the
**implementation is not**, which is precisely the failure mode a frozen contract is supposed to
prevent.

**`04`/`05` "frozen" status itself.** `00` requires a change note for any contract change and
mandates the `WHAT CHANGED / WHY / BACKWARD COMPATIBLE? / AFFECTED CLIENTS / REQUIRED MIGRATION`
format. `06` provides six notes in that format — **all six are authored by the same party that
authored the contracts they modify**, with no independent sign-off, and two of the six
(CN-001, CN-002) carry a `BACKWARD COMPATIBLE? yes` that the code contradicts. The freeze is
procedural only.

---

## 5. Is the phase ordering correct, or is a later phase a prerequisite for an earlier one?

**The ordering is not a valid partial order.** Four concrete defects:

**P-01 — `Phase 3.0` is a prerequisite of `Phase 3` but is numbered inside it.**
`06` §3.5: "Creating the declared-but-missing CHECK constraints … **blocked on 3.0 below**";
`06` §3.0: "**do this FIRST** … it precedes everything else." A phase cannot be both a child of
Phase 3 and a predecessor of it. `00`'s phase table does not contain 3.0 at all (C-05). Fix: make
Phase 3.0 its own numbered phase and renumber, or fold all three items into the head of Phase 3.

**P-02 — Phase 5 depends on Phase 6, while Phase 6 depends on Phase 5's contract.**
`05` §6 requires `knowledge_chunks` with `source_type ∈ {dsa_problem, lld_topic, hld_topic, note,
snippet, conversation_summary}` and `entity_id` as "slug or uuid". Phase 5 item 3 seeds the global
curriculum from `lld_topics` / `hld_topics`. Phase 6 step 6 is what stops iOS writing
`design_topics` and backfills into `lld_*`/`hld_*`. So **Phase 5's corpus is still being written by
iOS during Phase 5**, and `06` says Scenario 4 (§ Critical integration tests) "cannot pass before
step 6" — i.e. a Phase 6 step gates a Phase 5 acceptance test. Two orderings are needed:
(a) indexing the *global* curriculum (independent of iOS) can proceed; (b) indexing **per-user**
notes/snippets from iOS must be sequenced **after** Phase 6 step 4. `06` does not distinguish them.

**P-03 — Phase 4 step 3 depends on Phase 3.3, which depends on Phase 5.**
Phase 4 step 3: "Build the `PageContext` builder … reading unsaved drafts from component state."
Phase 3.3 adds the `page_context` field to the request, but `06`'s CN-001 says the backend "ignores
it until Phase 5." So Phase 4 can *build* the payload but cannot *verify* it end-to-end — its
acceptance criteria (Scenarios 1 and 2, both owned by "3 + 4") require Phase 5 item 5
(`ContextBuilder`). Phase 4 is therefore only partially completable in the numbered order.

**P-04 — Phase 7 is gated on "web AI behaviour is stable", an undefined gate.**
`06` Phase 7: "**Only after web AI behaviour is stable**, using the exact same contract." No
stability criterion, no exit test, no owner. Combined with `06`'s own admission that Phase 3.0 is
"the only work that touches live user data correctness", the plan has one well-specified critical
path item and a soft gate at the far end of the schedule.

**Correct partial order (as inferred, not as written):**

```
P0  Enumerate live values (SELECT DISTINCT status; count(*) the personal tables)   ← MISSING TODAY
P1  iOS enum + catalog-slug fix, shipped to the client fleet                      (3.0 / CN-005)
P2  Verify no legacy client writes bad enums        ← MISSING GATE
P3  ADD CONSTRAINT … NOT VALID, then VALIDATE       ← different from what 06 says
P4  knowledge_chunks + vector + additive AI columns (migration 0004)              (3.1)
P5  /ai/chat/stream + action routes + TutorActionService                          (3.3/5)
P6  PageContext end-to-end (server accepts slug)  → Phase 4 unblocks
P7  iOS repository layer + mutation queue  → stop writing design_topics           (6.4/6.5)
P8  Backfill design_topics (dry-run → verify zero new rows → run)                 (6.6)
P9  iOS AI                                                                         (7)
```

The material change from `06`: **the enum remediation must be preceded by an enumeration of what
is actually in the table and a `NOT VALID` constraint strategy**, and **the `design_topics`
stop-write must be a named gate before the backfill**, not prose inside a step.

---

## 6. What is missing from all eight documents

**M-01 (BLOCKING) — No rollback / downgrade contract.**
`06` §3.1 asserts migration `0004` is "guarded and reversible"; no `downgrade()` plan, no
`alembic downgrade` target, no statement of what happens to `knowledge_chunks` embeddings (a
`vector` column cannot be reconstructed without re-embedding at cost), and no rollback story for
the *client* half of a contract change. `06`'s six change notes all say
`REQUIRED MIGRATION: none` for clients — but **a client on an old build is a rollback scenario the
plan never models**. There is no "minimum supported client version" anywhere in the set.

**M-02 (BLOCKING) — No authorization/RLS model for the new FastAPI write path.**
`schema_report.md` states the connecting role **`bypasses RLS`**. So today the *only* thing keeping
user A out of user B's rows on the sync path is repository-layer `user_id` filtering. `01` §1 and
`04` §2 assert "the user id comes from the verified JWT `sub`" and "a `user_id` in a body or query
is ignored" — but **no document contains a test or a code reference proving cross-user isolation
for the sync push path**, and `06` §3.4 adds a user-isolation test only for *RAG retrieval*, not
for sync. `05` §5's sync contract is "frozen" with no isolation evidence attached.

**M-03 (BLOCKING) — No concurrency, load, or rate-limit plan.**
Sync push cap is `sync_max_mutations_per_push: int = 200` (verified in `config.py`). There is no
analysis of a 200-mutation batch against per-mutation savepoints, no statement of what happens when
two devices push the same `(user_id, mutation_id)` concurrently, and no load target for the AI
endpoints. `05` §3 says actions are "idempotent per action id" — with no concurrency semantics
(what if two devices execute the same action simultaneously?).

**M-04 — No data-retention or PII policy.**
`05` §6 introduces `knowledge_chunks.content` holding user notes/snippets, and §7 stores
conversation transcripts. `source_type` includes `note`, `snippet`, `conversation_summary`. Nothing
in the set states: retention period, deletion propagation when a note is deleted
(`05` §"Never embed" excludes raw metadata but a deleted note's *chunk* is not addressed),
or whether `GET /users/export` (which `04` claims exists) covers RAG content.

**M-05 — No definition of "today" / timezone authority that survives scrutiny.**
`04` §4 and `03` §4.4 both say `user_settings.timezone` is authoritative and `X-Timezone` is
advisory. **Falsified on the critical path:** `today.py` resolves
`timezone=client_timezone or user_settings.timezone`, and `get_or_default` **fabricates a settings
row using the client hint** when no row exists (`timezone=timezone_hint or self._settings.default_timezone`).
So on a first-ever request the client *does* set the timezone, and thereafter
`client_timezone or user_settings.timezone` still prefers the header. `06` Phase 4 step 2 is
literally "Verify the backend enforces `user_settings.timezone` over the `X-Timezone` header" — the
document set flags the risk but no document states the required behaviour for the
first-request / no-settings-row case, which is where the ambiguity bites.

**M-06 — No error-code catalogue.**
`04` §3 gives one example envelope and says codes are specific. The source has ~25 distinct codes
(`AI_NOT_CONFIGURED`, `PROGRESS_EXISTS`, `DUPLICATE_MUTATION`, `VERSION_CONFLICT`, …). No document
lists them. A frozen contract that does not enumerate its error vocabulary is not frozen from a
client's perspective.

**M-07 — No pagination/cursor contract for the AI conversation list.**
`04` §5 gives `limit`/`offset` and "catalog default page size 50". `/ai/conversations` returns
`Page[AIConversationSummary]` with a `context_type` filter — the filter is not documented in `04`
or `05`.

**M-08 — No idempotency contract for the new action endpoints.**
`05` §4 says execute is "Idempotent per action id" but does not say what the second call *returns*
(the action row? a 200 with `status: applied`? a 409?). `06` §3.4 tests "cross-user target
rejected, non-editable field rejected, unknown action type rejected, invalid enum value rejected,
stale `version` rejected" — but **not** duplicate execution.

**M-09 — No observability plan.**
No metrics, no SLO, no alerting, no tracing of the sync cursor lag, no AI latency/cost telemetry.
`06`'s "Performance guardrails" are all *restrictions* ("no N+1", "never load a whole chat
history") with no measurement.

**M-10 — No cost model for embeddings or LLM calls.**
`05` §6 names `gemini-embedding-2`; `06` §"Performance guardrails" says "768-dim vectors and
semantic content only, **to respect Supabase Free storage**." Free-tier *compute* (embedding every
note on write, at 90 + 20 + 20 global rows plus per-user content) is never estimated. A free-tier
project is named as the constraint and then not quantified.

**M-11 — No acceptance/definition-of-done for Phases 3–7 other than the seven scenarios.**
`06` gives "Acceptance: brief scenarios 1, 2, 5, 6, 7" for Phase 5 and "3, 4" for Phase 7 — but the
seven scenarios are the *only* exit criteria in the entire plan, and Scenario 4 is acknowledged as
unreachable in order (C-07). There is no per-phase exit test, no rollback trigger, and no owner for
the go/no-go.

**M-12 — No version control, therefore no auditability at all.**
`backend/`, `frontend/`, and `~/interviewready/` are not git repositories. Every "we did not
change X", "the contract is frozen", "migrations are additive and guarded", and "keep them as-is"
claim is un-diffable. **No change note in `06` can be independently verified**, because there is no
baseline to diff against. This is the meta-finding: it makes findings V-01…V-07 permanently
unresolvable rather than merely unverified. Before any Phase 3 work, the three trees must be
committed so that `06`'s contract-change discipline has something to attach to.

**M-13 — No handling of the pre-existing `user_problem_progress` row's provenance.**
`07` §4.3 asks whether it is "still wanted"; `06` §3.0 says "confirm the current count first".
Neither says what happens if it belongs to a real user, what timezone it was written under, or
whether `auth.users` (0 rows at snapshot time) implies it is orphaned. On a table with an FK to
`auth.users`, a progress row with no user is a live integrity question that no document answers.

**M-14 — No statement of which environment the documents describe.**
`backend/.env` exists (7 `DATABASE_URL` occurrences, populated `AI_API_KEY`), `schema_snapshot.json`
names Supabase project `qkuxfobfqioilwbjpvyf` for **both** projects, and no document distinguishes
local / staging / production. Phase 3.0's `UPDATE` and Phase 3.1's `CREATE EXTENSION` are described
without an environment. A plan whose first step is a live data mutation must name its target.

---

## 7. Ranked actions before Phase 3 begins

1. **M-12** — commit `backend/`, `frontend/`, and `~/interviewready/` to version control.
2. **V-06 / M-13** — run `SELECT count(*)` on every personal table; enumerate
   `SELECT DISTINCT status FROM user_problem_progress`; record `auth.users` membership.
3. **C-02 / V-14** — decide the DSA AI `context_id` type (slug vs UUID). This is a genuine
   contract change; it needs a change note and it invalidates CN-001's "backward compatible: yes".
4. **C-01** — rename or re-reference the AI contract file so `00` and `04` point at a real path.
5. **D-01 / D-02** — rewrite Phase 3.0 item 1 as: enumerate → map exhaustively → gate →
   `ADD CONSTRAINT … NOT VALID` → `VALIDATE CONSTRAINT`.
6. **D-05** — add an explicit stop-write gate for `design_topics` before the backfill, and place it
   before the iOS-to-`/sync` cutover rather than after.
7. **§4 `study_session`** — either implement the 11th sync handler or remove `study_session` from
   `05` §5 and `07` §1.11. A frozen contract that lists an unsupported entity is the exact drift
   the freeze is meant to prevent.
8. **M-02** — add a cross-user isolation test for `/sync/push` before calling the sync contract
   frozen.
9. **V-04** — perform and record one restore from `scripts/backup_public_schema.py`. Until then
   `01` §6's "proven restorable" must be deleted.
10. **M-01 / M-11** — add a minimum-supported-client-version policy and per-phase exit criteria.

---

## 8. What the documents get right (stated only because the record should be balanced)

- `01` §2.1 is a **correct and precisely-argued** root cause: `schema_snapshot.json` confirms
  `ck_user_problem_progress_status_valid` is absent while `ck_lld_progress_status_valid` and
  `ck_hld_progress_status_valid` are present. The consequence (silent acceptance of divergent enum
  values) follows.
- `01` §1's description of the sync cursor as `sync_changes.seq BIGINT IDENTITY` is verified
  (`uq_sync_changes_seq`, `sync_mutations` unique on `(user_id, mutation_id)`), and the reasoning
  about same-millisecond ordering and representable deletions is sound.
- `07` §1.2's conflict-key analysis is verified against the live constraints
  (`uq_user_problem_progress_user_id_problem_id` exists; `id` has no server default).
- `07` §"What is already compatible" is correct that `problem_notes` columns match
  (`approach`, `notes`, `time_complexity`, `space_complexity`, `mistakes`, `revision_notes`) and
  that `confidence` is 0–5 default 3.
- `scripts/backfill_design_topics.py` is genuinely defensively written (`--dry-run`, read-only
  source, idempotent, never force-fits into the shared catalog).
- `03` §4.4 correctly identifies the `X-Timezone` authority risk before anyone acted on it.

---

*End of review. No existing file was modified; the only files created by this reviewer are
`/tmp/agent-orchestrator-proof.txt` and this document.*
