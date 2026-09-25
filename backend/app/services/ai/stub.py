"""Deterministic offline AI provider.

Two jobs:

* **Tests.** The suite must not call a paid external API on every run, so
  ``AI_PROVIDER=stub`` yields a deterministic reply shaped like a real one.
* **Local development.** A developer with no API key can still exercise the tutor end to
  end, including conversation persistence and the full request/response contract.

It is clearly labelled: every response states that it came from the stub provider, so a
stub reply can never be mistaken for real tutoring advice.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.ai.provider import ChatMessage, ChatResult

_STUB_NOTICE = (
    "_(stub provider — set `AI_PROVIDER` and `AI_API_KEY` for real tutor responses)_"
)

#: Canned-but-plausible guidance keyed by the trailing phrase of the caller's action.
_ACTION_HINTS: dict[str, str] = {
    "hint": (
        "Here's a nudge rather than the answer.\n\n"
        "1. Restate the problem in one sentence — what exactly is being asked?\n"
        "2. Ask which pattern applies by looking at the *shape* of the input: "
        "sorted? contiguous subarray? repeated subproblems?\n"
        "3. Write the brute force first and time it. The expensive step is the "
        "operation you will need to eliminate."
    ),
    "explain": (
        "Think about it in three layers:\n\n"
        "**Invariant** — what must always be true as you move through the data?\n"
        "**State** — what is the minimum information you must carry forward?\n"
        "**Transition** — how does the state change on each step, and why is that O(1)?"
    ),
    "bug": (
        "Before changing anything, narrow it down:\n\n"
        "1. Which input first produces the wrong output? Write it down explicitly.\n"
        "2. Does it fail on an empty input, a single element, or a duplicate?\n"
        "3. Trace the loop by hand for that input and compare each intermediate value "
        "with what you expected."
    ),
    "complexity": (
        "Count the work per element, then multiply:\n\n"
        "* For each of the `n` elements, how many operations run?\n"
        "* Is any operation inside the loop secretly a loop of its own?\n"
        "* Which data structures give O(1) lookup, and what do they cost in space?"
    ),
    "default": (
        "Let's work through this together rather than jumping to code.\n\n"
        "Start by describing the pattern you think applies and *why*. "
        "I'll tell you whether the reasoning holds."
    ),
}


class StubProvider:
    """``AIProvider`` implementation that never makes a network call."""

    name = "stub"

    def __init__(self, *, model: str = "stub-model") -> None:
        self._model = model

    async def chat(
        self,
        *,
        messages: list[ChatMessage],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> ChatResult:
        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )

        hint = self._select_hint(system or "", last_user)
        digest = hashlib.blake2b(last_user.encode(), digest_size=4).hexdigest()

        content = (
            f"{hint}\n\n{_STUB_NOTICE}\n\n"
            f"<!-- deterministic stub reply id={digest} -->"
        )

        return ChatResult(
            content=content,
            provider=self.name,
            model=self._model,
            finish_reason="stop",
            usage={
                "input_tokens": sum(len(message.content.split()) for message in messages),
                "output_tokens": len(content.split()),
                "total_tokens": 0,
            },
        )

    @staticmethod
    def _select_hint(system: str, user_message: str) -> str:
        haystack = f"{system}\n{user_message}".lower()
        for keyword in ("hint", "explain", "bug", "complexity"):
            if keyword in haystack:
                return _ACTION_HINTS[keyword]
        return _ACTION_HINTS["default"]

    async def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self._model,
            "configured": True,
            "reachable": True,
            "note": "Stub provider: responses are canned and deterministic.",
        }

    async def aclose(self) -> None:
        return None
