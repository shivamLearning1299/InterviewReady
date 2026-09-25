"""Provider factory.

The only place that knows which concrete providers exist. ``AI_PROVIDER`` selects one;
swapping it in the environment is the entire migration path to a different backend.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.ai.gemini import GeminiProvider
from app.services.ai.groq import GroqProvider
from app.services.ai.provider import AIProvider, AIProviderConfigurationError
from app.services.ai.stub import StubProvider

logger = get_logger(__name__)


def build_provider(settings: Settings) -> AIProvider:
    """Construct the configured provider.

    A misconfiguration raises :class:`AIProviderConfigurationError`, which the AI routes
    translate into a ``503 AI_NOT_CONFIGURED`` instead of a 500 — the rest of the API keeps
    working when the tutor is unavailable.
    """
    provider_name = (settings.ai_provider or "stub").lower()

    if provider_name == "gemini":
        return GeminiProvider(
            api_key=settings.ai_api_key,
            model=settings.ai_model or "gemini-2.0-flash",
            base_url=settings.ai_base_url,
            timeout=settings.ai_timeout_seconds,
        )

    if provider_name == "groq":
        return GroqProvider(
            api_key=settings.ai_api_key,
            model=settings.ai_model or "llama-3.3-70b-versatile",
            base_url=settings.ai_base_url,
            timeout=settings.ai_timeout_seconds,
        )

    if provider_name == "stub":
        logger.warning(
            "AI tutor is running with the stub provider — responses are canned, not real"
        )
        return StubProvider(model=settings.ai_model or "stub-model")

    raise AIProviderConfigurationError(
        f"Unknown AI_PROVIDER '{settings.ai_provider}'. "
        "Supported values: gemini, groq, stub."
    )


__all__ = ["build_provider"]
