"""
Generador de FCP7 XML (formato "xmeml") para importar una secuencia de
clips + subtitulos directo en Adobe Premiere Pro, sin correr Premiere en
ningun lado - es un archivo de texto que el backend arma y el usuario
importa a mano en SU PROPIO Premiere ("File > Import..." y elegir el
.xml, o arrastrarlo al Project Panel).

Por que este camino y no un MCP que controle Premiere en vivo: correr
Premiere en un servidor para procesar ediciones de clientes pagos viola
los Terminos Generales de Adobe ("on a service bureau basis... or on
behalf of any third party") - ver HANDOFF.md punto 9. Generar un archivo
de intercambio oficial, que el cliente importa en su propia instalacion
licenciada, evita ese problema por completo. Es ademas mas robusto que
el approach de CapCut (ver capcut_export.py): el formato de CapCut hubo
que reversearlo a mano inspeccionando proyectos reales porque no hay
documentacion publica; xmeml SI esta documentado oficialmente por Apple.

Cuidado con el nombre: existen DOS formatos de Apple con nombres
parecidos e INCOMPATIBLES entre si -
  - "FCPXML" (Final Cut Pro X en adelante): basado en <spine>, timing en
    segundos racionales ("1001/30000s"), SIN <track> ni in/out.
  - "xmeml" (Final Cut Pro 7 y anteriores, "Legacy Interchange Format"):
    <sequence><media><video|audio><track><clipitem>, timing en FRAMES
    enteros via in/out/start/end. Es ESTE el que lee Adobe Premiere Pro
    con su "File > Export/Import > Final Cut Pro XML" - confirmado por
    investigacion: Premiere usa "xmeml basado en FCP Classic v6, con tags
    especificos de Adobe". Todo este archivo genera xmeml, no FCPXML.

Fuente del schema: documentacion oficial de Apple (developer.apple.com,
"Final Cut Pro XML Interchange Format", DTDs v1-5) - no se tuvo acceso a
un Premiere real para reversear un archivo exportado de verdad (a
diferencia de CapCut, donde si habia proyectos reales del usuario para
copiar). La estructura de <clipitem> (video+audio, in/out/start/end en
frames, <file> compartido entre clips del mismo material) esta bien
documentada y multiples fuentes independientes la confirman. La parte de
<generatoritem> para subtitulos como texto nativo editable es MAS
incierta - existe en el DTD pero no hay confirmacion de que el
generador "Text" de FCP7 se importe igual en Premiere. Por eso
build_premiere_companion_text() genera ademas un texto plano con los
mismos subtitulos y timestamps, pensado para que una persona (o un
copiloto de IA dentro de Premiere) los recree a mano si el
<generatoritem> no entra bien.

SIN PROBAR contra un Premiere real todavia - ver "Open decisions" en
HANDOFF.md. Antes de ofrecer este export a un cliente real, alguien con
Premiere instalado tiene que confirmar que el .xml generado abre bien y
que decidir si el generatoritem de subtitulos sobrevive o no.
"""

from __future__ import annotations

import subprocess
import json
import uuid
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dataclasses import dataclass, field


# Mapeo de fps NTSC comunes a (timebase entero, flag ntsc) - xmeml no
# tiene forma de escribir "29.97" directo, codifica el "drop frame" real
# via timebase redondeado + <ntsc>TRUE</ntsc>.
_NTSC_TIMEBASES = {
    23.976: 24,
    29.97: 30,
    47.952: 48,
    59.94: 60,
    119.88: 120,
}


def _rate_timebase_ntsc(fps: float) -> tuple[int, bool]:
    for ntsc_fps, timebase in _NTSC_TIMEBASES.items():
        if abs(fps - ntsc_fps) < 0.02:
            return timebase, True
    return max(1, round(fps)), False


def probe_video_info(video_path: str) -> dict:
    """
    width/height/fps/duration_s via ffprobe - mismos datos que ya usa
    main.py para otras cosas (_ffprobe_dimensions), agrupados en un dict
    para no pegarle 3 llamadas separadas a ffprobe.
    """
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", video_path,
        ],
        capture_output=True, text=True, timeout=30,
    )
    info = json.loads(result.stdout or "{}")
    stream = (info.get("streams") or [{}])[0]
    width = int(stream.get("width") or 1920)
    height = int(stream.get("height") or 1080)
    fr = stream.get("r_frame_rate") or "30/1"
    num, _, den = fr.partition("/")
    fps = float(num) / float(den or 1) if den else float(num)
    duration_s = float((info.get("format") or {}).get("duration") or 0)
    return {"width": width, "height": height, "fps": fps or 30.0, "duration_s": duration_s}


@dataclass
class PremiereSubtitleCue:
    start_s: float  # segundos, relativo al inicio del CLIP (no del timeline final)
    end_s: float
    text: str


@dataclass
class PremiereClip:
    source_start_s: float  # in-point dentro del video fuente
    source_end_s: float    # out-point dentro del video fuente
    label: str = ""
    subtitles: list[PremiereSubtitleCue] = field(default_factory=list)


def _seq_id() -> str:
    return uuid.uuid4().hex[:8]


def _add_rate(parent: ET.Element, fps: float) -> None:
    timebase, ntsc = _rate_timebase_ntsc(fps)
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def build_premiere_xml(
    video_path: str,
    clips: list[PremiereClip],
    sequence_name: str = "AVSuite Export",
    video_info: dict | None = None,
    source_filename: str | None = None,
    separate_tracks: bool = False,
) -> str:
    """
    Arma un xmeml con una secuencia: los `clips` quedan puestos uno atras
    del otro en el timeline (pensado para el flujo de reel/carrusel, que
    ya arma varios clips en una sola pieza - para un clip suelto es una
    secuencia de un solo clipitem). Cada clip aporta un clipitem de video
    y uno de audio, ambos apuntando al MISMO <file> (definido una sola
    vez, referenciado por id despues - así lo hace xmeml cuando varios
    clips vienen del mismo material). Los subtitulos de cada clip se
    agregan como <generatoritem> de texto en una pista de video aparte
    (siempre compartida entre todos los clips, independiente de
    `separate_tracks`), con su posicion recalculada a la posicion real
    dentro del timeline final (las cues vienen relativas al inicio de
    CADA clip, no del timeline armado).

    `separate_tracks`: si es False (default), todos los clips van en UNA
    sola pista de video + UNA de audio, uno atrás del otro ("mismo
    canal"). Si es True, cada clip recibe su PROPIA pista de video y de
    audio (N clips = N tracks de cada tipo) - siguen sin superponerse en
    el tiempo (mismos offsets acumulados que en el modo compartido), pero
    quedan en tracks separados para poder moverlos/ajustarlos en Premiere
    sin afectar a los clips vecinos.

    `video_path` es la ruta real en el server (se usa solo para leer
    metadata con ffprobe si no viene `video_info`) - NUNCA se escribe tal
    cual dentro del XML, esa ruta no existe en la máquina del usuario.
    Lo que sí se escribe es `source_filename` (o el basename de
    `video_path` si no se pasa uno): tiene que ser EXACTAMENTE el mismo
    nombre de archivo con el que se empaqueta el video en el ZIP que
    recibe el usuario, para que Premiere lo pueda relinkear solo si
    queda al lado del .xml.
    """
    if not clips:
        raise ValueError("Necesito al menos un clip para armar la secuencia.")

    info = video_info or probe_video_info(video_path)
    fps = info["fps"]
    width, height = info["width"], info["height"]
    file_name = source_filename or video_path.rsplit("/", 1)[-1]
    file_id = f"file-{_seq_id()}"
    file_defined = False

    xmeml = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(xmeml, "sequence", id=f"sequence-{_seq_id()}")
    ET.SubElement(sequence, "name").text = sequence_name

    total_frames = sum(
        round((c.source_end_s - c.source_start_s) * fps) for c in clips
    )
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _add_rate(sequence, fps)

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")

    # Formato/resolucion de la secuencia (se toma del video fuente, no
    # se deja elegir a mano - ver capability matrix del v2: lo
    # customizable es QUE clips entran, no la estructura del archivo).
    fmt = ET.SubElement(video, "format")
    char = ET.SubElement(fmt, "samplecharacteristics")
    _add_rate(char, fps)
    ET.SubElement(char, "width").text = str(width)
    ET.SubElement(char, "height").text = str(height)
    ET.SubElement(char, "pixelaspectratio").text = "square"
    ET.SubElement(char, "anamorphic").text = "FALSE"
    ET.SubElement(char, "fielddominance").text = "none"

    text_track = ET.SubElement(video, "track")  # subtítulos: siempre una pista propia y compartida

    audio = ET.SubElement(media, "audio")

    # Modo compartido: una sola pista de video/audio para todos los clips,
    # creada una vez acá afuera del loop. Modo separado: cada clip crea la
    # suya propia DENTRO del loop (ver abajo) - acá no se define nada.
    shared_video_track = None
    shared_audio_track = None
    if not separate_tracks:
        shared_video_track = ET.SubElement(video, "track")
        shared_audio_track = ET.SubElement(audio, "track")

    timeline_frame = 0  # cursor de escritura en el timeline final

    for clip in clips:
        in_frame = round(clip.source_start_s * fps)
        out_frame = round(clip.source_end_s * fps)
        clip_len = max(1, out_frame - in_frame)
        start_frame = timeline_frame
        end_frame = timeline_frame + clip_len
        clip_name = clip.label or f"Clip {_seq_id()}"

        if separate_tracks:
            video_track = ET.SubElement(video, "track")
            audio_track = ET.SubElement(audio, "track")
        else:
            video_track = shared_video_track
            audio_track = shared_audio_track

        # --- clipitem de video ---
        v_item = ET.SubElement(video_track, "clipitem", id=f"clipitem-{_seq_id()}")
        ET.SubElement(v_item, "name").text = clip_name
        ET.SubElement(v_item, "duration").text = str(clip_len)
        _add_rate(v_item, fps)
        ET.SubElement(v_item, "start").text = str(start_frame)
        ET.SubElement(v_item, "end").text = str(end_frame)
        ET.SubElement(v_item, "in").text = str(in_frame)
        ET.SubElement(v_item, "out").text = str(out_frame)
        v_item.append(_file_element(file_id, file_name, info, fps, define_full=not file_defined))
        file_defined = True

        # --- clipitem de audio (mismo material, mismo in/out/start/end) ---
        a_item = ET.SubElement(audio_track, "clipitem", id=f"clipitem-{_seq_id()}")
        ET.SubElement(a_item, "name").text = clip_name
        ET.SubElement(a_item, "duration").text = str(clip_len)
        _add_rate(a_item, fps)
        ET.SubElement(a_item, "start").text = str(start_frame)
        ET.SubElement(a_item, "end").text = str(end_frame)
        ET.SubElement(a_item, "in").text = str(in_frame)
        ET.SubElement(a_item, "out").text = str(out_frame)
        a_item.append(_file_element(file_id, file_name, info, fps, define_full=False))

        # --- subtitulos de este clip, reubicados en el timeline final ---
        for cue in clip.subtitles:
            cue_start = start_frame + round(cue.start_s * fps)
            cue_end = start_frame + round(cue.end_s * fps)
            cue_end = max(cue_end, cue_start + 1)
            _add_generator_text(text_track, cue.text, cue_start, cue_end, fps)

        if separate_tracks:
            # enabled/locked van DESPUES de los clipitems dentro de cada
            # <track> (schema de xmeml) - en modo separado cada track es
            # de UN clip nomas, así que se cierra ya mismo, no se puede
            # esperar a después del loop como en el modo compartido.
            ET.SubElement(video_track, "enabled").text = "TRUE"
            ET.SubElement(video_track, "locked").text = "FALSE"
            ET.SubElement(audio_track, "enabled").text = "TRUE"
            ET.SubElement(audio_track, "locked").text = "FALSE"

        timeline_frame = end_frame

    if not separate_tracks:
        ET.SubElement(shared_video_track, "enabled").text = "TRUE"
        ET.SubElement(shared_video_track, "locked").text = "FALSE"
        ET.SubElement(shared_audio_track, "enabled").text = "TRUE"
        ET.SubElement(shared_audio_track, "locked").text = "FALSE"

    ET.SubElement(text_track, "enabled").text = "TRUE"
    ET.SubElement(text_track, "locked").text = "FALSE"

    return _pretty_xml(xmeml)


def _file_element(file_id: str, file_name: str, info: dict, fps: float, define_full: bool) -> ET.Element:
    """
    xmeml deduplica material: la primera vez que se referencia un video
    se define completo (<file id=X> con name/pathurl/rate/duration/media),
    las siguientes veces solo <file id=X/> vacio, apuntando al mismo id.

    `pathurl` va SIN ruta de carpeta (solo el nombre del archivo): es la
    ruta del servidor la que no tiene sentido en la máquina del usuario,
    así que se deja como referencia "relativa" - Premiere la resuelve
    sola si el video queda en la misma carpeta que el .xml al descomprimir
    el ZIP, o si no, pide relinkear mostrando ese mismo nombre de archivo.
    """
    file_el = ET.Element("file", id=file_id)
    if not define_full:
        return file_el
    ET.SubElement(file_el, "name").text = file_name
    ET.SubElement(file_el, "pathurl").text = f"file://localhost/{file_name}"
    _add_rate(file_el, fps)
    ET.SubElement(file_el, "duration").text = str(round(info["duration_s"] * fps))
    file_media = ET.SubElement(file_el, "media")
    file_video = ET.SubElement(file_media, "video")
    fv_char = ET.SubElement(file_video, "samplecharacteristics")
    ET.SubElement(fv_char, "width").text = str(info["width"])
    ET.SubElement(fv_char, "height").text = str(info["height"])
    file_audio = ET.SubElement(file_media, "audio")
    fa_char = ET.SubElement(file_audio, "samplecharacteristics")
    ET.SubElement(fa_char, "samplerate").text = "48000"
    ET.SubElement(fa_char, "depth").text = "16"
    return file_el


def _add_generator_text(track: ET.Element, text: str, start_frame: int, end_frame: int, fps: float) -> None:
    """
    <generatoritem> con el generador "Text" incorporado de FCP7. Sin
    confirmar si Premiere lo importa como texto editable de verdad (ver
    docstring del modulo) - vale la pena intentarlo porque, si funciona,
    es mejor que el companion en texto plano (queda embebido y editable
    directo en el timeline).
    """
    gen = ET.SubElement(track, "generatoritem", id=f"generator-{_seq_id()}")
    ET.SubElement(gen, "name").text = "Text"
    ET.SubElement(gen, "duration").text = str(max(1, end_frame - start_frame))
    _add_rate(gen, fps)
    ET.SubElement(gen, "start").text = str(start_frame)
    ET.SubElement(gen, "end").text = str(end_frame)
    ET.SubElement(gen, "enabled").text = "TRUE"
    effect = ET.SubElement(gen, "effect")
    ET.SubElement(effect, "name").text = "Text"
    ET.SubElement(effect, "effectid").text = "Text"
    ET.SubElement(effect, "effectcategory").text = "Text"
    ET.SubElement(effect, "effecttype").text = "generator"
    ET.SubElement(effect, "mediatype").text = "video"
    param = ET.SubElement(effect, "parameter")
    ET.SubElement(param, "name").text = "Text"
    ET.SubElement(param, "value").text = text


def _pretty_xml(root: ET.Element) -> str:
    rough = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    # minidom deja una linea vacia por cada nodo de texto - limpiar
    return "\n".join(line for line in pretty.split("\n") if line.strip())


def build_premiere_companion_text(clips: list[PremiereClip], sequence_name: str = "AVSuite Export", video_note: str | None = None) -> str:
    """
    "Prompt companion": texto plano con los cortes y subtitulos de la
    secuencia, para que la persona (o un copiloto de IA dentro de
    Premiere) complete a mano lo que el <generatoritem> de subtitulos no
    haya traido bien - ver docstring del modulo. Timestamps en MM:SS
    relativos al timeline FINAL (ya con los clips uno atras del otro),
    no al video fuente.

    `video_note`: linea opcional sobre donde esta el video (ej: si no se
    bundleo en el ZIP porque venia de un archivo subido localmente y el
    usuario ya lo tiene) - vive acá en vez de solo en el mensaje de "done"
    de la UI porque este texto viaja CON el ZIP y no desaparece.
    """
    lines = [
        f"Companion de texto para \"{sequence_name}\"",
        "Generado por AI Audiovisual Suite Pro - completar a mano en Premiere",
        "si los subtítulos no entraron bien desde el archivo .xml importado.",
    ]
    if video_note:
        lines.append(video_note)
    lines.append("")
    cursor_s = 0.0
    for i, clip in enumerate(clips, 1):
        clip_len = clip.source_end_s - clip.source_start_s
        start_mmss = _seconds_to_mmss(cursor_s)
        end_mmss = _seconds_to_mmss(cursor_s + clip_len)
        label = clip.label or f"Clip {i}"
        lines.append(f"Clip {i} ({start_mmss} - {end_mmss}) \"{label}\":")
        if not clip.subtitles:
            lines.append("  (sin subtítulos)")
        for cue in clip.subtitles:
            cue_mmss = _seconds_to_mmss(cursor_s + cue.start_s)
            lines.append(f"  [{cue_mmss}] {cue.text}")
        lines.append("")
        cursor_s += clip_len
    return "\n".join(lines)


def _seconds_to_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"
