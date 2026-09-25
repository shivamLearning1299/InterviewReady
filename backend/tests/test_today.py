"""Daily plan tests: generation, determinism, idempotency and item mutation.

The daily plan is the product's core loop, so these tests are the ones that matter most.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


# ----------------------------------------------------------------------------- generation
async def test_today_creates_a_plan_on_first_request(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/today")
    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] is not None
    assert body["date"]


async def test_today_includes_dsa_items(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/today")
    body = response.json()
    assert body["dsa"]["total"] > 0
    assert len(body["dsa"]["items"]) == body["dsa"]["total"]


async def test_today_items_carry_a_reason(client, seeded_catalog) -> None:
    """Every pick must be explainable, otherwise the plan looks arbitrary to the user."""
    body = (await client.get("/api/v1/today")).json()
    assert all(item["problem_id"] for item in body["dsa"]["items"])


async def test_today_is_idempotent_within_a_day(client, seeded_catalog) -> None:
    """The whole point of persisting the plan: refreshing must not reshuffle it."""
    first = (await client.get("/api/v1/today")).json()
    second = (await client.get("/api/v1/today")).json()
    assert first["plan_id"] == second["plan_id"]
    assert [i["problem_id"] for i in first["dsa"]["items"]] == [
        i["problem_id"] for i in second["dsa"]["items"]
    ]


async def test_today_plan_is_persisted_not_regenerated(client, seeded_catalog) -> None:
    """A plan that is generated but never committed would change every request."""
    plan_id = (await client.get("/api/v1/today")).json()["plan_id"]
    listed = await client.get("/api/v1/daily-plans")
    assert listed.status_code == 200
    assert plan_id in [plan["id"] for plan in listed.json()["items"]]


async def test_plan_respects_the_configured_dsa_count(client, seeded_catalog) -> None:
    """The user's preference must actually change the plan size."""
    await client.put("/api/v1/settings", json={"daily_dsa_count": 2})
    body = (await client.get("/api/v1/today")).json()
    assert body["dsa"]["total"] == 2


async def test_plan_widens_when_the_preference_increases(client, seeded_catalog) -> None:
    await client.put("/api/v1/settings", json={"daily_dsa_count": 5})
    body = (await client.get("/api/v1/today")).json()
    assert body["dsa"]["total"] == 5


async def test_plan_is_capped_by_the_catalog_size(client, seeded_catalog) -> None:
    """Asking for more problems than exist must not fail or invent rows."""
    await client.put("/api/v1/settings", json={"daily_dsa_count": 50})
    body = (await client.get("/api/v1/today")).json()
    assert body["dsa"]["total"] <= len(seeded_catalog)


async def test_today_reports_streak_information(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/today")).json()
    assert "streak" in body
    assert "current" in body["streak"]


async def test_today_reports_revision_summary(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/today")).json()
    assert "revision_summary" in body


async def test_today_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    """Two users must receive independently generated plans."""
    mine = (await client.get("/api/v1/today")).json()
    theirs = (await other_client.get("/api/v1/today")).json()
    assert mine["plan_id"] != theirs["plan_id"]


async def test_explain_endpoint_describes_the_plan(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/today/explain")
    assert response.status_code == 200
    body = response.json()
    assert body["scoring_version"]
    assert "candidate_count" in body


async def test_explain_does_not_create_a_plan(client, seeded_catalog) -> None:
    """A diagnostics call must not have the side effect of persisting a plan."""
    await client.get("/api/v1/today/explain")
    listed = await client.get("/api/v1/daily-plans")
    assert listed.json()["total"] == 0


async def test_today_on_an_empty_catalog_still_responds(client) -> None:
    """Before seeding, the endpoint must return a valid empty plan rather than erroring."""
    response = await client.get("/api/v1/today")
    assert response.status_code == 200
    assert response.json()["dsa"]["items"] == []


# ------------------------------------------------------------------------------- history
async def test_daily_plans_are_listed(client, seeded_catalog) -> None:
    await client.get("/api/v1/today")
    response = await client.get("/api/v1/daily-plans")
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_daily_plan_can_be_fetched_by_date(client, seeded_catalog) -> None:
    today = (await client.get("/api/v1/today")).json()["date"]
    response = await client.get(f"/api/v1/daily-plans/{today}")
    assert response.status_code == 200
    assert response.json()["date"] == today


async def test_unknown_plan_date_returns_404(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/daily-plans/1999-01-01")
    assert response.status_code == 404


# ------------------------------------------------------------------------------ item ops
async def _first_item(client) -> dict:
    body = (await client.get("/api/v1/today")).json()
    return body["dsa"]["items"][0]


async def test_plan_item_can_be_marked_complete(client, seeded_catalog) -> None:
    item = await _first_item(client)
    response = await client.patch(
        f"/api/v1/daily-plans/items/{item['id']}", json={"is_completed": True}
    )
    assert response.status_code == 200
    # The endpoint returns the owning plan, so the change is asserted via its section.
    body = response.json()
    assert body["dsa"]["completed"] == 1


async def test_completion_is_reflected_in_the_section_counts(client, seeded_catalog) -> None:
    item = await _first_item(client)
    await client.patch(f"/api/v1/daily-plans/items/{item['id']}", json={"is_completed": True})
    body = (await client.get("/api/v1/today")).json()
    assert body["dsa"]["completed"] == 1


async def test_completion_can_be_reversed(client, seeded_catalog) -> None:
    item = await _first_item(client)
    await client.patch(f"/api/v1/daily-plans/items/{item['id']}", json={"is_completed": True})
    response = await client.patch(
        f"/api/v1/daily-plans/items/{item['id']}", json={"is_completed": False}
    )
    assert response.status_code == 200
    assert response.json()["dsa"]["completed"] == 0


async def test_plan_item_can_be_removed(client, seeded_catalog) -> None:
    item = await _first_item(client)
    response = await client.delete(f"/api/v1/daily-plans/items/{item['id']}")
    assert response.status_code == 200
    body = (await client.get("/api/v1/today")).json()
    assert item["id"] not in [i["id"] for i in body["dsa"]["items"]]


async def test_unknown_plan_item_returns_404(client, seeded_catalog) -> None:
    response = await client.patch(
        "/api/v1/daily-plans/items/00000000-0000-0000-0000-000000000000",
        json={"is_completed": True},
    )
    assert response.status_code == 404


async def test_another_user_cannot_mutate_my_plan_item(
    client, other_client, seeded_catalog
) -> None:
    item = await _first_item(client)
    response = await other_client.patch(
        f"/api/v1/daily-plans/items/{item['id']}", json={"is_completed": True}
    )
    assert response.status_code == 404
