"""Verificador pre-generación. Valida que el hecho de entrada tiene lo mínimo
para generar una noticia. NO verifica verdad — eso es responsabilidad del
editor que curó el hecho. Esto evita propagar inputs claramente rotos.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..editorial.core import FactInput


@dataclass
class VerificationReport:
    ok: bool
    missing_critical: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.ok:
            return "OK"
        parts = []
        if self.missing_critical:
            parts.append("CRÍTICO falta: " + ", ".join(self.missing_critical))
        if self.missing_optional:
            parts.append("opcional falta: " + ", ".join(self.missing_optional))
        if self.warnings:
            parts.append("avisos: " + ", ".join(self.warnings))
        return " | ".join(parts) if parts else "OK"


def verify_fact(fact: FactInput) -> VerificationReport:
    report = VerificationReport(ok=True)

    if not fact.fact_id or not fact.fact_id.strip():
        report.missing_critical.append("fact_id")
    if not fact.categoria or fact.categoria.strip().lower() in {
        "", "sin categoría", "sin categoria", "n/a", "tbd"
    }:
        report.missing_critical.append("categoría")
    if not fact.ciudad or not fact.ciudad.strip():
        report.missing_critical.append("ciudad")
    if not fact.region or "ñuble" not in fact.region.lower():
        report.missing_critical.append("region (debe incluir Ñuble)")
    if not fact.fecha or not fact.fecha.strip():
        report.missing_critical.append("fecha")
    if not fact.titulo_corto or len(fact.titulo_corto.strip()) < 8:
        report.missing_critical.append("titulo_corto (≥8 caracteres)")
    if not fact.que_paso or len(fact.que_paso.strip()) < 20:
        report.missing_critical.append("que_paso (≥20 caracteres)")
    if not fact.por_que_importa or len(fact.por_que_importa.strip()) < 10:
        report.missing_critical.append("por_que_importa (≥10 caracteres)")

    if not fact.contexto:
        report.missing_optional.append("contexto")
    if not fact.impacto:
        report.missing_optional.append("impacto")
    if not fact.fuentes:
        report.warnings.append("sin fuentes explícitas en el hecho")

    report.ok = len(report.missing_critical) == 0
    return report
