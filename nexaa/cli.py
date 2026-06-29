"""CLI de Nexaa. Punto de entrada para generar, listar, aprobar y rechazar."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from nexaa.engine.engine import NewsEngine


def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: no existe config: {path}", file=sys.stderr)
        sys.exit(2)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def cmd_generate(args, engine: NewsEngine) -> int:
    result = asyncio.run(engine.generate_from_fact(args.fact))

    print()
    print("=" * 70)
    print(f"  Verificación del hecho : {result.verification}")
    print(f"  Proveedor usado        : {result.provider or 'NINGUNO'}")
    print(f"  Es borrador            : {result.is_draft}")
    print(f"  Intentos del router    : {result.router_attempts}")
    print(f"  Tiempo total           : {result.elapsed_ms:.0f} ms")
    if result.quality:
        print(f"  Quality                : {result.quality}")
        print(f"  Requiere revisión      : {result.quality.needs_human_review}")
    print("=" * 70)

    if not result.ok:
        print(f"\nFALLO: {result.reason}", file=sys.stderr)
        return 1

    print(f"\nBorrador pendiente de aprobación humana:")
    print(f"  {result.pending_path}")
    print("\nPróximos pasos:")
    print(f"  python -m nexaa.cli pending")
    print(f"  python -m nexaa.cli approve {result.pending_path} --reviewer <email>")
    return 0


def cmd_pending(args, engine: NewsEngine) -> int:
    items = engine.approval_queue.list_pending()
    if not items:
        print("No hay borradores pendientes.")
        return 0
    print(f"{len(items)} borrador(es) pendiente(s):\n")
    for it in items:
        draft_tag = "  [DRAFT]" if it.is_draft else ""
        review_tag = "  [REVISIÓN]" if it.quality.get("needs_human_review") else ""
        print(f"· {it.item_id}{draft_tag}{review_tag}")
        print(f"    fact_id     : {it.fact_id}")
        print(f"    provider    : {it.provider}")
        print(f"    categoria   : {it.fact_summary.get('categoria')}")
        print(f"    ciudad      : {it.fact_summary.get('ciudad')}")
        print(f"    issues      : {len(it.quality.get('issues', []))}")
        print(f"    warnings    : {len(it.quality.get('warnings', []))}")
        print(f"    archivo     : data/pending/{it.item_id}.json")
        print()
    return 0


def cmd_approve(args, engine: NewsEngine) -> int:
    dst = engine.approval_queue.approve(args.path, reviewer=args.reviewer, reason=args.reason or "")
    print(f"APROBADO -> {dst}")
    return 0


def cmd_reject(args, engine: NewsEngine) -> int:
    if not args.reason:
        print("ERROR: --reason es obligatorio al rechazar", file=sys.stderr)
        return 2
    dst = engine.approval_queue.reject(args.path, reviewer=args.reviewer, reason=args.reason)
    print(f"RECHAZADO -> {dst}")
    return 0


def cmd_status(args, engine: NewsEngine) -> int:
    snap = engine.breaker_snapshot()
    available = engine.available_providers()
    print("Proveedores disponibles:", ", ".join(available) if available else "(ninguno)")
    print("\nCircuit breaker:")
    if not snap:
        print("  (sin actividad aún)")
    for name, st in snap.items():
        print(
            f"  · {name}: state={st['state']} failures={st['failures']} "
            f"cooldown_left={st['open_until_in']:.1f}s"
        )
        if st["last_error"]:
            print(f"      last_error: {st['last_error']}")
    return 0


def cmd_serve(args, engine: NewsEngine) -> int:
    import uvicorn
    from .web.app import build_app

    app = build_app(engine)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nexaa", description="Nexaa AI Editor CLI")
    p.add_argument("--config", default="config.yaml", help="ruta a config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="genera noticia desde un hecho verificado")
    g.add_argument("--fact", required=True, help="fact_id o ruta a JSON de hecho")

    sub.add_parser("pending", help="lista borradores pendientes de aprobación")

    a = sub.add_parser("approve", help="aprueba un borrador")
    a.add_argument("path", help="ruta al JSON en data/pending/")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", default="")

    r = sub.add_parser("reject", help="rechaza un borrador")
    r.add_argument("path", help="ruta al JSON en data/pending/")
    r.add_argument("--reviewer", required=True)
    r.add_argument("--reason", required=True)

    sub.add_parser("status", help="estado de proveedores y circuit breaker")

    s = sub.add_parser("serve", help="arranca el servidor web (interfaz responsive)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    return p


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    load_dotenv()
    args = build_parser().parse_args(argv)
    base_path = Path(__file__).resolve().parent.parent
    config = load_config(base_path / args.config)
    engine = NewsEngine(config, base_path=base_path)

    dispatch = {
        "generate": cmd_generate,
        "pending": cmd_pending,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "status": cmd_status,
        "serve": cmd_serve,
    }
    return dispatch[args.cmd](args, engine)


if __name__ == "__main__":
    sys.exit(main())
