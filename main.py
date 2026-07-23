import sys
import os
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import shutil
import tempfile
import time
import hashlib
import json
import asyncio
import zipfile
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from google import genai
from google.genai import types as genai_types
import yt_dlp
import requests
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================

app = FastAPI(title="AI Audiovisual Suite - Backend de Escaneo Continuo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

# Groq (opcional): último recurso cuando TODOS los modelos Gemini agotaron su cuota diaria.
# Sin diarización de speakers reales (Whisper no la hace), pero mantiene la app funcionando
# en vez de fallar por completo. Si no está seteada, este fallback simplemente se salta.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

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


def download_youtube_video(url: str) -> str:
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
        'format': 'best[height<=480][ext=mp4]/best[height<=480]/bestvideo[height<=480]+bestaudio/best[height<=720]/best',
        'outtmpl': os.path.join(tempfile.gettempdir(), '%(id)s.%(ext)s'),
        'noplaylist': True,
        # Permite a yt-dlp descargar el script solver de YouTube (deno) para resolver
        # el challenge de firma; sin esto solo consigue miniaturas, nunca video real.
        'remote_components': ['ejs:github'],
        'extractor_args': extractor_args,
    }

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
            if "403" in err_str or "401" in err_str or "Forbidden" in err_str or "cookie" in err_str.lower():
                print(f"   ⚠ Falló por permisos: {err_str[:120]}")
                continue
            print(f"   ✗ Error no relacionado con autenticación: {err_str[:200]}")
            raise HTTPException(status_code=400, detail=f"Error al descargar el video: {err_str}")

    # Si llegamos acá, todos los métodos fallaron
    raise HTTPException(
        status_code=403,
        detail=(
            f"No se pudo descargar el video con ningún método de autenticación. "
            f"Último error: {str(last_error)[:200]}. "
            f"Soluciones: (1) Verificá que el archivo de Drive tenga permiso 'Cualquier persona con el enlace'. "
            f"(2) Exportá cookies.txt desde Chrome y guardalo en la carpeta del proyecto. "
            f"(3) Bajá el video manualmente y subilo con 'Subir Local'."
        )
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
# gemini-3.1-flash-lite tiene ~500 req/día (vs ~20 req/día del resto), por eso se agregó
# como red de contención de alta capacidad antes de llegar a los modelos más nuevos/limitados.
GEMINI_MODELS = [
    m.strip() for m in os.getenv(
        "GEMINI_MODELS",
        "gemini-2.0-flash,gemini-2.0-flash-lite,gemini-2.5-flash,"
        "gemini-2.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash"
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


def _collapse_repeated_runs(text: str, max_repeats: int = 3) -> str:
    """
    Colapsa una misma palabra repetida muchas veces seguidas a un máximo de
    `max_repeats` repeticiones. Es el remedio para la alucinación típica de
    los modelos de transcripción durante tramos de música/silencio/audio
    poco claro, donde quedan "trabados" repitiendo la última palabra cientos
    de veces (ej: "no, no, no, no, no, ..." x300). El prompt ya les pide que
    no lo hagan, pero la instrucción sola no siempre alcanza.
    Deja intactas las repeticiones cortas normales (2-3 veces, típicas del
    habla real para dar énfasis).
    """
    import re

    pattern = re.compile(r'\b(\w+)\b((?:[\s,.:;!?-]+\1\b){3,})', re.IGNORECASE)

    def _replace(match):
        word = match.group(1)
        sep_match = re.match(r'[\s,.:;!?-]+', match.group(2))
        sep = sep_match.group(0) if sep_match else ' '
        return (word + sep) * (max_repeats - 1) + word

    return pattern.sub(_replace, text)


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
    "NEVER fill a music gap by repeating a word (such as 'no, no, no' or any filler). "
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
    "and NEVER fill music gaps with repeated words like 'no, no, no' or any filler.\n"
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


def _call_gemini_with_retry(uploaded_file, max_attempts: int = 3):
    """
    Llama a Gemini con reintentos y fallback automático entre modelos.
    - Cuota diaria agotada (PerDay) → cambia de modelo inmediatamente, no cuenta como intento.
    - Rate limit por minuto → espera y reintenta con el mismo modelo.
    - Otros errores → backoff exponencial.
    """
    last_error = None
    attempts_remaining = max_attempts
    call_n = 0

    while attempts_remaining > 0:
        model = _get_active_model()
        if model is None:
            raise Exception(
                f"Todos los modelos de Gemini tienen la cuota diaria agotada "
                f"({', '.join(GEMINI_MODELS)}). Último error: {last_error}."
            )
        call_n += 1
        try:
            print(f"   Intento {call_n} [modelo: {model}] (max_output_tokens={MAX_OUTPUT_TOKENS})...")
            response = client.models.generate_content(
                model=model,
                contents=[uploaded_file, PROMPT_ESCANEO],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    temperature=0.2,
                ),
            )
            text = _extract_text_safely(response)
            if text and len(text.strip()) > 50:
                if _is_meaningful_transcript(text):
                    return text
                print(f"   ⚠ Intento {call_n}: respuesta sin contenido de calidad. Reintentando...")
            else:
                print(f"   ⚠ Intento {call_n} devolvió respuesta vacía o incompleta.")
            attempts_remaining -= 1
        except Exception as e:
            last_error = e
            if _is_daily_quota_exhausted(e):
                print(f"   ⚠ Cuota DIARIA agotada para [{model}]. Cambiando al siguiente modelo...")
                _exhausted_models.add(model)
                # No decrementar attempts_remaining: cuota diaria no es un fallo del intento
            elif _is_quota_error(e):
                wait = _extract_retry_delay(e)
                print(f"   ⚠ Rate limit temporal (429) en [{model}]. Esperando {wait}s...")
                time.sleep(wait)
                attempts_remaining -= 1
            else:
                print(f"   ⚠ Intento {call_n} error [{model}]: {type(e).__name__}: {e}")
                time.sleep(2 ** (max_attempts - attempts_remaining + 1))
                attempts_remaining -= 1

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
        if _is_daily_quota_exhausted(e):
            print(f"   ⚠ Cuota DIARIA agotada para [{model}] en fallback. Cambiando de modelo...")
            _exhausted_models.add(model)
        elif _is_quota_error(e):
            wait = _extract_retry_delay(e)
            print(f"   ⚠ Fallback también falló por cuota. Esperando {wait}s...")
            time.sleep(wait)
        print(f"   ⚠ Fallback también falló: {e}")

    raise Exception(
        f"Gemini no devolvió contenido utilizable tras {max_attempts} intentos. "
        f"Último error: {last_error}."
    )


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


def _process_single_video_file(video_path: str) -> str:
    """
    Extrae el audio del archivo (drásticamente menos tokens que video),
    lo sube a Google Files, llama a Gemini y devuelve el transcript.
    Audio usa ~32 tokens/seg vs ~290 tokens/seg de video — cabe en el free tier.
    """
    audio_path = None
    path_to_upload = video_path

    # Intentar extraer audio para minimizar consumo de tokens
    try:
        audio_path = convert_to_clean_audio(video_path, mode="mp3")
        path_to_upload = audio_path
        size_mb = round(os.path.getsize(audio_path) / (1024 * 1024), 2)
        print(f"   Audio extraído: {os.path.basename(audio_path)} ({size_mb} MB). Subiendo a Google...")
    except Exception as e:
        print(f"   ⚠ No se pudo extraer audio ({e}). Subiendo archivo original...")

    try:
        uploaded_file = client.files.upload(file=path_to_upload)

        while uploaded_file.state.name == "PROCESSING":
            time.sleep(6)
            uploaded_file = client.files.get(name=uploaded_file.name)
            print(f"   Google procesando {os.path.basename(path_to_upload)}...")

        if uploaded_file.state.name == "FAILED":
            raise Exception(f"La indexación de {os.path.basename(path_to_upload)} falló en Google.")

        try:
            text = _call_gemini_with_retry(uploaded_file)
        except Exception as gemini_error:
            if GROQ_API_KEY:
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


def process_video_smart(video_path: str, progress_callback=None) -> str:
    """
    Decide si procesar el video entero o partirlo en tramos según su duración.
    progress_callback(stage, message) opcional para reportar avance.
    """
    def report(stage, msg):
        if progress_callback:
            progress_callback(stage, msg)
        print(f"[{stage}] {msg}")

    duration_seconds = get_video_duration_seconds(video_path)
    duration_minutes = duration_seconds / 60 if duration_seconds else 0

    if duration_minutes > 0:
        report("info", f"Duración detectada: {duration_minutes:.1f} minutos")

    # Si es corto o no pudimos detectar duración, procesamos entero
    if duration_minutes == 0 or duration_minutes <= CHUNK_THRESHOLD_MIN:
        report("analyzing", "Procesando video completo (un solo tramo)...")
        return _process_single_video_file(video_path)

    # Video largo: procesar por tramos
    chunk_seconds = CHUNK_DURATION_MIN * 60
    estimated_chunks = int((duration_seconds + chunk_seconds - 1) // chunk_seconds)
    report("analyzing", f"Video largo ({duration_minutes:.1f} min). Dividiendo en {estimated_chunks} tramos de {CHUNK_DURATION_MIN} min...")

    chunks = split_video_in_chunks(video_path, chunk_seconds)
    if len(chunks) <= 1:
        report("info", "No se pudo partir; procesando entero como fallback.")
        return _process_single_video_file(video_path)

    full_transcript = []
    try:
        for i, (offset, chunk_path) in enumerate(chunks, start=1):
            if i > 1:
                report("analyzing", f"Pausa de {INTER_CHUNK_DELAY}s entre tramos (cuota Gemini)...")
                time.sleep(INTER_CHUNK_DELAY)
            report("analyzing", f"Procesando tramo {i}/{len(chunks)} (desde minuto {offset//60})...")
            chunk_text = _process_single_video_file(chunk_path)
            adjusted = shift_timestamps_in_transcript(chunk_text, offset)
            full_transcript.append(f"\n=== TRAMO {i} (desde {offset//60:02d}:{offset%60:02d}) ===\n")
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


async def process_video_with_gemini(video_path: str, cache_key: str = None):
    """Versión no-streaming (compatible con el endpoint clásico)."""
    # Chequeo de cache
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            print(f"✓ Cache hit para {cache_key[:12]}...")
            cached["from_cache"] = True
            return cached

    try:
        print("Iniciando procesamiento inteligente (con detección automática de duración)...")
        text = process_video_smart(video_path)

        result = {"title": "Metraje Completo Analizado", "raw_timeline": text, "from_cache": False}

        if cache_key:
            cache_set(cache_key, result)

        return result

    except Exception as e:
        print(f"Error en Gemini: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en la IA: {str(e)}")


async def process_video_streaming(video_path: str, cache_key: str = None):
    """Versión streaming: emite eventos SSE con el progreso real."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # 1. Cache check
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            yield event("cache_hit", "Resultado encontrado en cache. Cargando...")
            cached["from_cache"] = True
            yield event("done", "Listo (desde cache)", {"result": cached})
            return

    try:
        # 2. Detectar duración y decidir si procesar entero o por tramos
        duration_seconds = get_video_duration_seconds(video_path)
        duration_minutes = duration_seconds / 60 if duration_seconds else 0

        if duration_minutes > 0:
            yield event("info", f"Duración del video: {duration_minutes:.1f} minutos")

        # 3. Procesamiento (entero o por tramos)
        if duration_minutes == 0 or duration_minutes <= CHUNK_THRESHOLD_MIN:
            yield event("uploading", "Video corto: procesando en un solo tramo...")
            await asyncio.sleep(0)
            try:
                text = _process_single_video_file(video_path)
            except Exception as e:
                yield event("error", str(e))
                return
        else:
            # Video largo: tramos
            chunk_seconds = CHUNK_DURATION_MIN * 60
            estimated = int((duration_seconds + chunk_seconds - 1) // chunk_seconds)
            yield event("analyzing", f"Video largo ({duration_minutes:.1f} min). Partiendo en {estimated} tramos de {CHUNK_DURATION_MIN} min...")
            await asyncio.sleep(0)

            chunks = split_video_in_chunks(video_path, chunk_seconds)
            if len(chunks) <= 1:
                yield event("analyzing", "No se pudo partir el video; procesando completo...")
                try:
                    text = _process_single_video_file(video_path)
                except Exception as e:
                    yield event("error", str(e))
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
                        try:
                            chunk_text = _process_single_video_file(chunk_path)
                        except Exception as e:
                            yield event("error", f"Falló el tramo {i}: {e}")
                            return
                        adjusted = shift_timestamps_in_transcript(chunk_text, offset)
                        full_transcript.append(f"\n=== TRAMO {i} (desde {offset//60:02d}:{offset%60:02d}) ===\n")
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
            "from_cache": False
        }

        if cache_key:
            cache_set(cache_key, result)

        yield event("done", "Análisis completo", {"result": result})

    except Exception as e:
        yield event("error", f"Error en el procesamiento: {str(e)}")


# ============================================================
# ENDPOINTS CLÁSICOS (mantenidos por compatibilidad)
# ============================================================

@app.post("/analyze-url")
async def analyze_url(input_data: UrlInput):
    cache_key = url_hash(input_data.url)
    cached = cache_get(cache_key)
    if cached:
        cached["from_cache"] = True
        return cached

    video_path = download_youtube_video(input_data.url)
    try:
        return await process_video_with_gemini(video_path, cache_key=cache_key)
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


@app.post("/analyze-video")
async def analyze_video(file: UploadFile = File(...)):
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, file.filename)
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        cache_key = file_hash(video_path)
        return await process_video_with_gemini(video_path, cache_key=cache_key)
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


# ============================================================
# ENDPOINTS CON STREAMING DE PROGRESO (nuevos)
# ============================================================

@app.post("/analyze-url-stream")
async def analyze_url_stream(input_data: UrlInput):
    """Versión streaming: el frontend recibe eventos de progreso en tiempo real."""
    cache_key = url_hash(input_data.url)

    async def generator():
        # Cache hit inmediato
        cached = cache_get(cache_key)
        if cached:
            cached["from_cache"] = True
            yield f"data: {json.dumps({'stage': 'cache_hit', 'message': 'Resultado en cache', 'result': cached}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'stage': 'done', 'message': 'Listo', 'result': cached}, ensure_ascii=False)}\n\n"
            return

        # Descarga
        yield f"data: {json.dumps({'stage': 'downloading', 'message': 'Descargando video desde la URL...'}, ensure_ascii=False)}\n\n"
        try:
            video_path = download_youtube_video(input_data.url)
        except HTTPException as e:
            yield f"data: {json.dumps({'stage': 'error', 'message': e.detail}, ensure_ascii=False)}\n\n"
            return

        try:
            async for chunk in process_video_streaming(video_path, cache_key=cache_key):
                yield chunk
        finally:
            if os.path.exists(video_path):
                os.remove(video_path)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/analyze-video-stream")
async def analyze_video_stream(file: UploadFile = File(...)):
    """Versión streaming para archivos locales."""
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, file.filename)
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    cache_key = file_hash(video_path)

    async def generator():
        try:
            async for chunk in process_video_streaming(video_path, cache_key=cache_key):
                yield chunk
        finally:
            if os.path.exists(video_path):
                os.remove(video_path)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# ENDPOINTS DE INSPECCIÓN Y CONVERSIÓN (opcionales, manuales)
# ============================================================

@app.post("/inspect-file")
async def inspect_file(file: UploadFile = File(...)):
    """
    Recibe un archivo, lo analiza con ffprobe y devuelve qué tiene adentro.
    El frontend usa esto para preguntarle al usuario si quiere convertir
    antes de procesar (cuando detecta audio renombrado como video).
    Después de inspeccionar, deja el archivo en una ruta temporal y devuelve
    esa ruta junto con la info, para que el siguiente paso lo use.
    """
    import uuid
    temp_dir = tempfile.gettempdir()
    # Generamos un nombre único para que dos archivos con el mismo nombre no choquen
    safe_name = f"inspect_{uuid.uuid4().hex[:8]}_{file.filename}"
    temp_path = os.path.join(temp_dir, safe_name)

    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    info = inspect_media_file(temp_path)
    info["temp_path"] = temp_path  # frontend devuelve esta ruta en el siguiente paso
    return info


class ProcessInspectedInput(BaseModel):
    temp_path: str
    convert_to_audio: bool = False
    conversion_mode: str = "copy"  # 'copy' (m4a) o 'mp3'


@app.post("/process-inspected")
async def process_inspected(input_data: ProcessInspectedInput):
    """
    Procesa un archivo previamente inspeccionado con /inspect-file.
    Si convert_to_audio=True, primero lo convierte con ffmpeg, después analiza.
    Versión streaming para reportar progreso.
    """
    temp_path = input_data.temp_path
    if not os.path.exists(temp_path):
        raise HTTPException(status_code=404, detail="El archivo temporal no existe o ya fue limpiado.")

    async def generator():
        path_to_process = temp_path
        created_files = []  # para limpiar al final

        try:
            # Conversión opcional ANTES de procesar
            if input_data.convert_to_audio:
                yield f"data: {json.dumps({'stage': 'converting', 'message': f'Convirtiendo a audio limpio (modo={input_data.conversion_mode})...'}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
                try:
                    converted = convert_to_clean_audio(temp_path, mode=input_data.conversion_mode)
                    path_to_process = converted
                    created_files.append(converted)
                    yield f"data: {json.dumps({'stage': 'converting', 'message': f'✓ Conversión completa. Continuando con análisis...'}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)
                except Exception as e:
                    yield f"data: {json.dumps({'stage': 'error', 'message': f'La conversión falló: {e}'}, ensure_ascii=False)}\n\n"
                    return

            # Procesamiento normal con cacheo
            cache_key = file_hash(path_to_process)
            async for chunk in process_video_streaming(path_to_process, cache_key=cache_key):
                yield chunk
        finally:
            # Limpieza
            for f in created_files:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    return StreamingResponse(generator(), media_type="text/event-stream")


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


@app.post("/cache-clear")
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


class ClipSpec(BaseModel):
    start: str
    end: str
    label: str = ""


class ExportClipsInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    clips: list[ClipSpec]


@app.post("/export-clips")
async def export_clips_endpoint(input_data: ExportClipsInput):
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        if not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido para exportar clips.")
            return
        if not input_data.clips:
            yield event("error", "No hay clips definidos para exportar.")
            return

        export_id = uuid.uuid4().hex[:12]
        clip_dir = EXPORT_DIR / export_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        using_uploaded_file = bool(input_data.video_path)

        try:
            if using_uploaded_file:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo.")
                    return
                video_path = input_data.video_path
            else:
                yield event("downloading", f"Descargando video fuente para cortar {len(input_data.clips)} clip(s)...")
                await asyncio.sleep(0)
                try:
                    video_path = download_youtube_video(input_data.url)
                except HTTPException as e:
                    yield event("error", e.detail)
                    return

            clip_files = []
            for i, clip in enumerate(input_data.clips, 1):
                safe_label = "".join(c if c.isalnum() or c in "-_ " else "_" for c in clip.label)[:25]
                clip_path = str(clip_dir / f"{i:02d}_{safe_label or 'clip'}.mp4")
                yield event("cutting", f"Cortando clip {i}/{len(input_data.clips)}: {clip.start} → {clip.end}")
                await asyncio.sleep(0)
                try:
                    cut_single_clip(video_path, clip.start, clip.end, clip_path)
                    clip_files.append(clip_path)
                except Exception as e:
                    yield event("cutting", f"⚠ Clip {i} falló: {str(e)[:80]}. Continuando...")
                    await asyncio.sleep(0)

            if not clip_files:
                yield event("error", "Ningún clip se pudo cortar.")
                return

            if len(clip_files) == 1:
                single_name = f"clip_{export_id}.mp4"
                shutil.copy(clip_files[0], str(EXPORT_DIR / single_name))
                yield event("done", "✓ Clip exportado.", {
                    "download_url": f"/exports/{single_name}",
                    "filename": single_name,
                    "clip_count": 1
                })
            else:
                zip_name = f"clips_{export_id}.zip"
                zip_path = str(EXPORT_DIR / zip_name)
                with zipfile.ZipFile(zip_path, "w") as zf:
                    for cf in clip_files:
                        zf.write(cf, os.path.basename(cf))
                yield event("done", f"✓ {len(clip_files)} clips empaquetados en ZIP.", {
                    "download_url": f"/exports/{zip_name}",
                    "filename": zip_name,
                    "clip_count": len(clip_files)
                })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if video_path and os.path.exists(video_path):
                try:
                    os.remove(video_path)
                except Exception:
                    pass
            try:
                shutil.rmtree(str(clip_dir), ignore_errors=True)
            except Exception:
                pass

    return StreamingResponse(generator(), media_type="text/event-stream")


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
# EXPORTACIÓN DE VIDEO PARA REDES SOCIALES
# ============================================================

class ReelClipSpec(BaseModel):
    start: str
    end: str
    label: str = ""


class ReelExportInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    clips: list[ReelClipSpec]
    platform: str


class CarouselExportInput(BaseModel):
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    clips: list[ReelClipSpec]
    platform: str


@app.post("/export-reel")
async def export_reel_endpoint(input_data: ReelExportInput):
    """Descarga, corta, une y convierte clips al formato de la plataforma. Devuelve un MP4."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        if not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay clips definidos."); return
        cfg = PLATFORM_CONFIGS.get(input_data.platform)
        if not cfg:
            yield event("error", f"Plataforma desconocida: {input_data.platform}"); return

        target_w, target_h, max_dur = cfg
        export_id = uuid.uuid4().hex[:12]
        clip_dir = EXPORT_DIR / export_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        using_uploaded_file = bool(input_data.video_path)

        try:
            if using_uploaded_file:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo."); return
                video_path = input_data.video_path
            else:
                yield event("downloading", "Descargando video fuente...")
                await asyncio.sleep(0)
                try:
                    video_path = download_youtube_video(input_data.url)
                except HTTPException as e:
                    yield event("error", e.detail); return

            clip_files = []
            for i, clip in enumerate(input_data.clips, 1):
                safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in clip.label)[:20]
                clip_path = str(clip_dir / f"{i:02d}_{safe or 'clip'}.mp4")
                yield event("cutting", f"Cortando clip {i}/{len(input_data.clips)}: {clip.start} → {clip.end}")
                await asyncio.sleep(0)
                try:
                    cut_single_clip(video_path, clip.start, clip.end, clip_path)
                    clip_files.append(clip_path)
                except Exception as e:
                    yield event("cutting", f"⚠ Clip {i} falló: {str(e)[:60]}. Continuando...")
                    await asyncio.sleep(0)

            if not clip_files:
                yield event("error", "Ningún clip se pudo cortar."); return

            # Escalar cada clip por separado al formato de la plataforma
            output_files = []
            for i, clip_path in enumerate(clip_files, 1):
                yield event("converting", f"Aplicando formato {target_w}×{target_h} a clip {i}/{len(clip_files)}...")
                await asyncio.sleep(0)
                scaled_path = str(clip_dir / f"scaled_{i:02d}.mp4")
                try:
                    scale_to_platform(clip_path, scaled_path, target_w, target_h, max_dur)
                    output_files.append(scaled_path)
                except Exception as e:
                    yield event("converting", f"⚠ Clip {i} falló al convertir: {str(e)[:60]}")
                    await asyncio.sleep(0)

            if not output_files:
                yield event("error", "Ningún clip se pudo convertir."); return

            if len(output_files) == 1:
                output_name = f"reel_{input_data.platform}_{export_id}.mp4"
                shutil.copy(output_files[0], str(EXPORT_DIR / output_name))
                yield event("done", f"✓ Video listo en {target_w}×{target_h}.", {
                    "download_url": f"/exports/{output_name}",
                    "filename": output_name,
                    "platform": input_data.platform,
                    "resolution": f"{target_w}x{target_h}",
                    "clip_count": 1,
                })
            else:
                zip_name = f"reel_{input_data.platform}_{export_id}.zip"
                zip_path = str(EXPORT_DIR / zip_name)
                with zipfile.ZipFile(zip_path, "w") as zf:
                    for f in output_files:
                        zf.write(f, os.path.basename(f))
                yield event("done", f"✓ {len(output_files)} clips listos en {target_w}×{target_h}.", {
                    "download_url": f"/exports/{zip_name}",
                    "filename": zip_name,
                    "platform": input_data.platform,
                    "resolution": f"{target_w}x{target_h}",
                    "clip_count": len(output_files),
                })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if video_path and os.path.exists(video_path):
                try: os.remove(video_path)
                except: pass
            try: shutil.rmtree(str(clip_dir), ignore_errors=True)
            except: pass

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/export-carousel")
async def export_carousel_endpoint(input_data: CarouselExportInput):
    """Genera un carrusel: clips 1:1 (ZIP de MP4) o placas de texto (ZIP de JPG)."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        if not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay slides definidos."); return
        if input_data.platform not in CAROUSEL_PLATFORMS:
            yield event("error", f"Plataforma no es carrusel: {input_data.platform}"); return

        export_id = uuid.uuid4().hex[:12]
        carousel_dir = EXPORT_DIR / f"car_{export_id}"
        carousel_dir.mkdir(parents=True, exist_ok=True)
        video_path = None
        using_uploaded_file = bool(input_data.video_path)

        try:
            if using_uploaded_file:
                if not os.path.exists(input_data.video_path):
                    yield event("error", "El archivo subido ya no existe en el servidor, volvé a subirlo."); return
                video_path = input_data.video_path
            else:
                yield event("downloading", "Descargando video fuente...")
                await asyncio.sleep(0)
                try:
                    video_path = download_youtube_video(input_data.url)
                except HTTPException as e:
                    yield event("error", e.detail); return

            output_files = []

            if input_data.platform == "ig_carrusel_clips":
                for i, clip in enumerate(input_data.clips, 1):
                    yield event("cutting", f"Procesando slide {i}/{len(input_data.clips)} (clip 1:1)...")
                    await asyncio.sleep(0)
                    raw_clip = str(carousel_dir / f"raw_{i:02d}.mp4")
                    out_clip = str(carousel_dir / f"slide_{i:02d}.mp4")
                    try:
                        cut_single_clip(video_path, clip.start, clip.end, raw_clip)
                        scale_to_platform(raw_clip, out_clip, 1080, 1080, 60)
                        output_files.append(out_clip)
                    except Exception as e:
                        yield event("cutting", f"⚠ Slide {i} falló: {str(e)[:60]}")
                        await asyncio.sleep(0)

            elif input_data.platform == "ig_carrusel_placas":
                for i, clip in enumerate(input_data.clips, 1):
                    yield event("cutting", f"Creando placa {i}/{len(input_data.clips)}...")
                    await asyncio.sleep(0)
                    frame_path = str(carousel_dir / f"frame_{i:02d}.jpg")
                    plate_path = str(carousel_dir / f"placa_{i:02d}.jpg")
                    label = clip.label or ""
                    if ":" in label:
                        parts = label.split(":", 1)
                        speaker, dialogue = parts[0].strip(), parts[1].strip()
                    else:
                        speaker, dialogue = "", label
                    try:
                        extract_frame(video_path, clip.start, frame_path)
                        create_carousel_plate(frame_path, dialogue, speaker, plate_path)
                        output_files.append(plate_path)
                    except Exception as e:
                        yield event("cutting", f"⚠ Placa {i} falló: {str(e)[:60]}")
                        await asyncio.sleep(0)

            if not output_files:
                yield event("error", "No se generó ningún archivo."); return

            zip_name = f"carousel_{input_data.platform}_{export_id}.zip"
            zip_path = str(EXPORT_DIR / zip_name)
            yield event("merging", f"Empaquetando {len(output_files)} archivos en ZIP...")
            await asyncio.sleep(0)
            with zipfile.ZipFile(zip_path, "w") as zf:
                for f in output_files:
                    zf.write(f, os.path.basename(f))

            yield event("done", f"✓ {len(output_files)} slides listos.", {
                "download_url": f"/exports/{zip_name}",
                "filename": zip_name,
                "slide_count": len(output_files),
            })

        except Exception as e:
            yield event("error", f"Error inesperado: {e}")
        finally:
            if video_path and os.path.exists(video_path):
                try: os.remove(video_path)
                except: pass
            try: shutil.rmtree(str(carousel_dir), ignore_errors=True)
            except: pass

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/")
def read_root():
    """Sirve el frontend directamente desde el servidor para evitar restricciones file://."""
    index_html = PROJECT_DIR / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html), media_type="text/html")
    return {"status": "Online - index.html no encontrado en el directorio del proyecto."}


@app.get("/debug/ytdlp-info")
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
