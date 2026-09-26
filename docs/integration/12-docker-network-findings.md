# 12 — Docker Network Findings: Supabase Reachability via Pooler

**Date:** 2026-09-26
**Image under test:** `interviewready-api:test` (id `6225a3d000e3`, 397 MB)
**Docker server:** 29.7.2 (Docker Desktop on macOS)
**Verifier role:** Docker/deployment verifier — network-path proof only.

---

## 0. Scope and honesty statement

This document answers exactly one question:

> Can an **IPv4-only container** on Docker's default `bridge` network reach
> **`*.pooler.supabase.com`**?

It does **not** determine, guess, or probe for the correct **pooler region**.
Region discovery by trying credentials against multiple hostnames is credential
spraying and was explicitly out of scope.

**No credentials were used in any command in this document.** Every probe is DNS,
TCP-handshake, or TLS/HTTP layer only. No `psql`, no `asyncpg.connect()`, no
`DATABASE_URL` was ever passed into a container.

All probes used `docker run --rm`, so **no containers were left behind** (verified
at the end — see §7).

---

## 1. Proof of channel (Step 1)

`/tmp/agent-docker-proof.txt` was written with exactly the bytes `DOCKER-ALIVE`
(no trailing newline).

```
$ printf 'DOCKER-ALIVE' > /tmp/agent-docker-proof.txt
$ ls -l /tmp/agent-docker-proof.txt
-rw-r--r--@ 1 shivamsharma  wheel  12 Sep 26 06:36 /tmp/agent-docker-proof.txt
$ cat /tmp/agent-docker-proof.txt
DOCKER-ALIVE
```

Size is 12 bytes = `DOCKER-ALIVE` verbatim.

---

## 2. What the `.env` actually contains (Step 2a)

Read from `/Users/shivamsharma/Desktop/interviewready/backend/.env` (secrets masked):

| Key | Host | Port | Notes |
|---|---|---|---|
| `DATABASE_URL` | `db.qkuxfobfqioilwbjpvyf.supabase.co` | 5432 | **direct host — IPv6-only** |
| `DATABASE_URL_DIRECT` | `db.qkuxfobfqioilwbjpvyf.supabase.co` | 5432 | same direct host |

**Critical observation:** both variables point at the **direct** host. There is
**no pooler hostname anywhere in the user's `.env`**. Both values are therefore
unusable from a default-bridge container, for the reason confirmed in §4.

Because the user had no pooler hostname of their own, the probe below uses the
placeholder `aws-0-ap-south-1.pooler.supabase.com` **strictly as a network-path
probe**. Its region was *not* validated and is *not* being asserted as correct —
see §6.

---

## 3. Exact commands run (Step 2b)

All commands are read-only network probes with **no credentials**.

### 3.1 Container has no `nc` — method note

The first attempt used `nc -zv`, which fails inside this image:

```
$ docker run --rm interviewready-api:test sh -c 'timeout 12 nc -zv aws-0-ap-south-1.pooler.supabase.com 5432'
timeout: failed to run command 'nc': No such file or directory
```

`nc`/`netcat` is **not installed** in `python:3.12-slim`. Subsequent TCP probes
therefore used the image's own Python interpreter and `curl`, which is a *better*
test anyway — it exercises the same runtime the app uses.

### 3.2 DNS resolution (no connection)

```
$ docker run --rm interviewready-api:test sh -c \
    'getent hosts db.qkuxfobfqioilwbjpvyf.supabase.co; \
     echo "[pooler]"; \
     getent hosts aws-0-ap-south-1.pooler.supabase.com'
```

### 3.3 TCP reachability + IPv4/IPv6 egress

```
$ docker run --rm interviewready-api:test python -c "
import socket, time
host='aws-0-ap-south-1.pooler.supabase.com'
ai = socket.getaddrinfo(host, 5432, socket.AF_INET, socket.SOCK_STREAM)
print('IPv4 resolved ->', sorted({a[4][0] for a in ai}))
for port in (5432, 6543):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(12)
    t0=time.time()
    try:
        s.connect((ai[0][4][0], port)); print(f'  IPv4 {host}:{port} CONNECT OK ({time.time()-t0:.2f}s)')
    except Exception as e:
        print(f'  IPv4 {host}:{port} FAILED: {type(e).__name__} {e}')
    finally: s.close()
"
```

```
$ docker run --rm interviewready-api:test sh -c 'cat /proc/net/ipv6_route'
$ docker run --rm interviewready-api:test sh -c \
    'curl -4 -sS -o /dev/null -w "http_code=%{http_code} remote_ip=%{remote_ip}\n" \
     --max-time 15 https://aws-0-ap-south-1.pooler.supabase.com'
```

### 3.4 Reproducing the reported failure (control)

```
$ docker run --rm interviewready-api:test python -c "
import socket
h='db.qkuxfobfqioilwbjpvyf.supabase.co'
print('IPv6 ->', sorted({a[4][0] for a in socket.getaddrinfo(h,5432,socket.AF_INET6,socket.SOCK_STREAM)}))
try:
    socket.getaddrinfo(h,5432,socket.AF_INET,socket.SOCK_STREAM)
except Exception as e: print('IPv4 resolve FAILED:', type(e).__name__, e)
s=socket.socket(socket.AF_INET6,socket.SOCK_STREAM); s.settimeout(10)
try: s.connect(('2406:da12:557:f802:842a:5351:1ff5:a916',5432)); print('IPv6 CONNECT OK')
except Exception as e: print('IPv6 connect FAILED:', type(e).__name__, e, '| errno=', getattr(e,'errno',None))
"
```

---

## 4. Raw output

### 4.1 DNS — direct host vs pooler

```
=== DNS getent hosts ===
[direct]
2406:da12:557:f802:842a:5351:1ff5:a916 db.qkuxfobfqioilwbjpvyf.supabase.co
[pooler]
3.111.105.85    pool-tcp-ap-south-1-ad84943-571391129070ce1e.elb.ap-south-1.amazonaws.com aws-0-ap-south-1.pooler.supabase.com
65.0.195.55     pool-tcp-ap-south-1-ad84943-571391129070ce1e.elb.ap-south-1.amazonaws.com aws-0-ap-south-1.pooler.supabase.com
```

Also confirmed with the image's Python resolver:

```
[A. direct host]
getent ahosts db.qkuxfobfqioilwbjpvyf.supabase.co  ->  getent ahosts: FAILED
```

`getent ahosts` (IPv4/IPv6 stream lookup) **fails** for the direct host — the
name has **no A record at all**. It resolves only via `AF_INET6`.

```
[B. pooler host]
3.111.105.85    STREAM pool-tcp-ap-south-1-ad84943-571391129070ce1e.elb.ap-south-1.amazonaws.com
65.0.195.55     STREAM pool-tcp-ap-south-1-ad84943-571391129070ce1e.elb.ap-south-1.amazonaws.com
```

> **Note on dual-stack:** the task brief called the pooler "dual-stack". What was
> actually observed is that the pooler resolves to **IPv4 (A) records only** —
> two AWS ELB addresses, `3.111.105.85` and `65.0.195.55`. No AAAA record was
> returned for this hostname. That is *sufficient and better* for our purpose:
> IPv4-only is exactly what the IPv4-only bridge network needs. The practical
> conclusion is unchanged — **the pooler is reachable, the direct host is not.**

### 4.2 TCP reachability — pooler

```
IPv4 resolved -> ['3.111.105.85', '65.0.195.55']
  IPv4 aws-0-ap-south-1.pooler.supabase.com:5432 CONNECT OK (0.03s)
  IPv4 aws-0-ap-south-1.pooler.supabase.com:6543 CONNECT OK (0.03s)
```

Both pooler ports answer:
- **5432** — session mode
- **6543** — transaction mode

### 4.3 TLS/HTTP layer through the pooler (IPv4 forced)

```
curl -4 http_code=404 remote_ip=3.111.105.85
--- exit=0 ---
```

A `404` here is a **success signal**: the TCP connection and the TLS handshake
completed against the pooler's HTTP edge (`remote_ip=3.111.105.85` over IPv4).
There is simply no HTTP resource at `/`. This confirms the full IPv4 path works
end-to-end. It is *not* a database authentication attempt — Postgres protocol
was never spoken.

### 4.4 IPv4 egress control

The image has working **IPv4 egress** to the public internet (the pooler
connections above are themselves proof; `1.1.1.1:443` control also succeeded
once probed with a tool present in the image).

### 4.5 IPv6 egress — absent

```
$ cat /proc/net/ipv6_route
00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo
00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000002 00000000 80200001       lo
00000000000000000000000000000000 00 00000000000000000000000000000000 00 00000000000000000000000000000000 ffffffff 00000001 00000000 00200200       lo
count=3
```

Every IPv6 route is scoped to **`lo`** (loopback). There is **no IPv6 default
route and no IPv6 gateway**. Container interfaces are IPv4-only
(`172.17.0.0/16` on the default bridge).

### 4.6 Root cause reproduced (control)

```
IPv6 resolved -> ['2406:da12:557:f802:842a:5351:1ff5:a916']
IPv4 resolve FAILED: gaierror [Errno -5] No address associated with hostname
IPv6 connect FAILED: OSError [Errno 101] Network is unreachable | errno= 101
```

This reproduces the reported failure **exactly** — `OSError: [Errno 101] Network
is unreachable` — and proves both halves of the diagnosis in one shot:
1. the direct host has **no IPv4 (A) record** (`gaierror -5`), so an IPv4-only
   container cannot even address it;
2. the only address it does have is IPv6, and the container has **no IPv6 route**,
   so the connect fails with `ENETUNREACH` (101).

---

## 5. Verdicts

| Question | Answer | Evidence |
|---|---|---|
| Does the container have **IPv4 egress**? | **YES** | pooler `:5432` and `:6543` `CONNECT OK` in 0.03 s; `curl -4` TLS handshake to pooler succeeded (`remote_ip=3.111.105.85`) |
| Does the container have **IPv6 egress**? | **NO** | `/proc/net/ipv6_route` contains only `lo`-scoped routes; `connect()` on the AAAA address → `Errno 101` |
| Can an IPv4-only container **resolve `*.pooler.supabase.com`**? | **YES** | `getent hosts` returned A records `3.111.105.85`, `65.0.195.55` |
| Can the container **reach** the pooler at the TCP layer? | **YES** | `:5432` and `:6543` both `CONNECT OK` |
| Can the container reach the **direct host**? | **NO** | AAAA-only + no IPv6 route → `Errno 101` |
| Was any credential used? | **NO** | all probes DNS / TCP / TLS-HTTP only |

---

## 6. What you must do (definitive)

**The pooler region must be read from the Supabase dashboard by you.** It was
never determined here, and it must not be determined by trying credentials
against candidate regions.

1. Open the Supabase dashboard → your project (`qkuxfobfqioilwbjpvyf`) →
   **Connect** (or **Settings → Database → Connection pooling**).
2. Read the **exact pooler hostname** shown there. It has the shape
   `aws-<N>-<region>.pooler.supabase.com` — the `<N>` prefix (e.g. `aws-0` vs
   `aws-1`) and `<region>` **must be copied verbatim**. Do not infer them.
3. Set **both** of these in `backend/.env` to the pooler connection string:

   ```
   DATABASE_URL=postgresql://postgres.<project-ref>:<password>@<pooler-host>:6543/postgres
   DATABASE_URL_DIRECT=postgresql://postgres.<project-ref>:<password>@<pooler-host>:6543/postgres
   ```

   Notes:
   - **Port 6543** = transaction pooling, the correct choice for a
     serverless/containerised API with many short-lived connections.
     **Port 5432** = session pooling (also proven reachable, §4.2).
   - The **username must carry the project ref** in pooler mode:
     `postgres.<project-ref>` (i.e. `postgres.qkuxfobfqioilwbjpvyf`), *not* bare
     `postgres` as used for the direct host. Getting this wrong yields an auth
     failure, not a network failure.
   - If the app uses `asyncpg` with prepared-statement caching, transaction mode
     (6543) may require disabling statement caching. Session mode (5432) is the
     drop-in fallback if you hit that.
4. Re-run the container and confirm it starts. Then re-run the API's own
   `/health/ready` probe.

**Definitive statement:** the network defect is *not* in the container, the image,
or the Docker network — it is purely that `.env` points at an IPv6-only direct
host. Pointing `DATABASE_URL` at the correct, dashboard-verified pooler hostname
is the entire fix. The IPv4 path itself is already proven working.

---

## 7. Dockerfile review (Step 4) — no edits made

Read `/Users/shivamsharma/Desktop/interviewready/backend/Dockerfile`. Reporting only.

### 7.1 Does `CMD` honour `$PORT` with a default? — **YES, correct**

```dockerfile
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

- Uses `${PORT:-8000}` → falls back to `8000` when `PORT` is unset. Verified
  in-container: `PORT=<unset>` when not passed, so the default is what a plain
  `docker run` gets.
- Runs `alembic upgrade head` first — migrations either succeed or the container
  fails loudly. Reasonable for a release step.

### 7.2 Does `HEALTHCHECK` probe the right port? — **YES, correct**

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health/ready" || exit 1
```

- Probes `${PORT:-8000}`, matching the `CMD` exactly — so it stays correct when
  the platform injects a different `PORT`. This is the right coupling; a
  hardcoded `8000` here would have been the classic divergence bug.
- `curl` is installed in the runtime stage, so the check is executable.
- `--start-period=40s` gives the migration + startup time room before retries
  count. Sensible.

### 7.3 Is `exec` used so signals reach uvicorn? — **YES, correct**

- `exec uvicorn ...` is present. Without it, `sh` would remain PID 1 and `SIGTERM`
  from `docker stop` / the orchestrator would not propagate to `uvicorn`,
  producing the familiar 10-second-timeout-then-`SIGKILL` ungraceful shutdown.
  With `exec`, `uvicorn` replaces the shell and receives signals directly. Correct.
- **Residual caveat (not a defect, worth knowing):** because the process starts as
  `sh -c "alembic upgrade head && exec uvicorn ..."`, signals sent *during* the
  migration phase go to `sh`, not to `alembic`. Shutdown during a long migration
  would not be graceful. This is a minor, common trade-off, not a bug — flagged
  only for completeness.

### 7.4 Other observations

- **Non-root:** `USER appuser` (uid 1000) is set before the runtime `CMD`; `EXPOSE`
  and `HEALTHCHECK` precede it but neither needs privilege. Good hygiene.
- **Multi-stage:** build toolchain (`build-essential`, `libpq-dev`) stays in the
  builder; runtime carries only `libpq5` + `curl`. Correct separation.
- **Python 3.12 pinned** with a documented rationale (asyncpg/SQLAlchemy not yet
  validated on 3.13+). Reasonable and deliberate.
- **`COPY --chown=appuser:appuser . .`** — the whole build context lands in the
  image. `.dockerignore` exists (610 bytes) and was not audited here; worth a
  separate check that `.env`, `.venv`, and `.pytest_cache` are excluded, since a
  leaked `.env` inside the image would be a real (if unrelated) defect.
- Driver sanity inside the image: `asyncpg 0.31.0`, `sqlalchemy 2.0.54` — both
  import cleanly.

**Dockerfile defects found that affect the reported issue: NONE.**

---

## 8. Cleanup

Every probe used `docker run --rm`. Verified:

```
$ docker ps -a --filter ancestor=interviewready-api:test --format '{{.ID}} {{.Names}} {{.Status}}'
(no output — no containers remain)
```

No containers, images, or networks were created, modified, or deleted. No files
were modified except `/tmp/agent-docker-proof.txt` and this document.
