"""Tests de la capa web. Usan TestClient (in-process, sin uvicorn)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nexaa.engine.engine import NewsEngine
from nexaa.web.app import build_app


@pytest.fixture
def client(config, clean_data_dir):
    engine = NewsEngine(config, base_path=ROOT)
    app = build_app(engine)
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Nexaa" in r.text
    assert "viewport" in r.text
    assert "/static/style.css" in r.text
    assert "/static/app.js" in r.text


def test_static_files_served(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "background" in r.text
    r = client.get("/static/app.js")
    assert r.status_code == 200
    assert "fetch" in r.text


def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "available_providers" in data
    assert "circuit_breaker" in data


def test_generate_rejects_empty(client):
    r = client.post("/api/generate", json={"que_paso": ""})
    assert r.status_code == 400


def test_generate_idea_mode(client):
    r = client.post("/api/generate", json={
        "mode": "idea",
        "categoria": "Educación",
        "ciudad": "Chillán",
        "fecha": "2026-06-14",
        "que_paso": "Hoy el liceo abrió un laboratorio nuevo con capacidad para 30 estudiantes.",
        "por_que_importa": "Beneficia a 1.200 estudiantes del establecimiento.",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["text"]
    assert "categor" in data["text"].lower()
    assert "noticia" in data["text"].lower() or "desarrollo" in data["text"].lower()
    assert data["provider"] in ("openai", "gemini", "claude", "groq", "mistral", "together", "local_template")
    if data["provider"] == "local_template":
        assert data["is_draft"] is True
    assert data["pending_path"]


def test_generate_pending_appears_in_queue(client):
    payload = {
        "mode": "idea",
        "categoria": "Salud",
        "ciudad": "San Carlos",
        "fecha": "2026-06-14",
        "que_paso": "El hospital local habilitó 12 camas nuevas en medicina interna.",
        "por_que_importa": "Reduce derivaciones al hospital de Chillán.",
    }
    r = client.post("/api/generate", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/pending")
    assert r2.status_code == 200
    items = r2.json()
    assert len(items) >= 1
    assert any("San Carlos" in (i.get("fact_summary") or {}).get("ciudad", "") for i in items)


def test_refine_rejects_empty_message(client):
    r = client.post("/api/refine", json={
        "user_message": "",
        "current_sections": {"Titular": "x"},
    })
    assert r.status_code == 400


def test_refine_rejects_empty_sections(client):
    r = client.post("/api/refine", json={
        "user_message": "mejorar titular",
        "current_sections": {},
    })
    assert r.status_code == 400


def test_refine_with_local_template_works(client):
    r = client.post("/api/refine", json={
        "format": "nexaa_social_v1",
        "categoria": "Educación",
        "ciudad": "Chillán",
        "region": "Región de Ñuble",
        "fecha": "2026-06-14",
        "que_paso": "Detalle del hecho verificado.",
        "por_que_importa": "Importa por X razón.",
        "current_sections": {
            "Categoría": "Educación",
            "Ciudad/Región": "Chillán, Región de Ñuble",
            "Titular": "Liceo abre laboratorio",
            "Noticia": "El liceo abrió un laboratorio. " * 30,
            "Resumen Corto": "El liceo abrió un laboratorio nuevo.",
            "Facebook Nexaa": "⚡ Laboratorio nuevo en Chillán. ¿Qué te parece?",
        },
        "user_message": "Haz el titular más directo",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert "Titular" in data["sections"]
    assert "Noticia" in data["sections"]


def test_approve_requires_reviewer(client):
    r = client.post("/api/approve", json={"path": "data/pending/xxx.json"})
    assert r.status_code == 400


def _ensure_pending(client):
    """Genera un nuevo pending si no hay ninguno, devuelve su path."""
    from pathlib import Path
    pending_dir = client.app.state.engine.approval_queue.pending_dir
    existing = list(pending_dir.glob("*.json"))
    if existing:
        return str(existing[0])
    r = client.post("/api/generate", json={
        "mode": "idea",
        "format": "nexaa_v1",
        "categoria": "Test",
        "ciudad": "Chillán",
        "region": "Región de Ñuble",
        "fecha": "2026-06-14",
        "que_paso": "Hecho de prueba para el test de aprobación con suficiente detalle.",
        "por_que_importa": "Para verificar el flujo de aprobación.",
    })
    assert r.status_code == 200
    items = list(pending_dir.glob("*.json"))
    assert items
    return str(items[0])


def test_approve_moves_pending_to_published(client):
    from pathlib import Path
    pending_dir = client.app.state.engine.approval_queue.pending_dir
    published_dir = client.app.state.engine.approval_queue.published_dir

    pending_path = _ensure_pending(client)
    pending_files_before = set(p.name for p in pending_dir.glob("*.json"))

    r = client.post("/api/approve", json={"path": pending_path, "reviewer": "editor@nexaa.cl"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert not Path(pending_path).exists()
    assert Path(data["path"]).exists()
    assert Path(data["path"]).parent == published_dir
    assert Path(data["path"]).name in pending_files_before


def test_reject_requires_reason(client):
    pending_path = _ensure_pending(client)
    r = client.post("/api/reject", json={
        "path": pending_path,
        "reviewer": "editor@nexaa.cl",
    })
    assert r.status_code == 400


def test_reject_moves_pending_to_rejected(client):
    from pathlib import Path
    pending_path = _ensure_pending(client)
    rejected_dir = client.app.state.engine.approval_queue.rejected_dir

    r = client.post("/api/reject", json={
        "path": pending_path,
        "reviewer": "editor@nexaa.cl",
        "reason": "datos insuficientes",
    })
    assert r.status_code == 200, r.text
    assert not Path(pending_path).exists()
    assert any(p.name in str(r.json()["path"]) for p in rejected_dir.glob("*.json"))


def test_remove_requires_reason(client):
    pending_path = _ensure_pending(client)
    r = client.post("/api/remove", json={"path": pending_path})
    assert r.status_code == 400


def test_remove_deletes_pending_only(client):
    from pathlib import Path
    pending_path = _ensure_pending(client)
    assert Path(pending_path).exists()

    r = client.post("/api/remove", json={
        "path": pending_path,
        "reason": "duplicado",
    })
    assert r.status_code == 200, r.text
    assert not Path(pending_path).exists()

    audit = client.app.state.engine.approval_queue.pending_dir.parent / "discarded.jsonl"
    assert not audit.exists()


def test_api_search_empty_and_valid(client):
    r = client.get("/api/search?q=")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


    # Test Google News
    r = client.get("/api/search?q=bomberos&source=national")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # Test Facebook search
    r = client.get("/api/search?q=bomberos&source=facebook")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # Test Twitter search
    r = client.get("/api/search?q=bomberos&source=twitter")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # Test Web General
    r = client.get("/api/search?q=bomberos&source=all")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_scrape_and_generate_endpoint(client, monkeypatch):
    from nexaa.sources.scraper import ScrapedContent
    async def mock_fetch(self, url, force=False):
        return ScrapedContent(
            url=url,
            canonical_url=url,
            site_name="Test Site",
            title="Liceo de Chillán abre laboratorio",
            main_text="El liceo abrió un laboratorio nuevo con capacidad para 30 estudiantes.",
            summary="El liceo abrió un laboratorio.",
        )
    from nexaa.sources.scraper import Scraper
    monkeypatch.setattr(Scraper, "fetch", mock_fetch)

    r = client.post("/api/scrape-and-generate", json={"url": "https://example.com/2026/06/14/noticia-de-prueba"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] in (True, False)
