"""Proveedor Anthropic Claude. Messages API."""

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


class ClaudeProvider(AIProvider):
    name = "claude"
    is_available: bool

    def __init__(self, api_key: str | None, model: str = "claude-3-5-haiku-latest"):
        self.api_key = api_key
        self.model = model
        self.is_available = bool(api_key)
        self._endpoint = "https://api.anthropic.com/v1/messages"
        self._version = "2023-06-01"

    async def generate(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_available:
            raise ProviderAuthError("CLAUDE_API_KEY no configurada")

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self._version,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"claude timeout: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"claude http error: {e}") from e

        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"claude auth error {resp.status_code}")
        if resp.status_code == 429:
            raise ProviderRateLimitError("claude rate limit 429")
        if resp.status_code == 529:
            raise ProviderRateLimitError("claude overloaded 529")
        if resp.status_code >= 500:
            raise ProviderError(f"claude server error {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"claude client error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            content = data["content"][0]["text"]
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise ProviderInvalidResponseError(f"claude respuesta inválida: {e}") from e

        if not content or not content.strip():
            raise ProviderInvalidResponseError("claude respuesta vacía")

        return content.strip()
