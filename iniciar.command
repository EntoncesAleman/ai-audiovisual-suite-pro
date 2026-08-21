#!/bin/bash
# Lanzador + instalador para Mac: doble click en Finder (o "./iniciar.command"
# desde la Terminal). La primera vez instala lo que falte (ffmpeg, venv,
# dependencias, .env); las siguientes veces solo arranca el servidor.
# No hardcodea ninguna API key - todo va a .env, que main.py carga solo.
set -e
cd "$(dirname "$0")"

echo ""
echo "============================================================"
echo "  AI Audiovisual Suite Pro"
echo "============================================================"
echo ""

# Aviso si esta carpeta vive en un disco de red (ej. /Volumes/algo montado
# por SMB) en vez del disco local: instalar dependencias ahí puede ser
# mucho más lento, y en casos vistos, la instalación se corta a mitad de
# camino. No es un error, solo un aviso para que no parezca que se colgó.
PROJECT_DIR="$(pwd)"
case "$PROJECT_DIR" in
    /Volumes/*)
        VOL_ROOT="/Volumes/$(echo "$PROJECT_DIR" | cut -d/ -f3)"
        if mount | grep -E "^.* on ${VOL_ROOT} \((smbfs|afpfs|nfs)" >/dev/null 2>&1; then
            echo "⚠ Este proyecto está en un disco de red (${VOL_ROOT}), no en el disco"
            echo "  local de esta Mac. Instalar/arrancar puede tardar bastante más de lo"
            echo "  normal. Si se pone muy lento o se corta a mitad de la instalación, no"
            echo "  está roto: volvé a correr este mismo script, retoma donde quedó. Para"
            echo "  que ande más rápido, lo ideal sería copiar esta carpeta al disco local"
            echo "  (por ejemplo, a tu carpeta de Usuario) y correr todo desde ahí."
            echo ""
        fi
        ;;
esac

# 1) Homebrew: no lo instalamos solos (es un cambio grande del sistema),
# pero sí lo usamos para instalar ffmpeg/python si ya está.
if ! command -v brew &>/dev/null; then
    echo "[AVISO] No encontré Homebrew. Instalalo primero con:"
    echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo "y volvé a correr este script."
    read -p "Presioná Enter para cerrar..."
    exit 1
fi

# 2) ffmpeg/ffprobe: el backend los invoca por subprocess para cortar,
# convertir y escalar clips - nada de eso funciona sin esto.
if ! command -v ffmpeg &>/dev/null; then
    echo "[1/4] ffmpeg no encontrado. Instalando con Homebrew (puede tardar un poco)..."
    brew install ffmpeg
else
    echo "[1/4] ffmpeg encontrado ✓"
fi

# 3) python3
if ! command -v python3 &>/dev/null; then
    echo "[2/4] python3 no encontrado. Instalando con Homebrew..."
    brew install python
else
    echo "[2/4] python3 encontrado ✓"
fi

# 4) Entorno virtual (solo se crea la primera vez)
if [ ! -f "venv/bin/activate" ]; then
    echo "[3/4] No hay entorno virtual. Creándolo..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip -q || true  # falla a veces en discos de red, no es crítico
else
    echo "[3/4] Entorno virtual encontrado ✓"
    source venv/bin/activate
fi

# Reconciliar dependencias SIEMPRE (no solo la primera vez): si requirements.txt
# sumó algo nuevo (ej. Pillow para los subtítulos incrustados) en una versión
# más nueva del proyecto, un venv viejo que ya existía se tiene que enterar acá,
# no solo en un venv recién creado. pip no reinstala lo que ya está.
if ! pip install -r requirements.txt -q; then
    echo ""
    echo "⚠ La instalación de dependencias no terminó bien (puede pasar por disco"
    echo "  lento o corte de conexión). No arrancó nada roto: volvé a correr este"
    echo "  mismo script y va a retomar solo lo que falte instalar, no desde cero."
    read -p "Presioná Enter para cerrar..."
    exit 1
fi

# 5) .env con la API key de Gemini (solo la primera vez, si no existe)
if [ ! -f ".env" ]; then
    echo ""
    echo "[4/4] Falta el archivo .env con tu API key de Gemini."
    echo "Conseguila gratis en https://aistudio.google.com/apikey"
    echo -n "Pegala acá (no se va a mostrar en pantalla) y Enter: "
    read -s gemini_key
    echo ""
    if [ -z "$gemini_key" ]; then
        echo "⚠ No se ingresó ninguna clave. Creá .env a mano antes de reintentar"
        echo "  (ver COMANDOS_ARRANQUE.txt) - sin GEMINI_API_KEY el servidor no arranca."
        read -p "Presioná Enter para cerrar..."
        exit 1
    fi
    echo "GEMINI_API_KEY=$gemini_key" > .env
    echo "✓ .env creado. GROQ_API_KEY y API_ACCESS_KEY son opcionales - agregalas"
    echo "  a mano en .env después si las querés (ver COMANDOS_ARRANQUE.txt)."
else
    echo "[4/4] .env encontrado ✓"
fi

echo ""
echo "============================================================"
echo "  Servidor corriendo en http://localhost:8000"
echo "  Abrí http://localhost:8000 en el navegador (NO el archivo .html directamente)."
echo "  Ctrl+C para frenar el servidor."
echo "============================================================"
echo ""

uvicorn main:app --reload --host 0.0.0.0 --port 8000

echo ""
echo "El servidor se detuvo."
read -p "Presioná Enter para cerrar..."
