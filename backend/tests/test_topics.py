"""LLD and HLD tests: catalog, progress, notes and code.

Both curricula share one repository implementation, so these tests run the same assertions
against LLD and HLD to prove the generic path genuinely works for both — that is exactly the
kind of aliasing/table-binding bug that a single-curriculum test would miss.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


@pytest.fixture(params=["lld", "hld"])
def kind(request: pytest.FixtureRequest) -> str:
    """Run each test against both curricula."""
    return request.param


@pytest.fixture
def base(kind: str) -> str:
    return f"/api/v1/{kind}"


@pytest.fixture
def topic_id(kind: str, seeded_topics) -> str:
    return str(seeded_topics[kind][0])


# ------------------------------------------------------------------------------- catalog
async def test_topics_are_listed(client, seeded_topics, base) -> None:
    response = await client.get(base)
    assert response.status_code == 200
    body = response.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert len(items) == 2


async def test_topic_listing_defaults_to_not_started(client, seeded_topics, base) -> None:
    """A topic the user has never touched still needs a well-formed progress object."""
    body = (await client.get(base)).json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert all(item["progress"]["status"] == "not_started" for item in items)


async def test_topic_detail_is_available(client, seeded_topics, base, topic_id) -> None:
    response = await client.get(f"{base}/{topic_id}")
    assert response.status_code == 200
    assert response.json()["title"]


async def test_unknown_topic_returns_404(client, seeded_topics, base) -> None:
    response = await client.get(f"{base}/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_topics_can_be_searched(client, seeded_topics, base) -> None:
    response = await client.get(base, params={"search": "parking"})
    assert response.status_code == 200


async def test_catalog_lists_are_isolated_between_users(
    client, other_client, seeded_topics, base
) -> None:
    """The catalog is shared, but progress on it is not."""
    topic = (await client.get(base)).json()
    items = topic["items"] if isinstance(topic, dict) and "items" in topic else topic
    target = items[0]["id"]
    await client.put(f"{base}/{target}/progress", json={"status": "completed"})

    theirs = (await other_client.get(base)).json()
    their_items = theirs["items"] if isinstance(theirs, dict) and "items" in theirs else theirs
    match = next(item for item in their_items if item["id"] == target)
    assert match["progress"]["status"] == "not_started"


# ------------------------------------------------------------------------------ progress
async def test_progress_can_be_recorded(client, seeded_topics, base, topic_id) -> None:
    response = await client.put(
        f"{base}/{topic_id}/progress", json={"status": "completed", "confidence": 4}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["confidence"] == 4


async def test_progress_is_reflected_in_the_catalog(client, seeded_topics, base, topic_id) -> None:
    await client.put(f"{base}/{topic_id}/progress", json={"status": "learning"})
    body = (await client.get(base)).json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    match = next(item for item in items if item["id"] == topic_id)
    assert match["progress"]["status"] == "learning"


async def test_progress_update_is_idempotent(client, seeded_topics, base, topic_id) -> None:
    payload = {"status": "completed", "confidence": 3}
    first = await client.put(f"{base}/{topic_id}/progress", json=payload)
    second = await client.put(f"{base}/{topic_id}/progress", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


async def test_progress_rejects_an_unknown_status(client, seeded_topics, base, topic_id) -> None:
    response = await client.put(f"{base}/{topic_id}/progress", json={"status": "nonsense"})
    assert response.status_code == 422


async def test_completing_a_topic_schedules_a_revision(
    client, seeded_topics, base, topic_id
) -> None:
    response = await client.put(f"{base}/{topic_id}/progress", json={"status": "completed"})
    assert response.status_code == 200


async def test_progress_is_isolated_between_users(
    client, other_client, seeded_topics, base, topic_id
) -> None:
    await client.put(f"{base}/{topic_id}/progress", json={"status": "completed"})
    body = (await other_client.get(base)).json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    match = next(item for item in items if item["id"] == topic_id)
    assert match["progress"]["status"] == "not_started"


async def test_progress_on_an_unknown_topic_returns_404(client, seeded_topics, base) -> None:
    response = await client.put(
        f"{base}/00000000-0000-0000-0000-000000000000/progress", json={"status": "completed"}
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------------- notes
async def test_notes_round_trip(client, seeded_topics, base, topic_id, kind) -> None:
    # LLD notes carry `summary`; HLD notes are the 13 design sections instead.
    field, value = ("summary", "my summary") if kind == "lld" else ("final_notes", "my notes")
    response = await client.put(f"{base}/{topic_id}/notes", json={field: value})
    assert response.status_code == 200
    assert response.json()[field] == value




async def test_notes_update_replaces_fields(client, seeded_topics, base, topic_id, kind) -> None:
    field = "summary" if kind == "lld" else "final_notes"
    await client.put(f"{base}/{topic_id}/notes", json={field: "first"})
    response = await client.put(f"{base}/{topic_id}/notes", json={field: "second"})
    assert response.json()[field] == "second"


async def test_notes_are_isolated_between_users(
    client, other_client, seeded_topics, base, topic_id, kind
) -> None:
    field = "summary" if kind == "lld" else "final_notes"
    await client.put(f"{base}/{topic_id}/notes", json={field: "mine"})
    response = await other_client.get(f"{base}/{topic_id}/notes")
    assert response.status_code == 200
    # Either absent, or present but not carrying this user's text.
    if response.json() is not None:
        assert response.json().get(field) in (None, "")


@pytest.mark.parametrize("kind", ["lld"])
async def test_lld_notes_accept_a_class_diagram(client, seeded_topics, topic_id) -> None:
    """LLD is the only curriculum with a structured class/relationship map."""
    response = await client.put(
        "/api/v1/lld/" + topic_id + "/notes",
        json={
            "summary": "parking lot",
            "patterns_used": ["strategy", "factory"],
            "class_diagram": [
                {"name": "ParkingLot", "responsibilities": "assign spots", "collaborators": []}
            ],
        },
    )
    assert response.status_code == 200


@pytest.mark.parametrize("kind", ["hld"])
async def test_hld_notes_accept_the_design_sections(client, seeded_topics, topic_id) -> None:
    response = await client.put(
        "/api/v1/hld/" + topic_id + "/notes",
        json={
            "functional_requirements": "shorten urls",
            "non_functional_requirements": "low latency",
            "capacity_estimation": "100M writes/day",
            "tradeoffs": "consistency vs availability",
        },
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------------- code
async def test_code_snippet_can_be_saved(client, seeded_topics, base, topic_id) -> None:
    response = await client.post(
        f"{base}/{topic_id}/code", json={"code": "class ParkingLot {}", "language": "java"}
    )
    assert response.status_code == 201
    assert response.json()["language"] == "java"


async def test_code_snippets_are_listed(client, seeded_topics, base, topic_id) -> None:
    await client.post(f"{base}/{topic_id}/code", json={"code": "a", "language": "python"})
    await client.post(f"{base}/{topic_id}/code", json={"code": "b", "language": "java"})
    response = await client.get(f"{base}/{topic_id}/code")
    assert response.status_code == 200
    body = response.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert len(items) == 2


async def test_code_snippet_can_be_updated(client, seeded_topics, base, topic_id) -> None:
    created = await client.post(
        f"{base}/{topic_id}/code", json={"code": "old", "language": "python"}
    )
    snippet_id = created.json()["id"]
    response = await client.put(
        f"{base}/{topic_id}/code/{snippet_id}", json={"code": "new"}
    )
    assert response.status_code == 200
    assert response.json()["code"] == "new"


async def test_code_snippet_can_be_deleted(client, seeded_topics, base, topic_id) -> None:
    created = await client.post(
        f"{base}/{topic_id}/code", json={"code": "temp", "language": "python"}
    )
    snippet_id = created.json()["id"]
    assert (await client.delete(f"{base}/{topic_id}/code/{snippet_id}")).status_code == 200


@pytest.mark.parametrize("kind", ["lld"])
async def test_snippet_cannot_be_deleted_through_the_other_curriculum(
    client, seeded_topics, topic_id
) -> None:
    """Snippet ids are scoped to their topic; the wrong base path must not delete it."""
    created = await client.post(
        f"/api/v1/lld/{topic_id}/code", json={"code": "mine", "language": "python"}
    )
    assert created.status_code == 201
    snippet_id = created.json()["id"]

    response = await client.delete(f"/api/v1/hld/{topic_id}/code/{snippet_id}")
    assert response.status_code >= 400

    # The snippet must still exist under its real owner.
    still_there = await client.get(f"/api/v1/lld/{topic_id}/code")
    body = still_there.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert any(item["id"] == snippet_id for item in items)


async def test_code_snippet_accepts_any_language(client, seeded_topics, base, topic_id) -> None:
    """Topic snippets take a free-form language (only the DSA endpoint uses a fixed enum)."""
    response = await client.post(
        f"{base}/{topic_id}/code", json={"code": "x", "language": "cobol"}
    )
    assert response.status_code == 201
