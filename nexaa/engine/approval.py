"""Cola de aprobación humana.

Todo lo generado va a data/pending/ como JSON. Un editor humano revisa y
mueve a data/published/ o data/rejected/. Esto es el "humano en el loop"
que evita que un error del sistema se publique automáticamente.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..editorial.core import FactInput
from ..quality.checker import QualityReport


@dataclass
class PendingItem:
    item_id: str
    created_at: str
    fact_id: str
    fact_summary: dict
    provider: str
    is_draft: bool
    text: str
    quality: dict
    router_attempts: int
    elapsed_ms: float
    status: str = "pending"
    decision_at: str | None = None
    decision_by: str | None = None
    decision_reason: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PendingItem":
        d = dict(d)
        d["fact_summary"] = dict(d.get("fact_summary", {}))
        d["quality"] = dict(d.get("quality", {}))
        d["extra"] = dict(d.get("extra", {}))
        return cls(**d)


class ApprovalQueue:
    def __init__(self, pending_dir: Path, published_dir: Path, rejected_dir: Path):
        self.pending_dir = Path(pending_dir)
        self.published_dir = Path(published_dir)
        self.rejected_dir = Path(rejected_dir)
        for d in (self.pending_dir, self.published_dir, self.rejected_dir):
            d.mkdir(parents=True, exist_ok=True)

    def submit(
        self,
        fact: FactInput,
        text: str,
        provider: str,
        is_draft: bool,
        quality: QualityReport,
        router_attempts: int,
        elapsed_ms: float,
    ) -> Path:
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        item_id = f"{ts}_{fact.fact_id}"
        item = PendingItem(
            item_id=item_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            fact_id=fact.fact_id,
            fact_summary={
                "categoria": fact.categoria,
                "ciudad": fact.ciudad,
                "region": fact.region,
                "fecha": fact.fecha,
                "titulo_corto": fact.titulo_corto,
                "image_url": fact.image_url,
            },
            provider=provider,
            is_draft=is_draft,
            text=text,
            quality={
                "ok": quality.ok,
                "issues": quality.issues,
                "warnings": quality.warnings,
                "needs_human_review": quality.needs_human_review,
                "uncertainty_count": quality.uncertainty_count,
                "word_counts": quality.word_counts,
            },
            router_attempts=router_attempts,
            elapsed_ms=elapsed_ms,
        )
        path = self.pending_dir / f"{item_id}.json"
        path.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def list_pending(self) -> list[PendingItem]:
        return [self._read(p) for p in sorted(self.pending_dir.glob("*.json"))]

    def _read(self, path: Path) -> PendingItem:
        return PendingItem.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def approve(self, pending_path: str | Path, reviewer: str, reason: str = "") -> Path:
        src = Path(pending_path)
        if not src.exists():
            raise FileNotFoundError(f"no existe: {src}")
        item = self._read(src)
        if item.status != "pending":
            raise ValueError(f"item ya decidido ({item.status})")
        item.status = "published"
        item.decision_at = datetime.now().isoformat(timespec="seconds")
        item.decision_by = reviewer
        item.decision_reason = reason
        dst = self.published_dir / src.name
        dst.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        src.unlink()
        return dst

    def reject(self, pending_path: str | Path, reviewer: str, reason: str) -> Path:
        src = Path(pending_path)
        if not src.exists():
            raise FileNotFoundError(f"no existe: {src}")
        item = self._read(src)
        if item.status != "pending":
            raise ValueError(f"item ya decidido ({item.status})")
        item.status = "rejected"
        item.decision_at = datetime.now().isoformat(timespec="seconds")
        item.decision_by = reviewer
        item.decision_reason = reason
        dst = self.rejected_dir / src.name
        dst.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        src.unlink()
        return dst
