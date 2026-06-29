"""Interfaz común para todos los proveedores de IA."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """Error genérico de un proveedor. El router decide si hace fallback."""


class ProviderAuthError(ProviderError):
    """Credenciales inválidas o ausentes. NO cuenta para circuit breaker."""


class ProviderRateLimitError(ProviderError):
    """429 / cuota agotada. SÍ cuenta para circuit breaker."""


class ProviderTimeoutError(ProviderError):
    """Timeout. SÍ cuenta para circuit breaker."""


class ProviderInvalidResponseError(ProviderError):
    """Respuesta no parseable o vacía. SÍ cuenta para circuit breaker."""


@runtime_checkable
class AIProvider(Protocol):
    name: str
    is_available: bool

    async def generate(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ) -> str:
        ...
