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
    # Transición HACIA el próximo clip de la secuencia (por-par, no global -
    # ver _TRANSITION_EFFECTS). "none"/vacío/desconocido = corte seco, sin
    # <transitionitem>. Solo tiene efecto si el clip tiene un siguiente y la
    # secuencia usa track compartido (separate_tracks=False) - un
    # <transitionitem> vive entre dos <clipitem> del MISMO <track>.
    transition_out: str = "none"


# Duración fija del crossfade - no se expone como opción por clip para no
# sumar otro control más; si hace falta ajustarla en Premiere después, es
# un handle que se arrastra en el timeline como cualquier transición.
_TRANSITION_DURATION_S = 1.0

# effectid/name tomados de nombres estándar de FCP7 (documentación/fuentes
# públicas, no de un XML real exportado por Premiere) - mismo caveat que
# el resto del archivo: sin confirmar contra un Premiere real todavía.
_TRANSITION_EFFECTS = {
    "dissolve": ("Cross Dissolve", "Dissolve"),
    "dip_black": ("Fade In Fade Out Dissolve", "Dissolve"),
    "wipe": ("Standard Wipe", "Wipe"),
}


def _transition_duration_frames(fps: float) -> int:
    return max(2, round(_TRANSITION_DURATION_S * fps))


def _seq_id() -> str:
    return uuid.uuid4().hex[:8]


def _add_rate(parent: ET.Element, fps: float) -> None:
    timebase, ntsc = _rate_timebase_ntsc(fps)
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(timebase)
    ET.SubElement(rate, "ntsc").text = "TRUE" if ntsc else "FALSE"


def _padded_clip_bounds(clip: PremiereClip, handle_s: float, src_duration_s: float | None) -> tuple[float, float, float]:
    """
    Devuelve (padded_start_s, padded_end_s, front_pad_s) para un clip con
    handle/margen aplicado - agrega `handle_s` segundos de aire antes y
    después del corte real, tomados del video FUENTE (no inventados), para
    tener margen de ajuste fino al editar en Premiere. Recortado en los
    bordes: no resta antes de 0 ni suma más allá de la duración real del
    video fuente si la conocemos. `front_pad_s` (el margen que
    efectivamente se pudo aplicar adelante, puede ser menor a `handle_s`
    si el corte ya estaba pegado al inicio del video) hace falta después
    para reubicar los subtítulos, que siguen siendo relativos al corte
    ORIGINAL pedido, no al padding.
    """
    if handle_s <= 0:
        return clip.source_start_s, clip.source_end_s, 0.0
    front_pad = min(handle_s, clip.source_start_s)
    back_pad = handle_s
    if src_duration_s:
        back_pad = min(handle_s, max(0.0, src_duration_s - clip.source_end_s))
    return clip.source_start_s - front_pad, clip.source_end_s + back_pad, front_pad


def _build_sequence(
    seq_name: str,
    clips: list[PremiereClip],
    info: dict,
    fps: float,
    file_id: str,
    file_name: str,
    file_defined: list[bool],
    separate_tracks: bool,
    handle_s: float,
    video_track_name: str | None,
    audio_track_name: str | None,
    target_width: int | None,
    target_height: int | None,
) -> ET.Element:
    """
    Arma UNA <sequence> completa (video+audio+subtítulos) para los
    `clips` dados. Factoreado aparte de build_premiere_xml() para poder
    llamarlo más de una vez cuando `multiple_sequences=True` genera,
    además de la secuencia "master" con todos los clips, una secuencia
    extra por cada clip individual - mismo motor, sin duplicar la lógica.

    `file_defined` es una lista de un elemento (`[bool]`) compartida
    entre TODAS las llamadas a esta función dentro del mismo XML: el
    <file> completo (name/pathurl/rate/duration/media) solo se escribe
    una vez en TODO el documento, sin importar cuántas secuencias lo
    referencien - las demás referencias son solo `<file id=X/>` vacío.
    """
    src_duration_s = info.get("duration_s")
    padded = [_padded_clip_bounds(c, handle_s, src_duration_s) for c in clips]
    clip_frames = [(round(ps * fps), round(pe * fps)) for ps, pe, _ in padded]
    clip_lens = [max(1, of - inf) for inf, of in clip_frames]
    src_total_frames = round(src_duration_s * fps) if src_duration_s else None

    sequence = ET.Element("sequence", id=f"sequence-{_seq_id()}")
    ET.SubElement(sequence, "name").text = seq_name

    # Ojo: las transiciones NO cambian la duración total (extienden el
    # saliente hacia adelante pero el próximo clip arranca en la misma
    # posición de siempre - ver el loop de abajo), así que esta suma sigue
    # siendo correcta aunque haya transiciones.
    total_frames = sum(clip_lens)
    ET.SubElement(sequence, "duration").text = str(total_frames)
    _add_rate(sequence, fps)

    media = ET.SubElement(sequence, "media")
    video = ET.SubElement(media, "video")

    # Formato/resolucion de la secuencia: por default se toma del video
    # fuente; si se pide target_width/height (ej. adaptar a 9:16 para
    # redes) se declara ESE tamaño en la secuencia - el contenido de los
    # clips no se escala/recorta acá (eso lo hace Premiere al importar,
    # como con cualquier material que no matchea el tamaño del timeline),
    # más simple y sin arriesgar transforms de motion mal armados.
    fmt = ET.SubElement(video, "format")
    char = ET.SubElement(fmt, "samplecharacteristics")
    _add_rate(char, fps)
    ET.SubElement(char, "width").text = str(target_width or info["width"])
    ET.SubElement(char, "height").text = str(target_height or info["height"])
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
        if video_track_name:
            ET.SubElement(shared_video_track, "name").text = video_track_name
        shared_audio_track = ET.SubElement(audio, "track")
        if audio_track_name:
            ET.SubElement(shared_audio_track, "name").text = audio_track_name

    timeline_frame = 0  # cursor de escritura en el timeline final

    for idx, clip in enumerate(clips):
        in_frame, out_frame = clip_frames[idx]
        front_pad_s = padded[idx][2]
        clip_len = clip_lens[idx]
        start_frame = timeline_frame
        end_frame = start_frame + clip_len
        clip_name = clip.label or f"Clip {_seq_id()}"

        # Transición HACIA el próximo clip: extiende el out-point de ESTE
        # clip con frames extra de source (mismo mecanismo que el handle),
        # clampeado a lo que realmente hay disponible - no del próximo
        # clip, que queda con su in/out sin tocar y arranca en la MISMA
        # posición de siempre (por eso el cursor de abajo sigue avanzando
        # por `clip_len` sin extender, ver comentario en total_frames).
        transition_type = (clip.transition_out or "none").strip()
        overlap_frames = 0
        has_next = idx + 1 < len(clips)
        if has_next and not separate_tracks and transition_type in _TRANSITION_EFFECTS:
            want = _transition_duration_frames(fps)
            avail_extend = max(0, src_total_frames - out_frame) if src_total_frames is not None else want
            avail_next = max(0, clip_lens[idx + 1] - 1)
            overlap_frames = max(0, min(want, avail_extend, avail_next))
        ext_out_frame = out_frame + overlap_frames
        ext_end_frame = end_frame + overlap_frames

        if separate_tracks:
            video_track = ET.SubElement(video, "track")
            if video_track_name:
                ET.SubElement(video_track, "name").text = f"{video_track_name} {idx + 1}"
            audio_track = ET.SubElement(audio, "track")
            if audio_track_name:
                ET.SubElement(audio_track, "name").text = f"{audio_track_name} {idx + 1}"
        else:
            video_track = shared_video_track
            audio_track = shared_audio_track

        # --- clipitem de video (out/end extendidos si hay transición saliente) ---
        v_item = ET.SubElement(video_track, "clipitem", id=f"clipitem-{_seq_id()}")
        ET.SubElement(v_item, "name").text = clip_name
        ET.SubElement(v_item, "duration").text = str(ext_end_frame - start_frame)
        _add_rate(v_item, fps)
        ET.SubElement(v_item, "start").text = str(start_frame)
        ET.SubElement(v_item, "end").text = str(ext_end_frame)
        ET.SubElement(v_item, "in").text = str(in_frame)
        ET.SubElement(v_item, "out").text = str(ext_out_frame)
        v_item.append(_file_element(file_id, file_name, info, fps, define_full=not file_defined[0]))
        file_defined[0] = True

        # --- clipitem de audio (mismo material, mismo in/out/start/end) ---
        a_item = ET.SubElement(audio_track, "clipitem", id=f"clipitem-{_seq_id()}")
        ET.SubElement(a_item, "name").text = clip_name
        ET.SubElement(a_item, "duration").text = str(ext_end_frame - start_frame)
        _add_rate(a_item, fps)
        ET.SubElement(a_item, "start").text = str(start_frame)
        ET.SubElement(a_item, "end").text = str(ext_end_frame)
        ET.SubElement(a_item, "in").text = str(in_frame)
        ET.SubElement(a_item, "out").text = str(ext_out_frame)
        a_item.append(_file_element(file_id, file_name, info, fps, define_full=False))

        # --- transitionitem hacia el próximo clip, si corresponde - tiene
        # que quedar en el XML ENTRE el clipitem de este clip y el del
        # próximo (orden de hijos dentro del <track>), por eso se agrega
        # acá y no en un paso aparte al final del loop ---
        if overlap_frames > 0:
            eff_name, eff_category = _TRANSITION_EFFECTS[transition_type]
            _add_transitionitem(video_track, eff_name, eff_category, end_frame, ext_end_frame, fps, "video")
            _add_transitionitem(audio_track, "Cross Fade (0dB)", "Crossfade", end_frame, ext_end_frame, fps, "audio")

        # --- subtitulos de este clip, reubicados en el timeline final ---
        # las cues son relativas al corte ORIGINAL pedido (sin padding),
        # así que hay que sumarles el margen que se agregó adelante
        # (front_pad_s) para que sigan cayendo sobre el mismo audio real.
        for cue in clip.subtitles:
            cue_start = start_frame + round(front_pad_s * fps) + round(cue.start_s * fps)
            cue_end = start_frame + round(front_pad_s * fps) + round(cue.end_s * fps)
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

    return sequence


def build_premiere_xml(
    video_path: str,
    clips: list[PremiereClip],
    sequence_name: str = "AVSuite Export",
    video_info: dict | None = None,
    source_filename: str | None = None,
    separate_tracks: bool = False,
    handle_s: float = 0.0,
    video_track_name: str | None = None,
    audio_track_name: str | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
    multiple_sequences: bool = False,
    organize_in_bin: bool = False,
) -> str:
    """
    Arma un xmeml con una secuencia "master": los `clips` quedan puestos
    uno atras del otro en el timeline (pensado para el flujo de
    reel/carrusel, que ya arma varios clips en una sola pieza - para un
    clip suelto es una secuencia de un solo clipitem). Cada clip aporta
    un clipitem de video y uno de audio, ambos apuntando al MISMO <file>
    (definido una sola vez en TODO el documento, referenciado por id
    despues). Los subtitulos de cada clip se agregan como <generatoritem>
    de texto en una pista de video aparte.

    Las transiciones son PER-CLIP (`clip.transition_out`, ver PremiereClip),
    no una opcion de esta funcion: cada clip declara la transicion hacia el
    SIGUIENTE, y solo se aplica si hay un clip siguiente y `separate_tracks`
    es False (un <transitionitem> vive entre dos <clipitem> del mismo
    <track> - en modo "canales separados" no hay forma de representarla).

    Opciones (todas opcionales, default = comportamiento previo):
    - `separate_tracks`: cada clip en su propia pista de video/audio en
      vez de todos apilados en una sola ("mismo canal" vs "separados").
    - `handle_s`: segundos de margen/aire agregados antes y después de
      cada corte (tomados del video fuente, recortado en los bordes) -
      ver `_padded_clip_bounds`.
    - `video_track_name`/`audio_track_name`: nombre custom para las
      pistas en vez del default de Premiere. SIN CONFIRMAR que Premiere
      respete `<track><name>` (no está en la documentación que se pudo
      conseguir) - si no lo hace, el peor caso es que el nombre se
      ignore, no debería romper el import.
    - `target_width`/`target_height`: declara la secuencia a este
      tamaño en vez de heredar el del video fuente (ej. adaptar a 9:16) -
      el contenido de los clips no se escala acá, Premiere lo maneja al
      importar como con cualquier material que no matchea el timeline.
    - `multiple_sequences`: además de la secuencia master (todos los
      clips juntos), genera una secuencia extra POR CADA clip individual
      (útil para poder abrir/exportar un clip suelto sin tocar el master).
    - `organize_in_bin`: envuelve las secuencias en un <bin> con el
      nombre de la secuencia, para que aparezcan agrupadas en el Project
      Panel de Premiere en vez de sueltas en la raíz. Estructura
      confirmada por documentación oficial (`<xmeml><bin><name>...
      <children><sequence>...`), pero sin probar contra un Premiere real
      (mismo caveat que el resto del archivo).

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
    file_name = source_filename or video_path.rsplit("/", 1)[-1]
    file_id = f"file-{_seq_id()}"
    file_defined = [False]  # compartido entre todas las secuencias del documento

    xmeml = ET.Element("xmeml", version="5")

    sequences = [
        _build_sequence(
            sequence_name, clips, info, fps, file_id, file_name, file_defined,
            separate_tracks, handle_s, video_track_name, audio_track_name,
            target_width, target_height,
        )
    ]
    if multiple_sequences:
        for i, clip in enumerate(clips, 1):
            single_name = f"{sequence_name} - {clip.label or f'Clip {i}'}"[:80]
            sequences.append(
                _build_sequence(
                    single_name, [clip], info, fps, file_id, file_name, file_defined,
                    separate_tracks=False, handle_s=handle_s,
                    video_track_name=video_track_name, audio_track_name=audio_track_name,
                    target_width=target_width, target_height=target_height,
                )
            )

    if organize_in_bin:
        bin_el = ET.SubElement(xmeml, "bin")
        ET.SubElement(bin_el, "name").text = sequence_name
        children = ET.SubElement(bin_el, "children")
        for seq in sequences:
            children.append(seq)
    else:
        for seq in sequences:
            xmeml.append(seq)

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


def _add_transitionitem(
    track: ET.Element, effect_name: str, effect_category: str,
    start_frame: int, end_frame: int, fps: float, mediatype: str,
) -> None:
    """
    <transitionitem>: dissolve/fundido/wipe entre dos <clipitem> CONSECUTIVOS
    del mismo <track> (por eso solo se arma en modo "mismo canal" - en
    "canales separados" cada clip vive en su propio track y un
    transitionitem entre tracks distintos no es representable acá). El
    clip saliente ya viene con su out-point extendido para que exista
    material real de source en la zona de overlap (ver el loop en
    _build_sequence) - esto solo escribe el elemento que le dice a Premiere
    "acá hay una transición", no mueve nada más.
    """
    t = ET.SubElement(track, "transitionitem", id=f"transition-{_seq_id()}")
    ET.SubElement(t, "start").text = str(start_frame)
    ET.SubElement(t, "end").text = str(end_frame)
    ET.SubElement(t, "alignment").text = "center"
    _add_rate(t, fps)
    effect = ET.SubElement(t, "effect")
    ET.SubElement(effect, "name").text = effect_name
    ET.SubElement(effect, "effectid").text = effect_name
    ET.SubElement(effect, "effectcategory").text = effect_category
    ET.SubElement(effect, "effecttype").text = "transition"
    ET.SubElement(effect, "mediatype").text = mediatype


def _pretty_xml(root: ET.Element) -> str:
    rough = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    # minidom deja una linea vacia por cada nodo de texto - limpiar
    return "\n".join(line for line in pretty.split("\n") if line.strip())


def build_premiere_companion_text(
    clips: list[PremiereClip],
    sequence_name: str = "AVSuite Export",
    video_note: str | None = None,
    handle_s: float = 0.0,
    src_duration_s: float | None = None,
) -> str:
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

    `handle_s`/`src_duration_s`: mismo padding que build_premiere_xml -
    si se usó margen/handles, este texto tiene que reflejar los MISMOS
    tiempos que terminaron en el XML, no los del corte sin padding.
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
        padded_start_s, padded_end_s, front_pad_s = _padded_clip_bounds(clip, handle_s, src_duration_s)
        clip_len = padded_end_s - padded_start_s
        start_mmss = _seconds_to_mmss(cursor_s)
        end_mmss = _seconds_to_mmss(cursor_s + clip_len)
        label = clip.label or f"Clip {i}"
        lines.append(f"Clip {i} ({start_mmss} - {end_mmss}) \"{label}\":")
        if not clip.subtitles:
            lines.append("  (sin subtítulos)")
        for cue in clip.subtitles:
            cue_mmss = _seconds_to_mmss(cursor_s + front_pad_s + cue.start_s)
            lines.append(f"  [{cue_mmss}] {cue.text}")
        lines.append("")
        cursor_s += clip_len
    return "\n".join(lines)


def build_premiere_srt(
    clips: list[PremiereClip],
    handle_s: float = 0.0,
    src_duration_s: float | None = None,
) -> str:
    """
    SRT real (no solo texto plano) con los mismos subtítulos y timing que
    quedó en el <generatoritem> del XML - pensado como backup adjunto en
    el ZIP para poder importarlo directo como pista de subtítulos en
    Premiere ("File > Import" de un .srt) si el generatoritem no entra
    bien. Timestamps en el formato HH:MM:SS,mmm que pide el estándar SRT,
    relativos al timeline FINAL armado (mismo criterio que el companion).
    """
    lines = []
    cursor_s = 0.0
    n = 0
    for clip in clips:
        padded_start_s, padded_end_s, front_pad_s = _padded_clip_bounds(clip, handle_s, src_duration_s)
        clip_len = padded_end_s - padded_start_s
        for cue in clip.subtitles:
            n += 1
            cue_start = cursor_s + front_pad_s + cue.start_s
            cue_end = cursor_s + front_pad_s + cue.end_s
            lines.append(str(n))
            lines.append(f"{_seconds_to_srt_ts(cue_start)} --> {_seconds_to_srt_ts(cue_end)}")
            lines.append(cue.text)
            lines.append("")
        cursor_s += clip_len
    return "\n".join(lines)


def _seconds_to_srt_ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    hh, rem_ms = divmod(total_ms, 3_600_000)
    mm, rem_ms = divmod(rem_ms, 60_000)
    ss, ms = divmod(rem_ms, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _seconds_to_mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"
