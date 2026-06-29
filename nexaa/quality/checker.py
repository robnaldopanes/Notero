"""Checker determinista de la salida.

NO usa otra LLM. Solo regex, conteo de palabras, longitudes y presencia de
secciones. Esto es más rápido, barato y reproducible que un juez LLM.

Trabaja contra un EditorialFormat específico, así que el mismo checker sirve
para nexaa_v1, nexaa_social_v1 o cualquier formato nuevo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..editorial.core import parse_sections
from ..editorial.formats import EditorialFormat, FORMATS
from ..editorial.style import (
    CLICKBAIT_PATTERNS,
    DRAFT_HEADER,
    UNCERTAINTY_MARKER,
)


@dataclass
class QualityReport:
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_human_review: bool = False
    is_draft: bool = False
    uncertainty_count: int = 0
    word_counts: dict[str, int] = field(default_factory=dict)
    format_name: str = "nexaa_v1"

    def __str__(self) -> str:
        if self.ok and not self.issues and not self.warnings:
            return "OK"
        parts = []
        if self.issues:
            parts.append("issues: " + "; ".join(self.issues))
        if self.warnings:
            parts.append("warnings: " + "; ".join(self.warnings))
        return " | ".join(parts)


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"\b\w+\b", text, flags=re.UNICODE) if w])


def _extract_region_keywords(region: str) -> list[str]:
    words = re.findall(r"\b\w+\b", region.lower(), flags=re.UNICODE)
    stopwords = {"de", "del", "la", "el", "los", "las", "y", "en", "un", "una", "región", "region"}
    return [w for w in words if w not in stopwords and len(w) > 2]


def check_output(
    text: str,
    config: Mapping,
    *,
    format: EditorialFormat | None = None,
    forbidden_words: Sequence[str] = (),
) -> QualityReport:
    fmt = format or FORMATS["nexaa_v1"]
    issues: list[str] = []
    warnings: list[str] = []
    word_counts: dict[str, int] = {}

    quality_cfg = config.get("quality", {})

    is_draft = DRAFT_HEADER in text
    if is_draft:
        warnings.append("salida es un BORRADOR (todos los proveedores externos fallaron)")

    sections = parse_sections(text, format=fmt)

    for required in fmt.required_section_names():
        if not sections.get(required):
            issues.append(f"falta sección obligatoria: {required}")

    titular = sections.get("Titular", "").strip()
    if titular:
        if fmt.titular_max_chars and len(titular) > fmt.titular_max_chars:
            issues.append(f"titular excede {fmt.titular_max_chars} chars ({len(titular)})")
        wc_tit = _word_count(titular)
        if fmt.titular_max_words and wc_tit > fmt.titular_max_words:
            warnings.append(f"titular largo: {wc_tit} palabras (recomendado ≤{fmt.titular_max_words})")

    for spec in fmt.sections:
        name = spec.name
        text_sec = sections.get(name, "").strip()
        if not text_sec:
            continue
        wc = _word_count(text_sec)
        word_counts[name] = wc
        if spec.min_words and wc < spec.min_words:
            issues.append(f"sección {name} muy corta: {wc} palabras (mín {spec.min_words})")
        if spec.max_words and name != "Titular" and wc > spec.max_words:
            issues.append(f"sección {name} muy larga: {wc} palabras (máx {spec.max_words})")

    region_str = config.get("region", "Región de Ñuble, Chile")
    region_keywords = _extract_region_keywords(region_str)

    ciudad = sections.get("Ciudad/Región", "").strip()
    if not ciudad:
        if "Ciudad/Región" in fmt.required_section_names():
            issues.append("Ciudad/Región vacía")
    elif region_keywords:
        if not any(kw in ciudad.lower() for kw in region_keywords):
            kw_display = " ni ".join(kw.capitalize() for kw in region_keywords)
            warnings.append(f"la sección Ciudad/Región no menciona explícitamente {kw_display}")

    uncertainty = text.count(UNCERTAINTY_MARKER)
    needs_human_review = uncertainty > 0
    if uncertainty:
        warnings.append(f"{uncertainty} marcador(es) de incertidumbre presente(s)")

    lower_text = text.lower()
    combined_forbidden = list(forbidden_words) + list(quality_cfg.get("forbidden_words", []))
    for word in combined_forbidden:
        if word and word.lower() in lower_text:
            issues.append(f"palabra prohibida encontrada: {word!r}")

    for pattern in CLICKBAIT_PATTERNS:
        if re.search(pattern, lower_text, flags=re.IGNORECASE):
            issues.append(f"patrón clickbait detectado: {pattern}")
    for pattern in fmt.forbidden_patterns:
        if re.search(pattern, lower_text, flags=re.IGNORECASE):
            issues.append(f"patrón prohibido del formato detectado: {pattern}")

    if re.search(r"\b\d{1,3}\.\d{3}\.\d{3}[-k]?\b", text):
        warnings.append("hay un RUT en el texto; verifica consentimiento de fuente")

    ok = len(issues) == 0
    return QualityReport(
        ok=ok,
        issues=issues,
        warnings=warnings,
        needs_human_review=needs_human_review,
        is_draft=is_draft,
        uncertainty_count=uncertainty,
        word_counts=word_counts,
        format_name=fmt.name,
    )
