"""Vercel entrypoint - Nexaa AI Editor.

Inlined CSS/JS para que funcione sin archivos estáticos externos.
"""

import sys
import os
import re
import base64
from pathlib import Path
from datetime import datetime
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env", override=False)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

import yaml

app = FastAPI(title="Nexaa AI Editor", version="0.1.0")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """HTTP Basic Auth — protege el editor con usuario/contraseña.

    Configurar en Vercel:
      NEXAA_USER=nexaa        (opcional, default: nexaa)
      NEXAA_PASSWORD=tupassword  (si no se setea, no pide auth)
    """
    path = request.url.path
    # Rutas públicas (no requieren auth)
    public_paths = ("/healthz", "/manifest.json", "/service-worker.js")
    if path in public_paths:
        return await call_next(request)

    password = os.getenv("NEXAA_PASSWORD", "")
    if not password:
        return await call_next(request)

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Basic "):
        return PlainTextResponse(
            "No autorizado",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Nexaa Editor"'},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        user, pwd = decoded.split(":", 1)
    except Exception:
        return PlainTextResponse(
            "No autorizado",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Nexaa Editor"'},
        )

    expected_user = os.getenv("NEXAA_USER", "nexaa")
    if user != expected_user or pwd != password:
        return PlainTextResponse(
            "Credenciales incorrectas",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Nexaa Editor"'},
        )

    return await call_next(request)


templates_dir = project_root / "nexaa" / "web" / "templates"
static_dir = project_root / "nexaa" / "web" / "static"

_config = None
_engine = None


def _get_config():
    global _config
    if _config is None:
        cfg_path = project_root / "config.yaml"
        if cfg_path.exists():
            _config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        else:
            _config = {"ia_order": ["groq", "mistral", "gemini"]}
        # Detect Vercel or any read-only serverless environment
        is_serverless = (
            os.getenv("VERCEL") == "1"
            or os.getenv("NOW_REGION") is not None
            or str(project_root).startswith("/var/task")
        )
        if is_serverless:
            paths = _config.setdefault("paths", {})
            paths["scraper_cache_dir"] = "/tmp/scraper_cache"
            paths["search_cache_dir"] = "/tmp/search_cache"
            paths["search_cache_dir_brave"] = "/tmp/search_cache_brave"
            paths["logs_dir"] = "/tmp/logs"
            paths["pending_dir"] = "/tmp/pending"
            paths["published_dir"] = "/tmp/published"
            paths["rejected_dir"] = "/tmp/rejected"
            paths["facts_dir"] = "/tmp/facts"
    return _config


def _get_engine():
    global _engine
    is_serverless = (
        os.getenv("VERCEL") == "1"
        or os.getenv("NOW_REGION") is not None
        or str(project_root).startswith("/var/task")
    )
    if _engine is None or is_serverless:
        try:
            from nexaa.engine.engine import NewsEngine
            _engine = NewsEngine(_get_config(), base_path=project_root)
        except Exception as e:
            raise RuntimeError(f"Engine init failed: {e}") from e
    return _engine


def _build_html() -> str:
    """Build HTML with CSS and JS inlined directly.

    Instead of regex-matching <link>/<script> tags (which breaks when
    version numbers change), this removes ALL /static/ references and
    injects the content before </head> and </body>.
    """
    html_path = templates_dir / "index.html"
    if not html_path.exists():
        return "<h1>Nexaa AI Editor</h1><p>Template not found</p>"

    html = html_path.read_text(encoding="utf-8")

    # Remove any existing stylesheet/script references to /static/
    # Use broad patterns that catch all variations (v6, v7, v9, v11, etc.)
    html = re.sub(r'<link[^>]*href="/static/[^"]*"[^>]*/?\s*>', '', html)
    html = re.sub(r'<script[^>]*src="/static/[^"]*"[^>]*>\s*</script>', '', html)

    # Inyectar CSS antes de </head>
    css_path = static_dir / "style.css"
    if css_path.exists():
        css = css_path.read_text(encoding="utf-8")
        html = html.replace("</head>", f"<style>\n{css}\n</style>\n</head>")

    # Inyectar PWA meta tags + service worker antes de </body>
    pwa_meta = (
        '<link rel="manifest" href="/manifest.json">\n'
        '<link rel="apple-touch-icon" href="/manifest.json">\n'
        '<meta name="mobile-web-app-capable" content="yes">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">\n'
        '<meta name="apple-mobile-web-app-title" content="Nexaa">\n'
    )
    sw_script = (
        '<script>if("serviceWorker" in navigator){'
        'navigator.serviceWorker.register("/service-worker.js").catch(e=>console.log("SW:",e))}</script>\n'
    )
    html = html.replace("</head>", pwa_meta + "</head>")

    # Inyectar JS antes de </body
    js_path = static_dir / "app.js"
    if js_path.exists():
        js = js_path.read_text(encoding="utf-8")
        html = html.replace("</body>", f"{sw_script}<script>\n{js}\n</script>\n</body>")

    return html


class GenerateRequest(BaseModel):
    mode: str = Field(default="idea")
    format: str = Field(default="nexaa_social_v1")
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
    format: str = "nexaa_social_v1"
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
    current_sections: dict[str, str] = Field(default_factory=dict)
    user_message: str = ""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_build_html())


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/trending")
async def api_trending(scope: str = "local"):
    """Detecta temas que están siendo cubiertos por múltiples medios simultáneamente."""
    try:
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone, timedelta
        from collections import defaultdict
        import httpx

        # Fuentes RSS según scope
        if scope == "local":
            sources = [
                ("La Discusión",   "https://www.ladiscusion.cl/feed/"),
                ("La Fontana",     "https://lafontana.cl/feed/"),
                ("Ñuble Digital",  "https://nubledigital.cl/feed/"),
                ("BioBio Chile (Ñuble)", "https://www.biobiochile.cl/tag/nuble/feed/"),
            ]
        elif scope == "international":
            sources = [
                ("BBC Mundo", "https://feeds.bbci.co.uk/mundo/rss.xml"),
                ("El País",   "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
                ("CNN Español", "https://cnnespanol.cnn.com/feed/"),
            ]
        else:  # national
            sources = [
                ("La Discusión", "https://www.ladiscusion.cl/feed/"),
                ("BioBio Chile", "https://www.biobiochile.cl/feed/"),
                ("La Tercera",   "https://www.latercera.com/feed/"),
                ("El Mostrador", "https://www.elmostrador.cl/feed/"),
                ("BBC Mundo",    "https://feeds.bbci.co.uk/mundo/rss.xml"),
            ]

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=48)

        # Stopwords para ignorar en la extracción de keywords
        stop = {"de", "la", "el", "en", "del", "las", "los", "un", "una", "y", "a", "con",
                "por", "para", "al", "se", "que", "su", "no", "más", "cómo", "muy", "le",
                "ya", "sin", "sobre", "entre", "desde", "ha", "ser", "sus", "tiene", "hay",
                "hasta", "pero", "cada", "nuevo", "nueva", "dos", "tres", "está", "tras",
                "fue", "ser", "sus", "como", "pero", "sobre", "todo", "cuando", "donde",
                "este", "esta", "estos", "estas", "otro", "otra", "otros", "otras",
                "más", "menos", "también", "para", "desde", "hasta", "entre", "sin"}

        def extract_keywords(title: str) -> set[str]:
            words = re.findall(r"[a-záéíóúñ]{3,}", title.lower())
            return {w for w in words if w not in stop}

        async def fetch_feed(name: str, url: str):
            try:
                async with httpx.AsyncClient(timeout=8, follow_redirects=True,
                                             headers={"User-Agent": "Mozilla/5.0"}) as c:
                    r = await c.get(url)
                    if r.status_code != 200:
                        return []
                    root = ET.fromstring(r.text.encode("utf-8"))
                    items = []
                    for item in root.findall(".//item"):
                        pub_el = item.find("pubDate")
                        if pub_el is None or not pub_el.text:
                            continue
                        try:
                            pub_dt = parsedate_to_datetime(pub_el.text)
                            if pub_dt < cutoff:
                                continue
                        except Exception:
                            continue
                        title_el = item.find("title")
                        link_el = item.find("link")
                        if title_el is None or link_el is None:
                            continue
                        title_text = (title_el.text or "").strip()
                        link = (link_el.text or "").strip()
                        if not title_text or not link:
                            continue
                        items.append({
                            "title": title_text,
                            "url": link,
                            "source": name,
                            "keywords": extract_keywords(title_text),
                            "ts": pub_dt.timestamp() if pub_dt else 0,
                        })
                    return items
            except Exception:
                return []

        # Fetch all feeds in parallel
        all_items = []
        for batch in asyncio.as_completed([fetch_feed(n, u) for n, u in sources]):
            try:
                all_items.extend(await batch)
            except Exception:
                pass

        # Cluster articles by shared keywords
        # A "topic" is a set of 2+ articles from different sources that share keywords
        clusters: list[dict] = []
        used = set()

        for i, item in enumerate(all_items):
            if i in used:
                continue
            cluster_items = [item]
            cluster_sources = {item["source"]}
            cluster_keywords = item["keywords"]
            used.add(i)

            for j, other in enumerate(all_items):
                if j in used:
                    continue
                if other["source"] in cluster_sources:
                    continue
                shared = cluster_keywords & other["keywords"]
                if len(shared) >= 1:
                    cluster_items.append(other)
                    cluster_sources.add(other["source"])
                    cluster_keywords = cluster_keywords & other["keywords"]
                    used.add(j)

            if len(cluster_items) >= 2:
                # Determine cluster topic from shared keywords
                topic = " / ".join(sorted(cluster_keywords)[:4])
                clusters.append({
                    "topic": topic,
                    "count": len(cluster_items),
                    "sources": sorted(cluster_sources),
                    "articles": [
                        {"title": a["title"], "url": a["url"], "source": a["source"]}
                        for a in sorted(cluster_items, key=lambda x: x["ts"], reverse=True)[:5]
                    ],
                })

        # Sort by number of sources (most relevant first)
        clusters.sort(key=lambda x: x["count"], reverse=True)
        return clusters[:10]

    except Exception:
        return []


@app.get("/manifest.json")
def manifest():
    return {
        "name": "Nexaa · Editor de noticias",
        "short_name": "Nexaa",
        "description": "Editor automático de noticias con IA. Región de Ñuble.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "lang": "es",
        "icons": [
            {
                "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 128 128'><rect width='128' height='128' rx='20' fill='%2338bdf8'/><text x='50%' y='50%' dominant-baseline='central' text-anchor='middle' fill='%230f172a' font-family='sans-serif' font-size='72' font-weight='800'>N</text></svg>",
                "sizes": "128x128",
                "type": "image/svg+xml",
                "purpose": "any"
            }
        ]
    }


@app.get("/service-worker.js")
def service_worker():
    content = """
const CACHE = 'nexaa-v1';
const OFFLINE_URL = '/';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.add(OFFLINE_URL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""
    return Response(content=content.strip(), media_type="application/javascript")


@app.get("/api/debug")
def api_debug():
    css_path = static_dir / "style.css"
    js_path = static_dir / "app.js"
    tpl_path = templates_dir / "index.html"
    cfg = _get_config()
    return {
        "project_root": str(project_root),
        "templates_dir": str(templates_dir),
        "static_dir": str(static_dir),
        "template_exists": tpl_path.exists(),
        "css_exists": css_path.exists(),
        "css_size": css_path.stat().st_size if css_path.exists() else 0,
        "js_exists": js_path.exists(),
        "js_size": js_path.stat().st_size if js_path.exists() else 0,
        "config_paths": cfg.get("paths", {}),
        "is_serverless": (
            os.getenv("VERCEL") == "1"
            or os.getenv("NOW_REGION") is not None
            or str(project_root).startswith("/var/task")
        ),
        "vercel_env": os.getenv("VERCEL", "not set"),
        "now_region": os.getenv("NOW_REGION", "not set"),
    }


@app.get("/api/status")
def api_status():
    try:
        eng = _get_engine()
        return {
            "available_providers": eng.available_providers(),
            "circuit_breaker": eng.breaker_snapshot(),
        }
    except Exception as e:
        return {"available_providers": ["local_template"], "circuit_breaker": {}, "error": str(e)}


@app.get("/api/formats")
def api_formats():
    try:
        from nexaa.editorial.formats import FORMATS
        return [
            {
                "name": f.name,
                "label": f.label,
                "description": f.description,
                "sections": [
                    {"name": s.name, "emoji": s.emoji, "required": s.required, "description": s.description}
                    for s in f.sections
                ],
            }
            for f in FORMATS.values()
        ]
    except Exception as e:
        return [{"name": "nexaa_social_v1", "label": "Nexaa social", "description": str(e), "sections": []}]


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    if not req.que_paso.strip():
        raise HTTPException(status_code=400, detail="que_paso es obligatorio")

    try:
        from nexaa.editorial.core import FactInput

        eng = _get_engine()
        fact_id = f"vercel-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        fecha = req.fecha.strip() or datetime.now().strftime("%Y-%m-%d")
        titulo = req.titulo_corto.strip() or (
            req.que_paso.strip()[:60] + ("…" if len(req.que_paso.strip()) > 60 else "")
        )
        sources = list(req.fuentes)
        if req.source_url and req.source_url not in sources:
            sources.append(req.source_url)

        fact = FactInput(
            fact_id=fact_id,
            categoria=req.categoria.strip() or "General",
            ciudad=req.ciudad.strip() or "Chillán",
            region=req.region.strip() or "Región de Ñuble",
            fecha=fecha,
            titulo_corto=titulo,
            que_paso=req.que_paso.strip(),
            por_que_importa=req.por_que_importa.strip() or "[POR VERIFICAR]",
            contexto=req.contexto.strip(),
            impacto=req.impacto.strip(),
            fuentes=tuple(sources),
            source_url=req.source_url.strip(),
        )

        result = await eng.generate_from_fact_for(fact, format_name=req.format)
        if not result.ok:
            return {"ok": False, "reason": result.reason}
        return _make_response(result, fact)
    except Exception as e:
        import traceback
        return {"ok": False, "reason": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


@app.post("/api/scrape-and-generate")
async def api_scrape_and_generate(req: ScrapeRequest):
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="url requerido")

    try:
        eng = _get_engine()
        result = await eng.generate_from_url(
            req.url, force=req.force, format_name="nexaa_social_v1"
        )
        if not result.ok:
            return {"ok": False, "reason": result.reason, "url": req.url}
        return _make_response(result)
    except Exception as e:
        import traceback
        return {"ok": False, "reason": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}


@app.post("/api/refine")
async def api_refine(req: RefineRequest):
    if not req.user_message.strip():
        raise HTTPException(status_code=400, detail="user_message vacío")
    if not req.current_sections:
        raise HTTPException(status_code=400, detail="current_sections vacío")

    from nexaa.editorial.core import FactInput

    eng = _get_engine()
    fact = FactInput(
        fact_id=f"refine-{datetime.now().strftime('%H%M%S')}",
        categoria=req.categoria or "General",
        ciudad=req.ciudad or "Chillán",
        region=req.region or "Región de Ñuble",
        fecha=req.fecha or datetime.now().strftime("%Y-%m-%d"),
        titulo_corto=req.titulo_corto or "",
        que_paso=req.que_paso or "",
        por_que_importa=req.por_que_importa or "",
        contexto=req.contexto,
        impacto=req.impacto,
        fuentes=tuple(req.fuentes),
        source_url=req.source_url,
    )
    result = await eng.refine(
        fact=fact,
        current_sections=req.current_sections,
        user_message=req.user_message,
        format_name=req.format,
    )
    if not result.ok:
        return {"ok": False, "reason": result.reason}
    return _make_response(result)


def _make_response(result, fact=None):
    q = result.quality
    return {
        "ok": True,
        "provider": result.provider,
        "is_draft": result.is_draft,
        "text": result.text,
        "quality_ok": q.ok if q else False,
        "issues": q.issues if q else [],
        "warnings": q.warnings if q else [],
        "needs_human_review": q.needs_human_review if q else False,
        "word_counts": q.word_counts if q else {},
        "pending_path": str(result.pending_path) if result.pending_path else None,
        "elapsed_ms": result.elapsed_ms,
        "sections": result.sections,
        "format": result.format_name,
        "source_url": result.source_url or (fact.source_url if fact else ""),
        "source_site": result.source_site or (fact.source_site if fact else ""),
        "image_url": getattr(result, "image_url", ""),
    }


def _is_homepage(url: str) -> bool:
    """Detecta si una URL es probablemente una portada/homepage en vez de un artículo."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").lower()
        if not path:
            return True
        if path in ("index.html", "index.php", "noticias", "feed"):
            return True
        if re.match(r"^/\d{4}/\d{2}/\d{2}/", path):
            return False
        if len(path) > 30:
            return False
        if len(path.split("/")) < 2 and len(path) < 20:
            return True
        return False
    except Exception:
        return False


@app.get("/api/search")
async def api_search(q: str = "", scope: str = "local"):
    query = q.strip()

    # Sin keywords → leer feeds RSS según el scope
    if not query:
        try:
            results = await _fetch_rss_from_sources(scope)
            return [r for r in results if not _is_homepage(r.get("url", ""))]
        except Exception:
            return []

    # Con keywords → buscar en DuckDuckGo
    try:
        import httpx
        from urllib.parse import quote_plus
        from html import unescape

        if scope == "local":
            full_query = f"{query} Ñuble Chile"
            region = "cl-es"
        elif scope == "national":
            full_query = f"{query} Chile"
            region = "cl-es"
        else:
            full_query = query
            region = "us-en"

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(full_query)}&kl={region}"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                      headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

        html_text = resp.text
        result_re = re.compile(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:a|div|span)',
            re.DOTALL | re.IGNORECASE,
        )

        tag_re = re.compile(r"<[^>]+>")
        seen = set()
        results = []
        for m in result_re.finditer(html_text):
            href = m.group(1)
            real_url = href
            if "uddg=" in href:
                try:
                    from urllib.parse import urlparse as _up, parse_qs as _pq
                    qs = _pq(_up(href).query)
                    if "uddg" in qs:
                        real_url = qs["uddg"][0]
                except Exception:
                    pass
            title = unescape(tag_re.sub("", m.group(2)).strip())
            snippet = unescape(tag_re.sub("", m.group(3)).strip())
            if real_url in seen or not real_url.startswith("http") or not title:
                continue
            if _is_homepage(real_url):
                continue
            seen.add(real_url)
            domain = real_url.split("//")[-1].split("/")[0].replace("www.", "")
            results.append({"title": title, "url": real_url, "snippet": snippet, "source": domain})
            if len(results) >= 10:
                break
        return results
    except Exception as e:
        return []


async def _fetch_rss_from_sources(scope: str = "local") -> list[dict]:
    """Lee feeds RSS de los medios locales/nacionales y devuelve las noticias
    de las últimas 24 horas, ordenadas de la más reciente a la más antigua."""
    import asyncio
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    from datetime import datetime, timezone, timedelta

    # Solo feeds verificados (desde Vercel, timeout 10s)
    LOCAL_RSS = [
        ("La Discusión",   "https://www.ladiscusion.cl/feed/"),
        ("La Fontana",     "https://lafontana.cl/feed/"),
        ("Ñuble Digital",  "https://nubledigital.cl/feed/"),
        ("Google News Ñuble", "https://news.google.com/rss/search?q=%C3%91uble+Chile&hl=es-419&gl=CL&ceid=CL:es-419"),
    ]

    # Google News RSS (devuelve URLs de artículos, no portadas)
    NATIONAL_RSS = [
        ("Google News Chile", "https://news.google.com/rss/search?q=Chile&hl=es-419&gl=CL&ceid=CL:es-419"),
        ("BBC Mundo",        "https://feeds.bbci.co.uk/mundo/rss.xml"),
        ("El País",          "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
    ]

    INTERNATIONAL_RSS = [
        ("Google News Mundo", "https://news.google.com/rss/search?q=Mundo&hl=es-419&gl=US&ceid=US:es-419"),
        ("BBC Mundo",        "https://feeds.bbci.co.uk/mundo/rss.xml"),
        ("El País",          "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
    ]

    if scope == "local":
        sources = LOCAL_RSS
    elif scope == "international":
        sources = INTERNATIONAL_RSS
    else:
        sources = NATIONAL_RSS
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    tag_re = re.compile(r"<[^>]+>")

    async def fetch_one(name: str, url: str) -> list[dict]:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True,
                                         headers={"User-Agent": "Mozilla/5.0"}) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                xml_text = resp.text
        except Exception:
            return []

        results = []
        try:
            root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
            for item in root.findall(".//item"):
                pub_el = item.find("pubDate")
                if pub_el is None or not pub_el.text:
                    continue
                try:
                    pub_dt = parsedate_to_datetime(pub_el.text)
                    if pub_dt < cutoff_24h:
                        continue
                except Exception:
                    continue

                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")

                title = (title_el.text or "").strip() if title_el is not None else ""
                link = (link_el.text or "").strip() if link_el is not None else ""
                desc_raw = (desc_el.text or "") if desc_el is not None else ""
                snippet = tag_re.sub("", desc_raw).strip()[:200]

                if not title or not link:
                    continue

                domain = link.split("//")[-1].split("/")[0].replace("www.", "")

                results.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                    "source": domain,
                    "_pub_ts": pub_dt.timestamp(),
                })
        except Exception:
            pass
        return results

    all_results = []
    tasks = [fetch_one(name, url) for name, url in sources]
    for batch in asyncio.as_completed(tasks):
        try:
            chunk = await batch
            all_results.extend(chunk)
        except Exception:
            pass

    # Deduplicar por URL y ordenar por fecha descendente
    seen = set()
    unique = []
    for r in all_results:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            unique.append(r)

    unique.sort(key=lambda x: x.get("_pub_ts", 0), reverse=True)
    for r in unique:
        r.pop("_pub_ts", None)

    return unique[:20]


@app.get("/api/pending")
def api_pending():
    eng = _get_engine()
    try:
        items = eng.approval_queue.list_pending()
        return [item.to_dict() for item in items]
    except Exception:
        return []


@app.post("/api/approve")
def api_approve(payload: dict):
    path = payload.get("path", "")
    reviewer = payload.get("reviewer", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path requerido")
    if not reviewer:
        raise HTTPException(status_code=400, detail="reviewer requerido")
    try:
        eng = _get_engine()
        dst = eng.approval_queue.approve(path, reviewer=reviewer)
        return {"ok": True, "path": str(dst), "reviewer": reviewer}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="pendiente no encontrado")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reject")
def api_reject(payload: dict):
    path = payload.get("path", "")
    reviewer = payload.get("reviewer", "").strip()
    reason = payload.get("reason", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path requerido")
    if not reviewer:
        raise HTTPException(status_code=400, detail="reviewer requerido")
    if not reason:
        raise HTTPException(status_code=400, detail="reason requerido")
    try:
        eng = _get_engine()
        dst = eng.approval_queue.reject(path, reviewer=reviewer, reason=reason)
        return {"ok": True, "path": str(dst), "reviewer": reviewer, "reason": reason}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="pendiente no encontrado")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/remove")
def api_remove(payload: dict):
    path = payload.get("path", "")
    reason = payload.get("reason", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path requerido")
    if not reason:
        raise HTTPException(status_code=400, detail="reason requerido")
    try:
        p = Path(path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="pendiente no encontrado")
        p.unlink()
        return {"ok": True, "path": path, "reason": reason}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
