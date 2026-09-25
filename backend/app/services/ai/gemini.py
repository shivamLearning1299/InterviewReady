"""Google Gemini provider (default).

Uses the REST ``generateContent`` endpoint over httpx rather than a vendor SDK, keeping the
dependency surface small and the request shape explicit.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.ai.provider import (
    AIProviderConfigurationError,
    ChatMessage,
    ChatResult,
)

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Transient conditions worth retrying rather than surfacing to the user.
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class GeminiProvider:
    """``AIProvider`` implementation backed by Google Gemini."""

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.0-flash",
        base_url: str = "",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise AIProviderConfigurationError(
                "AI_API_KEY is required when AI_PROVIDER=gemini."
            )
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                follow_redirects=False,
            )
        return self._client

    async def chat(
        self,
        *,
        messages: list[ChatMessage],
        system: str | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
    ) -> ChatResult:
        url = f"{self._base_url}/models/{self._model}:generateContent"

        contents: list[dict[str, Any]] = []
        for message in messages:
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._http().post(
                    url,
                    json=body,
                    # The key travels only in a header, so it never lands in a URL that
                    # could be captured by a proxy or an access log.
                    headers={
                        "x-goog-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning("Gemini request timed out", extra={"attempt": attempt})
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.6 * attempt)
                    continue
                raise AIProviderError("The AI provider timed out.") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("Gemini transport error", extra={"attempt": attempt})
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.6 * attempt)
                    continue
                raise AIProviderError("Could not reach the AI provider.") from exc

            if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "Gemini returned a retryable status",
                    extra={"status": response.status_code, "attempt": attempt},
                )
                await asyncio.sleep(0.6 * attempt)
                continue

            if response.status_code >= 400:
                # Log the provider's message but never the key or the full prompt.
                logger.error(
                    "Gemini returned an error",
                    extra={"status": response.status_code, "detail": response.text[:300]},
                )
                if response.status_code in {401, 403}:
                    raise AIProviderError("The AI provider rejected our credentials.")
                if response.status_code == 429:
                    raise AIProviderError("The AI provider is rate limiting us. Try again shortly.")
                raise AIProviderError("The AI provider returned an error.")

            return self._parse(response.json())

        raise AIProviderError("The AI provider could not be reached.") from last_error

    def _parse(self, payload: dict[str, Any]) -> ChatResult:
        candidates = payload.get("candidates") or []
        if not candidates:
            # A blocked prompt produces no candidates; surface it as a clear error rather
            # than an empty assistant message.
            feedback = payload.get("promptFeedback") or {}
            reason = feedback.get("blockReason") or "no candidates returned"
            raise AIProviderError(f"The AI provider declined to answer ({reason}).")

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()

        if not text:
            raise AIProviderError("The AI provider returned an empty response.")

        usage_metadata = payload.get("usageMetadata") or {}
        return ChatResult(
            content=text,
            provider=self.name,
            model=self._model,
            finish_reason=candidate.get("finishReason"),
            usage={
                "input_tokens": usage_metadata.get("promptTokenCount"),
                "output_tokens": usage_metadata.get("candidatesTokenCount"),
                "total_tokens": usage_metadata.get("totalTokenCount"),
            },
        )

    async def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self._model,
            "configured": bool(self._api_key),
            "reachable": None,  # an active probe would cost quota; /health/ready stays cheap
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
