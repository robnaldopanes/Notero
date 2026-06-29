"""Tests del scraper y de la conversión a FactInput.

No hacemos red en estos tests: usamos un HTML fijo y un transporte httpx
monkey-patched para simular respuestas.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexaa.sources.scraper import (
    Scraper,
    ScraperBlocked,
    ScraperError,
    ScraperUnreachable,
    _validate_url,
)
from nexaa.sources.scraper_to_fact import (
    NUBLE_CITIES,
    _detect_categoria,
    _detect_city,
    _detect_date,
    scraped_to_fact,
)
from nexaa.sources.scraper import ScrapedContent


SAMPLE_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <title>Liceo de Chillán abre laboratorio de ciencias</title>
  <meta name="description" content="El liceo Bicentenario abrió un nuevo laboratorio.">
  <meta property="article:published_time" content="2026-06-12T10:30:00">
  <meta name="author" content="Juan Pérez">
  <link rel="canonical" href="https://www.diarioconce.cl/2026/laboratorio">
</head>
<body>
  <article>
    <h1>Liceo de Chillán abre laboratorio de ciencias</h1>
    <p>El Liceo Bicentenario República de Chile de Chillán abrió un nuevo laboratorio de ciencias
    con capacidad para 30 estudiantes por jornada, luego de 18 meses de obras financiadas por
    el Ministerio de Educación. La inversión declarada por la seremía regional fue de 420
    millones de pesos.</p>
    <p>El nuevo espacio cuenta con equipamiento para química, física y biología, y permitirá
    descomprimir la demanda de实验 práctica que hoy se cubre parcialmente en otras
    dependencias del establecimiento. Alrededor de 1.200 estudiantes accederán a clases
    prácticas en condiciones adecuadas.</p>
    <p>La directora del establecimiento señaló que se trata de "un paso histórico" para la
    comunidad educativa local. Autoridades regionales presentes en la inauguración confirmaron
    que el modelo de inversión podría replicarse en otros liceos públicos de la región.</p>
  </article>
</body>
</html>
"""


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, html: str = SAMPLE_HTML, robots_allowed: bool = True):
        self.html = html
        self.robots_allowed = robots_allowed
        self.calls: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            if self.robots_allowed:
                body = "User-agent: *\nDisallow:"
            else:
                body = "User-agent: *\nDisallow: /"
            return httpx.Response(200, text=body)
        return httpx.Response(200, text=self.html, headers={"content-type": "text/html"})


@pytest.fixture
def scraper(tmp_path):
    return Scraper(cache_dir=tmp_path, timeout_s=5, respect_robots=True)


def test_validate_url_rejects_bad():
    with pytest.raises(ScraperError):
        _validate_url("")
    with pytest.raises(ScraperError):
        _validate_url("not-a-url")
    assert _validate_url("  https://example.com  ") == "https://example.com"


def test_scraper_fetches_and_extracts(scraper):
    async def run():
        transport = _FakeTransport()
        scraper._client = httpx.AsyncClient(
            transport=transport, follow_redirects=True,
            headers={"User-Agent": scraper.user_agent},
        )
        content = await scraper.fetch("https://www.diarioconce.cl/2026/laboratorio")
        assert content.title.startswith("Liceo de Chillán")
        assert "laboratorio" in content.main_text.lower()
        assert content.canonical_url == "https://www.diarioconce.cl/2026/laboratorio"
        assert content.author == "Juan Pérez"
        assert content.publish_date.startswith("2026-06-12")
        assert "diarioconce.cl" in content.site_name
        assert not content.from_cache
        assert any("robots.txt" in u for u in transport.calls)
    asyncio.run(run())


def test_scraper_uses_cache(tmp_path):
    async def run():
        transport = _FakeTransport()
        s = Scraper(cache_dir=tmp_path, cache_ttl_hours=1)
        s._client = httpx.AsyncClient(
            transport=transport, follow_redirects=True,
            headers={"User-Agent": s.user_agent},
        )
        c1 = await s.fetch("https://www.diarioconce.cl/x")
        assert not c1.from_cache
        c2 = await s.fetch("https://www.diarioconce.cl/x")
        assert c2.from_cache
        assert c2.title == c1.title
    asyncio.run(run())


def test_scraper_respects_robots_disallow(tmp_path):
    async def run():
        transport = _FakeTransport(robots_allowed=False)
        s = Scraper(cache_dir=tmp_path, respect_robots=True)
        s._client = httpx.AsyncClient(
            transport=transport, follow_redirects=True,
            headers={"User-Agent": s.user_agent},
        )
        with pytest.raises(ScraperBlocked):
            await s.fetch("https://www.diarioconce.cl/x")
    asyncio.run(run())


def test_scraper_unreachable_on_404(tmp_path):
    class T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(404, text="not found")
    async def run():
        s = Scraper(cache_dir=tmp_path)
        s._client = httpx.AsyncClient(transport=T(), follow_redirects=True)
        with pytest.raises(ScraperUnreachable):
            await s.fetch("https://example.com/x")
    asyncio.run(run())


def test_scraper_handles_garbage_html(tmp_path):
    async def run():
        s = Scraper(cache_dir=tmp_path)
        s._client = httpx.AsyncClient(
            transport=_FakeTransport(html="<html><body>nada útil</body></html>"),
            follow_redirects=True,
        )
        c = await s.fetch("https://example.com/empty")
        assert c.main_text or c.extraction_warnings
        assert c.extraction_warnings
    asyncio.run(run())


def test_detect_city():
    assert _detect_city("Ocurrió en Chillán") == "Chillán"
    assert _detect_city("San Carlos recibe fondos") == "San Carlos"
    assert _detect_city("Sin referencia") == "Chillán"


def test_detect_categoria():
    assert _detect_categoria("Hospital de Chillán abrió nuevas camas") == "Salud"
    assert _detect_categoria("Liceo abrió laboratorio") == "Educación"
    assert _detect_categoria("Carabineros detuvo a sospechoso") == "Seguridad"
    assert _detect_categoria("") == ""


def test_detect_date():
    assert _detect_date(ScrapedContent(url="x", publish_date="2026-06-12")) == "2026-06-12"
    assert _detect_date(ScrapedContent(url="x", publish_date="2026-06-12T10:30:00")) == "2026-06-12"
    assert _detect_date(ScrapedContent(url="x", publish_date="")) == "2026-06-12" or len(_detect_date(ScrapedContent(url="x", publish_date=""))) == 10


def test_scraped_to_fact_attribution():
    content = ScrapedContent(
        url="https://www.diarioconce.cl/2026/laboratorio",
        canonical_url="https://www.diarioconce.cl/2026/laboratorio",
        site_name="Diario Concepción",
        title="Liceo de Chillán abre laboratorio de ciencias",
        author="Juan Pérez",
        publish_date="2026-06-12",
        main_text="El Liceo Bicentenario de Chillán abrió un nuevo laboratorio con capacidad para 30 estudiantes.",
        summary="Apertura del nuevo laboratorio.",
    )
    fact = scraped_to_fact(content)
    assert fact.ciudad == "Chillán"
    assert fact.categoria == "Educación"
    assert fact.source_url == content.canonical_url
    assert fact.source_site == "Diario Concepción"
    assert fact.fuentes == (content.canonical_url,)
    assert fact.author == "Juan Pérez"
    assert fact.fact_id.startswith("src-")
    prompt = fact.to_prompt()
    assert "PROPIA DE NEXAA" in prompt or "propia de Nexaa" in prompt.lower()
    assert "Diario Concepción" in prompt
    assert "MEJORAR" in prompt.upper() or "MEJOR" in prompt.upper()


def test_nuble_cities_includes_chillan():
    assert "Chillán" in NUBLE_CITIES
    assert "San Carlos" in NUBLE_CITIES


def test_scraper_extracts_og_image(scraper):
    async def run():
        html_with_image = """
        <!DOCTYPE html>
        <html>
        <head>
          <title>Test Image</title>
          <meta property="og:image" content="https://example.com/assets/img.jpg">
        </head>
        <body>
          <p>Cuerpo del artículo con suficiente longitud para que trafilatura no lance warnings por ser muy corto.</p>
        </body>
        </html>
        """
        transport = _FakeTransport(html=html_with_image)
        scraper._client = httpx.AsyncClient(transport=transport)
        content = await scraper.fetch("https://example.com/noticia")
        assert content.image_url == "https://example.com/assets/img.jpg"
    asyncio.run(run())
