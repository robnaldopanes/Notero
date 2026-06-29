"""Proveedor Google Gemini. generateContent API."""

from __future__ import annotations

import httpx

from .base import (
    AIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


class GeminiProvider(AIProvider):
    name = "gemini"
    is_available: bool

    def __init__(self, api_key: str | None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.is_available = bool(api_key)
        self._endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        )

    async def generate(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_available:
            raise ProviderAuthError("GEMINI_API_KEY no configurada")

        params = {"key": self.api_key}
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._endpoint, params=params, json=payload)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"gemini timeout: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini http error: {e}") from e

        if resp.status_code in (400, 403) and "API key" in resp.text:
            raise ProviderAuthError("gemini api key inválida")
        if resp.status_code == 429:
            raise ProviderRateLimitError("gemini rate limit 429")
        if resp.status_code >= 500:
            raise ProviderError(f"gemini server error {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"gemini client error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ProviderInvalidResponseError(f"gemini respuesta inválida: {e}") from e

        if not content or not content.strip():
            raise ProviderInvalidResponseError("gemini respuesta vacía")

        return content.strip()
