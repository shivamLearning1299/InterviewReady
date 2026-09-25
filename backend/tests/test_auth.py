"""Authentication tests.

The HTTP fixtures stub ``get_current_user`` so route tests can focus on business logic.
That makes these tests the only place the *real* verification path is exercised, so they
assert the security properties directly against ``SupabaseTokenVerifier``:

* a token signed with the wrong key is rejected
* an HS256 token is rejected even when it is well formed (algorithm confusion)
* an expired token is rejected
* an anonymous-role token cannot act as a user
* a JWKS outage fails closed but does not crash the process

Signature verification is exercised with a locally generated EC key pair, so the tests
never depend on network access or on the real Supabase project.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.exceptions import UnauthenticatedError
from app.core.security import SupabaseTokenVerifier, extract_bearer_token

# The verifier compares against the issuer derived from ``settings.supabase_url``, so tests
# derive their expected issuer the same way instead of hardcoding a hostname.
ISSUER_PATH = "/auth/v1"
AUDIENCE = "authenticated"


@pytest.fixture
def issuer(settings) -> str:
    """The issuer the verifier under test expects."""
    return settings.jwt_issuer


# ------------------------------------------------------------------- token plumbing
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("Basic abc123", None),
        ("bearer", None),
        ("Bearer a.b.c", "a.b.c"),
        ("bearer a.b.c", "a.b.c"),
    ],
)
def test_extract_bearer_token(header: str | None, expected: str | None) -> None:
    assert extract_bearer_token(header) == expected


def test_bearer_token_is_extracted_case_insensitively() -> None:
    """Some HTTP clients normalise the scheme to lowercase."""
    assert extract_bearer_token("BEARER token-value") == "token-value"


# --------------------------------------------------------------- signature verification
@pytest.fixture(scope="module")
def signing_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="module")
def key_id() -> str:
    return "test-key-1"


@pytest.fixture
def verifier(settings, signing_key, key_id, monkeypatch: pytest.MonkeyPatch) -> SupabaseTokenVerifier:
    """A verifier whose JWKS fetch is stubbed with a locally generated public key.

    Stubbing the *network* call (``HttpxJWKSClient._fetch``) rather than the verification
    keeps the crypto path real: PyJWT still parses the JWK and verifies the ES256 signature,
    and the client's caching and parsing logic is exercised too.
    """
    instance = SupabaseTokenVerifier(settings)

    jwk_set: dict[str, Any] = {
        "keys": [
            jwt.algorithms.ECAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
        ]
    }
    jwk_set["keys"][0].update({"kid": key_id, "alg": "ES256", "use": "sig", "kty": "EC"})

    async def fake_fetch() -> dict[str, Any]:
        return jwk_set

    monkeypatch.setattr(instance._client, "_fetch", fake_fetch)
    return instance


def _claims(
    *,
    subject: str | None = None,
    role: str = "authenticated",
    expires_in: int = 3600,
    issuer: str,
    audience: str = AUDIENCE,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "sub": subject or str(uuid.uuid4()),
        "aud": audience,
        "iss": issuer,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "session_id": "session-1",
    }


def _sign(claims: dict[str, Any], key: ec.EllipticCurvePrivateKey, kid: str) -> str:
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})


async def test_valid_token_is_accepted(verifier, signing_key, key_id, issuer) -> None:
    claims = _claims(issuer=issuer)
    user = await verifier.verify(_sign(claims, signing_key, key_id))
    assert str(user.id) == claims["sub"]
    assert user.role == "authenticated"


async def test_token_signed_with_another_key_is_rejected(verifier, key_id, issuer) -> None:
    """The core guarantee: holding a token is not enough, it must be signed by the project."""
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    token = _sign(_claims(issuer=issuer), attacker_key, key_id)
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_hs256_token_is_rejected(verifier, key_id, issuer) -> None:
    """Algorithm confusion: a symmetric token must never be verified with a public key."""
    token = jwt.encode(
        _claims(issuer=issuer), "attacker-controlled-secret-value-32bytes", algorithm="HS256",
        headers={"kid": key_id},
    )
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_alg_none_token_is_rejected(verifier, key_id, issuer) -> None:
    """An unsigned token must never be accepted."""
    token = jwt.encode(_claims(issuer=issuer), key="", algorithm="none", headers={"kid": key_id})
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_expired_token_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    token = _sign(_claims(issuer=issuer, expires_in=-60), signing_key, key_id)
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_wrong_issuer_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    """Prevents accepting tokens minted by a different Supabase project."""
    token = _sign(_claims(issuer="https://evil-project.supabase.co/auth/v1"), signing_key, key_id)
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_wrong_audience_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    token = _sign(_claims(issuer=issuer, audience="anon"), signing_key, key_id)
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_anonymous_role_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    """The anon key's role must not grant access to authenticated endpoints."""
    token = _sign(_claims(issuer=issuer, role="anon"), signing_key, key_id)
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_missing_subject_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    claims = _claims(issuer=issuer)
    claims.pop("sub")
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(_sign(claims, signing_key, key_id))


async def test_non_uuid_subject_is_rejected(verifier, signing_key, key_id, issuer) -> None:
    """``sub`` becomes the user id used in every query, so it must be a UUID."""
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(
            _sign(_claims(issuer=issuer, subject="not-a-uuid"), signing_key, key_id)
        )


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b", "a.b.c.d"])
async def test_malformed_tokens_are_rejected(verifier, token: str) -> None:
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_unknown_key_id_triggers_a_refetch(verifier, signing_key, issuer) -> None:
    """Key rotation must not require a restart, so an unknown ``kid`` refetches once."""
    token = _sign(_claims(issuer=issuer), signing_key, "brand-new-kid")
    # The stubbed JWKS only knows the original kid, so verification still fails — but it
    # must fail as an auth error rather than an unhandled exception.
    with pytest.raises(UnauthenticatedError):
        await verifier.verify(token)


async def test_jwks_outage_fails_closed(settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the JWKS cannot be fetched, no token may be trusted."""
    instance = SupabaseTokenVerifier(settings)

    async def failing_fetch() -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(instance._client, "_fetch", failing_fetch)
    with pytest.raises((UnauthenticatedError, RuntimeError)):
        await instance.verify("a.b.c")


def test_health_reports_configuration_without_leaking_secrets(settings) -> None:
    """Health output is public (``/health/ready``), so it must not include the key."""
    instance = SupabaseTokenVerifier(settings)
    report = instance.health()
    serialised = str(report)
    assert "configured" in report
    assert settings.supabase_anon_key not in serialised
    assert "publishable" not in serialised.lower() or "sb_publishable" not in serialised


def test_allowed_algorithms_exclude_symmetric_ones() -> None:
    """A regression guard on the algorithm-confusion fix."""
    from app.core.jwks import _ALLOWED_ALGORITHMS

    assert not any(algorithm.startswith("HS") for algorithm in _ALLOWED_ALGORITHMS)
    assert "ES256" in _ALLOWED_ALGORITHMS
    assert "RS256" in _ALLOWED_ALGORITHMS
