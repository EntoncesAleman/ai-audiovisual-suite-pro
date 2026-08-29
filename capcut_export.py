"""
Integración con CapCut Pro (escritorio, local) vía capcut-cli.

CapCut no tiene API oficial ni exportación headless. La vía anterior de
este archivo (armar el JSON del draft a mano, clonando un proyecto real
como plantilla) generaba solo los archivos de la raíz del draft y nunca
la carpeta Timelines/<uuid>/ anidada que CapCut >= 8.7 realmente lee como
fuente de verdad (la raíz es un espejo derivado que CapCut regenera al
abrir el proyecto) - por eso los drafts generados a mano nunca llegaban
a abrir con contenido real ("Upload" / 0.0B). Ver HANDOFF.md puntos 6/10
para el historial completo de esa investigación.

Esta versión usa **capcut-cli** (github.com/renezander030/capcut-cli,
MIT, `npm install -g capcut-cli`), una herramienta de comunidad que sí
construye la estructura anidada moderna correctamente, y desde su v0.21
agrega `sync-timelines --nested --apply` - el fix real (no un copy
manual) para sincronizar raíz→anidado, confirmado contra CapCut Mac
9.2.8/9.3.0 en el issue #50 de esa herramienta. Todo esto ya se probó a
mano esta sesión con un video sintético: quickstart + add-video +
add-text + text-style (borde) + sync-timelines --nested --apply dejó la
raíz y el anidado bit a bit idénticos, con el video y el texto con
estilo presentes en ambos.

Limitación conocida (sin cambios respecto a la versión anterior): la
tipografía elegida en nuestro panel de subtítulos NO se traduce a CapCut
- capcut-cli tampoco expone un `--font` en `add-text`/`text-style` que
apunte a un archivo de fuente arbitrario (CapCut resuelve tipografías
contra su propio catálogo de recursos descargados). Color y borde sí se
traducen.

Requiere que CapCut esté CERRADO mientras se generan/registran drafts -
la app también lee/escribe estos mismos archivos mientras corre, y
tocarlos en simultáneo puede pisar una escritura del proceso real. No
hay forma de verificar esto desde acá; quien llama a estas funciones
tiene que asegurarse de que el usuario cerró CapCut antes.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

CAPCUT_PROJECTS_DIR = Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
_GENERATED_PREFIX = "AVSuite_"


def capcut_available() -> bool:
    return CAPCUT_PROJECTS_DIR.exists()


def _find_capcut_cli() -> str | None:
    """
    Busca el binario de capcut-cli: variable de entorno CAPCUT_CLI_BIN
    primero (por si se instaló en una ruta no estándar), después el PATH
    normal, y como último recurso le pregunta a npm dónde deja los
    binarios globales (necesario en esta Mac: el prefix de npm es
    ~/.local/node, que no está en el PATH de todos los procesos, ej. el
    LaunchAgent del server).
    """
    env_path = os.getenv("CAPCUT_CLI_BIN")
    if env_path and Path(env_path).exists():
        return env_path

    found = shutil.which("capcut")
    if found:
        return found

    try:
        result = subprocess.run(
            ["npm", "root", "-g"], capture_output=True, text=True, timeout=10
        )
        npm_root = result.stdout.strip()  # ej: ~/.local/node/lib/node_modules
        if npm_root:
            # node_modules/ vive en lib/ junto a bin/, dos niveles arriba
            candidate = Path(npm_root).parent.parent / "bin" / "capcut"
            if candidate.exists():
                return str(candidate)
    except Exception:
        pass
    return None


def _find_real_template_dir() -> Path | None:
    """
    Cualquier carpeta de draft real (no generada por nosotros) que ya
    exista en esta Mac, para pasarle a `capcut quickstart --template`.
    Evita el bug de la plantilla interna de capcut-cli (declara una
    versión de CapCut vieja, 6.5.0) que hace que el draft aparezca en
    0:00 y falle al abrir - ver warning que la propia herramienta
    imprime, y HANDOFF.md punto 10.
    """
    if not CAPCUT_PROJECTS_DIR.exists():
        return None
    for entry in sorted(CAPCUT_PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(_GENERATED_PREFIX):
            continue
        if (entry / "draft_info.json").exists():
            return entry
    return None


def _probe_height(clip_path: str, default: int = 1920) -> int:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=height", "-of", "json", clip_path],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(result.stdout or "{}")
        streams = info.get("streams") or [{}]
        return int(streams[0].get("height") or default)
    except Exception:
        return default


def _run_cli(capcut_bin: str, *args: str, timeout: int = 60) -> tuple[int, dict | None, str, str]:
    result = subprocess.run(
        [capcut_bin, *args], capture_output=True, text=True, timeout=timeout,
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = None
    return result.returncode, data, result.stdout, result.stderr


def build_and_register_capcut_draft(
    project_name: str,
    clip_path: str,
    cues: list[dict],
    style: dict,
) -> tuple[bool, str, dict | None]:
    """
    Arma un draft de CapCut real (video + subtítulos con color/borde) y
    lo deja registrado y sincronizado, todo vía capcut-cli.

    cues: lista de {start, end, text} en segundos, relativos al clip.
    style: mismo shape que nuestro SubtitleStyle - {font (no se usa,
    ver limitación en el docstring del módulo), color, border_color,
    border_width}.

    Devuelve (ok, message, info_dict). info_dict trae folder_path y el
    detalle de cada paso (útil para diagnosticar qué falló si algo no
    salió perfecto - a diferencia del intento anterior, acá un fallo en
    UN subtítulo no aborta todo el draft, sigue con el resto).
    """
    capcut_bin = _find_capcut_cli()
    if not capcut_bin:
        return False, "No encontré el binario de capcut-cli en esta máquina. Instalalo con: npm install -g capcut-cli", None
    if not capcut_available():
        return False, "No encontré la carpeta de proyectos de CapCut en esta Mac (~/Movies/CapCut). ¿Está instalado?", None

    template_dir = _find_real_template_dir()
    if not template_dir:
        return False, "No encontré ningún proyecto existente de CapCut para usar como plantilla de estructura. Creá al menos un proyecto (aunque sea vacío) en CapCut primero.", None

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in project_name)[:60].strip() or "export"
    folder_name = f"{_GENERATED_PREFIX}{safe_name}_{int(time.time())}"
    draft_dir = CAPCUT_PROJECTS_DIR / folder_name

    rc, data, out, err = _run_cli(
        capcut_bin, "quickstart", folder_name, "--video", clip_path, "--template", str(template_dir),
        timeout=120,
    )
    if rc != 0 or not data or not data.get("ok"):
        detail = (data or {}).get("error") if data else (err or out)[:300]
        return False, f"capcut-cli quickstart falló: {detail}", None

    font_size = max(20, round(_probe_height(clip_path) * 0.045))
    cue_results = []
    for cue in cues:
        text = (cue.get("text") or "").strip()
        start_s, end_s = cue.get("start", 0), cue.get("end", 0)
        if not text or end_s <= start_s:
            continue
        rc, seg_data, out, err = _run_cli(
            capcut_bin, "add-text", str(draft_dir), str(start_s), str(end_s - start_s), text,
            "--color", style.get("color", "#FFFFFF"), "--font-size", str(font_size),
        )
        if rc != 0 or not seg_data or not seg_data.get("ok"):
            cue_results.append({"text": text[:30], "ok": False, "error": (seg_data or {}).get("error") if seg_data else err[:150]})
            continue

        seg_id = seg_data.get("segment_id")
        border_width = style.get("border_width", 0)
        border_ok = True
        if seg_id and border_width:
            rc2, _, _, err2 = _run_cli(
                capcut_bin, "text-style", str(draft_dir), seg_id,
                "--border-width", str(border_width), "--border-color", style.get("border_color", "#000000"),
            )
            border_ok = rc2 == 0
        cue_results.append({"text": text[:30], "ok": True, "border_ok": border_ok})

    rc, sync_data, out, err = _run_cli(capcut_bin, "sync-timelines", str(draft_dir), "--nested", "--apply")
    sync_ok = bool(sync_data and sync_data.get("ok") and sync_data.get("in_sync"))

    failed_cues = [c for c in cue_results if not c.get("ok")]
    msg = "Draft de CapCut generado, registrado y sincronizado."
    if not sync_ok:
        msg += " ⚠ sync-timelines no confirmó estar en sync - revisar a mano antes de confiar en que abre con contenido real."
    if failed_cues:
        msg += f" ⚠ {len(failed_cues)}/{len(cues)} subtítulo(s) no se pudieron agregar."

    info = {
        "folder_path": str(draft_dir),
        "project_name": project_name,
        "registered": bool(data.get("registered")),
        "synced": sync_ok,
        "cues_added": len(cue_results) - len(failed_cues),
        "cues_total": len(cues),
        "cue_results": cue_results,
    }
    return True, msg, info


def delete_capcut_draft(folder_path: str) -> tuple[bool, str]:
    """
    Limpieza de un draft (de prueba o si el usuario se arrepiente) -
    borra la carpeta y usa `capcut prune`/deja que el próximo escaneo de
    CapCut la saque sola del índice. NO toca root_meta_info.json a mano
    (evita el mismo tipo de riesgo que registrar) - basta con borrar la
    carpeta, CapCut deja de listarla la próxima vez que escanea.
    """
    path = Path(folder_path)
    if not path.exists():
        return False, "La carpeta ya no existe."
    if not path.name.startswith(_GENERATED_PREFIX):
        return False, "Por seguridad, solo borro carpetas generadas por AVSuite (prefijo AVSuite_)."
    shutil.rmtree(path, ignore_errors=True)
    return True, "Draft borrado."
