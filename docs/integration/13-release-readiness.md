# 13 — Release Readiness: Public GitHub Push Audit

**Auditor role:** Release-readiness auditor (pre-push, read-only)
**Repository:** `/Users/shivamsharma/Desktop/interviewready`
**Audit date:** 2026-09-26
**Scope:** 3 commits, 258 tracked files, 26 uncommitted changes (21 modified, 5 untracked source/doc files)
**Method:** direct `git` object inspection (`git log --all -p`, per-commit `git grep`, blob-level search). No prior claim was trusted.
**Proof of channel:** `/tmp/agent-release-proof.txt` written and verified (`RELEASE-ALIVE`).

---

## VERDICT: **SAFE TO PUSH** — no real secret found in history or working tree.

Two pre-push hygiene items are recommended (non-blocking, and neither is a credential):
1. The uncommitted docs containing absolute local paths.
2. Never use `git add -A` / `git add .` — the 5.4 MB PNG and `frontend/node_modules/` + `backend/.venv/` exist on disk.

---

## (A) Secrets in history — THE CRITICAL CHECK

**Result: NO real secret was ever committed. All matches are placeholders, test fixtures, or vendor documentation.**

### A.1 The exact leaked Supabase publishable key

Target string: `sb_publishable_jrSKEo7ELjDv35Yji9H9lw_U0Zq2dqd`

| Probe | Command | Result |
|---|---|---|
| Pickaxe across all commits | `git log --all -S'<key>'` | **no output** |
| Byte-grep every blob in every commit | `git grep -n '<key>' <commit>` for all `git rev-list --all` | **no output** |

**Finding: the key was NEVER committed.** The author's leak into a chat transcript did not propagate into git history. Nothing to remediate. *(Note: it is still validly exposed in that transcript; rotating it remains good practice, but rotation is not required for this push.)*

### A.2 `sb_publishable_` occurrences in history — judged individually

| Location (commit `63533b90`) | Value | Judgement |
|---|---|---|
| `WALKTHROUGH.md:28` | `SUPABASE_PUBLISHABLE_KEY=sb_publishable_...` | **PLACEHOLDER** — literal ellipsis, no key material |
| `backend/.env.example:36` | `SUPABASE_PUBLISHABLE_KEY=` | **PLACEHOLDER** — empty |
| `backend/tests/conftest.py:167,178` | `sb_publishable_test` | **TEST FIXTURE** — literally the word `test`; not a valid Supabase key format |
| `backend/render.yaml:41`, `backend/README.md`, `backend/app/core/config.py:88`, `ARCHITECTURE.md:930` | variable *names* in comments/aliases | **NOT A SECRET** — identifiers only |
| `frontend/**/supabase-js` vendor code + `frontend/package-lock.json` | `key.startsWith('sb_publishable_')` | **VENDOR LOGIC** — library prefix check, no value |

No occurrence matched the leaked key or any other real key value.

### A.3 The real live Postgres password (project `qkuxfobfqioilwbjpvyf`)

- The live password was extracted from `backend/.env` (`DATABASE_URL`) in-memory only — **15 characters, never printed**.
- Literal-string search (`git grep -F`) across **every commit in `git rev-list --all`** and across all tracked files: **0 hits (`HIT=0`)**.
- `qkuxfobfqioilwbjpvyf` appears in history **only** in prose docs (`docs/integration/07-gap-analysis.md:9`, `docs/integration/08-orchestrator-review.md:545`) — a project *identifier*, not a credential. It carries no direct-auth capability on its own.
- `git ls-tree -r` over all commits for `*.env`, `*.env.local`, `Secrets.xcconfig`: **no such path was ever tracked.** The live `.env` files were never committed at any point.

**Finding: the real database password appears NOWHERE in git history — no file, no commit hash, no line number to report.**

### A.4 All `postgresql://` occurrences in history — every one is a placeholder

Every URL matched across all three commits resolves to a documented placeholder:

| File (all 3 commits) | Line | Shape | Judgement |
|---|---|---|---|
| `backend/.env.example` | 16, 20 | `postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:...` | **PLACEHOLDER** — angle-bracket tokens |
| `WALKTHROUGH.md` | 25, 26 | `postgresql://postgres.<ref>:<password>@db.<ref>.supabase.co:5432/postgres` | **PLACEHOLDER** |
| `backend/scripts/sql/rls_hardening.sql` | 18 | `postgresql://app_backend.<project-ref>:<password>@<host>:6543/postgres` | **PLACEHOLDER** — illustrative grant doc |
| `backend/tests/test_units.py` | 321 | `postgresql://u:*****@h:5432/d` | **TEST FIXTURE** |
| `backend/tests/conftest.py` | 55, 117 | fragment only (`postgresql://`) | **NOT A SECRET** |
| `backend/app/core/config.py` | 41, 48, 49 | docstring examples (`postgresql://...`) | **NOT A SECRET** |
| `SUMMARY.md:35`, `WALKTHROUGH.md:121,122,128` | — | prose/backtick fragments | **NOT A SECRET** |
| `backend/scripts/backup_public_schema.py:53`, `inspect_supabase_schema.py:197,198` | — | env-var-read fragments | **NOT A SECRET** |

No line contained a real host + real user + real password combination.

### A.5 Other credential classes

| Pattern | History result | Judgement |
|---|---|---|
| `service_role` | matches only in `frontend/node_modules` JSDoc/README of `supabase-js` v1 (committed in `63533b90`, removed in `8a925c8f`) and as the word in `ARCHITECTURE.md` — no key, no `eyJ` JWT | **VENDOR DOC / PROSE — not a secret** |
| `eyJ` JWT-looking | only `frontend/package-lock.json` + `convert-source-map/README.md` (base64 `sha512-…` integrity hashes / sample strings) | **NOT A SECRET** |
| AWS `AKIA…` | none | **clean** |
| `BEGIN … PRIVATE KEY` | none | **clean** |
| `SUPABASE_PUBLISHABLE_KEY=<value>` | only `63533b90`, and only as name/empty/`...`/`test` | **PLACEHOLDER** |
| Long hardcoded strings in `backend/app` + `frontend/src` | one hit: a nil UUID `00000000-0000-4000-8000-00000000ffff` (`frontend/src/mocks/store.ts:55`) | **NOT A SECRET — demo user ID** |

**Section A conclusion: no real secret, anywhere, in any of the 3 commits. All 3 commits are safe to publish.**

---

## (B) Working-tree secrets — what is staged / about to be committed

### B.1 `git status --porcelain` (26 entries)

21 modified tracked files (`backend/.env.example`, `backend/Dockerfile`, `backend/alembic/*`, `backend/app/**`, `backend/render.yaml`, `backend/tests/test_sync.py`, `docs/integration/04–06`, `frontend/src/features/ai/*`) plus **5 untracked** additions:

- `backend/alembic/versions/0005_ai_context_id_text.py`
- `backend/scripts/pre_deploy_check.py`
- `backend/scripts/sql/0004_0005_supabase_sql_editor.sql`
- `docs/integration/10-verification-report.md`
- `docs/integration/11-ios-client-layer.md`
- `docs/integration/12-docker-network-findings.md`

All are source, migration, or documentation files. The modified `backend/.env.example` is the **example** file (placeholder values only) — intended to be tracked.

### B.2 `.gitignore` coverage — verified with `git check-ignore -v`

| Path | Ruling | Rule |
|---|---|---|
| `backend/.env` | **IGNORED** | `backend/.gitignore:2:.env` |
| `frontend/.env.local` | **IGNORED** | `.gitignore:8:.env.*` |
| `InterviewReady/Configuration/Secrets.xcconfig` | **IGNORED** | `.gitignore:10:*.xcconfig` |
| `node_modules/` | **IGNORED** | `.gitignore:2:node_modules/` |
| `.venv/` | **IGNORED** | `.gitignore:3:.venv/` |
| `dist/` | **IGNORED** | `.gitignore:22:dist/` |
| `frontend/dist/` | **IGNORED** | `.gitignore:22:dist/` |
| `backend/.env.example` | not ignored | correct — `!.env.example` negation; placeholders only |

**All six required paths are covered.** Note `InterviewReady/Configuration/Secrets.xcconfig` does not currently exist on disk; the `*.xcconfig` rule (with a `Secrets.xcconfig.example` negation) covers it pre-emptively if the iOS project is added later.

### B.3 `git ls-files` grepped for secret patterns

Tracked-file grep for JWT/AWS/private-key/`sb_secret_` patterns returned **one false positive**: a `sha512-…eyJ…` npm integrity hash in `frontend/package-lock.json:3399`. **Not a secret.** No tracked file contains a credential.

---

## (C) Repo scope — what will actually be published

`git ls-files | sed 's|/.*||' | sort -u`:

```
.gitignore
ARCHITECTURE.md
SUMMARY.md
WALKTHROUGH.md
backend
docs
frontend
```

Seven top-level entries. The iOS app directory (`InterviewReady/`) is **not tracked at all** — this push contains backend + frontend + docs only. (The iOS source lives outside the repo at `/Users/shivamsharma/interviewready` per `docs/integration/10-verification-report.md:7` — see Section E.)

### C.1 FLAG — the multi-megabyte PNG

| Property | Value |
|---|---|
| File | `Gemini_Generated_Image_tsj0vttsj0vttsj0.png` (repo root) |
| Exact size | **5,662,062 bytes (5.4 MiB)** |
| Tracked? | **NO** — untracked (`??`) |
| Ignored? | **YES** — `.gitignore:34:Gemini_Generated_Image_*.png` |
| Will it be published? | **No, not by a normal push.** It would be published **only** by `git add -A` / `git add .` |

**Judgement: it does not belong in a code repo.** A 5.4 MB AI-generated raster is not source, not a build input, and not referenced by any tracked file. It is already correctly ignored — the risk is purely a blanket `git add -A`. Largest *tracked* blob is only 145 KB (`frontend/package-lock.json`), so the tracked tree itself is lean.

---

## (D) Build artefacts

| Artefact | Present on disk | Tracked files | Verdict |
|---|---|---|---|
| `frontend/dist/` | yes | **0** | NOT TRACKED — removed in `104cb2bb` "Stop tracking frontend/dist" |
| `frontend/node_modules/` | yes | **0** | NOT TRACKED — removed in `8a925c8f` "Stop tracking node_modules" |
| `backend/.venv/` | yes | **0** | NOT TRACKED |
| `__pycache__/`, `DerivedData/`, `schema_snapshot.json` | — | **0** each | NOT TRACKED |
| `*.xcuserstate`, `xcuserdata/` | none found | **0** | clean |

**Confirmed: no generated artefact is committed.** The two cleanup commits succeeded — `git ls-files` returns zero matches for all build/dependency patterns. Both directories remain on disk but are correctly ignored.

---

## (E) Embarrassment check

| Item | Result |
|---|---|
| Absolute local paths `/Users/shivamsharma/...` | **4 hits, 2 files — both UNTRACKED new docs** (`docs/integration/10-verification-report.md:6,7`; `docs/integration/12-docker-network-findings.md:49,289`). Not in any commit yet. |
| Personal email addresses | `shivam@interviewready.dev` (`frontend/src/mocks/client.ts:347`) and `demo@interviewready.app` (`frontend/src/features/auth/pages/login-page.tsx:25`) — **intentional demo/mock fixtures**, non-personal, on project domains. Acceptable. |
| Real names in TODO/FIXME | **none found** |
| Git author identity | `InterviewReady Dev <dev@interviewready.local>` — **clean, no personal identity** |
| Internal IPs (10/172.16-31/192.168) | **none found** |
| `.DS_Store` | **none on disk, none tracked** (ignored) |
| Editor state (`*.xcuserstate`, `xcuserdata/`) | **none found** |

The only genuine embarrassment items are the **four absolute-path lines in the two untracked docs** — a local-filesystem leak, not a credential leak.

---

## PRE-PUSH ACTION LIST

**Must do**
- None blocking. No credential remediation is required.

**Should do**
1. Before committing the new docs, replace `/Users/shivamsharma/...` with `<repo-root>` / relative paths in:
   - `docs/integration/10-verification-report.md` (lines 6, 7)
   - `docs/integration/12-docker-network-findings.md` (lines 49, 289)
2. **Never run `git add -A` / `git add .`.** Add paths explicitly. A blanket add would publish the 5.4 MB `Gemini_Generated_Image_tsj0vttsj0vttsj0.png`, and would expose `.gitignore`-bypassed copies if any tool rewrites ignores.
3. Consider whether the untracked `backend/scripts/sql/0004_0005_supabase_sql_editor.sql` and `backend/alembic/versions/0005_ai_context_id_text.py` are intended for publication — they are legitimate source, just confirm intent.

**Recommended hardening (not required for this push)**
4. Add a secret scanner (`gitleaks` / `trufflehog`) to CI so this stays true after the remote exists.
5. Rotate `sb_publishable_jrSKEo7ELjDv35Yji9H9lw_U0Zq2dqd` out-of-band — it leaked to a chat transcript even though it never reached git.

---

## HIGHEST-RISK FINDING

The highest-risk *finding* is **negative**: the single most dangerous class of defect — a permanent, unrecoverable credential leak in pushed history — is **absent**. The leaked publishable key (`sb_publishable_jrSKEo7ELjDv35Yji9H9lw_U0Zq2dqd`) and the live Postgres password for `qkuxfobfqioilwbjpvyf` both return **zero hits** across every blob of every commit, and no `.env`/`Secrets.xcconfig` file was ever tracked. The residual, *recoverable* risk is procedural: the repo is only safe as long as the operator adds paths explicitly rather than using `git add -A`, because a 5.4 MB PNG and two large ignored dependency trees sit untracked in the working directory.
