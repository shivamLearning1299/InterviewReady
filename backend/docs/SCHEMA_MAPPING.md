# Supabase schema mapping

The FastAPI application **reuses the existing `public` tables** and adds only what is
missing. No existing table is dropped and no user data is deleted.

## Decision: problem ids are `text`, not `uuid`

Every existing table references a problem as `problem_id text`, and there is **no problem
catalog table** in the database. Two options were available:

| Option | Consequence |
|---|---|
| **A. `dsa_problems.id` is `text`** (chosen) | Existing `problem_id` values join directly. Zero data migration. Existing user rows keep working. |
| B. `dsa_problems.id` is `uuid`, add `dsa_problems.slug` | Requires rewriting every `problem_id` value in `user_problem_progress`, `problem_notes`, `code_snippets` and the `daily_plans.problem_ids` JSONB array — a risky, irreversible data migration. |

Option A is used. `dsa_problems.id` is a stable slug (`"two-sum"`, `"number-of-islands"`),
which is also the `slug` column. The API treats it as an opaque string, so clients are
unaffected by the type. `lld_topics` and `hld_topics` are new tables and therefore use
`uuid` primary keys, matching `daily_plans.lld_topic_id uuid`.

## Reused tables

| Existing table | Model | Changes |
|---|---|---|
| `user_problem_progress` | `UserProblemProgress` | Renamed model columns to the existing names (`first_attempt_date`, `solved_date`, `last_reviewed_date`, `next_revision_date`, `time_spent_minutes`). Added `created_at`, `version`, `deleted_at`, `revision_count`, `is_favorite`. |
| `problem_notes` | `ProblemNote` | Added `created_at`, `version`, `deleted_at`. |
| `code_snippets` | `CodeSnippet` | Added `context_type`, `context_id`, `title`, `is_primary`, `created_at`, `version`, `deleted_at`. `problem_id` widened to NULLABLE so LLD/HLD snippets (which have no problem) can live in the same table. |
| `design_topics` | *not used by the API* | Left completely intact. See "LLD/HLD" below. |
| `daily_plans` | `DailyPlan` | Added `status`, `timezone`, `generated_by`, `created_at`, `version`, `deleted_at`. `problem_ids` is still populated on every insert (it is `NOT NULL`). Added `unique(user_id, date_key)` for generation idempotency. |
| `study_sessions` | `StudySession` | Added `started_at`, `ended_at`, `session_type`, `context_id`, `context_label`, `paused_minutes`, `note`, `created_at`, `version`, `deleted_at`. `minutes` is kept `NOT NULL` and receives `0` while a session is running. |

## New tables

`dsa_problems`, `dsa_topics`, `lld_topics`, `hld_topics`, `lld_progress`, `lld_notes`,
`hld_progress`, `hld_notes`, `problem_attempts`, `revision_queue`, `daily_plan_items`,
`user_activity_days`, `user_settings`, `user_devices`, `sync_changes`, `sync_mutations`,
`ai_conversations`, `ai_messages`, `ai_rate_limits`.

## LLD / HLD: the `design_topics` incompatibility

`design_topics` is a single user-owned table holding `area`, `status`, `notes`, `code`,
`requirements`, `architecture`, `tradeoffs`, `last_reviewed_date` and `next_revision_date`.
It is the pre-existing store for the user's own LLD/HLD work, but it

* has no link to any curriculum catalog, and
* cannot represent HLD's 13 design sections or LLD's class-responsibility breakdown
  without becoming a ~20-column table serving two unrelated document shapes.

The application therefore uses the normalised tables the API contract specifies
(`lld_topics`/`lld_progress`/`lld_notes` and `hld_topics`/`hld_progress`/`hld_notes`) and
leaves `design_topics` untouched.

To avoid orphaning existing work, `scripts/backfill_design_topics.py` performs a
**one-way, idempotent, non-destructive copy**: each `design_topics` row becomes a user
topic record under the matching curriculum, with `area` deciding whether it lands in LLD
or HLD. Reruns update rather than duplicate. `design_topics` is never modified.

Run it once, after `alembic upgrade head`:

```bash
.venv/bin/python -m scripts.backfill_design_topics --dry-run   # report
.venv/bin/python -m scripts.backfill_design_topics             # apply
```

## Security notes

* Every existing table is owned by `auth.users(id)` via a foreign key. The models do not
  declare that FK, because it lives in Supabase's `auth` schema which Alembic must not
  manage.
* If the application connects as the project owner, RLS is bypassed. The repository layer
  scopes every personal query by `user_id` regardless, and `app.current_user_id` is
  published as a session variable so RLS policies remain effective for any non-`BYPASSRLS`
  role.
* Recommended hardening (see README): create a dedicated `app_backend` role without
  `BYPASSRLS` and switch `DATABASE_URL` to it.
