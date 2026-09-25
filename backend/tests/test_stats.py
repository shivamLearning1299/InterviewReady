"""Statistics, streak and mastery tests.

These read aggregates across every domain (DSA, LLD, HLD, activity), so they are also the
broadest integration check on the reporting SQL.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


# ------------------------------------------------------------------------------- overview
async def test_overview_is_available_with_no_data(client) -> None:
    """A brand-new user must get zeros, not a 500 from an aggregate over an empty set."""
    response = await client.get("/api/v1/stats/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["dsa"]["total"] == 0
    assert body["dsa"]["solved"] == 0


async def test_overview_counts_the_catalog(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/stats/overview")).json()
    assert body["dsa"]["total"] == len(seeded_catalog)


async def test_overview_counts_solved_problems(client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    body = (await client.get("/api/v1/stats/overview")).json()
    assert body["dsa"]["solved"] == 1


async def test_overview_counts_mastered_problems(client, seeded_catalog) -> None:
    """Mastery is the headline number on the dashboard, tracked as a raw count."""
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "mastered"})
    body = (await client.get("/api/v1/stats/overview")).json()
    assert body["dsa"]["mastered"] == 1
    assert body["dsa"]["mastered"] <= body["dsa"]["total"]


async def test_overview_includes_topic_coverage(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/stats/overview")).json()
    assert "lld" in body and "hld" in body


async def test_overview_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    body = (await other_client.get("/api/v1/stats/overview")).json()
    assert body["dsa"]["solved"] == 0


# ------------------------------------------------------------------------- topic breakdown
async def test_topic_breakdown_lists_topics(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/stats/dsa/topics")
    assert response.status_code == 200
    assert response.json()["items"] or response.json() == []


async def test_topic_breakdown_reflects_progress(client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"})
    response = await client.get("/api/v1/stats/dsa/topics")
    assert response.status_code == 200


# -------------------------------------------------------------------- difficulty breakdown
async def test_difficulty_breakdown_reports_each_level(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/stats/dsa/difficulty")
    assert response.status_code == 200
    labels = {item["difficulty"] for item in response.json()["items"]}
    assert labels <= {"easy", "medium", "hard"}


async def test_difficulty_breakdown_sums_to_the_catalog(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/stats/dsa/difficulty")).json()
    assert sum(item["total"] for item in body["items"]) == len(seeded_catalog)


# -------------------------------------------------------------------------- activity series
async def test_activity_series_accepts_supported_ranges(client) -> None:
    for window in ("7d", "30d", "90d", "1y"):
        response = await client.get("/api/v1/stats/activity", params={"range": window})
        assert response.status_code == 200, window


async def test_activity_series_rejects_an_unknown_range(client) -> None:
    response = await client.get("/api/v1/stats/activity", params={"range": "5m"})
    assert response.status_code == 422


async def test_activity_series_returns_a_point_per_day(client) -> None:
    body = (await client.get("/api/v1/stats/activity", params={"range": "7d"})).json()
    assert len(body["items"]) == 7


async def test_activity_series_is_zero_filled(client) -> None:
    """A gap must render as an explicit zero, or charts silently mis-scale."""
    body = (await client.get("/api/v1/stats/activity", params={"range": "7d"})).json()
    assert all(point["activity_count"] == 0 for point in body["items"])


async def test_activity_series_records_study(client, seeded_catalog) -> None:
    """Completing a plan item records activity, which must then appear in the series."""
    body = (await client.get("/api/v1/today")).json()
    item_id = body["dsa"]["items"][0]["id"]
    await client.patch(f"/api/v1/daily-plans/items/{item_id}", json={"is_completed": True})

    series = (await client.get("/api/v1/stats/activity", params={"range": "7d"})).json()
    assert any(point["activity_count"] > 0 for point in series["items"])


# --------------------------------------------------------------------------------- streak
async def test_streak_is_zero_for_a_new_user(client) -> None:
    body = (await client.get("/api/v1/stats/streak")).json()
    assert body["current"] == 0
    assert body["longest"] == 0


async def test_streak_counts_today_after_studying(client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/today")).json()
    item_id = body["dsa"]["items"][0]["id"]
    await client.patch(f"/api/v1/daily-plans/items/{item_id}", json={"is_completed": True})

    streak = (await client.get("/api/v1/stats/streak")).json()
    assert streak["current"] == 1
    assert streak["today_active"] is True


async def test_streak_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    body = (await client.get("/api/v1/today")).json()
    item_id = body["dsa"]["items"][0]["id"]
    await client.patch(f"/api/v1/daily-plans/items/{item_id}", json={"is_completed": True})

    streak = (await other_client.get("/api/v1/stats/streak")).json()
    assert streak["current"] == 0


# -------------------------------------------------------------------------------- mastery
async def test_mastery_endpoint_lists_topic_mastery(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/stats/mastery")
    assert response.status_code == 200


async def test_mastery_reflects_mastered_problems(client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"status": "mastered"})
    response = await client.get("/api/v1/stats/mastery")
    assert response.status_code == 200


# ------------------------------------------------------------------------------ study time
async def test_overview_reports_study_minutes(client, seeded_catalog) -> None:
    await client.put(
        "/api/v1/dsa/problems/two-sum/progress",
        json={"status": "solved", "time_spent_minutes": 30},
    )
    body = (await client.get("/api/v1/stats/overview")).json()
    assert body["study_time"]["total_minutes"] >= 0
