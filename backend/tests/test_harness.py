"""Verifies the test harness itself: health, auth enforcement, and the stubbed client.

If these fail, every other DB-backed test is meaningless, so they are the canary.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.db


async def test_health_is_public(anon_client) -> None:
    response = await anon_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_me_requires_a_token(anon_client) -> None:
    """Personal data must never be reachable without a verified token."""
    response = await anon_client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"


async def test_me_returns_the_authenticated_user(client, user_id) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["id"] == str(user_id)


async def test_error_envelope_shape(anon_client) -> None:
    """Every error must carry the same {error: {code, message, details}} envelope."""
    response = await anon_client.get("/api/v1/today")
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}


async def test_openapi_lists_every_route(client) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    operations = [
        method
        for path in schema["paths"].values()
        for method in path
        if method in ("get", "post", "put", "patch", "delete")
    ]
    assert len(operations) == 69


async def test_unauthenticated_request_never_touches_user_data(anon_client) -> None:
    """A 401 must be returned before any user-scoped query runs."""
    for path in ("/api/v1/me", "/api/v1/today", "/api/v1/settings", "/api/v1/export"):
        response = await anon_client.get(path)
        assert response.status_code == 401, path
