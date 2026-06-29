"""Tests del sistema de formatos editoriales."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexaa.editorial.core import EditorialStyle, FactInput, build_system_prompt, parse_sections
from nexaa.editorial.formats import (
    FORMATS,
    NEXAA_SOCIAL_V1,
    NEXAA_V1,
    EditorialFormat,
    get_format,
)
from nexaa.providers.local_template import LocalTemplateProvider
from nexaa.quality.checker import check_output


SAMPLE_SOCIAL = """\
📌 CATEGORÍA: Educación
📌 CIUDAD/REGIÓN: Chillán, Región de Ñuble

🟥 TITULAR: Liceo de Chillán abre laboratorio de ciencias

🟦 NOTICIA:
El Liceo Bicentenario República de Chile de Chillán abrió un nuevo laboratorio de ciencias con capacidad para 30 estudiantes por jornada, luego de 18 meses de obras financiadas por el Ministerio de Educación. La inversión declarada por la seremía regional fue de 420 millones de pesos, e incluyó equipamiento para química, física y biología.

El nuevo espacio permitirá descomprimir la demanda de实验 práctica que hasta ahora se cubría parcialmente en otras dependencias del establecimiento. Alrededor de 1.200 estudiantes accederán a clases prácticas en condiciones adecuadas durante el presente año escolar.

La directora del liceo, María González, señaló que se trata de un paso histórico para la comunidad educativa local y agradeció el apoyo del Ministerio de Educación. Autoridades regionales presentes en la inauguración confirmaron que el modelo de inversión podría replicarse en otros liceos públicos de la región.

🟩 RESUMEN CORTO:
El Liceo Bicentenario de Chillán abrió un laboratorio nuevo con capacidad para 30 estudiantes. La obra costó 420 millones de pesos y beneficiará a 1.200 alumnos.

📲 FACEBOOK NEXAA:
⚡ Chillán ya tiene laboratorio nuevo en su liceo Bicentenario

El nuevo espacio atenderá a 30 estudiantes por jornada y beneficiará a 1.200 alumnos. La inversión fue de 420 millones de pesos.

¿Qué te parece esta noticia? ¿Crees que deberían replicar este modelo en otros liceos?

Síguenos en Nexaa para más noticias de la Región de Ñuble.

#Ñuble #Chillán #Educación #Chile
"""


def test_both_formats_registered():
    assert "nexaa_v1" in FORMATS
    assert "nexaa_social_v1" in FORMATS
    assert get_format("nexaa_v1") is NEXAA_V1
    assert get_format("nexaa_social_v1") is NEXAA_SOCIAL_V1
    assert get_format("nope") is NEXAA_V1


def test_social_format_sections():
    names = NEXAA_SOCIAL_V1.section_names()
    assert names == ("Categoría", "Ciudad/Región", "Titular", "Noticia", "Resumen Corto", "Facebook Nexaa")
    for name in names:
        spec = NEXAA_SOCIAL_V1.get(name)
        assert spec is not None
        assert spec.required
        assert spec.emoji


def test_social_format_parses_sample():
    sections = NEXAA_SOCIAL_V1.parse(SAMPLE_SOCIAL)
    assert sections["Categoría"] == "Educación"
    assert sections["Ciudad/Región"] == "Chillán, Región de Ñuble"
    assert "Liceo" in sections["Titular"]
    assert "420 millones" in sections["Noticia"]
    assert "1.200" in sections["Resumen Corto"]
    assert "FACEBOOK" in sections["Facebook Nexaa"].upper() or "#Ñuble" in sections["Facebook Nexaa"]


def test_social_format_tolerates_recuadro_prefix():
    text = "🟥 RECUADRO 1: TITULAR: Prueba de titular"
    sections = NEXAA_SOCIAL_V1.parse(text)
    assert sections["Titular"] == "Prueba de titular"


def test_parse_sections_accepts_format():
    sections = parse_sections(SAMPLE_SOCIAL, format=NEXAA_SOCIAL_V1)
    assert "Noticia" in sections
    assert "Facebook Nexaa" in sections


def test_classic_format_still_works():
    text = (
        "Categoría: Educación\n"
        "Ciudad/Región: Chillán, Región de Ñuble\n"
        "Titular: Prueba\n"
        "Desarrollo: " + ("largo " * 100) + "\n"
        "Contexto: " + ("fondo " * 30) + "\n"
        "Impacto: " + ("efecto " * 30) + "\n"
        "Cierre: cierre"
    )
    sections = NEXAA_V1.parse(text)
    assert sections["Desarrollo"]
    assert sections["Cierre"] == "cierre"


def test_system_prompt_social_mentions_facebook():
    style = EditorialStyle.default()
    style_social = EditorialStyle(
        name="nexaa_social_v1",
        region=style.region,
        language=style.language,
        format_name="nexaa_social_v1",
    )
    sp = build_system_prompt(style_social)
    assert "FACEBOOK" in sp.upper()
    assert "Titular" in sp or "RECUADRO" in sp
    for sec in ("CATEGORÍA", "TITULAR", "NOTICIA", "RESUMEN CORTO", "FACEBOOK"):
        assert sec.upper() in sp.upper() or sec in sp


def test_checker_validates_social_format():
    report = check_output(SAMPLE_SOCIAL, {"quality": {"forbidden_words": []}}, format=NEXAA_SOCIAL_V1)
    assert report.format_name == "nexaa_social_v1"
    assert "Noticia" in report.word_counts
    assert "Facebook Nexaa" in report.word_counts
    assert report.word_counts["Noticia"] > 50
    assert "Ñuble" in SAMPLE_SOCIAL or "Chillán" in SAMPLE_SOCIAL


def test_checker_flags_missing_social_section():
    bad = "📌 CATEGORÍA: X\n🟥 TITULAR: t\n🟦 NOTICIA: " + ("x " * 30) + "\n"
    report = check_output(bad, {"quality": {}}, format=NEXAA_SOCIAL_V1)
    assert not report.ok
    assert any("Facebook Nexaa" in i or "Resumen Corto" in i for i in report.issues)


def test_social_system_prompt_requires_improvement():
    style = EditorialStyle(
        name="nexaa_social_v1",
        region="Región de Ñuble, Chile",
        language="es-CL",
        format_name="nexaa_social_v1",
    )
    sp = build_system_prompt(style)
    assert "MEJORAR" in sp.upper() or "MEJOR" in sp.upper()
    assert "no es solo una copia reformateada" in sp.lower() or "copia reformateada" in sp.lower()
    assert "MEJORAR el titular" in sp
    assert "MEJORAR el contenido" in sp
    assert "MEJORAR el resumen" in sp
    assert "MEJORAR el post de redes" in sp or "post de redes" in sp.lower()


def test_fact_prompt_explicit_improvement_instruction_with_source():
    fact = FactInput(
        fact_id="x",
        categoria="Educación",
        ciudad="Chillán",
        region="Región de Ñuble",
        fecha="2026-06-14",
        titulo_corto="Original",
        que_paso="Texto original del artículo.",
        por_que_importa="Por qué importa.",
        source_url="https://www.ejemplo.cl/noticia",
        source_site="Ejemplo",
    )
    p = fact.to_prompt()
    assert "MEJOR" in p.upper()
    assert "SOLO material base" in p
    assert "PROPIA DE NEXAA" in p or "propia de Nexaa" in p.lower()
    assert "no incluyas" in p.lower() and "fuente" in p.lower()
    assert "atribuyas" in p.lower() or "atribuir" in p.lower()


def test_local_template_renders_social_format():
    async def run():
        prov = LocalTemplateProvider()
        fact = FactInput(
            fact_id="t1",
            categoria="Educación",
            ciudad="Chillán",
            region="Región de Ñuble",
            fecha="2026-06-12",
            titulo_corto="Liceo abre laboratorio",
            que_paso="Detalle extenso del hecho con más de veinte caracteres.",
            por_que_importa="Por qué importa para la comunidad.",
        )
        text = await prov.generate(
            "FORMATO Nexaa social con FACEBOOK NEXAA y RECUADRO 1", fact.to_prompt()
        )
        assert "🟥" in text and "🟦" in text and "🟩" in text and "📲" in text
        assert "FACEBOOK NEXAA" in text.upper()
    asyncio.run(run())
