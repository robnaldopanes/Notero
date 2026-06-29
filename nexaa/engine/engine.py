"""NewsEngine: orquesta verificación, router, checker y approval queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import os

import asyncio
import sys as _sys


def _safe_print(*args, **kwargs) -> None:
    """print() seguro en Windows: evita OSError con emojis en la consola."""
    kwargs.pop("flush", None)
    text = " ".join(str(a) for a in args) + kwargs.get("end", "\n")
    try:
        _sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        _sys.stdout.buffer.flush()
    except (AttributeError, OSError):
        safe = text.encode(_sys.stdout.encoding or "utf-8", errors="replace").decode(
            _sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe, end="", flush=True)


from .approval import ApprovalQueue
from ..editorial.core import EditorialStyle, FactInput, build_system_prompt
from ..providers.registry import build_providers
from ..quality.checker import QualityReport, check_output
from ..quality.verifier import verify_fact
from ..router.circuit_breaker import CircuitBreaker
from ..router.metrics import MetricsLogger
from ..router.router import AIRouter
from ..sources.fact_store import FactStore
from ..sources.scraper import USER_AGENT, Scraper, ScraperBlocked, ScraperError, ScraperUnreachable
from ..sources.scraper_to_fact import scraped_to_fact
from ..sources.rss_reader import RSSReader
from ..sources.duckduckgo_search import DuckDuckGoSearcher, SearchError
from ..sources.web_search import BraveSearcher, SearchResult, SearchError as BraveSearchError


@dataclass
class EngineResult:
    ok: bool
    reason: str
    pending_path: Path | None = None
    provider: str | None = None
    is_draft: bool = False
    quality: QualityReport | None = None
    verification: str = ""
    elapsed_ms: float = 0.0
    router_attempts: int = 0
    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    format_name: str = "nexaa_v1"
    source_url: str = ""
    source_site: str = ""
    image_url: str = ""


class NewsEngine:
    def __init__(self, config: Mapping, *, base_path: Path | None = None):
        self.config = dict(config)
        self.base_path = base_path or Path(".")

        paths = self.config.get("paths", {})
        self.fact_store = FactStore(self.base_path / paths.get("facts_dir", "data/facts"))
        self.approval_queue = ApprovalQueue(
            pending_dir=self.base_path / paths.get("pending_dir", "data/pending"),
            published_dir=self.base_path / paths.get("published_dir", "data/published"),
            rejected_dir=self.base_path / paths.get("rejected_dir", "data/rejected"),
        )

        logs_dir = self.base_path / paths.get("logs_dir", "data/logs")
        self.metrics = MetricsLogger(logs_dir / "router.jsonl")

        self.scraper = Scraper(
            cache_dir=self.base_path / paths.get("scraper_cache_dir", "data/scraper_cache"),
            user_agent=str(self.config.get("scraper", {}).get("user_agent", USER_AGENT)),
            timeout_s=float(self.config.get("scraper", {}).get("timeout_seconds", 15)),
            cache_ttl_hours=int(self.config.get("scraper", {}).get("cache_ttl_hours", 6)),
            respect_robots=bool(self.config.get("scraper", {}).get("respect_robots", True)),
        )

        self.rss_reader = RSSReader(
            cache_dir=self.base_path / paths.get("rss_cache_dir", "data/rss_cache"),
            timeout_s=float(self.config.get("scraper", {}).get("timeout_seconds", 15)),
            cache_ttl_hours=int(self.config.get("scraper", {}).get("cache_ttl_hours", 6)),
        )

        self.ddg_searcher = DuckDuckGoSearcher(
            cache_dir=self.base_path / paths.get("search_cache_dir", "data/search_cache"),
            timeout_s=float(self.config.get("web_search", {}).get("timeout_seconds", 10)),
            cache_ttl_hours=int(self.config.get("web_search", {}).get("cache_ttl_hours", 12)),
        )
        self.brave_searcher = BraveSearcher(
            api_key=os.getenv("BRAVE_API_KEY"),
            cache_dir=self.base_path / paths.get("search_cache_dir_brave", "data/search_cache_brave"),
            timeout_s=float(self.config.get("web_search", {}).get("timeout_seconds", 10)),
            cache_ttl_hours=int(self.config.get("web_search", {}).get("cache_ttl_hours", 12)),
        )

        cb_cfg = self.config.get("circuit_breaker", {})
        self.breaker = CircuitBreaker(
            failure_threshold=int(cb_cfg.get("failure_threshold", 3)),
            cooldown_seconds=float(cb_cfg.get("cooldown_seconds", 90)),
        )

        self.providers = build_providers(self.config)
        timeouts = self.config.get("timeouts", {})
        self.router = AIRouter(
            providers=self.providers,
            order=self.config.get("ia_order", ["openai", "gemini", "claude"]),
            breaker=self.breaker,
            metrics=self.metrics,
            primary_timeout_s=float(timeouts.get("primary_seconds", 8)),
            fallback_timeout_s=float(timeouts.get("fallback_seconds", 12)),
            global_budget_s=float(timeouts.get("global_budget_seconds", 30)),
            max_retries=int(self.config.get("max_retries", 2)),
            fallback_enabled=bool(self.config.get("fallback_enabled", True)),
        )

        region = self.config.get("region", "Región de Ñuble, Chile")
        self.style = EditorialStyle(
            name=str(self.config.get("editorial_style", "nexaa_v1")),
            region=region,
            language=str(self.config.get("default_language", "es-CL")),
        )

    def available_providers(self) -> list[str]:
        return [name for name, p in self.providers.items() if p.is_available]

    def breaker_snapshot(self) -> dict:
        return self.breaker.snapshot()

    def verify_fact(self, fact: FactInput) -> str:
        return str(verify_fact(fact))

    async def generate_from_fact(self, fact_id_or_path: str) -> EngineResult:
        fact = self.fact_store.load(fact_id_or_path)
        return await self.generate_from_fact_for(fact)

    def set_key(self, provider_name: str, api_key: str) -> bool:
        """Actualiza la API key de un proveedor en vivo (sin reiniciar).

        Devuelve True si el provider se activó correctamente.
        """
        from ..providers.registry import build_providers
        import os

        provider_key = f"{provider_name.upper()}_API_KEY"
        os.environ[provider_key] = api_key

        new_providers = build_providers(self.config, env=os.environ)
        if provider_name not in new_providers:
            return False

        new_p = new_providers[provider_name]
        if not new_p.is_available:
            return False

        self.providers[provider_name] = new_p
        self.router.providers[provider_name] = new_p
        return True

    async def scrape(self, url: str, *, force: bool = False):
        # 1. Intentar vía RSS del sitio (evita Cloudflare por completo)
        try:
            content = await self.rss_reader.fetch_by_url(url, force=force)
        except ScraperBlocked:
            # El sitio no tiene RSS accesible → intentar scraping directo
            try:
                content = await self.scraper.fetch(url, force=force)
            except ScraperBlocked as e:
                return {"error": "blocked", "detail": str(e)}
            except ScraperUnreachable as e:
                return {"error": "unreachable", "detail": str(e)}
            except ScraperError as e:
                return {"error": "scraper_error", "detail": str(e)}
        except ScraperUnreachable as e:
            return {"error": "unreachable", "detail": str(e)}
        except ScraperError as e:
            return {"error": "scraper_error", "detail": str(e)}

        fact = scraped_to_fact(content, region=self.style.region)
        return {
            "url": content.url,
            "canonical_url": content.canonical_url,
            "title": content.title,
            "author": content.author,
            "publish_date": content.publish_date,
            "site_name": content.site_name,
            "language": content.language,
            "main_text": content.main_text,
            "summary": content.summary,
            "from_cache": content.from_cache,
            "extraction_warnings": content.extraction_warnings,
            "suggested_categoria": fact.categoria,
            "suggested_ciudad": fact.ciudad,
            "suggested_fecha": fact.fecha,
            "suggested_image_url": fact.image_url,
        }

    async def generate_from_url(
        self,
        url: str,
        *,
        force: bool = False,
        format_name: str | None = None,
        expected_title: str = "",
    ) -> EngineResult:
        # 1. Intentar RSS nativo del sitio (sin Cloudflare)
        content = None
        rss_error: str = ""
        try:
            content = await self.rss_reader.fetch_by_url(url, force=force)
        except ScraperBlocked as e:
            rss_error = str(e)  # sin RSS → caer al scraper
        except Exception as e:
            rss_error = str(e)

        # 2. Fallback: scraper HTTP directo
        if content is None:
            try:
                content = await self.scraper.fetch(url, force=force)
            except ScraperBlocked as e:
                return EngineResult(
                    ok=False,
                    reason=f"Sitio bloqueado: no tiene RSS accesible y bloquea el scraping. {e}",
                )
            except ScraperUnreachable as e:
                return EngineResult(
                    ok=False,
                    reason=f"URL no accesible: {e}",
                )
            except ScraperError as e:
                return EngineResult(
                    ok=False,
                    reason=f"Error de scraping: {e}",
                )

        search_results: list[dict] = []
        topic = content.title or (content.main_text[:100] if content.main_text else "")

        from urllib.parse import urlparse
        source_url = content.canonical_url or content.url
        source_domain = ""
        try:
            source_domain = urlparse(source_url).netloc.replace("www.", "")
        except Exception:
            pass
        source_path = urlparse(source_url).path.rstrip("/")
        source_is_root = source_path in ("", "/", "")
        main_text_stripped = (content.main_text or "").strip()
        is_weak_source = (
            source_is_root
            or len(main_text_stripped) < 300
            or (content.title and source_domain and source_domain.split(".")[0] in content.title.lower())
        )
        if is_weak_source:
            return EngineResult(
                ok=False,
                reason=(
                    f"El URL parece ser la portada o índice de un sitio (no un artículo específico). "
                    f"Pegá la URL de un artículo concreto. Ej: {source_url}/2026/06/14/titulo-de-la-noticia/"
                ),
            )

        if expected_title:
            import re as _re
            expected_words = [
                w for w in _re.findall(r"\w{4,}", expected_title.lower())
                if w not in {"este", "esta", "para", "con", "los", "las", "del", "que", "una", "por", "sobre", "tras", "ante", "como", "pero", "sin", "tras"}
            ][:8]
            if expected_words:
                scraped_text_lower = (content.title + " " + (content.main_text or "")).lower()
                matched = sum(1 for w in expected_words if w in scraped_text_lower)
                if matched < 1:
                    return EngineResult(
                        ok=False,
                        reason=(
                            f"La URL no parece apuntar al artículo correcto "
                            f"(el contenido scrapeado no contiene ninguna palabra clave del título esperado). "
                            f"Probablemente la URL está truncada o rota. Copiá la URL completa desde el navegador. URL: {source_url}"
                        ),
                    )
        exclude_source = f" -site:{source_domain}" if source_domain else ""

        nuble_sites = [
            "biobiochile.cl", "cooperativa.cl", "diariochillan.cl",
            "nublenews.cl", "elchillaneitor.cl", "nublealdia.cl",
            "radionuble.cl", "latercera.com", "emol.com",
        ]
        nuble_sites_filter = " ".join(
            f'OR "site:{s}"' for s in nuble_sites if s != source_domain
        )

        search_queries = [
            f"{topic} Chile{exclude_source}",
            f"{topic} (\"site:biobiochile.cl\" \"site:cooperativa.cl\" \"site:diariochillan.cl\" \"site:nublenews.cl\" \"site:elchillaneitor.cl\" \"site:nublealdia.cl\" \"site:radionuble.cl\"){exclude_source}",
        ]

        MAX_RESULTS = 6
        seen_urls: set[str] = set()
        for q in search_queries:
            if len(search_results) >= MAX_RESULTS:
                break
            try:
                results = await self.ddg_searcher.search(q, count=4, region="cl-es")
                for r in results:
                    if r.url in seen_urls:
                        continue
                    if source_domain and source_domain in r.url:
                        continue
                    seen_urls.add(r.url)
                    search_results.append({
                        "title": r.title,
                        "url": r.url,
                        "description": r.description,
                    })
                    if len(search_results) >= MAX_RESULTS:
                        break
            except (SearchError, Exception):
                pass

        if self.brave_searcher.is_available:
            try:
                results = await self.brave_searcher.search(
                    f"{topic} Chile{exclude_source}", count=3, country="cl"
                )
                for r in results:
                    if r.url in seen_urls:
                        continue
                    if source_domain and source_domain in r.url:
                        continue
                    seen_urls.add(r.url)
                    search_results.append({
                        "title": r.title, "url": r.url, "description": r.description,
                    })
                    if len(search_results) >= MAX_RESULTS:
                        break
            except (BraveSearchError, Exception):
                pass

        # ── Scraping completo de fuentes adicionales (paralelo) ───────────────
        # Raspa el texto completo de las 3 primeras fuentes encontradas para
        # que la IA tenga material real con qué construir una noticia superior.
        # Cada fetch corre en paralelo con timeout individual de 9 segundos.
        if search_results:
            async def _fetch_source_text(src_url: str) -> str:
                try:
                    fetched = await asyncio.wait_for(
                        self.scraper.fetch(src_url, force=False),
                        timeout=9.0,
                    )
                    text = (fetched.main_text or "").strip()
                    # Limitar a 500 palabras para no inflar el prompt
                    words = text.split()
                    if len(words) > 500:
                        text = " ".join(words[:500]) + "…"
                    return text
                except Exception:
                    return ""

            top_sources = search_results[:3]
            fetched_texts = await asyncio.gather(
                *[_fetch_source_text(r["url"]) for r in top_sources],
                return_exceptions=True,
            )
            for i, ft in enumerate(fetched_texts):
                if isinstance(ft, str) and ft.strip():
                    search_results[i]["full_text"] = ft
                    _safe_print(f"[enrich] fuente {i+1} scrapeada: {len(ft.split())} palabras — {search_results[i]['url'][:80]}")
                else:
                    _safe_print(f"[enrich] fuente {i+1} sin texto — {search_results[i]['url'][:80]}")
        # ─────────────────────────────────────────────────────────────────────

        fact = scraped_to_fact(
            content,
            region=self.style.region,
            search_results=search_results,
        )
        return await self.generate_from_fact_for(fact, format_name=format_name)

    async def generate_from_fact_for(self, fact: FactInput, *, format_name: str | None = None) -> EngineResult:
        report = verify_fact(fact)
        if not report.ok:
            return EngineResult(
                ok=False,
                reason=f"hecho inválido: {report}",
                verification=str(report),
            )

        style = self._resolve_style(format_name)
        system = build_system_prompt(style)
        user = fact.to_prompt_with_format(style.format)

        return await self._run_generation(
            fact=fact,
            style=style,
            system=system,
            user=user,
            verification=str(report),
        )

    def _resolve_style(self, format_name: str | None) -> EditorialStyle:
        if format_name and format_name != self.style.format_name:
            return EditorialStyle(
                name=format_name,
                region=self.style.region,
                language=self.style.language,
                format_name=format_name,
            )
        return self.style

    async def _run_generation(
        self,
        *,
        fact: FactInput,
        style: EditorialStyle,
        system: str,
        user: str,
        verification: str,
        _is_retry: bool = False,
    ) -> EngineResult:
        primary = self.config.get("ia_order", ["openai", "groq", "gemini", "claude"])[0]
        primary_cfg = self.config.get("providers", {}).get(primary, {})
        temperature = float(primary_cfg.get("temperature", 0.2))
        # Lee max_tokens del config por proveedor (default 2000 si no está definido)
        max_tokens = int(primary_cfg.get("max_tokens", 2000))

        route = await self.router.generate(
            system, user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if route is None:
            return EngineResult(
                ok=False,
                reason="ningún proveedor pudo generar contenido",
                verification=verification,
            )

        quality = check_output(route.text, self.config, format=style.format)
        sections = style.format.parse(route.text)

        # ── Auto-retry si hay secciones muy cortas y aún no reintentamos ──────
        short_issues = [i for i in quality.issues if "muy corta" in i]
        if short_issues and not _is_retry:
            detalle = "; ".join(short_issues)
            retry_user = (
                user
                + "\n\n⚠️ ATENCIÓN — LA RESPUESTA ANTERIOR FUE RECHAZADA POR SER MUY CORTA:\n"
                + detalle
                + "\nDebes extender las secciones indicadas para cumplir el mínimo de palabras. "
                "Agrega contexto, antecedentes, impacto local y detalles del hecho. "
                "NO repitas frases, NO uses relleno: agrega información real y útil. "
                "Genera la noticia completa nuevamente respetando todos los mínimos."
            )
            _safe_print(f"[auto-retry] secciones cortas detectadas: {detalle}")
            return await self._run_generation(
                fact=fact,
                style=style,
                system=system,
                user=retry_user,
                verification=verification,
                _is_retry=True,
            )
        # ─────────────────────────────────────────────────────────────────────

        pending_path = self.approval_queue.submit(
            fact=fact,
            text=route.text,
            provider=route.provider,
            is_draft=route.is_draft,
            quality=quality,
            router_attempts=route.attempts,
            elapsed_ms=route.elapsed_ms,
        )

        return EngineResult(
            ok=True,
            reason="ok",
            pending_path=pending_path,
            provider=route.provider,
            is_draft=route.is_draft,
            quality=quality,
            verification=verification,
            elapsed_ms=route.elapsed_ms,
            router_attempts=route.attempts,
            text=route.text,
            sections=sections,
            format_name=style.format_name,
            source_url=fact.source_url,
            source_site=fact.source_site,
            image_url=fact.image_url,
        )

    async def refine(
        self,
        fact: FactInput,
        current_sections: dict[str, str],
        user_message: str,
        *,
        format_name: str | None = None,
    ) -> EngineResult:
        """Refina una noticia existente a partir de una instrucción en lenguaje natural.

        Mantiene el formato Nexaa (mismos encabezados) y modifica solo lo que el
        usuario pidió. El resto se preserva textualmente.
        """
        if not user_message.strip():
            return EngineResult(ok=False, reason="mensaje de refinamiento vacío")

        style = self._resolve_style(format_name)
        system = build_system_prompt(style) + (
            "\n\nMODO REFINAMIENTO (chat con el editor):\n"
            "El editor ya tiene una versión de la noticia. Tu trabajo es modificar SOLO lo que el "
            "editor pide en su mensaje. Mantén el resto EXACTAMENTE igual. No cambies datos verificados. "
            "No cambies la atribución. No cambies la estructura. Solo ajusta lo que el editor pidió.\n"
            "Responde con la noticia completa, con los MISMOS encabezados en el MISMO orden."
        )

        current_text = "\n\n".join(
            f"{style.format.get(name).emoji} {name}:\n{content}".strip()
            for name, content in current_sections.items()
            if content
        )

        user = (
            f"NOTICIA ACTUAL (que el editor quiere refinar):\n\n{current_text}\n\n"
            f"INSTRUCCIÓN DEL EDITOR:\n{user_message.strip()}\n\n"
            f"Responde SOLO con la noticia modificada. Mantén todo lo que no esté relacionado "
            f"con la instrucción del editor EXACTAMENTE igual, palabra por palabra."
        )

        return await self._run_generation(
            fact=fact,
            style=style,
            system=system,
            user=user,
            verification="refinamiento",
        )
