"""Proveedor Together AI. API OpenAI-compatible.

Free: $5 USD de credito al registrarse en https://api.together.xyz/ (sin tarjeta).
"""

from __future__ import annotations

from .openai_provider import OpenAIProvider


class TogetherProvider(OpenAIProvider):
    name = "together"

    def __init__(
        self,
        api_key: str | None,
        model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.together.xyz/v1",
        )
