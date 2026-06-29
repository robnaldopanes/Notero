"""Circuit breaker por proveedor.

Estados:
- CLOSED: pasa normal. Tras N fallos consecutivos → OPEN.
- OPEN: bloquea llamadas hasta cumplido el cooldown → HALF_OPEN.
- HALF_OPEN: deja pasar UNA llamada de prueba. Si pasa → CLOSED. Si falla → OPEN.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

State = Literal["closed", "open", "half_open"]


@dataclass
class _ProviderState:
    failures: int = 0
    state: State = "closed"
    open_until: float = 0.0
    last_error: str = ""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 90):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, _ProviderState] = {}
        self._lock = Lock()

    def allow(self, provider: str) -> bool:
        with self._lock:
            st = self._states.setdefault(provider, _ProviderState())
            if st.state == "open":
                if time.monotonic() >= st.open_until:
                    st.state = "half_open"
                    return True
                return False
            return True

    def record_success(self, provider: str) -> None:
        with self._lock:
            st = self._states.setdefault(provider, _ProviderState())
            st.failures = 0
            st.state = "closed"
            st.open_until = 0.0
            st.last_error = ""

    def record_failure(self, provider: str, error: str) -> None:
        with self._lock:
            st = self._states.setdefault(provider, _ProviderState())
            st.failures += 1
            st.last_error = error
            if st.state == "half_open":
                st.state = "open"
                st.open_until = time.monotonic() + self.cooldown_seconds
            elif st.failures >= self.failure_threshold:
                st.state = "open"
                st.open_until = time.monotonic() + self.cooldown_seconds

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {
                    "state": st.state,
                    "failures": st.failures,
                    "open_until_in": max(0.0, st.open_until - time.monotonic()),
                    "last_error": st.last_error,
                }
                for name, st in self._states.items()
            }
