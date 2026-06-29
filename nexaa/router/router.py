"""AI Router.

Estrategia:
1. Intenta el proveedor primario con timeout corto.
2. Si falla, lanza TODOS los demás en paralelo con timeout más largo.
3. Devuelve el primer resultado exitoso.
4. Si todos fallan, intenta el template local como último recurso.
5. Reporta cada intento al metrics logger.
6. Errores de auth NO cuentan para el circuit breaker (son problemas de config, no de servicio).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..providers.base import (
    AIProvider,
    ProviderAuthError,
    ProviderError,
)
from .circuit_breaker import CircuitBreaker
from .metrics import MetricsLogger, make_event


@dataclass
class RouteResult:
    text: str
    provider: str
    is_draft: bool
    attempts: int
    elapsed_ms: float


class AIRouter:
    def __init__(
        self,
        providers: Mapping[str, AIProvider],
        order: Sequence[str],
        breaker: CircuitBreaker,
        metrics: MetricsLogger,
        *,
        primary_timeout_s: float = 8.0,
        fallback_timeout_s: float = 12.0,
        global_budget_s: float = 30.0,
        max_retries: int = 2,
        fallback_enabled: bool = True,
    ):
        self.providers = providers
        self.order = list(order)
        self.breaker = breaker
        self.metrics = metrics
        self.primary_timeout_s = primary_timeout_s
        self.fallback_timeout_s = fallback_timeout_s
        self.global_budget_s = global_budget_s
        self.max_retries = max_retries
        self.fallback_enabled = fallback_enabled

    async def generate(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1400,
    ) -> RouteResult | None:
        t0 = time.monotonic()
        deadline = t0 + self.global_budget_s

        def budget_left() -> float:
            return max(0.0, deadline - time.monotonic())

        primary = self.order[0]
        fallbacks = self.order[1:]

        result = await self._try_with_retries(
            primary, system, user,
            timeout=self.primary_timeout_s, budget_left=budget_left,
            temperature=temperature, max_tokens=max_tokens,
        )
        if result is not None:
            return self._wrap(result, t0, is_draft=False)

        if not self.fallback_enabled or not fallbacks:
            return await self._try_local_template(system, user, t0, budget_left)

        remaining = [p for p in fallbacks if self.breaker.allow(p)]
        if not remaining:
            return await self._try_local_template(system, user, t0, budget_left)

        tasks = [
            self._try_with_retries(
                p,
                system,
                user,
                timeout=self.fallback_timeout_s,
                budget_left=budget_left,
                temperature=temperature, max_tokens=max_tokens,
            )
            for p in remaining
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for r in results:
            if r is not None:
                return self._wrap(r, t0, is_draft=False)

        return await self._try_local_template(system, user, t0, budget_left)

    async def _try_with_retries(
        self,
        provider_name: str,
        system: str,
        user: str,
        *,
        timeout: float,
        budget_left,
        temperature: float = 0.2,
        max_tokens: int = 1400,
    ) -> tuple[str, str, int] | None:
        provider = self.providers.get(provider_name)
        if provider is None or not provider.is_available:
            self.metrics.log(
                make_event(
                    "skip",
                    provider_name,
                    success=False,
                    error="no disponible o sin api key",
                )
            )
            return None

        if not self.breaker.allow(provider_name):
            self.metrics.log(
                make_event("circuit_open", provider_name, success=False, error="circuit open")
            )
            return None

        attempts = 0
        for attempt in range(1, self.max_retries + 1):
            attempts = attempt
            left = budget_left()
            if left <= 0:
                self.metrics.log(
                    make_event("budget_exhausted", provider_name, success=False, attempt=attempt)
                )
                return None

            effective_timeout = min(timeout, left)
            ts = time.monotonic()
            try:
                text = await asyncio.wait_for(
                    provider.generate(system, user, max_tokens=max_tokens, temperature=temperature),
                    timeout=effective_timeout,
                )
                latency = (time.monotonic() - ts) * 1000
                self.breaker.record_success(provider_name)
                self.metrics.log(
                    make_event(
                        "generate_ok",
                        provider_name,
                        success=True,
                        latency_ms=latency,
                        attempt=attempt,
                    )
                )
                return (provider_name, text, attempts)
            except ProviderAuthError as e:
                self.metrics.log(
                    make_event(
                        "auth_error",
                        provider_name,
                        success=False,
                        error=str(e),
                        attempt=attempt,
                    )
                )
                return None
            except asyncio.TimeoutError:
                latency = (time.monotonic() - ts) * 1000
                self.breaker.record_failure(provider_name, "timeout")
                self.metrics.log(
                    make_event(
                        "timeout",
                        provider_name,
                        success=False,
                        latency_ms=latency,
                        error="timeout",
                        attempt=attempt,
                    )
                )
            except ProviderError as e:
                latency = (time.monotonic() - ts) * 1000
                self.breaker.record_failure(provider_name, str(e))
                self.metrics.log(
                    make_event(
                        "provider_error",
                        provider_name,
                        success=False,
                        latency_ms=latency,
                        error=str(e),
                        attempt=attempt,
                    )
                )
            except Exception as e:
                latency = (time.monotonic() - ts) * 1000
                self.breaker.record_failure(provider_name, repr(e))
                self.metrics.log(
                    make_event(
                        "unexpected_error",
                        provider_name,
                        success=False,
                        latency_ms=latency,
                        error=repr(e),
                        attempt=attempt,
                    )
                )

        return None

    async def _try_local_template(
        self, system: str, user: str, t0: float, budget_left
    ) -> RouteResult | None:
        provider = self.providers.get("local_template")
        if provider is None or budget_left() <= 0:
            self.metrics.log(
                make_event("all_failed", "router", success=False, error="sin tiempo o sin local")
            )
            return None
        ts = time.monotonic()
        try:
            text = await provider.generate(system, user)
            latency = (time.monotonic() - ts) * 1000
            self.metrics.log(
                make_event("local_template_ok", "local_template", success=True, latency_ms=latency)
            )
            return RouteResult(
                text=text,
                provider="local_template",
                is_draft=True,
                attempts=0,
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception as e:
            self.metrics.log(
                make_event("local_template_failed", "local_template", success=False, error=repr(e))
            )
            return None

    @staticmethod
    def _wrap(
        item: tuple[str, str, int], t0: float, *, is_draft: bool
    ) -> RouteResult:
        provider_name, text, attempts = item
        return RouteResult(
            text=text,
            provider=provider_name,
            is_draft=is_draft,
            attempts=attempts,
            elapsed_ms=(time.monotonic() - t0) * 1000,
        )
