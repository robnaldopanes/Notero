"""Capa web de Nexaa. FastAPI + HTML responsive.

Pensado para uso desde celular: una sola página, sin login, sin estado
complejo. El usuario pega una idea, opcionalmente aporta categoría/ciudad/fecha,
oprime "Generar" y recibe texto listo para copiar.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _safe_print(*args, **kwargs) -> None:
    """print() seguro en Windows: encodea a utf-8 con reemplazo para evitar
    OSError cuando la consola no soporta los caracteres del texto (ej. emojis)."""
    kwargs.pop("flush", None)  # siempre forzamos flush manualmente
    text = " ".join(str(a) for a in args) + kwargs.get("end", "\n")
    try:
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except (AttributeError, OSError):
        # Fallback si stdout no tiene buffer (ej. pytest, IDEs)
        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe, end="", flush=True)

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..editorial.core import FactInput
from ..engine.engine import NewsEngine


class GenerateRequest(BaseModel):
    mode: str = Field(default="idea", pattern="^(idea|fact|scrape)$")
    format: str = Field(default="nexaa_v1", pattern="^(nexaa_v1|nexaa_social_v1)$")
    categoria: str = ""
    ciudad: str = "Chillán"
    region: str = "Región de Ñuble"
    fecha: str = ""
    titulo_corto: str = ""
    que_paso: str = ""
    por_que_importa: str = ""
    contexto: str = ""
    impacto: str = ""
    fuentes: list[str] = Field(default_factory=list)
    source_url: str = ""


class ScrapeRequest(BaseModel):
    url: str
    force: bool = False
    expected_title: str = ""


class RefineRequest(BaseModel):
    format: str = Field(default="nexaa_social_v1", pattern="^(nexaa_v1|nexaa_social_v1)$")
    categoria: str = ""
    ciudad: str = "Chillán"
    region: str = "Región de Ñuble"
    fecha: str = ""
    titulo_corto: str = ""
    que_paso: str = ""
    por_que_importa: str = ""
    contexto: str = ""
    impacto: str = ""
    fuentes: list[str] = Field(default_factory=list)
    source_url: str = ""
    source_site: str = ""
    current_sections: dict[str, str] = Field(default_factory=dict)
    user_message: str = ""


class GenerateResponse(BaseModel):
    ok: bool
    reason: str = ""
    provider: str | None = None
    is_draft: bool = False
    text: str = ""
    quality_ok: bool = False
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
    word_counts: dict[str, int] = Field(default_factory=dict)
    pending_path: str | None = None
    elapsed_ms: float = 0.0
    source_url: str = ""
    source_site: str = ""
    image_url: str = ""
    format: str = "nexaa_v1"
    sections: dict[str, str] = Field(default_factory=dict)


@dataclass
class _WebState:
    engine: NewsEngine
    counter: int = 0


def build_app(engine: NewsEngine) -> FastAPI:
    state = _WebState(engine=engine)

    package_root = Path(__file__).resolve().parent
    templates_dir = package_root / "templates"
    static_dir = package_root / "static"

    app = FastAPI(title="Nexaa AI Editor", version="0.1.0")
    app.state.engine = engine

    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )

    @app.middleware("http")
    async def log_exceptions_to_file(request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            import traceback
            try:
                with open("c:/Users/damian/Desktop/la clase/notero/error_traceback.txt", "w", encoding="utf-8") as f:
                    traceback.print_exc(file=f)
            except Exception:
                pass
            raise e

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        resp = await call_next(request)
        if request.url.path.startswith("/static") or request.url.path in ("/", "/healthz"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (templates_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/favicon.ico")
    def favicon():
        ico = static_dir / "favicon.ico"
        if ico.exists():
            return FileResponse(ico)
        raise HTTPException(status_code=404)

    # Fuentes RSS: locales de Ñuble + nacionales con cobertura regional
    # Solo se incluyen las que tienen RSS funcionando y devuelven XML válido.
    LOCAL_RSS_SOURCES = [
        # Medios locales de Ñuble
        ("La Discusión",         "https://www.ladiscusion.cl/feed/"),
        ("Radio Contacto",       "https://radiocontacto.cl/feed/"),
        ("La Fontana",           "https://lafontana.cl/feed/"),
        ("Ñuble Digital",        "https://nubledigital.cl/feed/"),
        # Municipalidades de Ñuble (las que tienen RSS público)
        ("Muni Chillán Viejo",   "https://www.chillanviejo.cl/feed/"),
        ("Muni Cobquecura",      "https://www.municipalidadcobquecura.cl/feed/"),
        ("Muni Coelemu",         "https://www.municoelemu.cl/feed/"),
        ("Muni Coihueco",        "https://www.coihueco.cl/feed/"),
        ("Muni Florida",         "https://www.muniflorida.cl/feed/"),
        ("Muni Pemuco",          "https://www.pemuco.cl/feed/"),
        ("Muni Quirihue",        "https://www.muniquirihue.cl/feed/"),
        ("Muni San Carlos",      "https://www.munisancarlos.cl/feed/"),
        ("Muni San Ignacio",     "https://www.sanignacio.cl/feed/"),
        # Organismos públicos con RSS
        ("GORE Ñuble",           "https://www.goredenuble.cl/feed/"),
        ("Mineduc (nacional)",   "https://www.mineduc.cl/feed/"),
        ("DGA (MOP)",            "https://dga.mop.gob.cl/feed/"),
        # Nacionales con cobertura regional
        ("BioBio Chile",          "https://www.biobiochile.cl/feed/"),
        ("BioBio Chile (Ñuble)",  "https://www.biobiochile.cl/tag/nuble/feed/"),
        ("Cooperativa",           "https://www.cooperativa.cl/noticias/site/tax/port/all/rss.xml"),
        ("La Tercera",            "https://www.latercera.com/feed/"),
        ("El Mostrador",          "https://www.elmostrador.cl/feed/"),
        ("EMOL",                  "https://www.emol.com/rss/"),
        ("Interferencia",         "https://interferencia.cl/feed/"),
        # Pendientes: agregar cuando me pases la URL correcta del RSS
    ]

    # Dominios bloqueados — no los mostramos en resultados de búsqueda
    BLOCKED_DOMAINS = {"nubleonline.cl", "www.nubleonline.cl"}

    @app.get("/api/status")
    def api_status() -> dict:
        return {
            "available_providers": state.engine.available_providers(),
            "circuit_breaker": state.engine.breaker_snapshot(),
        }

    @app.get("/api/search")
    async def api_search(q: str = "", source: str = "national", scope: str = "local") -> list[dict]:
        import xml.etree.ElementTree as ET
        from urllib.parse import quote_plus, urlparse
        import httpx

        query = q.strip()
        results = []

        if scope == "local":
            if not query:
                query = "Ñuble"
            query_lower = query.lower()
            if "ñuble" not in query_lower and "chillán" not in query_lower and "chillan" not in query_lower:
                query = f'{query} "Ñuble"'
            # Excluir sitios bloqueados desde la query de Google News
            exclude_clause = " ".join(f"-site:{d}" for d in BLOCKED_DOMAINS)
            full_query = f"{query} {exclude_clause}"
            url = f"https://news.google.com/rss/search?q={quote_plus(full_query)}&hl=es-419&gl=CL&ceid=CL:es-419"
        elif scope == "national":
            if not query:
                query = "Chile"
            url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=es-419&gl=CL&ceid=CL:es-419"
        else:  # international
            if not query:
                query = "Mundo"
            url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=es-419&gl=US&ceid=US:es-419"

        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        def parse_rss_items(xml_bytes_or_text, default_source: str = "") -> list[dict]:
            """Parsea items de un feed RSS y devuelve lista de dicts normalizados."""
            items_out = []
            try:
                if isinstance(xml_bytes_or_text, bytes):
                    root = ET.fromstring(xml_bytes_or_text)
                else:
                    root = ET.fromstring(xml_bytes_or_text.encode("utf-8", errors="replace"))
            except ET.ParseError:
                return []

            for item in root.findall(".//item"):
                # Filtro de antigüedad: solo últimas 48h (más amplio para fuentes locales)
                pub_date_el = item.find("pubDate")
                if pub_date_el is not None and pub_date_el.text:
                    try:
                        pub_dt = parsedate_to_datetime(pub_date_el.text)
                        if (now - pub_dt).total_seconds() > 172800:  # 48h
                            continue
                    except Exception:
                        pass

                title_el = item.find("title")
                link_el  = item.find("link")
                source_el = item.find("source")

                title = (title_el.text or "").strip() if title_el is not None else ""
                link  = (link_el.text or "").strip() if link_el is not None else ""

                source_name = ""
                if source_el is not None:
                    source_name = (source_el.text or "").strip()
                elif default_source:
                    source_name = default_source
                elif " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source_name = parts[1].strip()

                if source_name and title.endswith(f" - {source_name}"):
                    title = title[: -len(f" - {source_name}")].strip()

                if not link:
                    continue

                domain = urlparse(link).netloc.replace("www.", "")
                if domain in BLOCKED_DOMAINS:
                    continue

                display_source = source_name or domain
                items_out.append({
                    "title":   title,
                    "url":     link,
                    "snippet": f"Noticia de {display_source}." if display_source else "Noticia local.",
                    "source":  display_source,
                    "_is_google": "google.com" in link,
                })

            return items_out

        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Feedfetcher-Google/1.0)"},
        ) as client:

            # ------------------------------------------------------------------ #
            # 1. Google News RSS (excluye dominios bloqueados)                    #
            # ------------------------------------------------------------------ #
            google_raw: list[dict] = []
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    google_raw = parse_rss_items(resp.content)[:20]
            except Exception:
                pass

            # ------------------------------------------------------------------ #
            # 2. RSS directos de fuentes locales (solo para búsqueda local)       #
            # ------------------------------------------------------------------ #
            local_raw: list[dict] = []
            if scope == "local":
                async def fetch_local_rss(name: str, feed_url: str) -> list[dict]:
                    try:
                        r = await client.get(feed_url, timeout=6.0)
                        if r.status_code == 200:
                            items = parse_rss_items(r.content, default_source=name)
                            # Si hay query de texto, filtrar por coincidencia
                            if query and query.lower() not in ("ñuble", "chillán", "chillan"):
                                kw = query.lower().replace('"ñuble"', "").replace('"', "").strip().split()
                                items = [
                                    i for i in items
                                    if any(k in i["title"].lower() for k in kw)
                                ]
                            return items[:8]
                    except Exception:
                        pass
                    return []

                local_results = await asyncio.gather(
                    *(fetch_local_rss(name, feed_url) for name, feed_url in LOCAL_RSS_SOURCES)
                )
                for chunk in local_results:
                    local_raw.extend(chunk)

            # ------------------------------------------------------------------ #
            # 3. Resolver URLs de Google News → URL real del artículo             #
            # ------------------------------------------------------------------ #
            from ..sources.scraper import resolve_google_news_url

            async def resolve_item(item_dict: dict) -> dict:
                if item_dict.get("_is_google") or "news.google.com" in item_dict["url"]:
                    resolved = await resolve_google_news_url(item_dict["url"], client)
                    item_dict["url"] = resolved
                    domain = urlparse(resolved).netloc.replace("www.", "")
                    if not item_dict["source"] or "google" in item_dict["source"].lower():
                        item_dict["source"] = domain
                    # Descartar si resulta ser un dominio bloqueado
                    if domain in BLOCKED_DOMAINS:
                        return {}
                item_dict.pop("_is_google", None)
                return item_dict

            # Primero fuentes locales RSS (ya tienen URL real, no necesitan resolver)
            for item in local_raw:
                item.pop("_is_google", None)

            resolved_google = await asyncio.gather(*(resolve_item(r) for r in google_raw))
            resolved_google = [r for r in resolved_google if r]  # quitar los vacíos (bloqueados)

            # ------------------------------------------------------------------ #
            # 4. Merge: locales primero, luego Google, sin duplicados por URL     #
            # ------------------------------------------------------------------ #
            seen_urls: set[str] = set()
            merged: list[dict] = []

            for item in [*local_raw, *resolved_google]:
                key = item.get("url", "")
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    merged.append(item)
                if len(merged) >= 20:
                    break

            results = merged

        return results

    @app.get("/api/formats")
    def api_formats() -> list[dict]:
        from ..editorial.formats import FORMATS
        out = []
        for fmt in FORMATS.values():
            out.append({
                "name": fmt.name,
                "label": fmt.label,
                "description": fmt.description,
                "sections": [
                    {"name": s.name, "emoji": s.emoji, "required": s.required, "description": s.description}
                    for s in fmt.sections
                ],
            })
        return out

    @app.post("/api/generate", response_model=GenerateResponse)
    async def api_generate(req: GenerateRequest) -> GenerateResponse:
        if not req.que_paso.strip():
            raise HTTPException(status_code=400, detail="que_paso es obligatorio")

        state.counter += 1
        fact_id = f"web-{datetime.now().strftime('%Y%m%d%H%M%S')}-{state.counter:04d}"

        fecha = req.fecha.strip() or datetime.now().strftime("%Y-%m-%d")
        titulo = req.titulo_corto.strip() or (req.que_paso.strip()[:60] + ("…" if len(req.que_paso.strip()) > 60 else ""))
        categoria = req.categoria.strip() or ("General" if req.mode == "idea" else "")
        por_que = req.por_que_importa.strip() or "[POR VERIFICAR - completar antes de publicar]"

        sources = list(req.fuentes)
        if req.source_url and req.source_url not in sources:
            sources.append(req.source_url)

        fact = FactInput(
            fact_id=fact_id,
            categoria=categoria,
            ciudad=req.ciudad.strip() or "Chillán",
            region=req.region.strip() or "Región de Ñuble",
            fecha=fecha,
            titulo_corto=titulo,
            que_paso=req.que_paso.strip(),
            por_que_importa=por_que,
            contexto=req.contexto.strip(),
            impacto=req.impacto.strip(),
            fuentes=tuple(sources),
            source_url=req.source_url.strip(),
            source_site="",
        )

        result = await state.engine.generate_from_fact_for(fact, format_name=req.format)

        if not result.ok:
            return GenerateResponse(
                ok=False,
                reason=result.reason,
            )

        q = result.quality
        return GenerateResponse(
            ok=True,
            provider=result.provider,
            is_draft=result.is_draft,
            text=result.text,
            quality_ok=q.ok if q else False,
            issues=q.issues if q else [],
            warnings=q.warnings if q else [],
            needs_human_review=q.needs_human_review if q else False,
            word_counts=q.word_counts if q else {},
            pending_path=str(result.pending_path) if result.pending_path else None,
            elapsed_ms=result.elapsed_ms,
            source_url=fact.source_url,
            source_site=fact.source_site,
            image_url=result.image_url,
            format=req.format,
            sections=result.sections,
        )

    @app.post("/api/scrape")
    async def api_scrape(req: ScrapeRequest) -> dict:
        result = await state.engine.scrape(req.url, force=req.force)
        return result

    @app.post("/api/scrape-and-generate")
    async def api_scrape_and_generate(req: ScrapeRequest, format: str = "nexaa_social_v1") -> dict:
        _safe_print(f"[scrape-and-generate] url={req.url} force={req.force} format={format} expected_title={req.expected_title!r}")
        result = await state.engine.generate_from_url(
            req.url, force=req.force, format_name=format, expected_title=req.expected_title
        )
        if not result.ok:
            _safe_print(f"[scrape-and-generate] FALLO: {result.reason}")
            return {"ok": False, "reason": result.reason, "url": req.url}
        _safe_print(f"[scrape-and-generate] OK provider={result.provider} format={result.format_name} elapsed_ms={result.elapsed_ms:.0f}")
        q = result.quality
        return {
            "ok": True,
            "provider": result.provider,
            "is_draft": result.is_draft,
            "text": result.text,
            "sections": result.sections,
            "format": result.format_name,
            "quality_ok": q.ok if q else False,
            "issues": q.issues if q else [],
            "warnings": q.warnings if q else [],
            "needs_human_review": q.needs_human_review if q else False,
            "word_counts": q.word_counts if q else {},
            "pending_path": str(result.pending_path) if result.pending_path else None,
            "elapsed_ms": result.elapsed_ms,
            "source_url": result.source_url,
            "source_site": result.source_site,
            "image_url": result.image_url,
        }

    @app.post("/api/refine")
    async def api_refine(req: RefineRequest) -> dict:
        if not req.user_message.strip():
            raise HTTPException(status_code=400, detail="user_message vacío")
        if not req.current_sections:
            raise HTTPException(status_code=400, detail="current_sections vacío")

        fact = FactInput(
            fact_id=f"refine-{int(asyncio.get_event_loop().time() * 1000)}",
            categoria=req.categoria or "General",
            ciudad=req.ciudad or "Chillán",
            region=req.region or "Región de Ñuble",
            fecha=req.fecha or "1970-01-01",
            titulo_corto=req.titulo_corto or "",
            que_paso=req.que_paso or "",
            por_que_importa=req.por_que_importa or "",
            contexto=req.contexto,
            impacto=req.impacto,
            fuentes=tuple(req.fuentes),
            source_url=req.source_url,
            source_site=req.source_site,
        )
        result = await state.engine.refine(
            fact=fact,
            current_sections=req.current_sections,
            user_message=req.user_message,
            format_name=req.format,
        )
        if not result.ok:
            return {"ok": False, "reason": result.reason}
        q = result.quality
        return {
            "ok": True,
            "provider": result.provider,
            "is_draft": result.is_draft,
            "text": result.text,
            "sections": result.sections,
            "format": result.format_name,
            "quality_ok": q.ok if q else False,
            "issues": q.issues if q else [],
            "warnings": q.warnings if q else [],
            "needs_human_review": q.needs_human_review if q else False,
            "word_counts": q.word_counts if q else {},
            "elapsed_ms": result.elapsed_ms,
            "image_url": result.image_url,
        }

    @app.get("/api/pending")
    def api_pending() -> list[dict]:
        items = state.engine.approval_queue.list_pending()
        return [item.to_dict() for item in items]

    @app.post("/api/approve")
    def api_approve(payload: dict) -> dict:
        path = payload.get("path")
        reviewer = (payload.get("reviewer") or "").strip()
        reason = (payload.get("reason") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path requerido")
        if not reviewer:
            raise HTTPException(status_code=400, detail="reviewer requerido")
        try:
            dst = state.engine.approval_queue.approve(path, reviewer=reviewer, reason=reason)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="pendiente no encontrado")
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True, "path": str(dst), "reviewer": reviewer}

    @app.post("/api/reject")
    def api_reject(payload: dict) -> dict:
        path = payload.get("path")
        reviewer = (payload.get("reviewer") or "").strip()
        reason = (payload.get("reason") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path requerido")
        if not reviewer:
            raise HTTPException(status_code=400, detail="reviewer requerido")
        if not reason:
            raise HTTPException(status_code=400, detail="reason requerido al rechazar")
        try:
            dst = state.engine.approval_queue.reject(path, reviewer=reviewer, reason=reason)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="pendiente no encontrado")
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"ok": True, "path": str(dst), "reviewer": reviewer, "reason": reason}

    @app.post("/api/remove")
    def api_remove(payload: dict) -> dict:
        from pathlib import Path
        path = payload.get("path")
        reason = (payload.get("reason") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="path requerido")
        if not reason:
            raise HTTPException(status_code=400, detail="reason requerido al quitar")
        p = Path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="pendiente no encontrado")
        p.unlink()
        return {"ok": True, "path": path, "reason": reason}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.exception_handler(Exception)
    def unhandled(request, exc):  # noqa: ARG001
        import traceback
        import sys
        print("--- UNHANDLED EXCEPTION IN WEB LAYER ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("-----------------------------------------", file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={"detail": f"internal error: {type(exc).__name__}: {exc}"},
        )

    return app
