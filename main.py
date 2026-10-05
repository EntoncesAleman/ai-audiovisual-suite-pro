import sys
import os
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import re
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
from typing import Literal
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from google import genai
from google.genai import types as genai_types
import yt_dlp
import requests
from dotenv import load_dotenv
import premiere_export
import capcut_export
from studio_store import RecordStore
from studio_backend import install_studio, upload_media, account
from studio_tools import ImageRequest, CampaignRequest, CapCutPackageRequest, generate_images, generate_campaign, build_capcut_package
from studio_render import StudioRenderRequest, render_studio
from studio_tools import CampaignPackageRequest, build_campaign_package

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
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()],
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
# Usuarios reales (username + password) con roles. Las contraseñas NUNCA
# se guardan en texto plano: se hashean con PBKDF2-HMAC-SHA256 + salt
# aleatoria por usuario.
#
# PERSISTENCIA: usuarios, access requests y ownership de exports viven en
# Supabase (Postgres), no en JSON local - un redeploy de Render reconstruye
# el filesystem desde la imagen, así que cualquier JSON en disco se perdía
# en cada redeploy (no solo un restart). Se accede vía la REST API de
# PostgREST (Data API) con el service_role key, siempre server-side - el
# frontend nunca habla con Supabase directo. Todo vive en un schema propio
# (SUPABASE_SCHEMA, ver migración) separado de "public", para no mezclarse
# con otras apps que puedan compartir el mismo proyecto Supabase.
# ------------------------------------------------------------------
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_SCHEMA = os.getenv("SUPABASE_SCHEMA", "avsuite")
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL / SUPABASE_SERVICE_KEY. Son obligatorias: usuarios, planes, consumo, "
        "access requests y ownership de exports viven en Supabase (no en JSON local), así que sin "
        "esto el server no tiene dónde persistir nada.\n"
        "Ejemplo: export SUPABASE_URL='https://xxxx.supabase.co'\n"
        "         export SUPABASE_SERVICE_KEY='eyJ...' (service_role, NUNCA el anon/publishable key)"
    )


def _supabase_request(method: str, table: str, params: dict | None = None, json_body=None, prefer: str | None = None):
    """
    Llamada cruda a la Data API (PostgREST) de Supabase. Siempre con el
    service_role key (bypassa RLS) - nunca se expone al frontend. `table`
    puede ser "users", "access_requests", "exports_index" o "rpc/<func>".
    """
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept-Profile": SUPABASE_SCHEMA,
        "Content-Profile": SUPABASE_SCHEMA,
    }
    if prefer:
        headers["Prefer"] = prefer
    resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=15)
    if not resp.ok:
        raise RuntimeError(f"Supabase {method} {table} falló ({resp.status_code}): {resp.text[:300]}")
    return resp


def _supabase_select(table: str, params: dict | None = None) -> list:
    return _supabase_request("GET", table, params={"select": "*", **(params or {})}).json()


def _supabase_upsert(table: str, rows, on_conflict: str):
    """Upsert (insert o update por PK) de una o más filas. No borra filas ausentes del batch."""
    if isinstance(rows, dict):
        rows = [rows]
    if not rows:
        return
    _supabase_request(
        "POST", table, params={"on_conflict": on_conflict}, json_body=rows,
        prefer="resolution=merge-duplicates,return=minimal",
    )


# Session token hashes are persisted in studio_records, expire after 7 days
# and can be revoked across server restarts. Raw tokens are never stored.


def _load_users() -> dict:
    rows = _supabase_select("users")
    return {r["username"]: {k: v for k, v in r.items() if k != "username"} for r in rows}


def _save_users(users: dict):
    """Upsert de TODO el dict recibido (siempre se llama después de _load_users(),
    así que ya trae todas las filas relevantes - no hace falta un diff)."""
    rows = [{"username": uname, **fields} for uname, fields in users.items()]
    _supabase_upsert("users", rows, on_conflict="username")


def _get_user_row(username: str) -> dict | None:
    """Fetch de UNA sola fila (evita traer toda la tabla) - usado en los paths
    calientes de auth/metering que corren en cada request."""
    rows = _supabase_select("users", params={"username": f"eq.{username}", "limit": "1"})
    if not rows:
        return None
    r = rows[0]
    return {k: v for k, v in r.items() if k != "username"}


def _load_requests() -> list:
    return _supabase_select("access_requests", params={"order": "created_at.desc"})


def _save_requests(reqs: list):
    _supabase_upsert("access_requests", reqs, on_conflict="id")


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
    """Exige una sesión persistente válida o la clave estática de compatibilidad."""
    if x_api_key:
        session = studio_store.get_session(x_api_key)
        if session:
            user = _get_user_row(session["username"])
            if not user or not user.get("active",True):
                raise HTTPException(401,"Sesión inválida o expirada. Iniciá sesión de nuevo.")
            session["role"] = user.get("role","USER")
            return session
        if API_ACCESS_KEY and x_api_key == API_ACCESS_KEY:
            return {"username": "legacy", "role": "USER"}
    raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Iniciá sesión de nuevo.")


def require_superadmin(x_api_key: str | None = Header(default=None)):
    session = require_api_key(x_api_key)
    if not session or session.get("role") != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="Necesitás permisos de administrador.")
    return session

# ------------------------------------------------------------------
# PLANES (FREE/PRO) + METERING
# ------------------------------------------------------------------
# `role` (SUPERADMIN vs USER) sigue siendo el eje de permisos de admin.
# `plan` (FREE/PRO) es un eje independiente que decide límites de uso -
# se agrega como campo nuevo en users_db.json, con default perezoso
# (_ensure_plan_defaults) para no necesitar un script de migración aparte
# sobre el único usuario que ya existía antes de esta fase.
PLAN_FREE = "FREE"
PLAN_PRO = "PRO"

FREE_DAILY_LIMIT_SECONDS = int(os.getenv("FREE_DAILY_LIMIT_SECONDS", str(60 * 60)))   # 60 min/día
FREE_MAX_FILE_SECONDS = int(os.getenv("FREE_MAX_FILE_SECONDS", str(60 * 60)))         # 60 min/archivo
FREE_MAX_CONCURRENT_JOBS = 1
PRO_MAX_CONCURRENT_JOBS = 3          # fair use del lado app; el semáforo global (MAX_CONCURRENT_HEAVY_OPS)
                                     # sigue siendo el límite real de infraestructura en el free tier de Render.
FREE_MAX_BATCH_CLIPS = 3            # tope de clips por exportación (export-clips/reel/carousel/capcut) en FREE
FREE_MAX_EXPORTS_HISTORY = 10       # cuántos exports propios lista /exports para un usuario FREE


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ensure_plan_defaults(user: dict) -> dict:
    """Migración perezosa: completa plan/daily_usage_* la primera vez que se
    lee un usuario creado antes de esta fase (o recién creado sin esos campos)."""
    user.setdefault("plan", PLAN_PRO if user.get("role") == "SUPERADMIN" else PLAN_FREE)
    user.setdefault("daily_usage_seconds", 0)
    user.setdefault("daily_usage_date", _today_str())
    return user


def get_current_user(x_api_key: str | None = Header(default=None)) -> dict:
    """
    Dependency que resuelve la sesión (require_api_key) y la enriquece con
    plan/límites, para que los endpoints de metering/feature-gating no
    tengan que releer users_db.json cada uno a mano. Devuelve siempre un
    dict con username/role/plan/unrestricted (nunca None).
    """
    session = require_api_key(x_api_key)
    username = session.get("username")
    role = session.get("role", "USER")
    if username == "legacy":
        # API_ACCESS_KEY estática (compatibilidad, sin cuenta real detrás):
        # no tiene sentido meterle límites de plan a un secreto compartido.
        return {"username": "legacy", "role": role, "plan": PLAN_PRO, "unrestricted": True}
    user = _get_user_row(username)
    if not user or not user.get("active",True):
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada. Iniciá sesión de nuevo.")
    _ensure_plan_defaults(user)
    return {
        "username": username,
        "role": role,
        "plan": user.get("plan", PLAN_FREE),
        "unrestricted": role == "SUPERADMIN",
        "daily_usage_seconds": user.get("daily_usage_seconds", 0),
        "daily_usage_date": user.get("daily_usage_date"),
    }


def require_pro(user: dict = Depends(get_current_user)) -> dict:
    """Gate simple on/off para funciones exclusivas de PRO (Voiceover, Premiere/XML)."""
    if not user["unrestricted"] and user["plan"] != PLAN_PRO:
        raise HTTPException(status_code=403, detail="Esta función es exclusiva del plan PRO. Pedile a un administrador que active tu cuenta en PRO.")
    return user


def _check_free_quota(user: dict, duration_seconds: float | None):
    """
    Enforcement de FREE: 60 min por archivo + 60 min/día acumulados. Se
    llama ANTES de arrancar el trabajo pesado (ya se conoce la duración real
    en ese punto - ver process_video_smart/streaming), para no gastar cuota
    de Gemini/Groq en un análisis que de todos modos se va a rechazar.
    """
    if user["unrestricted"] or user["plan"] != PLAN_FREE:
        return
    if duration_seconds and duration_seconds > FREE_MAX_FILE_SECONDS:
        raise HTTPException(
            status_code=403,
            detail=f"El plan FREE permite archivos de hasta {FREE_MAX_FILE_SECONDS // 60} minutos. Este archivo dura {duration_seconds / 60:.1f} min. Pasate a PRO para procesar archivos más largos."
        )
    username = user.get("username")
    if not username:
        return
    record = _get_user_row(username)
    if not record:
        return
    _ensure_plan_defaults(record)
    today = _today_str()
    used = record.get("daily_usage_seconds", 0) if record.get("daily_usage_date") == today else 0
    if used + (duration_seconds or 0) > FREE_DAILY_LIMIT_SECONDS:
        remaining_min = max(0, (FREE_DAILY_LIMIT_SECONDS - used) // 60)
        raise HTTPException(
            status_code=403,
            detail=f"Límite diario del plan FREE alcanzado (60 min/día). Te quedan {remaining_min} min hoy. Pasate a PRO para uso sin este límite diario."
        )


def _record_usage(username: str | None, duration_seconds: float | None):
    """
    Suma `duration_seconds` al contador diario del usuario (con reset por
    fecha). Se llama SIEMPRE que un análisis termina con éxito, sin importar
    el plan, para que el admin pueda ver consumo real de cualquier cuenta.
    Usa el RPC atómico avsuite.increment_usage (UPDATE del lado de Postgres)
    en vez de leer-modificar-escribir desde acá, para no perder incrementos
    si dos requests del mismo usuario terminan casi al mismo tiempo (plan PRO
    permite hasta 3 jobs simultáneos - ver PRO_MAX_CONCURRENT_JOBS).
    """
    if not username or username == "legacy" or not duration_seconds:
        return
    _supabase_request(
        "POST", "rpc/increment_usage",
        json_body={"p_username": username, "p_seconds": int(round(duration_seconds)), "p_today": _today_str()},
    )


def _check_batch_allowed(user: dict, clip_count: int):
    """Gate de 'batch' PRO: FREE solo puede exportar de a pocos clips por vez."""
    if user["unrestricted"] or user["plan"] != PLAN_FREE:
        return
    if clip_count > FREE_MAX_BATCH_CLIPS:
        raise HTTPException(
            status_code=403,
            detail=f"El plan FREE permite exportar hasta {FREE_MAX_BATCH_CLIPS} clips por vez. Pasate a PRO para exportar en lote."
        )


# ------------------------------------------------------------------
# Concurrencia POR USUARIO: además del semáforo global (una operación
# pesada a la vez en TODO el servidor, ver _heavy_ops_semaphore más abajo),
# FREE no puede tener más de un job propio en curso - si no, una sola
# cuenta FREE podría acumular cola propia mandando varios requests a la vez.
# ------------------------------------------------------------------
_user_active_jobs: dict[str, int] = {}
_user_jobs_lock = asyncio.Lock()


def _max_jobs_for(user: dict) -> int:
    if user["unrestricted"] or user["plan"] == PLAN_PRO:
        return PRO_MAX_CONCURRENT_JOBS
    return FREE_MAX_CONCURRENT_JOBS


async def _acquire_user_job_slot(user: dict):
    username = user.get("username")
    if not username or username == "legacy" or user.get("unrestricted"):
        return
    async with _user_jobs_lock:
        current = _user_active_jobs.get(username, 0)
        if current >= _max_jobs_for(user):
            raise HTTPException(status_code=429, detail="Ya tenés un trabajo en curso. Esperá a que termine antes de iniciar otro.")
        _user_active_jobs[username] = current + 1


def _release_user_job_slot(user: dict):
    username = user.get("username")
    if not username or username == "legacy" or user.get("unrestricted"):
        return
    current = _user_active_jobs.get(username, 0)
    if current <= 1:
        _user_active_jobs.pop(username, None)
    else:
        _user_active_jobs[username] = current - 1


# ------------------------------------------------------------------
# RATE LIMITING básico (por IP) para los dos endpoints públicos sin auth
# (login y solicitud de acceso) - simple ventana fija en memoria, no hace
# falta Redis para este volumen.
# ------------------------------------------------------------------
_rate_limit_buckets: dict[str, list] = {}


def _rate_limit(key: str, max_requests: int, window_seconds: float):
    now = time.time()
    bucket = _rate_limit_buckets.setdefault(key, [])
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= max_requests:
        raise HTTPException(status_code=429, detail="Demasiados intentos desde esta IP. Esperá un momento y volvé a intentar.")
    bucket.append(now)


def _client_ip(request) -> str:
    return request.client.host if request and request.client else "unknown"


# ------------------------------------------------------------------
# OWNERSHIP de exports: antes cualquiera con la URL podía listar/descargar
# el export de cualquier otro usuario (GET /exports, GET /exports/{filename}
# sin auth ni dueño). Esta tabla (filename -> username, en Supabase) es lo
# que permite gatear ambos endpoints por dueño real - los archivos en sí
# siguen en el filesystem efímero de Render (EXPORT_DIR), solo el ÍNDICE de
# quién es el dueño de cada uno vive en la base.
# ------------------------------------------------------------------

def _load_exports_index() -> dict:
    rows = _supabase_select("exports_index")
    return {r["filename"]: {"username": r["username"], "created_at": r["created_at"]} for r in rows}


def _save_exports_index(idx: dict):
    rows = [{"filename": fn, **fields} for fn, fields in idx.items()]
    _supabase_upsert("exports_index", rows, on_conflict="filename")


def _register_export(filename: str, username: str | None):
    if not username or username == "legacy":
        raise HTTPException(401, "Ingresá con una cuenta para guardar exportaciones.")
    studio_store.save_media(username, EXPORT_DIR / filename, filename, "export",
                           hashlib.sha256(filename.encode()).hexdigest())
    _supabase_upsert(
        "exports_index",
        {"filename": filename, "username": username, "created_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="filename",
    )


def _get_export_owner(filename: str) -> str | None:
    """Fetch de UNA sola fila (evita traer todo el índice) - usado en la descarga."""
    rows = _supabase_select("exports_index", params={"filename": f"eq.{filename}", "select": "username", "limit": "1"})
    return rows[0]["username"] if rows else None


# Groq (opcional): último recurso cuando TODOS los modelos Gemini agotaron su cuota diaria.
# Sin diarización de speakers reales (Whisper no la hace), pero mantiene la app funcionando
# en vez de fallar por completo. Si no está seteada, este fallback simplemente se salta.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")
# "llama-3.3-70b-versatile" (el default viejo) fue dado de baja por Groq -
# confirmado en vivo el 2026-09-28: /chat/completions devolvía 404
# "model_not_found" (no un problema de URL/base_url, la URL siempre fue
# correcta). Verificado contra GET /openai/v1/models que este es un modelo
# real y activo hoy - si Groq lo da de baja en el futuro, revisar esa
# lista antes de asumir cuál poner.
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-120b")

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

studio_store = RecordStore(
    os.getenv("STUDIO_DATA_DIR", str(Path(__file__).parent / ".studio-data")),
    mode=os.getenv("STUDIO_STORAGE", "supabase"), url=SUPABASE_URL,
    key=SUPABASE_SERVICE_KEY, schema=SUPABASE_SCHEMA,
)


def _scoped_cache_key(key: str, user: dict) -> str:
    return hashlib.sha256(f"{account(user)}:{key}".encode()).hexdigest()


async def _validate_media_input(input_data, user):
    """Only accept opaque owned assets; never a path supplied by a browser."""
    if getattr(input_data, "video_path", ""):
        raise HTTPException(400, "Las rutas del servidor no se aceptan. Volvé a subir el archivo.")
    if getattr(input_data, "url", ""):
        _validate_source_url(input_data.url)
    asset_id = getattr(input_data, "asset_id", "")
    if asset_id:
        path, media = await asyncio.to_thread(studio_store.media_path, account(user), asset_id)
        if media["suffix"] in {".png", ".jpg", ".jpeg", ".webp", ".zip"}:
            raise HTTPException(400, "Elegí una fuente de audio o video.")
        input_data.video_path = str(path)


def cache_video_path(cache_key: str, user: dict):
    """Devuelve la ruta al video cacheado para este cache_key, o None si no esta."""
    if not cache_key:
        return None
    if not re.fullmatch(r"[a-f0-9]{32,64}", cache_key):
        raise HTTPException(400, "Identificador de video inválido.")
    if not studio_store.get(account(user), "media", cache_key):
        return None
    path, media = studio_store.media_path(account(user), cache_key)
    if media["suffix"] in {".png", ".jpg", ".jpeg", ".webp", ".zip"}:
        return None
    return str(path)


def cache_video_store(cache_key: str, source_path: str, user: dict):
    """
    Mueve el video original a la carpeta de cache (no lo copia: evita duplicar
    el escrito a disco). A partir de ahi, exportar clips lo reusa directo sin
    volver a descargar ni pedir que se re-suba.
    """
    if not cache_key or not os.path.exists(source_path):
        return
    studio_store.save_media(account(user), source_path, Path(source_path).name, "source", cache_key)

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

# Ruta configurable por env var (antes hardcodeada a /etc/secrets/cookies.txt,
# que es donde Render monta los "Secret Files" por default - pero ese mount
# point puede variar según cómo esté configurado el servicio, así que ahora
# es override-able sin tocar código). Si no se setea, se prueban los mismos
# dos defaults de siempre.
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE")


def _cookies_file_candidates() -> list:
    candidates = []
    if YTDLP_COOKIES_FILE:
        candidates.append(Path(YTDLP_COOKIES_FILE))
    candidates.append(Path("/etc/secrets/cookies.txt"))  # default de Render para Secret Files
    candidates.append(Path(__file__).parent / "cookies.txt")  # uso local, o Secret Files montados en la raíz de la app
    return candidates


def _find_cookies_file():
    """
    Busca cookies.txt en las ubicaciones posibles según dónde se esté corriendo
    (ver _cookies_file_candidates). yt-dlp reescribe el cookiejar después de
    cada uso, así que si el original es de solo lectura (caso Render) lo
    copiamos a un archivo escribible en /tmp y devolvemos ese.
    Devuelve el Path a usar, o None si no hay cookies en ningún lado o si el
    archivo existe pero no se puede LEER (permiso denegado a nivel filesystem
    - se loguea claro y se sigue sin cookies, en vez de que un error acá
    tire abajo toda la descarga con un traceback no relacionado).
    """
    if _WRITABLE_COOKIES_FILE.exists():
        return _WRITABLE_COOKIES_FILE

    for candidate in _cookies_file_candidates():
        if not candidate.exists():
            continue
        if not os.access(candidate, os.R_OK):
            print(f"⚠ cookies.txt encontrado en {candidate} pero el proceso no tiene permiso de lectura (uid actual: {os.getuid()}). Se sigue sin cookies.")
            continue
        try:
            shutil.copy(candidate, _WRITABLE_COOKIES_FILE)
            return _WRITABLE_COOKIES_FILE
        except OSError as e:
            # No debería pasar si el os.access() de arriba dio OK, pero por
            # las dudas no dejamos que un error acá tire abajo la descarga
            # entera con un traceback sin relación con YouTube/Drive.
            print(f"⚠ cookies.txt encontrado en {candidate} pero falló al copiarlo a {_WRITABLE_COOKIES_FILE}: {e}. Se sigue sin cookies.")
            continue
    return None


def _cookies_file_diagnostics() -> dict:
    """
    Diagnóstico de cookies.txt SIN tocar su contenido (nunca se lee ni se
    devuelve una sola línea del archivo) - solo existencia/tamaño/dueño/
    permisos/legibilidad, para poder auditar por qué yt-dlp no las está
    usando sin necesidad de acceso directo al filesystem de Render. Ver
    /debug/ytdlp-info.
    """
    result = {
        "configured_path_env": YTDLP_COOKIES_FILE,
        "running_as_uid": os.getuid(),
        "running_as_gid": os.getgid(),
        "candidates": [],
        "resolved": None,
    }
    for candidate in _cookies_file_candidates():
        entry = {"path": str(candidate), "exists": candidate.exists()}
        if entry["exists"]:
            try:
                st = candidate.stat()
                entry["size_bytes"] = st.st_size
                entry["owner_uid"] = st.st_uid
                entry["owner_gid"] = st.st_gid
                entry["mode_octal"] = oct(st.st_mode & 0o777)
                entry["readable_by_this_process"] = os.access(candidate, os.R_OK)
                # Edad del archivo (NO del contenido/expiración real de cada
                # cookie, que no se lee) - señal indirecta útil: las cookies
                # de sesión de YouTube suelen vencer en semanas: un archivo
                # de varios meses es la sospecha #1 si YouTube empieza a
                # rechazar todo con "Sign in to confirm you're not a bot"
                # incluso con cookies.txt presente y legible.
                entry["age_days"] = round((datetime.now(timezone.utc).timestamp() - st.st_mtime) / 86400, 1)
            except OSError as e:
                entry["stat_error"] = str(e)
        result["candidates"].append(entry)
    resolved = _find_cookies_file()
    if resolved:
        result["resolved"] = str(resolved)
        try:
            st = resolved.stat()
            result["resolved_size_bytes"] = st.st_size
        except OSError:
            pass
    return result


# Aviso sobre métodos de autenticación para Drive/YouTube
_cookies_file_check = _find_cookies_file()
if _cookies_file_check:
    print(f"✓ Cookies encontradas en: {_cookies_file_check} (se usarán para archivos privados)")
else:
    print("ℹ Sin cookies.txt accesible. Para archivos privados de Drive se intentará leer cookies de Chrome.")
    print("  Si Drive/YouTube te da 403, revisá /debug/ytdlp-info para ver qué rutas se probaron y por qué.")


class UrlInput(BaseModel):
    url: str
    engine: str = "auto"  # "auto" (Gemini + Groq de respaldo) | "gemini" | "groq"

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        try:
            return _validate_source_url(value)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc


def _validate_source_url(value):
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        allowed = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "drive.google.com", "docs.google.com"}
        if parsed.scheme != "https" or host not in allowed or parsed.port not in {None, 443} or parsed.username or parsed.password:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(400, "Usá un enlace HTTPS de YouTube o Google Drive, o subí el archivo.") from exc
    return value.strip()


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
    """ID único por exportación para aislar archivos entre pedidos y cuentas."""
    payload = "|".join((*parts, uuid.uuid4().hex))
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


# ------------------------------------------------------------------
# Errores de YouTube que NINGUNA estrategia/reintento va a arreglar (el
# contenido en sí está bloqueado/no existe) - para estos cortamos rápido
# en vez de probar las 4 estrategias en vano. Cualquier otro error (incluido
# "Failed to extract any player response", que es justamente el síntoma de
# que el player_client forzado quedó afectado por el rollout SABR-only de
# YouTube - ver https://github.com/yt-dlp/yt-dlp/issues/12482) SÍ vale la
# pena reintentar con la siguiente estrategia, porque ya se confirmó
# reproduciendo el error que "sin forzar player_client" lo resuelve en la
# mayoría de los casos.
_YOUTUBE_UNFIXABLE_PATTERNS = (
    "video unavailable", "video is unavailable", "private video", "this video is private",
    "video is no longer available", "video has been removed",
    "account associated with this video has been terminated",
    "sign in to confirm your age", "age-restricted", "not available in your country",
    "copyright", "this video is not available", "video does not exist",
)


def _friendly_youtube_error(err_str: str) -> str:
    """
    Traduce el error crudo de yt-dlp (que suele incluir texto en inglés
    pensado para devs, plantillas de GitHub issue, sugerencias de `-U`, etc.
    - ver el mensaje real que veía el usuario antes de este fix) a un
    mensaje corto y accionable. Si no reconoce el patrón, devuelve un
    mensaje genérico igual de limpio (nunca el traceback crudo). Esta misma
    función de descarga (_download_youtube, a pesar del nombre) también
    maneja links de Google Drive.

    IMPORTANTE: el orden de los checks importa. "Sign in to confirm you're
    not a bot" y errores de cookies vencidas casi siempre vienen acompañados
    de "HTTP Error 403: Forbidden" en el mismo mensaje - si el check genérico
    de 403/permisos fuera el primero, se comería esos casos y el usuario
    vería "permiso denegado" para un bloqueo anti-bot de YouTube que no tiene
    nada que ver con permisos de archivo (bug real que tuvo este mensaje
    antes de reordenar). Por eso los patrones más específicos de YouTube van
    primero, y el catch-all de permisos/cookies genérico (pensado para Drive)
    queda último, antes del fallback genérico.
    """
    low = err_str.lower()
    if any(p in low for p in ("private video", "this video is private")):
        return "Ese video es privado. Pedile al dueño que lo haga público o 'No listado', o subilo como archivo local."
    if any(p in low for p in ("video unavailable", "video is unavailable", "video is no longer available", "video has been removed", "video does not exist", "this video is not available")):
        return "Ese video ya no está disponible en YouTube (lo borraron o el link está mal)."
    if "terminated" in low:
        return "La cuenta de YouTube dueña de ese video fue dada de baja - el video ya no existe."
    if "age-restricted" in low or "sign in to confirm your age" in low:
        return "Ese video tiene restricción de edad y requiere inicio de sesión en YouTube - no se puede descargar de forma anónima."
    if "not available in your country" in low or "geo" in low:
        return "Ese video no está disponible en la región del servidor (restricción geográfica de YouTube)."
    if "copyright" in low:
        return "Ese video fue bloqueado por un reclamo de copyright y ya no está disponible."
    # Cookies vencidas/rechazadas por YouTube: yt-dlp lo reporta con frases
    # como "cookies are no longer valid" o "cookies have expired" - DISTINTO
    # de un error de filesystem (no poder leer cookies.txt, que ni siquiera
    # llega hasta acá, ver _find_cookies_file).
    if ("cookies" in low and ("no longer valid" in low or "expired" in low or "invalid" in low)):
        return "Las cookies de YouTube configuradas en el servidor están vencidas o ya no son válidas. Hay que renovar cookies.txt (exportarlas de nuevo desde una sesión logueada en YouTube)."
    if "sign in to confirm you" in low or "not a bot" in low or "login_required" in low:
        return "YouTube le pidió al servidor confirmar que no es un bot (bloqueo anti-bot, no un problema de permisos de archivo). Reintentá en unos minutos, o subí el video como archivo local mientras tanto."
    if "player response" in low or "sabr" in low:
        return "YouTube cambió cómo entrega este video y no se pudo extraer con ningún método. Reintentá en unos minutos (suele ser temporal) o subí el video como archivo local."
    if "live event has ended" in low or "no video formats found" in low:
        return "Ese video fue una transmisión en vivo que recién terminó y YouTube todavía no lo terminó de procesar. Reintentá en unos minutos."
    # Catch-all de permisos/cookies genérico: acá sí puede ser Google Drive
    # (URL que esta función también maneja) con el archivo no compartido.
    if "403" in err_str or "401" in err_str or "forbidden" in low:
        return (
            "No se pudo acceder al archivo (permiso denegado). Si es de Google Drive, "
            "verificá que tenga permiso 'Cualquier persona con el enlace'. Si es de YouTube, "
            "puede ser un bloqueo temporal - reintentá en unos minutos, o subí el archivo como 'Subir Local'."
        )
    return "No se pudo descargar ese video de YouTube. Puede ser un bloqueo temporal de YouTube - reintentá en unos minutos, o subilo como archivo local mientras tanto."


# ------------------------------------------------------------------
# Cooldown anti rate-limit de YouTube: si una URL ya nos devolvió 429/
# "confirmá que no sos un bot", reintentar el ciclo completo de 4
# estrategias de nuevo a los pocos segundos (típico si alguien ve el error
# y reintenta al toque, o dos tabs/clicks superpuestos) solo empeora las
# cosas - cada estrategia vuelve a pegarle a YouTube desde la misma IP, que
# es justo lo que escala el bloqueo. Confirmado en logs reales de
# producción: un mismo request disparó 2 ciclos completos (8 intentos) en
# ~25s, todos fallando con el mismo bloqueo.
_YT_RATE_LIMIT_COOLDOWN_SECONDS = int(os.getenv("YT_RATE_LIMIT_COOLDOWN_SECONDS", "90"))
_recent_youtube_blocks: dict[str, float] = {}


def _is_rate_limit_or_bot_check(err_str: str) -> bool:
    low = err_str.lower()
    return "429" in err_str or "too many requests" in low or "sign in to confirm you" in low or "not a bot" in low


def _download_youtube(url: str, format_selector: str, outtmpl_suffix: str = "", progress_callback=None) -> str:
    cooldown_key = url_hash(url)
    blocked_at = _recent_youtube_blocks.get(cooldown_key)
    if blocked_at is not None:
        elapsed = time.time() - blocked_at
        if elapsed < _YT_RATE_LIMIT_COOLDOWN_SECONDS:
            remaining = int(_YT_RATE_LIMIT_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=(
                    f"YouTube bloqueó temporalmente este video hace muy poco (demasiados intentos seguidos "
                    f"desde este servidor). Esperá {remaining}s antes de reintentar - reintentar ahora solo "
                    f"empeora el bloqueo. Mientras tanto podés subir el video como archivo local."
                ),
            )
        del _recent_youtube_blocks[cooldown_key]

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
    best_error = None  # último error que vino de una extracción REAL contra YouTube/Drive (no un fallo local de herramientas, ver abajo)

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
            low = err_str.lower()
            if any(p in low for p in _YOUTUBE_UNFIXABLE_PATTERNS):
                # El video en sí está bloqueado/no existe - ninguna otra
                # estrategia (otro player_client, cookies, etc.) lo arregla.
                print(f"   ✗ Error no recuperable: {err_str[:200]}")
                raise HTTPException(status_code=400, detail=_friendly_youtube_error(err_str))
            if _is_rate_limit_or_bot_check(err_str):
                # Bloqueo a nivel IP (429) o chequeo anti-bot de YouTube: NO
                # es algo que otro player_client o cookies.txt vaya a
                # esquivar (confirmado en logs reales: las 4 estrategias
                # fallan igual una vez que arranca). Cortamos acá en vez de
                # seguir probando - cada intento extra es otro request a
                # YouTube que solo puede empeorar el bloqueo - y guardamos
                # el cooldown para que un reintento inmediato (manual o
                # automático) no vuelva a pegarle.
                _recent_youtube_blocks[cooldown_key] = time.time()
                print(f"   ✗ Bloqueo anti-bot/rate-limit de YouTube, corto acá (cooldown {_YT_RATE_LIMIT_COOLDOWN_SECONDS}s): {err_str[:200]}")
                raise HTTPException(status_code=429, detail=_friendly_youtube_error(err_str))
            # "could not find chrome cookies database": la última estrategia
            # ("cookies de Chrome") SIEMPRE falla así en Render (no hay Chrome
            # instalado) - es un fallo local y predecible, no un error real de
            # YouTube/Drive. Si lo dejáramos pisar `best_error`, el mensaje
            # final sería ese ruido en vez del motivo real del fallo previo
            # (ej. cookies.txt vencidas, bloqueo anti-bot).
            if "chrome cookies database" not in low:
                best_error = e
            # Cualquier otro error (incluido "Failed to extract any player
            # response" - síntoma del rollout SABR-only de YouTube que
            # degrada los player_client forzados, ver comentario arriba de
            # _YOUTUBE_UNFIXABLE_PATTERNS) vale la pena reintentar con la
            # siguiente estrategia antes de darnos por vencidos.
            print(f"   ⚠ Falló, reintentando con la siguiente estrategia: {err_str[:150]}")
            continue

    # Si llegamos acá, todas las estrategias fallaron. Preferimos el último
    # error que vino de una extracción real (best_error) para el mensaje
    # final - más informativo que el ruido local de "cookies de Chrome".
    final_error = best_error if best_error is not None else last_error
    print(f"   ✗ Las {len(strategies)} estrategias de descarga fallaron. Último error relevante: {final_error}")
    raise HTTPException(status_code=502, detail=_friendly_youtube_error(str(final_error)))


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
        # gemini-2.0-flash, gemini-2.0-flash-lite, gemini-2.5-flash-lite y
        # gemini-2.5-flash fueron dados de baja por Google (404 NOT_FOUND
        # permanente, "no longer available") - sacados de la lista default
        # para no desperdiciar reintentos contra modelos que nunca van a
        # responder. gemini-2.5-flash en particular estaba anunciado para
        # el 16/10/2026 pero confirmado 404 en vivo ya el 28/09/2026 -
        # dado de baja antes de lo anunciado.
        # gemini-3.7-flash (el más nuevo) NO va primero a propósito: probado
        # a mano el 2026-08-25 contra audio real, devuelve 0 candidatos +
        # 503 "high demand" de forma consistente - muy probablemente por ser
        # recién salido y todavía en rollout inestable del lado de Google.
        # Como no es un 404 "modelo muerto" ni una cuota agotada, el código
        # no lo descarta solo: si queda primero, gasta los 3 intentos + el
        # fallback contra un modelo roto antes de rendirse. Se lo deja
        # último, probar de nuevo a ponerlo más arriba en unas semanas.
        "gemini-3.6-flash,gemini-3.5-flash,"
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
    info["duration_seconds"] = get_video_duration_seconds(file_path)
    info["duration_minutes"] = round(info["duration_seconds"] / 60, 2)

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
                    info["width"] = stream.get("width")
                    info["height"] = stream.get("height")
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


def _collapse_repeated_runs(text: str, max_repeats: int = 3, max_phrase_words: int = 20) -> str:
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

    Usa \\S+ (cualquier caracter no-espacio) en vez de \\w+ para armar cada
    "palabra" del patrón - con \\w+ una frase con signos de interrogación
    españoles en el medio ("Ella eh ese libro habla mucho de esto, ¿no?")
    nunca hacía match, porque ¿/? no son caracteres \\w, sin importar cuán
    alto estuviera max_phrase_words. Encontrado en vivo: un video real
    donde esa frase de 9 palabras se repitió cientos de veces sin que este
    filtro la tocara.
    """
    import re

    pattern = re.compile(
        r'((?:\S+\s+){0,%d}\S+)((?:\s+\1){3,})' % (max_phrase_words - 1),
        re.IGNORECASE
    )

    def _replace(match):
        phrase = match.group(1)
        return (phrase + ' ') * (max_repeats - 1) + phrase

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
    "You are receiving an AUDIO FILE (MP3). It may be a radio program, a podcast, an interview, or any other "
    "spoken content. Your task is to transcribe ALL human speech from the first second to the very last second "
    "— do NOT stop early, and do NOT skip ahead.\n\n"
    "CRITICAL — NEVER SKIP THE BEGINNING: Start transcribing from 00:00. Never jump ahead several minutes into "
    "the file assuming the start is silence or music — check the actual audio. Quiet, unclear, cross-talking, or "
    "hard-to-hear speech is still speech: transcribe your best guess of it instead of skipping it. Only skip a "
    "segment if you are completely certain it contains ZERO human speech (pure instrumental music, a jingle, or "
    "true silence) — if in doubt, transcribe it instead of skipping.\n\n"
    "IMPORTANT — MUSICAL BREAKS: Some programs contain musical breaks of several minutes at various points "
    "(not just at the start). Whenever you encounter music, jingles, instrumental segments, or any non-speech audio "
    "— whether at the beginning, middle, or end of the file — skip ONLY that exact segment, and resume transcribing "
    "at the very next moment where a human voice speaks (do not overshoot past the point speech actually resumes). "
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
    "Use ONLY 'Speaker 1', 'Speaker 2', 'Speaker 3', etc. — NEVER guess, infer, or attach a real name in "
    "parentheses (e.g. never write 'Speaker 1 (Juan)'), even if a name is mentioned somewhere in the audio. "
    "Real names get added later by a human reviewing the transcript, not by you. "
    "Maintain the same numbered label consistently for the same voice throughout the entire transcription.\n\n"
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


# Modelo dedicado de ASR (AudioTranscriptionConfig) - DESACTIVADO del
# pipeline principal (ver _process_single_video_file), aunque la función de
# abajo se deja definida por si alguien quiere retomarlo más adelante.
# Motivo: pide diarization=True, pero _transcribe_with_gemini_dedicated()
# descarta esa estructura al envolver el resultado (ver docstring de la
# función) - un video de 50 min con varios hablantes quedaba mostrado como
# un solo "Speaker 1" sin separación real, y con un único TIMESTAMP: 00:00
# para todo el audio. Sumado a que ya estaba marcado como poco confiable
# (probado a mano el 2026-08-26: mayoría 503 "high demand", texto cortado
# cuando sí respondía), no vale la pena seguir intentándolo primero.
# Para retomarlo en serio habría que parsear la diarización/timestamps
# reales que devuelve el modelo (no investigado todavía) en vez de tirarlos.
GEMINI_TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")


def _transcribe_with_gemini_dedicated(uploaded_file) -> str:
    """
    NO SE LLAMA desde el pipeline principal - ver comentario arriba de
    GEMINI_TRANSCRIBE_MODEL. Queda definida por si se retoma más adelante,
    parseando de verdad la diarización/timestamps que devuelve el modelo en
    vez de aplastarlos en una sola entrada como hace ahora.

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


def _call_gemini_with_retry(uploaded_file, max_cycles: int = 4):
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
        if cycle > 1:
            # Pausa entre vueltas completas (ver mismo razonamiento en
            # _call_gemini_text): si TODOS los modelos dieron 503 en la
            # vuelta anterior, un respiro le da tiempo a la sobrecarga de
            # Google de bajar antes de volver a probarlos.
            print(f"   ⚠ Ninguno de los {len(GEMINI_MODELS)} modelos respondió en el ciclo {cycle - 1}. Pausa de 10s antes de la vuelta {cycle}/{max_cycles}...")
            time.sleep(10)
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


def _call_gemini_text(prompt: str, max_cycles: int = 4) -> str:
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
        if cycle > 1:
            # Pausa entre vueltas completas (no entre modelos individuales):
            # si TODOS los modelos dieron 503 "alta demanda" en la vuelta
            # anterior, probarlos nuevamente de inmediato pega contra la
            # misma sobrecarga - un respiro le da tiempo a Google de bajarla
            # antes de la próxima vuelta.
            print(f"   ⚠ Ninguno de los {len(GEMINI_MODELS)} modelos respondió en el ciclo {cycle - 1}. Pausa de 10s antes de la vuelta {cycle}/{max_cycles}...")
            time.sleep(10)
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


def _raise_for_groq_status(response):
    """
    response.raise_for_status() solo (requests) tira un mensaje genérico
    tipo "404 Client Error: Not Found for url: ..." sin el cuerpo real del
    error - así fue como el modelo de Groq dado de baja (404
    "model_not_found") se vio en el log idéntico a un problema de URL/
    endpoint, hasta que se confirmó a mano contra la API cuál era la causa
    real. Esto incluye el cuerpo de la respuesta en el mensaje para que la
    próxima vez se vea de una.
    """
    if response.status_code >= 400:
        raise Exception(f"Groq HTTP {response.status_code}: {response.text[:500]}")


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
    _raise_for_groq_status(response)
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
    (compatible con OpenAI), modelo GROQ_TEXT_MODEL, en vez de un modelo Gemini.
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
    _raise_for_groq_status(response)
    data = response.json()
    choices = data.get("choices") or []
    text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
    if not text:
        raise Exception(f"Groq ({GROQ_TEXT_MODEL}) no devolvió texto.")
    return text


def _normalize_engine(value: str) -> str:
    """Clampea el motor pedido a uno de los 3 válidos, "auto" si viene vacío o inválido."""
    value = (value or "auto").strip().lower()
    return value if value in ("auto", "gemini", "groq") else "auto"


_SILENCE_MAX_VOLUME_THRESHOLD_DB = -50.0


def _is_pure_silence(audio_path: str, threshold_db: float = _SILENCE_MAX_VOLUME_THRESHOLD_DB) -> bool:
    """
    Corre `ffmpeg -af volumedetect` (filtro nativo, ya es dependencia del
    proyecto) sobre TODO el audio y devuelve True si el pico máximo de
    volumen de todo el tramo está por debajo de `threshold_db` - es decir,
    silencio digital puro o casi puro (sin señal de voz real, ni siquiera
    baja). Habla real, aunque sea susurrada, deja picos muy por encima de
    -50dB, así que este umbral no descarta diálogo genuino.

    Pre-filtro recomendado por el QA Agent y el Market Research Agent
    (ver HANDOFF.md, market-research-report.md tema 2): confirmado en vivo
    que Gemini alucina una frase repetida cientos de veces cuando el audio
    de entrada no tiene ninguna señal real - en vez de mandarle ese tramo a
    un modelo generativo, se detecta acá (una sola pasada de ffmpeg, sin
    costo de API) y se devuelve "sin diálogo" directo.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_path, "-af", "volumedetect", "-vn", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
        if not match:
            return False  # no se pudo determinar - seguir el camino normal (Gemini/Groq)
        return float(match.group(1)) <= threshold_db
    except Exception:
        return False  # ante cualquier error del pre-filtro, no bloquear el flujo normal


_NO_DIALOGUE_TRANSCRIPT = (
    "TIMESTAMP: 00:00\n"
    "SPEAKER: (silencio)\n"
    "DIALOGUE: [Sin diálogo detectado - tramo sin señal de audio real]"
)


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

    # _is_pure_silence() YA NO SE LLAMA ACÁ: confirmado en vivo (dos veces,
    # con videos reales con diálogo real desde el minuto 0) que descartaba
    # tramos enteros de 10 minutos con conversación real como "silencio" -
    # la transcripción terminaba arrancando recién en el minuto 10, y
    # después en el minuto 40, sin que hubiera silencio real ahí. El costo
    # de este falso positivo (perder contenido real) es mucho peor que el
    # problema que venía a evitar (alucinación de frases repetidas en
    # tramos sin señal), que igual ya se mitiga después con
    # _collapse_repeated_runs(). Queda la función definida por si se
    # retoma con una heurística más estricta más adelante.

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
                # _transcribe_with_gemini_dedicated (gemini-3.5-transcribe) YA
                # NO se intenta acá: confirmado que aunque pide diarization=True,
                # el wrapper de esa función descarta toda esa estructura y
                # devuelve el audio ENTERO como un solo bloque "SPEAKER: Speaker 1"
                # en "TIMESTAMP: 00:00" (ver la función) - un video de 50 minutos
                # con varios hablantes quedaba mostrado como un único hablante sin
                # separación real. GEMINI_MODELS con PROMPT_ESCANEO (abajo) sí
                # devuelve múltiples SPEAKER/TIMESTAMP reales, que es lo que el
                # resto de la app (Speech Map, generación de clips) necesita.
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


async def process_video_with_gemini(video_path: str, user: dict, cache_key: str = None, engine: str = "auto"):
    """Versión no-streaming (compatible con el endpoint clásico)."""
    # Chequeo de cache
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            print(f"✓ Cache hit para {cache_key[:12]}...")
            cached["from_cache"] = True
            return cached

    await _acquire_user_job_slot(user)
    # Mismo semáforo/guard de memoria que las versiones streaming (ver
    # comentario junto a _heavy_ops_semaphore) - este endpoint clásico hace
    # el mismo trabajo pesado y se había quedado afuera de esa protección.
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)

        # Enforcement de plan/cuota ANTES de gastar cuota de Gemini/Groq (ver
        # _check_free_quota) - se conoce la duración real acá mismo.
        duration_seconds = await asyncio.to_thread(get_video_duration_seconds, video_path)
        _check_free_quota(user, duration_seconds)

        print("Iniciando procesamiento inteligente (con detección automática de duración)...")
        text = await asyncio.to_thread(process_video_smart, video_path, None, engine)

        result = {"title": "Metraje Completo Analizado", "raw_timeline": text, "from_cache": False, "cache_key": cache_key}

        if cache_key:
            cache_set(cache_key, result)

        _record_usage(user.get("username"), duration_seconds)
        return result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en Gemini: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en la IA: {str(e)}")
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


async def process_video_streaming(video_path: str, user: dict, cache_key: str = None, engine: str = "auto"):
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

    try:
        await _acquire_user_job_slot(user)
    except HTTPException as e:
        yield event("error", e.detail)
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

        # Enforcement de plan/cuota ANTES de gastar cuota de Gemini/Groq.
        try:
            _check_free_quota(user, duration_seconds)
        except HTTPException as e:
            yield event("error", e.detail)
            return

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

        _record_usage(user.get("username"), duration_seconds)
        yield event("done", "Análisis completo", {"result": result})

    except Exception as e:
        yield event("error", f"Error en el procesamiento: {str(e)}")
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


# ============================================================
# ENDPOINTS CLÁSICOS (mantenidos por compatibilidad)
# ============================================================

@app.post("/analyze-url")
async def analyze_url(input_data: UrlInput, user: dict = Depends(get_current_user)):
    cache_key = _scoped_cache_key(url_hash(input_data.url), user)
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
        return await process_video_with_gemini(video_path, user, cache_key=cache_key, engine=_normalize_engine(input_data.engine))
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)


@app.post("/analyze-video")
async def analyze_video(file: UploadFile = File(...), engine: str = Form("auto"), user: dict = Depends(get_current_user)):
    media = await upload_media(studio_store, user, file, inspect=inspect_media_file)
    video_path, _ = await asyncio.to_thread(studio_store.media_path, account(user), media["id"])
    result = await process_video_with_gemini(str(video_path), user, cache_key=media["id"], engine=_normalize_engine(engine))
    result["asset_id"] = media["id"]
    return result


# ============================================================
# ENDPOINTS CON STREAMING DE PROGRESO (nuevos)
# ============================================================

@app.post("/analyze-url-stream")
async def analyze_url_stream(input_data: UrlInput, user: dict = Depends(get_current_user)):
    """Versión streaming: el frontend recibe eventos de progreso en tiempo real."""
    cache_key = _scoped_cache_key(url_hash(input_data.url), user)
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
            async for chunk in process_video_streaming(video_path, user, cache_key=cache_key, engine=engine):
                yield chunk
        finally:
            # No se cachea como "video exportable": es solo audio. Para
            # exportar clips se descarga el video real por separado.
            if os.path.exists(video_path):
                os.remove(video_path)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/analyze-video-stream")
async def analyze_video_stream(file: UploadFile = File(...), engine: str = Form("auto"), user: dict = Depends(get_current_user)):
    """Versión streaming para archivos locales."""
    media = await upload_media(studio_store, user, file, inspect=inspect_media_file)
    video_path, _ = await asyncio.to_thread(studio_store.media_path, account(user), media["id"])
    cache_key = media["id"]
    engine = _normalize_engine(engine)

    async def generator():
        async for chunk in process_video_streaming(str(video_path), user, cache_key=cache_key, engine=engine):
            yield chunk

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================
# ENDPOINT DE INSPECCIÓN (usado como "subir y obtener ruta temporal"
# para resolver la fuente de una exportación de clips/reel)
# ============================================================

@app.post("/inspect-file")
async def inspect_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """
    Recibe un archivo, lo analiza con ffprobe y devuelve qué tiene adentro.
    Después de inspeccionar, deja el archivo en una ruta temporal y devuelve
    esa ruta junto con la info. El análisis (siempre audio-only, ver
    _process_single_video_file) ya no pasa por acá; este endpoint solo lo
    usa el frontend para subir el archivo fuente al exportar clips/reel.
    """
    media = await upload_media(studio_store, user, file, inspect=inspect_media_file)
    return {**media["metadata"], "asset_id": media["id"], "name": media["name"]}


# ============================================================
# UTILIDADES
# ============================================================

@app.get("/cache-stats",dependencies=[Depends(require_superadmin)])
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
def cache_clear(user: dict = Depends(get_current_user)):
    """Vacía solo análisis asociados a los medios y proyectos de esta cuenta."""
    deleted = 0
    owner=account(user)
    rows=studio_store.list(owner,"media",1000)
    workspace=studio_store.get(owner,"workspace","main")
    sessions=workspace["payload"].get("sessions",[]) if workspace else []
    keys={row["id"] for row in rows}
    keys.update(session.get("data",{}).get("cache_key","") for session in sessions)
    for key in keys:
        if not re.fullmatch(r"[a-f0-9]{32,64}",key):
            continue
        f=CACHE_DIR/f"{key}.json"
        if not f.exists():
            continue
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
    # "gemini" (default, usado por captions/chat) o "groq" (usado por
    # Generate Clips - ver comentario en el endpoint más abajo).
    engine_preference: str = "gemini"


class AssistantChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class AssistantChatInput(BaseModel):
    transcript: str
    messages: list[AssistantChatMessage]


@app.post("/assistant-chat")
async def assistant_chat(input_data: AssistantChatInput, user: dict = Depends(get_current_user)):
    """
    Chat de ida y vuelta del modo "Assistant" (ver ai-assistant-card en
    index.html) - a diferencia de /generate-clip-suggestions (un prompt,
    una respuesta final), acá se manda el historial completo de la
    conversación en cada llamada (sin estado en el server, mismo patrón
    simple que el resto de la app) para que la persona pueda ir y venir con
    la IA sobre el material ya transcripto antes de pedirle los clips.
    """
    if not input_data.messages:
        raise HTTPException(status_code=400, detail="Falta al menos un mensaje.")
    if not input_data.transcript or len(input_data.transcript.strip()) < 10:
        raise HTTPException(status_code=400, detail="Todavía no hay transcripción para conversar sobre eso - analizá un video primero.")

    system_context = (
        "Sos un asistente conversacional que ayuda a un editor de video/redes sociales a decidir qué "
        "hacer con un material ya transcripto (armar clips, resúmenes, ideas de contenido, lo que pida). "
        "Tenés la transcripción completa abajo. Respondé en español, de forma breve y directa - esto es "
        "un chat, no un ensayo.\n"
        "Si en algún momento tu respuesta señala fragmentos puntuales del video (por pedido explícito o "
        "porque tiene sentido para lo que se está charlando), marcá cada uno así:\n"
        "⏱ Inicio: MM:SS\n⏱ Fin: MM:SS\n💬 Fragmento: \"cita textual de la transcripción\"\n"
        "Usá SIEMPRE timestamps y citas reales tomados de la transcripción de abajo, nunca los inventes. "
        "Si la charla no necesita marcar momentos puntuales, no uses ese formato.\n\n"
        f"[TRANSCRIPCIÓN COMPLETA]:\n{input_data.transcript}"
    )

    gemini_contents = [
        {"role": "user", "parts": [{"text": system_context}]},
        {"role": "model", "parts": [{"text": "Dale, ya tengo la transcripción a mano. ¿Qué necesitás?"}]},
    ]
    for m in input_data.messages:
        gemini_contents.append({"role": "user" if m.role == "user" else "model", "parts": [{"text": m.content}]})

    await _acquire_user_job_slot(user)
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)
        try:
            reply = await asyncio.to_thread(_call_gemini_text, gemini_contents)
            return {"reply": reply, "engine": "gemini"}
        except Exception as gemini_error:
            if GROQ_API_KEY:
                print(f"   ⚠ Gemini agotó todos sus modelos ({gemini_error}). Probando con Groq ({GROQ_TEXT_MODEL})...")
                try:
                    # Groq no soporta el formato de historial de Gemini - se aplana
                    # a un único prompt de texto con la conversación completa.
                    flat_history = "\n".join(f"{'Usuario' if m.role == 'user' else 'Asistente'}: {m.content}" for m in input_data.messages)
                    flat_prompt = f"{system_context}\n\n[CONVERSACIÓN HASTA ACÁ]:\n{flat_history}\n\nAsistente:"
                    reply = await asyncio.to_thread(_call_groq_text, flat_prompt)
                    return {"reply": reply, "engine": "groq"}
                except Exception as groq_error:
                    print(f"   ⚠ Groq también falló: {groq_error}")
                    raise Exception(f"Gemini falló ({gemini_error}) y Groq también falló ({groq_error}).")
            raise Exception(f"Gemini falló y GROQ_API_KEY no está configurada en el servidor, así que no hay red de contención: {gemini_error}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"El asistente no pudo responder: {e}")
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


@app.post("/generate-clip-suggestions")
async def generate_with_ai(input_data: GenerateWithAiInput, user: dict = Depends(get_current_user)):
    """
    Prompt libre "en la app": manda el prompt (transcripción + instrucciones,
    ya armado del lado del frontend) directo a Gemini y devuelve el texto.
    Reemplaza el paso manual de copiar el prompt a ChatGPT/Claude/Gemini web
    y pegar la respuesta de vuelta - el resultado se importa directo al
    exportador de clips sin salir de la app.

    Por default prueba Gemini primero y cae a Groq (GROQ_TEXT_MODEL) si
    agota TODA su lista de modelos (ver _call_gemini_text). Generate Clips
    manda engine_preference="groq" para invertir el orden (pedido explícito:
    Gemini viene ignorando la cantidad de clips pedida y generando cientos
    de clips de segundos en vez de la cantidad pedida - mientras se afina
    el prompt, arrancar por Groq da resultados más predecibles para ese
    caso puntual). La respuesta indica en "engine" cuál de los dos resolvió
    el pedido, para que el frontend lo pueda mostrar.
    """
    if not input_data.prompt or len(input_data.prompt.strip()) < 10:
        raise HTTPException(status_code=400, detail="El prompt está vacío.")

    if input_data.engine_preference == "groq" and GROQ_API_KEY:
        first_name, first_fn = "groq", (lambda: _call_groq_text(input_data.prompt))
        second_name, second_fn = "gemini", (lambda: _call_gemini_text(input_data.prompt))
    else:
        first_name, first_fn = "gemini", (lambda: _call_gemini_text(input_data.prompt))
        second_name, second_fn = "groq", (lambda: _call_groq_text(input_data.prompt))
    second_available = GROQ_API_KEY if second_name == "groq" else True

    await _acquire_user_job_slot(user)
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)
        try:
            text = await asyncio.to_thread(first_fn)
            return {"text": text, "engine": first_name}
        except Exception as first_error:
            if second_available:
                print(f"   ⚠ {first_name} falló ({first_error}). Probando con {second_name}...")
                try:
                    text = await asyncio.to_thread(second_fn)
                    return {"text": text, "engine": second_name}
                except Exception as second_error:
                    print(f"   ⚠ {second_name} también falló: {second_error}")
                    raise Exception(f"{first_name} falló ({first_error}) y {second_name} también falló ({second_error}).")
            raise Exception(f"{first_name} falló y no hay red de contención configurada (GROQ_API_KEY ausente): {first_error}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo generar una respuesta: {e}")
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


# ============================================================
# VOICEOVER / DOBLAJE (Gemini TTS)
# ============================================================

# Modelos con TTS dedicado de Gemini - mismo SDK y cuenta que ya usa el
# proyecto para transcripción/generación de texto, sin dependencia nueva.
# El flash-preview es el default (probado en vivo, rápido); el pro-preview
# queda como respaldo (mejor calidad, cuota más chica) si el primero falla.
# Son modelos "preview": mismo cuidado que gemini-3.5-transcribe en HANDOFF.md
# (probar con casos reales antes de prometerlos como 100% estables).
GEMINI_TTS_MODELS = [
    m.strip() for m in os.getenv(
        "GEMINI_TTS_MODELS",
        "gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts",
    ).split(",") if m.strip()
]

# Voces prebuilt de Gemini confirmadas en vivo contra la API real (de las ~30
# que documenta Google, esta es la muestra que efectivamente devolvió audio
# en la prueba, no una lista copiada de la documentación sin probar).
TTS_VOICES = {
    "Kore": "Firme, informativa",
    "Zephyr": "Brillante, enérgica",
    "Aoede": "Fresca, natural",
    "Fenrir": "Excitable, grave",
}
_DEFAULT_TTS_VOICE = "Kore"


class TtsInput(BaseModel):
    text: str
    voice: str = _DEFAULT_TTS_VOICE


@app.get("/tts-voices")
def get_tts_voices():
    """Voces disponibles para /generate-voiceover, para que el frontend arme el selector sin hardcodearlas."""
    return {"voices": TTS_VOICES, "default": _DEFAULT_TTS_VOICE}


def _pcm_to_wav_bytes(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Gemini TTS devuelve PCM crudo (sin header) - lo envolvemos en un WAV real para que sea reproducible/descargable."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


_TTS_SAMPLE_RATE_RE = re.compile(r"rate=(\d+)")


@app.post("/generate-voiceover")
async def generate_voiceover(input_data: TtsInput, user: dict = Depends(require_pro)):
    """
    Convierte un texto (guion, copy para redes, lo que sea) en un archivo de
    audio .wav con Gemini TTS - para doblaje/voiceover de los clips exportados.
    No se mezcla automáticamente con ningún video: devuelve el .wav suelto,
    la persona lo importa a mano en Premiere/CapCut/donde edite.
    Exclusivo PRO (ver require_pro).
    """
    text = (input_data.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="El texto no puede estar vacío.")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="Texto demasiado largo (máx. 5000 caracteres).")
    voice = input_data.voice if input_data.voice in TTS_VOICES else _DEFAULT_TTS_VOICE

    await _acquire_user_job_slot(user)
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)

        last_error = None
        for model in GEMINI_TTS_MODELS:
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=text,
                    config=genai_types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=genai_types.SpeechConfig(
                            voice_config=genai_types.VoiceConfig(
                                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name=voice)
                            )
                        ),
                    ),
                )
                content = response.candidates[0].content if response.candidates else None
                part = content.parts[0] if content and content.parts else None
                if not part or not part.inline_data or not part.inline_data.data:
                    raise Exception(f"{model} no devolvió audio (respuesta vacía, posible filtro de seguridad o falla transitoria).")

                rate_match = _TTS_SAMPLE_RATE_RE.search(part.inline_data.mime_type or "")
                sample_rate = int(rate_match.group(1)) if rate_match else 24000
                wav_bytes = _pcm_to_wav_bytes(part.inline_data.data, sample_rate=sample_rate)

                export_id = deterministic_export_id(text, voice, model)
                filename = f"voiceover_{export_id}.wav"
                with open(EXPORT_DIR / filename, "wb") as f:
                    f.write(wav_bytes)
                await asyncio.to_thread(_register_export, filename, user.get("username"))

                return {"download_url": f"/exports/{filename}", "filename": filename, "model": model, "voice": voice}
            except Exception as e:
                last_error = e
                print(f"   ⚠ TTS con {model} falló ({e}). Probando siguiente modelo...")
                continue

        raise HTTPException(status_code=502, detail=f"No se pudo generar el audio con ningún modelo de TTS. Último error: {last_error}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error generando el voiceover: {e}")
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


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


_TS_STRICT_RE = re.compile(r"^\d{1,3}(:\d{1,2}){1,2}$")


def _parse_ts_strict(ts: str) -> float | None:
    """
    Como ts_to_seconds_f, pero devuelve None (en vez de 0.0) si el string no
    tiene la forma MM:SS/HH:MM:SS esperada - así un timestamp no parseable
    ("hola", vacío, etc.) se puede distinguir de un "00:00" real en vez de
    confundirse silenciosamente con el inicio del video.
    """
    ts = (ts or "").strip()
    if not _TS_STRICT_RE.match(ts):
        return None
    try:
        parts = [float(p) for p in ts.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def validate_clips_timespan(clips: list) -> str | None:
    """
    Valida el rango de cada clip ANTES de cortar/armar nada - devuelve un
    mensaje de error legible (o None si todo está bien).

    Sin esto, un timestamp mal escrito o invertido pasaba silencioso:
    ts_to_seconds_f() devuelve 0.0 para texto no parseable, y el fallback
    de +30s que tenía cut_single_clip terminaba entregando el video
    completo (o un tramo que no era el pedido) reportando "éxito" igual -
    mismo problema en el XML de Premiere, con <in>/<out> invertidos.
    """
    errors = []
    for i, c in enumerate(clips, 1):
        start_s = _parse_ts_strict(c.start)
        end_s = _parse_ts_strict(c.end)
        if start_s is None:
            errors.append(f"Clip {i}: no pude interpretar el inicio \"{c.start}\" (formato esperado MM:SS o HH:MM:SS).")
        elif end_s is None:
            errors.append(f"Clip {i}: no pude interpretar el fin \"{c.end}\" (formato esperado MM:SS o HH:MM:SS).")
        elif end_s <= start_s:
            errors.append(f"Clip {i}: el fin ({c.end}) tiene que ser posterior al inicio ({c.start}).")
    return " | ".join(errors) if errors else None


def cut_single_clip(video_path: str, start_ts: str, end_ts: str, output_path: str):
    import subprocess
    start_s = ts_to_seconds_f(start_ts)
    end_s = ts_to_seconds_f(end_ts)
    if end_s <= start_s:
        # Ya debería haber sido rechazado antes por validate_clips_timespan()
        # - esto es defensa en profundidad, no el camino esperado.
        raise ValueError(f"Rango de tiempo inválido: el fin ({end_ts}) no es posterior al inicio ({start_ts}).")
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


class ThumbnailSpec(BaseModel):
    start: str


class ThumbnailRequest(BaseModel):
    asset_id: str = ""
    url: str = ""
    video_path: str = ""
    cache_key: str = ""
    clips: list[ThumbnailSpec]


@app.post("/generate-thumbnails")
async def generate_thumbnails(input_data: ThumbnailRequest, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
    """
    Extrae un frame por clip (en su timestamp de inicio) del video YA
    CACHEADO del análisis y lo devuelve como JPG chico en base64, para las
    miniaturas reales del grid de clips. A propósito NO descarga el video si
    todavía no está en cache (analizarlo primero ya lo cachea) - generar
    thumbnails no debería pagar el costo de bajar el video entero de nuevo.
    Alineado por índice con `clips` (no por timestamp, que podría repetirse).
    """
    import base64

    effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
    video_path = await asyncio.to_thread(cache_video_path, effective_cache_key, user) if effective_cache_key else None
    if not video_path and input_data.video_path and os.path.exists(input_data.video_path):
        video_path = input_data.video_path
    if not video_path:
        raise HTTPException(status_code=404, detail="El video todavía no está en cache - analizalo (o exportá un clip) primero para poder generar miniaturas.")
    if not input_data.clips:
        return {"thumbnails": []}

    await _acquire_user_job_slot(user)
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)

        thumbnails: list[str | None] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, clip in enumerate(input_data.clips):
                frame_path = os.path.join(tmpdir, f"thumb_{i}.jpg")
                try:
                    await asyncio.to_thread(extract_frame, video_path, clip.start, frame_path)
                    await asyncio.to_thread(_downscale_thumbnail, frame_path)
                    with open(frame_path, "rb") as f:
                        thumbnails.append("data:image/jpeg;base64," + base64.b64encode(f.read()).decode())
                except Exception as e:
                    print(f"   ⚠ No se pudo extraer thumbnail del clip {i} ({clip.start}): {e}")
                    thumbnails.append(None)
        return {"thumbnails": thumbnails}
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


class EnsureCachedVideoRequest(BaseModel):
    url: str = ""
    cache_key: str = ""


@app.post("/ensure-cached-video")
async def ensure_cached_video(input_data: EnsureCachedVideoRequest, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
    """
    A diferencia de /generate-thumbnails (que a propósito NO descarga si no
    hay cache), este SÍ fuerza la descarga del video completo de una URL para
    dejarlo cacheado - necesario para que el mini-player y las miniaturas
    funcionen con fuentes de YouTube/Drive igual que ya funcionan con un
    archivo local (que queda cacheado solo al analizarlo). Pensado para
    llamarse una sola vez por sesión, cuando ya hay clips para mostrar -
    no en cada render del grid.
    """
    if not input_data.url and not input_data.cache_key:
        raise HTTPException(status_code=400, detail="Falta url o cache_key.")
    effective_cache_key = input_data.cache_key or _scoped_cache_key(url_hash(input_data.url), user)
    if await asyncio.to_thread(cache_video_path, effective_cache_key, user):
        return {"cache_key": effective_cache_key, "cached": True}
    if not input_data.url:
        raise HTTPException(status_code=404, detail="No hay video cacheado y no se dio una URL para descargarlo.")

    await _acquire_user_job_slot(user)
    await _heavy_ops_semaphore.acquire()
    try:
        mem_error = _memory_headroom_error()
        if mem_error:
            raise HTTPException(status_code=503, detail=mem_error)
        video_path = await asyncio.to_thread(download_youtube_video, input_data.url)
        try:
            await asyncio.to_thread(cache_video_store, effective_cache_key, video_path, user)
        finally:
            if os.path.exists(video_path):
                os.remove(video_path)
        return {"cache_key": effective_cache_key, "cached": True}
    finally:
        _heavy_ops_semaphore.release()
        _release_user_job_slot(user)


@app.get("/cached-video/{cache_key}")
def get_cached_video(cache_key: str, user: dict = Depends(get_current_user)):
    """
    Sirve el video cacheado para el mini-player. Requiere el header de auth
    (como cualquier endpoint protegido), así que el frontend lo pide con
    fetch() + authHeaders() y arma un blob: URL - un <video src="..."> plano
    no serviría porque el navegador no manda headers custom en esa request.
    """
    video_path = cache_video_path(cache_key, user)
    if not video_path:
        raise HTTPException(status_code=404, detail="Video no cacheado.")
    return FileResponse(video_path)


def _downscale_thumbnail(image_path: str, max_width: int = 200):
    """Achica el JPG in-place para que viajar en base64 no sea pesado (miniatura, no necesita resolución real)."""
    from PIL import Image
    img = Image.open(image_path)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    img.convert("RGB").save(image_path, "JPEG", quality=72)


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
    start: float = Field(ge=0,allow_inf_nan=False)
    end: float = Field(gt=0,allow_inf_nan=False)
    text: str = Field(max_length=1000)


class SubtitleStyle(BaseModel):
    font: str = "anton"
    color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = Field(default=3,ge=0,le=12)


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
    """Quema subtítulos; un fallo debe avisarse, nunca entregar un video incompleto."""
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
        print(f"⚠ Burn-in de subtítulos falló: {e}")
        raise RuntimeError("No se pudieron incrustar los subtítulos. Reintentá o desactivá los subtítulos.") from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


class ClipSpec(BaseModel):
    start: str
    end: str
    label: str = ""
    subtitles: list[SubtitleCue] = []
    # Transición hacia el PRÓXIMO clip de la secuencia, solo usada por
    # /export-premiere-xml (el resto de los endpoints que comparten este
    # modelo la ignoran). "none"/vacío = corte seco. Ver premiere_export.py.
    transition_out: str = "none"


class ExportClipsInput(BaseModel):
    asset_id: str = ""
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ClipSpec]
    subtitle_style: SubtitleStyle | None = None


@app.post("/export-clips")
async def export_clips_endpoint(input_data: ExportClipsInput, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        # Si no vino cache_key (ej: exportar directo pegando una URL, sin
        # pasar antes por análisis), usamos el hash de la URL para que un
        # segundo export del mismo video pueda reusar lo recién descargado.
        effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
        cached_video = await asyncio.to_thread(cache_video_path, effective_cache_key, user)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido para exportar clips.")
            return
        if not input_data.clips:
            yield event("error", "No hay clips definidos para exportar.")
            return
        timespan_error = validate_clips_timespan(input_data.clips)
        if timespan_error:
            yield event("error", f"Timestamps inválidos: {timespan_error}")
            return
        try:
            _check_batch_allowed(user, len(input_data.clips))
        except HTTPException as e:
            yield event("error", e.detail)
            return

        try:
            await _acquire_user_job_slot(user)
        except HTTPException as e:
            yield event("error", e.detail)
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
                delete_video_after = False
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
                await asyncio.to_thread(_register_export, single_name, user.get("username"))
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
                await asyncio.to_thread(_register_export, zip_name, user.get("username"))
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
            _release_user_job_slot(user)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/exports")
async def list_exports(user: dict = Depends(get_current_user)):
    """
    Lista lo que haya terminado de generarse en el servidor, con link de
    descarga directo. Sirve como red de contención cuando la conexión se
    corta antes de que la web reciba el link (el archivo puede haberse
    terminado igual del lado del servidor) - navegá a /exports para
    buscarlo a mano en vez de tener que volver a generarlo.

    Ownership: cada usuario ve solo lo que exportó él mismo (índice
    filename->username en exports_index.json, ver _register_export).
    SUPERADMIN ve todo. Los archivos "huérfanos" (de antes de esta fase,
    sin dueño registrado) solo los ve SUPERADMIN, por las dudas.
    """
    idx = _load_exports_index()
    is_admin = user["role"] == "SUPERADMIN"
    files = sorted(
        (f for f in EXPORT_DIR.iterdir() if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not is_admin:
        username = user.get("username")
        files = [f for f in files if idx.get(f.name, {}).get("username") == username]
        if not user["unrestricted"] and user["plan"] == PLAN_FREE:
            files = files[:FREE_MAX_EXPORTS_HISTORY]
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
async def download_export(filename: str, user: dict = Depends(get_current_user)):
    """
    Descarga un archivo exportado. Antes no chequeaba dueño (cualquiera con
    la URL podía bajar el export de cualquier otro usuario) - ahora exige
    que el archivo esté registrado a nombre de quien pide, o SUPERADMIN.
    Archivos sin dueño registrado (de antes de esta fase) solo los puede
    bajar SUPERADMIN.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    filepath = EXPORT_DIR / filename
    owner = await asyncio.to_thread(_get_export_owner, filename)
    is_owner = owner is not None and owner == user.get("username")
    if not is_owner and user["role"] != "SUPERADMIN":
        raise HTTPException(status_code=403, detail="No tenés permiso para descargar este archivo.")
    if not filepath.exists():
        restored, _ = await asyncio.to_thread(studio_store.media_path, owner, hashlib.sha256(filename.encode()).hexdigest())
        filepath = restored
    import mimetypes
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(str(filepath), media_type=media_type, filename=filename)


# ============================================================
# EXPORTACIÓN A PREMIERE (FCP7 XML / xmeml)
# ============================================================
# Ver premiere_export.py para el detalle del formato y sus límites
# conocidos (sin confirmar todavía en un Premiere real). A diferencia de
# CapCut, esto NO necesita el puente local - es solo un archivo que el
# usuario importa en su propio Premiere, funciona igual en Render.

class ExportPremiereInput(BaseModel):
    asset_id: str = ""
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ClipSpec]
    sequence_name: str = "AVSuite Export"
    # Los subtítulos van o no van según si el frontend mandó cues en cada
    # clip (no hace falta un flag acá). El orden de los clips también lo
    # decide el frontend antes de mandar la lista (no hay flag de "orden"
    # acá, el backend siempre respeta el orden que recibe).
    separate_tracks: bool = False
    handle_seconds: float = 0.0
    video_track_name: str = ""
    audio_track_name: str = ""
    target_width: int = 0   # 0 = heredar del video fuente
    target_height: int = 0  # 0 = heredar del video fuente
    multiple_sequences: bool = False
    organize_in_bin: bool = False
    include_companion: bool = True
    include_srt: bool = False


@app.post("/export-premiere-xml")
async def export_premiere_xml_endpoint(input_data: ExportPremiereInput, user: dict = Depends(require_pro)):
    await _validate_media_input(input_data, user)
    """Exclusivo PRO (ver require_pro) - marcado como tal en el producto."""
    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
        cached_video = await asyncio.to_thread(cache_video_path, effective_cache_key, user)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido para exportar a Premiere.")
            return
        if not input_data.clips:
            yield event("error", "No hay clips definidos para exportar.")
            return
        timespan_error = validate_clips_timespan(input_data.clips)
        if timespan_error:
            yield event("error", f"Timestamps inválidos: {timespan_error}")
            return

        try:
            await _acquire_user_job_slot(user)
        except HTTPException as e:
            yield event("error", e.detail)
            return

        async for _ in _wait_for_heavy_slot():
            yield event("queued", "Hay otra operación pesada en curso en el servidor. Esperando turno...")

        export_id = deterministic_export_id(
            "premiere-" + (effective_cache_key or input_data.video_path or "local"),
            *[f"{c.start}-{c.end}-{c.label}" for c in input_data.clips],
        )
        video_path = None
        delete_video_after = False  # el cacheado NO se borra, igual que en /export-clips
        # Si el video vino de un archivo subido localmente (no de una URL), el
        # usuario YA lo tiene en su computadora - empaquetarlo de nuevo en el
        # ZIP es una copia redundante (y en videos grandes, pesada/lenta para
        # nada). Solo se bundlea el video cuando viene de una URL, que es el
        # único caso en el que el usuario no tiene el archivo a mano.
        is_local_upload = False

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
                delete_video_after = False
                is_local_upload = True
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
                    transition_out=c.transition_out or "none",
                )
                for c in input_data.clips
            ]

            safe_seq_name = "".join(
                c if c.isalnum() or c in "-_ " else "_" for c in input_data.sequence_name
            )[:40].strip() or "AVSuite_Export"
            if is_local_upload:
                # El nombre que va en el XML es el ORIGINAL con el que la
                # persona subió el archivo (pelamos el prefijo "inspect_XXXXXXXX_"
                # que le pone /inspect-file), no el de la secuencia - así el
                # relink en Premiere apunta al nombre real de su propio archivo.
                import re
                bundled_video_name = re.sub(r'^inspect_[0-9a-f]{8}_', '', os.path.basename(video_path))
            else:
                bundled_video_name = f"{safe_seq_name}{os.path.splitext(video_path)[1] or '.mp4'}"

            try:
                video_info = await asyncio.to_thread(premiere_export.probe_video_info, video_path)
                xml_str = await asyncio.to_thread(
                    premiere_export.build_premiere_xml,
                    video_path, pe_clips, input_data.sequence_name, video_info, bundled_video_name,
                    separate_tracks=input_data.separate_tracks,
                    handle_s=max(0.0, input_data.handle_seconds),
                    video_track_name=input_data.video_track_name.strip() or None,
                    audio_track_name=input_data.audio_track_name.strip() or None,
                    target_width=input_data.target_width or None,
                    target_height=input_data.target_height or None,
                    multiple_sequences=input_data.multiple_sequences,
                    organize_in_bin=input_data.organize_in_bin,
                )
            except Exception as e:
                yield event("error", f"No se pudo armar el XML de Premiere: {e}")
                return
            video_note = (
                f"El video NO se incluyó en este ZIP (venía de un archivo subido localmente, ya lo tenés) - "
                f"al importar el .xml en Premiere, relinkealo contra tu archivo original \"{bundled_video_name}\"."
                if is_local_upload else None
            )

            yield event("merging", "Empaquetando XML + archivos extra en ZIP...", {"pct": 90})
            await asyncio.sleep(0)

            zip_name = f"premiere_{export_id}.zip"
            zip_path = str(EXPORT_DIR / zip_name)
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(f"{safe_seq_name}.xml", xml_str)
                if input_data.include_companion:
                    companion_str = premiere_export.build_premiere_companion_text(
                        pe_clips, input_data.sequence_name, video_note,
                        handle_s=max(0.0, input_data.handle_seconds), src_duration_s=video_info.get("duration_s"),
                    )
                    zf.writestr(f"{safe_seq_name}_companion.txt", companion_str)
                if input_data.include_srt:
                    srt_str = premiere_export.build_premiere_srt(
                        pe_clips, handle_s=max(0.0, input_data.handle_seconds), src_duration_s=video_info.get("duration_s"),
                    )
                    zf.writestr(f"{safe_seq_name}.srt", srt_str)
                if not is_local_upload:
                    # Mismo nombre que quedó embebido en el XML (bundled_video_name)
                    # - así Premiere lo puede relinkear solo si el usuario lo
                    # descomprime todo en la misma carpeta. Si vino de un
                    # archivo local, no se bundlea (ver comentario arriba) - el
                    # usuario ya lo tiene, relinkea a mano contra su original.
                    zf.write(video_path, bundled_video_name)

            await asyncio.to_thread(_register_export, zip_name, user.get("username"))
            extras = []
            if input_data.include_companion:
                extras.append("companion")
            if input_data.include_srt:
                extras.append("srt")
            done_message = "✓ Proyecto de Premiere listo (XML" + (" + " + " + ".join(extras) if extras else "") + ")."
            if is_local_upload:
                done_message += f" No se incluyó el video en el ZIP (ya lo tenés) - al importar el XML en Premiere, relinkealo contra tu archivo original \"{bundled_video_name}\"."
            else:
                done_message += " Incluye el video fuente."
            yield event("done", done_message, {
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
            _release_user_job_slot(user)

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
    asset_id: str = ""
    url: str = ""
    video_path: str = ""
    cache_key: str = ""
    clip: ClipSpec
    subtitle_style: SubtitleStyle | None = None
    project_name: str = ""


@app.post("/export-capcut")
async def export_capcut_endpoint(input_data: ExportCapCutInput, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
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

        effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
        cached_video = await asyncio.to_thread(cache_video_path, effective_cache_key, user)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido.")
            return
        timespan_error = validate_clips_timespan([input_data.clip])
        if timespan_error:
            yield event("error", f"Timestamps inválidos: {timespan_error}")
            return

        try:
            await _acquire_user_job_slot(user)
        except HTTPException as e:
            yield event("error", e.detail)
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
                delete_video_after = False
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
            _release_user_job_slot(user)

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
    asset_id: str = ""
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ReelClipSpec]
    platform: str
    original_size: bool = False  # si True, no se escala/recorta al formato de la plataforma
    subtitle_style: SubtitleStyle | None = None


class CarouselExportInput(BaseModel):
    asset_id: str = ""
    url: str = ""
    video_path: str = ""  # ruta de un archivo subido con /inspect-file, alternativa a url
    cache_key: str = ""   # cache_key del analisis: si el video quedo cacheado, se reusa sin descargar/subir
    clips: list[ReelClipSpec]
    platform: str
    subtitle_style: SubtitleStyle | None = None
    # Sin "tamaño original": el carrusel siempre es 1:1 (clips o placas), no aplica.


@app.post("/export-reel")
async def export_reel_endpoint(input_data: ReelExportInput, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
    """Descarga, corta, une y convierte clips al formato de la plataforma. Devuelve un MP4."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
        cached_video = await asyncio.to_thread(cache_video_path, effective_cache_key, user)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay clips definidos."); return
        timespan_error = validate_clips_timespan(input_data.clips)
        if timespan_error:
            yield event("error", f"Timestamps inválidos: {timespan_error}"); return
        cfg = PLATFORM_CONFIGS.get(input_data.platform)
        if not cfg:
            yield event("error", f"Plataforma desconocida: {input_data.platform}"); return
        try:
            _check_batch_allowed(user, len(input_data.clips))
        except HTTPException as e:
            yield event("error", e.detail); return

        try:
            await _acquire_user_job_slot(user)
        except HTTPException as e:
            yield event("error", e.detail); return

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
                delete_video_after = False
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
                await asyncio.to_thread(_register_export, output_name, user.get("username"))
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
                await asyncio.to_thread(_register_export, zip_name, user.get("username"))
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
            _release_user_job_slot(user)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/export-carousel")
async def export_carousel_endpoint(input_data: CarouselExportInput, user: dict = Depends(get_current_user)):
    await _validate_media_input(input_data, user)
    """Genera un carrusel: clips 1:1 (ZIP de MP4) o placas de texto (ZIP de JPG)."""

    def event(stage: str, message: str, data: dict = None):
        payload = {"stage": stage, "message": message}
        if data:
            payload.update(data)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generator():
        effective_cache_key = input_data.cache_key or (_scoped_cache_key(url_hash(input_data.url), user) if input_data.url else "")
        cached_video = await asyncio.to_thread(cache_video_path, effective_cache_key, user)
        if not cached_video and not input_data.url and not input_data.video_path:
            yield event("error", "Se requiere una URL o un archivo local subido."); return
        if not input_data.clips:
            yield event("error", "No hay slides definidos."); return
        if input_data.platform not in CAROUSEL_PLATFORMS:
            yield event("error", f"Plataforma no es carrusel: {input_data.platform}"); return
        if input_data.platform == "ig_carrusel_clips":
            # Slides de video (rango start→end real, mismo riesgo que /export-clips).
            timespan_error = validate_clips_timespan(input_data.clips)
            if timespan_error:
                yield event("error", f"Timestamps inválidos: {timespan_error}"); return
        else:
            # Placas de texto: solo se usa `start` (un frame puntual, ver
            # extract_frame más abajo) - `end` no aplica acá, no exigir rango.
            bad = [i for i, c in enumerate(input_data.clips, 1) if _parse_ts_strict(c.start) is None]
            if bad:
                yield event("error", f"No pude interpretar el timestamp de la(s) placa(s) {', '.join(map(str, bad))} (formato esperado MM:SS o HH:MM:SS)."); return
        try:
            _check_batch_allowed(user, len(input_data.clips))
        except HTTPException as e:
            yield event("error", e.detail); return

        try:
            await _acquire_user_job_slot(user)
        except HTTPException as e:
            yield event("error", e.detail); return

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
                delete_video_after = False
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
            await asyncio.to_thread(_register_export, zip_name, user.get("username"))

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
            _release_user_job_slot(user)

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


def _plan_payload_for(username: str, role: str) -> dict:
    """Bloque de plan/consumo/límites que se manda al frontend en login y
    auth/check, para que la UI pueda mostrar 'FREE 12/60 min hoy' o 'PRO'
    sin tener que pegarle a otro endpoint aparte."""
    if username == "legacy":
        return {"plan": PLAN_PRO, "unrestricted": True, "daily_usage_seconds": 0, "limits": {}}
    record = _get_user_row(username)
    if not record:
        return {"plan": PLAN_FREE, "unrestricted": False, "daily_usage_seconds": 0, "limits": {}}
    _ensure_plan_defaults(record)
    today = _today_str()
    used = record.get("daily_usage_seconds", 0) if record.get("daily_usage_date") == today else 0
    unrestricted = role == "SUPERADMIN"
    plan = record.get("plan", PLAN_FREE)
    return {
        "plan": plan,
        "unrestricted": unrestricted,
        "daily_usage_seconds": used,
        "limits": {} if (unrestricted or plan == PLAN_PRO) else {
            "daily_seconds": FREE_DAILY_LIMIT_SECONDS,
            "max_file_seconds": FREE_MAX_FILE_SECONDS,
            "max_batch_clips": FREE_MAX_BATCH_CLIPS,
            "max_concurrent_jobs": FREE_MAX_CONCURRENT_JOBS,
        },
    }


@app.get("/auth/check")
def auth_check(session: dict = Depends(require_api_key)):
    """
    El Auth Guard del frontend le pega a este endpoint con el header
    X-API-Key (el token guardado en el navegador) para saber si la sesión
    sigue siendo válida antes de mostrar el dashboard. Devuelve además
    username/role/plan para poder restaurar el estado (badge de SUPERUSER,
    plan/consumo, etc.) sin tener que loguearse de nuevo en cada F5.
    """
    if session:
        return {"ok": True, "username": session["username"], "role": session["role"], **_plan_payload_for(session["username"], session["role"])}
    return {"ok": True, "auth_enabled": bool(API_ACCESS_KEY)}


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def auth_login(body: LoginBody, request: Request):
    _rate_limit(f"login:{_client_ip(request)}", max_requests=10, window_seconds=300)
    users = _load_users()
    user = users.get(body.username)
    if not user or not user.get("active", True) or not _verify_password(body.password, user["password_hash"], user["salt"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    token = secrets.token_hex(24)
    role = user.get("role", "USER")
    studio_store.save_session(token,body.username,role)
    return {"token": token, "username": body.username, "role": role, **_plan_payload_for(body.username, role)}


@app.post("/auth/logout", dependencies=[Depends(require_api_key)])
def auth_logout(x_api_key: str | None = Header(default=None)):
    if x_api_key:
        studio_store.revoke_session(x_api_key)
    return {"ok": True}


class AccessRequestBody(BaseModel):
    name: str
    project: str = ""
    reason: str = ""


@app.post("/access-requests")
def create_access_request(body: AccessRequestBody, request: Request):
    """Público (sin auth): cualquiera sin cuenta puede pedir acceso desde el modal de login."""
    _rate_limit(f"access-request:{_client_ip(request)}", max_requests=5, window_seconds=3600)
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
    plan: str = PLAN_FREE  # "FREE" | "PRO" - el admin elige al aprobar (default FREE)


@app.post("/admin/access-requests/{request_id}/approve", dependencies=[Depends(require_superadmin)])
def approve_access_request(request_id: str, body: ApproveRequestBody):
    reqs = _load_requests()
    req = next((r for r in reqs if r["id"] == request_id), None)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="Usuario y contraseña son obligatorios.")
    plan = body.plan if body.plan in (PLAN_FREE, PLAN_PRO) else PLAN_FREE
    users = _load_users()
    if username in users:
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe.")
    pw_hash, salt = _hash_password(body.password)
    users[username] = {
        "password_hash": pw_hash,
        "salt": salt,
        "role": "USER",
        "plan": plan,
        "daily_usage_seconds": 0,
        "daily_usage_date": _today_str(),
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
    changed = False
    rows = []
    for uname, u in users.items():
        before = dict(u)
        _ensure_plan_defaults(u)
        if u != before:
            changed = True
        today = _today_str()
        used = u.get("daily_usage_seconds", 0) if u.get("daily_usage_date") == today else 0
        rows.append({
            "username": uname,
            "role": u.get("role"),
            "plan": u.get("plan", PLAN_FREE),
            "active": u.get("active", True),
            "created_at": u.get("created_at"),
            "daily_usage_seconds": used,
        })
    if changed:
        _save_users(users)
    return {"users": rows}


class SetPlanBody(BaseModel):
    plan: str  # "FREE" | "PRO"


@app.post("/admin/users/{username}/set-plan", dependencies=[Depends(require_superadmin)])
def set_user_plan(username: str, body: SetPlanBody):
    if body.plan not in (PLAN_FREE, PLAN_PRO):
        raise HTTPException(status_code=400, detail="Plan inválido (usá FREE o PRO).")
    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    _ensure_plan_defaults(users[username])
    users[username]["plan"] = body.plan
    _save_users(users)
    return {"ok": True, "username": username, "plan": body.plan}


@app.post("/admin/users/{username}/activate", dependencies=[Depends(require_superadmin)])
def activate_user(username: str):
    users = _load_users()
    if username not in users:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    users[username]["active"] = True
    _save_users(users)
    return {"ok": True}


def _revoke_sessions_for(username: str):
    studio_store.revoke_user_sessions(username)


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


@app.get("/debug/ytdlp-info", dependencies=[Depends(require_superadmin)])
def debug_ytdlp_info():
    """
    Diagnostico de la infraestructura de descarga de YouTube/Drive: versión
    de yt-dlp, ffmpeg, plugin bgutil-ytdlp-pot-provider, y cookies.txt
    (existencia/tamaño/dueño/permisos - NUNCA contenido). No requiere Shell
    (que es solo para planes pagos de Render) - se consulta como cualquier URL.
    """
    import importlib.metadata
    import io
    import contextlib

    result = {}

    result["yt_dlp_version"] = yt_dlp.version.__version__
    result["ffmpeg_path"] = shutil.which("ffmpeg")
    result["ffprobe_path"] = shutil.which("ffprobe")
    result["deno_path"] = shutil.which("deno")
    result["cookies"] = _cookies_file_diagnostics()

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


# Online studio handlers share the verified export implementations above.
class AnalyzeAssetInput(BaseModel):
    asset_id: str = Field(min_length=32, max_length=64, pattern=r"^[a-f0-9]+$")
    engine: Literal["auto", "gemini", "groq"] = "auto"


async def _analyze_asset_job(payload, user):
    request = AnalyzeAssetInput(**payload)
    path, media = await asyncio.to_thread(studio_store.media_path, account(user), request.asset_id)
    if media["suffix"] in {".png", ".jpg", ".jpeg", ".webp", ".zip"}:
        raise HTTPException(400, "Seleccioná un archivo de audio o video.")
    return StreamingResponse(process_video_streaming(str(path), user, cache_key=request.asset_id, engine=request.engine), media_type="text/event-stream")


async def _studio_ai_job(func, *args, user):
    await _acquire_user_job_slot(user)
    try:
        async with _heavy_ops_semaphore:
            return await asyncio.to_thread(func, *args)
    finally:
        _release_user_job_slot(user)


async def _image_job(payload, user):
    return await _studio_ai_job(generate_images, client, studio_store, account(user), ImageRequest(**payload), user=user)


async def _campaign_job(payload, user):
    return await _studio_ai_job(generate_campaign, _call_gemini_text, CampaignRequest(**payload), user=user)


async def _campaign_package_job(payload, user):
    filename=f"campaña_{uuid.uuid4().hex}.zip"
    request=CampaignPackageRequest(**payload)
    result=await _studio_ai_job(build_campaign_package,request,str(EXPORT_DIR/filename),studio_store,account(user),user=user)
    await asyncio.to_thread(_register_export,filename,account(user))
    return result


async def _capcut_package_job(payload, user):
    request = CapCutPackageRequest(**payload)
    await _validate_media_input(request, user)
    _check_batch_allowed(user, len(request.clips))
    invalid = validate_clips_timespan(request.clips)
    if invalid:
        raise HTTPException(400, invalid)
    await _acquire_user_job_slot(user)
    downloaded = None
    try:
        async with _heavy_ops_semaphore:
            source = request.video_path or await asyncio.to_thread(cache_video_path, request.cache_key, user)
            if not source:
                if not request.url:
                    raise HTTPException(400, "Elegí una fuente para exportar.")
                downloaded = await asyncio.to_thread(download_youtube_video, request.url)
                source = downloaded
            filename = f"capcut_{uuid.uuid4().hex}.zip"
            result = await asyncio.to_thread(build_capcut_package, request, source, str(EXPORT_DIR / filename),
                capcut_export._find_capcut_cli(), cut_single_clip, ts_to_seconds_f, inspect_media_file)
            await asyncio.to_thread(_register_export, filename, account(user))
            return result
    finally:
        if downloaded:
            Path(downloaded).unlink(missing_ok=True)
        _release_user_job_slot(user)


def _export_job(endpoint, model):
    async def run(payload, user):
        return await endpoint(model(**payload), user=user)
    return run


async def _render_studio_job(payload, user):
    request = StudioRenderRequest(**payload)
    await _validate_media_input(request, user)
    invalid = validate_clips_timespan(request.clips)
    if invalid:
        raise HTTPException(400, invalid)
    if request.track_speaker:
        if request.framing != "fill":
            raise HTTPException(400,"Elegí llenar el cuadro para seguir al hablante.")
        await asyncio.to_thread(studio_store.reserve_quota,account(user),"reframe:"+_today_str(),len(request.clips),100)
    await _acquire_user_job_slot(user)
    downloaded = None
    try:
        async with _heavy_ops_semaphore:
            source = request.video_path or await asyncio.to_thread(cache_video_path, request.cache_key, user)
            if not source:
                if not request.url:
                    raise HTTPException(400, "Elegí una fuente para exportar.")
                downloaded = await asyncio.to_thread(download_youtube_video, request.url)
                source = downloaded
            filename = f"montaje_{uuid.uuid4().hex}.mp4"
            result = await asyncio.to_thread(render_studio, request, source, str(EXPORT_DIR / filename), studio_store,
                account(user), ts_to_seconds_f, inspect_media_file, burn_subtitles, SubtitleStyle, client, _get_active_model())
            await asyncio.to_thread(_register_export, filename, account(user))
            return result
    finally:
        if downloaded:
            Path(downloaded).unlink(missing_ok=True)
        _release_user_job_slot(user)


studio_jobs = install_studio(app, studio_store, get_current_user, {
    "analyze-url": (UrlInput, _export_job(analyze_url_stream, UrlInput), False),
    "analyze-file": (AnalyzeAssetInput, _analyze_asset_job, False),
    "export-clips": (ExportClipsInput, _export_job(export_clips_endpoint, ExportClipsInput), False),
    "export-reel": (ReelExportInput, _export_job(export_reel_endpoint, ReelExportInput), False),
    "export-carousel": (CarouselExportInput, _export_job(export_carousel_endpoint, CarouselExportInput), False),
    "export-premiere": (ExportPremiereInput, _export_job(export_premiere_xml_endpoint, ExportPremiereInput), True),
    "export-capcut-local": (ExportCapCutInput, _export_job(export_capcut_endpoint, ExportCapCutInput), True),
    "export-capcut-package": (CapCutPackageRequest, _capcut_package_job, True),
    "generate-images": (ImageRequest, _image_job, True),
    "generate-campaign": (CampaignRequest, _campaign_job, True),
    "render-studio": (StudioRenderRequest, _render_studio_job, True),
    "export-campaign": (CampaignPackageRequest, _campaign_package_job, True),
}, inspect=inspect_media_file)


@app.get("/studio/features")
def studio_features(user: dict = Depends(get_current_user)):
    return {"storage": studio_store.mode, "images": True, "capcut_package": capcut_export._find_capcut_cli() is not None,
            "capcut_local": capcut_export.capcut_available(), "campaigns": True}
