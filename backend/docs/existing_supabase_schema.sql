-- =============================================================================
-- EXISTING Supabase schema (as provided by the project owner, 2026-09-26)
-- =============================================================================
-- This file is a REFERENCE ONLY. It documents the pre-existing `public` schema that
-- the FastAPI application must reuse. It is never executed.
--
-- Notes that drove the model design:
--   * `problem_id` is `text`, not `uuid`, in every table that references a problem,
--     and NO problem catalog table exists. The catalog is therefore keyed by a TEXT
--     primary key (a stable slug) so existing rows join directly with zero data
--     migration. See docs/SCHEMA_MAPPING.md.
--   * `confidence` is NOT NULL DEFAULT 3 (not nullable).
--   * Date columns are suffixed `_date`, not `_at`.
--   * `daily_plans.problem_ids` is `jsonb NOT NULL`, so it must be populated on every
--     insert even though the application uses a normalised `daily_plan_items` table.
--   * No `created_at`, `version` or `deleted_at` columns exist. They are added
--     additively by migration 0002 for offline-sync support.
-- =============================================================================

CREATE TABLE public.user_problem_progress (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  problem_id text NOT NULL,
  status text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  first_attempt_date timestamp with time zone,
  solved_date timestamp with time zone,
  last_reviewed_date timestamp with time zone,
  next_revision_date timestamp with time zone,
  confidence integer NOT NULL DEFAULT 3,
  time_spent_minutes integer NOT NULL DEFAULT 0,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT user_problem_progress_pkey PRIMARY KEY (id),
  CONSTRAINT user_problem_progress_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.problem_notes (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  problem_id text NOT NULL,
  approach text NOT NULL DEFAULT ''::text,
  notes text NOT NULL DEFAULT ''::text,
  time_complexity text NOT NULL DEFAULT ''::text,
  space_complexity text NOT NULL DEFAULT ''::text,
  mistakes text NOT NULL DEFAULT ''::text,
  revision_notes text NOT NULL DEFAULT ''::text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT problem_notes_pkey PRIMARY KEY (id),
  CONSTRAINT problem_notes_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.code_snippets (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  problem_id text NOT NULL,
  language text NOT NULL,
  code text NOT NULL DEFAULT ''::text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT code_snippets_pkey PRIMARY KEY (id),
  CONSTRAINT code_snippets_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.design_topics (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  area text NOT NULL,
  title text NOT NULL,
  status text NOT NULL,
  notes text NOT NULL DEFAULT ''::text,
  code text NOT NULL DEFAULT ''::text,
  requirements text NOT NULL DEFAULT ''::text,
  architecture text NOT NULL DEFAULT ''::text,
  tradeoffs text NOT NULL DEFAULT ''::text,
  last_reviewed_date timestamp with time zone,
  next_revision_date timestamp with time zone,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT design_topics_pkey PRIMARY KEY (id),
  CONSTRAINT design_topics_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.daily_plans (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  date_key date NOT NULL,
  problem_ids jsonb NOT NULL,
  lld_topic_id uuid,
  hld_topic_id uuid,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT daily_plans_pkey PRIMARY KEY (id),
  CONSTRAINT daily_plans_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.study_sessions (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  date timestamp with time zone NOT NULL,
  minutes integer NOT NULL,
  area text NOT NULL,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT study_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT study_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);
