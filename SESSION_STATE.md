# Estado del proyecto Nexaa AI Editor (Guardado 2026-06-29)

## Lo que está funcionando
- ✅ Sistema completo de generación de noticias con IA (Groq, Mistral, Gemini)
- ✅ Scraping de URLs con DuckDuckGo para enriquecer contenido
- ✅ Interfaz web responsive (accesible desde celular)
- ✅ Dos modos: "Desde URL" y "Desde texto"
- ✅ Genera noticias en formato Nexaa (Titular, Noticia, Resumen Corto, Facebook)
- ✅ Selector de formato: "Nexaa social" o "Nexaa clásico"
- ✅ Botones de copiar por sección + "Copiar todo"
- ✅ Panel de revisión humana (Aprobar/Rechazar/Quitar)
- ✅ Parser flexible que maneja emojis, markdown bold, flechas
- ✅ Quality checker con palabras prohibidas anti-clickbait
- ✅ Sistema de búsqueda integrado (DuckDuckGo + RSS de medios Ñuble)
- ✅ 54 tests pasando
- ✅ Código subido a GitHub: https://github.com/robnaldopanos/notaro

## Lo que falta para poner online
- ⏳ Deploy a fly.io (script listo: `deploy_flyio.bat`)
- ⏳ Configurar API keys en el servidor
- ⏳ Crear volumen persistente para datos

## Archivos importantes para el deploy
- `deploy_flyio.bat` — script de deploy automático a fly.io
- `push_github.bat` — script para subir a GitHub
- `Dockerfile` — configuración de contenedor
- `fly.toml` — configuración de fly.io
- `.env` — API keys (ya configuradas localmente)

## API Keys configuradas
- Groq: (en .env local)
- Mistral: (en .env local)
- Gemini: (en .env local)

## Próximos pasos
1. Deploy a fly.io (doble click en `deploy_flyio.bat`)
2. Probar acceso desde el celular
3. Configurar dominio custom si se desea (ej: editor.nexaa.cl)
4. Integrar con la web principal de nexaa.cl

## Recordatorio: Deploy a fly.io (IMPORTANTE)
1. Abrir https://fly.io y crear cuenta gratis (email, sin tarjeta)
2. Doble click en `deploy_flyio.bat` en la carpeta del proyecto
3. Se abre el navegador → click en "Authorize" para dar permisos
4. Volver al script y esperar 5 minutos
5. La app queda en https://nexaa-editor.fly.dev (o similar)
6. Tu PC puede estar apagada, la app funciona 24/7
7. Gratis, sin límite para uso personal
8. Si querés dominio custom (ej: editor.nexaa.cl), compralo en NIC Chile y configurá en fly.io

## Comandos útiles
```powershell
# Iniciar servidor local
cd C:\Users\damian\Desktop\la clase\notero\nexaa-ai-editor
python -m nexaa.cli serve --host 0.0.0.0 --port 8000

# Deploy a fly.io
.\deploy_flyio.bat

# Subir a GitHub
.\push_github.bat

# Tests
python -m pytest tests/ -v
```

## Notas importantes
- El código está en: C:\Users\damian\Desktop\la clase\notero\nexaa-ai-editor
- Railway tiene el límite alcanzado este mes
- fly.io es la alternativa recomendada (gratis, sin límite)
- El script `deploy_flyio.bat` hace todo automáticamente (solo requiere autorización en el navegador)
- Las API keys están configuradas en `.env` y también se copian al deploy
- El sistema tiene backup automático del código en GitHub

## Documentación completa
- DEPLOY-SINGLE-USER.md — guía de deploy detallada
- README.md — documentación del proyecto
