# InterviewReady — unified architecture: audit and frozen contracts

> **Provenance note.** These documents were produced by one author working through four
> ownership roles (iOS, Backend, React, AI/RAG), not by four independent agents. The
> subagent mechanism in this session returned no work product (file writes stayed in
> isolated forks and final messages returned `null`), so the four-agent split was executed
> as four responsibilities with explicit interface contracts between them. The role
> boundaries, deliverables and cross-agent contract rules below are exactly as specified;
> only the number of authors differs.

## Reading order

| # | Document | Owner | Purpose |
|---|---|---|---|
| 00 | `00-README.md` | — | This file. Phases, order, rules. |
| 01 | `01-audit-backend.md` | Agent 2 — Backend | Route/service/schema inventory, gaps, what must not change |
| 02 | `02-audit-ios.md` | Agent 1 — iOS | Direct-DB usage, duplicated logic, migration surface |
| 03 | `03-audit-react.md` | Agent 3 — React | Existing client, endpoint map, what to build |
| 04 | `04-contract-openapi.md` | Agent 2 | **Frozen** existing API contract + required additions |
| 05 | `04-contract-ai.md` | Agent 4 | **Frozen** PageContext, TutorAction, AI request/response, sync |
| 06 | `06-migration-plan.md` | all | Phased, prioritised execution plan with owners |
| 07 | `07-gap-analysis.md` | — | Previously delivered desktop↔iOS divergence analysis |

## Non-negotiable engineering rules

1. **FastAPI is the authoritative application layer.** Clients render; they do not own
   daily-plan selection, revision intervals, streaks, mastery, or conflict resolution.
2. **No agent changes a shared contract unilaterally.** Any change to an API payload, a DB
   field name, an enum value, or the PageContext / TutorAction / sync schema must ship a
   change note in the format below and be reflected in `04-*`.
3. **Never trust a client-supplied `user_id`.** The user id comes from the verified JWT `sub`.
4. **Never expose a service-role key** to React or iOS.
5. **Do not destroy existing user data.** Existing tables are adapted additively.
6. **No new infrastructure** — no Redis, Kafka, Celery, Pinecone, Chroma, Elasticsearch,
   microservices. PostgreSQL + pgvector + FastAPI is the ceiling.
7. **Do not rewrite working UI.** Migration happens behind a repository abstraction.

## Cross-agent contract change note (mandatory format)

```text
WHAT CHANGED
WHY
BACKWARD COMPATIBLE?   yes/no
AFFECTED CLIENTS       iOS / React / AI / backend
REQUIRED MIGRATION
```

## Phases

| Phase | Deliverable | Status |
|---|---|---|
| 1 — Audit | Four role audits | **delivered** (`01`, `02`, `03`, `07`) |
| 2 — Freeze contracts | OpenAPI inventory + AI/PageContext/TutorAction/sync schemas | **delivered** (`04-contract-*`) |
| 3 — Backend stabilization | Missing routes, pgvector schema, tests | planned (`06`) |
| 4 — React integration | Conform screens to frozen contract | planned |
| 5 — AI foundation | Embeddings, chunking, hybrid retrieval, actions, streaming | planned |
| 6 — iOS migration | Remove direct DB writes behind repositories | planned |
| 7 — iOS AI | PageContext, streaming, Apply/Dismiss | planned |

## Shared enums (frozen — identical values on every platform)

```text
ProblemStatus   not_started | attempted | solved | needs_revision | mastered
DesignStatus    not_started | learning  | completed | needs_revision | mastered
TopicStatus     == DesignStatus (same five values, used by LLDTopic and HLDTopic)
Difficulty      easy | medium | hard
StudyArea       dsa | lld | hld
AttemptOutcome  gave_up | partial | solved | solved_with_hint | revision_success | revision_failed
SyncOperation   upsert | delete
DeviceType      ios | web | android | other
```

Forbidden: `done`, `inProgress`, `notStarted`, `needsRevision`, `TODO`, `complete` for a
solved problem. Swift will use camelCase *identifiers* with `rawValue` set to the snake_case
wire value (see `02-audit-ios.md` §6) — the wire value never changes.
