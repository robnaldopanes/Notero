"""Proveedor de plantilla local.

NO es un publicador. Genera un BORRADOR estructurado a partir de los hechos
verificados cuando todos los proveedores externos fallan. Siempre marca la
salida como DRAFT y solo devuelve texto — el caller (engine) es responsable
de etiquetar el resultado y NUNCA publicar un draft sin aprobación humana.
"""

from __future__ import annotations

import re

from .base import AIProvider
from ..editorial.core import FactInput
from ..editorial.style import DRAFT_HEADER, UNCERTAINTY_MARKER


class LocalTemplateProvider(AIProvider):
    name = "local_template"
    is_available = True

    _USER_FACT_RE = re.compile(r"ID del hecho:\s*(\S+)")
    _CIUDAD_RE = re.compile(r"^Ciudad:\s*(.+)$", re.MULTILINE)
    _REGION_RE = re.compile(r"^Región:\s*(.+)$", re.MULTILINE)
    _FECHA_RE = re.compile(r"^Fecha del hecho:\s*(.+)$", re.MULTILINE)
    _TITULO_RE = re.compile(r"^Título referencial:\s*(.+)$", re.MULTILINE)
    _CATEGORIA_RE = re.compile(r"^Categoría asignada:\s*(.+)$", re.MULTILINE)
    _QUE_RE = re.compile(r"^- Qué ocurrió:\s*(.+)$", re.MULTILINE)
    _PORQUE_RE = re.compile(r"^- Por qué importa:\s*(.+)$", re.MULTILINE)

    async def generate(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ) -> str:
        fact = self._parse_fact(user)
        if fact is None:
            return self._empty_draft(system)

        if "RECUADRO" in system or "FACEBOOK" in system.upper():
            return self._render_social(fact, system)
        return self._render_classic(fact, system)

    def _render_classic(self, fact, system: str) -> str:
        titulo = self._clip(fact.titulo_corto, 90)
        return (
            f"{DRAFT_HEADER}\n"
            f"Proveedor usado: local_template (todos los externos fallaron)\n"
            f"{DRAFT_HEADER}\n\n"
            f"Categoría: {fact.categoria}\n"
            f"Ciudad/Región: {fact.ciudad}, {fact.region}\n"
            f"Titular: {titulo}\n\n"
            f"Desarrollo:\n"
            f"{fact.que_paso}\n\n"
            f"El hecho fue registrado el {fact.fecha}. "
            f"{UNCERTAINTY_MARKER} Este borrador no fue redactado por un modelo "
            f"de lenguaje; requiere edición humana antes de publicarse.\n\n"
            f"Contexto:\n"
            f"{fact.contexto or UNCERTAINTY_MARKER + ' Contexto no disponible en el hecho de origen.'}\n\n"
            f"Impacto:\n"
            f"{fact.impacto or UNCERTAINTY_MARKER + ' Impacto no cuantificado en el hecho de origen.'}\n\n"
            f"Cierre:\n"
            f"Desde Nexaa continuaremos el seguimiento de este hecho a medida "
            f"que se confirmen más antecedentes."
        )

    def _render_social(self, fact, system: str) -> str:
        titulo = self._clip(fact.titulo_corto, 90)
        attribution = ""
        if fact.source_url:
            attribution = f"\nFuente: {fact.source_site} — {fact.source_url}\n"
        return (
            f"{DRAFT_HEADER}\n"
            f"Proveedor usado: local_template (todos los externos fallaron)\n"
            f"{DRAFT_HEADER}\n\n"
            f"📌 CATEGORÍA: {fact.categoria}\n"
            f"📌 CIUDAD/REGIÓN: {fact.ciudad}, {fact.region}\n\n"
            f"🟥 TITULAR: {titulo}\n\n"
            f"🟦 NOTICIA:\n"
            f"{fact.que_paso}\n\n"
            f"El hecho fue registrado el {fact.fecha}. "
            f"{UNCERTAINTY_MARKER} Este borrador no fue redactado por un modelo "
            f"de lenguaje; requiere edición humana antes de publicarse.{attribution}\n\n"
            f"🟩 RESUMEN CORTO:\n"
            f"{self._clip(fact.por_que_importa, 280)}\n\n"
            f"📲 FACEBOOK NEXAA:\n"
            f"⚡ {titulo}\n\n"
            f"{self._clip(fact.por_que_importa, 200)}\n\n"
            f"¿Qué opinas de esta noticia? Cuéntanos en los comentarios.\n\n"
            f"Sigue a Nexaa para más noticias de la Región de Ñuble.\n\n"
            f"#Ñuble #Chile #NoticiasRegionales #{fact.categoria or 'General'}"
        )

    def _parse_fact(self, user: str) -> FactInput | None:
        m = self._USER_FACT_RE.search(user)
        if not m:
            return None
        fact_id = m.group(1)

        def grab(regex: re.Pattern[str], default: str = "") -> str:
            mm = regex.search(user)
            return mm.group(1).strip() if mm else default

        return FactInput(
            fact_id=fact_id,
            categoria=grab(self._CATEGORIA_RE, "Sin categoría"),
            ciudad=grab(self._CIUDAD_RE, "Ñuble"),
            region=grab(self._REGION_RE, "Región de Ñuble"),
            fecha=grab(self._FECHA_RE, "fecha sin confirmar"),
            titulo_corto=grab(self._TITULO_RE, "Hecho en seguimiento"),
            que_paso=grab(self._QUE_RE, "Sin descripción disponible."),
            por_que_importa=grab(self._PORQUE_RE, "Sin justificación disponible."),
        )

    @staticmethod
    def _clip(text: str, n: int) -> str:
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    def _empty_draft(self, system: str = "") -> str:
        if system and ("RECUADRO" in system or "FACEBOOK" in system.upper()):
            return (
                f"{DRAFT_HEADER}\n{DRAFT_HEADER}\n\n"
                f"📌 CATEGORÍA: Sin categoría\n"
                f"📌 CIUDAD/REGIÓN: Región de Ñuble, Chile\n\n"
                f"🟥 TITULAR: [BORRADOR - REQUIERE EDICIÓN HUMANA]\n\n"
                f"🟦 NOTICIA:\n"
                f"{UNCERTAINTY_MARKER} No fue posible parsear el hecho de origen.\n\n"
                f"🟩 RESUMEN CORTO:\n{UNCERTAINTY_MARKER}\n\n"
                f"📲 FACEBOOK NEXAA:\n{UNCERTAINTY_MARKER}"
            )
        return (
            f"{DRAFT_HEADER}\n"
            f"{DRAFT_HEADER}\n\n"
            f"Categoría: Sin categoría\n"
            f"Ciudad/Región: Región de Ñuble, Chile\n"
            f"Titular: [BORRADOR - REQUIERE EDICIÓN HUMANA]\n\n"
            f"Desarrollo:\n"
            f"{UNCERTAINTY_MARKER} No fue posible parsear el hecho de origen. "
            f"Un editor humano debe redactar esta noticia manualmente.\n\n"
            f"Contexto:\n{UNCERTAINTY_MARKER}\n\n"
            f"Impacto:\n{UNCERTAINTY_MARKER}\n\n"
            f"Cierre:\nPendiente de redacción."
        )
