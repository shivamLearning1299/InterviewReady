"""User account tests: profile, settings, devices, and the data export.

The export endpoint is the highest-risk read in the API: it aggregates everything the
service knows about a user, so a mistake there leaks data or produces a half-empty backup.
These tests check both completeness and that no secret is ever included.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.db


# ----------------------------------------------------------------------------------- me
async def test_me_returns_the_authenticated_identity(client, user_id) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user_id)
    assert body["email"]


async def test_me_never_exposes_the_token(client) -> None:
    """A profile response must not echo credentials back."""
    body = (await client.get("/api/v1/me")).text
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "sb_publishable" not in body


async def test_two_users_see_their_own_profile(client, other_client, user_id, other_user_id) -> None:
    assert (await client.get("/api/v1/me")).json()["id"] == str(user_id)
    assert (await other_client.get("/api/v1/me")).json()["id"] == str(other_user_id)


# ------------------------------------------------------------------------------ settings
async def test_settings_are_created_on_first_read(client) -> None:
    """A brand-new user must get usable defaults rather than a 404."""
    response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["daily_dsa_count"] >= 1
    assert body["timezone"]


async def test_settings_can_be_updated(client) -> None:
    response = await client.put(
        "/api/v1/settings", json={"daily_dsa_count": 7, "timezone": "Asia/Kolkata"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["daily_dsa_count"] == 7
    assert body["timezone"] == "Asia/Kolkata"


async def test_settings_update_persists(client) -> None:
    await client.put("/api/v1/settings", json={"theme": "dark"})
    assert (await client.get("/api/v1/settings")).json()["theme"] == "dark"


async def test_settings_update_is_partial(client) -> None:
    """Omitting a field must leave it untouched, not reset it to the default."""
    await client.put("/api/v1/settings", json={"daily_dsa_count": 9, "theme": "dark"})
    await client.put("/api/v1/settings", json={"theme": "light"})

    body = (await client.get("/api/v1/settings")).json()
    assert body["theme"] == "light"
    assert body["daily_dsa_count"] == 9


async def test_settings_reject_an_out_of_range_count(client) -> None:
    response = await client.put("/api/v1/settings", json={"daily_dsa_count": 999})
    assert response.status_code == 422


async def test_revision_count_accepts_zero(client) -> None:
    """Turning revisions off entirely is a legitimate preference."""
    response = await client.put("/api/v1/settings", json={"daily_revision_count": 0})
    assert response.status_code == 200
    assert response.json()["daily_revision_count"] == 0


async def test_settings_are_isolated_between_users(client, other_client) -> None:
    await client.put("/api/v1/settings", json={"daily_dsa_count": 12})
    assert (await other_client.get("/api/v1/settings")).json()["daily_dsa_count"] != 12


async def test_settings_reject_an_absurd_timezone(client) -> None:
    response = await client.put("/api/v1/settings", json={"timezone": "x" * 200})
    assert response.status_code == 422


# ------------------------------------------------------------------------------- devices
async def test_device_can_be_registered(client) -> None:
    response = await client.put(
        "/api/v1/settings/devices",
        json={"device_identifier": "iphone-1", "device_type": "ios", "display_name": "My iPhone"},
    )
    assert response.status_code == 200
    assert response.json()["device_identifier"] == "iphone-1"


async def test_devices_are_listed(client) -> None:
    await client.put(
        "/api/v1/settings/devices", json={"device_identifier": "iphone-1", "device_type": "ios"}
    )
    response = await client.get("/api/v1/settings/devices")
    assert response.status_code == 200
    body = response.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert any(item["device_identifier"] == "iphone-1" for item in items)


async def test_device_registration_is_idempotent(client) -> None:
    """Re-registering the same device must update it, not duplicate it."""
    payload = {"device_identifier": "iphone-1", "device_type": "ios"}
    await client.put("/api/v1/settings/devices", json=payload)
    await client.put("/api/v1/settings/devices", json=payload)

    body = (await client.get("/api/v1/settings/devices")).json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert sum(1 for item in items if item["device_identifier"] == "iphone-1") == 1


async def test_device_requires_an_identifier(client) -> None:
    response = await client.put("/api/v1/settings/devices", json={"device_type": "ios"})
    assert response.status_code == 422


async def test_devices_are_isolated_between_users(client, other_client) -> None:
    await client.put(
        "/api/v1/settings/devices", json={"device_identifier": "iphone-1", "device_type": "ios"}
    )
    body = (await other_client.get("/api/v1/settings/devices")).json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert all(item["device_identifier"] != "iphone-1" for item in items)


# -------------------------------------------------------------------------------- export
async def test_export_is_available_for_an_empty_account(client) -> None:
    """An export must work before any study has happened, or a user cannot back up early."""
    response = await client.get("/api/v1/export")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] >= 1
    assert body["exported_at"]


async def test_export_covers_every_domain(client, seeded_catalog, seeded_topics) -> None:
    """A partial export is worse than none: the user would silently lose data on restore."""
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    await client.put("/api/v1/dsa/problems/two-sum/notes", json={"approach": "hash map"})
    await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "pass", "language": "python"}
    )
    await client.post("/api/v1/dsa/problems/two-sum/attempts", json={"outcome": "solved"})
    await client.put(
        f"/api/v1/lld/{seeded_topics['lld'][0]}/progress", json={"status": "completed"}
    )
    await client.put("/api/v1/ai/chat", json={"message": "hello"})

    body = (await client.get("/api/v1/export")).json()
    for key in (
        "problem_progress",
        "notes",
        "code_snippets",
        "attempt_history",
        "lld_topics",
        "hld_topics",
        "lld_notes",
        "hld_notes",
        "activity",
        "settings",
    ):
        assert key in body, f"export is missing '{key}'"

    assert len(body["problem_progress"]) == 1
    assert len(body["code_snippets"]) == 1
    assert len(body["attempt_history"]) == 1


async def test_export_never_contains_secrets(client, seeded_catalog) -> None:
    """The export is written to disk by clients, so it must not carry credentials."""
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    raw = json.dumps((await client.get("/api/v1/export")).json())

    for forbidden in ("access_token", "refresh_token", "api_key", "password", "secret"):
        assert forbidden not in raw.lower(), f"export leaked a '{forbidden}' field"
    assert "sb_publishable" not in raw


async def test_export_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    body = (await other_client.get("/api/v1/export")).json()
    assert body["problem_progress"] == []


async def test_export_can_exclude_conversations(client) -> None:
    """Conversations are bulky; clients may want a leaner export."""
    await client.post("/api/v1/ai/chat", json={"message": "hello"})
    response = await client.get("/api/v1/export", params={"include_conversations": False})
    assert response.status_code == 200
    assert response.json().get("ai_conversations", []) == []


async def test_export_includes_conversations_by_default(client) -> None:
    await client.post("/api/v1/ai/chat", json={"message": "hello"})
    body = (await client.get("/api/v1/export")).json()
    assert len(body.get("ai_conversations", [])) >= 1
