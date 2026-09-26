# 10 — Independent Verification Report

**Role:** Independent adversarial verifier.
**Date:** 2026-09-26
**Repos under test:**
- Backend: `/Users/shivamsharma/Desktop/interviewready/backend`
- iOS: `/Users/shivamsharma/interviewready`

**Baseline:** working tree at `104cb2bb` plus the uncommitted change set the author
described (8 modified files + 1 new untracked migration). The author's summaries were
treated as unverified assertions. Every claim below was re-derived from source, from a
live PostgreSQL 16.15 cluster created for this purpose, or both.

**Channel proof:** `/tmp/agent-verifier-proof.txt` contains exactly `VERIFIER-ALIVE`
(14 bytes, no trailing newline).

---

## Verdict table

| Claim | Statement | Verdict | Headline evidence |
|-------|-----------|---------|-------------------|
| **A** | Sync protocol now supports all 11 entities | **VERIFIED** | 11/11 `SyncEntity` values mapped; `__init__` kwarg order == call site; `find()` used; no import cycle |
| **B** | Migration 0004 creates correctly-named CHECK constraints via `op.f()` | **VERIFIED** | Live `pg_constraint` shows `ck_user_problem_progress_status_valid` + `ck_user_problem_progress_confidence_range`, zero double-prefixes; counterfactual proves `op.f()` is load-bearing |
| **C** | `ai_conversations.context_id` widened uuid → TEXT | **VERIFIED** (with one latent typing wart, see N-2) | Model/schema agree; `AIChatRequest(context_type='dsa', context_id='two-sum', ...)` accepted; 0005 downgrade regex correct; single head |
| **D** | 292 tests pass with a real database | **VERIFIED** | `292 passed in 11.12s`, zero skips, reproduced twice, against a throwaway Postgres |

**No claim was falsified.** Three NEW problems were found that the author did not
mention (N-1, N-2, N-3) — see below. **N-1 is a real functional gap.**

---

## Environment and method

A dedicated throwaway PostgreSQL cluster was created under `/tmp` on **port 55501 only**,
per the constraint in the task. No other port and no `/tmp/ir-*` path was touched.

```bash
export PGDATA=/tmp/verifier-pg55501/data
export PGPORT=55501
initdb -D "$PGDATA" -U postgres --auth=trust -E UTF8
pg_ctl -D "$PGDATA" -o "-p 55501 -k /tmp/verifier-pg55501 -c listen_addresses=127.0.0.1" \
       -l /tmp/verifier-pg55501/pg.log start
# PostgreSQL 16.15 (Homebrew) on aarch64-apple-darwin25.6.0
psql -h 127.0.0.1 -p 55501 -U postgres -c "CREATE DATABASE ir_verify;"
```

The pre-existing Supabase tables required by migration 0001 were loaded from the repo's
own fixture, exactly as `tests/conftest.py` does:

```bash
psql -h 127.0.0.1 -p 55501 -U postgres -d ir_verify \
     -v ON_ERROR_STOP=1 -f tests/fixtures/legacy_schema.sql
```

---

## CLAIM A — "The sync protocol now supports all 11 entities." — **VERIFIED**

### A.1 All 11 `SyncEntity` values map to a handler — VERIFIED

`app/core/constants.py` declares 11 members:

```
PROBLEM_PROGRESS PROBLEM_ATTEMPT PROBLEM_NOTES CODE_SNIPPET REVISION
LLD_PROGRESS LLD_NOTES HLD_PROGRESS HLD_NOTES STUDY_SESSION USER_SETTINGS
```

`app/services/sync_service.py::_handlers()` returns a dict with exactly these 11 keys
(`STUDY_SESSION` added at line 291). Machine-checked comparison of the AST against the
enum returned an empty set on both sides:

```
handler keys: 11
enum members: 11
MISSING handlers: set()
EXTRA handlers: set()
total mapped: 11 == enum size: 11 -> True
```

### A.2 `SyncService.__init__` param order matches the call site exactly — VERIFIED

Both lists are identical, position for position (13 keyword-only params):

```
 0 sync_repo   1 device_repo   2 progress_repo   3 attempt_repo   4 notes_repo
 5 snippet_repo 6 revision_repo 7 lld_repo        8 hld_repo       9 settings_repo
10 activity_repo 11 session_repo 12 settings
sig == call kwargs: True
```

`session_repo` sits between `activity_repo` and `settings` in both the signature and
`app/api/v1/services.py`.

### A.3 `find()` is used, not the raising `get()` — VERIFIED

`app/repositories/activity.py` gained `find()` (returns `StudySession | None`), distinct
from the pre-existing `get()` which raises `StudySessionNotFoundError`. The handler calls
`find()`:

```
app/services/sync_service.py:671:  current = await self._sessions.find(user_id=user_id, session_id=mutation.record_id)
```

The upsert-vs-insert distinction depends on this: on a fresh create `current` is `None`
and the handler proceeds to `create()`. Using `get()` would raise on every insert.

### A.4 No import cycle between `sync_service` and `study_session_service` — VERIFIED

`sync_service.py` imports only the constant, not the service class:

```
53: from app.services.study_session_service import MAX_SESSION_MINUTES
```

`study_session_service.py` does not import `sync_service` at all, and the only importer of
`SyncService` in the codebase is `app/api/v1/services.py`. Both modules import cleanly in
a fresh interpreter, in either order.

**Claim A verdict: VERIFIED.** (The claim is nonetheless *incomplete* — see N-1.)

---

## CLAIM B — "Migration 0004 creates correctly-named CHECK constraints." — **VERIFIED**

### Reasoning about `op.f()`

`app/db/base.py` sets the convention `{"ck": "ck_%(table_name)s_%(constraint_name)s"}` on
the shared `MetaData`. Alembic's `op.create_check_constraint` funnels through
`CreateCheckConstraintOp.to_constraint()` → `SchemaObjects.check_constraint()`, which
builds a `CheckConstraint` **against the target metadata**, so the naming convention is
applied to whatever name is passed. Passing the already-qualified
`ck_user_problem_progress_confidence_range` therefore re-applies the template.
`op.f(name)` wraps the string in SQLAlchemy's `conv` marker, which instructs the naming
system that the name is already final. The author's reasoning is correct.

### Proof — live `pg_constraint`, not inference

`alembic upgrade head` ran on the throwaway cluster with `TEST_DATABASE_URL` set:

```bash
export TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:55501/ir_verify"
.venv/bin/alembic upgrade head     # 0001 -> 0002 -> 0003 -> 0004 -> 0005, no errors
```

```sql
SELECT conname, contype, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid='public.user_problem_progress'::regclass ORDER BY conname;
```

```
 conname                                   | contype | def
-------------------------------------------+---------+--------------------------------------------------------------
 ck_user_problem_progress_confidence_range | c       | CHECK (((confidence >= 0) AND (confidence <= 5)))
 ck_user_problem_progress_status_valid     | c       | CHECK ((status = ANY (ARRAY['not_started',...,'mastered'])))
 uq_user_problem_progress_user_id_problem_id | u     | UNIQUE (user_id, problem_id)
 user_problem_progress_pkey                | p       | PRIMARY KEY (id)
 user_problem_progress_user_id_fkey        | f       | FOREIGN KEY (user_id) REFERENCES auth.users(id)
```

Exact-match query for the two expected names returned both, spelled correctly; the
double-prefix probe returned **0 rows**:

```sql
SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_%ck_%';   -- (0 rows)
```

### Counterfactual — `op.f()` is load-bearing

Resolving the name through the real `SchemaObjects` path with the project's actual
`NAMING_CONVENTION`:

```
WITHOUT op.f() ->   ck_user_problem_progress_ck_user_problem_progress_confidence_range  (len 66)
WITH    op.f() ->   ck_user_problem_progress_confidence_range                            (len 41)
```

The 66-character variant exceeds PostgreSQL's 63-byte identifier limit, so it would be
silently truncated to `..._confidence_ra` — which matches the `NOTICE` PostgreSQL emitted
when an unwrapped name was attempted during probing. Without `op.f()` this claim's
outcome would be a wrong, truncated constraint name and permanent autogenerate drift.

**Claim B verdict: VERIFIED.**

---

## CLAIM C — "`ai_conversations.context_id` was widened from uuid to TEXT." — **VERIFIED**

### C.1 Model and schema agree — VERIFIED

```
app/db/models/ai.py:57    context_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
app/schemas/ai.py:17      context_id: str | None = Field(default=None, max_length=300, ...)
app/schemas/ai.py:63      (AIConversationSummary) context_id: str | None = None
```

Live column after `upgrade head`:

```
 context_id | character varying | 300
```

The service also dropped the two `str()` casts, consistent with the column now being text
(`problem_id = context_id`, `context_id=conversation.context_id`).

### C.2 `AIChatRequest(context_type='dsa', context_id='two-sum', message='x')` is accepted — VERIFIED

```python
>>> AIChatRequest(context_type='dsa', context_id='two-sum', message='x')
context_id='two-sum'   (type: str)
```

The OLD schema genuinely rejected this — a hand-rebuilt copy of the previous field
(`context_id: uuid.UUID | None`) raised `ValidationError`, reproducing the 422 the author
described. A UUID-shaped string still validates (`'123e4567-…'` accepted), and the new
`max_length=300` correctly rejects a 301-character slug.

### C.3 Migration 0005 downgrade regex guard — CORRECT

The guard is:

```sql
UPDATE public.ai_conversations SET context_id = NULL
WHERE context_id IS NOT NULL AND context_id !~* '^[0-9a-f]{8}-...-[0-9a-f]{12}$'
```

`!~*` is PostgreSQL's **case-insensitive** non-match. That is the right choice: a canonical
uppercase UUID rendered as text must survive narrowing. Verified against the live engine —
uppercase UUIDs are **not** nulled, slugs/empty/malformed values **are**:

```
 canonical lowercase | 123e4567-e89b-…-426614174000 | would_be_nulled = f
 UPPERCASE           | 123E4567-E89B-…-426614174000 | would_be_nulled = f   <- !~* is doing real work
 dsa slug            | two-sum                      | would_be_nulled = t
 empty string        |                              | would_be_nulled = t
```

End-to-end round-trip on real rows (`alembic downgrade 0004` then `upgrade head`):
the slug row was NULLed (documented, intentional — the conversation row survives, only the
context link is dropped), the lowercase UUID row was preserved, and an uppercase UUID row
came back normalized to lowercase via the `::uuid` cast. The index
`ix_ai_conversations_user_id_context` was dropped and recreated on both legs; it is present
at head. The `upgrade` drop-then-alter ordering is necessary because Postgres cannot alter
the type of an indexed column.

### C.4 Single head — VERIFIED

```
$ .venv/bin/alembic heads
0005_ai_context_id_text (head)
```

Full chain is linear: `0001 -> 0002 -> 0003 -> 0004 -> 0005`. No branching.

**Claim C verdict: VERIFIED.** One latent typing inconsistency found that the author did
not mention — see N-2. It does **not** break behaviour, and I initially suspected it did
before proving otherwise.

---

## CLAIM D — "292 tests pass with a real database." — **VERIFIED**

```
$ export TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:55501/ir_verify"
$ .venv/bin/pytest -q -p no:randomly
........................................................................ [ 24%]
........................................................................ [ 49%]
........................................................................ [ 73%]
........................................................................ [ 98%]
....                                                                     [100%]
292 passed in 11.12s
```

**Actual number: 292. Exactly matches the claim.** Reproduced twice (11.26s, 11.12s).

Crucially, this is **not** a run where the DB-backed tests were skipped: the suite was
executed with `TEST_DATABASE_URL` pointing at the throwaway cluster, and
`pytest -rs` reported no skip summary line at all. Collection was also 292. The six new
`study_session` tests in `tests/test_sync.py` ran for real:

```
$ .venv/bin/pytest tests/test_sync.py -q -k study_session
6 passed, 32 deselected in 1.00s
```

Note on methodology: `-p no:randomly` was used because the plugin is not installed; the
suite is already order-independent via per-test transaction rollback.

**Claim D verdict: VERIFIED. The real test count is 292.**

---

## NEW problems found (not mentioned by the author)

### N-1 — `study_session` deletes are silently dropped (REAL FUNCTIONAL GAP)

**Severity: high.** Claim A says the protocol "supports all 11 entities". It supports
**upsert** for all 11, but `_apply_delete()` in `app/services/sync_service.py` has **no
`study_session` branch**. Its `if/elif` chain handles only `code_snippet`,
`problem_notes`, `problem_progress`, `lld_notes`, `hld_notes`, and `revision`. A
`study_session` delete falls through to the `if not deleted:` tail and returns
`skipped_duplicate` with `applied=False`.

Proven end-to-end against the real database and the real ASGI app (temporary probe test,
subsequently deleted — no test file was left behind):

```
UPSERT status:                                              applied
DELETE result:                                              skipped_duplicate | error_code: None | applied: False
sessions still visible after delete:                        1
study_session DELETE entries in pull stream:                0
```

Consequences:
1. A session deleted while offline is **never removed** — it stays visible through
   `GET /api/v1/study-sessions` after the client believes it deleted it.
2. **No tombstone is written** to `sync_changes`, so the deletion never propagates to the
   user's other devices. The row is resurrected on every device, permanently.
3. The client receives `skipped_duplicate`, which the protocol documents as
   "already absent — stop retrying", so the mutation is consumed and lost for good.

Every other entity in the protocol has a delete path; `study_session` is now the only
upsertable entity without one. This is exactly the class of bug the handler was added to
fix, left half-fixed.

### N-2 — `_resolve_context_label` still types `context_id` as `uuid.UUID | None`

**Severity: low (latent).** `app/services/ai_tutor_service.py:379` declares
`context_id: uuid.UUID | None`, but after the schema change the DSA/LLD/HLD call site
passes `payload.context_id`, which is now a plain `str`. For LLD/HLD the value is forwarded
untouched to `repo.get_with_progress(topic_id=...)`, whose column is `UUID`.

I initially judged this a break and tested it adversarially. **It does not break**: SQLAlchemy
binds the parameter as `$n::UUID` from the column type, so a well-formed UUID string is
cast correctly by PostgreSQL. Verified with a real `lld_topics` + `lld_progress` row:

```
progress str-form lookup -> 1 row(s) -> MATCHED
topic    str-form lookup -> 1 row(s)
```

The consequence is confined to error handling: a **malformed** `context_id` for an LLD/HLD
conversation now surfaces as a `DataError` from the driver rather than being rejected at
the schema boundary. It is caught by the surrounding `except Exception` in
`_resolve_context_label` (returns `None` label), but in `_fill_topic_context` the
`uuid.UUID(str(topic_id))` call is only guarded for the *lookup*, so a malformed value
degrades the tutor context rather than erroring cleanly. The annotation should be widened
to `str | None` to match reality. Non-blocking, but it is drift the schema change
introduced and did not clean up.

### N-3 — `study_session` upsert with no `record_id` mints a server-side id

**Severity: low (design consequence).** With no `record_id`, `mutation.record_id` is
`None`, so `find()` is skipped and `create(session_id=None)` runs — the server generates a
new UUID. The client's locally queued row can therefore never be correlated with the
server's, which defeats the stated purpose of the `session_id` parameter added in
`app/repositories/activity.py` ("lets the client correlate its local row with the server's
after a push"). The mutation still reports `applied`, so the client cannot tell that
correlation failed. Verified: a no-`record_id` push returned `applied` with a
server-generated `record_id`. Every other offline entity keys on a client-assigned id;
`study_session` should require one too.

Related, same handler: an **unparseable** `started_at`/`ended_at` silently falls back to
`utcnow()` (`_parse_datetime` returns `None`). Verified — a push with
`started_at="NOT-A-DATE"` and `ended_at="also-not-dates"` returned `applied`. This is a
deliberate, documented trade-off (drain the queue rather than wedge it), but it means a
client with a broken encoder records fabricated study time instead of surfacing a bug.

---

## Commands run (verbatim)

```bash
# channel proof
printf 'VERIFIER-ALIVE' > /tmp/agent-verifier-proof.txt

# cluster (port 55501 only)
export PGDATA=/tmp/verifier-pg55501/data PGPORT=55501
initdb -D "$PGDATA" -U postgres --auth=trust -E UTF8
pg_ctl -D "$PGDATA" -o "-p 55501 -k /tmp/verifier-pg55501 -c listen_addresses=127.0.0.1" \
       -l /tmp/verifier-pg55501/pg.log start
psql -h 127.0.0.1 -p 55501 -U postgres -c "CREATE DATABASE ir_verify;"
psql -h 127.0.0.1 -p 55501 -U postgres -d ir_verify -v ON_ERROR_STOP=1 -f tests/fixtures/legacy_schema.sql

# Claim B
export TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:55501/ir_verify"
export DATABASE_URL="$TEST_DATABASE_URL" DATABASE_URL_DIRECT="$TEST_DATABASE_URL"
.venv/bin/alembic upgrade head
psql -h 127.0.0.1 -p 55501 -U postgres -d ir_verify -c \
  "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='public.user_problem_progress'::regclass ORDER BY conname;"
psql -h 127.0.0.1 -p 55501 -U postgres -d ir_verify -tAc \
  "SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_%ck_%';"

# Claim C
.venv/bin/alembic heads
.venv/bin/alembic downgrade 0004_progress_check_constraints
psql -h 127.0.0.1 -p 55501 -U postgres -d ir_verify -c \
  "SELECT data_type FROM information_schema.columns WHERE table_name='ai_conversations' AND column_name='context_id';"
.venv/bin/alembic upgrade head

# Claim D
.venv/bin/pytest --collect-only -q
.venv/bin/pytest -q -p no:randomly
.venv/bin/pytest tests/test_sync.py -q -p no:randomly -k study_session -v

# Claim A
.venv/bin/python -c "from app.schemas.ai import AIChatRequest; print(AIChatRequest(context_type='dsa', context_id='two-sum', message='x'))"
# AST comparison of SyncEntity members vs _handlers() keys; kwarg-order comparison of
# SyncService.__init__ vs the Services() call site; import of both services in a fresh interpreter.
```

---

## Artifacts

- Proof of channel: `/tmp/agent-verifier-proof.txt` (exactly `VERIFIER-ALIVE`).
- Throwaway cluster: `/tmp/verifier-pg55501/` on port **55501**, created and used only for
  this verification.
- No existing file was modified. Two temporary probe test files were created and deleted;
  their `__pycache__` entries were also removed. `git status` matches the pre-existing
  author change set with no verifier artifacts.

## Bottom line

All four claims are **VERIFIED**, and the claimed test count of **292 is accurate** against
a real database. The verification was not a rubber stamp: it produced a concrete,
reproduced functional defect (**N-1**, `study_session` deletes are dropped and never
tombstoned) plus two lower-severity issues (**N-2**, **N-3**) that the author's summaries
did not disclose. Claim A's wording — "supports all 11 entities" — is true only for the
upsert path and should be read as incomplete.
