"""Lector de feeds RSS para extraer contenido de noticias sin scraping.

Estrategia (en orden de prioridad):
1. RSS nativo del sitio  → <dominio>/feed/  o  <dominio>/rss.xml  (sin Cloudflare)
2. Google News RSS       → news.google.com/rss/search?q=<título>
3. Ninguno               → ScraperBlocked  (el caller decide qué hacer)

Las respuestas son compatibles con ScrapedContent para integrarse
transparentemente con el pipeline existente.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

import httpx

from .scraper import ScrapedContent, ScraperBlocked, ScraperUnreachable, ScraperError

# User-Agent de lector de feeds legítimo — permitido por prácticamente todos los sitios
RSS_USER_AGENT = (
    "Mozilla/5.0 (compatible; Feedfetcher-Google; +http://www.google.com/feedfetcher.html)"
)

# Rutas RSS típicas que probamos en orden
_RSS_CANDIDATES = ["/feed/", "/feed", "/rss.xml", "/rss", "/atom.xml", "/index.xml"]

DEFAULT_TIMEOUT_S = 12.0
DEFAULT_CACHE_TTL_HOURS = 2


# --------------------------------------------------------------------------- #
#  Helpers de parseo RSS/Atom                                                  #
# --------------------------------------------------------------------------- #

_NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
    "media":   "http://search.yahoo.com/mrss/",
    "atom":    "http://www.w3.org/2005/Atom",
}


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _find_image(item: ET.Element, channel: ET.Element) -> str:
    """Extrae la URL de imagen del item (og:image, media:thumbnail, enclosure)."""
    for tag in (
        "media:thumbnail",
        "media:content",
    ):
        ns, local = tag.split(":")
        el = item.find(f"{{{_NS[ns]}}}{local}")
        if el is not None:
            url = el.get("url", "")
            if url:
                return url

    # <enclosure type="image/...">
    enc = item.find("enclosure")
    if enc is not None and "image" in enc.get("type", ""):
        return enc.get("url", "")

    return ""


def _extract_item(item: ET.Element, site_name: str) -> Optional[dict]:
    """Parsea un <item> RSS y devuelve un dict con campos normalizados."""
    title_el = item.find("title")
    link_el  = item.find("link")
    desc_el  = item.find("description")
    date_el  = item.find("pubDate") or item.find(f"{{{_NS['dc']}}}date")
    author_el = item.find(f"{{{_NS['dc']}}}creator") or item.find("author")

    # Contenido completo si está disponible
    content_el = item.find(f"{{{_NS['content']}}}encoded")

    title  = _text(title_el)
    link   = _text(link_el)
    desc   = _text(desc_el)
    date   = _text(date_el)
    author = _text(author_el)

    # Preferir contenido completo sobre descripción
    raw_text = _text(content_el) if content_el is not None else desc

    # Limpiar HTML básico
    raw_text = re.sub(r"<[^>]+>", " ", raw_text)
    raw_text = re.sub(r"\s{2,}", " ", raw_text).strip()

    if not link:
        return None

    image_url = _find_image(item, item)  # pasa item dos veces, suficiente para este scope

    return {
        "title":        title,
        "url":          link,
        "main_text":    raw_text,
        "summary":      desc if raw_text != desc else "",
        "publish_date": date,
        "author":       author,
        "image_url":    image_url,
        "site_name":    site_name,
    }


# --------------------------------------------------------------------------- #
#  RSSReader                                                                   #
# --------------------------------------------------------------------------- #

class RSSReader:
    """Lee feeds RSS de un sitio y devuelve ScrapedContent sin depender del scraper."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                follow_redirects=True,
                headers={
                    "User-Agent": RSS_USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                    "Accept-Language": "es-CL,es;q=0.9",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------------------------------------------------------------------- #
    #  Caché                                                                   #
    # ---------------------------------------------------------------------- #

    def _cache_key(self, url: str) -> str:
        return "rss_" + hashlib.sha256(url.encode()).hexdigest()[:28]

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{self._cache_key(url)}.json"

    def _read_cache(self, url: str) -> ScrapedContent | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        try:
            ts = datetime.fromisoformat(data.get("fetched_at", ""))
        except ValueError:
            return None
        if datetime.now() - ts > self.cache_ttl:
            return None
        return _dict_to_scraped(data, from_cache=True)

    def _write_cache(self, url: str, content: ScrapedContent) -> None:
        path = self._cache_path(url)
        from dataclasses import asdict
        snapshot = asdict(content)
        snapshot["from_cache"] = False
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------------- #
    #  API pública                                                             #
    # ---------------------------------------------------------------------- #

    async def fetch_by_url(self, article_url: str, *, force: bool = False) -> ScrapedContent:
        """Intenta obtener el contenido de article_url vía el RSS del mismo dominio.

        Flujo:
        1. Busca el feed RSS del dominio (prueba rutas comunes).
        2. Busca en los items del feed la URL exacta.
        3. Si no la encuentra, toma el primer item del feed como referencia
           de la noticia más reciente (fallback útil cuando el link de Google
           News apunta al artículo pero no coincide exactamente).
        4. Si ningún feed del dominio responde, lanza ScraperBlocked para
           que el llamador decida si usa scraping normal.
        5. Si el RSS no trae imagen, hace un GET rápido al HTML para extraer og:image.
        """
        if not force:
            cached = self._read_cache(article_url)
            if cached is not None:
                # Si el caché no tiene imagen, intentar obtenerla ahora
                if not cached.image_url:
                    client = self._get_client()
                    cached.image_url = await _fetch_og_image(article_url, client)
                    if cached.image_url:
                        self._write_cache(article_url, cached)
                return cached

        parsed = urlparse(article_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        site_name = parsed.netloc.replace("www.", "")

        client = self._get_client()

        # Intentar rutas de feed del dominio
        feed_xml: str | None = None
        feed_url_used: str | None = None
        for candidate in _RSS_CANDIDATES:
            try:
                resp = await client.get(base + candidate, timeout=8.0)
                if resp.status_code == 200 and _looks_like_feed(resp.text):
                    feed_xml = resp.text
                    feed_url_used = base + candidate
                    break
            except Exception:
                continue

        if feed_xml is None:
            raise ScraperBlocked(
                f"No se encontró feed RSS accesible en {base}. "
                "El sitio puede requerir scraping directo."
            )

        content = _find_in_feed(feed_xml, article_url, site_name)
        if content is None:
            raise ScraperUnreachable(
                f"Feed encontrado en {feed_url_used} pero no contiene el artículo {article_url}"
            )

        # Si el RSS no trajo imagen, intentar extraerla del HTML del artículo
        if not content.image_url:
            content.image_url = await _fetch_og_image(article_url, client)

        content.fetched_at = datetime.now().isoformat(timespec="seconds")
        self._write_cache(article_url, content)
        return content

    async def fetch_latest(self, feed_url: str, *, count: int = 10) -> list[ScrapedContent]:
        """Descarga un feed RSS y devuelve los últimos N artículos."""
        client = self._get_client()
        try:
            resp = await client.get(feed_url)
        except httpx.HTTPError as e:
            raise ScraperUnreachable(f"Error al obtener feed {feed_url}: {e}") from e
        if resp.status_code >= 400:
            raise ScraperUnreachable(f"HTTP {resp.status_code} al obtener {feed_url}")

        site_name = urlparse(feed_url).netloc.replace("www.", "")
        items = _parse_feed(resp.text, site_name)
        results = []
        for item in items[:count]:
            sc = _item_to_scraped(item)
            sc.fetched_at = datetime.now().isoformat(timespec="seconds")
            results.append(sc)
        return results

    async def google_news_rss(
        self,
        query: str,
        *,
        count: int = 5,
        region: str = "CL",
        lang: str = "es-419",
    ) -> list[ScrapedContent]:
        """Busca en Google News RSS y devuelve artículos como ScrapedContent."""
        url = (
            f"https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl={lang}&gl={region}&ceid={region}:{lang}"
        )
        client = self._get_client()
        try:
            resp = await client.get(url)
        except httpx.HTTPError as e:
            raise ScraperUnreachable(f"Error Google News RSS: {e}") from e
        if resp.status_code >= 400:
            raise ScraperUnreachable(f"Google News RSS HTTP {resp.status_code}")

        items = _parse_feed(resp.text, "Google News")
        results = []
        for item in items[:count]:
            sc = _item_to_scraped(item)
            sc.fetched_at = datetime.now().isoformat(timespec="seconds")
            results.append(sc)
        return results


# --------------------------------------------------------------------------- #
#  Helpers internos                                                             #
# --------------------------------------------------------------------------- #

def _looks_like_feed(text: str) -> bool:
    """Heurística rápida para saber si la respuesta es un feed XML."""
    snippet = text[:500].lower()
    return "<rss" in snippet or "<feed" in snippet or "<channel" in snippet


def _parse_feed(xml_text: str, site_name: str) -> list[dict]:
    """Parsea RSS/Atom y devuelve lista de dicts normalizados."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = root.findall(".//item")  # RSS
    if not items:
        items = root.findall(f".//{{{_NS['atom']}}}entry")  # Atom

    result = []
    for item in items:
        parsed = _extract_item(item, site_name)
        if parsed:
            result.append(parsed)
    return result


def _find_in_feed(xml_text: str, target_url: str, site_name: str) -> ScrapedContent | None:
    """Busca en el feed el item cuya URL coincida con target_url.
    Si no coincide exactamente, devuelve el primer item (el más reciente).
    """
    items = _parse_feed(xml_text, site_name)
    if not items:
        return None

    # Coincidencia exacta
    for item in items:
        if item.get("url", "") == target_url:
            return _item_to_scraped(item)

    # Si la URL objetivo está en el path de algún item (coincidencia parcial)
    target_path = urlparse(target_url).path.rstrip("/")
    for item in items:
        item_path = urlparse(item.get("url", "")).path.rstrip("/")
        if target_path and item_path and target_path == item_path:
            return _item_to_scraped(item)

    # Devolver el más reciente como mejor aproximación
    return _item_to_scraped(items[0])


def _item_to_scraped(item: dict) -> ScrapedContent:
    return ScrapedContent(
        url=item.get("url", ""),
        canonical_url=item.get("url", ""),
        site_name=item.get("site_name", ""),
        title=item.get("title", ""),
        author=item.get("author", ""),
        publish_date=item.get("publish_date", ""),
        main_text=item.get("main_text", ""),
        summary=item.get("summary", ""),
        language="es",
        image_url=item.get("image_url", ""),
        fetched_at="",
        from_cache=False,
        extraction_warnings=["contenido obtenido vía RSS (puede ser extracto)"]
        if len(item.get("main_text", "")) < 300
        else [],
    )


def _dict_to_scraped(data: dict, *, from_cache: bool = False) -> ScrapedContent:
    return ScrapedContent(
        url=data.get("url", ""),
        canonical_url=data.get("canonical_url", ""),
        site_name=data.get("site_name", ""),
        title=data.get("title", ""),
        author=data.get("author", ""),
        publish_date=data.get("publish_date", ""),
        main_text=data.get("main_text", ""),
        summary=data.get("summary", ""),
        language=data.get("language", "es"),
        image_url=data.get("image_url", ""),
        fetched_at=data.get("fetched_at", ""),
        from_cache=from_cache,
        extraction_warnings=data.get("extraction_warnings", []),
    )


async def _fetch_og_image(url: str, client: httpx.AsyncClient) -> str:
    """Hace un GET al HTML del artículo y extrae og:image / twitter:image.

    Devuelve la URL de la imagen o cadena vacía si no se encuentra.
    Nunca lanza excepciones — si falla, devuelve ''.
    """
    try:
        resp = await client.get(url, timeout=8.0)
        if resp.status_code >= 400:
            return ""
        html = resp.text

        # Regex que tolera cualquier orden de atributos en el tag <meta>
        tag_re = re.compile(r"<meta\b([^>]+)>", re.IGNORECASE | re.DOTALL)
        content_re = re.compile(r'content=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)

        for prop in ("og:image", "twitter:image", "twitter:image:src"):
            prop_re = re.compile(
                r'(?:property|name)=[\"\']' + re.escape(prop) + r'[\"\']',
                re.IGNORECASE,
            )
            for m in tag_re.finditer(html):
                attrs = m.group(1)
                if prop_re.search(attrs):
                    cm = content_re.search(attrs)
                    if cm:
                        from urllib.parse import urljoin
                        return urljoin(url, cm.group(1).strip())
    except Exception:
        pass
    return ""

