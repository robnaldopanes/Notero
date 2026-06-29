"""Scraper responsable de artículos externos.

Funcionalidades:
- HTTP GET con timeout y User-Agent identificable.
- Consulta robots.txt antes de descargar (si está bloqueado, lanza ScraperBlocked).
- Extrae el contenido principal con trafilatura (no copia HTML crudo).
- Cache en disco por URL con TTL configurable.
- Devuelve un ScrapedContent con metadatos: título, autor, fecha, sitio, texto limpio.

NO se hace cargo de resúmenes ni reescritura — eso lo hace el motor.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura


# User-Agent de navegador real para evitar bloqueos Cloudflare en sitios sin RSS.
# El RSS Reader tiene su propio UA de feed-fetcher; este se usa solo como último recurso.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_CACHE_TTL_HOURS = 6


class ScraperError(Exception):
    pass


class ScraperBlocked(ScraperError):
    """robots.txt del sitio prohíbe el scraping para nuestro UA."""


class ScraperUnreachable(ScraperError):
    """No se pudo descargar el recurso (timeout, 4xx, 5xx, DNS, etc.)."""


@dataclass
class ScrapedContent:
    url: str
    canonical_url: str = ""
    site_name: str = ""
    title: str = ""
    author: str = ""
    publish_date: str = ""
    main_text: str = ""
    summary: str = ""
    language: str = ""
    image_url: str = ""
    fetched_at: str = ""
    from_cache: bool = False
    extraction_warnings: list[str] = field(default_factory=list)


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


async def resolve_google_news_url(url: str, client: httpx.AsyncClient) -> str:
    if "news.google.com/rss/articles/" not in url and "news.google.com/articles/" not in url:
        return url
    try:
        import html
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        }, follow_redirects=True)
        if resp.status_code != 200:
            return url

        match = re.search(r'<c-wiz[^>]+data-p="([^"]+)"', resp.text)
        if not match:
            return url

        data_p = html.unescape(match.group(1))
        data_p_replaced = data_p.replace('%.@.', '["garturlreq",')
        obj = json.loads(data_p_replaced)

        payload_data = obj[:-6] + obj[-2:]
        payload = {
            'f.req': json.dumps([[['Fbv4je', json.dumps(payload_data), 'null', 'generic']]])
        }

        api_url = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
        api_headers = {
            'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        }

        api_resp = await client.post(api_url, headers=api_headers, data=payload)
        if api_resp.status_code != 200:
            return url

        raw_text = api_resp.text.replace(")]}'\n", "").strip()
        json_data = json.loads(raw_text)
        array_string = json_data[0][2]
        final_url = json.loads(array_string)[1]
        return final_url
    except Exception:
        return url


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    if not _URL_RE.match(url):
        raise ScraperError("URL inválida (debe empezar con http:// o https://)")
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ScraperError("URL sin host")
    return url



def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


async def _robots_allowed(url: str, user_agent: str, client: httpx.AsyncClient) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = await client.get(robots_url, timeout=5.0)
    except httpx.HTTPError:
        return True
    if resp.status_code >= 400:
        return True
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(user_agent, url)


class Scraper:
    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str = USER_AGENT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
        respect_robots: bool = True,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.respect_robots = respect_robots
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                follow_redirects=True,
                headers={"User-Agent": self.user_agent, "Accept-Language": "es-CL,es;q=0.9,*;q=0.5"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, url: str, *, force: bool = False) -> ScrapedContent:
        url = _validate_url(url)
        client = self._get_client()

        if "news.google.com/rss/articles/" in url or "news.google.com/articles/" in url:
            try:
                resolved = await resolve_google_news_url(url, client)
                url = _validate_url(resolved)
            except Exception:
                pass

        if not force:
            cached = self._read_cache(url)
            if cached is not None:
                cached.from_cache = True
                # Si el caché no tiene imagen, intentar extraerla del HTML ahora
                if not cached.image_url:
                    try:
                        resp = await self._get_client().get(url, timeout=8.0)
                        if resp.status_code < 400:
                            cached.image_url = self._extract_og_image(resp.text, url)
                            if cached.image_url:
                                self._write_cache(url, cached)
                    except Exception:
                        pass
                return cached


        client = self._get_client()

        if self.respect_robots and not await _robots_allowed(url, self.user_agent, client):
            raise ScraperBlocked(f"robots.txt bloquea scraping de {url}")

        try:
            resp = await client.get(url)
        except httpx.HTTPError as e:
            raise ScraperUnreachable(f"error HTTP: {e}") from e

        if resp.status_code >= 400:
            raise ScraperUnreachable(f"HTTP {resp.status_code} al obtener {url}")

        html = resp.text
        content = self._extract(html, url, resp)
        content.fetched_at = datetime.now().isoformat(timespec="seconds")
        self._write_cache(url, content)
        return content

    def _extract(self, html: str, url: str, resp: httpx.Response) -> ScrapedContent:
        warnings: list[str] = []

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            include_images=False,
            favor_recall=True,
            with_metadata=True,
            output_format="json",
        ) or ""

        if extracted:
            try:
                meta = json.loads(extracted)
            except json.JSONDecodeError:
                meta = {}
        else:
            meta = {}

        title = (meta.get("title") or "").strip()
        author = (meta.get("author") or "").strip()
        date = (meta.get("date") or "").strip()
        sitename = (meta.get("sitename") or "").strip()
        description = (meta.get("description") or "").strip()
        text = (meta.get("raw_text") or meta.get("text") or "").strip()
        language = (meta.get("language") or "").strip()

        if not title:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = re.sub(r"\s+", " ", title_match.group(1)).strip()
                warnings.append("título extraído de <title>, no de metadatos")
        if not title:
            warnings.append("no se pudo extraer el título")
            title = url

        if not text:
            text_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)', html, re.IGNORECASE)
            if text_match:
                text = text_match.group(1).strip()
                warnings.append("solo se extrajo la metadescripción; no se encontró cuerpo del artículo")
            else:
                text = ""
                warnings.append("no se pudo extraer el cuerpo del artículo")

        if not sitename:
            parsed = urlparse(url)
            sitename = parsed.netloc

        canonical = ""
        canon_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', html, re.IGNORECASE)
        if canon_match:
            canonical = urljoin(url, canon_match.group(1).strip())
        else:
            canonical = url

        image_url = self._extract_og_image(html, url)

        if not date:
            og_match = re.search(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE)
            if og_match:
                date = og_match.group(1).strip()
                warnings.append("fecha extraída de OpenGraph, no del JSON-LD")
        if not date:
            warnings.append("sin fecha de publicación detectable")

        if len(text) < 200:
            warnings.append(f"texto extraído muy corto ({len(text)} chars)")

        return ScrapedContent(
            url=url,
            canonical_url=canonical,
            site_name=sitename,
            title=title,
            author=author,
            publish_date=date,
            main_text=text,
            summary=description,
            language=language,
            image_url=image_url,
            fetched_at="",
            from_cache=False,
            extraction_warnings=warnings,
        )

    def _extract_og_image(self, html: str, url: str) -> str:
        """Extrae og:image / twitter:image del HTML tolerando cualquier orden de atributos."""
        tag_re = re.compile(r"<meta\b([^>]+)>", re.IGNORECASE | re.DOTALL)
        attr_content_re = re.compile(r'content=["\']([^"\']+)["\']', re.IGNORECASE)
        for prop in ("og:image", "twitter:image", "twitter:image:src"):
            attr_prop_re = re.compile(
                r'(?:property|name)=["\']' + re.escape(prop) + r'["\']',
                re.IGNORECASE,
            )
            for m in tag_re.finditer(html):
                if attr_prop_re.search(m.group(1)):
                    cm = attr_content_re.search(m.group(1))
                    if cm:
                        return urljoin(url, cm.group(1).strip())
        return ""

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{_cache_key(url)}.json"

    def _read_cache(self, url: str) -> ScrapedContent | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        fetched_at = data.get("fetched_at", "")
        try:
            ts = datetime.fromisoformat(fetched_at)
        except ValueError:
            return None
        if datetime.now() - ts > self.cache_ttl:
            return None
        return ScrapedContent(
            url=data["url"],
            canonical_url=data.get("canonical_url", ""),
            site_name=data.get("site_name", ""),
            title=data.get("title", ""),
            author=data.get("author", ""),
            publish_date=data.get("publish_date", ""),
            main_text=data.get("main_text", ""),
            summary=data.get("summary", ""),
            language=data.get("language", ""),
            image_url=data.get("image_url", ""),
            fetched_at=fetched_at,
            from_cache=False,
            extraction_warnings=list(data.get("extraction_warnings", [])),
        )

    def _write_cache(self, url: str, content: ScrapedContent) -> None:
        path = self._cache_path(url)
        snapshot = asdict(content)
        snapshot["from_cache"] = False
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
