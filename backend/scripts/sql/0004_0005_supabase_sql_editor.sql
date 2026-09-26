-- =============================================================================
-- InterviewReady — apply migrations 0004 + 0005 via the Supabase SQL Editor
--
-- WHY THIS EXISTS
-- The deployment target (Render) has no shell access to run `alembic upgrade head`
-- interactively, and the Supabase SQL Editor is the one place you can inspect and run DDL
-- against the project directly. Both migrations are expressible as plain SQL, so this is
-- the same work Alembic performs — not an approximation of it.
--
-- SAFE TO RE-RUN. Every statement is idempotent: constraints are guarded by existence
-- checks, and the repairs are conditional UPDATEs that match nothing on a clean database.
--
-- TAKES A FEW SECONDS. All DDL runs in one transaction; if any statement fails the whole
-- thing rolls back and nothing is left half-applied.
--
-- PREREQUISITE: this MUST be applied AFTER the iOS client stops sending camelCase status
-- values. The constraint added at the end rejects 'notStarted', so applying this while an
-- older client is still writing will make those writes fail.
-- =============================================================================

begin;

-- -----------------------------------------------------------------------------
-- MIGRATION 0004 — user_problem_progress CHECK constraints
--
-- The ORM has always declared these two constraints, but no migration ever created them.
-- That is why a client writing 'notStarted' was accepted silently and then became
-- unreadable to the application. Repair the data first, then constrain it.
-- -----------------------------------------------------------------------------

-- 1. Repair the two camelCase spellings a direct-writing client is known to emit.
--    These are pure aliases, so no information is lost.
update public.user_problem_progress
   set status = 'not_started'
 where status = 'notStarted';

update public.user_problem_progress
   set status = 'needs_revision'
 where status = 'needsRevision';

-- 2. Fold anything else outside the canonical vocabulary (an unknown enum name, a stray
--    casing) to 'not_started' — the column default since 0003, and how the application
--    already interprets "no real progress yet".
update public.user_problem_progress
   set status = 'not_started'
 where status is null
    or status not in ('not_started','attempted','solved','needs_revision','mastered');

-- 3. Clamp out-of-range confidence rather than resetting it: the row keeps the closest
--    in-range value instead of losing its meaning.
update public.user_problem_progress
   set confidence = greatest(0, least(5, confidence))
 where confidence is not null
   and confidence not between 0 and 5;

update public.user_problem_progress
   set confidence = 3
 where confidence is null;

-- 4. Now the constraints, named exactly as app/db/models/dsa.py declares them so Alembic
--    autogenerate reports no drift afterwards.
--
--    `status` may be the legacy `text` type while the ORM declares varchar(30); the
--    comparison casts to text either way, so the constraint is valid on both.
do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'ck_user_problem_progress_status_valid'
           and conrelid = 'public.user_problem_progress'::regclass
    ) then
        alter table public.user_problem_progress
          add constraint ck_user_problem_progress_status_valid
          check (status in ('not_started','attempted','solved','needs_revision','mastered'));
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_constraint
         where conname = 'ck_user_problem_progress_confidence_range'
           and conrelid = 'public.user_problem_progress'::regclass
    ) then
        alter table public.user_problem_progress
          add constraint ck_user_problem_progress_confidence_range
          check (confidence between 0 and 5);
    end if;
end $$;


-- -----------------------------------------------------------------------------
-- MIGRATION 0005 — widen ai_conversations.context_id to TEXT
--
-- The column was uuid, which is right for LLD/HLD (their topics are UUID-keyed) but
-- impossible for DSA: `dsa_problems.id` is the problem SLUG, so the client sends
-- context_id = 'two-sum'. Pydantic rejected it with a 422 and EVERY DSA tutor request
-- failed. Widening uuid -> text is lossless; a UUID renders as its canonical text form.
--
-- The index is dropped and recreated because PostgreSQL cannot alter the type of a column
-- an index depends on. This is expected, not data loss.
-- -----------------------------------------------------------------------------

drop index if exists public.ix_ai_conversations_user_id_context;

alter table public.ai_conversations
    alter column context_id type varchar(300) using context_id::text;

create index if not exists ix_ai_conversations_user_id_context
    on public.ai_conversations (user_id, context_type, context_id);


-- -----------------------------------------------------------------------------
-- Record the migrations as applied, so a later `alembic upgrade head` is a no-op
-- instead of re-running them.
--
-- NOTE: the column is `version_num`, NOT `version`. Read it before trusting the update.
-- -----------------------------------------------------------------------------

-- Confirm the column name first (should return exactly one row: version_num):
-- select column_name from information_schema.columns
--  where table_name = 'alembic_version';

update public.alembic_version
   set version_num = '0005_ai_context_id_text';

commit;


-- =============================================================================
-- VERIFY — run these AFTER the commit
-- =============================================================================

-- Expect exactly these two, with NO doubled 'ck_..._ck_...' prefix:
--   ck_user_problem_progress_confidence_range
--   ck_user_problem_progress_status_valid
select conname
  from pg_constraint
 where conrelid = 'public.user_problem_progress'::regclass
   and contype = 'c'
 order by conname;

-- Expect character varying(300) / text:
select column_name, data_type, character_maximum_length
  from information_schema.columns
 where table_name = 'ai_conversations' and column_name = 'context_id';

-- Expect 0005_ai_context_id_text:
select version_num from public.alembic_version;

-- Expect your 1 row, now canonical:
select problem_id, status, confidence from public.user_problem_progress;

-- Expect 90 — your seeded catalog is untouched:
select count(*) from public.dsa_problems;

-- PROOF THE FIX WORKS: this must FAIL with a check-constraint violation.
-- Run it, see the error, and you have confirmed the silent-corruption path is closed.
-- insert into public.user_problem_progress (id, user_id, problem_id, status, confidence)
-- values (gen_random_uuid(), gen_random_uuid(), 'two-sum', 'notStarted', 3);
