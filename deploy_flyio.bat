@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  NEXAA - DEPLOY A FLY.IO (SERVER 24/7)
echo ============================================
echo.

:: 1. Verificar Python
echo [1/7] Verificando Python...
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python no instalado.
    pause
    exit /b 1
)
echo OK
echo.

:: 2. Instalar flyctl
echo [2/7] Instalando flyctl...
where flyctl >nul 2>nul
if errorlevel 1 (
    powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
    if errorlevel 1 (
        echo ERROR instalando flyctl. Intenta manualmente:
        echo https://fly.io/docs/hands-on/install-flyctl/
        pause
        exit /b 1
    )
    echo flyctl instalado. Respawn needed...
    start "" "%~f0"
    exit /b 0
)
flyctl version
echo OK
echo.

:: 3. Login
echo [3/7] Iniciando sesion en fly.io (se abre el navegador)...
flyctl auth login
if errorlevel 1 (
    echo ERROR: login fallo. Intenta manualmente: flyctl auth login
    pause
    exit /b 1
)
echo OK
echo.

:: 4. Crear app
echo [4/7] Creando app en fly.io...
flyctl app create nexaa-editor --generate-name
if errorlevel 1 (
    echo ERROR creando app. Puede que ya exista, continuando...
)
echo OK
echo.

:: 5. Crear volumen
echo [5/7] Creando volumen persistente (1GB)...
flyctl volumes create nexaa_data --size 1 --region iad
if errorlevel 1 (
    echo ERROR creando volumen. Continuando...
)
echo OK
echo.

:: 6. Configurar env vars
echo [6/7] Configurando API keys...
echo.
echo Las API keys se leen automaticamente del archivo .env en tu PC.
echo Asegurate de que exista el archivo .env con las keys configuradas.
echo.
echo Presiona Enter para continuar...
pause >nul
echo OK
echo.
echo OK
echo.

:: 7. Deploy
echo [7/7] Desplegando... (puede tardar 3-5 minutos)
flyctl deploy --config fly.toml --yes
if errorlevel 1 (
    echo ERROR deployando. Revisa los logs:
    flyctl logs
    pause
    exit /b 1
)
echo.
echo ============================================
echo  LISTO! Tu app esta en fly.io
echo.
echo  URL: https://nexaa-editor.fly.dev
echo.
echo  Podes abrirla desde cualquier dispositivo.
echo  Tu PC puede estar apagada.
echo ============================================
echo.
pause
