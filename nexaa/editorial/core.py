"""Editorial Core: reglas Nexaa, builder del system prompt, parser de secciones.

El Editorial Core es código, no prompt dinámico de usuario. Las reglas viven aquí
y se inyectan a cualquier proveedor de IA. Esto garantiza que la línea editorial
sea idéntica sin importar qué modelo responda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .formats import FORMATS, EditorialFormat, get_format
from .style import UNCERTAINTY_MARKER


NEXAA_SECTIONS: tuple[str, ...] = FORMATS["nexaa_v1"].section_names()


@dataclass(frozen=True)
class EditorialStyle:
    name: str
    region: str
    language: str
    format_name: str = "nexaa_v1"

    @classmethod
    def default(cls) -> "EditorialStyle":
        return cls(
            name="nexaa_v1",
            region="Región de Ñuble, Chile",
            language="es-CL",
            format_name="nexaa_v1",
        )

    @property
    def format(self) -> EditorialFormat:
        return get_format(self.format_name)


@dataclass(frozen=True)
class FactInput:
    """Hecho verificado de entrada. NO texto libre del usuario."""

    fact_id: str
    categoria: str
    ciudad: str
    region: str
    fecha: str
    titulo_corto: str
    que_paso: str
    por_que_importa: str
    fuentes: tuple[str, ...] = ()
    contexto: str = ""
    impacto: str = ""
    datos_adicionales: Mapping[str, str] = field(default_factory=dict)
    source_url: str = ""
    source_site: str = ""
    author: str = ""
    language: str = ""
    image_url: str = ""
    search_results: tuple[dict, ...] = ()

    def to_prompt(self) -> str:
        lines: list[str] = [
            f"ID del hecho: {self.fact_id}",
            f"Categoría asignada: {self.categoria}",
            f"Ciudad: {self.ciudad}",
            f"Región: {self.region}",
            f"Fecha del hecho: {self.fecha}",
            f"Título referencial: {self.titulo_corto}",
            "",
            "DATOS VERIFICADOS (úsalo como fuente primaria):",
            f"- Qué ocurrió: {self.que_paso}",
            f"- Por qué importa: {self.por_que_importa}",
        ]
        if self.contexto:
            lines.append(f"- Contexto disponible: {self.contexto}")
        if self.impacto:
            lines.append(f"- Impacto conocido: {self.impacto}")
        if self.datos_adicionales:
            lines.append("- Datos adicionales verificados:")
            for k, v in self.datos_adicionales.items():
                lines.append(f"  · {k}: {v}")
        if self.author:
            lines.append(f"- Autor del material de origen: {self.author}")
        if self.source_url:
            lines.append("")
            lines.append("ATENCIÓN — MATERIAL DE ORIGEN:")
            lines.append(
                "El texto a continuación es SOLO material base, no el resultado final. La noticia final es "
                "PROPIA DE NEXAA, no del medio de origen. NO incluyas 'Fuente:', NO atribuyas a medios "
                "externos, NO incluyas URLs de otros sitios. Tu trabajo es producir una versión MEJOR: "
                "titular más fuerte, contenido mejor estructurado (pirámide invertida), resumen editorial "
                "sintético, post para Facebook optimizado. Trata la información como insumo, no como cita."
            )
            lines.append(f"- Tema de referencia: {self.source_site or 'medio externo'}")
        if self.search_results:
            lines.append("")
            lines.append("FUENTES ADICIONALES — CONTENIDO COMPLETO DE OTROS MEDIOS:")
            lines.append(
                "A continuación tienes el contenido completo (o parcial) de otros medios que cubrieron "
                "este mismo tema. ÚSALOS para enriquecer la noticia con datos, ángulos y contexto que "
                "el artículo original no tiene. NO copies párrafos textuales. NO los cites como fuente. "
                "Tratalos como investigación de background: extrae los datos más relevantes y redáctalos "
                "con tus propias palabras, integrados naturalmente en la noticia Nexaa."
            )
            for i, r in enumerate(self.search_results, 1):
                lines.append(f"\n--- FUENTE {i}: {r.get('title', '(sin título)')} ---")
                if r.get("full_text"):
                    lines.append(r["full_text"])
                elif r.get("description"):
                    lines.append(f"(solo snippet disponible) {r['description'][:300]}")
        if self.fuentes:
            lines.append("")
            lines.append("Fuentes:")
            for f in self.fuentes:
                lines.append(f"- {f}")
        lines.append("")
        lines.append(
            "INSTRUCCIONES DE GENERACIÓN:"
        )
        lines.append(
            "1. Usa SOLO los datos verificados de arriba."
        )
        lines.append(
            "2. Si necesitas un dato que NO está aquí, NO lo inventes. "
            f"Márcalo como: {UNCERTAINTY_MARKER}"
        )
        lines.append(
            "3. Estructura la respuesta con los encabezados exactos indicados en el system prompt."
        )
        return "\n".join(lines)

    def to_prompt_with_format(self, fmt: "EditorialFormat | None" = None) -> str:  # noqa: F821
        """Versión del user-prompt que inyecta los mínimos de palabras del formato."""
        from .formats import get_format
        base = self.to_prompt()
        resolved = fmt or get_format("nexaa_v1")
        min_lines: list[str] = []
        for spec in resolved.sections:
            if spec.min_words:
                min_lines.append(f"  · {spec.name}: mínimo {spec.min_words} palabras")
        if not min_lines:
            return base
        extension = (
            "\n\n⚠️ EXTENSIÓN MÍNIMA OBLIGATORIA — CRÍTICO:\n"
            "Las siguientes secciones DEBEN tener al menos el número de palabras indicado. "
            "Si el material de origen es escaso, enriquece con contexto verificable, "
            "antecedentes históricos, impacto local y detalles del hecho. "
            "NO entregues secciones más cortas que estos mínimos:\n"
            + "\n".join(min_lines)
            + "\nSi no cumples estos mínimos, la noticia será rechazada automáticamente."
        )
        return base + extension


def build_system_prompt(style: EditorialStyle) -> str:
    return style.format.build_system_prompt(region=style.region, language=style.language)


def parse_sections(text: str, format: EditorialFormat | None = None) -> dict[str, str]:
    fmt = format or FORMATS["nexaa_v1"]
    return fmt.parse(text)
