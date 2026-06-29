"""Registry de proveedores. Construye instancias desde config + env."""

from __future__ import annotations

import os
from typing import Mapping

from .base import AIProvider
from .claude_provider import ClaudeProvider
from .gemini_provider import GeminiProvider
from .groq_provider import GroqProvider
from .local_template import LocalTemplateProvider
from .mistral_provider import MistralProvider
from .openai_provider import OpenAIProvider
from .together_provider import TogetherProvider


def build_providers(config: Mapping, env: Mapping | None = None) -> dict[str, AIProvider]:
    providers_cfg = config.get("providers", {})
    e = env if env is not None else os.environ
    providers: dict[str, AIProvider] = {
        "openai": OpenAIProvider(
            api_key=e.get("OPENAI_API_KEY"),
            model=providers_cfg.get("openai", {}).get("model", "gpt-4o-mini"),
        ),
        "groq": GroqProvider(
            api_key=e.get("GROQ_API_KEY"),
            model=providers_cfg.get("groq", {}).get("model", "llama-3.3-70b-versatile"),
        ),
        "together": TogetherProvider(
            api_key=e.get("TOGETHER_API_KEY"),
            model=providers_cfg.get("together", {}).get(
                "model", "meta-llama/Llama-3.3-70B-Instruct-Turbo"
            ),
        ),
        "mistral": MistralProvider(
            api_key=e.get("MISTRAL_API_KEY"),
            model=providers_cfg.get("mistral", {}).get("model", "mistral-small-latest"),
        ),
        "gemini": GeminiProvider(
            api_key=e.get("GEMINI_API_KEY"),
            model=providers_cfg.get("gemini", {}).get("model", "gemini-2.0-flash"),
        ),
        "claude": ClaudeProvider(
            api_key=e.get("CLAUDE_API_KEY"),
            model=providers_cfg.get("claude", {}).get("model", "claude-3-5-haiku-latest"),
        ),
        "local_template": LocalTemplateProvider(),
    }
    return providers
