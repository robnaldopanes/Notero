# Nexaa AI Editor System

Generador automático de noticias con línea editorial fija para un medio digital local de la **Región de Ñuble, Chile**. Multi-proveedor de IA, con fallback automático y aprobación humana antes de publicar. Incluye interfaz web responsive usable desde celular.

## Arquitectura

```
nexaa/
├── editorial/      Reglas Nexaa (formato, estilo, prompt del sistema)
├── providers/      OpenAI, Gemini, Claude, LocalTemplate (misma interfaz)
├── router/         AI Router con circuit breaker + métricas
├── quality/        Verificador de hechos + checker determinista
├── sources/        Fact store (hechos verificados)
├── engine/         Orquestador + cola de aprobación humana
├── web/            FastAPI + HTML responsive (mobile-first)
└── cli.py          Entrada de línea de comandos
```

## Principios de diseño

1. **Hechos verificados primero.** El sistema NO genera desde texto libre. Lee de un fact store con datos curados, o recibe un `FactInput` validado (vía web o API).
2. **Editorial Core es código, no prompt.** Las reglas viven en `editorial/core.py` y se inyectan al system prompt.
3. **Fallback paralelo, no secuencial.** El router intenta el primario, y si falla lanza todos los demás en paralelo.
4. **Circuit breaker.** Si un proveedor falla N veces, queda fuera por un cooldown.
5. **Checks deterministas, no otra LLM.** Las secciones, longitudes y palabras prohibidas se validan con regex.
6. **Humano en el loop.** Todo lo generado va a `data/pending/` y requiere aprobación antes de pasar a `data/published/`.
7. **Template local = borrador, no publicación.** Si todos los proveedores fallan, se genera un BORRADOR marcado, nunca se publica directo.
8. **Web y CLI comparten el mismo engine.** Un solo `NewsEngine` con dos interfaces.

## Configuración

```bash
cp .env.example .env
# Editar .env con tus API keys (al menos una)
pip install -r requirements.txt
```

`config.yaml` controla el orden de proveedores, timeouts, circuit breaker y reglas de calidad.

## Uso — CLI

```bash
# Generar desde un hecho verificado
python -m nexaa.cli generate --fact data/facts/ejemplo.json

# Ver borradores pendientes
python -m nexaa.cli pending

# Aprobar un borrador
python -m nexaa.cli approve data/pending/xxx.json --reviewer editor@nexaa.cl

# Rechazar
python -m nexaa.cli reject data/pending/xxx.json --reason "datos insuficientes"

# Estado de proveedores y circuit breaker
python -m nexaa.cli status

# Arrancar servidor web
python -m nexaa.cli serve --host 0.0.0.0 --port 8000
```

## Uso — Web (celular incluido)

```bash
python -m nexaa.cli serve --host 0.0.0.0 --port 8000
# Abre http://localhost:8000 en el navegador del celular (misma red)
```

La página es responsive, mobile-first, con:

- Selector de modo: *idea rápida* o *hecho verificado*
- Campos opcionales para categoría, ciudad, fecha, contexto, impacto, fuentes
- Botón "Generar noticia"
- Tags de estado (DRAFT, REVISIÓN, OK, issues)
- Texto listo para copiar al portapapeles
- Detalles de calidad plegables

Endpoints disponibles:

| Método | Ruta             | Función                                        |
| ------ | ---------------- | ---------------------------------------------- |
| GET    | `/`              | UI responsive                                  |
| GET    | `/api/status`    | Proveedores activos + estado del circuit       |
| POST   | `/api/generate`  | Genera borrador a partir de un hecho           |
| GET    | `/api/pending`   | Lista borradores esperando aprobación humana   |
| GET    | `/healthz`       | Liveness                                       |

## Línea editorial (resumen)

- 7 secciones obligatorias: Categoría, Ciudad/Región, Titular, Desarrollo, Contexto, Impacto, Cierre.
- Titular ≤ 90 caracteres, sin clickbait.
- Desarrollo 70–320 palabras, responde qué/cuándo/dónde/por qué.
- Sin datos inventados. Si falta info clave, se marca `[DATO NO CONFIRMADO]`.
- Foco geográfico: Región de Ñuble, Chile.

## Agregar un nuevo proveedor

1. Crear `nexaa/providers/mi_provider.py` con clase que implemente `AIProvider`.
2. Registrarla en `nexaa/providers/registry.py`.
3. Agregar el nombre al `ia_order` en `config.yaml`.

## Tests

```bash
python -m pytest tests/ -v
```

18 tests cubren: editorial core, parser de secciones, system prompt, verificador de hechos, checker determinista, circuit breaker, router con fallback, engine end-to-end con template local, capa web (TestClient).

## Tests de humo del servidor real

```bash
python examples/smoke_web.py
```

Levanta uvicorn en proceso aparte, pega `GET /healthz`, `GET /api/status`, `POST /api/generate` y `GET /api/pending`, y apaga.
