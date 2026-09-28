import { state } from '../state.js';
import { getSessions, setSessions, clearUrlDraft } from '../utils/storage.js';
import { renderClipsList } from './clips.js';
import { renderReelClipsList, updateVideoPanel } from './reelEditor.js';
import { generateIAPrompt } from './prompts.js';
import { toggleEdit } from './timeline.js';
import { renderInteractiveTranscript } from './transcriptPanel.js';
import { setTelemetryMetrics, resetExportPreview } from '../utils/dom.js';
import { estimateDurationSeconds, secondsToTs, collapseRepeatedRuns } from '../utils/helpers.js';

// El listado/administración del historial (borrar, exportar JSON, importar,
// borrar caché del servidor) vive en historial.html/historial.js, una
// página aparte. Acá solo queda lo que esta página necesita: guardar la
// sesión recién analizada y poder cargar una sesión existente por id
// (typ. al volver desde el historial con ?session=<id>, ver app.js).

export function saveSession(data) {
    if (state._pendingSourceUrl) { data.source_url = state._pendingSourceUrl; state._pendingSourceUrl = ""; }
    // Metadata de la tabla System Telemetry, para que sobreviva a recargar
    // esta sesión más tarde desde el historial (ver loadSessionData abajo).
    data.engine_label = state.lastEngineLabel;
    data.input_label = state.lastInputLabel;
    data.diarization_label = state.lastDiarizationLabel;
    let sessions = getSessions();
    const newSession = { id: Date.now(), timestamp: new Date().toLocaleDateString(), data: data };
    sessions.unshift(newSession);
    try {
        setSessions(sessions);
    } catch (e) {
        alert("⚠ El historial está casi lleno. Andá al Historial y exportá/vaciá algunas sesiones antes de seguir.");
    }
    state.currentSessionId = newSession.id;
    loadSessionData(data);
}

export function loadSessionById(id) {
    let sessions = getSessions();
    let item = sessions.find(s => s.id === id);
    if (item) {
        state.currentSessionId = id;
        loadSessionData(item.data);
    }
}

export function loadSessionData(data) {
    state.currentData = data;
    // collapseRepeatedRuns acá (no solo en parseTimelineToSegments) para que
    // la caja cruda editable (#resTimeline, ver timeline.js) y todo lo que
    // lee state.originalTimeline directo (SRT, prompt de IA) también queden
    // limpios - incluye sesiones YA guardadas de antes de este fix, se
    // arreglan solas la próxima vez que se cargan, sin reanalizar el video.
    state.originalTimeline = collapseRepeatedRuns(data.raw_timeline || "No hay líneas de tiempo registradas.");
    document.getElementById('resTimeline').innerText = state.originalTimeline;
    document.getElementById('cacheBadge').innerHTML = data.from_cache ? '<span class="cache-badge">⚡ DESDE CACHE</span>' : '';
    document.getElementById('timelineSearch').value = "";
    document.getElementById('searchInfo').textContent = "";
    if (state.editing) toggleEdit();
    // Restaurar URL fuente en el panel de clips
    document.getElementById('clipSourceUrl').value = data.source_url || "";
    // El panel de clips arranca vacío: parseClipsFromTimeline() arma UN CLIP
    // POR CADA BLOQUE de diálogo de la transcripción (no una selección
    // curada) - en un video largo con muchos cambios de turno esto podía
    // volcar cientos de clips sin que la persona pidiera nada. Pedido
    // explícito: que no se dispare solo, solo a mano con "Extraer
    // timestamps" o generando con IA.
    state.clipsList = [];
    renderClipsList();
    // Actualizar panel de video para redes
    state.reelClipsList = [];
    renderReelClipsList();
    updateVideoPanel();
    generateIAPrompt();
    renderInteractiveTranscript();
    resetExportPreview('previewVideo');
    const durationSec = estimateDurationSeconds(state.originalTimeline);
    setTelemetryMetrics({
        engine: data.engine_label || "—",
        input: data.input_label || data.source_url || "—",
        duration: durationSec > 0 ? `~${secondsToTs(durationSec)}` : "—",
        diarization: data.diarization_label || "—",
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

export function startNewSession() {
    state.currentData = null;
    state.currentSessionId = null;
    document.getElementById('streamUrl').value = "";
    document.getElementById('localFile').value = "";
    document.getElementById('resTimeline').innerText = "Procesá un audio/video para ver acá la transcripción completa.";
    document.getElementById('cacheBadge').innerHTML = "";
    document.getElementById('promptOutput').innerText = "Carga un análisis para generar el prompt dinámico...";
    state.originalTimeline = "";
    state.clipsList = [];
    renderClipsList();
    state.reelClipsList = [];
    renderReelClipsList();
    updateVideoPanel();
    renderInteractiveTranscript();
    resetExportPreview('previewVideo');
    setTelemetryMetrics({ engine: "—", input: "—", duration: "—", diarization: "—" });
    clearUrlDraft();
}
