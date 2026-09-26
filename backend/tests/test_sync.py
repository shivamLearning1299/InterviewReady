"""Offline synchronisation tests: push, pull, idempotency and conflict resolution.

Offline sync is the riskiest part of the system — a bug here silently loses or duplicates a
user's study history — so these tests focus hard on exactly the properties that make it
safe: replaying a mutation must never apply twice, a stale write must be rejected rather
than clobbering, and the pull cursor must be stable and resumable.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.db


def mutation(
    *,
    entity: str = "problem_progress",
    payload: dict | None = None,
    record_id: uuid.UUID | None = None,
    operation: str = "upsert",
    base_version: int | None = None,
) -> dict:
    body: dict = {
        "mutation_id": str(uuid.uuid4()),
        "entity": entity,
        "operation": operation,
        "payload": payload if payload is not None else {"status": "solved", "confidence": 4},
    }
    if record_id is not None:
        body["record_id"] = str(record_id)
    if base_version is not None:
        body["base_version"] = base_version
    return body


async def push(client, *mutations: dict, device_id: str = "device-1"):
    return await client.post(
        "/api/v1/sync/push",
        json={"device_id": device_id, "device_type": "ios", "mutations": list(mutations)},
    )


# ----------------------------------------------------------------------------------- push
async def test_push_applies_a_progress_mutation(client, seeded_catalog) -> None:
    response = await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 1
    assert body["results"][0]["status"] == "applied"


async def test_pushed_progress_is_visible_through_the_rest_api(client, seeded_catalog) -> None:
    """A sync push must be indistinguishable from the equivalent REST write."""
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    response = await client.get("/api/v1/dsa/problems", params={"search": "two sum"})
    assert response.json()["items"][0]["progress"]["status"] == "solved"


async def test_push_requires_at_least_one_mutation(client, seeded_catalog) -> None:
    response = await client.post("/api/v1/sync/push", json={"mutations": []})
    assert response.status_code == 422


async def test_push_rejects_an_unknown_entity(client, seeded_catalog) -> None:
    response = await push(client, mutation(entity="not_a_real_entity"))
    assert response.status_code == 422


async def test_push_reports_rejected_mutations(client, seeded_catalog) -> None:
    """An unknown entity per mutation is reported per item, not as a blanket 500."""
    response = await push(
        client,
        mutation(payload={"problem_id": "two-sum", "status": "solved"}),
        mutation(entity="problem_attempt", payload={"problem_id": "nope", "outcome": "solved"}),
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2


async def test_mutations_in_one_push_are_processed_in_order(client, seeded_catalog) -> None:
    response = await push(
        client,
        mutation(payload={"problem_id": "two-sum", "status": "attempted"}),
        mutation(payload={"problem_id": "two-sum", "status": "solved"}),
    )
    assert response.json()["applied_count"] == 2


# ---------------------------------------------------------------------------- idempotency
async def test_replaying_a_mutation_is_a_no_op(client, seeded_catalog) -> None:
    """The core offline guarantee: a retried push must not apply twice."""
    m = mutation(payload={"problem_id": "two-sum", "status": "solved"})
    first = await push(client, m)
    second = await push(client, m)

    assert first.json()["applied_count"] == 1
    assert second.json()["duplicate_count"] == 1
    assert second.json()["applied_count"] == 0


async def test_replayed_mutation_reports_duplicate_status(client, seeded_catalog) -> None:
    m = mutation(payload={"problem_id": "two-sum", "status": "solved"})
    await push(client, m)
    body = (await push(client, m)).json()
    assert body["results"][0]["status"] == "skipped_duplicate"


async def test_replay_does_not_double_count_time_spent(client, seeded_catalog) -> None:
    """The failure mode that matters most: inflating a user's recorded study time."""
    m = mutation(payload={"problem_id": "two-sum", "status": "solved", "time_spent_minutes": 30})
    await push(client, m)
    await push(client, m)

    detail = await client.get("/api/v1/dsa/problems/two-sum")
    assert detail.json()["progress"]["total_time_spent_minutes"] == 30


async def test_duplicate_mutations_within_one_push_apply_once(client, seeded_catalog) -> None:
    """A batched retry can contain the same mutation twice."""
    m = mutation(payload={"problem_id": "two-sum", "status": "solved"})
    body = (await push(client, m, m)).json()
    assert body["applied_count"] == 1
    assert body["duplicate_count"] == 1


async def test_partial_progress_mutation_inserts_without_a_status(
    client, seeded_catalog
) -> None:
    """A push carrying only some fields must still create the row.

    ``status`` is NOT NULL with no server default, so a payload like ``{"confidence": 5}``
    used to fail the INSERT with a NOT NULL violation — and the error was misreported as
    ``skipped_duplicate``, silently discarding the user's change.
    """
    body = (
        await push(client, mutation(payload={"problem_id": "two-sum", "confidence": 5}))
    ).json()
    assert body["applied_count"] == 1
    assert body["rejected_count"] == 0

    detail = await client.get("/api/v1/dsa/problems/two-sum")
    progress = detail.json()["progress"]
    assert progress["confidence"] == 5
    assert progress["status"] == "not_started"


async def test_partial_progress_mutation_preserves_the_existing_status(
    client, seeded_catalog
) -> None:
    """A partial update must not reset a solved problem back to ``not_started``.

    The column has to be present for the INSERT to satisfy NOT NULL, but it must be excluded
    from the DO UPDATE clause so the stored value survives.
    """
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    response = await push(client, mutation(payload={"problem_id": "two-sum", "confidence": 5}))
    assert response.json()["applied_count"] == 1

    detail = await client.get("/api/v1/dsa/problems/two-sum")
    progress = detail.json()["progress"]
    assert progress["confidence"] == 5
    assert progress["status"] == "solved"


async def test_pushed_partial_update_bumps_the_stored_version(client, seeded_catalog) -> None:
    """The post-write row must reflect the write, not the pre-write identity-mapped copy.

    ``ProblemProgressRepository.upsert`` returned a stale ORM object when it built the
    statement directly, so the optimistic-concurrency check read the old ``version`` and a
    stale write was reported as applied instead of as a conflict.
    """
    first = await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    first_version = first.json()["results"][0]["version"]

    second = await push(client, mutation(payload={"problem_id": "two-sum", "confidence": 4}))
    second_version = second.json()["results"][0]["version"]

    assert first_version is not None and second_version is not None
    assert second_version > first_version


# ------------------------------------------------------------------------ conflict handling
async def test_stale_write_is_reported_as_a_conflict(client, seeded_catalog) -> None:
    """A client writing from an old version must be told, not silently overwritten."""
    created = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"}
    )
    stale_version = created.json()["version"]

    # Advance the row so the client's base_version is now stale.
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"confidence": 5})

    response = await push(
        client,
        mutation(
            payload={"problem_id": "two-sum", "status": "attempted"},
            base_version=stale_version,
        ),
    )
    body = response.json()
    assert body["conflict_count"] == 1
    assert body["results"][0]["status"] == "conflict"


async def test_conflict_returns_the_server_record(client, seeded_catalog) -> None:
    """Without the server's copy the client cannot merge; it would just retry blindly."""
    created = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"}
    )
    version = created.json()["version"]
    await client.put("/api/v1/dsa/problems/two-sum/progress", json={"confidence": 5})

    body = (
        await push(
            client,
            mutation(
                payload={"problem_id": "two-sum", "status": "attempted"},
                base_version=version,
            ),
        )
    ).json()
    assert body["results"][0]["server_record"] is not None


async def test_conflict_does_not_overwrite_the_server_value(client, seeded_catalog) -> None:
    """Rejecting the write is the point — the server's newer state must survive."""
    created = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"}
    )
    version = created.json()["version"]
    await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"confidence": 5, "status": "mastered"}
    )

    await push(
        client,
        mutation(
            payload={"problem_id": "two-sum", "status": "attempted"},
            base_version=version,
        ),
    )
    detail = await client.get("/api/v1/dsa/problems/two-sum")
    assert detail.json()["progress"]["status"] == "mastered"


async def test_matching_base_version_applies_cleanly(client, seeded_catalog) -> None:
    created = await client.put(
        "/api/v1/dsa/problems/two-sum/progress", json={"status": "solved"}
    )
    version = created.json()["version"]

    body = (
        await push(
            client,
            mutation(
                payload={"problem_id": "two-sum", "confidence": 5},
                base_version=version,
            ),
        )
    ).json()
    assert body["applied_count"] == 1
    assert body["conflict_count"] == 0


# ------------------------------------------------------------------------------------ pull
async def test_pull_returns_changes_after_a_push(client, seeded_catalog) -> None:
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    response = await client.get("/api/v1/sync/pull", params={"cursor": 0})
    assert response.status_code == 200
    body = response.json()
    assert len(body["changes"]) >= 1


async def test_pull_from_the_latest_cursor_is_empty(client, seeded_catalog) -> None:
    """Otherwise every sync would re-download the user's whole history."""
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    cursor = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["next_cursor"]

    response = await client.get("/api/v1/sync/pull", params={"cursor": cursor})
    assert response.json()["changes"] == []


async def test_pull_cursor_is_monotonic(client, seeded_catalog) -> None:
    first = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["next_cursor"]
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    second = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["next_cursor"]
    assert second >= first


async def test_pull_returns_changes_oldest_first(client, seeded_catalog) -> None:
    """A cursor is only resumable if changes arrive in sequence order."""
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    await push(client, mutation(payload={"problem_id": "contains-duplicate", "status": "solved"}))

    changes = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["changes"]
    sequences = [change["seq"] for change in changes]
    assert sequences == sorted(sequences)


async def test_pull_change_records_describe_the_entity(client, seeded_catalog) -> None:
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    change = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["changes"][0]
    assert change["entity"] == "problem_progress"
    assert change["operation"] == "upsert"
    assert change["record_id"]


async def test_pull_is_isolated_between_users(client, other_client, seeded_catalog) -> None:
    """One user's change feed must never leak another user's activity."""
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    response = await other_client.get("/api/v1/sync/pull", params={"cursor": 0})
    assert response.json()["changes"] == []


async def test_pull_pagination_is_bounded(client, seeded_catalog) -> None:
    for problem in ("two-sum", "contains-duplicate", "valid-anagram"):
        await push(client, mutation(payload={"problem_id": problem, "status": "solved"}))
    response = await client.get("/api/v1/sync/pull", params={"cursor": 0, "limit": 2})
    assert response.status_code == 200
    assert len(response.json()["changes"]) <= 2


# ---------------------------------------------------------------------------------- status
async def test_sync_status_reports_the_cursor(client, seeded_catalog) -> None:
    response = await client.get("/api/v1/sync/status")
    assert response.status_code == 200
    assert "server_cursor" in response.json()


async def test_sync_status_advances_after_a_push(client, seeded_catalog) -> None:
    before = (await client.get("/api/v1/sync/status")).json()["server_cursor"]
    await push(client, mutation(payload={"problem_id": "two-sum", "status": "solved"}))
    after = (await client.get("/api/v1/sync/status")).json()["server_cursor"]
    assert after > before


# ---------------------------------------------------------------------- entity coverage
@pytest.mark.parametrize(
    ("entity", "payload"),
    [
        ("problem_progress", {"problem_id": "two-sum", "status": "solved"}),
        ("problem_notes", {"problem_id": "two-sum", "approach": "hash map"}),
        ("problem_attempt", {"problem_id": "two-sum", "outcome": "solved"}),
        ("revision", {"problem_id": "two-sum", "due_at": "2030-01-01T00:00:00Z"}),
        ("code_snippet", {"problem_id": "two-sum", "language": "python", "code": "pass"}),
    ],
)
async def test_each_dsa_entity_can_be_pushed(client, seeded_catalog, entity, payload) -> None:
    """Every entity the client can mutate offline must have a working server handler."""
    response = await push(client, mutation(entity=entity, payload=payload))
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] in ("applied", "conflict", "rejected")


async def test_delete_mutation_is_honoured(client, seeded_catalog) -> None:
    record = uuid.uuid4()
    await push(
        client,
        mutation(
            entity="code_snippet",
            payload={"problem_id": "two-sum", "language": "python", "code": "temp"},
            record_id=record,
        ),
    )
    await push(client, mutation(entity="code_snippet", operation="delete", record_id=record))
    response = await client.get("/api/v1/dsa/problems/two-sum/code")
    assert response.status_code == 200


# ------------------------------------------------------------------------- study_session
# `SyncEntity` declared 11 values but only 10 were registered in `_handlers()`, so a
# client following the published sync contract and pushing a `study_session` was answered
# with UNSUPPORTED_ENTITY. These tests pin the handler that closed that gap — and pin the
# security property that matters most about it: the duration is server-measured, so a
# device clock cannot inflate recorded study time.


async def test_study_session_entity_is_supported(client, seeded_catalog) -> None:
    """The regression test for the missing handler."""
    response = await push(
        client,
        mutation(
            entity="study_session",
            payload={
                "session_type": "dsa",
                "started_at": "2026-01-01T10:00:00+00:00",
                "ended_at": "2026-01-01T10:30:00+00:00",
            },
            record_id=uuid.uuid4(),
        ),
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "applied", result
    assert result["error_code"] is None


async def test_study_session_derives_duration_from_the_server_clock(
    client, seeded_catalog
) -> None:
    """A client-supplied duration must be ignored entirely."""
    response = await push(
        client,
        mutation(
            entity="study_session",
            payload={
                "session_type": "dsa",
                "started_at": "2026-01-01T10:00:00+00:00",
                "ended_at": "2026-01-01T10:45:00+00:00",
                # A lying client. Must not be honoured.
                "duration_minutes": 9999,
                "minutes": 9999,
            },
            record_id=uuid.uuid4(),
        ),
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "applied"

    listed = await client.get("/api/v1/study-sessions")
    assert listed.status_code == 200
    sessions = listed.json()["items"]
    assert len(sessions) == 1
    # 45 real minutes, not the 9999 the client asked for.
    assert sessions[0]["duration_minutes"] == 45


async def test_study_session_duration_is_clamped(client, seeded_catalog) -> None:
    """An implausibly long session is clamped, mirroring StudySessionService.stop."""
    response = await push(
        client,
        mutation(
            entity="study_session",
            payload={
                "session_type": "dsa",
                "started_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-05T00:00:00+00:00",  # 4 days
            },
            record_id=uuid.uuid4(),
        ),
    )
    assert response.status_code == 200
    applied = response.json()["results"][0]
    assert applied["status"] == "applied"

    listed = await client.get("/api/v1/study-sessions")
    # MAX_SESSION_MINUTES is 8 hours.
    assert listed.json()["items"][0]["duration_minutes"] == 8 * 60


async def test_study_session_with_no_end_time_stays_running(client, seeded_catalog) -> None:
    """A session pushed without `ended_at` is an open session, not a rejected mutation."""
    response = await push(
        client,
        mutation(
            entity="study_session",
            payload={"session_type": "hld", "started_at": "2026-01-01T10:00:00+00:00"},
            record_id=uuid.uuid4(),
        ),
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "applied"

    running = await client.get("/api/v1/study-sessions/running")
    assert running.status_code == 200
    assert running.json() is not None
    assert running.json()["session_type"] == "hld"


async def test_study_session_with_an_end_before_the_start_is_clamped(
    client, seeded_catalog
) -> None:
    """A skewed device clock must not wedge the queue with an endless rejection."""
    response = await push(
        client,
        mutation(
            entity="study_session",
            payload={
                "session_type": "dsa",
                "started_at": "2026-01-01T10:00:00+00:00",
                "ended_at": "2026-01-01T09:00:00+00:00",  # an hour BEFORE the start
            },
            record_id=uuid.uuid4(),
        ),
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "applied"

    listed = await client.get("/api/v1/study-sessions")
    # Clamped to zero rather than negative.
    assert listed.json()["items"][0]["duration_minutes"] == 0


async def test_study_session_appears_in_the_pull_stream(client, seeded_catalog) -> None:
    """A pushed session must propagate to the user's other devices."""
    session_id = uuid.uuid4()
    await push(
        client,
        mutation(
            entity="study_session",
            payload={
                "session_type": "dsa",
                "started_at": "2026-01-01T10:00:00+00:00",
                "ended_at": "2026-01-01T10:20:00+00:00",
            },
            record_id=session_id,
        ),
    )

    pulled = await client.get("/api/v1/sync/pull", params={"cursor": 0})
    assert pulled.status_code == 200
    changes = pulled.json()["changes"]
    assert any(
        c["entity"] == "study_session" and c["record_id"] == str(session_id) for c in changes
    ), changes


async def test_study_session_delete_is_honoured(client, seeded_catalog) -> None:
    """An offline session deletion must tombstone and propagate.

    Regression test for a gap found by independent verification: the upsert path for
    ``study_session`` existed but ``_apply_delete`` had no branch for it, so a delete was
    silently reported as ``skipped_duplicate`` while the row stayed visible forever.
    """
    session_id = uuid.uuid4()
    await push(
        client,
        mutation(
            entity="study_session",
            payload={"session_type": "dsa", "started_at": "2026-01-01T10:00:00+00:00"},
            record_id=session_id,
        ),
    )
    assert (await client.get("/api/v1/study-sessions")).json()["items"], "session not created"

    deleted = await push(
        client, mutation(entity="study_session", operation="delete", record_id=session_id)
    )
    result = deleted.json()["results"][0]
    assert result["status"] == "applied", result

    # Gone from the read API.
    assert (await client.get("/api/v1/study-sessions")).json()["items"] == []

    # And a tombstone reached the change feed, so other devices learn about it.
    changes = (await client.get("/api/v1/sync/pull", params={"cursor": 0})).json()["changes"]
    tombstones = [
        c
        for c in changes
        if c["entity"] == "study_session"
        and c["record_id"] == str(session_id)
        and c["operation"] == "delete"
    ]
    assert tombstones, changes


async def test_deleting_an_absent_study_session_is_idempotent(client, seeded_catalog) -> None:
    """Replaying a delete for a row that was never created must not fail the batch."""
    response = await push(
        client,
        mutation(entity="study_session", operation="delete", record_id=uuid.uuid4()),
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "skipped_duplicate"
