# Frozen contract — FastAPI API surface (Phase 2, Agent 2)

Status: **frozen**. Changes require a contract change note (see `00-README.md`).

## 1. Mapping: brief's target contract → actual backend

`EXISTS` = already implemented, keep as-is. `ADD` = must be built.

| Brief target | Actual path | Status |
|---|---|---|
| `GET /health` | `GET /health` | EXISTS |
| `GET /health/ready` | `GET /health/ready` | EXISTS |
| `GET /api/v1/me` | `GET /api/v1/me` | EXISTS |
| `GET /api/v1/today` | `GET /api/v1/today` | EXISTS |
| `GET /api/v1/daily-plans` | `GET /api/v1/daily-plans` | EXISTS |
| `GET /api/v1/daily-plans/{date}` | `GET /api/v1/daily-plans/{plan_date}` | EXISTS (param name differs) |
| `GET /api/v1/dsa/problems` | `GET /api/v1/dsa/problems` | EXISTS |
| `GET /api/v1/dsa/problems/{id}` | `GET /api/v1/dsa/problems/{problem_id}` | EXISTS |
| `PUT /api/v1/dsa/problems/{id}/progress` | same | EXISTS |
| `GET/PUT /api/v1/dsa/problems/{id}/notes` | same | EXISTS |
| `GET/POST /api/v1/dsa/problems/{id}/code` | same | EXISTS |
| `PUT/DELETE /api/v1/dsa/problems/{id}/code/{code_id}` | `.../{snippet_id}` | EXISTS (param name differs) |
| `POST/GET /api/v1/dsa/problems/{id}/attempts` | same | EXISTS |
| `GET /api/v1/revisions` | same | EXISTS |
| `POST /api/v1/revisions/{id}/complete` | same | EXISTS |
| `POST /api/v1/dsa/problems/{id}/revision` | same | EXISTS |
| `GET /api/v1/lld`, `/{id}`, `/{id}/progress`, `/{id}/notes` | same | EXISTS |
| `GET /api/v1/hld`, `/{id}`, `/{id}/progress`, `/{id}/notes` | same | EXISTS |
| `GET /api/v1/stats/overview` `/dsa/topics` `/dsa/difficulty` `/activity` | same | EXISTS |
| `POST /api/v1/study-sessions/start`, `/{id}/stop` | same | EXISTS |
| `POST /api/v1/ai/chat` | same | EXISTS |
| `POST /api/v1/ai/chat/stream` | — | **ADD** |
| `GET /api/v1/ai/conversations` | same | EXISTS |
| `GET /api/v1/ai/conversations/{id}` | same | EXISTS |
| `POST /api/v1/ai/actions/{id}/execute` | — | **ADD** |
| `POST /api/v1/ai/actions/{id}/reject` | — | **ADD** |
| `POST /api/v1/sync/push` | same | EXISTS |
| `GET /api/v1/sync/pull` | same | EXISTS |
| `GET /api/v1/settings`, `PUT` | same | EXISTS (+ `GET/PUT /settings/devices`) |

### Endpoints the brief did not list but that exist — keep them

`GET /api/v1/dsa/topics`, `/dsa/filters`, `PATCH /dsa/problems/{id}/attempts/{attempt_id}`,
`GET /api/v1/revisions/summary`, `POST /api/v1/revisions/promote-stale`,
`GET /api/v1/today/explain`, `PATCH/DELETE /api/v1/daily-plans/items/{item_id}`,
`GET /api/v1/stats/streak`, `/stats/mastery`,
`GET /api/v1/study-sessions`, `/study-sessions/running`,
`GET /api/v1/ai/actions` (returns the action *menu*), `DELETE /ai/conversations/{id}`,
`GET /api/v1/sync/status`, `GET /api/v1/users/export`,
`GET/PUT /api/v1/lld/{id}/code`, `/hld/{id}/code`.

**Decision:** preserve every working path. `GET /ai/actions` keeps returning the static action
menu (renaming it would break React); the new `POST /ai/actions/{id}/execute` operates on a
*pending action instance*, which is a different resource — see `04-contract-ai.md` §4.

## 2. Auth

```
Authorization: Bearer <supabase_access_token>
```

* Verified against the project JWKS (`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`).
* `aud` must equal `SUPABASE_JWT_AUDIENCE` (default `authenticated`).
* All `HS*` algorithms are rejected.
* `user_id` is the verified `sub` claim. **A `user_id` in a body or query is ignored.**
* React and iOS both already hold a valid Supabase token, so no auth change is needed.

## 3. Error envelope (uniform on every failure)

```json
{"error": {"code": "PROBLEM_NOT_FOUND", "message": "DSA problem not found", "details": null}}
```

Handler-level translation turns PostgreSQL `IntegrityError` constraint names into specific
API codes. Sync results additionally carry per-mutation `status`, `error_code` and `message`.

## 4. Middleware

* CORS: explicit origins, credentials allowed, methods
  `GET POST PUT PATCH DELETE OPTIONS`, headers
  `Authorization, Content-Type, X-Request-ID, X-Device-Id`, exposed `X-Request-ID`.
* Wildcard origin is a hard error in production.
* `GZipMiddleware` (min 1024 bytes), security headers, request-context middleware
  (request id + user id contextvars, with a redaction filter so tokens never reach logs).
* `X-Timezone` is **advisory**. The authoritative timezone is `user_settings.timezone`; clients
  must not be able to move `date_key` or streaks by asserting a timezone. Flagged in
  `03-audit-react.md` §4.4 — verify this is enforced server-side.

## 5. Conventions clients must honour

* Pagination: `limit` / `offset`. Catalog default page size 50. Never assume "all rows".
* Sync push cap: `sync_max_mutations_per_push` (configurable) — split batches.
* `version` + `updated_at` are server-authoritative. Clients send `base_version`, never `version`.
* Server clock is authoritative. `client_timestamp` on a mutation is advisory only.
* Soft deletes: a deleted row is reported by `/sync/pull` as `operation: "delete"`.
