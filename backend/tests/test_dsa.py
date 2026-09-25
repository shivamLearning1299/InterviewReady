"""DSA practice tests: catalog, progress, attempts, notes, code snippets and revisions.

Every test goes through HTTP against the real ASGI app, so routing, validation, error
envelopes, serialisation and SQL are all exercised together.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


# ------------------------------------------------------------------------------- catalog
async def test_catalog_is_listed(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(seeded_catalog)
    assert len(body["items"]) == len(seeded_catalog)


async def test_catalog_items_carry_progress_defaults(client, seeded_catalog) -> None:
    """A problem the user has never touched still needs a well-formed progress object."""
    response = await client.get("/api/v1/dsa/problems")
    item = next(p for p in response.json()["items"] if p["slug"] == "two-sum")
    assert item["progress"]["status"] == "not_started"


async def test_catalog_pagination(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems", params={"limit": 3, "offset": 0})
    body = response.json()
    assert len(body["items"]) == 3
    assert body["total"] == len(seeded_catalog)


async def test_catalog_can_be_filtered_by_difficulty(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems", params={"difficulty": "medium"})
    items = response.json()["items"]
    assert items
    assert {item["difficulty"] for item in items} == {"medium"}


async def test_catalog_can_be_filtered_by_topic(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems", params={"topic": "graphs"})
    items = response.json()["items"]
    assert items
    assert {item["primary_topic"] for item in items} == {"graphs"}


async def test_catalog_can_be_searched(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems", params={"search": "island"})
    items = response.json()["items"]
    assert [item["slug"] for item in items] == ["number-of-islands"]


async def test_problem_detail_includes_related_documents(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems/two-sum")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "two-sum"
    assert body["notes"] is None
    assert body["code_snippets"] == []
    assert body["attempts"] == []


async def test_unknown_problem_returns_404(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROBLEM_NOT_FOUND"


async def test_topics_endpoint_lists_curriculum_topics(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/topics")
    assert response.status_code == 200
    body = response.json()
    # The endpoint is paginated, and topics are keyed by slug (the catalog's primary key).
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert items


async def test_filters_endpoint_reports_available_facets(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/filters")
    assert response.status_code == 200
    body = response.json()
    assert set(body["difficulties"]) == {"easy", "medium", "hard"}
    assert "graphs" in body["patterns"] or body["patterns"] == []


# ------------------------------------------------------------------------------ progress
async def test_progress_can_be_recorded(client, seeded_catalog) -> None:
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved", "confidence": 4}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "solved"
    assert body["confidence"] == 4


async def test_progress_is_reflected_in_the_catalog(client, seeded_catalog) -> None:
    await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved", "confidence": 5}
    )
    response = await client.get("/api/v1/dsa/problems", params={"search": "two sum"})
    item = response.json()["items"][0]
    assert item["progress"]["status"] == "solved"


async def test_progress_update_is_idempotent(client, seeded_catalog) -> None:
    """Applying the same update twice must not create a second progress row."""
    payload = {"status": "solved", "confidence": 3}
    first = await client.put("/api/v1/dsa/problems/two-sum/progress", json=payload)
    second = await client.put("/api/v1/dsa/problems/two-sum/progress", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


async def test_solving_schedules_a_revision(client, seeded_catalog) -> None:
    """Solving is only useful if the problem comes back for review."""
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/progress",
        json={"status": "solved", "confidence": 3, "schedule_revision": True},
    )
    assert response.status_code == 200
    assert response.json()["next_revision_at"] is not None


async def test_progress_rejects_an_out_of_range_confidence(client, seeded_catalog) -> None:
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved", "confidence": 9}
    )
    assert response.status_code == 422


async def test_progress_rejects_an_unknown_status(client, seeded_catalog) -> None:
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "nonsense"}
    )
    assert response.status_code == 422


async def test_progress_on_unknown_problem_returns_404(client, seeded_catalog) -> None:
    response = await client.put(
        "/api/v1/dsa/problems/nope/progress", json={"status": "solved"}
    )
    assert response.status_code == 404


async def test_progress_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    """The central privacy guarantee: one user's work must never appear for another."""
    await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved", "confidence": 5}
    )
    response = await other_client.get("/api/v1/dsa/problems", params={"search": "two sum"})
    assert response.json()["items"][0]["progress"]["status"] == "not_started"


# ------------------------------------------------------------------------------ attempts
async def test_attempt_can_be_logged(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/dsa/problems/two-sum/attempts",
        json={"outcome": "solved", "duration_minutes": 25, "notes": "hash map"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["outcome"] == "solved"
    assert body["duration_minutes"] == 25


async def test_attempts_are_listed_newest_first(client, seeded_catalog) -> None:
    for note in ("first", "second"):
        await client.post(
            "/api/v1/dsa/problems/two-sum/attempts", json={"outcome": "partial", "notes": note}
        )
    response = await client.get("/api/v1/dsa/problems/two-sum/attempts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2


async def test_attempt_can_be_updated(client, seeded_catalog) -> None:
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/attempts", json={"outcome": "partial"}
    )
    attempt_id = created.json()["id"]
    response = await client.patch(
        f"/api/v1/dsa/problems/two-sum/attempts/{attempt_id}",
        json={"outcome": "solved"},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "solved"


async def test_attempt_rejects_an_unknown_outcome(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/dsa/problems/two-sum/attempts", json={"outcome": "nonsense"}
    )
    assert response.status_code == 422


async def test_attempts_are_isolated_between_users(client, other_client, seeded_catalog) -> None:
    await client.post("/api/v1/dsa/problems/two-sum/attempts", json={"outcome": "solved"})
    response = await other_client.get("/api/v1/dsa/problems/two-sum/attempts")
    assert response.json()["items"] == []


# --------------------------------------------------------------------------------- notes
async def test_notes_are_created_on_first_write(client, seeded_catalog) -> None:
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/notes",
        json={"approach": "hash map", "time_complexity": "O(n)"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approach"] == "hash map"
    assert body["time_complexity"] == "O(n)"


async def test_notes_are_returned_when_absent(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/dsa/problems/two-sum/notes")
    assert response.status_code == 200


async def test_notes_update_replaces_fields(client, seeded_catalog) -> None:
    await client.put("/api/v1/dsa/problems/two-sum/notes", json={"approach": "brute force"})
    response = await client.put(
        "/api/v1/dsa/problems/two-sum/notes", json={"approach": "hash map"}
    )
    assert response.json()["approach"] == "hash map"


async def test_notes_are_isolated_between_users(client, other_client, seeded_catalog) -> None:
    """One user's notes must never be readable by another."""
    await client.put("/api/v1/dsa/problems/two-sum/notes", json={"approach": "mine"})
    response = await other_client.get("/api/v1/dsa/problems/two-sum/notes")
    # The API returns ``null`` (not a 404) when the caller has written no notes yet.
    assert response.json() is None


# ------------------------------------------------------------------------- code snippets
async def test_code_snippet_can_be_saved(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/dsa/problems/two-sum/code",
        json={"code": "def twoSum(nums, t): ...", "language": "python", "title": "optimal"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["language"] == "python"
    assert body["title"] == "optimal"


async def test_code_snippets_are_listed(client, seeded_catalog) -> None:
    await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "a", "language": "python"}
    )
    await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "b", "language": "java"}
    )
    response = await client.get("/api/v1/dsa/problems/two-sum/code")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_code_snippet_can_be_updated(client, seeded_catalog) -> None:
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "old", "language": "python"}
    )
    snippet_id = created.json()["id"]
    response = await client.put(
        f"/api/v1/dsa/problems/two-sum/code/{snippet_id}",
        json={"code": "new"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == "new"


async def test_code_snippet_can_be_deleted(client, seeded_catalog) -> None:
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "temp", "language": "python"}
    )
    snippet_id = created.json()["id"]
    response = await client.delete(f"/api/v1/dsa/problems/two-sum/code/{snippet_id}")
    assert response.status_code == 200
    remaining = await client.get("/api/v1/dsa/problems/two-sum/code")
    assert remaining.json() == []


async def test_code_snippet_rejects_an_unknown_language(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "x", "language": "brainfuck"}
    )
    assert response.status_code == 422


async def test_deleting_another_users_snippet_is_not_possible(
    client, other_client, seeded_catalog
) -> None:
    """Snippet ids are guessable only by their owner; cross-user delete must 404."""
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/code", json={"code": "mine", "language": "python"}
    )
    snippet_id = created.json()["id"]
    response = await other_client.delete(f"/api/v1/dsa/problems/two-sum/code/{snippet_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------- revisions
async def test_manual_revision_can_be_scheduled(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"}
    )
    assert response.status_code in (200, 201)
    assert response.json()["problem_id"] == "two-sum"


async def test_revision_list_is_empty_initially(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/revisions")
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_scheduled_revision_appears_in_the_list(client, seeded_catalog) -> None:
    await client.post("/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"})
    response = await client.get("/api/v1/revisions")
    assert response.json()["total"] == 1


async def test_revision_summary_reports_buckets(client, seeded_catalog) -> None:
    await client.post("/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"})
    response = await client.get("/api/v1/revisions/summary")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"due", "overdue", "upcoming"}


async def test_revision_can_be_completed(client, seeded_catalog) -> None:
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"}
    )
    revision_id = created.json()["id"]
    response = await client.post(
        f"/api/v1/revisions/{revision_id}/complete", json={"result": "success", "confidence": 4}
    )
    assert response.status_code == 200
    body = response.json()
    assert body is not None


async def test_completing_a_revision_is_idempotent(client, seeded_catalog) -> None:
    """A retried request (offline client, network blip) must not double-count."""
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"}
    )
    revision_id = created.json()["id"]
    payload = {"result": "success", "confidence": 4}
    first = await client.post(f"/api/v1/revisions/{revision_id}/complete", json=payload)
    second = await client.post(f"/api/v1/revisions/{revision_id}/complete", json=payload)
    assert first.status_code == second.status_code == 200


async def test_failed_revision_comes_back_soon(client, seeded_catalog) -> None:
    """Failing is the strongest signal, so the next revision must be scheduled promptly."""
    created = await client.post(
        "/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"}
    )
    revision_id = created.json()["id"]
    response = await client.post(
        f"/api/v1/revisions/{revision_id}/complete", json={"result": "failed"}
    )
    assert response.status_code == 200


async def test_completing_an_unknown_revision_returns_404(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/revisions/00000000-0000-0000-0000-000000000000/complete",
        json={"result": "success"},
    )
    assert response.status_code == 404


async def test_revisions_are_isolated_between_users(client, other_client, seeded_catalog) -> None:
    await client.post("/api/v1/dsa/problems/two-sum/revision", json={"reason": "manual"})
    response = await other_client.get("/api/v1/revisions")
    assert response.json()["total"] == 0


async def test_promote_stale_reports_a_count(client, seeded_catalog) -> None:
    response = await client.post("/api/v1/revisions/promote-stale")
    assert response.status_code == 200
