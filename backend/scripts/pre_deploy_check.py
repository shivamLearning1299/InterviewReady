"""Fail a deployment before it starts, instead of after it is unreachable.

Run this as part of the release step. It checks the two configuration mistakes that are
invisible locally and only surface once the service is live, where diagnosing them costs far
more than catching them here.

    1. A database host that a hosted platform cannot resolve.
       `db.<ref>.supabase.co` publishes ONLY an AAAA record (verified by DNS query). IPv4-only
       hosts — Render's default networking among them — cannot reach it. The app works fine on
       a developer's Mac, which has IPv6, and fails on the platform.

    2. A wildcard CORS origin in production.
       `main.py` already raises at startup for this, but a container that crash-loops is a
       worse signal than a check that refuses to release.

Usage::

    python -m scripts.pre_deploy_check
"""

from __future__ import annotations

import socket
import sys

from app.core.config import get_settings

#: Hosts that resolve only over IPv6, so an IPv4-only platform cannot reach them.
_IPV6_ONLY_HOST = "db."


def _fail(message: str) -> None:
    print(f"  ✗ {message}")


def _ok(message: str) -> None:
    print(f"  ✓ {message}")


def check_database_host() -> bool:
    """Reject the direct Supabase host when the deploy target is IPv4-only."""
    settings = get_settings()
    url = settings.migration_database_url
    if "@" not in url:
        _fail("migration_database_url is not a parseable connection string")
        return False

    hostport = url.split("@")[-1].split("/")[0]
    host = hostport.split(":")[0]
    print(f"\n[1/3] database host: {host}")

    if ".pooler.supabase.com" in host:
        _ok("using the Supabase pooler (dual-stack, supported for hosted deploys)")
        return True

    if host.startswith(_IPV6_ONLY_HOST) and host.endswith(".supabase.co"):
        # Resolve to show the actual evidence rather than asserting it.
        has_a = bool(_resolve(host, socket.AF_INET))
        _fail(
            f"'{host}' is the direct Supabase host. IPv4 (A) record: "
            f"{'present' if has_a else 'ABSENT'}."
        )
        # Only report the IPv6 result when the lookup succeeded: a restricted DNS resolver
        # returns nothing for both families, and claiming "IPv6 absent" from that would be a
        # misleading conclusion drawn from a failed lookup.
        has_aaaa = bool(_resolve(host, socket.AF_INET6))
        if has_a or has_aaaa:
            _fail(f"IPv6 (AAAA) record: {'present' if has_aaaa else 'ABSENT'}.")
        else:
            _ok("(DNS lookup returned nothing here; the reason below stands regardless)")
        _fail(
            "An IPv4-only platform (Render default) cannot resolve this. Use the pooler: "
            "aws-0-<region>.pooler.supabase.com (dashboard > Connect > Session pooler)."
        )
        return False

    _ok("host is not the IPv6-only Supabase direct endpoint")
    return True


def check_cors() -> bool:
    """A wildcard origin with credentials is both insecure and rejected at startup."""
    settings = get_settings()
    origins = settings.cors_origins
    print(f"\n[2/3] CORS origins: {origins or '(none configured)'}")

    if not origins:
        _fail("no CORS origins configured — browser clients will be blocked")
        return False

    if settings.is_production and "*" in origins:
        _fail("wildcard origin is not permitted in production")
        return False

    for origin in origins:
        if origin.startswith("http://localhost") and settings.is_production:
            _ok(f"'{origin}' looks like a development origin in production — double-check it")
        if "*" in origin and not settings.is_production:
            _ok("wildcard is allowed outside production")

    _ok("origins are explicit")
    return True


def check_required_settings() -> bool:
    """Confirm the values that make the API able to answer a request at all."""
    settings = get_settings()
    print("\n[3/3] required settings")
    healthy = True

    checks = [
        ("DATABASE_URL", settings.is_connectable, "database-backed endpoints would return 503"),
        ("SUPABASE_URL", bool(settings.supabase_url), "every authenticated endpoint would 401"),
        ("SUPABASE_JWT_AUDIENCE", bool(settings.supabase_jwt_audience), "token audience unverified"),
    ]
    for name, present, consequence in checks:
        if present:
            _ok(f"{name} is set")
        else:
            _fail(f"{name} is missing — {consequence}")
            healthy = False

    if not settings.ai_api_key:
        _ok("AI_API_KEY is not set — the tutor will return 503, everything else works")

    _ok(f"APP_ENV={settings.app_env}")
    return healthy


def _resolve(host: str, family: socket.AddressFamily) -> list[str]:
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)]
    except (socket.gaierror, OSError):
        return []


def main() -> int:
    print("InterviewReady pre-deploy configuration check")
    results = [check_database_host(), check_cors(), check_required_settings()]

    print()
    if all(results):
        print("All checks passed — safe to deploy.")
        return 0
    print("Refusing to deploy: fix the items marked ✗ above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
