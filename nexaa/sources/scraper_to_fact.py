"""Convierte un ScrapedContent en un FactInput listo para el motor.

Aplica heurísticas simples para llenar ciudad y categoría a partir del texto
extraído. El editor humano siempre puede corregirlas en la UI antes de generar.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Sequence

from ..editorial.core import FactInput
from .scraper import ScrapedContent


NUBLE_CITIES: tuple[str, ...] = (
    "Chillán", "Chillán Viejo", "San Carlos", "Ñiquén", "San Fabián",
    "Coihueco", "Pinto", "El Carmen", "Pemuco", "Yungay", "Quillón",
    "Bulnes", "Florida", "Ránquil", "Portezuelo", "Treguaco", "Cobquecura",
    "Quirihue", "Ninhue", "San Nicolás", "Chanco",
    "Cobquecura", "San Ignacio", "San Pedro de la Paz",
)

# Ciudades principales de Chile (fuera de Ñuble) con su región
CHILE_CITIES_REGIONS: tuple[tuple[str, str], ...] = (
    ("Santiago", "Región Metropolitana"),
    ("Providencia", "Región Metropolitana"),
    ("Las Condes", "Región Metropolitana"),
    ("Maipú", "Región Metropolitana"),
    ("Puente Alto", "Región Metropolitana"),
    ("La Florida", "Región Metropolitana"),
    ("Pudahuel", "Región Metropolitana"),
    ("Valparaíso", "Región de Valparaíso"),
    ("Viña del Mar", "Región de Valparaíso"),
    ("Quilpué", "Región de Valparaíso"),
    ("Villa Alemana", "Región de Valparaíso"),
    ("San Antonio", "Región de Valparaíso"),
    ("Concepción", "Región del Biobío"),
    ("Talcahuano", "Región del Biobío"),
    ("Los Ángeles", "Región del Biobío"),
    ("Coronel", "Región del Biobío"),
    ("Hualpén", "Región del Biobío"),
    ("Temuco", "Región de La Araucanía"),
    ("Padre Las Casas", "Región de La Araucanía"),
    ("Villarrica", "Región de La Araucanía"),
    ("Puerto Montt", "Región de Los Lagos"),
    ("Osorno", "Región de Los Lagos"),
    ("Castro", "Región de Los Lagos"),
    ("Antofagasta", "Región de Antofagasta"),
    ("Calama", "Región de Antofagasta"),
    ("Iquique", "Región de Tarapacá"),
    ("Alto Hospicio", "Región de Tarapacá"),
    ("Arica", "Región de Arica y Parinacota"),
    ("Copiapó", "Región de Atacama"),
    ("La Serena", "Región de Coquimbo"),
    ("Coquimbo", "Región de Coquimbo"),
    ("Rancagua", "Región de O'Higgins"),
    ("San Fernando", "Región de O'Higgins"),
    ("Talca", "Región del Maule"),
    ("Curicó", "Región del Maule"),
    ("Linares", "Región del Maule"),
    ("Valdivia", "Región de Los Ríos"),
    ("Coyhaique", "Región de Aysén"),
    ("Punta Arenas", "Región de Magallanes"),
)

# Países para alcance internacional
INTERNATIONAL_COUNTRIES: tuple[str, ...] = (
    "Argentina", "Brasil", "Peru", "Bolivia", "Colombia", "Venezuela",
    "México", "Estados Unidos", "España", "Francia", "Alemania",
    "Reino Unido", "China", "Japón", "Rusia", "Israel", "Ucrania",
    "Ecuador", "Paraguay", "Uruguay", "Cuba", "Italia", "Portugal",
)

KEYWORD_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Educación", ("escuela", "colegio", "liceo", "universidad", "alumno", "docente", "seremía de educación", "mineduc", "cft", "ip")),
    ("Salud", ("hospital", "cesfam", "salud", "médico", "paciente", "vacuna", "seremi de salud", "urgencia", "enfermera")),
    ("Seguridad", ("carabinero", "pdi", "delito", "robo", "detención", "policía", "shooting", "balacera", "allanamiento")),
    ("Política", ("alcalde", "concejal", "gore", "intendente", "gobierno regional", "seremi", "ministerio", "congreso")),
    ("Deportes", ("club", "estadio", "fútbol", "tenis", "partido", "campeonato", "selección", "deportista")),
    ("Cultura", ("festival", "teatro", "museo", "exposición", "concierto", "artista", "cultural")),
    ("Economía", ("empresa", "comercio", "empleo", "cesantía", "inversión", "pyme", "feria")),
    ("Medio Ambiente", ("incendio", "contaminación", "río", "bosque", "conaf", "sequía", "alerta ambiental")),
)


def _hash_id(url: str) -> str:
    return "src-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]


def _detect_city(text: str) -> str:
    """Detecta ciudad de Ñuble. Default: Chillán."""
    if not text:
        return "Chillán"
    lower = text.lower()
    for city in NUBLE_CITIES:
        if city.lower() in lower:
            return city
    return "Chillán"


def _detect_city_national(text: str, site_name: str = "") -> tuple[str, str]:
    """Detecta ciudad y región para alcance nacional.
    Devuelve (ciudad, region). Si no encuentra nada, usa el site_name como ciudad.
    """
    lower = text.lower()

    # Primero buscar Ñuble por si la noticia es local aunque venga en pestaña nacional
    for city in NUBLE_CITIES:
        if city.lower() in lower:
            return city, "Región de Ñuble"

    # Luego buscar ciudades nacionales
    for city, region in CHILE_CITIES_REGIONS:
        if city.lower() in lower:
            return city, region

    # Intentar detectar región directamente del texto
    region_match = re.search(
        r"regi[oó]n\s+(?:de\s+|del\s+)?([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s']+?)(?:\s*[,.]|\s+(?:inform|se|la|el|los|las))",
        text, re.IGNORECASE
    )
    if region_match:
        detected = region_match.group(1).strip().title()
        return site_name or "Chile", f"Región de {detected}"

    # Fallback: nombre del sitio como ciudad, Chile como región
    city_fallback = site_name.replace("www.", "").split(".")[0].title() if site_name else "Chile"
    return city_fallback, "Chile"


def _detect_city_international(text: str, site_name: str = "") -> tuple[str, str]:
    """Detecta ciudad/país para alcance internacional."""
    lower = text.lower()

    for country in INTERNATIONAL_COUNTRIES:
        if country.lower() in lower:
            return country, "Internacional"

    # Fallback: nombre del sitio
    city_fallback = site_name.replace("www.", "").split(".")[0].title() if site_name else "Internacional"
    return city_fallback, "Internacional"


def _detect_categoria(text: str) -> str:
    if not text:
        return ""
    lower = text.lower()
    best = ""
    best_hits = 0
    for cat, keywords in KEYWORD_CATEGORIES:
        hits = sum(1 for kw in keywords if kw in lower)
        if hits > best_hits:
            best_hits = hits
            best = cat
    return best


def _detect_date(content: ScrapedContent) -> str:
    if content.publish_date:
        raw = content.publish_date.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
        ):
            try:
                dt = datetime.strptime(raw[:19], fmt[: len(raw[:19]) + 1] if False else fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.now().strftime("%Y-%m-%d")


def scraped_to_fact(
    content: ScrapedContent,
    *,
    region: str = "Región de Ñuble",
    fact_id: str | None = None,
    search_results: Sequence[dict] = (),
    scope: str = "local",
) -> FactInput:
    text_concat = " ".join([content.title, content.summary, content.main_text])
    categoria = _detect_categoria(text_concat)
    fecha = _detect_date(content)
    que_paso = (content.main_text or content.summary or content.title).strip()
    if not content.summary and content.main_text:
        summary = content.main_text[:300].rsplit(".", 1)[0] + "." if "." in content.main_text[:300] else content.main_text[:300]
    else:
        summary = content.summary

    # Detección de ciudad y región según el alcance de búsqueda
    if scope == "national":
        ciudad, region = _detect_city_national(text_concat, content.site_name)
    elif scope == "international":
        ciudad, region = _detect_city_international(text_concat, content.site_name)
    else:
        # local: comportamiento original
        ciudad = _detect_city(text_concat)
        # region ya viene como parámetro ("Región de Ñuble")

    return FactInput(
        fact_id=fact_id or _hash_id(content.canonical_url or content.url),
        categoria=categoria or "General",
        ciudad=ciudad,
        region=region,
        fecha=fecha,
        titulo_corto=content.title[:200] or "Hecho en seguimiento",
        que_paso=que_paso,
        por_que_importa=summary or "[REQUIERE EDICION: completar por que importa]",
        contexto="",
        impacto="",
        fuentes=(content.canonical_url or content.url,),
        source_url=content.canonical_url or content.url,
        source_site=content.site_name,
        author=content.author,
        language=content.language,
        image_url=content.image_url,
        search_results=tuple(search_results),
        datos_adicionales={
            "url_original": content.url,
            "canonical_url": content.canonical_url,
            "extraction_warnings": "; ".join(content.extraction_warnings) or "ninguna",
            "search_results_count": str(len(search_results)),
            "scope": scope,
        },
    )

