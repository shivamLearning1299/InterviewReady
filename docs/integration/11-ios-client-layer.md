# iOS → FastAPI client layer

Implemented against the **live** OpenAPI document (`/openapi.json`, 55 paths), not the
markdown contracts, so the paths and field names are the ones the running backend serves.

## Layout

```
Networking/
    APIError.swift        typed errors mapped from the backend error envelope
    APIEndpoint.swift     every route as a value; paths verified against /openapi.json
    APIClient.swift       actor: URL assembly, bearer auth, JSON, error mapping
Models/DTO/
    CommonDTO.swift       Page<T>, UserResponse, DeletedResponse, APIDate
    TodayDTO.swift        TodayResponse, TodaySection, TodayItem, DailyPlanDetail
    DSADTO.swift          problems, notes, snippets, attempts, revisions + requests
    DesignDTO.swift       LLD and HLD, modelled as SEPARATE types
    SettingsDTO.swift     settings, devices, study sessions
    StatsDTO.swift        overview, topics, streak, activity, mastery
    SyncDTO.swift         11 entities, mutations, push/pull, JSONValue
    AIDTO.swift           chat request/response, conversations, action menu
Repositories/
    DSAAPIRepository.swift      (renamed: collided with the legacy SwiftData protocol)
    DesignRepository.swift
    ProgressRepository.swift    today, revisions, stats, settings, sessions
    SyncRepository.swift        + SyncLocalState (device id, pull cursor)
AI/
    PageContext.swift     unsaved-draft context sent with AI requests
Services/
    AITutorService.swift          FastAPI-backed tutor
    APIClient+Setup.swift         one-time wiring
    AuthService+APIToken.swift    Supabase token -> API client bridge
```

## Name collisions resolved

Two types in the new layer shadowed existing ones and would not have compiled:

| New type | Collided with | Resolution |
|---|---|---|
| `DSARepository` | the SwiftData catalog protocol in `AppServices.swift` | renamed to `DSAAPIRepository` / `DSAAPIRepositoryProtocol` |
| `AITutorService` | the old `/api/chat` implementation in `AppServices.swift` | old one replaced by a deprecated `LegacyAITutorService` shim that delegates to the new service |

`ContentView.swift` had one call site using the old tutor; it now uses the shim.

## Key contract facts the client encodes

* **`problem_id` is a slug, not a UUID.** `dsa_problems.id` is TEXT. Every DSA path parameter
  and `AIChatRequest.contextId` for `.dsa` is the slug. `topic_id` for LLD/HLD *is* a UUID.
* **11 sync entities**, including `study_session` (which had no handler on the backend until it
  was added).
* **Cursor is a server bigint**, never a device timestamp.
* **`baseVersion`** must be sent on updates so the backend can detect a lost update; a
  `conflict` response carries `serverRecord` for merging.
* **`mutationId`** is generated per change and reused on retry; the backend de-duplicates.
* **Duration is server-measured** — the client never sends `durationMinutes` on a stop.
* **`runningStudySession()` returns `nil`**, not 404, when nothing is running.

## Not yet done

* The four legacy Supabase repositories are **still present and still in use** —
  `SwissServices.swift` has not been deleted. The new layer sits alongside it. Wiring the UI
  to the new repositories is the next step, and only then can direct PostgREST writes be removed.
* No UI changes: `ContentView.swift` still renders from SwiftData.
* `TutorAction` / Apply-Dismiss and streaming are not implemented (they depend on backend
  endpoints that do not exist yet).
