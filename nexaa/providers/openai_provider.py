"""Proveedor OpenAI. Chat completions API."""

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


class OpenAIProvider(AIProvider):
    name = "openai"
    is_available: bool

    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-4o-mini",
        *,
        base_url: str = "https://api.openai.com/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.is_available = bool(api_key)
        self._endpoint = f"{self.base_url}/chat/completions"

    async def generate(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ) -> str:
        if not self.is_available:
            raise ProviderAuthError("OPENAI_API_KEY no configurada")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"openai timeout: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"openai http error: {e}") from e

        if resp.status_code == 401 or resp.status_code == 403:
            raise ProviderAuthError(f"openai auth error {resp.status_code}")
        if resp.status_code == 429:
            raise ProviderRateLimitError("openai rate limit 429")
        if resp.status_code >= 500:
            raise ProviderError(f"openai server error {resp.status_code}")
        if resp.status_code >= 400:
            raise ProviderError(f"openai client error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderInvalidResponseError(f"openai respuesta inválida: {e}") from e

        if not content or not content.strip():
            raise ProviderInvalidResponseError("openai respuesta vacía")

        return content.strip()
