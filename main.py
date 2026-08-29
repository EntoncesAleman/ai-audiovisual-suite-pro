import sys
import os
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import shutil
import tempfile
import time
import hashlib
import hmac
import secrets
import json
import asyncio
import queue
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai
from google.genai import types as genai_types
import yt_dlp
import requests
from dotenv import load_dotenv
import premiere_export
import capcut_export

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================

app = FastAPI(title="AI Audiovisual Suite - Backend de Escaneo Continuo")


@app.middleware("http")
async def no_cache_static_assets(request, call_next):
    """
    StaticFiles no manda Cache-Control por default, así que el navegador
    puede quedarse con una versión vieja de un .js/.css en cache heurística
    (sobre todo con la pestaña abierta durante desarrollo activo, sin F5) y
    mostrar comportamiento inconsistente que después es muy difícil de
    diagnosticar a distancia. Forzamos revalidación siempre en /css y /js.
    """
    response = await call_next(request)
    if request.url.path.startswith("/css/") or request.url.path.startswith("/js/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # No usamos cookies para nada (la sesión viaja por header X-API-Key, ver
    # más abajo), así que no hace falta allow_credentials=True. Dejarlo en
    # True junto con allow_origins=["*"] es la combinación que habilita un
    # navegador a mandar credenciales cross-origin sin querer - sin uso real
    # hoy, pero mejor no dejarla activa para cuando haya sesiones de verdad.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Seguridad: API key solo desde variable de entorno
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "Falta GEMINI_API_KEY. Definila como variable de entorno antes de iniciar el servidor.\n"
        "Ejemplo (Linux/Mac): export GEMINI_API_KEY='tu_clave'\n"
        "Ejemplo (Windows PowerShell): $env:GEMINI_API_KEY='tu_clave'"
    )

client = genai.Client(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------
# Acceso a la API: la pantalla de login (login.html) todavía no tenía
# ningún backend real detrás - cualquiera con la URL podía pegarle a los
# endpoints de análisis/exportación (consumo de cuota Gemini/Groq, CPU,
# memoria) sin autenticarse. API_ACCESS_KEY es un secreto compartido
# simple (no hay usuarios/roles todavía) que el login pide una vez y
# guarda en el navegador, mandándolo de ahí en más como header X-API-KEY.
# Si no se configura esta variable de entorno, el chequeo queda
# desactivado (igual que el comportamiento de antes) para no romper
# despliegues existentes que todavía no la seteen a propósito.
API_ACCESS_KEY = os.getenv("API_ACCESS_KEY")

# ------------------------------------------------------------------
# Usuarios reales (username + password) con roles, en reemplazo del
# secreto único de arriba. Guardado en JSON planos junto al proyecto
# (mismo patrón simple que el resto de la app - nada de base de datos).
# Las contraseñas NUNCA se guardan en texto plano: se hashean con
# PBKDF2-HMAC-SHA256 + salt aleatoria por usuario.
# ------------------------------------------------------------------
USERS_DB_FILE = Path(__file__).parent / "users_db.json"
ACCESS_REQUESTS_FILE = Path(__file__).parent / "access_requests.json"

# Tokens de sesión emitidos por /auth/login: viven en memoria (se pierden
# si el servidor reinicia - igual que cualquier "mantener sesión iniciada"
# en un free tier que duerme, el navegador simplemente vuelve a pedir login).
_sessions: dict[str, dict] = {}


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_users() -> dict:
    return _load_json(USERS_DB_FILE, {})


def _save_users(users: dict):
    _save_json(USERS_DB_FILE, users)


def _load_requests() -> list:
    return _load_json(ACCESS_REQUESTS_FILE, [])


def _save_requests(reqs: list):
    _save_json(ACCESS_REQUESTS_FILE, reqs)


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex(), salt


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = _hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


def _bootstrap_superadmin():
    """Crea el superusuario inicial desde variables de entorno (ADMIN_USERNAME /
    ADMIN_PASSWORD en .env, nunca hardcodeado acá) si todavía no existe. No
    pisa la contraseña si el usuario ya fue creado (por si se cambió después
    con "Resetear contraseña" desde el panel)."""
    admin_user = os.getenv("ADMIN_USERNAME")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    if not admin_user or not admin_pass:
        print("⚠ ADMIN_USERNAME / ADMIN_PASSWORD no configuradas: no se crea ningún superusuario todavía.")
        return
    users = _load_users()
    if admin_user in users:
        return
    pw_hash, salt = _hash_password(admin_pass)
    users[admin_user] = {
        "password_hash": pw_hash,
        "salt": salt,
        "role": "SUPERADMIN",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_users(users)
    print(f"✓ Superusuario inicial creado: {admin_user}")


_bootstrap_superadmin()


def require_api_key(x_api_key: str | None = Header(default=None)):
    """Dependency de FastAPI para los endpoints protegidos: exige un token de
    sesión válido (emitido por /auth/login) o, por compatibilidad, la
    API_ACCESS_KEY estática si está configurada. Si no hay ningún usuario
    creado todavía y tampoco API_ACCESS_KEY, no bloquea nada (servidor recién
    instalado, sin login configurado)."""
    if x_api_key:
        session = _sessions.get(x_api_key)
        if session:
            return session
        if API_ACCESS_KEY and x_api_key == API_ACCESS_KEY:
            return {"username": "legacy", "role": "USER"}
    if not _load_users() and not API_ACCESS_KEY:
        return None
    raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Iniciá sesión de nuevo.")


def require_superadmin(x_api_key: str | None = Header(default=None)):
    session = require_api_key(x_api_key)
    if not session or session.get("role") != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Necesitás permisos de administrador.")
    return session

# Groq (opcional): último recurso cuando TODOS los modelos Gemini agotaron su cuota diaria.
# Sin diarización de speakers reales (Whisper no la hace), pero mantiene la app funcionando
# en vez de fallar por completo. Si no está seteada, este fallback simplemente se salta.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile")

# URL del servicio bgutil-ytdlp-pot-provider (deploy separado en Render con la imagen
# brainicism/bgutil-ytdlp-pot-provider). Genera los PO Tokens que YouTube exige para
# no mostrar "Sign in to confirm you're not a bot", sin necesitar cookies ni login.
# Si no está seteada, yt-dlp sigue funcionando igual que antes (sin este plugin).
POT_PROVIDER_BASE_URL = os.getenv("POT_PROVIDER_BASE_URL")

# Carpeta de cacheo: si ya se analizó un video con el mismo hash, devolvemos el resultado guardado
CACHE_DIR = Path(os.getenv("CACHE_DIR", tempfile.gettempdir())) / "audiovisual_suite_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EXPORT_DIR = Path(tempfile.gettempdir()) / "audiovisual_suite_exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Cache de videos originales (junto al cache de resultados de analisis): permite
# exportar clips despues sin volver a descargar de la URL ni re-subir el archivo.
VIDEO_CACHE_DIR = CACHE_DIR / "videos"
VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_video_path(cache_key: str):
    """Devuelve la ruta al video cacheado para este cache_key, o None si no esta."""
    if not cache_key:
        return None
    matches = list(VIDEO_CACHE_DIR.glob(f"{cache_key}.*"))
    return str(matches[0]) if matches else None


def cache_video_store(cache_key: str, source_path: str):
    """
    Mueve el video original a la carpeta de cache (no lo copia: evita duplicar
    el escrito a disco). A partir de ahi, exportar clips lo reusa directo sin
    volver a descargar ni pedir que se re-suba.
    """
    if not cache_key or not os.path.exists(source_path):
        return
    ext = Path(source_path).suffix or ".mp4"
    dest = VIDEO_CACHE_DIR / f"{cache_key}{ext}"
    try:
        # Si ya habia un cacheado (re-analisis del mismo video), lo reemplazamos.
        if dest.exists():
            dest.unlink()
        shutil.move(source_path, str(dest))
    except Exception as e:
        print(f"⚠ No se pudo cachear el video: {e}")

# Configs de plataforma para exportación de video: (ancho, alto, max_dur_seg o None)
PLATFORM_CONFIGS: dict[str, tuple] = {
    "ig_reel_15s":        (1080, 1920, 15),
    "ig_reel_30s":        (1080, 1920, 30),
    "ig_reel_60s":        (1080, 1920, 60),
    "ig_story_15s":       (1080, 1920, 15),
    "ig_feed_4x5":        (1080, 1350, 60),
    "ig_carrusel_clips":  (1080, 1080, 60),
    "ig_carrusel_placas": (1080, 1080, None),
    "tiktok_15s":         (1080, 1920, 15),
    "tiktok_30s":         (1080, 1920, 30),
    "tiktok_60s":         (1080, 1920, 60),
    "youtube_short":      (1080, 1920, 60),
    "twitter_x_clip":     (1280, 720,  140),
}

CAROUSEL_PLATFORMS = {"ig_carrusel_clips", "ig_carrusel_placas"}

print(f"✓ Backend activo. Cacheo en: {CACHE_DIR}")

_WRITABLE_COOKIES_FILE = Path(tempfile.gettempdir()) / "cookies_writable.txt"


def _find_cookies_file():
    """
    Busca cookies.txt en las ubicaciones posibles según dónde se esté corriendo:
    - /etc/secrets/cookies.txt: ruta garantizada por Render para Secret Files (solo lectura).
    - junto a main.py: uso local o Secret Files montados en la raíz de la app.
    yt-dlp reescribe el cookiejar después de cada uso, así que si el original es de
    solo lectura (caso Render) lo copiamos a un archivo escribible en /tmp y devolvemos ese.
    Devuelve el Path a usar, o None si no hay cookies en ningún lado.
    """
    if _WRITABLE_COOKIES_FILE.exists():
        return _WRITABLE_COOKIES_FILE

    candidates = [
        Path("/etc/secrets/cookies.txt"),
        Path(__file__).parent / "cookies.txt",
    ]
    for candidate in candidates:
        if candidate.exists():
            shutil.copy(candidate, _WRITABLE_COOKIES_FILE)
            return _WRITABLE_COOKIES_FILE
    return None


# Aviso sobre métodos de autenticación para Drive/YouTube
_cookies_file_check = _find_cookies_file()
if _cookies_file_check:
    print(f"✓ Cookies encontradas en: {_cookies_file_check} (se usarán para archivos privados)")
else:
    print("ℹ Sin cookies.txt en la carpeta. Para archivos privados de Drive se intentará leer cookies de Chrome.")
    print("  Si Drive te da 403, exportá cookies.txt con la extensión 'Get cookies.txt LOCALLY' y guardalo acá.")


class UrlInput(BaseModel):
    url: str
    engine: str = "auto"  # "auto" (Gemini + Groq de respaldo) | "gemini" | "groq"


# ============================================================
# UTILIDADES DE CACHEO
# ============================================================

def file_hash(path: str, chunk_size: int = 65536) -> str:
    """Hash SHA-256 del archivo, para identificar videos idénticos."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def url_hash(url: str) -> str:
    """Hash de una URL (más rápido que descargar dos veces para comparar)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _safe_upload_filename(filename: str) -> str:
    """
    Devuelve solo el nombre base de un filename recibido en un upload
    multipart, sin separadores de path. Ese filename lo controla quien
    hace el request, así que nunca hay que usarlo tal cual para construir
    una ruta en disco: os.path.join descarta la ruta base si el segundo
    argumento es una ruta absoluta (ej. "/etc/algo"), y un ".." en medio
    del nombre permite escapar del directorio temporal igual. Ambos casos
    permitían escritura de archivo arbitraria antes de este chequeo.
    """
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or set(name) <= {"."}:
        name = "upload"
    return name


def deterministic_export_id(*parts: str) -> str:
    """
    ID de exportación estable a partir de la fuente + los clips pedidos (en
    vez de un uuid random). Así, si el server se reinicia a mitad de un
    export y el usuario le da "Generar" de nuevo con los mismos clips, cae
    en la MISMA carpeta y puede saltear los clips que ya se habían cortado,
    en vez de arrancar de cero. El video fuente en /tmp sobrevive un reinicio
    por OOM (no un redeploy), asi que esto le saca provecho a eso.
    """
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def cache_get(key: str):
    """Recupera resultado cacheado si existe."""
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def cache_set(key: str, data: dict):
    """Guarda un resultado en cache."""
    cache_file = CACHE_DIR / f"{key}.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ No se pudo guardar cache: {e}")


# ============================================================
# DESCARGA DE VIDEO
# ============================================================

# Detectamos qué método de autenticación usar para Drive/YouTube
# Orden de prioridad:
#   1. Si existe ./cookies.txt → lo usamos (método más confiable)
#   2. Si no, probamos leer cookies de Chrome directamente
#   3. Si tampoco funciona, descarga anónima
PROJECT_DIR = Path(__file__).parent

# El HTML fue refactorizado a CSS/JS separados en carpetas propias; los servimos
# como archivos estáticos para que <link>/<script type="module"> puedan cargarlos.
app.mount("/css", StaticFiles(directory=str(PROJECT_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(PROJECT_DIR / "js")), name="js")
app.mount("/assets", StaticFiles(directory=str(PROJECT_DIR / "assets")), name="assets")


def _build_ydl_opts_with_auth(base_opts: dict) -> list:
    """
    Devuelve una lista de configuraciones de yt-dlp para probar en orden.
    La descarga anónima va primero: con el POT Token provider (si está
    configurado) alcanza para YouTube público sin cookies, y así no se
    pierde tiempo probando cookies que sabemos que se vencen solas.
    Las estrategias con cookies quedan de fallback al final, para casos
    como archivos privados de Google Drive donde sí hacen falta.
    """
    strategies = [("descarga anónima", dict(base_opts))]

    # Fallback: sin forzar player_client. Streams que acaban de terminar
    # ("post_live" - YouTube todavía no los reprocesó como VOD normal)
    # fallan con "This live event has ended" cuando forzamos una lista fija
    # de clients (android/tv/ios o web/tv/android); dejar que yt-dlp use
    # sus propios defaults sí los resuelve - confirmado reproduciendo el
    # error contra un video real. Va segundo (antes que cookies, que según
    # yt-dlp#15274/#16507 empeoran este caso puntual) para no perder la
    # ventaja anti-bot del override en videos normales.
    base_youtube_args = base_opts.get('extractor_args', {}).get('youtube', {})
    if base_youtube_args.get('player_client'):
        opts_default_clients = dict(base_opts)
        extractor_args_default = dict(base_opts['extractor_args'])
        youtube_args_default = dict(base_youtube_args)
        youtube_args_default.pop('player_client', None)
        extractor_args_default['youtube'] = youtube_args_default
        opts_default_clients['extractor_args'] = extractor_args_default
        strategies.append(("player_client por defecto (stream recién terminado)", opts_default_clients))

    # Fallback: archivo cookies.txt exportado del navegador (Drive privado, etc.)
    cookies_file = _find_cookies_file()
    if cookies_file:
        opts = dict(base_opts)
        opts['cookiefile'] = str(cookies_file)
        strategies.append(("cookies.txt en carpeta del proyecto", opts))

    # Fallback: cookies leídas directamente de Chrome (solo tiene sentido en local)
    opts_chrome = dict(base_opts)
    opts_chrome['cookiesfrombrowser'] = ('chrome',)
    strategies.append(("cookies de Chrome", opts_chrome))

    return strategies


async def run_blocking_with_heartbeat(func, *args, interval: float = 20.0, **kwargs):
    """
    Corre `func` (bloqueante) en un thread aparte y va yieldeando
    ("heartbeat", None) cada `interval` segundos mientras espera, terminando
    con ("result", valor) o ("error", excepcion).

    Sirve para pasos largos y silenciosos (descargar el video, subir/procesar
    con Gemini) donde antes no salía ningún byte por el stream SSE durante
    varios minutos: el proxy de Render puede matar la conexión por verla
    inactiva, y el frontend perdía todo el progreso sin aviso. Mandando un
    comentario de keep-alive periódico evitamos ese corte.
    """
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            break
        yield ("heartbeat", None)
    try:
        result = task.result()
        yield ("result", result)
    except Exception as e:
        yield ("error", e)


async def run_blocking_with_progress(func, *args, poll_interval: float = 1.0, heartbeat_interval: float = 20.0, **kwargs):
    """
    Como run_blocking_with_heartbeat, pero además le pasa a `func` un kwarg
    `progress_callback` (thread-safe: `func` corre en un thread aparte) con
    el que puede ir reportando progreso real mientras trabaja - pensado
    para los progress_hooks de yt-dlp, que antes solo se veían en la
    consola del server y nunca llegaban al frontend.

    yt-dlp llama al hook varias veces por segundo durante una descarga por
    fragmentos; mandar cada callback individual por SSE sería spam, así
    que acá se juntan y se yieldea como mucho un ("progress", mensaje) por
    `poll_interval` segundos (el más reciente de la tanda). Si no hay ni
    progreso ni resultado por `heartbeat_interval`, cae al mismo
    keep-alive que la versión sin progreso.
    """
    progress_queue: "queue.Queue[str]" = queue.Queue()

    def progress_callback(message: str):
        progress_queue.put(message)

    task = asyncio.create_task(asyncio.to_thread(func, *args, progress_callback=progress_callback, **kwargs))
    loop = asyncio.get_event_loop()
    last_activity = loop.time()
    while True:
        done, _ = await asyncio.wait({task}, timeout=poll_interval)
        latest = None
        while True:
            try:
                latest = progress_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            last_activity = loop.time()
            yield ("progress", latest)
        elif done:
            break
        elif loop.time() - last_activity >= heartbeat_interval:
            last_activity = loop.time()
            yield ("heartbeat", None)
    try:
        result = task.result()
        yield ("result", result)
    except Exception as e:
        yield ("error", e)


# ------------------------------------------------------------------
# Límite de concurrencia y guard de memoria para operaciones pesadas
# ------------------------------------------------------------------
# En el free tier de Render (512MB) dos análisis/exports pesados corriendo
# en simultáneo son casi garantía de que el sistema operativo mate el
# proceso por quedarse sin memoria - eso se vio como un reinicio "limpio"
# del servidor a mitad de una operación (sin traceback, porque lo mata el
# OS desde afuera). Este semáforo fuerza que solo una operación pesada
# (analizar o exportar) corra a la vez; MAX_CONCURRENT_HEAVY_OPS es
# configurable por si esto corre en una máquina con más RAM.
MAX_CONCURRENT_HEAVY_OPS = int(os.getenv("MAX_CONCURRENT_HEAVY_OPS", "1"))
_heavy_ops_semaphore = asyncio.Semaphore(MAX_CONCURRENT_HEAVY_OPS)

try:
    import psutil
except ImportError:
    psutil = None

# Umbral de memoria libre por debajo del cual preferimos frenar ANTES de
# arrancar ffmpeg/subir a Gemini, con un mensaje claro, en vez de dejar
# que el sistema operativo mate el proceso a mitad de camino.
MIN_FREE_MB_FOR_HEAVY_OP = int(os.getenv("MIN_FREE_MB_FOR_HEAVY_OP", "150"))


async def _wait_for_heavy_slot(interval: float = 15.0):
    """
    Espera su turno para el semáforo de operaciones pesadas, yieldeando
    cada `interval` segundos mientras hace cola (heartbeat) para que el
    watchdog de stall del frontend (sin bytes por STREAM_STALL_MS) no
    salte creyendo que la conexión se colgó. Al terminar, el semáforo
    queda tomado (llamar siempre a _heavy_ops_semaphore.release() en un
    finally del lado del caller).
    """
    task = asyncio.create_task(_heavy_ops_semaphore.acquire())
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            return
        yield True


def _memory_headroom_error() -> str | None:
    """
    Devuelve un mensaje de error si la memoria libre está por debajo del
    umbral, o None si hay margen suficiente (o si psutil no está
    instalado, en cuyo caso no bloqueamos nada - mismo comportamiento
    que antes de este chequeo).
    """
    if psutil is None:
        return None
    try:
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        return None
    if available_mb < MIN_FREE_MB_FOR_HEAVY_OP:
        return (
            f"Memoria disponible baja en el servidor ({available_mb:.0f}MB libres, "
            f"mínimo {MIN_FREE_MB_FOR_HEAVY_OP}MB). Esperá un momento y reintentá, "
            f"o probá con menos clips a la vez."
        )
    return None


def _format_yt_progress(d: dict) -> str | None:
    """
    Arma un mensaje legible a partir del dict que yt-dlp le pasa a
    progress_hooks. No usamos los `_percent_str`/`_speed_str`/etc. que trae
    el dict (vienen con códigos ANSI de color pensados para terminal, no
    para mostrar en la UI) - se calculan a mano desde los campos numéricos.
    """
    status = d.get('status')
    if status == 'downloading':
        downloaded = d.get('downloaded_bytes') or 0
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        parts = []
        if total:
            parts.append(f"{downloaded / total * 100:.1f}% de {total / 1024 / 1024:.1f}MB")
        elif downloaded:
            parts.append(f"{downloaded / 1024 / 1024:.1f}MB")
        speed = d.get('speed')
        if speed:
            parts.append(f"a {speed / 1024:.0f}KB/s")
        eta = d.get('eta')
        if eta is not None:
            mins, secs = divmod(int(eta), 60)
            parts.append(f"ETA {mins:02d}:{secs:02d}")
        frag_idx, frag_count = d.get('fragment_index'), d.get('fragment_count')
        if frag_idx and frag_count:
            parts.append(f"(frag {frag_idx}/{frag_count})")
        return "Descargando " + " ".join(parts) if parts else None
    if status == 'finished':
        return "Descarga completa, procesando archivo..."
    return None


def _download_youtube(url: str, format_selector: str, outtmpl_suffix: str = "", progress_callback=None) -> str:
    extractor_args = {}
    if POT_PROVIDER_BASE_URL:
        # Le dice al plugin bgutil-ytdlp-pot-provider (instalado via requirements.txt)
        # donde esta el servicio que genera los PO Tokens. Los PO Tokens son
        # especificos del cliente 'web' - si restringimos player_client a
        # android/tv/ios (como haciamos antes) el proveedor nunca se llega a usar.
        # Con el proveedor activo dejamos 'web' primero para que se aproveche.
        extractor_args['youtubepot-bgutilhttp'] = {'base_url': [POT_PROVIDER_BASE_URL]}
        extractor_args['youtube'] = {'player_client': ['web', 'tv', 'android']}
    else:
        # Sin proveedor de tokens, 'web' dispara el chequeo anti-bot casi siempre;
        # los clientes de apps moviles/TV usan otra verificacion sin cookies/login.
        extractor_args['youtube'] = {'player_client': ['android', 'tv', 'ios']}

    base_opts = {
        'format': format_selector,
        'outtmpl': os.path.join(tempfile.gettempdir(), f'%(id)s{outtmpl_suffix}.%(ext)s'),
        'noplaylist': True,
        # Permite a yt-dlp descargar el script solver de YouTube (deno) para resolver
        # el challenge de firma; sin esto solo consigue miniaturas, nunca contenido real.
        'remote_components': ['ejs:github'],
        'extractor_args': extractor_args,
    }
    if progress_callback is not None:
        def _hook(d):
            msg = _format_yt_progress(d)
            if msg:
                progress_callback(msg)
        base_opts['progress_hooks'] = [_hook]

    strategies = _build_ydl_opts_with_auth(base_opts)
    last_error = None

    for strategy_name, ydl_opts in strategies:
        try:
            print(f"   Intentando descarga con: {strategy_name}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                path = ydl.prepare_filename(info)
                print(f"   ✓ Descarga exitosa usando: {strategy_name}")
                return path
        except Exception as e:
            err_str = str(e)
            last_error = e
            is_auth_issue = (
                "403" in err_str or "401" in err_str or "Forbidden" in err_str or "cookie" in err_str.lower()
            )
            # "This live event has ended" / "No video formats found" en un
            # stream que acaba de terminar son específicos de qué
            # player_client se usó (ver estrategia "player_client por
            # defecto" arriba) - vale la pena seguir probando en vez de
            # cortar en el primer intento.
            is_live_ended = (
                "live event has ended" in err_str.lower() or "no video formats found" in err_str.lower()
            )
            if is_auth_issue or is_live_ended:
                reason = "permisos" if is_auth_issue else "stream recién terminado"
                print(f"   ⚠ Falló ({reason}): {err_str[:120]}")
                continue
            print(f"   ✗ Error no relacionado con autenticación: {err_str[:200]}")
            raise HTTPException(status_code=400, detail=f"Error al descargar: {err_str}")

    # Si llegamos acá, todos los métodos fallaron
    raise HTTPException(
        status_code=403,
        detail=(
            f"No se pudo descargar con ningún método de autenticación. "
            f"Último error: {str(last_error)[:200]}. "
            f"Soluciones: (1) Verificá que el archivo de Drive tenga permiso 'Cualquier persona con el enlace'. "
            f"(2) Exportá cookies.txt desde Chrome y guardalo en la carpeta del proyecto. "
            f"(3) Bajá el archivo manualmente y subilo con 'Subir Local'."
        )
    )


def download_youtube_video(url: str, progress_callback=None) -> str:
    """Descarga el video completo. Usar solo para exportar (cortar/convertir clips) - para
    transcribir no hace falta, ver download_youtube_audio."""
    return _download_youtube(
        url,
        'best[height<=480][ext=mp4]/best[height<=480]/bestvideo[height<=480]+bestaudio/best[height<=720]/best',
        progress_callback=progress_callback,
    )


def download_youtube_audio(url: str, progress_callback=None) -> str:
    """
    Descarga SOLO el audio, para transcribir. La desgrabación nunca usó el
    video en sí (_process_single_video_file igual extrae el audio antes de
    subirlo a Gemini/Groq), así que bajar el video entero para analizar era
    puro desperdicio de ancho de banda, tiempo y memoria - con videos largos
    esto era lo que hacía que el análisis tardara de más y, al exportar
    después, hacía más probable quedarse sin los 512MB del free tier de
    Render. Sufijo distinto en el nombre de archivo para no pisar una
    descarga de video en curso del mismo id.
    """
    return _download_youtube(
        url,
        'bestaudio[ext=m4a]/bestaudio/best',
        outtmpl_suffix='_audio',
        progress_callback=progress_callback,
    )


# ============================================================
# PROCESAMIENTO CON GEMINI
# ============================================================

# Configuración de procesamiento por tramos:
# Si el video supera CHUNK_THRESHOLD_MIN minutos, lo dividimos en partes
# de CHUNK_DURATION_MIN minutos cada una y procesamos secuencialmente.
# Cada tramo cabe holgado en los 8192 tokens base de salida del modelo,
# pero igual subimos el max_output_tokens al máximo permitido.
CHUNK_THRESHOLD_MIN = int(os.getenv("CHUNK_THRESHOLD_MIN", "15"))   # umbral para activar tramos
CHUNK_DURATION_MIN = int(os.getenv("CHUNK_DURATION_MIN", "10"))    # duración de cada tramo
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "65536"))   # tope de salida por llamada

# Lista de modelos Gemini en orden de preferencia (fallback automático al agotar cuota diaria).
# Cada modelo tiene su propia cuota diaria separada en el free tier, así que sumar más
# modelos a la lista aumenta la capacidad total gratuita antes de que la app deje de funcionar.
# gemini-3.1-flash-lite tiene ~500 req/día (vs ~20 req/día del resto), por eso se dejó
# último como red de contención de alta capacidad en vez de primero.
GEMINI_MODELS = [
    m.strip() for m in os.getenv(
        "GEMINI_MODELS",
        # gemini-2.0-flash, gemini-2.0-flash-lite y gemini-2.5-flash-lite
        # fueron dados de baja por Google (404 NOT_FOUND permanente,
        # "no longer available") - sacados de la lista default para no
        # desperdiciar reintentos contra modelos que nunca van a responder.
        # gemini-2.5-flash sigue vivo pero Google ya anunció su baja para
        # el 16/10/2026 - si vuelve a dar 404 después de esa fecha, sacarlo
        # de acá también.
        # gemini-3.7-flash (el más nuevo) NO va primero a propósito: probado
        # a mano el 2026-08-25 contra audio real, devuelve 0 candidatos +
        # 503 "high demand" de forma consistente - muy probablemente por ser
        # recién salido y todavía en rollout inestable del lado de Google.
        # Como no es un 404 "modelo muerto" ni una cuota agotada, el código
        # no lo descarta solo: si queda primero, gasta los 3 intentos + el
        # fallback contra un modelo roto antes de rendirse. Se lo deja
        # último, probar de nuevo a ponerlo más arriba en unas semanas.
        "gemini-2.5-flash,gemini-3.6-flash,gemini-3.5-flash,"
        "gemini-3.1-flash-lite,gemini-3.7-flash"
    ).split(",") if m.strip()
]

# Modelos con cuota diaria agotada en esta sesión del servidor
_exhausted_models: set = set()


def get_video_duration_seconds(video_path: str) -> float:
    """
    Devuelve la duración del video en segundos usando ffprobe.
    Si ffprobe no está disponible, devuelve 0 (que hace que se procese entero).
    """
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except FileNotFoundError:
        print("⚠ ffprobe no encontrado. Instalá ffmpeg para procesamiento por tramos. Continúo sin partir.")
    except Exception as e:
        print(f"⚠ ffprobe falló: {e}")
    return 0.0


def inspect_media_file(file_path: str) -> dict:
    """
    Inspecciona un archivo y devuelve qué streams tiene (video/audio),
    duración, codec, tamaño y si parece ser 'audio renombrado como video'.
    Útil para decidir si conviene convertir antes de subir a Gemini.
    Devuelve un dict con: has_video, has_audio, duration_minutes,
    size_mb, extension, suggest_conversion, reason.
    """
    import subprocess
    import json as _json

    info = {
        "has_video": False,
        "has_audio": False,
        "duration_minutes": 0,
        "size_mb": 0,
        "extension": os.path.splitext(file_path)[1].lower(),
        "suggest_conversion": False,
        "reason": "",
        "video_codec": None,
        "audio_codec": None,
        "filename": os.path.basename(file_path),
    }

    # Tamaño
    try:
        info["size_mb"] = round(os.path.getsize(file_path) / (1024 * 1024), 2)
    except Exception:
        pass

    # Duración
    info["duration_minutes"] = round(get_video_duration_seconds(file_path) / 60, 2)

    # Streams con ffprobe
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-print_format", "json", file_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            data = _json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    info["has_video"] = True
                    info["video_codec"] = stream.get("codec_name")
                elif stream.get("codec_type") == "audio":
                    info["has_audio"] = True
                    info["audio_codec"] = stream.get("codec_name")
    except FileNotFoundError:
        info["reason"] = "ffprobe no instalado - no se puede analizar"
        return info
    except Exception as e:
        info["reason"] = f"Error al inspeccionar: {e}"
        return info

    # Heurística de sugerencia
    # Caso típico: archivo con extensión de video pero sin stream de video → audio renombrado
    video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
    if info["extension"] in video_extensions and not info["has_video"] and info["has_audio"]:
        info["suggest_conversion"] = True
        info["reason"] = (
            f"El archivo tiene extensión {info['extension']} (de video) pero solo contiene "
            f"audio ({info['audio_codec']}). Google a veces rechaza esta inconsistencia. "
            f"Convertir a audio limpio (.m4a) suele resolverlo."
        )
    elif not info["has_video"] and not info["has_audio"]:
        info["reason"] = "El archivo no parece tener streams de audio ni video."
    elif info["has_video"] and info["has_audio"]:
        info["reason"] = f"Video con audio detectado correctamente ({info['video_codec']} + {info['audio_codec']})."
    elif info["has_audio"] and not info["has_video"]:
        info["reason"] = f"Audio puro detectado ({info['audio_codec']}). Compatible con Gemini."

    return info


def convert_to_clean_audio(input_path: str, output_path: str = None, mode: str = "copy") -> str:
    """
    Convierte un archivo a audio limpio en formato .m4a o .mp3.
    mode='copy': copia el stream de audio sin re-codificar (rapidísimo, formato .m4a).
    mode='mp3': re-codifica a MP3 mono 16kHz 64kbps (más liviano, máxima compatibilidad).
    Devuelve la ruta del archivo generado.
    """
    import subprocess

    if output_path is None:
        base = os.path.splitext(input_path)[0]
        ext = ".m4a" if mode == "copy" else ".mp3"
        output_path = f"{base}_clean{ext}"

    if mode == "copy":
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", input_path,
            "-vn", "-acodec", "copy",
            output_path
        ]
    else:  # mp3
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", input_path,
            "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
            output_path
        ]

    print(f"   Convirtiendo a audio limpio (mode={mode}): {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        # Si el modo copy falla (por ejemplo formato incompatible), reintentamos con mp3
        if mode == "copy":
            print(f"   ⚠ Copy falló: {result.stderr[:200]}. Reintentando con re-encode mp3...")
            return convert_to_clean_audio(input_path, mode="mp3")
        raise Exception(f"ffmpeg conversión falló: {result.stderr[:300]}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise Exception("El archivo convertido quedó vacío.")

    print(f"   ✓ Conversión OK: {output_path} ({round(os.path.getsize(output_path)/(1024*1024), 2)} MB)")
    return output_path


def split_video_in_chunks(video_path: str, chunk_seconds: int) -> list:
    """
    Divide un video en tramos de chunk_seconds usando ffmpeg (sin re-codificar).
    Devuelve una lista de tuplas (offset_segundos, ruta_archivo_tramo).
    """
    import subprocess
    duration = get_video_duration_seconds(video_path)
    if duration <= 0:
        return [(0, video_path)]  # fallback: video entero

    chunks = []
    base, ext = os.path.splitext(video_path)
    offset = 0
    idx = 0
    while offset < duration:
        chunk_path = f"{base}_chunk{idx:02d}{ext}"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", str(offset),
                "-i", video_path,
                "-t", str(chunk_seconds),
                "-c", "copy",  # sin re-encode = rapidísimo
                chunk_path
            ], check=True, timeout=300)
            chunks.append((offset, chunk_path))
        except subprocess.CalledProcessError as e:
            print(f"⚠ Error partiendo tramo {idx}: {e}. Intento con re-encode...")
            # Reintento con re-encode por si el copy falla en el corte exacto
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-ss", str(offset),
                    "-i", video_path,
                    "-t", str(chunk_seconds),
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac",
                    chunk_path
                ], check=True, timeout=600)
                chunks.append((offset, chunk_path))
            except Exception as e2:
                print(f"⚠ Re-encode también falló: {e2}. Salto este tramo.")
        offset += chunk_seconds
        idx += 1
    return chunks


def _collapse_repeated_runs(text: str, max_repeats: int = 3, max_phrase_words: int = 4) -> str:
    """
    Colapsa una misma palabra O frase corta (hasta `max_phrase_words` palabras)
    repetida muchas veces seguidas a un máximo de `max_repeats` repeticiones.
    Es el remedio para la alucinación típica de los modelos de transcripción
    durante tramos de música/silencio/audio poco claro, donde quedan "trabados"
    repitiendo lo último que entendieron cientos de veces (ej: "no, no, no, ..."
    x300, o "que venga, que venga, que venga, ..." x60). El prompt ya les pide
    que no lo hagan, pero la instrucción sola no siempre alcanza.
    Deja intactas las repeticiones cortas normales (2-3 veces, típicas del
    habla real para dar énfasis, como un "que venga, que venga!" real).
    """
    import re

    pattern = re.compile(
        r'\b((?:\w+[\s,]+){0,%d}\w+)\b((?:[\s,.:;!?-]+\1\b){3,})' % (max_phrase_words - 1),
        re.IGNORECASE
    )

    def _replace(match):
        phrase = match.group(1)
        sep_match = re.match(r'[\s,.:;!?-]+', match.group(2))
        sep = sep_match.group(0) if sep_match else ' '
        return (phrase + sep) * (max_repeats - 1) + phrase

    # Aplicar hasta que no cambie más: una racha larga puede necesitar más
    # de una pasada para terminar de colapsar del todo.
    prev = None
    result = text
    while prev != result:
        prev = result
        result = pattern.sub(_replace, result)
    return result


def shift_timestamps_in_transcript(text: str, offset_seconds: int) -> str:
    """
    Suma offset_seconds a cada timestamp del transcript.
    Soporta los dos formatos que Gemini puede devolver:
      - Formato solicitado:  'TIMESTAMP: MM:SS'
      - Formato real Gemini: 'MM:SS: Speaker:' al inicio de línea
    """
    import re

    def to_seconds(ts: str) -> int:
        parts = [int(p) for p in ts.strip().split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return 0

    def to_ts(secs: int) -> str:
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def replace_keyword_ts(match):
        try:
            new_secs = to_seconds(match.group(1)) + offset_seconds
            return f"TIMESTAMP: {to_ts(new_secs)}"
        except Exception:
            return match.group(0)

    def replace_inline_ts(match):
        # match.group(1) = el timestamp, match.group(2) = ': ' que sigue
        try:
            new_secs = to_seconds(match.group(1)) + offset_seconds
            return f"{to_ts(new_secs)}{match.group(2)}"
        except Exception:
            return match.group(0)

    # Formato 1: TIMESTAMP: MM:SS (o HH:MM:SS)
    text = re.sub(
        r"TIMESTAMP:\s*(\d{1,2}:\d{2}(?::\d{2})?)",
        replace_keyword_ts,
        text
    )

    # Formato 2: MM:SS: o HH:MM:SS: al inicio de cada línea (lo que Gemini realmente devuelve)
    text = re.sub(
        r"^(\d{1,2}:\d{2}(?::\d{2})?)(:\s)",
        replace_inline_ts,
        text,
        flags=re.MULTILINE
    )

    return text


PROMPT_ESCANEO = (
    "You are receiving an AUDIO FILE (MP3) from a RADIO PROGRAM. Your task is to transcribe ALL human speech "
    "from the first second to the very last second — do NOT stop early.\n\n"
    "IMPORTANT — MUSICAL BREAKS: This radio program contains musical breaks of several minutes at various points "
    "(not just at the start). Whenever you encounter music, jingles, instrumental segments, or any non-speech audio "
    "— whether at the beginning, middle, or end of the file — skip them COMPLETELY and silently. "
    "Jump directly to the next moment where a human voice speaks and continue transcribing from there. "
    "NEVER produce any output entry for a music segment. "
    "NEVER fill a music gap by repeating a word or short phrase (such as 'no, no, no' or "
    "'que venga, que venga, que venga' or any filler). "
    "If a section has no speech at all, produce nothing for it.\n\n"
    "CRITICAL RULE — NO EMPTY ENTRIES: Every entry in your output MUST contain actual dialogue text in the "
    "DIALOGUE field. If you cannot hear what is being said in a segment, skip that segment entirely. "
    "NEVER produce a DIALOGUE field that is blank or empty.\n\n"
    "CRITICAL RULE — ACCURATE TIMESTAMPS: Each entry MUST have its correct time position in the audio. "
    "Do NOT place every entry at 00:00. Timestamps must reflect when the speech actually occurs.\n\n"
    "CRITICAL: Do not stop or skip sections because of:\n"
    "- Commercial breaks or pauses (e.g. 'be right back', jingles, bumpers)\n"
    "- Background music, radio IDs, station sound signatures\n"
    "- Silence or gaps in conversation\n"
    "- Repetitive or similar-sounding segments\n"
    "- Transition music between blocks\n"
    "Continue transcribing ALL speech until you reach the absolute end of the audio file.\n\n"
    "CRITICAL RULE FOR SPEAKERS: Assign a unique numbered label to each distinct voice you identify. "
    "Use 'Speaker 1', 'Speaker 2', 'Speaker 3', etc. If you can identify their actual name from the conversation, "
    "use it instead (e.g., 'Speaker 1 (Juan)'). Maintain the same label consistently throughout the entire transcription. "
    "Never use a generic 'Speaker' label for multiple people.\n\n"
    "Provide the output strictly as plain text using the following format for each event found (do not use markdown blocks or JSON):\n"
    "TIMESTAMP: [Give the exact timestamp, e.g., 04:12]\n"
    "SPEAKER: [Numbered speaker label, e.g., Speaker 1, Speaker 2, or Speaker 1 (Name)]\n"
    "DIALOGUE: [The exact literal speech or dialogue text — NEVER leave this empty]\n"
    "---"
)

# Prompt de fallback: más corto y permisivo, para casos donde el escaneo completo falla.
PROMPT_ESCANEO_FALLBACK = (
    "Transcribe the dialogue of this RADIO PROGRAM AUDIO FILE in chronological order from start to finish. "
    "This program has musical breaks of several minutes at various points throughout the audio. "
    "Whenever you encounter music, jingles, or non-speech audio — at any point — skip it entirely and silently. "
    "Move directly to the next human voice. NEVER write anything for music segments, "
    "and NEVER fill music gaps with a repeated word or short phrase like 'no, no, no' or "
    "'que venga, que venga, que venga' or any filler.\n"
    "Do NOT stop at commercial breaks or pauses — continue until the very last second of speech.\n"
    "IMPORTANT: Each DIALOGUE entry MUST contain actual spoken text — never leave it blank or empty.\n"
    "Assign each distinct voice a numbered label: Speaker 1, Speaker 2, etc. "
    "Keep the same label for the same person throughout.\n"
    "For each segment use this plain text format:\n"
    "TIMESTAMP: MM:SS\n"
    "SPEAKER: Speaker 1\n"
    "DIALOGUE: text\n"
    "---\n"
    "Cover all speech in the audio. Plain text only, no JSON, no markdown."
)


def _extract_text_safely(response):
    """
    Intenta sacar texto de la respuesta de Gemini incluso cuando .text falla.
    El error 'Failed to convert server response to JSON' suele venir porque
    la respuesta tiene candidatos sin contenido válido o se cortó.
    """
    # 1. Intento normal
    try:
        if response and response.text:
            return response.text
    except Exception as e:
        print(f"⚠ response.text falló: {e}")

    # 2. Intento manual recorriendo candidates/parts
    try:
        if response and hasattr(response, "candidates") and response.candidates:
            chunks = []
            for cand in response.candidates:
                if not cand or not getattr(cand, "content", None):
                    continue
                parts = getattr(cand.content, "parts", []) or []
                for part in parts:
                    txt = getattr(part, "text", None)
                    if txt:
                        chunks.append(txt)
            if chunks:
                return "\n".join(chunks)
    except Exception as e:
        print(f"⚠ Extracción manual falló: {e}")

    # 3. Diagnóstico: imprimir qué devolvió Gemini para entender qué pasó
    try:
        finish = None
        safety = None
        if response and hasattr(response, "candidates") and response.candidates:
            c0 = response.candidates[0]
            finish = getattr(c0, "finish_reason", None)
            safety = getattr(c0, "safety_ratings", None)
        print(f"⚠ Diagnóstico Gemini → finish_reason={finish}, safety_ratings={safety}")
    except Exception:
        pass

    return None


INTER_CHUNK_DELAY = int(os.getenv("INTER_CHUNK_DELAY", "30"))  # segundos entre tramos (evita cuota 429)


def _is_meaningful_transcript(text: str) -> bool:
    """
    Devuelve True si la respuesta de Gemini tiene contenido real de diálogo.
    Rechaza:
      - Respuestas donde todos los timestamps son '00:00' (Gemini no pudo ubicarse en el tiempo)
      - Respuestas donde >70% de las entradas DIALOGUE están vacías
    """
    import re
    if not text or len(text.strip()) < 100:
        return False

    # Check 1: DIALOGUE: format — porcentaje de entradas con texto real
    dialogue_lines = [l for l in text.splitlines() if l.upper().startswith("DIALOGUE:")]
    if len(dialogue_lines) >= 3:
        non_empty = [l for l in dialogue_lines if len(l.split(":", 1)[-1].strip()) > 3]
        ratio = len(non_empty) / len(dialogue_lines)
        if ratio < 0.30:
            print(f"   ⚠ Calidad insuficiente: solo {len(non_empty)}/{len(dialogue_lines)} entradas DIALOGUE tienen texto ({ratio:.0%}).")
            return False

    # Check 2: detectar si todos los timestamps son 00:00
    ts_matches = re.findall(r'(?:^|\n)(\d{1,2}:\d{2}(?::\d{2})?)\s*:', text)
    if len(ts_matches) >= 5:
        all_zero = all(ts in ("00:00", "0:00", "00:00:00") for ts in ts_matches)
        if all_zero:
            print(f"   ⚠ Todos los {len(ts_matches)} timestamps son 00:00 — Gemini no pudo ubicarse. Descartando.")
            return False

    # Check 3: detectar contenido repetitivo — cubre DIALOGUE: y SPEAKER:/Speaker N:
    # (antes solo buscaba "DIALOGUE:" y nunca matcheaba el formato "SPEAKER X: ...")
    from collections import Counter
    speaker_lines = [l for l in text.splitlines()
                     if l.upper().startswith("DIALOGUE:")
                     or re.search(r'(?i)\bspeaker\b[\w\s]*:', l)]
    raw = (" ".join(re.split(r'(?i)(?:\bspeaker\b[\w\s]*:|dialogue:)', l, maxsplit=1)[-1].strip()
                    for l in speaker_lines)
           if speaker_lines else text)
    words = re.findall(r'\b\w+\b', raw.lower())
    if len(words) >= 20:
        top_word, top_count = Counter(words).most_common(1)[0]
        ratio = top_count / len(words)
        if ratio > 0.60:
            print(f"   ⚠ Contenido repetitivo detectado: '{top_word}' ocupa {ratio:.0%} del diálogo. Descartando.")
            return False

    # Check 4: mismo timestamp repetido > 15 veces = hallucination (Gemini atascado en pausa musical)
    ts_only_lines = [l.strip() for l in text.splitlines()
                     if re.match(r'^\d{1,2}:\d{2}(?::\d{2})?$', l.strip())]
    if ts_only_lines:
        ts_counter = Counter(ts_only_lines)
        max_ts, max_count = ts_counter.most_common(1)[0]
        if max_count > 15:
            print(f"   ⚠ Timestamp '{max_ts}' repetido {max_count} veces — hallucination detectada. Descartando.")
            return False

    return True


def _is_daily_quota_exhausted(e: Exception) -> bool:
    """True si la cuota DIARIA del modelo está agotada (no sirve esperar, hay que cambiar de modelo)."""
    msg = str(e)
    is_quota_error = "429" in msg or "RESOURCE_EXHAUSTED" in msg
    is_daily = "PerDay" in msg or "per_day" in msg.lower() or "daily" in msg.lower()
    return is_quota_error and is_daily


def _is_model_unavailable(e: Exception) -> bool:
    """
    True si el modelo fue dado de baja por Google (404 NOT_FOUND, "no longer
    available"). Igual que la cuota diaria agotada: no sirve reintentar,
    hay que descartar el modelo para el resto de esta sesión del server.
    """
    msg = str(e)
    return "404" in msg and ("NOT_FOUND" in msg or "not found" in msg.lower() or "no longer available" in msg.lower())


def _get_active_model() -> str | None:
    """Devuelve el primer modelo de GEMINI_MODELS que no tenga la cuota diaria agotada, o None."""
    for model in GEMINI_MODELS:
        if model not in _exhausted_models:
            return model
    return None


def _is_quota_error(e: Exception) -> bool:
    """Detecta si la excepción es un error 429 / RESOURCE_EXHAUSTED de Gemini."""
    msg = str(e).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def _extract_retry_delay(e: Exception, default: int = 65) -> int:
    """Extrae el retryDelay sugerido por Gemini del mensaje de error (si lo trae)."""
    import re
    match = re.search(r"retry[_ ]?delay['\"]?\s*[=:]\s*['\"]?(\d+)", str(e), re.IGNORECASE)
    if match:
        return int(match.group(1)) + 5  # +5 seg de margen
    return default


# Modelo dedicado de ASR con diarización real (AudioTranscriptionConfig),
# a diferencia de GEMINI_MODELS que son LLMs de propósito general "actuando"
# de transcriptor siguiendo las instrucciones de PROMPT_ESCANEO. En teoría
# da mejor diarización que pedírsela a un LLM en el prompt.
# Probado a mano el 2026-08-26 (recién anunciado ese mismo día): en la
# mayoría de los intentos devuelve 503 "high demand"; cuando sí responde,
# el texto viene incompleto/cortado antes de cubrir el audio entero. No es
# confiable todavía - por eso _transcribe_with_gemini_dedicated() no
# reintenta nada acá adentro, cualquier falla cae rápido al resto de
# GEMINI_MODELS en vez de insistir.
GEMINI_TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")


def _transcribe_with_gemini_dedicated(uploaded_file) -> str:
    """
    Transcribe con el modelo dedicado GEMINI_TRANSCRIBE_MODEL en vez de
    pedirle a un LLM de propósito general que actúe de transcriptor. No
    sigue el formato TIMESTAMP/SPEAKER/DIALOGUE de PROMPT_ESCANEO (es ASR
    puro, no un modelo de instrucciones) - se envuelve el texto crudo en
    ese formato como una sola entrada, igual que hace
    _transcribe_with_groq_whisper cuando Whisper no devuelve segments.
    Sin reintentos propios: una sola llamada, cualquier falla se propaga
    para que el caller pase directo a GEMINI_MODELS.
    """
    response = client.models.generate_content(
        model=GEMINI_TRANSCRIBE_MODEL,
        contents=[uploaded_file],
        config=genai_types.GenerateContentConfig(
            max_output_tokens=32768,
            audio_transcription_config=genai_types.AudioTranscriptionConfig(
                diarization=True,
                mode=genai_types.AudioTranscriptionConfigMode.VERBATIM,
                word_timestamp=True,
            ),
        ),
    )
    text = _extract_text_safely(response)
    if not text or len(text.strip()) < 50:
        raise Exception(f"{GEMINI_TRANSCRIBE_MODEL} devolvió texto vacío o demasiado corto.")
    return f"TIMESTAMP: 00:00\nSPEAKER: Speaker 1\nDIALOGUE: {text.strip()}\n---"


def _call_gemini_with_retry(uploaded_file, max_cycles: int = 2):
    """
    Llama a Gemini recorriendo GEMINI_MODELS en orden. Ante CUALQUIER
    falla del modelo actual (excepción de cualquier tipo - no solo
    cuota/404 como antes - o una respuesta sin contenido útil) pasa
    directo al siguiente modelo de la lista en vez de reintentar el
    mismo. Antes un error transitorio (ej: 503 "high demand" de un
    modelo recién salido) quedaba reintentando con backoff exponencial
    contra ESE modelo hasta agotar los intentos, sin llegar a probar
    nunca los otros 4 sanos de la lista.
    - Cuota diaria agotada / 404 (dado de baja) → se descarta el modelo
      para el resto de la sesión, como antes (nunca tiene sentido
      reintentarlo).
    - Rate limit por minuto (429) → espera el retry_delay sugerido
      (con techo) y pasa igual al siguiente modelo - no se queda
      esperando ahí si hay otro modelo con cuota propia disponible.
    - Cualquier otro error, o respuesta vacía/de mala calidad → pasa
      directo al siguiente modelo, sin esperar.
    Da hasta `max_cycles` vueltas completas a la lista (un modelo con un
    problema transitorio puede andar bien en la segunda vuelta) antes de
    caer al prompt de fallback simplificado.
    """
    last_error = None

    for cycle in range(1, max_cycles + 1):
        models_this_cycle = [m for m in GEMINI_MODELS if m not in _exhausted_models]
        if not models_this_cycle:
            raise Exception(
                f"Todos los modelos de Gemini tienen la cuota diaria agotada "
                f"({', '.join(GEMINI_MODELS)}). Último error: {last_error}."
            )
        for model in models_this_cycle:
            try:
                print(f"   Ciclo {cycle}/{max_cycles} [modelo: {model}] (max_output_tokens={MAX_OUTPUT_TOKENS})...")
                response = client.models.generate_content(
                    model=model,
                    contents=[uploaded_file, PROMPT_ESCANEO],
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        temperature=0.2,
                    ),
                )
                text = _extract_text_safely(response)
                if text and len(text.strip()) > 50 and _is_meaningful_transcript(text):
                    return text
                print(f"   ⚠ [{model}] devolvió respuesta vacía o sin contenido de calidad. Probando siguiente modelo...")
            except Exception as e:
                last_error = e
                if _is_daily_quota_exhausted(e):
                    print(f"   ⚠ Cuota DIARIA agotada para [{model}]. Descartándolo para el resto de esta sesión...")
                    _exhausted_models.add(model)
                elif _is_model_unavailable(e):
                    print(f"   ⚠ [{model}] fue dado de baja por Google (404). Descartándolo para el resto de esta sesión...")
                    _exhausted_models.add(model)
                elif _is_quota_error(e):
                    wait = min(_extract_retry_delay(e), 20)
                    print(f"   ⚠ Rate limit temporal (429) en [{model}]. Esperando {wait}s antes de probar el siguiente...")
                    time.sleep(wait)
                else:
                    print(f"   ⚠ [{model}] error: {type(e).__name__}: {e}. Probando siguiente modelo...")

    # Último recurso: prompt corto con el modelo activo
    model = _get_active_model()
    if model is None:
        raise Exception(
            f"Todos los modelos de Gemini tienen la cuota diaria agotada. Último error: {last_error}."
        )
    print(f"   Cambiando a prompt de fallback simplificado [modelo: {model}]...")
    try:
        response = client.models.generate_content(
            model=model,
            contents=[uploaded_file, PROMPT_ESCANEO_FALLBACK],
            config=genai_types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.2,
            ),
        )
        text = _extract_text_safely(response)
        if text and len(text.strip()) > 50 and _is_meaningful_transcript(text):
            return text
        if text:
            print("   ⚠ Fallback devolvió respuesta pero sin calidad suficiente.")
    except Exception as e:
        last_error = e
        if _is_daily_quota_exhausted(e) or _is_model_unavailable(e):
            _exhausted_models.add(model)
        print(f"   ⚠ Fallback también falló: {e}")

    raise Exception(
        f"Gemini no devolvió contenido utilizable tras {max_cycles} ciclo(s) por "
        f"{len(GEMINI_MODELS)} modelo(s). Último error: {last_error}."
    )


def _call_gemini_text(prompt: str, max_cycles: int = 2) -> str:
    """
    Llama a Gemini con un prompt de solo texto (sin archivo adjunto) - se usa
    para el "prompt libre": en vez de que la persona copie el prompt a
    ChatGPT/Claude y pegue la respuesta a mano, la app le manda el prompt
    (transcripción + instrucciones) directo a Gemini y devuelve el resultado.
    Mismo mecanismo de rotación por ciclo completo que _call_gemini_with_retry
    (ver ese docstring) - si Gemini agota TODA la lista, el caller
    (/generate-clip-suggestions) tiene su propio fallback a Groq.
    """
    last_error = None

    for cycle in range(1, max_cycles + 1):
        models_this_cycle = [m for m in GEMINI_MODELS if m not in _exhausted_models]
        if not models_this_cycle:
            raise Exception(
                f"Todos los modelos de Gemini tienen la cuota diaria agotada "
                f"({', '.join(GEMINI_MODELS)}). Último error: {last_error}."
            )
        for model in models_this_cycle:
            try:
                print(f"   [prompt libre] Ciclo {cycle}/{max_cycles} [modelo: {model}]...")
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        temperature=0.4,
                    ),
                )
                text = _extract_text_safely(response)
                if text and len(text.strip()) > 10:
                    return text
                print(f"   ⚠ [{model}] devolvió respuesta vacía o muy corta. Probando siguiente modelo...")
            except Exception as e:
                last_error = e
                if _is_daily_quota_exhausted(e):
                    print(f"   ⚠ Cuota DIARIA agotada para [{model}]. Descartándolo para el resto de esta sesión...")
                    _exhausted_models.add(model)
                elif _is_model_unavailable(e):
                    print(f"   ⚠ [{model}] fue dado de baja por Google (404). Descartándolo para el resto de esta sesión...")
                    _exhausted_models.add(model)
                elif _is_quota_error(e):
                    wait = min(_extract_retry_delay(e), 20)
                    print(f"   ⚠ Rate limit temporal (429) en [{model}]. Esperando {wait}s antes de probar el siguiente...")
                    time.sleep(wait)
                else:
                    print(f"   ⚠ [{model}] error: {type(e).__name__}: {e}. Probando siguiente modelo...")

    raise Exception(f"Gemini no devolvió respuesta tras {max_cycles} ciclo(s). Último error: {last_error}.")


def _seconds_to_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def _transcribe_with_groq_whisper(audio_path: str) -> str:
    """
    Último recurso cuando se agotó la cuota diaria de TODOS los modelos Gemini.
    Transcribe el audio con Whisper Large v3 vía la API gratuita de Groq
    (https://console.groq.com, 2000 req/día en el free tier) y devuelve el
    texto en el mismo formato TIMESTAMP/SPEAKER/DIALOGUE que usa el resto del pipeline.
    Whisper no diariza hablantes reales, así que todo queda como 'Speaker 1'.
    """
    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (os.path.basename(audio_path), f)},
            data={"model": GROQ_WHISPER_MODEL, "response_format": "verbose_json"},
            timeout=120,
        )
    response.raise_for_status()
    data = response.json()

    segments = data.get("segments") or []
    if not segments:
        text = (data.get("text") or "").strip()
        if not text:
            raise Exception("Groq Whisper no devolvió texto ni segmentos.")
        return f"TIMESTAMP: 00:00\nSPEAKER: Speaker 1\nDIALOGUE: {text}\n---"

    lines = []
    for seg in segments:
        dialogue = (seg.get("text") or "").strip()
        if not dialogue:
            continue
        lines.append(
            f"TIMESTAMP: {_seconds_to_mmss(seg.get('start', 0))}\n"
            f"SPEAKER: Speaker 1\n"
            f"DIALOGUE: {dialogue}\n---"
        )
    if not lines:
        raise Exception("Groq Whisper devolvió segmentos sin texto utilizable.")
    return "\n".join(lines)


def _call_groq_text(prompt: str) -> str:
    """
    Último recurso para el "prompt libre" (/generate-clip-suggestions)
    cuando Gemini agotó TODA su lista de modelos (todos los ciclos de
    _call_gemini_text). Mismo espíritu que _transcribe_with_groq_whisper
    (Groq como red de contención, no como motor principal) pero para
    generación de texto: usa la API de chat completions de Groq
    (compatible con OpenAI) con Llama 3.3 70B en vez de un modelo Gemini.
    """
    if not GROQ_API_KEY:
        raise Exception("GROQ_API_KEY no está configurada en el servidor.")
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": GROQ_TEXT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
    if not text:
        raise Exception("Groq (Llama 3.3 70B) no devolvió texto.")
    return text


def _normalize_engine(value: str) -> str:
    """Clampea el motor pedido a uno de los 3 válidos, "auto" si viene vacío o inválido."""
    value = (value or "auto").strip().lower()
    return value if value in ("auto", "gemini", "groq") else "auto"


def _process_single_video_file(video_path: str, engine: str = "auto") -> str:
    """
    Extrae el audio del archivo (drásticamente menos tokens que video) y lo
    transcribe. `engine` controla qué motor usar:
    - "auto" (default): Gemini primero, Groq como red de contención si Gemini falla del todo.
    - "gemini": solo Gemini (diarización real de speakers), sin fallback a Groq.
    - "groq": solo Groq Whisper (rápido, cuota más generosa, sin diarización real).
    Audio usa ~32 tokens/seg vs ~290 tokens/seg de video — cabe en el free tier.
    """
    # Extraer audio SIEMPRE antes de mandar nada a transcribir - nunca se
    # sube el video completo (para archivos locales, source_path acá puede
    # ser un video de verdad, a diferencia del flujo por URL que ya baja
    # solo audio). Menos tokens/tiempo de subida, y evita mandarle un video
    # entero a Gemini/Groq si la extracción llegara a fallar en silencio.
    audio_path = convert_to_clean_audio(video_path, mode="mp3")
    path_to_upload = audio_path
    size_mb = round(os.path.getsize(audio_path) / (1024 * 1024), 2)
    print(f"   Audio extraído: {os.path.basename(audio_path)} ({size_mb} MB).")

    try:
        if engine == "groq":
            if not GROQ_API_KEY:
                raise Exception("Se pidió usar solo Groq pero GROQ_API_KEY no está configurada en el servidor.")
            print("   Transcribiendo con Groq Whisper (motor forzado)...")
            text = _transcribe_with_groq_whisper(path_to_upload)
            print("   ✓ Transcripción obtenida vía Groq Whisper (sin diarización real de speakers).")
            return _collapse_repeated_runs(text)

        # engine == "auto" o "gemini": pasa por Gemini
        print("   Subiendo a Google...")
        uploaded_file = client.files.upload(file=path_to_upload)
        try:
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(6)
                uploaded_file = client.files.get(name=uploaded_file.name)
                print(f"   Google procesando {os.path.basename(path_to_upload)}...")

            if uploaded_file.state.name == "FAILED":
                raise Exception(f"La indexación de {os.path.basename(path_to_upload)} falló en Google.")

            try:
                try:
                    text = _transcribe_with_gemini_dedicated(uploaded_file)
                    print(f"   ✓ Transcripción obtenida vía {GEMINI_TRANSCRIBE_MODEL} (diarización real dedicada).")
                except Exception as dedicated_error:
                    print(f"   ⚠ {GEMINI_TRANSCRIBE_MODEL} no disponible/no usable ({dedicated_error}). Pasando a GEMINI_MODELS...")
                    text = _call_gemini_with_retry(uploaded_file)
            except Exception as gemini_error:
                if engine == "auto" and GROQ_API_KEY:
                    print(f"   ⚠ Gemini falló ({gemini_error}). Probando fallback con Groq Whisper...")
                    try:
                        text = _transcribe_with_groq_whisper(path_to_upload)
                        print("   ✓ Transcripción obtenida vía Groq Whisper (sin diarización real de speakers).")
                    except Exception as groq_error:
                        print(f"   ⚠ Groq Whisper también falló: {groq_error}")
                        raise gemini_error
                else:
                    raise
        finally:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

        return _collapse_repeated_runs(text)

    finally:
        # Limpiar el audio temporal (el video original lo limpia el caller)
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


def process_video_smart(video_path: str, progress_callback=None, engine: str = "auto") -> str:
    """
    Decide si procesar el video entero o partirlo en tramos según su
    duración, y devuelve la transcripción con tiempo absoluto continuo
    desde 00:00 del video original (sin marcas de tramo: si el texto le
    llega a otra IA con "=== TRAMO 2 ===" de por medio, puede confundirse
    y devolver timestamps relativos al tramo en vez de al video completo —
    por eso el resultado es siempre un único hilo).
    progress_callback(stage, message) opcional para reportar avance.
    engine: "auto" | "gemini" | "groq" (ver _process_single_video_file).
    """
    def report(stage, msg):
        if progress_callback:
            progress_callback(stage, msg)
        print(f"[{stage}] {msg}")

    duration_seconds = get_video_duration_seconds(video_path)
    duration_minutes = duration_seconds / 60 if duration_seconds else 0

    if duration_minutes > 0:
        report("info", f"Duración a procesar: {duration_minutes:.1f} minutos")

    # Si es corto o no pudimos detectar duración, procesamos entero
    if duration_minutes == 0 or duration_minutes <= CHUNK_THRESHOLD_MIN:
        report("analyzing", "Procesando (un solo tramo)...")
        return _process_single_video_file(video_path, engine=engine)

    # Largo: procesar por tramos
    chunk_seconds = CHUNK_DURATION_MIN * 60
    estimated_chunks = int((duration_seconds + chunk_seconds - 1) // chunk_seconds)
    report("analyzing", f"Largo ({duration_minutes:.1f} min). Dividiendo en {estimated_chunks} tramos de {CHUNK_DURATION_MIN} min...")

    chunks = split_video_in_chunks(video_path, chunk_seconds)
    if len(chunks) <= 1:
        report("info", "No se pudo partir; procesando entero como fallback.")
        return _process_single_video_file(video_path, engine=engine)

    full_transcript = []
    try:
        for i, (offset, chunk_path) in enumerate(chunks, start=1):
            if i > 1:
                report("analyzing", f"Pausa de {INTER_CHUNK_DELAY}s entre tramos (cuota Gemini)...")
                time.sleep(INTER_CHUNK_DELAY)
            report("analyzing", f"Procesando tramo {i}/{len(chunks)} (desde minuto {offset//60})...")
            chunk_text = _process_single_video_file(chunk_path, engine=engine)
            adjusted = shift_timestamps_in_transcript(chunk_text, offset)
            full_transcript.append(adjusted)
    finally:
        # Limpieza local de los tramos creados
        for offset, chunk_path in chunks:
            if chunk_path != video_path and os.path.exists(chunk_path):
                try:
                    os.remove(chunk_path)
                except Exception:
                    pass
    return "\n".join(full_transcript)


async def process_video_with_gemini(video_path: str, cache_key: str = None, engine: str = "auto"):
    """Versión no-streaming (compatible con el endpoint clásico)."""
    # Chequeo de cache
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            print(f"✓ Cache hit para {cache_key[:12]}...")
            cached["from_cache"] = True
            return cached

    # Mismo semáforo/guard de memoria que las versiones streaming (ver
    # comentario junto a _heavy_ops_semaphore) - este endpoint clásico hace
    # el mismo trabajo pesado y se había quedado afuera de esa protección.
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)

        print("Iniciando procesamiento inteligente (con detección automática de duración)...")
        text = await asyncio.to_thread(process_video_smart, video_path, None, engine)

        result = {"title": "Metraje Completo Analizado", "raw_timeline": text, "from_cache": False, "cache_key": cache_key}

        if cache_key:
            cache_set(cache_key, result)

        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en Gemini: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en la IA: {str(e)}")
    finally:
        _heavy_ops_semaphore.release()


async def process_video_streaming(video_path: str, cache_key: str = None, engine: str = "auto"):
    """Versión streaming: emite eventos SSE con el progreso real."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # 1. Cache check (sin pasar por el semáforo: no hace trabajo pesado)
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            yield event("cache_hit", "Resultado encontrado en cache. Cargando...")
            cached["from_cache"] = True
            yield event("done", "Listo (desde cache)", {"result": cached})
            return

    # 2. Cola por el semáforo de operaciones pesadas (ver comentario junto a
    # _heavy_ops_semaphore) - si hay otra en curso, avisamos y esperamos
    # nuestro turno en vez de sumar presión de memoria en simultáneo.
    async for _ in _wait_for_heavy_slot():
        yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            yield event("error", mem_error)
            return

        # 3. Detectar duración y decidir si procesar entero o por tramos
        duration_seconds = await asyncio.to_thread(get_video_duration_seconds, video_path)
        duration_minutes = duration_seconds / 60 if duration_seconds else 0

        if duration_minutes > 0:
            yield event("info", f"Duración a procesar: {duration_minutes:.1f} minutos")

        # 4. Procesamiento (entero o por tramos)
        if duration_minutes == 0 or duration_minutes <= CHUNK_THRESHOLD_MIN:
            yield event("uploading", "Procesando en un solo tramo...")
            await asyncio.sleep(0)
            text = None
            process_error = None
            async for kind, payload in run_blocking_with_heartbeat(_process_single_video_file, video_path, engine=engine):
                if kind == "heartbeat":
                    yield ": keep-alive\n\n"
                elif kind == "result":
                    text = payload
                else:
                    process_error = payload
            if process_error:
                yield event("error", str(process_error))
                return
        else:
            # Largo: tramos
            chunk_seconds = CHUNK_DURATION_MIN * 60
            estimated = int((duration_seconds + chunk_seconds - 1) // chunk_seconds)
            yield event("analyzing", f"Largo ({duration_minutes:.1f} min). Partiendo en {estimated} tramos de {CHUNK_DURATION_MIN} min...")
            await asyncio.sleep(0)

            chunks = await asyncio.to_thread(split_video_in_chunks, video_path, chunk_seconds)
            if len(chunks) <= 1:
                yield event("analyzing", "No se pudo partir; procesando completo...")
                text = None
                process_error = None
                async for kind, payload in run_blocking_with_heartbeat(_process_single_video_file, video_path, engine=engine):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "result":
                        text = payload
                    else:
                        process_error = payload
                if process_error:
                    yield event("error", str(process_error))
                    return
            else:
                full_transcript = []
                try:
                    for i, (offset, chunk_path) in enumerate(chunks, start=1):
                        if i > 1:
                            yield event("analyzing", f"Pausa de {INTER_CHUNK_DELAY}s entre tramos (cuota Gemini)...")
                            await asyncio.sleep(INTER_CHUNK_DELAY)
                        yield event("analyzing", f"Tramo {i}/{len(chunks)} — desde minuto {offset//60} (subiendo y analizando)...")
                        await asyncio.sleep(0)
                        chunk_text = None
                        process_error = None
                        async for kind, payload in run_blocking_with_heartbeat(_process_single_video_file, chunk_path, engine=engine):
                            if kind == "heartbeat":
                                yield ": keep-alive\n\n"
                            elif kind == "result":
                                chunk_text = payload
                            else:
                                process_error = payload
                        if process_error:
                            yield event("error", f"Falló el tramo {i}: {process_error}")
                            return
                        adjusted = shift_timestamps_in_transcript(chunk_text, offset)
                        full_transcript.append(adjusted)
                        yield event("analyzing", f"Tramo {i}/{len(chunks)} completado ✓")
                        await asyncio.sleep(0)
                finally:
                    for offset, chunk_path in chunks:
                        if chunk_path != video_path and os.path.exists(chunk_path):
                            try:
                                os.remove(chunk_path)
                            except Exception:
                                pass
                text = "\n".join(full_transcript)

        result = {
            "title": "Metraje Completo Analizado",
            "raw_timeline": text,
            "from_cache": False,
            "cache_key": cache_key
        }

        if cache_key:
            cache_set(cache_key, result)

        yield event("done", "Análisis completo", {"result": result})

    except Exception as e:
        yield event("error", f"Error en el procesamiento: {str(e)}")
    finally:
        _heavy_ops_semaphore.release()


# ============================================================
# ENDPOINTS CLÁSICOS (mantenidos por compatibilidad)
# ============================================================

@app.post("/analyze-url", dependencies=[Depends(require_api_key)])
async def analyze_url(input_data: UrlInput):
    cache_key = url_hash(input_data.url)
    cached = cache_get(cache_key)
    if cached:
        cached["from_cache"] = True
        return cached

    # Solo audio: analizar nunca necesitó el video, y descargarlo entero
    # era lo que hacía lento/pesado el análisis de videos largos. No se
    # cachea como "video exportable" - para exportar clips se descarga
    # el video real por separado, ver /export-clips, /export-reel, etc.
    video_path = await asyncio.to_thread(download_youtube_audio, input_data.url)
    try:
        return await process_video_with_gemini(video_path, cache_key=cache_key, engine=_normalize_engine(input_data.engine))
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


@app.post("/analyze-video", dependencies=[Depends(require_api_key)])
async def analyze_video(file: UploadFile = File(...), engine: str = Form("auto")):
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}_{_safe_upload_filename(file.filename)}")
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        cache_key = file_hash(video_path)
        return await process_video_with_gemini(video_path, cache_key=cache_key, engine=_normalize_engine(engine))
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


# ============================================================
# ENDPOINTS CON STREAMING DE PROGRESO (nuevos)
# ============================================================

@app.post("/analyze-url-stream", dependencies=[Depends(require_api_key)])
async def analyze_url_stream(input_data: UrlInput):
    """Versión streaming: el frontend recibe eventos de progreso en tiempo real."""
    cache_key = url_hash(input_data.url)
    engine = _normalize_engine(input_data.engine)

    async def generator():
        # Cache hit inmediato
        cached = cache_get(cache_key)
        if cached:
            cached["from_cache"] = True
            yield f"data: {json.dumps({'stage': 'cache_hit', 'message': 'Resultado en cache', 'result': cached}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'stage': 'done', 'message': 'Listo', 'result': cached}, ensure_ascii=False)}\n\n"
            return

        # Descarga (solo audio: transcribir nunca necesitó el video, y bajarlo
        # entero era lo que hacía lento/pesado el análisis de videos largos)
        yield f"data: {json.dumps({'stage': 'downloading', 'message': 'Descargando audio desde la URL...'}, ensure_ascii=False)}\n\n"
        video_path = None
        download_error = None
        async for kind, payload in run_blocking_with_progress(download_youtube_audio, input_data.url):
            if kind == "heartbeat":
                yield ": keep-alive\n\n"
            elif kind == "progress":
                yield f"data: {json.dumps({'stage': 'downloading', 'message': payload}, ensure_ascii=False)}\n\n"
            elif kind == "result":
                video_path = payload
            else:
                download_error = payload
        if download_error:
            msg = download_error.detail if isinstance(download_error, HTTPException) else str(download_error)
            yield f"data: {json.dumps({'stage': 'error', 'message': msg}, ensure_ascii=False)}\n\n"
            return

        try:
            async for chunk in process_video_streaming(video_path, cache_key=cache_key, engine=engine):
                yield chunk
        finally:
            # No se cachea como "video exportable": es solo audio. Para
            # exportar clips se descarga el video real por separado.
            if os.path.exists(video_path):
                os.remove(video_path)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/analyze-video-stream", dependencies=[Depends(require_api_key)])
async def analyze_video_stream(file: UploadFile = File(...), engine: str = Form("auto")):
    """Versión streaming para archivos locales."""
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, f"{uuid.uuid4().hex[:8]}_{_safe_upload_filename(file.filename)}")
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    cache_key = file_hash(video_path)
    engine = _normalize_engine(engine)

    async def generator():
        try:
            async for chunk in process_video_streaming(video_path, cache_key=cache_key, engine=engine):
                yield chunk
        finally:
            # En vez de borrarlo, lo dejamos cacheado para poder exportar clips
            # despues sin volver a re-subirlo.
            cache_video_store(cache_key, video_path)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# ENDPOINT DE INSPECCIÓN (usado como "subir y obtener ruta temporal"
# para resolver la fuente de una exportación de clips/reel)
# ============================================================

@app.post("/inspect-file", dependencies=[Depends(require_api_key)])
async def inspect_file(file: UploadFile = File(...)):
    """
    Recibe un archivo, lo analiza con ffprobe y devuelve qué tiene adentro.
    Después de inspeccionar, deja el archivo en una ruta temporal y devuelve
    esa ruta junto con la info. El análisis (siempre audio-only, ver
    _process_single_video_file) ya no pasa por acá; este endpoint solo lo
    usa el frontend para subir el archivo fuente al exportar clips/reel.
    """
    temp_dir = tempfile.gettempdir()
    # Generamos un nombre único para que dos archivos con el mismo nombre no choquen
    safe_name = f"inspect_{uuid.uuid4().hex[:8]}_{_safe_upload_filename(file.filename)}"
    temp_path = os.path.join(temp_dir, safe_name)

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    info = await asyncio.to_thread(inspect_media_file, temp_path)
    info["temp_path"] = temp_path  # frontend devuelve esta ruta en el siguiente paso
    return info


# ============================================================
# UTILIDADES
# ============================================================

@app.get("/cache-stats")
def cache_stats():
    """Estadísticas del cache: cuántos análisis guardados, tamaño total."""
    files = list(CACHE_DIR.glob("*.json"))
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "cached_analyses": len(files),
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "cache_dir": str(CACHE_DIR)
    }


@app.post("/cache-clear", dependencies=[Depends(require_api_key)])
def cache_clear():
    """Vacía el cache."""
    deleted = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    return {"deleted": deleted}


@app.get("/prompts")
def get_prompts():
    """Devuelve la biblioteca de enfoques desde prompts.json."""
    prompts_file = Path(__file__).parent / "prompts.json"
    if not prompts_file.exists():
        return JSONResponse({"error": "prompts.json no encontrado"}, status_code=404)
    with open(prompts_file, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/teaser-templates")
def get_teaser_templates():
    """Devuelve la biblioteca de plantillas de curva dramática para teaser."""
    templates_file = Path(__file__).parent / "teaser_templates.json"
    if not templates_file.exists():
        return JSONResponse({"error": "teaser_templates.json no encontrado"}, status_code=404)
    with open(templates_file, "r", encoding="utf-8") as f:
        return json.load(f)


class GenerateWithAiInput(BaseModel):
    prompt: str


@app.post("/generate-clip-suggestions", dependencies=[Depends(require_api_key)])
async def generate_with_ai(input_data: GenerateWithAiInput):
    """
    Prompt libre "en la app": manda el prompt (transcripción + instrucciones,
    ya armado del lado del frontend) directo a Gemini y devuelve el texto.
    Reemplaza el paso manual de copiar el prompt a ChatGPT/Claude/Gemini web
    y pegar la respuesta de vuelta - el resultado se importa directo al
    exportador de clips sin salir de la app.

    Si Gemini agota TODA su lista de modelos (ver _call_gemini_text), cae a
    Groq (Llama 3.3 70B) como último recurso antes de fallar del todo - la
    respuesta indica en "engine" cuál de los dos resolvió el pedido, para
    que el frontend lo pueda mostrar.
    """
    if not input_data.prompt or len(input_data.prompt.strip()) < 10:
        raise HTTPException(status_code=400, detail="El prompt está vacío.")

    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)
        try:
            text = await asyncio.to_thread(_call_gemini_text, input_data.prompt)
            return {"text": text, "engine": "gemini"}
        except Exception as gemini_error:
            if GROQ_API_KEY:
                print(f"   ⚠ Gemini agotó todos sus modelos ({gemini_error}). Probando con Groq (Llama 3.3 70B)...")
                try:
                    text = await asyncio.to_thread(_call_groq_text, input_data.prompt)
                    return {"text": text, "engine": "groq"}
                except Exception as groq_error:
                    print(f"   ⚠ Groq también falló: {groq_error}")
                    raise gemini_error
            raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini no pudo generar una respuesta: {e}")
    finally:
        _heavy_ops_semaphore.release()


# ============================================================
# EXPORTACIÓN DE CLIPS (corte con ffmpeg a partir de timestamps)
# ============================================================

def ts_to_seconds_f(ts: str) -> float:
    """MM:SS o HH:MM:SS → segundos float."""
    try:
        parts = [float(p) for p in ts.strip().split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        pass
    return 0.0


def cut_single_clip(video_path: str, start_ts: str, end_ts: str, output_path: str):
    import subprocess
    start_s = ts_to_seconds_f(start_ts)
    end_s = ts_to_seconds_f(end_ts)
    if end_s <= start_s:
        end_s = start_s + 30  # fallback: 30 segundos
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start_s), "-to", str(end_s),
        "-i", video_path, "-c", "copy", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise Exception(f"ffmpeg: {result.stderr[:200]}")


# ============================================================
# UTILIDADES DE EXPORTACIÓN DE VIDEO PARA REDES SOCIALES
# ============================================================

def scale_to_platform(input_path: str, output_path: str, width: int, height: int, max_dur: int = None):
    """Escala y rellena (letterbox/pillarbox) un video al formato de la plataforma."""
    import subprocess
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path]
    if max_dur:
        cmd += ["-t", str(max_dur)]
    cmd += [
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"ffmpeg scale error: {result.stderr[:300]}")


def extract_frame(video_path: str, timestamp: str, output_path: str):
    """Extrae un fotograma del video en el timestamp dado."""
    import subprocess
    start_s = ts_to_seconds_f(timestamp)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start_s), "-i", video_path,
        "-vframes", "1", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise Exception(f"Frame extraction error: {result.stderr[:200]}")


def _load_pil_font(size: int):
    """Carga una fuente del sistema con fallback al default de PIL."""
    from PIL import ImageFont
    for name in ["arialbd.ttf", "arial.ttf", "Arial Bold.ttf", "Arial.ttf",
                  "DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "LiberationSans-Bold.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def create_carousel_plate(frame_path: str, dialogue: str, speaker: str, output_path: str):
    """Crea una placa de carrusel 1080×1080 con frame + overlay de texto (Pillow)."""
    try:
        from PIL import Image, ImageDraw
        import textwrap

        img = Image.open(frame_path).convert("RGB")
        w, h = img.size
        # Crop al centro para quedar cuadrado
        size = min(w, h)
        left = (w - size) // 2
        top = (h - size) // 2
        img = img.crop((left, top, left + size, top + size))
        img = img.resize((1080, 1080), Image.LANCZOS)

        # Overlay oscuro degradado en la mitad inferior
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        draw_ov.rectangle([(0, 550), (1080, 780)], fill=(0, 0, 0, 120))
        draw_ov.rectangle([(0, 780), (1080, 1080)], fill=(0, 0, 0, 210))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)

        draw = ImageDraw.Draw(img)
        font_sp = _load_pil_font(30)
        font_txt = _load_pil_font(42)

        y = 590
        if speaker and speaker.strip():
            draw.text((60, y), speaker.strip().upper()[:45], font=font_sp, fill=(160, 185, 255))
            y += 52

        for line in textwrap.wrap(dialogue[:300], width=36)[:7]:
            draw.text((60, y), line, font=font_txt, fill=(255, 255, 255))
            y += 58

        img.convert("RGB").save(output_path, "JPEG", quality=90)

    except ImportError:
        # Fallback: ffmpeg drawtext
        import subprocess
        txt = dialogue[:120].replace("\\", "").replace("'", "").replace(":", ".").replace("\n", " ")
        vf = (
            f"scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,"
            f"drawbox=y=600:w=iw:h=480:color=black@0.75:t=fill,"
            f"drawtext=fontsize=38:fontcolor=white:x=60:y=640:text='{txt}'"
        )
        result = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", frame_path, "-vf", vf, output_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            shutil.copy(frame_path, output_path)


# ============================================================
# SUBTÍTULOS INCRUSTADOS (burn-in con PIL + overlay de ffmpeg)
# ============================================================
# El ffmpeg local no tiene el filtro "drawtext" compilado (falta
# libfreetype/fontconfig en el build de Homebrew). En vez de depender de eso,
# el texto de cada cue se renderiza como PNG transparente con Pillow (con la
# tipografía, color y borde elegidos) y se superpone al clip con el filtro
# "overlay", que sí está disponible siempre.
FONTS_DIR = PROJECT_DIR / "assets" / "fonts"

SUBTITLE_FONTS = {
    "anton":    {"label": "Anton (Impacto)",        "file": "Anton-Regular.ttf"},
    "bebas":    {"label": "Bebas Neue (Condensada)", "file": "BebasNeue-Regular.ttf"},
    "poppins":  {"label": "Poppins Bold (Moderna)",  "file": "Poppins-Bold.ttf"},
    "archivo":  {"label": "Archivo Black (Geométrica)", "file": "ArchivoBlack-Regular.ttf"},
    "luckiest": {"label": "Luckiest Guy (Divertida)", "file": "LuckiestGuy-Regular.ttf"},
}


@app.get("/subtitle-fonts")
async def list_subtitle_fonts():
    return {key: {"label": val["label"]} for key, val in SUBTITLE_FONTS.items()}


class SubtitleCue(BaseModel):
    start: float  # segundos, relativo al inicio del clip (no del video original)
    end: float
    text: str


class SubtitleStyle(BaseModel):
    font: str = "anton"
    color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 3


def _ffprobe_dimensions(video_path: str):
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", video_path],
        capture_output=True, text=True, timeout=30,
    )
    info = json.loads(result.stdout or "{}")
    streams = info.get("streams") or [{}]
    return int(streams[0].get("width") or 1280), int(streams[0].get("height") or 720)


def _hex_to_rgb(hex_color: str, default=(255, 255, 255)):
    try:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _render_subtitle_png(text: str, style: "SubtitleStyle", width: int, height: int, out_path: str):
    """Renderiza el texto de una cue como PNG transparente del tamaño del video."""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    font_info = SUBTITLE_FONTS.get(style.font, SUBTITLE_FONTS["anton"])
    font_path = FONTS_DIR / font_info["file"]
    font_size = max(18, int(height * 0.07))
    font = ImageFont.truetype(str(font_path), font_size)

    chars_per_line = max(8, int(width / (font_size * 0.58)))
    lines = textwrap.wrap(text.strip(), width=chars_per_line)[:3] or [""]
    wrapped = "\n".join(lines)

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = _hex_to_rgb(style.color, (255, 255, 255))
    stroke_fill = _hex_to_rgb(style.border_color, (0, 0, 0))
    x = width / 2
    y = height * 0.82
    draw.multiline_text(
        (x, y), wrapped, font=font, fill=fill,
        stroke_width=max(0, style.border_width), stroke_fill=stroke_fill,
        anchor="mm", align="center", spacing=8,
    )
    img.save(out_path, "PNG")


def burn_subtitles(clip_path: str, output_path: str, cues: list, style: "SubtitleStyle"):
    """Quema las cues de subtítulo en el clip ya cortado. Si algo falla, copia
    el clip sin subtítulos en vez de romper toda la exportación."""
    import subprocess
    usable_cues = [c for c in cues if c.text and c.text.strip() and c.end > c.start]
    if not usable_cues:
        shutil.copy(clip_path, output_path)
        return

    tmp_dir = tempfile.mkdtemp(prefix="subs_")
    try:
        width, height = _ffprobe_dimensions(clip_path)
        png_paths = []
        for i, cue in enumerate(usable_cues):
            png_path = os.path.join(tmp_dir, f"cue_{i:03d}.png")
            _render_subtitle_png(cue.text, style, width, height, png_path)
            png_paths.append(png_path)

        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clip_path]
        for p in png_paths:
            cmd += ["-i", p]

        filter_parts = []
        last_label = "0:v"
        for i, cue in enumerate(usable_cues):
            out_label = f"v{i}"
            filter_parts.append(
                f"[{last_label}][{i + 1}:v]overlay=enable='between(t,{cue.start},{cue.end})'[{out_label}]"
            )
            last_label = out_label
        filter_complex = ";".join(filter_parts)

        cmd += [
            "-filter_complex", filter_complex,
            "-map", f"[{last_label}]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise Exception(f"ffmpeg overlay: {result.stderr[:300]}")
    except Exception as e:
        print(f"⚠ Burn-in de subtítulos falló ({e}), exportando el clip sin subtítulos.")
        shutil.copy(clip_path, output_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class ClipSpec(BaseModel):
    start: str
    end: str
    label: str = ""
    subtitles: list[SubtitleCue] = []


class ExportClipsInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ClipSpec]
    subtitle_style: SubtitleStyle | None = None


@app.post("/export-clips", dependencies=[Depends(require_api_key)])
async def export_clips_endpoint(input_data: ExportClipsInput):
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        # Si no vino cache_key (ej: exportar directo pegando una URL, sin
        # pasar antes por análisis), usamos el hash de la URL para que un
        # segundo export del mismo video pueda reusar lo recién descargado.
        effective_cache_key = input_data.cache_key or (url_hash(input_data.url) if input_data.url else "")
        cached_video = cache_video_path(effective_cache_key)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido para exportar clips.")
            return
        if not input_data.clips:
            yield event("error", "No hay clips definidos para exportar.")
            return

        # Cola por el semáforo de operaciones pesadas (ver comentario junto a
        # _heavy_ops_semaphore) antes de tocar disco/red/ffmpeg.
        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        export_id = deterministic_export_id(
            effective_cache_key or input_data.video_path or "local",
            *[f"{c.start}-{c.end}-{c.label}" for c in input_data.clips],
        )
        clip_dir = EXPORT_DIR / export_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        delete_video_after = False  # el cacheado NO se borra: lo puede volver a usar otra exportacion

        try:
            mem_error = _memory_headroom_error()
            if mem_error:
                yield event("error", mem_error)
                return

            if cached_video:
                video_path = cached_video
            elif input_data.video_path:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo.")
                    return
                video_path = input_data.video_path
                delete_video_after = True
            else:
                yield event("downloading", f"Descargando video fuente para cortar {len(input_data.clips)} clip(s)...", {"pct": 5})
                await asyncio.sleep(0)
                download_error = None
                async for kind, payload in run_blocking_with_progress(download_youtube_video, input_data.url):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "progress":
                        yield event("downloading", payload)
                    elif kind == "result":
                        video_path = payload
                    else:
                        download_error = payload
                if download_error:
                    yield event("error", download_error.detail if isinstance(download_error, HTTPException) else str(download_error))
                    return
                # No se cachea: se borra despues de usarlo (ver finally), igual
                # que la descarga de audio para analizar. Cachear el video acá
                # sumaba disco/pagecache que puede contar contra el limite de
                # memoria del contenedor en el free tier de Render.
                delete_video_after = True

            clip_files = []
            total_clips = len(input_data.clips)
            for i, clip in enumerate(input_data.clips, 1):
                safe_label = "".join(c if c.isalnum() or c in "-_ " else "_" for c in clip.label)[:25]
                clip_path = str(clip_dir / f"{i:02d}_{safe_label or 'clip'}.mp4")
                pct = 10 + round(80 * i / total_clips)
                # Si el server se reinició a mitad de un intento anterior con
                # estos mismos clips, este archivo ya puede estar cortado.
                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                    yield event("cutting", f"Clip {i}/{total_clips} ya estaba cortado de un intento anterior, lo salteo.", {"pct": pct, "current": i, "total": total_clips})
                    await asyncio.sleep(0)
                    clip_files.append(clip_path)
                    continue
                yield event("cutting", f"Cortando clip {i}/{total_clips}: {clip.start} → {clip.end}", {"pct": pct, "current": i, "total": total_clips})
                await asyncio.sleep(0)
                cut_error = None
                async for kind, payload in run_blocking_with_heartbeat(cut_single_clip, video_path, clip.start, clip.end, clip_path):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "error":
                        cut_error = payload
                if cut_error:
                    yield event("cutting", f"⚠ Clip {i} falló: {str(cut_error)[:80]}. Continuando...", {"pct": pct})
                    await asyncio.sleep(0)
                    continue

                if clip.subtitles and input_data.subtitle_style:
                    yield event("cutting", f"Quemando subtítulos en clip {i}/{total_clips}...", {"pct": pct, "current": i, "total": total_clips})
                    await asyncio.sleep(0)
                    subbed_path = str(clip_dir / f"{i:02d}_subbed.mp4")
                    async for kind, payload in run_blocking_with_heartbeat(burn_subtitles, clip_path, subbed_path, clip.subtitles, input_data.subtitle_style):
                        if kind == "heartbeat":
                            yield ": keep-alive\n\n"
                    if os.path.exists(subbed_path) and os.path.getsize(subbed_path) > 0:
                        clip_path = subbed_path

                clip_files.append(clip_path)

            if not clip_files:
                yield event("error", "Ningún clip se pudo cortar.")
                return

            if len(clip_files) == 1:
                single_name = f"clip_{export_id}.mp4"
                shutil.copy(clip_files[0], str(EXPORT_DIR / single_name))
                yield event("done", "✓ Clip exportado.", {
                    "download_url": f"/exports/{single_name}",
                    "filename": single_name,
                    "clip_count": 1,
                    "pct": 100,
                })
            else:
                yield event("merging", f"Empaquetando {len(clip_files)} clips en ZIP...", {"pct": 95})
                await asyncio.sleep(0)
                zip_name = f"clips_{export_id}.zip"
                zip_path = str(EXPORT_DIR / zip_name)
                with zipfile.ZipFile(zip_path, "w") as zf:
                    for cf in clip_files:
                        zf.write(cf, os.path.basename(cf))
                yield event("done", f"✓ {len(clip_files)} clips empaquetados en ZIP.", {
                    "download_url": f"/exports/{zip_name}",
                    "filename": zip_name,
                    "clip_count": len(clip_files),
                    "pct": 100,
                })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if delete_video_after and video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            try:
                shutil.rmtree(str(clip_dir), ignore_errors=True)
            except Exception:
                pass
            _heavy_ops_semaphore.release()

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/exports")
async def list_exports():
    """
    Lista lo que haya terminado de generarse en el servidor, con link de
    descarga directo. Sirve como red de contención cuando la conexión se
    corta antes de que la web reciba el link (el archivo puede haberse
    terminado igual del lado del servidor) - navegá a /exports para
    buscarlo a mano en vez de tener que volver a generarlo.
    """
    files = sorted(
        (f for f in EXPORT_DIR.iterdir() if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    rows = "\n".join(
        f'<tr><td>{f.name}</td><td>{f.stat().st_size / (1024 * 1024):.1f} MB</td>'
        f'<td>{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))}</td>'
        f'<td><a href="/exports/{f.name}">Descargar</a></td></tr>'
        for f in files
    )
    html = f"""
    <html><head><meta charset="utf-8"><title>Exports</title>
    <style>
        body {{ font-family: sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        td, th {{ padding: 8px 12px; border-bottom: 1px solid #334155; text-align: left; }}
        a {{ color: #818cf8; }}
    </style></head>
    <body>
        <h2>Archivos exportados en el servidor</h2>
        <table>
            <tr><th>Archivo</th><th>Tamaño</th><th>Modificado</th><th></th></tr>
            {rows or '<tr><td colspan="4">No hay archivos exportados todavía.</td></tr>'}
        </table>
    </body></html>
    """
    return HTMLResponse(content=html)


@app.get("/exports/{filename}")
async def download_export(filename: str):
    """Descarga un archivo de clip exportado."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    filepath = EXPORT_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado o expirado.")
    media_type = "video/mp4" if filename.endswith(".mp4") else "application/zip"
    return FileResponse(str(filepath), media_type=media_type, filename=filename)


# ============================================================
# EXPORTACIÓN A PREMIERE (FCP7 XML / xmeml)
# ============================================================
# Ver premiere_export.py para el detalle del formato y sus límites
# conocidos (sin confirmar todavía en un Premiere real). A diferencia de
# CapCut, esto NO necesita el puente local - es solo un archivo que el
# usuario importa en su propio Premiere, funciona igual en Render.

class ExportPremiereInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ClipSpec]
    sequence_name: str = "AVSuite Export"


@app.post("/export-premiere-xml", dependencies=[Depends(require_api_key)])
async def export_premiere_xml_endpoint(input_data: ExportPremiereInput):
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (url_hash(input_data.url) if input_data.url else "")
        cached_video = cache_video_path(effective_cache_key)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido para exportar a Premiere.")
            return
        if not input_data.clips:
            yield event("error", "No hay clips definidos para exportar.")
            return

        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        export_id = deterministic_export_id(
            "premiere-" + (effective_cache_key or input_data.video_path or "local"),
            *[f"{c.start}-{c.end}-{c.label}" for c in input_data.clips],
        )
        video_path = None
        delete_video_after = False  # el cacheado NO se borra, igual que en /export-clips

        try:
            mem_error = _memory_headroom_error()
            if mem_error:
                yield event("error", mem_error)
                return

            if cached_video:
                video_path = cached_video
            elif input_data.video_path:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo.")
                    return
                video_path = input_data.video_path
                delete_video_after = True
            else:
                yield event("downloading", "Descargando video fuente para armar la secuencia de Premiere...", {"pct": 10})
                await asyncio.sleep(0)
                download_error = None
                async for kind, payload in run_blocking_with_progress(download_youtube_video, input_data.url):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "progress":
                        yield event("downloading", payload)
                    elif kind == "result":
                        video_path = payload
                    else:
                        download_error = payload
                if download_error:
                    yield event("error", download_error.detail if isinstance(download_error, HTTPException) else str(download_error))
                    return
                # No se cachea: mismo motivo que en /export-clips, no
                # sumar disco/pagecache contra el límite de memoria del
                # free tier de Render.
                delete_video_after = True

            yield event("info", "Armando la secuencia de Premiere (XML)...", {"pct": 60})
            await asyncio.sleep(0)

            pe_clips = [
                premiere_export.PremiereClip(
                    source_start_s=ts_to_seconds_f(c.start),
                    source_end_s=ts_to_seconds_f(c.end),
                    label=c.label,
                    subtitles=[
                        premiere_export.PremiereSubtitleCue(cue.start, cue.end, cue.text)
                        for cue in c.subtitles
                    ],
                )
                for c in input_data.clips
            ]

            safe_seq_name = "".join(
                c if c.isalnum() or c in "-_ " else "_" for c in input_data.sequence_name
            )[:40].strip() or "AVSuite_Export"
            bundled_video_name = f"{safe_seq_name}{os.path.splitext(video_path)[1] or '.mp4'}"

            try:
                video_info = await asyncio.to_thread(premiere_export.probe_video_info, video_path)
                xml_str = await asyncio.to_thread(
                    premiere_export.build_premiere_xml,
                    video_path, pe_clips, input_data.sequence_name, video_info, bundled_video_name,
                )
            except Exception as e:
                yield event("error", f"No se pudo armar el XML de Premiere: {e}")
                return
            companion_str = premiere_export.build_premiere_companion_text(pe_clips, input_data.sequence_name)

            yield event("merging", "Empaquetando XML + companion + video fuente en ZIP...", {"pct": 90})
            await asyncio.sleep(0)

            zip_name = f"premiere_{export_id}.zip"
            zip_path = str(EXPORT_DIR / zip_name)
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(f"{safe_seq_name}.xml", xml_str)
                zf.writestr(f"{safe_seq_name}_companion.txt", companion_str)
                # Mismo nombre que quedó embebido en el XML (bundled_video_name)
                # - así Premiere lo puede relinkear solo si el usuario lo
                # descomprime todo en la misma carpeta.
                zf.write(video_path, bundled_video_name)

            yield event("done", "✓ Proyecto de Premiere listo (XML + companion + video fuente).", {
                "download_url": f"/exports/{zip_name}",
                "filename": zip_name,
                "clip_count": len(input_data.clips),
                "pct": 100,
            })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if delete_video_after and video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            _heavy_ops_semaphore.release()

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# EXPORTACIÓN A CAPCUT (draft nativo vía capcut-cli)
# ============================================================
# Ver capcut_export.py para el detalle y las pruebas hechas. A diferencia
# de Premiere, esto SÓLO funciona cuando el server corre en una Mac con
# CapCut instalado (necesita el puente local / túnel, no Render) - por
# eso existe /capcut-status, para que el frontend pueda avisar antes de
# intentar en vez de fallar confuso.

@app.get("/capcut-status")
def capcut_status():
    return {
        "capcut_installed": capcut_export.capcut_available(),
        "capcut_cli_found": capcut_export._find_capcut_cli() is not None,
    }


class ExportCapCutInput(BaseModel):
    url: str = ""
    video_path: str = ""
    cache_key: str = ""
    clip: ClipSpec
    subtitle_style: SubtitleStyle | None = None
    project_name: str = ""


@app.post("/export-capcut", dependencies=[Depends(require_api_key)])
async def export_capcut_endpoint(input_data: ExportCapCutInput):
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        if not capcut_export.capcut_available():
            yield event("error", "CapCut no está instalado en este servidor (falta ~/Movies/CapCut/...). Esta función solo funciona corriendo el server en una Mac con CapCut instalado, no en Render.")
            return
        if not capcut_export._find_capcut_cli():
            yield event("error", "No encontré capcut-cli en este servidor. Instalalo con: npm install -g capcut-cli")
            return

        effective_cache_key = input_data.cache_key or (url_hash(input_data.url) if input_data.url else "")
        cached_video = cache_video_path(effective_cache_key)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido.")
            return

        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        clip = input_data.clip
        export_id = deterministic_export_id(
            "capcut-" + (effective_cache_key or input_data.video_path or "local"),
            f"{clip.start}-{clip.end}-{clip.label}",
        )
        clip_dir = EXPORT_DIR / export_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        delete_video_after = False

        try:
            mem_error = _memory_headroom_error()
            if mem_error:
                yield event("error", mem_error)
                return

            if cached_video:
                video_path = cached_video
            elif input_data.video_path:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo.")
                    return
                video_path = input_data.video_path
                delete_video_after = True
            else:
                yield event("downloading", "Descargando video fuente para el clip...", {"pct": 10})
                await asyncio.sleep(0)
                download_error = None
                async for kind, payload in run_blocking_with_progress(download_youtube_video, input_data.url):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "progress":
                        yield event("downloading", payload)
                    elif kind == "result":
                        video_path = payload
                    else:
                        download_error = payload
                if download_error:
                    yield event("error", download_error.detail if isinstance(download_error, HTTPException) else str(download_error))
                    return
                delete_video_after = True

            yield event("cutting", f"Cortando clip: {clip.start} → {clip.end}...", {"pct": 40})
            await asyncio.sleep(0)
            clip_path = str(clip_dir / "clip_for_capcut.mp4")
            cut_error = None
            async for kind, payload in run_blocking_with_heartbeat(cut_single_clip, video_path, clip.start, clip.end, clip_path):
                if kind == "heartbeat":
                    yield ": keep-alive\n\n"
                elif kind == "error":
                    cut_error = payload
            if cut_error or not os.path.exists(clip_path):
                yield event("error", f"No se pudo cortar el clip: {cut_error}")
                return

            yield event("info", "Armando el draft de CapCut (video + subtítulos)...", {"pct": 70})
            await asyncio.sleep(0)

            cues = [{"start": c.start, "end": c.end, "text": c.text} for c in clip.subtitles]
            style = {}
            if input_data.subtitle_style:
                style = {
                    "color": input_data.subtitle_style.color,
                    "border_color": input_data.subtitle_style.border_color,
                    "border_width": input_data.subtitle_style.border_width,
                }
            project_name = input_data.project_name or clip.label or "AVSuite Export"

            ok, msg, info = await asyncio.to_thread(
                capcut_export.build_and_register_capcut_draft, project_name, clip_path, cues, style,
            )
            if not ok:
                yield event("error", msg)
                return

            yield event("done", f"✓ {msg} Reabrí CapCut para verlo en tu lista de proyectos.", {"pct": 100, **(info or {})})

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if delete_video_after and video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            shutil.rmtree(str(clip_dir), ignore_errors=True)
            _heavy_ops_semaphore.release()

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# EXPORTACIÓN DE VIDEO PARA REDES SOCIALES
# ============================================================

class ReelClipSpec(BaseModel):
    start: str
    end: str
    label: str = ""
    subtitles: list[SubtitleCue] = []


class ReelExportInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ReelClipSpec]
    platform: str
    original_size: bool = False  # si True, no se escala/recorta al formato de la plataforma
    subtitle_style: SubtitleStyle | None = None


class CarouselExportInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ReelClipSpec]
    platform: str
    subtitle_style: SubtitleStyle | None = None
    # Sin "tamaño original": el carrusel siempre es 1:1 (clips o placas), no aplica.


@app.post("/export-reel", dependencies=[Depends(require_api_key)])
async def export_reel_endpoint(input_data: ReelExportInput):
    """Descarga, corta, une y convierte clips al formato de la plataforma. Devuelve un MP4."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (url_hash(input_data.url) if input_data.url else "")
        cached_video = cache_video_path(effective_cache_key)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay clips definidos."); return
        cfg = PLATFORM_CONFIGS.get(input_data.platform)
        if not cfg:
            yield event("error", f"Plataforma desconocida: {input_data.platform}"); return

        # Cola por el semáforo de operaciones pesadas antes de tocar disco/red/ffmpeg.
        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        target_w, target_h, max_dur = cfg
        export_id = deterministic_export_id(
            effective_cache_key or input_data.video_path or "local",
            input_data.platform,
            *[f"{c.start}-{c.end}-{c.label}" for c in input_data.clips],
        )
        clip_dir = EXPORT_DIR / export_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        delete_video_after = False

        try:
            mem_error = _memory_headroom_error()
            if mem_error:
                yield event("error", mem_error)
                return

            if cached_video:
                video_path = cached_video
            elif input_data.video_path:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo."); return
                video_path = input_data.video_path
                delete_video_after = True
            else:
                yield event("downloading", "Descargando video fuente...", {"pct": 5})
                await asyncio.sleep(0)
                download_error = None
                async for kind, payload in run_blocking_with_progress(download_youtube_video, input_data.url):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "progress":
                        yield event("downloading", payload)
                    elif kind == "result":
                        video_path = payload
                    else:
                        download_error = payload
                if download_error:
                    yield event("error", download_error.detail if isinstance(download_error, HTTPException) else str(download_error)); return
                delete_video_after = True

            clip_files = []
            clip_specs = []  # en paralelo a clip_files, para poder asociar subtítulos por clip
            total_clips = len(input_data.clips)
            for i, clip in enumerate(input_data.clips, 1):
                safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in clip.label)[:20]
                clip_path = str(clip_dir / f"{i:02d}_{safe or 'clip'}.mp4")
                pct = 5 + round(45 * i / total_clips)
                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                    yield event("cutting", f"Clip {i}/{total_clips} ya estaba cortado, lo salteo.", {"pct": pct, "current": i, "total": total_clips})
                    await asyncio.sleep(0)
                    clip_files.append(clip_path)
                    clip_specs.append(clip)
                    continue
                yield event("cutting", f"Cortando clip {i}/{total_clips}: {clip.start} → {clip.end}", {"pct": pct, "current": i, "total": total_clips})
                await asyncio.sleep(0)
                cut_error = None
                async for kind, payload in run_blocking_with_heartbeat(cut_single_clip, video_path, clip.start, clip.end, clip_path):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "error":
                        cut_error = payload
                if cut_error:
                    yield event("cutting", f"⚠ Clip {i} falló: {str(cut_error)[:60]}. Continuando...", {"pct": pct})
                    await asyncio.sleep(0)
                else:
                    clip_files.append(clip_path)
                    clip_specs.append(clip)

            if not clip_files:
                yield event("error", "Ningún clip se pudo cortar."); return

            if input_data.original_size:
                # El usuario pidió mantener el tamaño/aspecto original: los
                # clips ya cortados (sin recodificar) son directamente el resultado.
                output_files = clip_files
                yield event("converting", "Manteniendo tamaño original (sin escalar/recortar)...", {"pct": 92})
                await asyncio.sleep(0)
            else:
                # Escalar cada clip por separado al formato de la plataforma
                output_files = []
                total_scale = len(clip_files)
                for i, clip_path in enumerate(clip_files, 1):
                    pct = 50 + round(45 * i / total_scale)
                    scaled_path = str(clip_dir / f"scaled_{i:02d}.mp4")
                    if os.path.exists(scaled_path) and os.path.getsize(scaled_path) > 0:
                        yield event("converting", f"Clip {i}/{total_scale} ya estaba convertido, lo salteo.", {"pct": pct, "current": i, "total": total_scale})
                        await asyncio.sleep(0)
                        output_files.append(scaled_path)
                        continue
                    yield event("converting", f"Aplicando formato {target_w}×{target_h} a clip {i}/{total_scale}...", {"pct": pct, "current": i, "total": total_scale})
                    await asyncio.sleep(0)
                    scale_error = None
                    async for kind, payload in run_blocking_with_heartbeat(scale_to_platform, clip_path, scaled_path, target_w, target_h, max_dur):
                        if kind == "heartbeat":
                            yield ": keep-alive\n\n"
                        elif kind == "error":
                            scale_error = payload
                    if scale_error:
                        yield event("converting", f"⚠ Clip {i} falló al convertir: {str(scale_error)[:60]}", {"pct": pct})
                        await asyncio.sleep(0)
                    else:
                        output_files.append(scaled_path)

            if not output_files:
                yield event("error", "Ningún clip se pudo convertir."); return

            if input_data.subtitle_style and any(c.subtitles for c in clip_specs):
                yield event("converting", "Quemando subtítulos...", {"pct": 93})
                await asyncio.sleep(0)
                for i, (out_path, clip) in enumerate(zip(output_files, clip_specs), 1):
                    if not clip.subtitles:
                        continue
                    subbed_path = str(clip_dir / f"subbed_{i:02d}.mp4")
                    async for kind, payload in run_blocking_with_heartbeat(burn_subtitles, out_path, subbed_path, clip.subtitles, input_data.subtitle_style):
                        if kind == "heartbeat":
                            yield ": keep-alive\n\n"
                    if os.path.exists(subbed_path) and os.path.getsize(subbed_path) > 0:
                        output_files[i - 1] = subbed_path

            size_label = "tamaño original" if input_data.original_size else f"{target_w}×{target_h}"
            if len(output_files) == 1:
                output_name = f"reel_{input_data.platform}_{export_id}.mp4"
                shutil.copy(output_files[0], str(EXPORT_DIR / output_name))
                yield event("done", f"✓ Video listo en {size_label}.", {
                    "download_url": f"/exports/{output_name}",
                    "filename": output_name,
                    "platform": input_data.platform,
                    "resolution": "original" if input_data.original_size else f"{target_w}x{target_h}",
                    "clip_count": 1,
                    "pct": 100,
                })
            else:
                yield event("merging", f"Empaquetando {len(output_files)} clips en ZIP...", {"pct": 95})
                await asyncio.sleep(0)
                zip_name = f"reel_{input_data.platform}_{export_id}.zip"
                zip_path = str(EXPORT_DIR / zip_name)
                with zipfile.ZipFile(zip_path, "w") as zf:
                    for f in output_files:
                        zf.write(f, os.path.basename(f))
                yield event("done", f"✓ {len(output_files)} clips listos en {size_label}.", {
                    "download_url": f"/exports/{zip_name}",
                    "filename": zip_name,
                    "platform": input_data.platform,
                    "resolution": "original" if input_data.original_size else f"{target_w}x{target_h}",
                    "clip_count": len(output_files),
                    "pct": 100,
                })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if delete_video_after and video_path and os.path.exists(video_path):
                try: os.remove(video_path)
                except: pass
            try: shutil.rmtree(str(clip_dir), ignore_errors=True)
            except: pass
            _heavy_ops_semaphore.release()

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/export-carousel", dependencies=[Depends(require_api_key)])
async def export_carousel_endpoint(input_data: CarouselExportInput):
    """Genera un carrusel: clips 1:1 (ZIP de MP4) o placas de texto (ZIP de JPG)."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (url_hash(input_data.url) if input_data.url else "")
        cached_video = cache_video_path(effective_cache_key)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay slides definidos."); return
        if input_data.platform not in CAROUSEL_PLATFORMS:
            yield event("error", f"Plataforma no es carrusel: {input_data.platform}"); return

        # Cola por el semáforo de operaciones pesadas antes de tocar disco/red/ffmpeg.
        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        export_id = deterministic_export_id(
            effective_cache_key or input_data.video_path or "local",
            input_data.platform,
            *[f"{c.start}-{c.end}-{c.label}" for c in input_data.clips],
        )
        carousel_dir = EXPORT_DIR / f"car_{export_id}"
        carousel_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        delete_video_after = False

        try:
            mem_error = _memory_headroom_error()
            if mem_error:
                yield event("error", mem_error)
                return

            if cached_video:
                video_path = cached_video
            elif input_data.video_path:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo."); return
                video_path = input_data.video_path
                delete_video_after = True
            else:
                yield event("downloading", "Descargando video fuente...", {"pct": 5})
                await asyncio.sleep(0)
                download_error = None
                async for kind, payload in run_blocking_with_progress(download_youtube_video, input_data.url):
                    if kind == "heartbeat":
                        yield ": keep-alive\n\n"
                    elif kind == "progress":
                        yield event("downloading", payload)
                    elif kind == "result":
                        video_path = payload
                    else:
                        download_error = payload
                if download_error:
                    yield event("error", download_error.detail if isinstance(download_error, HTTPException) else str(download_error)); return
                delete_video_after = True

            output_files = []
            total_slides = len(input_data.clips)

            if input_data.platform == "ig_carrusel_clips":
                for i, clip in enumerate(input_data.clips, 1):
                    pct = 5 + round(85 * i / total_slides)
                    raw_clip = str(carousel_dir / f"raw_{i:02d}.mp4")
                    out_clip = str(carousel_dir / f"slide_{i:02d}.mp4")
                    if os.path.exists(out_clip) and os.path.getsize(out_clip) > 0:
                        yield event("cutting", f"Slide {i}/{total_slides} ya estaba listo, lo salteo.", {"pct": pct, "current": i, "total": total_slides})
                        await asyncio.sleep(0)
                        output_files.append(out_clip)
                        continue
                    yield event("cutting", f"Procesando slide {i}/{total_slides} (clip 1:1)...", {"pct": pct, "current": i, "total": total_slides})
                    await asyncio.sleep(0)
                    slide_error = None
                    async for kind, payload in run_blocking_with_heartbeat(cut_single_clip, video_path, clip.start, clip.end, raw_clip):
                        if kind == "heartbeat":
                            yield ": keep-alive\n\n"
                        elif kind == "error":
                            slide_error = payload
                    if not slide_error:
                        async for kind, payload in run_blocking_with_heartbeat(scale_to_platform, raw_clip, out_clip, 1080, 1080, 60):
                            if kind == "heartbeat":
                                yield ": keep-alive\n\n"
                            elif kind == "error":
                                slide_error = payload
                    if slide_error:
                        yield event("cutting", f"⚠ Slide {i} falló: {str(slide_error)[:60]}", {"pct": pct})
                        await asyncio.sleep(0)
                        continue

                    if clip.subtitles and input_data.subtitle_style:
                        subbed_clip = str(carousel_dir / f"subbed_{i:02d}.mp4")
                        async for kind, payload in run_blocking_with_heartbeat(burn_subtitles, out_clip, subbed_clip, clip.subtitles, input_data.subtitle_style):
                            if kind == "heartbeat":
                                yield ": keep-alive\n\n"
                        if os.path.exists(subbed_clip) and os.path.getsize(subbed_clip) > 0:
                            out_clip = subbed_clip

                    output_files.append(out_clip)

            elif input_data.platform == "ig_carrusel_placas":
                for i, clip in enumerate(input_data.clips, 1):
                    pct = 5 + round(85 * i / total_slides)
                    frame_path = str(carousel_dir / f"frame_{i:02d}.jpg")
                    plate_path = str(carousel_dir / f"placa_{i:02d}.jpg")
                    if os.path.exists(plate_path) and os.path.getsize(plate_path) > 0:
                        yield event("cutting", f"Placa {i}/{total_slides} ya estaba lista, la salteo.", {"pct": pct, "current": i, "total": total_slides})
                        await asyncio.sleep(0)
                        output_files.append(plate_path)
                        continue
                    yield event("cutting", f"Creando placa {i}/{total_slides}...", {"pct": pct, "current": i, "total": total_slides})
                    await asyncio.sleep(0)
                    label = clip.label or ""
                    if ":" in label:
                        parts = label.split(":", 1)
                        speaker, dialogue = parts[0].strip(), parts[1].strip()
                    else:
                        speaker, dialogue = "", label
                    try:
                        await asyncio.to_thread(extract_frame, video_path, clip.start, frame_path)
                        await asyncio.to_thread(create_carousel_plate, frame_path, dialogue, speaker, plate_path)
                        output_files.append(plate_path)
                    except Exception as e:
                        yield event("cutting", f"⚠ Placa {i} falló: {str(e)[:60]}", {"pct": pct})
                        await asyncio.sleep(0)

            if not output_files:
                yield event("error", "No se generó ningún archivo."); return

            zip_name = f"carousel_{input_data.platform}_{export_id}.zip"
            zip_path = str(EXPORT_DIR / zip_name)
            yield event("merging", f"Empaquetando {len(output_files)} archivos en ZIP...", {"pct": 95})
            await asyncio.sleep(0)
            with zipfile.ZipFile(zip_path, "w") as zf:
                for f in output_files:
                    zf.write(f, os.path.basename(f))

            yield event("done", f"✓ {len(output_files)} slides listos.", {
                "download_url": f"/exports/{zip_name}",
                "filename": zip_name,
                "slide_count": len(output_files),
                "pct": 100,
            })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if delete_video_after and video_path and os.path.exists(video_path):
                try: os.remove(video_path)
                except: pass
            try: shutil.rmtree(str(carousel_dir), ignore_errors=True)
            except: pass
            _heavy_ops_semaphore.release()

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/")
def read_root():
    """Sirve el frontend directamente desde el servidor para evitar restricciones file://."""
    index_html = PROJECT_DIR / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html), media_type="text/html")
    return {"status": "Online - index.html no encontrado en el directorio del proyecto."}


@app.get("/login")
def read_login():
    """
    Deprecado: el login ahora es un modal en "/" (ver js/modules/auth.js),
    con usuarios reales en vez del secreto único que usaba esta pantalla
    (login.html/login.js siguen en el repo pero ya no los sirve nadie).
    Redirige para que un link o bookmark viejo no termine en una pantalla
    de login que ya no puede validar ninguna contraseña real.
    """
    return RedirectResponse(url="/")


@app.get("/historial")
def read_historial():
    """Página aparte con el historial de sesiones (antes vivía en index.html)."""
    historial_html = PROJECT_DIR / "historial.html"
    if historial_html.exists():
        return FileResponse(str(historial_html), media_type="text/html")
    return {"status": "historial.html no encontrado en el directorio del proyecto."}


@app.get("/auth/check", dependencies=[Depends(require_api_key)])
def auth_check(x_api_key: str | None = Header(default=None)):
    """
    El Auth Guard del frontend le pega a este endpoint con el header
    X-API-Key (el token guardado en el navegador) para saber si la sesión
    sigue siendo válida antes de mostrar el dashboard. Devuelve además
    username/role para poder restaurar el estado (badge de SUPERUSER, etc.)
    sin tener que loguearse de nuevo en cada F5.
    """
    session = _sessions.get(x_api_key) if x_api_key else None
    if session:
        return {"ok": True, "username": session["username"], "role": session["role"]}
    return {"ok": True, "auth_enabled": bool(API_ACCESS_KEY)}


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def auth_login(body: LoginBody):
    users = _load_users()
    user = users.get(body.username)
    if not user or not user.get("active", True) or not _verify_password(body.password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    token = secrets.token_hex(24)
    _sessions[token] = {"username": body.username, "role": user.get("role", "USER")}
    return {"token": token, "username": body.username, "role": user.get("role", "USER")}


@app.post("/auth/logout", dependencies=[Depends(require_api_key)])
def auth_logout(x_api_key: str | None = Header(default=None)):
    _sessions.pop(x_api_key, None)
    return {"ok": True}


class AccessRequestBody(BaseModel):
    name: str
    project: str = ""
    reason: str = ""


@app.post("/access-requests")
def create_access_request(body: AccessRequestBody):
    """Público (sin auth): cualquiera sin cuenta puede pedir acceso desde el modal de login."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio.")
    reqs = _load_requests()
    reqs.insert(0, {
        "id": uuid.uuid4().hex,
        "name": name,
        "project": body.project.strip(),
        "reason": body.reason.strip(),
        "status": "PENDING",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_requests(reqs)
    return {"ok": True}


@app.get("/admin/access-requests", dependencies=[Depends(require_superadmin)])
def list_access_requests():
    return {"requests": [r for r in _load_requests() if r["status"] == "PENDING"]}


class ApproveRequestBody(BaseModel):
    username: str
    password: str


@app.post("/admin/access-requests/{request_id}/approve", dependencies=[Depends(require_superadmin)])
def approve_access_request(request_id: str, body: ApproveRequestBody):
    reqs = _load_requests()
    req = next((r for r in reqs if r["id"] == request_id), None)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="Usuario y contraseña son obligatorios.")
    users = _load_users()
    if username in users:
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe.")
    pw_hash, salt = _hash_password(body.password)
    users[username] = {
        "password_hash": pw_hash,
        "salt": salt,
        "role": "USER",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_users(users)
    req["status"] = "APPROVED"
    _save_requests(reqs)
    return {"ok": True}


@app.post("/admin/access-requests/{request_id}/reject", dependencies=[Depends(require_superadmin)])
def reject_access_request(request_id: str):
    reqs = _load_requests()
    req = next((r for r in reqs if r["id"] == request_id), None)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    req["status"] = "REJECTED"
    _save_requests(reqs)
    return {"ok": True}


@app.get("/admin/users", dependencies=[Depends(require_superadmin)])
def list_users():
    users = _load_users()
    return {"users": [
        {"username": uname, "role": u.get("role"), "active": u.get("active", True), "created_at": u.get("created_at")}
        for uname, u in users.items()
    ]}


def _revoke_sessions_for(username: str):
    for tok in [t for t, s in _sessions.items() if s["username"] == username]:
        del _sessions[tok]


@app.post("/admin/users/{username}/reset-password", dependencies=[Depends(require_superadmin)])
def reset_user_password(username: str):
    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    new_password = secrets.token_urlsafe(9)
    pw_hash, salt = _hash_password(new_password)
    users[username]["password_hash"] = pw_hash
    users[username]["salt"] = salt
    _save_users(users)
    _revoke_sessions_for(username)
    return {"ok": True, "password": new_password}


@app.post("/admin/users/{username}/deactivate", dependencies=[Depends(require_superadmin)])
def deactivate_user(username: str):
    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    users[username]["active"] = False
    _save_users(users)
    _revoke_sessions_for(username)
    return {"ok": True}


@app.post("/admin/users/{username}/revoke-session", dependencies=[Depends(require_superadmin)])
def revoke_user_session(username: str):
    _revoke_sessions_for(username)
    return {"ok": True}


@app.get("/debug/ytdlp-info", dependencies=[Depends(require_api_key)])
def debug_ytdlp_info():
    """
    Diagnostico temporal: confirma si el plugin bgutil-ytdlp-pot-provider esta
    instalado y si yt-dlp lo detecta como plugin cargado. No requiere Shell
    (que es solo para planes pagos de Render) - se consulta como cualquier URL.
    """
    import importlib.metadata
    import io
    import contextlib

    result = {}

    try:
        result["bgutil_pip_version"] = importlib.metadata.version("bgutil-ytdlp-pot-provider")
    except importlib.metadata.PackageNotFoundError:
        result["bgutil_pip_version"] = None

    result["pot_provider_base_url_env"] = POT_PROVIDER_BASE_URL

    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            test_ydl = yt_dlp.YoutubeDL({"verbose": True, "simulate": True, "skip_download": True, "quiet": False})
            test_ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False, process=False)
    except Exception as e:
        buf.write(f"\n[EXCEPTION] {e}")

    verbose_output = buf.getvalue()
    plugin_lines = [line for line in verbose_output.splitlines() if "plugin" in line.lower() or "pot" in line.lower()]
    result["plugin_related_lines"] = plugin_lines
    result["full_verbose_tail"] = verbose_output[-3000:]

    return JSONResponse(result)
