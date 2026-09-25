"""JWKS fetching over httpx.

PyJWT ships :class:`jwt.PyJWKClient`, which fetches the key set with ``urllib``. That is a
problem in practice: ``urllib`` uses the *system* certificate store, which on macOS is
frequently incomplete (``SSL: CERTIFICATE_VERIFY_FAILED``) unless the user has run
``Install Certificates.command``. A backend that cannot fetch its JWKS cannot authenticate
anyone.

``httpx`` bundles ``certifi``, so TLS verification works out of the box. This client
therefore does the HTTP itself and delegates only the JWK parsing to PyJWT.

It also adds two behaviours the stock client lacks:

* **Single refetch lock.** A burst of concurrent requests for an unknown ``kid`` triggers
  one refetch, not one per request.
* **Bounded negative caching.** Failures are remembered briefly so a JWKS outage does not
  turn every request into a slow timeout, while still recovering quickly.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from app.core.logging import get_logger

logger = get_logger(__name__)

#: How long to remember a failed fetch before retrying (seconds).
NEGATIVE_CACHE_SECONDS = 10


@dataclass(slots=True)
class _CacheEntry:
    jwk_set: PyJWKSet
    fetched_at: float

    def is_fresh(self, ttl: int) -> bool:
        return (time.monotonic() - self.fetched_at) < ttl


class HttpxJWKSClient:
    """Fetches, caches and searches a JWKS document over httpx."""

    def __init__(
        self,
        url: str,
        *,
        cache_ttl_seconds: int = 600,
        timeout: float = 10.0,
    ) -> None:
        self._url = url
        self._ttl = max(60, cache_ttl_seconds)
        self._timeout = timeout
        self._cache: _CacheEntry | None = None
        self._lock = asyncio.Lock()
        self._last_failure_at: float = 0.0
        self._consecutive_failures = 0
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        return self._url

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=5.0),
                follow_redirects=False,
                # Supabase's edge caches the JWKS for 10 minutes itself; a short client
                # timeout keeps a degraded auth server from stalling requests.
                headers={"Accept": "application/json"},
            )
        return self._client

    # ------------------------------------------------------------------ public API
    async def get_signing_key_from_jwt(self, token: str) -> PyJWK:
        """Return the key that should have signed ``token``.

        Raises :class:`jwt.exceptions.PyJWKClientError` subclasses so callers can treat
        "cannot reach the JWKS" differently from "the token is bogus".
        """
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise jwt.exceptions.PyJWKClientError(
                "Could not read the token header while resolving its signing key."
            ) from exc

        kid = header.get("kid")
        algorithm = header.get("alg")

        # Reject algorithm confusion before doing any network work: a token claiming HS256
        # must never be validated against a public key from the JWKS.
        if algorithm is not None and algorithm not in _ALLOWED_ALGORITHMS:
            raise jwt.exceptions.PyJWKClientError(
                f"Unsupported token signing algorithm: {algorithm}"
            )

        jwk_set = await self._get_jwk_set()
        key = self._select_key(jwk_set, kid=kid, algorithm=algorithm)

        if key is None:
            # The key may have been rotated since we cached. Refetch once, then give up.
            logger.info("Signing key not in cached JWKS; refetching", extra={"kid": kid})
            jwk_set = await self._get_jwk_set(force_refresh=True)
            key = self._select_key(jwk_set, kid=kid, algorithm=algorithm)

        if key is None:
            raise jwt.exceptions.PyJWKClientError(
                f"No matching signing key found in the JWKS for kid={kid!r}. "
                "The key may have been revoked, or the token was not issued by this project."
            )

        return key

    async def get_jwk_set(self, *, force_refresh: bool = False) -> PyJWKSet:
        """Expose the parsed key set (used by diagnostics/tests)."""
        return await self._get_jwk_set(force_refresh=force_refresh)

    # ------------------------------------------------------------------- internals
    async def _get_jwk_set(self, *, force_refresh: bool = False) -> PyJWKSet:
        """Return a cached key set, fetching when stale or when forced."""
        if not force_refresh and self._cache is not None and self._cache.is_fresh(self._ttl):
            return self._cache.jwk_set

        # Short-circuit during a JWKS outage so a broken auth server does not make every
        # authenticated request wait for a timeout.
        if (
            not force_refresh
            and self._last_failure_at
            and (time.monotonic() - self._last_failure_at) < NEGATIVE_CACHE_SECONDS
            and self._cache is None
        ):
            raise jwt.exceptions.PyJWKClientConnectionError(
                "The JWKS endpoint was unreachable moments ago; not retrying yet."
            )

        async with self._lock:
            # Another coroutine may have refreshed while we waited for the lock.
            if not force_refresh and self._cache is not None and self._cache.is_fresh(self._ttl):
                return self._cache.jwk_set

            try:
                data = await self._fetch()
            except Exception as exc:
                self._last_failure_at = time.monotonic()
                self._consecutive_failures += 1
                if isinstance(exc, jwt.exceptions.PyJWKClientError):
                    raise
                # Serve a stale key set if we have one: a rotated key we already hold is
                # still valid for the token being verified, and rejecting every request
                # during a brief JWKS blip is a far worse outcome.
                if self._cache is not None:
                    logger.warning(
                        "JWKS fetch failed; serving the previously cached key set",
                        extra={"failures": self._consecutive_failures},
                    )
                    return self._cache.jwk_set
                raise jwt.exceptions.PyJWKClientConnectionError(
                    "Could not fetch the JWKS from the identity provider."
                ) from exc

            self._last_failure_at = 0.0
            self._consecutive_failures = 0
            jwk_set = self._parse(data)
            self._cache = _CacheEntry(jwk_set=jwk_set, fetched_at=time.monotonic())

            logger.info(
                "JWKS refreshed",
                extra={"keys": len(jwk_set.keys), "ttl_seconds": self._ttl},
            )
            return jwk_set

    async def _fetch(self) -> dict[str, Any]:
        response = await self._http().get(self._url)

        if response.status_code >= 400:
            raise jwt.exceptions.PyJWKClientConnectionError(
                f"The JWKS endpoint returned HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise jwt.exceptions.PyJWKClientConnectionError(
                "The JWKS endpoint did not return valid JSON."
            ) from exc

        if not isinstance(payload, dict) or "keys" not in payload:
            raise jwt.exceptions.PyJWKClientConnectionError(
                "The JWKS response has no 'keys' member."
            )

        return payload

    @staticmethod
    def _parse(payload: dict[str, Any]) -> PyJWKSet:
        """Parse the document, distinguishing an empty set from a malformed one.

        Supabase returns ``{"keys": []}`` when the project still uses a legacy shared
        secret (HS256). That is not an error to retry — it is a configuration problem worth
        reporting precisely.
        """
        keys = payload.get("keys") or []
        if not keys:
            raise jwt.exceptions.PyJWKClientError(
                "The JWKS contains no keys. This Supabase project is likely still using a "
                "legacy shared-secret (HS256) signing key. Enable asymmetric JWT signing "
                "keys in the Supabase dashboard so tokens can be verified with a public key."
            )

        try:
            return PyJWKSet.from_dict(payload)
        except Exception as exc:
            raise jwt.exceptions.PyJWKClientError(
                f"Could not parse the JWKS document: {exc}"
            ) from exc

    @staticmethod
    def _select_key(
        jwk_set: PyJWKSet, *, kid: str | None, algorithm: str | None
    ) -> PyJWK | None:
        """Find the key by ``kid``, falling back to an algorithm match.

        Matching on ``kid`` first is correct; falling back to the algorithm lets a token
        with no ``kid`` still be verified when the project publishes exactly one key.
        """
        if kid is not None:
            for key in jwk_set.keys:
                if key.key_id == kid:
                    return key
            return None

        candidates = [key for key in jwk_set.keys if key.algorithm_name == algorithm]
        if len(candidates) == 1:
            return candidates[0]
        # Ambiguous: without a kid we cannot know which key signed the token.
        return None

    # ----------------------------------------------------------------- diagnostics
    def health(self) -> dict[str, Any]:
        return {
            "url": self._url,
            "cached_keys": len(self._cache.jwk_set.keys) if self._cache else 0,
            "cache_age_seconds": (
                round(time.monotonic() - self._cache.fetched_at, 1) if self._cache else None
            ),
            "cache_ttl_seconds": self._ttl,
            "consecutive_failures": self._consecutive_failures,
        }


#: Algorithms accepted from a token header. HS* is deliberately absent.
_ALLOWED_ALGORITHMS = frozenset(
    {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}
)

__all__ = ["NEGATIVE_CACHE_SECONDS", "HttpxJWKSClient"]
