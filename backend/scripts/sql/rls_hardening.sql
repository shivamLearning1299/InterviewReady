-- =============================================================================
-- Optional RLS hardening: a least-privilege role for the FastAPI backend.
-- =============================================================================
-- The application currently connects as the Supabase project owner (`postgres`), which
-- has BYPASSRLS — so Row Level Security policies are effectively inert for it. The
-- repository layer already scopes every personal-data query by `user_id`, but RLS should
-- still act as a second line of defence.
--
-- Running this file creates `app_backend`: a login role with exactly the privileges the
-- API needs and **no** BYPASSRLS attribute. Policies can then key off
-- `current_setting('app.current_user_id', true)`, which the session layer sets on every
-- request via `set_config(..., true)`.
--
-- Read it before running it. Adjust the password (use a strong one, stored in your secret
-- manager — never in this file), then run it as the project owner.
--
-- Afterwards, point DATABASE_URL at the new role:
--   postgresql://app_backend.<project-ref>:<password>@<host>:6543/postgres
-- and verify with:  SELECT current_user, rolbypassrls FROM pg_roles WHERE rolname = current_user;
-- =============================================================================

-- 1. Create the role. Replace the password before running.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_backend') THEN
    -- CHANGE THIS PASSWORD. Do not commit the real value.
    CREATE ROLE app_backend LOGIN PASSWORD 'CHANGE_ME_BEFORE_RUNNING';
  END IF;
END
$$;

-- 2. Schema usage and data privileges. No DDL: migrations run as the owner, not as the API.
GRANT USAGE ON SCHEMA public TO app_backend;
GRANT USAGE ON SCHEMA auth TO app_backend;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_backend;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_backend;

-- 3. Apply the same grants to anything created later (so future migrations do not lock
--    the API out of a newly added table).
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_backend;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_backend;

-- 4. Read-only access to auth.users so the API can join a user id to an email if needed.
--    No access to auth.sessions, refresh tokens, or identity data.
GRANT SELECT ON auth.users TO app_backend;

-- 5. Explicitly confirm the role does NOT bypass RLS. This is the whole point.
ALTER ROLE app_backend NOBYPASSRLS;

-- =============================================================================
-- Example policies (adapt the predicate to your table's owner column).
-- =============================================================================
-- With RLS active and `app.current_user_id` set per request, each policy reduces to a
-- comparison against the session variable. The `true` second argument to
-- `current_setting` means "return NULL instead of erroring" when the GUC is unset, so a
-- request that somehow skipped authentication sees zero rows rather than a 500.
--
--   CREATE POLICY user_isolation ON public.user_problem_progress
--     FOR ALL
--     USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
--     WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
--
-- Repeat for problem_notes, code_snippets, daily_plans, study_sessions and the new tables.
--
-- Note: policies never apply to a BYPASSRLS role, which is why this file exists
-- separately from the migrations.
