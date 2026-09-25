-- =============================================================================
-- Legacy-schema fixture for local testing.
-- =============================================================================
-- Recreates the pre-existing Supabase `public` tables (plus a minimal `auth.users`
-- stand-in) so migrations and the test suite can run against a faithful shape of the
-- real database.
--
-- This file is for LOCAL DEVELOPMENT AND TESTS ONLY. It is never run against Supabase,
-- where these tables already exist and hold user data.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS auth;

-- Minimal stand-in for Supabase's auth.users. The real table is much wider, but the only
-- property our schema depends on is that `id uuid` is a unique, referenceable key.
CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS public.user_problem_progress (
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

CREATE TABLE IF NOT EXISTS public.problem_notes (
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

CREATE TABLE IF NOT EXISTS public.code_snippets (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  problem_id text NOT NULL,
  language text NOT NULL,
  code text NOT NULL DEFAULT ''::text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT code_snippets_pkey PRIMARY KEY (id),
  CONSTRAINT code_snippets_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE IF NOT EXISTS public.design_topics (
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

CREATE TABLE IF NOT EXISTS public.daily_plans (
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

CREATE TABLE IF NOT EXISTS public.study_sessions (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  date timestamp with time zone NOT NULL,
  minutes integer NOT NULL,
  area text NOT NULL,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT study_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT study_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

-- Supabase enables RLS on user tables by default. Mirroring that here means the test
-- suite exercises the same access path as production.
ALTER TABLE public.user_problem_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.problem_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.code_snippets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.design_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.study_sessions ENABLE ROW LEVEL SECURITY;
