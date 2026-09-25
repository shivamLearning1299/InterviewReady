# Agent 3 — React frontend audit (Phase 1)

Project: `~/Desktop/interviewready/frontend` — Vite 7, React 19, TypeScript 5.9,
TanStack Query 5, React Router 7, Radix UI, Monaco, Recharts, Tailwind 4, `@supabase/supabase-js`.

## 1. Structure (keep)

```
src/
  api/        config.ts client.ts contract.ts http.ts auth.ts errors.ts endpoints/*.ts
  app/        App.tsx app-shell/{app-shell,header,sidebar,command-palette}.tsx
  components/ shared/* ui/*
  features/   ai/ auth/ code/ dsa/ hld/ lld/ revision/ settings/ shared/ stats/ today/
  hooks/      use-api.ts use-study-timer.ts
  lib/        constants format helpers query-keys status timezone utils
  mocks/      ai-responder.ts client.ts ...
  types/      ai common dsa hld lld search settings stats today
```

Feature folders already match the target layout. **Do not restructure.**

## 2. Existing — working

* **Contract-first API layer.** `src/api/contract.ts` defines one `ApiClient` interface;
  `realClient` (HTTP vs FastAPI) and `mockClient` (in-memory) both satisfy it, and
  `src/api/client.ts` binds `api` from `VITE_USE_MOCKS`. Components import only `api`.
* **Centralised transport.** `src/api/http.ts` owns URL/query assembly, headers, bearer token,
  JSON parsing and uniform error normalisation. Nothing else calls `fetch` directly.
* **Auth indirection.** `setTokenResolver()` / `setUnauthorizedHandler()` are module-level
  callbacks, so the auth provider (demo ↔ Supabase) is swappable without an import cycle, and
  a single 401 clears a dead session once.
* **Always-on custom header.** Every request sends `X-Timezone: getClientTimezone()`. The
  backend accepts `X-Request-ID` / `X-Device-Id` per CORS config — timezone is sent on the
  wire but let me flag it below.
* **Device identity exists but is unused for sync.**
  `STORAGE_KEYS.deviceId = 'ir-device-id'` is defined in `config.ts`; the web client does
  **not** call `/sync/*`. Only iOS does.
* **Study timer** already exists (`hooks/use-study-timer.ts`) against
  `/study-sessions/start` + `/{id}/stop`.

## 3. Endpoint modules present

`endpoints/all.ts` (assembles `realClient`), `core.ts`, `dsa.ts`, `design.ts` (LLD+HLD),
`revisions.ts`, `stats.ts`, `settings.ts`, `ai.ts`.

## 4. Broken / drift risks

1. **`USE_MOCKS` defaults to `true`.** `readFlag(import.meta.env.VITE_USE_MOCKS, true)` — the
   app boots against the in-memory mock layer, not FastAPI. Any integration test must set
   `VITE_USE_MOCKS=false`.
2. **`http.ts` throws `MOCK_BYPASS` if reached in mock mode** (defensive, correct) — but it
   means a component that bypasses `api` fails only at runtime in mock mode.
3. **`contract.ts` is hand-maintained**, not generated from OpenAPI. Nothing prevents it from
   drifting from the Pydantic schemas. Highest-value fix in this phase: generate TS types from
   `/openapi.json` and assert `contract.ts` against them.
4. **`X-Timezone` is client-asserted** and the backend must not use it as the authority for
   `date_key`/streaks; the user's stored `user_settings.timezone` is authoritative.
5. **Mock/real drift is invisible.** `mockClient` must satisfy `ApiClient`, but its *behaviour*
   (pagination defaults, error codes, conflict handling) is not checked against the real
   backend.

## 5. Old architecture to remove

* The mock layer is not "old architecture" and must stay — it is what makes the app boot with
  nothing configured. But it must not be what proves the contract.
* Nothing else. The web client is already FastAPI-shaped.

## 6. Missing (Phase 4 work)

| Need | Status |
|---|---|
| `PageContext` builder per screen | **must add** |
| TutorAction Apply/Dismiss UI | **must add** |
| Diff view before applying code changes | **must add** |
| SSE consumption of `/ai/chat/stream` | **must add** |
| Types generated from OpenAPI | **must add** (drift guard) |
| Unsaved-draft capture (code, notes, selected text, focused field) | **must add** |

## 7. Ownership boundaries

React must **not** compute: today's plan, revision intervals, streaks, mastery, or statistics.
`features/today/` currently derives some display values locally (`use-weekly-progress.ts`) — keep
only presentational aggregation over server-provided numbers, never the algorithm itself.

React owns: rendering, local UI state, unsaved drafts, selected text, focused field, optimistic
display updates, and calling APIs.
