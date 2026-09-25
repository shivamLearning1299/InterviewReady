"""AI tutor tests: request validation, context grounding, rate limiting and conversations.

The provider is the deterministic stub, so these tests assert the *contract* — that context
is assembled from the user's own data, that limits are enforced, and that conversations
persist — without depending on any model's output.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db


async def test_actions_endpoint_describes_the_capabilities(client) -> None:
    response = await client.get("/api/v1/ai/actions")
    assert response.status_code == 200
    body = response.json()
    assert body["actions"]
    assert body["context_types"]
    assert body["provider"]


async def test_chat_returns_a_reply(client) -> None:
    response = await client.post(
        "/api/v1/ai/chat", json={"message": "Explain two pointers."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["message"]["content"]
    assert body["conversation_id"]


async def test_chat_creates_a_conversation(client) -> None:
    response = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert response.json()["is_new_conversation"] is True


async def test_chat_reuses_an_existing_conversation(client) -> None:
    first = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    conversation_id = first.json()["conversation_id"]

    second = await client.post(
        "/api/v1/ai/chat", json={"message": "and again", "conversation_id": conversation_id}
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    assert second.json()["is_new_conversation"] is False


async def test_empty_message_is_rejected(client) -> None:
    """An empty prompt would waste a provider call and return nothing useful."""
    response = await client.post("/api/v1/ai/chat", json={"message": ""})
    assert response.status_code == 422


async def test_over_long_message_is_rejected(client) -> None:
    response = await client.post("/api/v1/ai/chat", json={"message": "x" * 9_000})
    assert response.status_code == 422


async def test_unknown_action_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "action": "do_my_homework"}
    )
    assert response.status_code == 422


async def test_unknown_context_type_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/ai/chat", json={"message": "hi", "context_type": "astrology"}
    )
    assert response.status_code == 422


async def test_missing_message_is_rejected(client) -> None:
    response = await client.post("/api/v1/ai/chat", json={})
    assert response.status_code == 422


async def test_dsa_context_is_grounded_in_the_problem(client, seeded_catalog) -> None:
    """The tutor must be given the problem it is asked about, not a generic prompt."""
    response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "Why does the two-pointer approach work here?",
            "context_type": "dsa",
            "context_id": None,
            "action": "give_hint",
        },
    )
    assert response.status_code == 200
    assert response.json()["context_used"] is not None


async def test_context_reports_what_was_used(client, seeded_catalog) -> None:
    response = await client.post(
        "/api/v1/ai/chat",
        json={"message": "hint", "context_type": "dsa", "action": "give_hint"},
    )
    assert response.status_code == 200
    assert "context_type" in response.json()["context_used"]


async def test_lld_context_is_supported(client, seeded_topics) -> None:
    response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "How should I structure this?",
            "context_type": "lld",
            "context_id": str(seeded_topics["lld"][0]),
        },
    )
    assert response.status_code == 200


async def test_hld_context_is_supported(client, seeded_topics) -> None:
    response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "What should I estimate first?",
            "context_type": "hld",
            "context_id": str(seeded_topics["hld"][0]),
        },
    )
    assert response.status_code == 200


async def test_selected_code_is_accepted(client) -> None:
    """A selected snippet is the main way a user asks about their own attempt."""
    response = await client.post(
        "/api/v1/ai/chat",
        json={
            "message": "Why is this slow?",
            "action": "explain_code",
            "selected_code": "for i in range(n):\n    for j in range(n): pass",
        },
    )
    assert response.status_code == 200


async def test_oversized_selected_code_is_rejected(client) -> None:
    """The limit bounds how much of a file is sent to the provider (and billed)."""
    response = await client.post(
        "/api/v1/ai/chat", json={"message": "review", "selected_code": "x" * 120_000}
    )
    assert response.status_code == 422


# ------------------------------------------------------------------------ conversations
async def test_conversations_are_listed(client) -> None:
    await client.post("/api/v1/ai/chat", json={"message": "hello"})
    response = await client.get("/api/v1/ai/conversations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1


async def test_conversation_can_be_fetched_with_messages(client) -> None:
    created = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    conversation_id = created.json()["conversation_id"]

    response = await client.get(f"/api/v1/ai/conversations/{conversation_id}")
    assert response.status_code == 200
    assert len(response.json()["messages"]) >= 2  # the user turn and the reply


async def test_unknown_conversation_returns_404(client) -> None:
    response = await client.get(
        "/api/v1/ai/conversations/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


async def test_conversation_can_be_deleted(client) -> None:
    created = await client.post("/api/v1/ai/chat", json={"message": "hello"})
    conversation_id = created.json()["conversation_id"]

    assert (await client.delete(f"/api/v1/ai/conversations/{conversation_id}")).status_code == 200
    assert (
        await client.get(f"/api/v1/ai/conversations/{conversation_id}")
    ).status_code == 404


async def test_conversations_are_isolated_between_users(client, other_client) -> None:
    """Chat history is as private as any other user data."""
    await client.post("/api/v1/ai/chat", json={"message": "my private question"})
    response = await other_client.get("/api/v1/ai/conversations")
    assert response.json()["total"] == 0


async def test_another_users_conversation_is_not_readable(client, other_client) -> None:
    created = await client.post("/api/v1/ai/chat", json={"message": "mine"})
    conversation_id = created.json()["conversation_id"]

    response = await other_client.get(f"/api/v1/ai/conversations/{conversation_id}")
    assert response.status_code == 404


async def test_another_users_conversation_cannot_be_deleted(client, other_client) -> None:
    created = await client.post("/api/v1/ai/chat", json={"message": "mine"})
    conversation_id = created.json()["conversation_id"]

    response = await other_client.delete(f"/api/v1/ai/conversations/{conversation_id}")
    assert response.status_code == 404


# ------------------------------------------------------------------------ rate limiting
async def test_rate_limit_is_eventually_enforced(client, settings) -> None:
    """The cap protects a shared provider quota, so it must actually bite.

    The configured limit is read from settings rather than hardcoded, so tuning the limit
    does not silently disable this test.
    """
    limit = settings.ai_rate_limit_per_hour
    statuses = []
    for _ in range(limit + 3):
        response = await client.post("/api/v1/ai/chat", json={"message": "hi"})
        statuses.append(response.status_code)
        if response.status_code == 429:
            break

    assert 429 in statuses, "the per-hour cap was never enforced"
    # Everything before the cap must have succeeded.
    assert all(status == 200 for status in statuses[:-1])


async def test_rate_limit_response_carries_retry_after(client, settings) -> None:
    limit = settings.ai_rate_limit_per_hour
    for _ in range(limit + 3):
        response = await client.post("/api/v1/ai/chat", json={"message": "hi"})
        if response.status_code == 429:
            assert response.json()["error"]["code"] == "RATE_LIMITED"
            break
    else:
        pytest.fail("the per-hour cap was never enforced")


async def test_rate_limit_is_per_user(client, other_client, settings) -> None:
    """One user exhausting their quota must not lock anybody else out."""
    for _ in range(settings.ai_rate_limit_per_hour + 3):
        if (await client.post("/api/v1/ai/chat", json={"message": "hi"})).status_code == 429:
            break

    response = await other_client.post("/api/v1/ai/chat", json={"message": "hello"})
    assert response.status_code == 200
