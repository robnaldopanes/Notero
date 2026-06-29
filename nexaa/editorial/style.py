"""Estilo editorial Nexaa. Constantes y validaciones de formato."""

NEXAA_SECTIONS: tuple[str, ...] = (
    "Categoría",
    "Ciudad/Región",
    "Titular",
    "Desarrollo",
    "Contexto",
    "Impacto",
    "Cierre",
)

SECTION_HEADERS: tuple[str, ...] = tuple(f"{s}:" for s in NEXAA_SECTIONS)

MAX_TITULAR_CHARS: int = 90

CLICKBAIT_PATTERNS: tuple[str, ...] = (
    r"\bno te lo cre[eé]r?[aá]s\b",
    r"\bte volar[aá] la cabeza\b",
    r"\bimperdible\b",
    r"\b[oó]bvio que\b",
    r"\bmejor ver\s+(el|lo)\s+v[ií]deo\b",
)

UNCERTAINTY_MARKER: str = "[DATO NO CONFIRMADO - REQUIERE REVISIÓN]"

DRAFT_HEADER: str = "=== BORRADOR AUTOMÁTICO - NO PUBLICADO ==="
