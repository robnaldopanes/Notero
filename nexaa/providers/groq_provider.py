"""Proveedor Groq. Usa la API OpenAI-compatible de Groq (free tier disponible).

Referencia: https://console.groq.com/ — signup con email, sin tarjeta.
Modelos típicos: llama-3.1-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768.
"""

from __future__ import annotations

from .openai_provider import OpenAIProvider


class GroqProvider(OpenAIProvider):
    name = "groq"

    def __init__(self, api_key: str | None, model: str = "llama-3.3-70b-versatile"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.groq.com/openai/v1",
        )
