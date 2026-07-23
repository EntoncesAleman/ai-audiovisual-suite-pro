@echo off
chcp 65001 >nul
title AI Audiovisual Suite Pro

cd /d "%~dp0"

echo.
echo ============================================================
echo   AI Audiovisual Suite Pro
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] No se encontro el entorno virtual (venv).
    echo Ejecuta: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

set GEMINI_API_KEY=AQ.Ab8RN6LAxbHghKCBu0pZ_hDUKSuocpPGWK8rt4INoBkU6H5Jvg

echo [1/2] API key configurada (termina en ...%GEMINI_API_KEY:~-4%)
echo [2/2] Arrancando servidor...
echo.
echo ============================================================
echo   Servidor corriendo en http://localhost:8000
echo   Abri http://localhost:8000 en el navegador (NO el archivo .html directamente).
echo   Ctrl+C para frenar el servidor.
echo ============================================================
echo.

uvicorn main:app --reload --host 0.0.0.0 --port 8000

echo.
echo El servidor se detuvo.
pause
