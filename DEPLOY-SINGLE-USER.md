# Plan: deploy del editor IA a Railway (single user)

**Fecha de la conversación:** 2026-06-28
**Decisión:** deployar el editor de IA a Railway, accesible desde cualquier lugar, con UN solo usuario (vos). No multi-user. No auto-publicar. No iframe dentro de nexaa.cl.

---

## Por qué Railway y no otra cosa

Ya tenés cuenta en Railway y lo usás para nexaa.cl. Es el camino de menor fricción:
- Mismo proveedor que tu web actual
- HTTPS automático con custom domain
- Volúmenes persistentes (para `data/published/`, `data/pending/`, etc.)
- Free tier: $5 USD de crédito/mes alcanza para un servicio chico como este
- Deploy desde GitHub en 5 minutos

**Alternativas descartadas por ahora:** fly.io, Hetzner VPS, Oracle Cloud. Todas válidas pero Railway ya lo tenés montado.

---

## Lo que hay que hacer (paso a paso)

### 1. Preparar el proyecto (local, ~30 min)

- [ ] Crear `Dockerfile` en la raíz del proyecto
- [ ] Crear `.dockerignore` (excluir `data/`, `.env`, `__pycache__`, `*.log`, etc.)
- [ ] Verificar que `requirements.txt` esté completo
- [ ] Confirmar que el server arranca con `python -m nexaa.cli serve --host 0.0.0.0 --port $PORT` (Railway asigna el puerto via env var)

### 2. Subir a GitHub (si no está) (~10 min)

- [ ] Crear repo en GitHub
- [ ] Push del código (SIN el archivo `.env` con keys reales)
- [ ] El `.env.example` sí va al repo (es la plantilla)

### 3. Deploy en Railway (~5 min)

- [ ] En Railway: New Project → Deploy from GitHub → seleccionar el repo
- [ ] Railway detecta el Dockerfile automáticamente
- [ ] Configurar el puerto: Railway usa variable `$PORT`, hay que asegurarse que el server lea eso

### 4. Variables de entorno en Railway (~5 min)

En el dashboard de Railway, agregar las variables (NO en el código, en el panel de env vars del servicio):

```
GROQ_API_KEY=tu_groq_key_aqui
MISTRAL_API_KEY=tu_mistral_key_aqui
GEMINI_API_KEY=tu_gemini_key_aqui
```

Opcionales (si querés que funcione):
- `BRAVE_API_KEY=` (Brave no es gratis en su tier actual, dejalo vacío)
- `TOGETHER_API_KEY=` (no la activaste, podés dejarla vacía)

### 5. Volumen persistente (~5 min)

Railway por defecto **no persiste archivos entre deploys**. Si subís un nuevo deploy, se pierden los JSONs de `data/`.

- [ ] En Railway: agregar un volumen montado en `/app/data`
- [ ] Tamaño: 1 GB alcanza para miles de noticias

### 6. Dominio custom (opcional, ~10 min)

Si tenés `nexaa.cl` propio:
- [ ] Crear subdominio `editor.nexaa.cl` (o el nombre que prefieras)
- [ ] CNAME en tu DNS apuntando a Railway
- [ ] Railway auto-aprovisiona HTTPS con Let's Encrypt
- [ ] En Railway: agregar el dominio custom en la config del servicio

Si no tenés dominio propio, podés usar la URL que Railway te da (`xxx.railway.app`) y listo.

### 7. Probar end-to-end (~15 min)

- [ ] Abrir `https://editor.nexaa.cl/` (o la URL de Railway) en el navegador
- [ ] Pegar una URL de prueba (ej. una noticia de La Discusión)
- [ ] Verificar que genera y que se guarda en `data/pending/`
- [ ] Probar Aprobar/Rechazar/Quitar desde la UI
- [ ] Verificar que se crea el archivo en `data/published/`

---

## Workflow del periodista (después del deploy)

1. Abrir `https://editor.nexaa.cl/` en el navegador (celular o compu)
2. Pegar URL de La Discusión o un texto
3. La IA genera las 6 secciones (TITULAR, NOTICIA, RESUMEN CORTO, FACEBOOK NEXAA, etc.)
4. Refinar con el chat si hace falta
5. Aprobar → el archivo JSON se guarda en `data/published/`
6. Click "Copiar como HTML"
7. Pegar en el CMS de nexaa.cl como borrador
8. Editar si quiere, publicar

**Tiempo estimado por noticia:** 2-3 minutos.

---

## Lo que NO se hace (decisiones tomadas)

- ❌ **No multi-user** — solo vos. Si más adelante querés sumar un periodista, se agrega después.
- ❌ **No auto-publicar** — el copy-paste manual a nexaa.cl es el paso final. Más seguro.
- ❌ **No iframe dentro de nexaa.cl** — se accede por subdominio o link, no embebido.
- ❌ **No Brave Search API** — confirmé que su plan gratuito ya no es realmente gratis. Se queda integrado pero inactivo.
- ❌ **No Together/Mistral como providers extras** — ya tenés Groq + Mistral + Gemini, alcanza.

---

## Estado actual del proyecto (al 2026-06-28)

**Lo que funciona:**
- 54/54 tests pasando
- 3 IAs gratuitas activas: Groq, Mistral, Gemini
- Fallback automático entre providers
- Parser flexible (maneja markdown bold, flechas, formatos variantes)
- Quality checker con reglas anti-invención
- Aprobar/Rechazar/Quitar con UI
- Formato Nexaa social (6 secciones con Facebook)
- Temperatura 0.2 (más determinista)
- Búsqueda DuckDuckGo integrada (sin API, gratis)
- HTML/JS/CSS responsive, mobile-first
- Prompt con 3 fuentes: material de origen + búsqueda DDG + conocimiento del modelo, con marcadores
- PWA setup: NO hecho todavía (sería en un futuro)

**Versión actual del frontend:** v9 (visible en el badge de la UI)

**API keys configuradas en `.env`:**
- GROQ_API_KEY ✓
- MISTRAL_API_KEY ✓
- GEMINI_API_KEY ✓

**Lo que falta para deploy:**
- Dockerfile
- Subir a GitHub
- Crear servicio en Railway
- Configurar env vars y volumen persistente
- (Opcional) Dominio custom

---

## Preguntas pendientes que se dejaron abiertas

1. ¿El dominio `nexaa.cl` es tuyo? (para decidir si usar subdominio `editor.nexaa.cl` o URL de Railway)
2. ¿El proyecto del editor está en un repo Git (GitHub/GitLab)? (para deploy)
3. ¿Railway free tier o de pago? (free alcanza, pago da más margen)
4. ¿nexaa.cl corre en Railway como Docker, Nixpacks, o custom? (para integrar mejor)

---

## Riesgos a tener en cuenta cuando se haga el deploy

1. **Volumen persistente**: si no se monta el volumen, los `data/` se borran en cada deploy. **CRÍTICO no olvidarse.**
2. **API keys en env vars**: nunca commitear el `.env` con keys reales. Solo el `.env.example` va al repo.
3. **Rate limits**: el free tier de Groq es 30 req/min y 100K tokens/día. Suficiente para uso normal, pero si generás muchas noticias seguidas, puede hacer 429.
4. **Railway free tier**: el crédito mensual es de $5. Si el servicio consume más, se pausa o se cobra. Monitorear el uso.
5. **Scraping de medios**: Hetzner/AWS tienen mejor reputación que Railway/IPs cloud para scraping. Si nexaa.cl está en Railway y el scraping falla, considerar:
   - Usar un proxy residencial
   - O deployar el editor en otro servidor (VPS)
   - Por ahora: probar, si funciona, OK

---

## Si en el futuro se quiere algo más

- **Sumar un periodista**: agregar tabla `users` + auth (SQLite + bcrypt). Estimado: 2-3 días.
- **Auto-publicar**: webhook del editor → endpoint de nexaa.cl. Estimado: 1 día.
- **PWA para celular**: manifest.json + service worker. Estimado: 2 horas.
- **Cambiar a otro servidor**: el Dockerfile ya está, así que es solo deploy.

---

## Prompt sugerido para retomar este trabajo

Si arrancás de nuevo el chat o volvés después de varios días, pegale esto al otro chat:

```
Tengo un proyecto en C:\Users\damian\Desktop\la clase\notero\nexaa-ai-editor\
que es un editor de noticias con IA. Quiero deployarlo a Railway. Leé el
archivo DEPLOY-SINGLE-USER.md en la raíz del proyecto, después
DEPLOY-SINGLE-USER.md tiene todos los pasos y decisiones que tomamos.
```

---

## Contacto del proyecto

- **Ruta local:** `C:\Users\damian\Desktop\la clase\notero\nexaa-ai-editor\`
- **Versión:** 0.1.0
- **Estado:** funcional en localhost, listo para deploy a Railway
