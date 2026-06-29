"""Buscador web via DuckDuckGo HTML (sin API, sin key, sin signup).

Hace GET a https://html.duckduckgo.com/html/ y parsea el HTML.
Devuelve los resultados como `SearchResult`.

Cero dependencias externas, zero costo.
Limitacion: si DuckDuckGo cambia el HTML, hay que ajustar el parser.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx


USER_AGENT = "Mozilla/5.0 (compatible; NexaaBot/0.1; +https://nexaa.local)"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_CACHE_TTL_HOURS = 12


class SearchError(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    description: str
    source: str = ""

    @property
    def domain(self) -> str:
        try:
            return urlparse(self.url).netloc.replace("www.", "")
        except Exception:
            return ""


_RESULTS_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.+?)</a>.*?'
    r'class="result__snippet"[^>]*>(.+?)</(?:a|div|span|td)',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


class DuckDuckGoSearcher:
    name = "duckduckgo"
    is_available = True

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
        self.cache_ttl = cache_ttl_hours * 3600
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _cache_key(self, query: str, count: int, region: str) -> str:
        raw = f"{query}|{count}|{region}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, query: str, count: int, region: str) -> Path:
        return self.cache_dir / f"{self._cache_key(query, count, region)}.json"

    def _read_cache(self, query: str, count: int, region: str) -> list[SearchResult] | None:
        path = self._cache_path(query, count, region)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) > self.cache_ttl:
                return None
            return [SearchResult(**r) for r in data.get("results", [])]
        except Exception:
            return None

    def _write_cache(self, query: str, count: int, region: str, results: list[SearchResult]) -> None:
        path = self._cache_path(query, count, region)
        path.write_text(
            json.dumps({
                "ts": time.time(),
                "query": query,
                "count": count,
                "region": region,
                "results": [
                    {"title": r.title, "url": r.url, "description": r.description, "source": r.source}
                    for r in results
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_real_url(href: str) -> str:
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/l/" in href or "uddg=" in href:
            try:
                parsed = urlparse(href)
                qs = parse_qs(parsed.query)
                if "uddg" in qs and qs["uddg"]:
                    return qs["uddg"][0]
            except Exception:
                return href
        return href

    def _parse_html(self, html: str, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        for m in _RESULTS_RE.finditer(html):
            href = m.group(1)
            real_url = self._extract_real_url(href)
            if not real_url or real_url.startswith("javascript:"):
                continue
            title = _TAG_RE.sub("", m.group(2)).strip()
            title = unescape(title).strip()
            snippet = _TAG_RE.sub("", m.group(3)).strip()
            snippet = unescape(snippet).strip()
            if not title or not real_url.startswith("http"):
                continue
            results.append(SearchResult(
                title=title[:200],
                url=real_url,
                description=snippet[:400],
                source=urlparse(real_url).netloc.replace("www.", ""),
            ))
            if len(results) >= count:
                break
        return results

    async def search(self, query: str, *, count: int = 3, region: str = "cl-es") -> list[SearchResult]:
        cached = self._read_cache(query, count, region)
        if cached is not None:
            return cached

        client = self._get_client()
        try:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": region, "kp": -2, "df": "d"},
            )

        except httpx.HTTPError as e:
            raise SearchError(f"ddg http error: {e}") from e

        if resp.status_code >= 500:
            raise SearchError(f"ddg server error {resp.status_code}")
        if resp.status_code >= 400:
            raise SearchError(f"ddg client error {resp.status_code}")
        if not resp.text or "<html" not in resp.text.lower():
            raise SearchError("ddg respuesta sin HTML")

        results = self._parse_html(resp.text, count)
        self._write_cache(query, count, region, results)
        return results
