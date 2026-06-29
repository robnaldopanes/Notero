"""Formatos editoriales configurables.

Cada formato define sus secciones, marcadores visuales, validaciones y reglas.
El motor, el parser y el checker leen de aquí. Agregar un formato nuevo = crear
un nuevo EditorialFormat y registrarlo en FORMATS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class SectionSpec:
    name: str
    emoji: str
    header_pattern: str
    required: bool = True
    min_words: int = 0
    max_words: int = 0
    max_chars: int = 0
    description: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class EditorialFormat:
    name: str
    label: str
    description: str
    sections: tuple[SectionSpec, ...]
    custom_rules: tuple[str, ...] = ()
    titular_max_words: int = 14
    titular_max_chars: int = 90
    forbidden_patterns: tuple[str, ...] = ()

    def section_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sections)

    def required_section_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sections if s.required)

    def get(self, name: str) -> SectionSpec | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def section_by_name(self, name: str) -> SectionSpec | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def parse(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {s.name: "" for s in self.sections}
        current: str | None = None
        buffer: list[str] = []

        def strip_md(s: str) -> str:
            return re.sub(r"\*{1,3}|_{1,3}|`", "", s)

        def clean_value(s: str, spec: SectionSpec | None = None) -> str:
            s = strip_md(s).strip()
            if spec is not None:
                if spec.emoji:
                    s = s.replace(spec.emoji, "", 1).strip()
                name_lc = spec.name.lower()
                if s.lower().startswith(name_lc + ":") or s.lower().startswith(name_lc + " :"):
                    s = s[len(name_lc) + 1:].strip()
            s = re.sub(r"^[\s\-•\*→:]+", "", s).strip()
            s = re.sub(r"^[:：\s]+", "", s).strip()
            return s

        def find_section_header(line: str) -> SectionSpec | None:
            stripped = strip_md(line).strip()
            stripped_lower = stripped.lower()
            for spec in self.sections:
                name_lower = spec.name.lower()
                if spec.emoji:
                    if spec.emoji not in stripped and name_lower not in stripped_lower:
                        continue
                else:
                    if name_lower not in stripped_lower:
                        continue
                pat = spec.header_pattern
                if re.match(pat, stripped, flags=re.IGNORECASE):
                    return spec
                name_clean = strip_md(stripped).lower()
                if name_clean.startswith(name_lower + ":") or name_clean.startswith(name_lower + " :"):
                    return spec
                if name_clean.startswith(name_lower + "**") or name_clean.startswith("**" + name_lower):
                    return spec
            return None

        def find_section_by_emoji(line: str, used: set[str]) -> SectionSpec | None:
            """Fallback: si la línea tiene el emoji de una sección no usada aún,
            devolverla. Sirve para IAs que escriben el valor directo con emoji
            sin mencionar el nombre de la sección (ej: "📌 **Economía**")."""
            stripped = strip_md(line).strip()
            if not stripped:
                return None
            for spec in self.sections:
                if not spec.emoji:
                    continue
                if spec.name in used:
                    continue
                if spec.emoji in stripped[:5]:
                    return spec
            return None

        def extract_inline(line: str, spec: SectionSpec) -> str:
            stripped = strip_md(line).strip()
            for pattern in (spec.header_pattern,):
                m = re.match(pattern, stripped, flags=re.IGNORECASE)
                if m:
                    rest = stripped[m.end():].strip()
                    return clean_value(rest, spec)
            return clean_value(stripped, spec)

        lines = text.splitlines()
        used_sections: set[str] = set()
        i = 0
        while i < len(lines):
            line = lines[i]
            spec = find_section_header(line)
            if spec is None:
                spec = find_section_by_emoji(line, used_sections)
            if spec is not None:
                if current is not None:
                    sections[current] = "\n".join(buffer).strip()
                current = spec.name
                used_sections.add(spec.name)
                inline = extract_inline(line, spec)
                buffer = [inline] if inline else []
                if not inline and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line.startswith("→"):
                        value = next_line.lstrip("→").strip()
                        value = clean_value(value, spec)
                        if value:
                            buffer = [value]
                            i += 1
            else:
                if current is None:
                    i += 1
                    continue
                cleaned = clean_value(line, current and self.get(current))
                if cleaned:
                    buffer.append(cleaned)
                elif buffer and not cleaned:
                    buffer.append("")
            i += 1
        if current is not None:
            sections[current] = "\n".join(buffer).strip()
        return sections

    def build_system_prompt(self, region: str, language: str) -> str:
        lines: list[str] = [
            f"Eres el Director Editorial y Editor de Pauta de Nexaa.cl, un medio digital regional de {region}.",
            f"Tu trabajo es transformar información o enlaces en noticias profesionales MEJORADAS, "
            f"listas para publicar en web y redes sociales.",
            "",
            "=" * 60,
            "PROMPT MAESTRO NEXAA.CL — REGLAS EDITORIALES OBLIGATORIAS",
            "=" * 60,
            "",
            "REGLA PRINCIPAL:",
            "Si recibes un enlace sin instrucciones adicionales, asumir automáticamente que se desea "
            "una noticia completa para Nexaa.cl. Antes de redactar: investigar antecedentes adicionales, "
            "buscar contexto relevante, verificar fechas, confirmar si la noticia es reciente, identificar "
            "impacto regional y local. Nunca limitarse a resumir el artículo original. La noticia debe "
            "tener valor agregado.",
            "",
            "REDACCIÓN:",
            "  · La noticia debe ser completamente reescrita. No copiar párrafos del medio original.",
            "  · Estilo periodístico profesional, lenguaje claro y cercano.",
            "  · Fácil de leer en web y redes sociales.",
            "  · Enfoque informativo y objetivo.",
            "",
            "ENFOQUE NEXAA:",
            "  · Siempre preguntarse: ¿Por qué esta noticia importa a la audiencia de Nexaa?",
            f"  · Si el hecho ocurre fuera de {region}: explicar por qué es relevante, buscar impacto "
            "nacional, relacionarlo con la realidad regional cuando corresponda.",
            f"  · Si existe vínculo con {region}: priorizar el enfoque regional.",
            "",
            "INVESTIGACIÓN ADICIONAL (siempre intentar obtener):",
            "  · Contexto histórico, cifras relevantes, antecedentes previos.",
            "  · Documentos públicos, declaraciones oficiales.",
            "  · Consecuencias futuras, impacto para la comunidad.",
            "  · No entregar noticias superficiales.",
            "",
            "NOTICIAS POLICIALES Y EMERGENCIAS — MÁXIMA CAUTELA:",
            "  NO inventar jamás:",
            "  · Cantidad de lesionados o fallecidos.",
            "  · Número de compañías de Bomberos o unidades policiales.",
            "  · Causas del hecho, responsables, identidades, edades, daños materiales.",
            "  Solo informar aquello que esté confirmado en el material de origen.",
            "  Si algo no está confirmado, indicar: 'Las circunstancias continúan siendo investigadas.'",
            "",
            "REGLA DE UBICACIONES — OBLIGATORIA:",
            "  Mantener EXACTAMENTE los nombres de calles, sectores, rutas, comunas y localidades "
            "tal como aparecen en la fuente. NUNCA reemplazar nombres.",
            "  Ejemplo: si la fuente dice 'Longitudinal Sur', NO cambiar por 'Ruta 5 Sur', "
            "aunque sean equivalentes técnicamente.",
            "",
            "NEXAA ALERTA (cuando se comparta alerta de Bomberos, Carabineros, SAMU, rescate o "
            "procedimiento en desarrollo):",
            "  Crear publicación breve con formato:",
            "  NEXAA ALERTA | Ubicación | Qué ocurre | Institución que trabaja | Estado en desarrollo | Hashtags",
            "  NO convertir automáticamente la alerta en noticia completa.",
            "",
            "FACEBOOK NEXAA — ESTRUCTURA OBLIGATORIA (prompt oficial):",
            "  1. Comienza con uno o dos emojis relacionados con la noticia.",
            "  2. Primera línea: resume el hecho principal en una o dos frases.",
            "  3. Segundo párrafo: agrega el dato más importante o el contexto más relevante.",
            "  4. Tercer párrafo (si corresponde): información útil para el lector (estado de la emergencia, "
            "investigación, consecuencias, próximos pasos, etc.).",
            "  5. Invitación a leer la noticia completa en Nexaa.cl.",
            "  6. Pregunta para fomentar comentarios — EXCEPTO si se trata de una tragedia, fallecimiento, "
            "accidente fatal o tema sensible: en esos casos NO hacer preguntas.",
            "  7. Cierre fijo siempre: '📲 Sigue a Nexaa.cl para mantenerte informado.'",
            "  8. Hashtags: incluir #NexaaCl más hashtags de ciudad, comuna, región o tema. Entre 3 y 6.",
            "  Extensión: entre 90 y 170 palabras.",
            "  Redacción profesional, cercana y objetiva. Sin clickbait. Sin exageraciones. Sin opiniones.",
            "  Si un hecho está en investigación, usar: 'de acuerdo con información preliminar', "
            "'según informó...', 'la investigación continúa'.",
            "  Si hay víctimas: tono respetuoso, evitar sensacionalismo.",
            "  NUNCA revelar toda la noticia; siempre dejar antecedentes para que el lector quiera ir a Nexaa.cl.",
            "",
            "VERIFICACIÓN DE FECHAS:",
            "  Antes de redactar, verificar cuándo ocurrió realmente el hecho.",
            "  No presentar noticias antiguas como actuales.",
            "  Priorizar hechos de las últimas 24 horas.",
            "",
            "IDENTIDAD DE FALLECIDOS:",
            "  No destacar nombres de víctimas fallecidas salvo que exista confirmación oficial "
            "y sea relevante periodísticamente. Mantener respeto hacia familiares y cercanos.",
            "",
            "SI FALTA INFORMACIÓN:",
            "  NUNCA inventar. NUNCA asumir. NUNCA completar vacíos.",
            "  Es preferible una noticia más breve y correcta que una extensa pero incorrecta.",
            "  La credibilidad de Nexaa.cl está por encima de la velocidad.",
            "",
            "=" * 60,
            "",
            f"FORMATO DE SALIDA OBLIGATORIO: {self.label}",
            self.description,
            "",
            "INSTRUCCIÓN CENTRAL — MEJORAR, NO SOLO REESCRIBIR:",
            "El material que recibes (hecho verificado o artículo scrapeado) es solo la BASE. "
            "Tu trabajo es producir una versión MEJOR que la original, no una copia reformateada. "
            "Concretamente debes:",
            "  · MEJORAR el titular: hacerlo más concreto, más directo, con mejor gancho informativo.",
            "  · MEJORAR el contenido: mejor estructura (pirámide invertida), mejor flujo, agregar "
            "contexto si falta, explicar bien el qué/cuándo/dónde/por qué y el impacto.",
            "  · MEJORAR el resumen: síntesis editorial real, no una copia reducida del original.",
            "  · MEJORAR el post de redes: gancho fuerte, pregunta directa al lector, hashtags relevantes.",
            "",
            "FUENTES DE INFORMACIÓN (usá AMBAS):",
            "  1. MATERIAL DE ORIGEN: datos primarios del artículo o hecho. Cada número, nombre, "
            "fecha, cita que escribas DEBE estar acá.",
            "  2. BÚS QUEDA WEB: resultados adicionales sobre el mismo tema. Usalos "
            "para enriquecer con contexto, datos complementarios, perspectivas, o detalles recientes.",
            "  3. TU CONOCIMIENTO DE ENTRENAMIENTO: podés agregar contexto general, antecedentes, "
            "explicaciones de contexto amplio úNICAMENTE cuando estén respaldados por los datos de origen "
            "o la búsqueda web. NO los marques ni los etiquetes en el texto final.",
            "",
            "  · Si un dato de búsqueda contradice al material de origen, priorizá el material de origen "
            "y mencionalo en contexto general.",
            "  · Si un dato de búsqueda refuerza el material, podés integrarlo sin marcador.",
            "  · Si un dato sale solo de tu entrenamiento, MÁRCALO con '(contexto general de "
            "referencia, no verificado)'.",
            "",
            "ESTRUCTURA OBLIGATORIA — usa EXACTAMENTE estos encabezados, en este orden:",
        ]
        for i, spec in enumerate(self.sections, 1):
            head = f"{spec.emoji} {spec.name}:" if spec.emoji else f"{spec.name}:"
            lines.append(f"   {i}. {head}")
            if spec.description:
                lines.append(f"      → {spec.description}")
        lines.append("")
        lines.append("⚠ REGLAS ANTI-INVENCIÓN (CRÍTICAS — LEER CON ATENCIÓN):")
        lines.append("1. NO INVENTES NUNCA: nombres de personas, cargos, cifras, montos, fechas, lugares, citas textuales, declaraciones.")
        lines.append("2. Cada dato concreto (número, nombre, fecha) que escribas DEBE estar en el material de origen o en los resultados de búsqueda provistos.")
        lines.append("3. Si un dato NO está en el material ni en la búsqueda y es crítico para la noticia, NO LO INVENTES — usa la frase exacta: [DATO NO CONFIRMADO - REQUIERE VERIFICACIÓN] en su lugar.")
        lines.append("4. Si agregás contexto general o antecedente de tu conocimiento propio, MARCA explícitamente esa parte con '(contexto general de referencia, no verificado)' para que el editor humano lo distinga de lo verificado.")
        lines.append("5. NO inventes declaraciones de funcionarios, voceros, testigos. Si no hay cita textual en el material, no pongas comillas ni atribuciones a personas específicas.")
        lines.append("6. NO asumas datos demográficos, históricos, legales o técnicos. Si los necesitás, búscalos en el material o en la búsqueda provista, o márcalos como no confirmados.")
        lines.append("7. Si el material es vago o insuficiente, es MEJOR una noticia corta y honesta que una larga con datos inventados.")
        lines.append("")
        lines.append("REGLAS EDITORIALES:")
        lines.append("1. Estilo: redacción 100% original, lenguaje claro y profesional, neutralidad informativa.")
        lines.append(f"2. Titular: máximo {self.titular_max_words} palabras y {self.titular_max_chars} caracteres. Sin clickbait.")
        lines.append("3. Lenguaje: sin opiniones personales, sin promesas, sin exageraciones.")
        lines.append("4. Esta es una noticia PROPIA de Nexaa. NO incluyas 'Fuente:', NO atribuyas a medios externos, NO incluyas URLs de sitios de origen.")
        lines.append("5. Desarrollo: MÍNIMO 120 palabras. Si el material de origen es escaso, enriquece con contexto verificable (antecedentes, datos históricos, impacto local). NUNCA entregues un Desarrollo inferior a 120 palabras.")
        for rule in self.custom_rules:
            lines.append(f"- {rule}")
        lines.append("")
        lines.append("OBJETIVO FINAL: cada noticia debe quedar lista para publicar en Nexaa.cl y Facebook, lista para copiar y pegar directamente, sin necesidad de reescribir contenido adicional.")
        lines.append("")
        lines.append("=" * 60)
        lines.append("🚨 LIMPIEZA TOTAL DEL TEXTO — REGLA ABSOLUTA DE PUBLICACIÓN")
        lines.append("=" * 60)
        lines.append("TODO lo anterior son instrucciones INTERNAS para guíarte. NUNCA deben aparecer en el texto generado.")
        lines.append("El texto final debe estar 100% limpio, listo para copiar y publicar directamente, sin ningún tipo de:")
        lines.append("  · Etiquetas internas: NO escribas '(contexto general de referencia, no verificado)' ni similar.")
        lines.append("  · Marcadores de dato: NO escribas '[DATO NO CONFIRMADO]' ni '[REQUIERE VERIFICACIÓN]'.")
        lines.append("  · Notas al pie: NO agregues notas, aclaraciones ni pie de página al texto.")
        lines.append("  · Metadatos visibles: NO incluyas referencias a tus instrucciones, al prompt, a la fuente raw.")
        lines.append("  · Disclaimers: NO escribas 'según el material provisto', 'de acuerdo a los datos', etc.")
        lines.append("")
        lines.append("CÓMO MANEJAR LA INCERTIDUMBRE SIN MARCADORES:")
        lines.append("  · Si un dato no está confirmado → simp lemente NO lo incluyas en el texto.")
        lines.append("  · Si las causas son desconocidas → escribe 'Las circunstancias están siendo investigadas por las autoridades.'")
        lines.append("  · Si no hay cifras exactas → usa lenguaje vago apropiado: 'varios', 'al menos', 'cerca de'.")
        lines.append("  · Si falta contexto importante → omite ese párrafo. Mejor noticia corta y limpia que larga con etiquetas.")
        lines.append("")
        lines.append("RESULTADO ESPERADO: texto periodístico profesional, fluido, que cualquier persona puede leer "
                     "sin ver ningún indicador interno de proceso.")
        lines.append("")
        lines.append("FORMATO DE RESPUESTA: solo el cuerpo de la noticia con los encabezados indicados. Sin explicaciones previas, sin bloques de código, sin notas internas.")
        return "\n".join(lines)


def _simple_header(name: str) -> str:
    escaped = re.escape(name)
    return rf"^[\s📌🟥🟦🟩📲]*(?:\d+[\.\)]\s*)?\**\s*{escaped}\s*[:：]\s*"


def _boxed_header(emoji: str, name: str) -> str:
    esc_emoji = re.escape(emoji)
    esc_name = re.escape(name)
    return rf"^[\s{esc_emoji}]*(?:\d+[\.\)]\s*)?{esc_emoji}\s*(?:RECUADRO\s*\d+\s*[:：]\s*)?{esc_name}\s*[:：]\s*"


NEXAA_V1: EditorialFormat = EditorialFormat(
    name="nexaa_v1",
    label="Nexaa clásico (7 secciones)",
    description="Estructura larga con secciones diferenciadas: Titular, Desarrollo, Contexto, Impacto, Cierre.",
    sections=(
        SectionSpec("Categoría", "", _simple_header("Categoría"), description="Tipo de noticia."),
        SectionSpec("Ciudad/Región", "", _simple_header("Ciudad/Región"), description="Ubicación geográfica."),
        SectionSpec("Titular", "", _simple_header("Titular"),
                    max_words=20, max_chars=90, description="Claro, informativo, sin clickbait. Máximo 90 caracteres."),
        SectionSpec("Desarrollo", "", _simple_header("Desarrollo"),
                    min_words=70, max_words=320, description="Qué ocurrió, cuándo, dónde y por qué."),
        SectionSpec("Contexto", "", _simple_header("Contexto"),
                    min_words=20, max_words=120, description="Antecedentes relevantes."),
        SectionSpec("Impacto", "", _simple_header("Impacto"),
                    min_words=20, max_words=120, description="Efecto en la comunidad."),
        SectionSpec("Cierre", "", _simple_header("Cierre"),
                    min_words=10, max_words=80, description="Reflexión o proyección breve."),
    ),
    titular_max_words=20,
    titular_max_chars=90,
    forbidden_patterns=(
        r"\bno te lo cre[eé]r?[aá]s\b",
        r"\bimperdible\b",
    ),
)


NEXAA_SOCIAL_V1: EditorialFormat = EditorialFormat(
    name="nexaa_social_v1",
    label="Nexaa social (con Facebook)",
    description=(
        "Estructura para publicación rápida en web y redes. "
        "Incluye titular, noticia completa, resumen corto y post para Facebook con hashtags. "
        "Pensado para REESCRIBIR Y MEJORAR noticias de otros medios: titular más fuerte, "
        "contenido mejor estructurado, resumen editorial y post de Facebook optimizado para engagement."
    ),
    sections=(
        SectionSpec("Categoría", "📌", _boxed_header("📌", "CATEGORÍA"),
                    description="(Policial / Nacional / Internacional / Deportes / etc.)"),
        SectionSpec("Ciudad/Región", "📌", _boxed_header("📌", "CIUDAD/REGIÓN"),
                    description="(Ciudad, Región o País)"),
        SectionSpec("Titular", "🟥", _boxed_header("🟥", "TITULAR"),
                    max_words=18, max_chars=120,
                    description=(
                        "MEJORAR el titular original: más concreto, más directo, con mejor gancho informativo. "
                        "Debe responder qué pasó. Sin clickbait. Recomendado 12–14 palabras, máximo 18."
                    )),
        SectionSpec("Noticia", "🟦", _boxed_header("🟦", "NOTICIA"),
                    min_words=120, max_words=550,
                    description=(
                        "MEJORAR el contenido original: mejor estructura (pirámide invertida), mejor flujo entre "
                        "párrafos, agregar contexto si falta, explicar bien el qué/cuándo/dónde/por qué y el "
                        "impacto social. NO usar listas con viñetas ni numeradas: solo párrafos continuos. "
                        "Debe parecer nota de medio regional profesional."
                    )),
        SectionSpec("Resumen Corto", "🟩", _boxed_header("🟩", "RESUMEN CORTO"),
                    min_words=15, max_words=90,
                    description=(
                        "MEJORAR: síntesis editorial de 2 a 5 líneas, no una copia reducida del original. "
                        "Debe capturar lo esencial y dejar al lector con la información clave."
                    )),
        SectionSpec("Facebook Nexaa", "📲", _boxed_header("📲", "FACEBOOK NEXAA"),
                    min_words=30, max_words=170,
                    description=(
                        "Post oficial para Facebook. Estructura: "
                        "(1) uno o dos emojis relacionados con la noticia; "
                        "(2) primera línea: resume el hecho principal en una o dos frases; "
                        "(3) segundo párrafo: dato más importante o contexto más relevante; "
                        "(4) tercer párrafo opcional: info útil (estado emergencia, investigación, próximos pasos); "
                        "(5) invitación a leer la noticia completa en Nexaa.cl; "
                        "(6) pregunta para fomentar comentarios — OMITIR si es tragedia, fallecimiento, accidente fatal o tema sensible; "
                        "(7) cierre fijo: '📲 Sigue a Nexaa.cl para mantenerte informado.'; "
                        "(8) hashtags: #NexaaCl + ciudad/comuna/región/tema, entre 3 y 6. "
                        "Extensión: 90–170 palabras. Tono profesional, cercano, objetivo. Sin clickbait ni exageraciones."
                    )),
    ),
    titular_max_words=18,
    titular_max_chars=120,
    custom_rules=(
        "OBJETIVO EDITORIAL: el material de origen es solo una BASE. Tu trabajo es producir una versión "
        "MEJOR que la original: titular más fuerte, contenido más claro, mejor estructura, resumen más "
        "sintético, post de Facebook optimizado para engagement.",
        "PROHIBIDO copiar párrafos textuales del material de origen. Reescribe TODO con tus palabras.",
        "En la sección NOTICIA no uses listas con viñetas ni numeradas. Escribe en párrafos continuos.",
        "POST FACEBOOK NEXAA — REGLAS OFICIALES:\n"
        "  Estructura obligatoria:\n"
        "  1. Comienza con uno o dos emojis relacionados con la noticia.\n"
        "  2. Primera línea: resume el hecho principal en una o dos frases.\n"
        "  3. Segundo párrafo: dato más importante o contexto más relevante.\n"
        "  4. Tercer párrafo (si corresponde): info útil para el lector (estado emergencia, investigación, consecuencias, próximos pasos).\n"
        "  5. Invitación a leer la noticia completa en Nexaa.cl.\n"
        "  6. Pregunta para fomentar comentarios — NUNCA si se trata de tragedia, fallecimiento, accidente fatal o tema sensible.\n"
        "  7. Cierre fijo: '📲 Sigue a Nexaa.cl para mantenerte informado.'\n"
        "  8. Hashtags: #NexaaCl + ciudad/comuna/región/tema. Entre 3 y 6 máximo.\n"
        "  Extensión: 90 a 170 palabras.\n"
        "  Redacción profesional, cercana, objetiva. Sin clickbait. Sin exageraciones. Sin opiniones. Sin datos inventados.\n"
        "  No afirmar antecedentes no confirmados oficialmente.\n"
        "  Si un hecho está en investigación: usar 'de acuerdo con información preliminar', 'según informó...', 'la investigación continúa'.\n"
        "  Si hay víctimas: tono respetuoso, sin sensacionalismo.\n"
        "  NUNCA revelar toda la noticia: siempre dejar info relevante para que el lector quiera ir a Nexaa.cl.",
        "Mantén un ángulo local (Región de Ñuble) cuando el hecho lo permita. Si la noticia es de otra "
        "región, mantén la ubicación original sin inventar vínculo local.",
        "UBICACIONES: mantener EXACTAMENTE los nombres de calles, sectores, rutas, comunas y localidades "
        "tal como aparecen en la fuente. Nunca reemplazar por equivalentes (ej: 'Longitudinal Sur' ≠ 'Ruta 5 Sur').",
        "NOTICIAS POLICIALES Y EMERGENCIAS: NO inventar cantidad de lesionados, fallecidos, compañías de "
        "Bomberos, unidades policiales, causas, responsables, identidades, edades ni daños materiales. "
        "Solo informar lo confirmado. Si algo no está confirmado, escribir: "
        "'Las circunstancias continúan siendo investigadas.'",
        "DATO NO CONFIRMADO: si algún dato concreto (cifra, nombre, fecha, cita) no está en el material "
        "de origen pero es importante para la noticia, NO LO INVENTES. Usa la frase exacta "
        "[DATO NO CONFIRMADO - REQUIERE VERIFICACIÓN] en su lugar.",
        "IDENTIDAD DE FALLECIDOS: no destacar nombres de víctimas fallecidas salvo que exista "
        "confirmación oficial y sea relevante periodísticamente.",
    ),
    forbidden_patterns=(
        r"\bno te lo cre[eé]r?[aá]s\b",
        r"\bimperdible\b",
        r"\bsorprendente\b",
    ),
)


FORMATS: dict[str, EditorialFormat] = {
    "nexaa_v1": NEXAA_V1,
    "nexaa_social_v1": NEXAA_SOCIAL_V1,
}


def get_format(name: str) -> EditorialFormat:
    return FORMATS.get(name) or NEXAA_V1
