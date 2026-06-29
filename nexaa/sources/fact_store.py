"""Fact Store. Carga hechos verificados desde JSON.

El sistema NO genera desde texto libre. Solo desde hechos que un editor
(curador humano) aprobó previamente. Esto es la pieza anti-alucinación
más importante.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..editorial.core import FactInput


class FactStore:
    def __init__(self, facts_dir: Path):
        self.facts_dir = Path(facts_dir)

    def list_ids(self) -> list[str]:
        if not self.facts_dir.exists():
            return []
        return sorted(p.stem for p in self.facts_dir.glob("*.json"))

    def load(self, fact_id_or_path: str) -> FactInput:
        path = self._resolve(fact_id_or_path)
        if not path.exists():
            raise FileNotFoundError(f"hecho no encontrado: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._to_fact(data)

    def save(self, fact: FactInput) -> Path:
        self.facts_dir.mkdir(parents=True, exist_ok=True)
        path = self.facts_dir / f"{fact.fact_id}.json"
        path.write_text(
            json.dumps(self._from_fact(fact), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def _resolve(self, fact_id_or_path: str) -> Path:
        p = Path(fact_id_or_path)
        if p.is_absolute() or p.exists():
            return p
        return self.facts_dir / f"{fact_id_or_path}.json"

    @staticmethod
    def _to_fact(data: dict) -> FactInput:
        required = [
            "fact_id", "categoria", "ciudad", "region", "fecha",
            "titulo_corto", "que_paso", "por_que_importa",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"hecho inválido, faltan campos: {missing}")
        return FactInput(
            fact_id=str(data["fact_id"]),
            categoria=str(data["categoria"]),
            ciudad=str(data["ciudad"]),
            region=str(data["region"]),
            fecha=str(data["fecha"]),
            titulo_corto=str(data["titulo_corto"]),
            que_paso=str(data["que_paso"]),
            por_que_importa=str(data["por_que_importa"]),
            contexto=str(data.get("contexto", "")),
            impacto=str(data.get("impacto", "")),
            fuentes=tuple(data.get("fuentes", ())),
            datos_adicionales=dict(data.get("datos_adicionales", {})),
        )

    @staticmethod
    def _from_fact(fact: FactInput) -> dict:
        return {
            "fact_id": fact.fact_id,
            "categoria": fact.categoria,
            "ciudad": fact.ciudad,
            "region": fact.region,
            "fecha": fact.fecha,
            "titulo_corto": fact.titulo_corto,
            "que_paso": fact.que_paso,
            "por_que_importa": fact.por_que_importa,
            "contexto": fact.contexto,
            "impacto": fact.impacto,
            "fuentes": list(fact.fuentes),
            "datos_adicionales": dict(fact.datos_adicionales),
        }
