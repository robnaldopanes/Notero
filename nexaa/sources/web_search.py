"""Buscador web usando Brave Search API.

Free tier: 2000 queries/mes en https://brave.com/search/api/
Signup con email, sin tarjeta. La key se entrega inmediatamente.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx


USER_AGENT = "NexaaBot/0.1 (+https://nexaa.local)"
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
        from urllib.parse import urlparse
        try:
            return urlparse(self.url).netloc.replace("www.", "")
        except Exception:
            return ""


class BraveSearcher:
    def __init__(
        self,
        api_key: str | None,
        cache_dir: Path,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
    ):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.cache_ttl = cache_ttl_hours * 3600
        self._client: Optional[httpx.AsyncClient] = None
        self.is_available = bool(api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _cache_key(self, query: str, count: int) -> str:
        raw = f"{query}|{count}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, query: str, count: int) -> Path:
        return self.cache_dir / f"{self._cache_key(query, count)}.json"

    def _read_cache(self, query: str, count: int) -> list[SearchResult] | None:
        path = self._cache_path(query, count)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("ts", 0) > self.cache_ttl:
                return None
            return [SearchResult(**r) for r in data.get("results", [])]
        except Exception:
            return None

    def _write_cache(self, query: str, count: int, results: list[SearchResult]) -> None:
        path = self._cache_path(query, count)
        path.write_text(
            json.dumps({
                "ts": time.time(),
                "query": query,
                "count": count,
                "results": [
                    {"title": r.title, "url": r.url, "description": r.description, "source": r.source}
                    for r in results
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def search(self, query: str, *, count: int = 3, country: str = "cl") -> list[SearchResult]:
        if not self.is_available:
            return []
        cached = self._read_cache(query, count)
        if cached is not None:
            return cached

        client = self._get_client()
        try:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count, "country": country.upper(), "safesearch": "moderate", "freshness": "pd"},
                headers={"X-Subscription-Token": self.api_key},
            )

        except httpx.HTTPError as e:
            raise SearchError(f"brave http error: {e}") from e

        if resp.status_code == 429:
            raise SearchError("brave rate limit 429")
        if resp.status_code >= 500:
            raise SearchError(f"brave server error {resp.status_code}")
        if resp.status_code >= 400:
            raise SearchError(f"brave client error {resp.status_code}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise SearchError(f"brave respuesta inválida: {e}") from e

        results: list[SearchResult] = []
        for r in (data.get("web") or {}).get("results", [])[:count]:
            results.append(SearchResult(
                title=(r.get("title") or "").strip(),
                url=(r.get("url") or "").strip(),
                description=(r.get("description") or "").strip(),
                source=(r.get("profile") or {}).get("name", ""),
            ))

        self._write_cache(query, count, results)
        return results
