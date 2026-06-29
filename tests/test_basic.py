"""Tests básicos sin red. Verifican pipeline end-to-end con template local."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexaa.editorial.core import (
    EditorialStyle,
    FactInput,
    build_system_prompt,
    parse_sections,
)
from nexaa.engine.engine import NewsEngine
from nexaa.providers.base import (
    ProviderError,
)
from nexaa.providers.local_template import LocalTemplateProvider
from nexaa.quality.checker import check_output
from nexaa.quality.verifier import verify_fact
from nexaa.router.circuit_breaker import CircuitBreaker
from nexaa.router.metrics import MetricsLogger
from nexaa.router.router import AIRouter


def test_fact_verifier_accepts_valid():
    fact = FactInput(
        fact_id="t1",
        categoria="Educación",
        ciudad="Chillán",
        region="Región de Ñuble",
        fecha="2026-06-12",
        titulo_corto="Título de prueba suficientemente largo",
        que_paso="Ocurrió algo verificado con al menos veinte caracteres de detalle.",
        por_que_importa="Es importante para la comunidad local.",
    )
    r = verify_fact(fact)
    assert r.ok, r


def test_fact_verifier_rejects_missing_critical():
    fact = FactInput(
        fact_id="",
        categoria="",
        ciudad="",
        region="Metropolitana",
        fecha="",
        titulo_corto="corto",
        que_paso="no",
        por_que_importa="",
    )
    r = verify_fact(fact)
    assert not r.ok
    assert "fact_id" in r.missing_critical
    assert "categoría" in r.missing_critical
    assert "region (debe incluir Ñuble)" in r.missing_critical


def test_sections_parser_extracts_all():
    text = (
        "Categoría: Educación\n"
        "Ciudad/Región: Chillán, Región de Ñuble\n"
        "Titular: Algún titular informativo\n\n"
        "Desarrollo:\nLínea 1\nLínea 2\n\n"
        "Contexto:\nFondo histórico breve.\n\n"
        "Impacto:\nBeneficia a la comunidad.\n\n"
        "Cierre:\nReflexión final."
    )
    s = parse_sections(text)
    assert s["Categoría"] == "Educación"
    assert s["Desarrollo"] == "Línea 1\nLínea 2"
    assert s["Cierre"] == "Reflexión final."


def test_system_prompt_mentions_region():
    style = EditorialStyle.default()
    sp = build_system_prompt(style)
    assert "Ñuble" in sp
    for sec in ("Categoría", "Titular", "Desarrollo", "Contexto", "Impacto", "Cierre"):
        assert sec in sp


def test_checker_flags_missing_sections():
    text = "Categoría: X\nTitular: algo\n"
    cfg = {"quality": {"min_desarrollo_chars": 100}}
    r = check_output(text, cfg)
    assert not r.ok
    assert any("Desarrollo" in i for i in r.issues)


def test_checker_detects_forbidden_word():
    text = (
        "Categoría: X\nCiudad/Región: Chillán, Región de Ñuble\n"
        "Titular: Increíble noticia\n"
        "Desarrollo: " + ("palabra " * 100) + "\n"
        "Contexto: " + ("contexto " * 30) + "\n"
        "Impacto: " + ("impacto " * 30) + "\n"
        "Cierre: cierre breve."
    )
    cfg = {"quality": {"forbidden_words": ["increíble"]}}
    r = check_output(text, cfg)
    assert any("prohibida" in i for i in r.issues)


def test_checker_marks_uncertainty():
    text = (
        "Categoría: X\nCiudad/Región: Chillán, Región de Ñuble\n"
        "Titular: Hecho en seguimiento\n"
        "Desarrollo: " + ("detalle " * 100) + "[DATO NO CONFIRMADO - REQUIERE REVISIÓN] más texto.\n"
        "Contexto: " + ("fondo " * 30) + "\n"
        "Impacto: " + ("efecto " * 30) + "\n"
        "Cierre: fin."
    )
    r = check_output(text, {"quality": {}})
    assert r.needs_human_review
    assert r.uncertainty_count == 1


def test_checker_dynamic_region():
    text_bad = (
        "Categoría: X\nCiudad/Región: Santiago, Región Metropolitana\n"
        "Titular: Hecho de prueba\n"
        "Desarrollo: " + ("detalle " * 100) + "\n"
        "Contexto: " + ("fondo " * 30) + "\n"
        "Impacto: " + ("efecto " * 30) + "\n"
        "Cierre: fin."
    )
    r_bad = check_output(text_bad, {"region": "Región de Ñuble, Chile"})
    assert any("no menciona explícitamente Ñuble ni Chile" in w for w in r_bad.warnings)

    r_good = check_output(text_bad, {"region": "Región Metropolitana, Chile"})
    assert not any("no menciona explícitamente" in w for w in r_good.warnings)


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    assert cb.allow("x")
    cb.record_failure("x", "err1")
    cb.record_failure("x", "err2")
    assert not cb.allow("x")
    assert cb.snapshot()["x"]["state"] == "open"


def test_local_template_generates_draft():
    async def run():
        prov = LocalTemplateProvider()
        fact = FactInput(
            fact_id="t1",
            categoria="Educación",
            ciudad="Chillán",
            region="Región de Ñuble",
            fecha="2026-06-12",
            titulo_corto="Título referencial del hecho",
            que_paso="Detalle extenso del hecho con más de veinte caracteres.",
            por_que_importa="Por qué importa.",
        )
        text = await prov.generate("", fact.to_prompt())
        assert "BORRADOR" in text
        assert "Categoría" in text
        assert "Ñuble" in text
    asyncio.run(run())


def test_router_falls_back_to_local_when_all_fail(monkeypatch, tmp_path):
    async def run():
        from nexaa.providers.base import ProviderError, ProviderAuthError

        class FakeFailing:
            name = "openai"
            is_available = True
            async def generate(self, *a, **kw):
                raise ProviderError("boom")

        class FakeUnavailable:
            name = "gemini"
            is_available = False
            async def generate(self, *a, **kw):
                raise ProviderAuthError("no key")

        providers = {
            "openai": FakeFailing(),
            "gemini": FakeUnavailable(),
            "claude": FakeUnavailable(),
            "local_template": LocalTemplateProvider(),
        }
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
        metrics = MetricsLogger(tmp_path / "m.jsonl")
        router = AIRouter(
            providers=providers,
            order=["openai", "gemini", "claude"],
            breaker=cb,
            metrics=metrics,
            primary_timeout_s=1,
            fallback_timeout_s=1,
            global_budget_s=3,
            max_retries=1,
            fallback_enabled=True,
        )
        r = await router.generate("sys", "ID del hecho: t1\nCategoría asignada: X\nCiudad: Chillán\nRegión: Región de Ñuble\nFecha del hecho: 2026-06-12\nTítulo referencial: hola mundo test\n- Qué ocurrió: detalle extenso de más de veinte caracteres.\n- Por qué importa: por algo.\n")
        assert r is not None
        assert r.provider == "local_template"
        assert r.is_draft
    asyncio.run(run())


def test_engine_end_to_end_with_local_template(config, clean_data_dir):
    async def run():
        engine = NewsEngine(config, base_path=ROOT)
        result = await engine.generate_from_fact("nb-2026-001")
        assert result.ok
        assert result.provider == "local_template"
        assert result.is_draft
        assert result.pending_path is not None
        assert result.pending_path.exists()
    asyncio.run(run())
