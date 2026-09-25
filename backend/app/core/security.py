"""Supabase Auth JWT verification.

The clients (React, iOS) authenticate against Supabase Auth and send the resulting
access token as ``Authorization: Bearer <token>``. This module is the only place that
decides whether a request is authenticated.

Design notes
------------
* **Asymmetric verification only.** Tokens are verified against the project's public
  JWKS (``/auth/v1/.well-known/jwks.json``) using ES256/RS256. There is no shared-secret
  path, so a leaked ``SUPABASE_JWT_SECRET`` cannot be used to mint a valid token, and the
  backend never needs that secret at all.
* **All of signature, expiry, issuer and audience are checked.** Verifying the signature
  alone would accept a token minted by a *different* Supabase project, since anyone can
  fetch that project's public key.
* **The user id comes from the ``sub`` claim of a verified token** — never from a request
  body, query parameter or header supplied by the client.
* **Key rotation is handled** by caching the JWKS for a bounded time (default 10 minutes)
  and refetching when a ``kid`` is unknown, so a rotated signing key does not cause an
  outage longer than the cache window.
* **Fetching uses httpx, not urllib.** ``jwt.PyJWKClient`` fetches over ``urllib``, which
  relies on the system certificate store — commonly incomplete on macOS, producing
  ``CERTIFICATE_VERIFY_FAILED``. httpx bundles certifi, so TLS verification works
  everywhere without machine-specific setup. See :mod:`app.core.jwks`.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthenticatedError
from app.core.jwks import HttpxJWKSClient
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Algorithms Supabase uses for asymmetric signing keys. HS256 is deliberately excluded.
ALLOWED_ALGORITHMS = ("ES256", "RS256", "ES384", "RS384", "ES512", "RS512")

#: Claims that must be present for a token to be usable as an identity assertion.
REQUIRED_CLAIMS = ("exp", "sub", "iss")


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """The verified identity behind a request.

    ``id`` is the Supabase ``auth.users.id`` UUID taken from the ``sub`` claim.
    """

    id: uuid.UUID
    email: str | None = None
    role: str | None = None
    session_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_anonymous(self) -> bool:
        return self.role == "anon"

    def __str__(self) -> str:  # pragma: no cover - logging aid
        return str(self.id)


class SupabaseTokenVerifier:
    """Verifies Supabase access tokens against the project's JWKS.

    A single instance is created per application (see ``app.api.deps``). The underlying
    :class:`HttpxJWKSClient` owns the key cache and the refetch lock.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        jwks_url = settings.resolved_jwks_url

        self._client: HttpxJWKSClient | None = None
        if jwks_url:
            self._client = HttpxJWKSClient(
                jwks_url,
                cache_ttl_seconds=settings.supabase_jwks_cache_seconds,
                timeout=10.0,
            )
        else:
            logger.warning(
                "SUPABASE_URL is not configured — every authenticated request will fail"
            )

        self._lock = asyncio.Lock()
        self._jwks_failures = 0
        self._last_jwks_failure_at = 0.0

    # ------------------------------------------------------------------ properties
    @property
    def configured(self) -> bool:
        return self._client is not None

    async def aclose(self) -> None:
        """Release the JWKS HTTP client on shutdown."""
        if self._client is not None:
            await self._client.aclose()

    # ----------------------------------------------------------------- verification
    async def verify(self, token: str) -> AuthenticatedUser:
        """Verify ``token`` and return the identity it asserts.

        Raises :class:`UnauthenticatedError` for any failure. The error message is
        deliberately generic — distinguishing "expired" from "bad signature" to an
        unauthenticated caller leaks information.
        """
        if not token:
            raise UnauthenticatedError("Missing bearer token.")

        if self._client is None:
            raise UnauthenticatedError("Authentication is not configured on this server.")

        signing_key = await self._resolve_signing_key(token)

        options = {
            "require": list(REQUIRED_CLAIMS),
            "verify_signature": True,
            "verify_exp": True,
            "verify_iat": False,
            "verify_nbf": True,
            "verify_aud": bool(self._settings.supabase_jwt_audience),
            "verify_iss": bool(self._settings.jwt_issuer),
        }

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._settings.supabase_jwt_audience or None,
                issuer=self._settings.jwt_issuer or None,
                options=options,
                leeway=10,
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthenticatedError("Access token has expired.") from exc
        except jwt.InvalidAudienceError as exc:
            raise UnauthenticatedError("Access token audience is invalid.") from exc
        except jwt.InvalidIssuerError as exc:
            raise UnauthenticatedError("Access token issuer is invalid.") from exc
        except jwt.InvalidTokenError as exc:
            logger.info("Rejected malformed or invalid Supabase token", extra={"reason": str(exc)})
            raise UnauthenticatedError("Access token is invalid.") from exc

        return self._to_user(claims)

    async def _resolve_signing_key(self, token: str) -> Any:
        """Fetch (and cache) the JWKS key identified by the token's ``kid``.

        httpx performs the I/O, so no thread offloading is needed and the cache lock inside
        the client ensures a concurrent burst only produces one refetch.
        """
        assert self._client is not None

        try:
            return await self._client.get_signing_key_from_jwt(token)
        except jwt.exceptions.PyJWKClientConnectionError as exc:
            self._jwks_failures += 1
            self._last_jwks_failure_at = time.monotonic()
            logger.error("Could not reach the Supabase JWKS endpoint", exc_info=True)
            raise UnauthenticatedError("Authentication is temporarily unavailable.") from exc
        except jwt.exceptions.PyJWKClientError as exc:
            # Unknown kid, malformed token header, or an empty JWKS (legacy HS256 project).
            logger.info("Supabase JWKS lookup failed", extra={"reason": str(exc)})
            raise UnauthenticatedError("Access token is invalid.") from exc

    @staticmethod
    def _to_user(claims: dict[str, Any]) -> AuthenticatedUser:
        subject = claims.get("sub")
        try:
            user_id = uuid.UUID(str(subject))
        except (TypeError, ValueError) as exc:
            raise UnauthenticatedError("Access token subject is not a valid user id.") from exc

        email = claims.get("email")
        if not isinstance(email, str):
            email = None

        role = claims.get("role")
        if not isinstance(role, str):
            role = None

        session_id = claims.get("session_id")
        if not isinstance(session_id, str):
            session_id = None

        # A publishable/anon key is itself a JWT with no `sub`. Reject it explicitly so an
        # accidental "Bearer <anon key>" is never treated as a signed-in user.
        if role == "anon":
            raise UnauthenticatedError("Anonymous tokens cannot access user data.")

        return AuthenticatedUser(
            id=user_id,
            email=email,
            role=role,
            session_id=session_id,
            claims=claims,
        )

    # -------------------------------------------------------------------- diagnostics
    def health(self) -> dict[str, Any]:
        """Expose non-sensitive verification state for ``/health/ready``."""
        return {
            "configured": self.configured,
            "jwks_configured": bool(self._settings.resolved_jwks_url),
            "issuer": self._settings.jwt_issuer or None,
            "audience": self._settings.supabase_jwt_audience or None,
            "jwks": self._client.health() if self._client else None,
            "recent_jwks_failures": self._jwks_failures,
        }

    async def ensure_jwks_available(self) -> bool:
        """Actively fetch the JWKS. Used by an optional deep readiness check."""
        if self._client is None:
            return False
        try:
            jwk_set = await self._client.get_jwk_set()
        except Exception:
            logger.warning("JWKS preflight failed", exc_info=True)
            return False
        return bool(jwk_set.keys)


def extract_bearer_token(authorization: str | None) -> str | None:
    """Pull the token out of an ``Authorization`` header.

    Returns ``None`` when the header is absent or not a bearer scheme. Note that
    Supabase publishable keys are sent on the ``apikey`` header, not here, so a
    well-behaved client never lands in this path with a non-JWT value.
    """
    if not authorization:
        return None
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = credentials.strip()
    return token or None
