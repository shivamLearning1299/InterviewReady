"""AI provider abstraction.

Routes and the tutor service depend only on the :class:`AIProvider` protocol, so swapping
Gemini for Groq, Cloudflare Workers AI, OpenAI or a local model is a configuration change
(``AI_PROVIDER``) rather than a code change.

API keys live exclusively here, on the server: a client never sees a provider credential
and never talks to a provider directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class ChatMessage:
    """One turn submitted to a provider."""

    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class ChatResult:
    """A provider's reply plus bookkeeping."""

    content: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False)


@runtime_checkable
class AIProvider(Protocol):
    """The contract every AI backend must satisfy."""

    name: str

    async def chat(
        self,
        *,
        messages: list[ChatMessage],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Send a conversation and return the assistant's reply."""
        ...

    async def health(self) -> dict[str, Any]:
        """Non-sensitive readiness information (never the key itself)."""
        ...

    async def aclose(self) -> None:
        """Release any underlying HTTP resources."""
        ...


class AIProviderConfigurationError(RuntimeError):
    """Raised when a provider is selected but not fully configured."""
