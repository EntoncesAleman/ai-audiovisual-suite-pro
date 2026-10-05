import { authHeaders } from './storage.js';

export function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

export function highlightSearch(text, query) {
    if (!query) return text;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

/**
 * Actualiza una barra de progreso de exportación identificada por prefijo
 * (ej: "clipExport" -> #clipExportProgress / #clipExportProgressFill / #clipExportProgressPct).
 */
export function setExportProgress(prefix, pct) {
    const wrap = document.getElementById(`${prefix}Progress`);
    const fill = document.getElementById(`${prefix}ProgressFill`);
    const label = document.getElementById(`${prefix}ProgressPct`);
    if (!wrap || !fill || !label) return;
    wrap.classList.add('active');
    const clamped = Math.max(0, Math.min(100, pct));
    fill.style.width = clamped + '%';
    label.textContent = Math.round(clamped) + '%';
}

export function resetExportProgress(prefix) {
    const wrap = document.getElementById(`${prefix}Progress`);
    const fill = document.getElementById(`${prefix}ProgressFill`);
    const label = document.getElementById(`${prefix}ProgressPct`);
    if (!wrap || !fill || !label) return;
    wrap.classList.remove('active');
    fill.style.width = '0%';
    label.textContent = '0%';
}

/**
 * Mini-player de vista previa: es un único panel compartido (#previewVideo,
 * arriba junto al metraje, separado del generador/exportador) que se
 * completa con el resultado de la última exportación, sea cual sea la
 * pestaña (clips simples o video para redes) que la generó. El recuadro
 * siempre está visible, con un placeholder hasta que haya un resultado
 * real. Solo carga el video cuando el resultado es un único mp4 ya
 * descargable (no un ZIP con varios clips o placas, ahí no hay un único
 * archivo que previsualizar y se deja el placeholder). `videoUrl` debe ser
 * la URL absoluta ya resuelta (ej: downloadBtn.href).
 */
/**
 * videoUrl es una ruta protegida (/exports/{filename}, exige dueño - ver
 * main.py); un <video src> plano no manda headers custom, así que hay que
 * traerlo con fetch() + X-API-Key y pasarle el blob resultante, igual que
 * loadRemoteSourcePreview en player.js (mismo motivo).
 */
export async function showExportPreview(videoId, payload, videoUrl) {
    const video = document.getElementById(videoId);
    const placeholder = document.getElementById(`${videoId}Placeholder`);
    if (!video) return;
    const isSingleMp4 = payload.clip_count === 1 && (payload.filename || "").endsWith(".mp4");
    if (isSingleMp4 && videoUrl) {
        try {
            const res = await fetch(videoUrl, { headers: authHeaders() });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            video.src = URL.createObjectURL(await res.blob());
            video.classList.add('has-src');
            if (placeholder) placeholder.style.display = 'none';
        } catch (e) {
            resetExportPreview(videoId);
        }
    } else {
        resetExportPreview(videoId);
    }
}

/** Vuelve el mini-player a su estado placeholder (ej: al arrancar una exportación nueva). */
export function resetExportPreview(videoId) {
    const video = document.getElementById(videoId);
    const placeholder = document.getElementById(`${videoId}Placeholder`);
    if (video) {
        video.removeAttribute('src');
        video.load();
        video.classList.remove('has-src');
    }
    if (placeholder) placeholder.style.display = 'flex';
}

/**
 * Panel "System Telemetry": un único log fijo, siempre visible en la
 * página (no aparece/desaparece con la acción en curso), que acumula lo
 * que va haciendo el servidor durante toda la sesión: análisis inicial
 * y exportaciones. `prefix` identifica el panel: espera #<prefix>Log y
 * #<prefix>Badge en el HTML.
 */
const TELEMETRY_KIND_BY_STAGE = {
    error: "error",
    done: "success",
    queued: "warn",
};
const TELEMETRY_MAX_LINES = 300;

export function telemetryLog(prefix, message, stage = "info") {
    const log = document.getElementById(`${prefix}Log`);
    if (!log || !message) return;
    const kind = TELEMETRY_KIND_BY_STAGE[stage] || "info";
    const time = new Date().toLocaleTimeString('es-AR', { hour12: false });
    const line = document.createElement('div');
    line.className = `telemetry-line telemetry-${kind}`;
    line.innerHTML = `<span class="telemetry-ts">[${time}]</span>${escapeHtml(message)}`;
    log.appendChild(line);
    while (log.children.length > TELEMETRY_MAX_LINES) {
        log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
    setTelemetryState(prefix, stage);
}

function setTelemetryState(prefix, stage) {
    const badge = document.getElementById(`${prefix}Badge`);
    if (!badge) return;
    const states = {
        idle: { cls: 'state-idle', text: '○ EN ESPERA' },
        done: { cls: 'state-done', text: '✓ LISTO' },
        error: { cls: 'state-error', text: '✕ ERROR' },
    };
    const s = states[stage] || { cls: 'state-live', text: '● EN CURSO' };
    badge.className = `telemetry-badge ${s.cls}`;
    badge.textContent = s.text;
    if (prefix === 'telemetry') updateTelemetryDonut(stage);
}

/**
 * Dona + radios IDLE/SCANNING del panel System Telemetry: reflejan el mismo
 * estado que ya calcula setTelemetryState (arriba), traducido a las 4
 * variantes visuales del donut (idle/scanning/done/error).
 */
function updateTelemetryDonut(stage) {
    const donut = document.getElementById('telemetryDonut');
    if (!donut) return;
    const donutState = stage === 'idle' ? 'idle' : stage === 'done' ? 'done' : stage === 'error' ? 'error' : 'scanning';
    donut.dataset.state = donutState;

    const idleRadio = document.getElementById('statusRadioIdle');
    const scanRadio = document.getElementById('statusRadioScanning');
    if (idleRadio) idleRadio.classList.toggle('active', donutState === 'idle' || donutState === 'done');
    if (scanRadio) scanRadio.classList.toggle('active', donutState === 'scanning');
}

/**
 * Fila de métricas del panel System Telemetry (Engine / Input / Duration /
 * Diarization). Se llama al arrancar un análisis (analysis.js, con lo que
 * el usuario eligió) y al cargar una sesión guardada (sessions.js, con lo
 * que quedó persistido en esa sesión).
 */
export function setTelemetryMetrics({ engine, input, duration, diarization } = {}) {
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? "—"; };
    set('metricEngine', engine);
    set('metricInput', input);
    set('metricDuration', duration);
    set('metricDiarization', diarization);
}
