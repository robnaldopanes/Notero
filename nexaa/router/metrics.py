"""Métricas estructuradas en JSONL para observabilidad."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO


@dataclass
class RouterEvent:
    ts: float
    event: str
    provider: str
    latency_ms: float = 0.0
    success: bool = False
    error: str = ""
    attempt: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts))
        return d


class MetricsLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] | None = None

    def _open(self) -> IO[str]:
        if self._fh is None:
            self._fh = self.log_path.open("a", encoding="utf-8")
        return self._fh

    def log(self, event: RouterEvent) -> None:
        fh = self._open()
        fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def make_event(
    event: str,
    provider: str,
    *,
    success: bool = False,
    latency_ms: float = 0.0,
    error: str = "",
    attempt: int = 0,
    **extra,
) -> RouterEvent:
    return RouterEvent(
        ts=time.time(),
        event=event,
        provider=provider,
        latency_ms=latency_ms,
        success=success,
        error=error,
        attempt=attempt,
        extra=extra,
    )
