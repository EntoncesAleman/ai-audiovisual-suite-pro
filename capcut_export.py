"""
Prototipo de integración con CapCut Pro (escritorio, local).

CapCut no tiene una API oficial ni exportación headless. Lo que sí existe es
su formato de proyecto ("draft"): una carpeta con un draft_info.json (JSON
plano) que describe pistas, clips y textos. Si generamos una carpeta con esa
forma dentro de la carpeta de Proyectos de CapCut, la app la puede abrir como
un proyecto editable más.

Esto es 100% no oficial y reversineado a mano inspeccionando proyectos reales
ya guardados en esta máquina (ver ~/Movies/CapCut/User Data/Projects/) - no
hay documentación pública del formato, así que puede romperse con una
actualización de CapCut. En vez de adivinar cada campo, clonamos un proyecto
real y válido que ya exista en esta Mac como "plantilla" estructural, y solo
pisamos los campos que nos importan (clip, texto, color, timing). Así los
cientos de campos internos que no entendemos quedan con valores que sabemos
que la versión de CapCut instalada acá acepta.

Limitación conocida: la tipografía elegida en nuestro panel de subtítulos NO
se traduce todavía a CapCut (los textos generados usan la fuente default de
CapCut) - las fuentes reales que usamos para el burn-in son archivos sueltos,
pero CapCut resuelve tipografías contra su propio catálogo de recursos
descargados, no contra una ruta de archivo arbitraria. Color, borde y timing
sí se traducen.
"""

import copy
import json
import os
import shutil
import time
import uuid
from pathlib import Path

CAPCUT_PROJECTS_DIR = Path.home() / "Movies" / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
_GENERATED_PREFIX = "AVSuite_"


def capcut_available() -> bool:
    return CAPCUT_PROJECTS_DIR.exists()


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _hex_to_rgb_float(hex_color: str, default=(1.0, 1.0, 1.0)):
    try:
        h = (hex_color or "").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return default


def _rgb_float_to_hex_alpha(rgb) -> str:
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}ff"


def _load_template_draft():
    """Usa cualquier draft real y válido que ya exista en esta máquina como
    plantilla estructural, en vez de adivinar a mano los ~100 campos internos
    sin documentar que tiene el formato."""
    if not CAPCUT_PROJECTS_DIR.exists():
        return None
    for entry in sorted(CAPCUT_PROJECTS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(_GENERATED_PREFIX):
            continue
        info_path = entry / "draft_info.json"
        if not info_path.exists():
            continue
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mats = data.get("materials", {})
            if data.get("tracks") and mats.get("videos") and mats.get("texts"):
                return data
        except Exception:
            continue
    return None


def _build_video_material(template_mat, clip_path, width, height, duration_us):
    mat = copy.deepcopy(template_mat)
    mat["id"] = _new_id()
    mat["path"] = clip_path
    mat["media_path"] = ""
    mat["duration"] = duration_us
    mat["width"] = width
    mat["height"] = height
    mat["material_name"] = os.path.basename(clip_path)
    mat["local_material_id"] = str(uuid.uuid4())
    mat["crop"] = {
        "upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
        "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0,
    }
    return mat


def _build_video_segment(template_seg, material_id, duration_us):
    seg = copy.deepcopy(template_seg)
    seg["id"] = _new_id()
    seg["source_timerange"] = {"start": 0, "duration": duration_us}
    seg["target_timerange"] = {"start": 0, "duration": duration_us}
    seg["render_timerange"] = {"start": 0, "duration": 0}
    seg["clip"] = {
        "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0},
        "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0,
    }
    seg["material_id"] = material_id
    seg["extra_material_refs"] = []
    seg["render_index"] = 0
    seg["keyframe_refs"] = []
    seg["track_render_index"] = 0
    seg["group_id"] = ""
    seg["caption_info"] = None
    return seg


def _build_text_material(template_mat, text, hex_color, hex_border_color, border_width_norm, font_size):
    mat = copy.deepcopy(template_mat)
    mat["id"] = _new_id()
    mat["name"] = mat["id"]
    mat["recognize_task_id"] = ""
    mat["recognize_text"] = text

    rgb = _hex_to_rgb_float(hex_color)
    border_rgb = _hex_to_rgb_float(hex_border_color, (0.0, 0.0, 0.0))
    style_run = {
        "fill": {"content": {"solid": {"color": list(rgb)}, "render_type": "solid"}},
        "range": [0, len(text)],
        "strokes": (
            [{"width": border_width_norm, "mode": 0, "content": {"solid": {"color": list(border_rgb)}, "render_type": "solid"}}]
            if border_width_norm > 0 else []
        ),
        "useLetterColor": False,
        "size": font_size,
        "font": {"path": "", "id": ""},
    }
    mat["content"] = json.dumps({"styles": [style_run], "text": text}, ensure_ascii=False)
    mat["words"] = {"start_time": [], "end_time": [], "text": []}
    mat["current_words"] = {"start_time": [], "end_time": [], "text": []}

    mat["text_color"] = _rgb_float_to_hex_alpha(rgb)
    mat["text_alpha"] = 1.0
    mat["border_color"] = _rgb_float_to_hex_alpha(border_rgb)
    mat["border_alpha"] = 1.0 if border_width_norm > 0 else 0.0
    mat["border_width"] = border_width_norm
    mat["border_mode"] = 0
    mat["font_size"] = font_size
    mat["text_size"] = font_size
    mat["font_name"] = ""
    mat["font_title"] = "none"
    mat["font_path"] = ""
    mat["font_id"] = ""
    mat["font_resource_id"] = ""
    mat["fonts"] = []
    mat["has_shadow"] = False
    mat["combo_info"] = {"text_templates": []}
    mat["caption_template_info"] = {
        "resource_id": "", "third_resource_id": "", "resource_name": "", "category_id": "",
        "category_name": "", "effect_id": "", "request_id": "", "path": "", "is_new": False, "source_platform": 0,
    }
    return mat


def _build_text_segment(template_seg, material_id, start_us, duration_us):
    seg = copy.deepcopy(template_seg)
    seg["id"] = _new_id()
    seg["source_timerange"] = None
    seg["target_timerange"] = {"start": start_us, "duration": duration_us}
    seg["render_timerange"] = {"start": 0, "duration": 0}
    seg["clip"] = {
        "scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": -0.65},
        "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0,
    }
    seg["material_id"] = material_id
    seg["extra_material_refs"] = []
    seg["render_index"] = 14000
    seg["keyframe_refs"] = []
    seg["group_id"] = ""
    seg["caption_info"] = None
    return seg


def build_capcut_draft(project_name: str, clip_path: str, width: int, height: int, fps: float,
                        duration_us: int, cues: list, style: dict):
    """
    cues: lista de {start, end, text} en segundos, relativos al clip.
    style: {font, color, border_color, border_width} (mismo shape que
    nuestro SubtitleStyle - "font" no se traduce todavía, ver limitación
    documentada arriba del archivo).

    Devuelve (ok, message, info_dict). info_dict trae draft_id/folder_path/
    duration_us, útil para un registro posterior en root_meta_info.json.
    """
    if not capcut_available():
        return False, "No encontré la carpeta de proyectos de CapCut en esta Mac (~/Movies/CapCut). ¿Está instalado?", None

    template = _load_template_draft()
    if not template:
        return False, "No encontré ningún proyecto existente de CapCut para usar como plantilla de estructura. Creá al menos un proyecto (aunque sea vacío) en CapCut primero.", None

    template_video_track = next((t for t in template["tracks"] if t.get("type") == "video" and t.get("segments")), None)
    template_text_track = next((t for t in template["tracks"] if t.get("type") == "text" and t.get("segments")), None)
    if not template_video_track or not template_text_track:
        return False, "El proyecto de CapCut que encontré como plantilla no tiene pistas de video/texto usables.", None

    draft_id = _new_id()
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in project_name)[:60].strip() or "export"
    folder_name = f"{_GENERATED_PREFIX}{safe_name}_{int(time.time())}"
    folder_path = CAPCUT_PROJECTS_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=False)
    (folder_path / "Resources").mkdir(exist_ok=True)
    (folder_path / "Timelines").mkdir(exist_ok=True)

    template_video_mat = template["materials"]["videos"][0]
    template_text_mat = template["materials"]["texts"][0]

    video_material = _build_video_material(template_video_mat, clip_path, width, height, duration_us)
    video_segment = _build_video_segment(template_video_track["segments"][0], video_material["id"], duration_us)
    video_track = {"id": _new_id(), "type": "video", "segments": [video_segment], "flag": 2, "attribute": 0, "name": "", "is_default_name": True}

    text_materials, text_segments = [], []
    for cue in cues:
        text = (cue.get("text") or "").strip()
        start_s, end_s = cue.get("start", 0), cue.get("end", 0)
        if not text or end_s <= start_s:
            continue
        border_norm = round(max(0, style.get("border_width", 3)) / 40.0, 4)
        font_size = max(20, round(height * 0.045))
        mat = _build_text_material(
            template_text_mat, text,
            style.get("color", "#FFFFFF"), style.get("border_color", "#000000"),
            border_norm, font_size,
        )
        seg = _build_text_segment(
            template_text_track["segments"][0], mat["id"],
            int(start_s * 1_000_000), int((end_s - start_s) * 1_000_000),
        )
        text_materials.append(mat)
        text_segments.append(seg)

    text_track = {"id": _new_id(), "type": "text", "segments": text_segments, "flag": 0, "attribute": 0, "name": "", "is_default_name": True}

    draft_info = copy.deepcopy(template)
    draft_info["id"] = draft_id
    draft_info["name"] = project_name
    draft_info["duration"] = duration_us
    draft_info["fps"] = fps
    draft_info["canvas_config"] = {"ratio": "original", "width": width, "height": height, "background": None}
    draft_info["tracks"] = [video_track, text_track]
    draft_info["materials"] = {k: [] for k in template["materials"].keys()}
    draft_info["materials"]["videos"] = [video_material]
    draft_info["materials"]["texts"] = text_materials
    draft_info["cover"] = None
    draft_info["static_cover_image_path"] = ""
    if isinstance(draft_info.get("config"), dict):
        draft_info["config"]["subtitle_recognition_id"] = ""
        draft_info["config"]["subtitle_taskinfo"] = []
    now_us = int(time.time() * 1_000_000)
    draft_info["create_time"] = now_us
    draft_info["update_time"] = now_us

    with open(folder_path / "draft_info.json", "w", encoding="utf-8") as f:
        json.dump(draft_info, f, ensure_ascii=False)

    draft_meta = {
        "draft_cover": "draft_cover.jpg",
        "draft_fold_path": str(folder_path),
        "draft_id": draft_id,
        "draft_is_invisible": False,
        "draft_name": project_name,
        "draft_root_path": str(CAPCUT_PROJECTS_DIR),
        "draft_removable": True,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_duration": duration_us,
    }
    with open(folder_path / "draft_meta_info.json", "w", encoding="utf-8") as f:
        json.dump(draft_meta, f, ensure_ascii=False, indent=4)

    with open(folder_path / "draft_virtual_store.json", "w", encoding="utf-8") as f:
        json.dump({"draft_materials": [], "draft_virtual_store": [{"type": 0, "value": []}, {"type": 1, "value": []}, {"type": 2, "value": []}]}, f)

    now_s = int(time.time())
    with open(folder_path / "draft_settings", "w", encoding="utf-8") as f:
        f.write(f"[General]\ncloud_last_modify_platform=mac\ndraft_create_time={now_s}\ndraft_last_edit_time={now_s}\nreal_edit_keys=0\nreal_edit_seconds=0\n")

    with open(folder_path / "draft_biz_config.json", "w", encoding="utf-8") as f:
        json.dump({"timeline_settings": {}}, f)

    info = {
        "draft_id": draft_id,
        "folder_path": str(folder_path),
        "project_name": project_name,
        "duration_us": duration_us,
    }
    return True, "Draft de CapCut generado.", info


def register_draft_in_capcut(draft_id: str, folder_path: str, project_name: str, duration_us: int):
    """Agrega la entrada al índice root_meta_info.json que CapCut lee para
    mostrar el proyecto en la pantalla de Drafts. Hace un backup antes de
    escribir. Llamar SOLO con CapCut cerrado, para no chocar con una
    escritura del proceso real de la app sobre el mismo archivo."""
    root_path = CAPCUT_PROJECTS_DIR / "root_meta_info.json"
    if not root_path.exists():
        return False, "No encontré root_meta_info.json."

    with open(root_path, "r", encoding="utf-8") as f:
        root = json.load(f)

    backup_path = root_path.with_name(root_path.name + ".avsuite_backup")
    shutil.copy(root_path, backup_path)

    now_us = int(time.time() * 1_000_000)
    entry = {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": str(Path(folder_path) / "draft_cover.jpg"),
        "draft_fold_path": str(folder_path),
        "draft_id": draft_id,
        "draft_is_ai_shorts": False, "draft_is_cloud_temp_draft": False,
        "draft_is_invisible": False, "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_json_file": str(Path(folder_path) / "draft_info.json"),
        "draft_name": project_name,
        "draft_new_version": "", "draft_root_path": str(CAPCUT_PROJECTS_DIR),
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "", "pippit_id": "",
        "pippit_user_name": "", "streaming_edit_draft_ready": True,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": 0, "tm_draft_cloud_user_id": 0,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": duration_us,
    }
    root.setdefault("all_draft_store", []).insert(0, entry)
    with open(root_path, "w", encoding="utf-8") as f:
        json.dump(root, f, ensure_ascii=False)
    return True, f"Registrado en CapCut. Backup del índice original en {backup_path.name}."
