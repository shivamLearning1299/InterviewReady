"""Groq provider.

Groq exposes an OpenAI-compatible ``/chat/completions`` endpoint, so this adapter also
serves as the template for OpenAI, Together, vLLM and most other compatible backends.
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

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class GroqProvider:
    """``AIProvider`` implementation backed by Groq's OpenAI-compatible API."""

    name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = "",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise AIProviderConfigurationError(
                "AI_API_KEY is required when AI_PROVIDER=groq."
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
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(message.as_dict() for message in messages)

        body: dict[str, Any] = {
            "model": self._model,
            "messages": payload_messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._http().post(
                    f"{self._base_url}/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.6 * attempt)
                    continue
                raise AIProviderError("The AI provider timed out.") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.6 * attempt)
                    continue
                raise AIProviderError("Could not reach the AI provider.") from exc

            if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(0.6 * attempt)
                continue

            if response.status_code >= 400:
                logger.error(
                    "Groq returned an error",
                    extra={"status": response.status_code, "detail": response.text[:300]},
                )
                if response.status_code in {401, 403}:
                    raise AIProviderError("The AI provider rejected our credentials.")
                if response.status_code == 429:
                    raise AIProviderError("The AI provider is rate limiting us.")
                raise AIProviderError("The AI provider returned an error.")

            return self._parse(response.json())

        raise AIProviderError("The AI provider could not be reached.") from last_error

    def _parse(self, payload: dict[str, Any]) -> ChatResult:
        choices = payload.get("choices") or []
        if not choices:
            raise AIProviderError("The AI provider returned no choices.")

        choice = choices[0]
        text = ((choice.get("message") or {}).get("content") or "").strip()
        if not text:
            raise AIProviderError("The AI provider returned an empty response.")

        usage = payload.get("usage") or {}
        return ChatResult(
            content=text,
            provider=self.name,
            model=payload.get("model") or self._model,
            finish_reason=choice.get("finish_reason"),
            usage={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )

    async def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self._model,
            "configured": bool(self._api_key),
            "reachable": None,
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
