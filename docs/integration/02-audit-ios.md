# Agent 1 — iOS audit (Phase 1)

Project: `~/interviewready` — SwiftUI + SwiftData, supabase-swift 2.55.2, Xcode project
`InterviewReady.xcodeproj`. ~2,000 lines of Swift across 8 source files.

## 1. Existing — working (keep the UI)

| File | Lines | Role |
|---|---|---|
| `MyApp.swift` | 25 | `@main`, builds `ModelContainer`, runs `SeedService` |
| `Views/AuthenticationView.swift` | 171 | `AppRootView` state machine + sign-in/up form |
| `ContentView.swift` | 511 | All screens: Today, DSA list, Problem detail, Code, Notes, DesignHub, DesignList, DesignDetail, AITutor, Stats, Settings |
| `Models/AppModels.swift` | 241 | 8 SwiftData `@Model` classes + `DSAProblemDTO` |
| `Services/SupabaseServices.swift` | 564 | Auth + 3 sync repositories + 6 remote DTOs |
| `Services/AppServices.swift` | 159 | Config, catalog repo, daily plan, seeding, notifications, AI tutor, starter catalog |
| `Services/ConnectivityMonitor.swift` | 28 | `NWPathMonitor` online/offline flag |

The UI is complete for DSA/LLD/HLD/Stats/Settings and **must not be rewritten**.

## 2. Old architecture to remove — direct database access

`Services/SupabaseServices.swift` performs PostgREST table operations from the client. All of
it must move behind `APIClient` → FastAPI.

| Repository | Tables written directly | Operation |
|---|---|---|
| `SupabaseProgressRepository` | `user_problem_progress` | `select()` + `upsert(...)` |
| `SupabaseDesignRepository` | `design_topics` | `select()` + `upsert(...)` |
| `SupabaseSupplementalRepository` | `problem_notes`, `code_snippets`, `study_sessions` | `select()` + `upsert(...)` |

`SyncService` orchestrates only `progressRepository.syncProgress(...)`; the design and
supplemental repositories are **constructed nowhere** — dead code with a live `SyncService`
call path.

### The sync algorithm being replaced

Per table, per sync: `select()` the **entire remote table** (no user filter, no pagination),
build a dictionary by `id`, insert remote rows that are missing locally, then for each local
row either apply the remote row when `remoteRow.updatedAt > row.updatedAt` or upload when
`isDirty`. This is last-write-wins on the **device clock**, with no cursor, no version, no
conflict surface and no device identity. It must be replaced by `/sync/push` + `/sync/pull`.

## 3. Old DTOs / schema assumptions

`RemoteProgress`, `RemoteDesignTopic`, `RemoteNote`, `RemoteSnippet`, `RemoteStudySession` each
map snake_case ↔ camelCase by hand via `CodingKeys`. They must be replaced by DTOs generated
from / conforming to the FastAPI OpenAPI schemas.

Divergences already verified (see `07-gap-analysis.md` for the full analysis):

1. **Enum values are wrong on the wire.** `ProblemStatus` raw values are
   `notStarted, attempted, solved, needsRevision, mastered`; the backend expects
   `not_started, ... , needs_revision, ...`. Postgres does **not** reject these because the
   declared CHECK constraint on `user_problem_progress` was never created. Silent data
   corruption.
2. **Conflict key is the primary key.** iOS `.upsert(...)` passes no `onConflict`, so PostgREST
   conflicts on `id` (client `UUID()`); the live unique constraint is
   `(user_id, problem_id)`.
3. **`design_topics` is the wrong table.** The backend reads `lld_topics` / `hld_topics` +
   `lld_progress` / `lld_notes` / `hld_progress` / `hld_notes`. `design_topics` is unmapped by
   the ORM. Every LLD/HLD write from iOS is invisible to the backend.
4. **Column naming mismatch.** iOS writes `last_reviewed_date` / `next_revision_date`; the
   topic tables use `last_reviewed_at` / `next_revision_at`.
5. **`code_snippets` rows are orphaned.** iOS omits `context_type` / `context_id`, so rows land
   with `context_id = ''` and are skipped by every backend snippet endpoint.
6. **5 of 8 catalog ids do not exist server-side** — `best-time-stock`, `binary-search`,
   `subarray-sum`, `next-greater`, `islands`.
7. **No `version` field anywhere.** The backend's concurrency contract is `base_version` →
   `version`; iOS has neither.

## 4. Duplicated business logic to delete (server owns it)

| Location | Logic | Thresholds | Replacement |
|---|---|---|---|
| `AppServices.swift` `DailyPlanService.makePlan` | 3-question plan: due → weak-topic easy → medium → fallback | `dailyCount = 3` **hardcoded** | `GET /api/v1/today` |
| `AppServices.swift` `DailyPlanService.revisionDate(for:)` | Revision interval ladder | `confidence<=2 → 1d`, `==3 → 3d`, `else 7d` | `POST /api/v1/dsa/problems/{id}/revision` |
| `ContentView.swift` `currentStreak` | Streak from `solvedDate` | requires a *solved* problem per consecutive day | `GET /api/v1/stats/streak` |
| `ContentView.swift` `StatsView` | Solved counts, LLD/HLD completion | — | `GET /api/v1/stats/overview` |
| `ContentView.swift` `TodayView.solvedCount` | `x / 400` denominator | **400 hardcoded** | `stats/overview` totals |

The hardcoded `400` and `3` are exactly the kind of client-side knowledge the architecture
forbids.

## 5. Local data that must stay client-side

`SeedService.seedDesignTopics` hardcodes 23 LLD titles ("OOP", "SOLID", "Parking Lot", …) and
31 HLD titles. These must be replaced by the server catalog (`lld_topics.json` 20 rows,
`hld_topics.json` 20 rows), matched by **slug**. `LocalDSARepository.importCatalogIfNeeded`
reads `Resources/dsa_questions.json` (6 rows) with a hardcoded `StarterCatalog` fallback. The
bundled catalog should become a cached copy of the server catalog, not an independent source.

## 6. Proposed enum shape (wire values unchanged)

```swift
enum ProblemStatus: String, Codable, CaseIterable, Identifiable {
    case notStarted      = "not_started"
    case attempted       = "attempted"
    case solved          = "solved"
    case needsRevision   = "needs_revision"
    case mastered        = "mastered"
    var id: String { rawValue }
}

enum DesignStatus: String, Codable, CaseIterable, Identifiable {
    case notStarted    = "not_started"
    case learning      = "learning"
    case completed     = "completed"
    case needsRevision = "needs_revision"
    case mastered      = "mastered"
    var id: String { rawValue }
}
```

Swift identifiers stay idiomatic camelCase; the **wire value** is the frozen snake_case enum.
`DesignStatus` is genuinely different from `ProblemStatus` (`learning`/`completed` vs
`attempted`/`solved`) and gets its own type instead of being overloaded.

## 7. Missing (Phases 6–7)

```
Networking/   APIClient.swift  APIEndpoint.swift  APIError.swift
Repositories/ DSARepository.swift  DesignRepository.swift
              ProgressRepository.swift  SyncRepository.swift
Services/     AuthService.swift  SyncService.swift
              AI/AITutorService.swift  AI/AIStreamClient.swift
Models/       DTO/   Local/
AI/           PageContext.swift  TutorAction.swift  TutorResponse.swift
```

### Offline requirements that must not regress

Users must still be able to, without internet: view downloaded DSA items, write code, write
notes, change progress, and study LLD/HLD. Changes queue for synchronisation.

Design: SwiftData remains the local store. `isDirty` on each `@Model` already marks queued
changes. Add: a local mutation queue with a client-generated `mutation_id` per change, a stored
`lastPullCursor`, and a `deviceIdentifier` — the three things `/sync/push` and `/sync/pull`
require and that the app currently lacks entirely.

## 8. Needs migration (summary)

1. Enum raw values (blocks everything; silent corruption today).
2. 5 catalog ids → real slugs.
3. `context_type` / `context_id` on code snippets.
4. Replace 3 PostgREST repositories with `APIClient` + repositories.
5. Replace the select-everything sync with push/pull + cursor + mutation queue.
6. Delete `DailyPlanService`, `revisionDate(for:)`, client streak, client stats.
7. `DesignTopic` → LLD/HLD topics matched by slug (needs the `design_topics` backfill).
8. Replace hardcoded seed lists with the server catalog.
