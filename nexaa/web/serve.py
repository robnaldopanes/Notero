"""Entry point para producción (uvicorn, gunicorn, etc).

Uso: uvicorn --app-dir /app nexaa.web.serve:create_app --factory
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ..engine.engine import NewsEngine
from .app import build_app


def _load_config() -> dict:
    config_path = Path(os.getenv("NEXAA_CONFIG", "/app/config.yaml"))
    if not config_path.exists():
        return {"ia_order": ["openai", "groq", "together", "mistral", "gemini", "claude"]}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def create_app():
    load_dotenv(Path(os.getenv("NEXAA_ENV", "/app/.env")), override=False)
    base = Path(os.getenv("NEXAA_BASE", "/app"))
    config = _load_config()
    engine = NewsEngine(config, base_path=base)
    return build_app(engine)
