"""Proveedor Mistral AI. API OpenAI-compatible.

Free tier: signup en https://console.mistral.ai/ (sin tarjeta).
"""

from __future__ import annotations

from .openai_provider import OpenAIProvider


class MistralProvider(OpenAIProvider):
    name = "mistral"

    def __init__(self, api_key: str | None, model: str = "mistral-small-latest"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.mistral.ai/v1",
        )
