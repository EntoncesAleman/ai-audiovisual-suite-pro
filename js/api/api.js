import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { authHeaders } from '../utils/storage.js';
import { telemetryLog } from '../utils/dom.js';

/**
 * Resuelve de dónde sale el video fuente para exportar. Orden de prioridad:
 * 1. cache_key del análisis actual (el server guardó el video, cero re-subida/descarga).
 * 2. URL pegada.
 * 3. Archivo local subido de nuevo (fallback si el cache ya no está).
 * Devuelve {cache_key}, {url} o {video_path}, o null si no hay ninguna
 * (y ya mostró el alert correspondiente).
 */
export async function resolveExportSource(urlInputId, fileInputId, statusEl) {
    const url = document.getElementById(urlInputId).value.trim();
    const fileInput = document.getElementById(fileInputId);
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    if (state.currentData && state.currentData.cache_key && !file) {
        // Mandamos la URL igual aunque haya cache_key: el disco de Render es
        // efímero, así que si el server se reinició desde que se analizó el
        // video, el cache del video ya no existe ahí aunque el frontend
        // todavía lo recuerde. El backend prueba cache primero y si no está
        // cae en descargar de la URL en vez de fallar con "falta URL".
        return { cache_key: state.currentData.cache_key, url };
    }

    if (!url && !file) {
        alert("Pegá la URL del video fuente o seleccioná el archivo local antes de exportar.");
        return null;
    }
    if (file) {
        if (statusEl) {
            statusEl.className = "clip-export-status active";
            statusEl.textContent = "⏳ Subiendo archivo local...";
        }
        telemetryLog('telemetry', `Subiendo archivo local (${file.name})...`, 'uploading');
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(`${BACKEND_URL}/inspect-file`, { method: "POST", headers: authHeaders(), body: formData });
        if (!res.ok) {
            telemetryLog('telemetry', '❌ Error subiendo el archivo local.', 'error');
            throw new Error("No se pudo subir el archivo (HTTP " + res.status + ")");
        }
        const info = await res.json();
        telemetryLog('telemetry', '✓ Archivo local subido.', 'done');
        return { video_path: info.temp_path };
    }
    return { url };
}

/**
 * Pide miniaturas reales (un frame por clip, en su timestamp de inicio) al
 * backend - solo funciona si el video ya quedó cacheado del análisis (o hay
 * una URL a mano): a propósito NO fuerza descarga ni re-subida de archivo
 * local solo para una miniatura, así que si no hay nada disponible, los
 * clips se quedan con `thumbnail: null` (el grid cae al placeholder de
 * siempre) en vez de bloquear o mostrar un error.
 *
 * Muta `clip.thumbnail` in-place en los clips de `clipsList` que todavía no
 * tengan esa propiedad (`undefined`) - llamar de nuevo con la misma lista es
 * barato, solo pide lo que falta. Usado por clips.js y reelEditor.js.
 */
export async function fetchClipThumbnails(clipsList, sourceUrlInputId, onUpdate) {
    const pending = clipsList.filter(c => c.thumbnail === undefined);
    if (pending.length === 0) return;

    const cacheKey = state.currentData?.cache_key || "";
    const urlInput = document.getElementById(sourceUrlInputId);
    const url = (urlInput?.value || "").trim() || state.currentData?.source_url || "";
    if (!cacheKey && !url) {
        pending.forEach(c => { c.thumbnail = null; });
        return;
    }

    try {
        const res = await fetch(`${BACKEND_URL}/generate-thumbnails`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cache_key: cacheKey, url, clips: pending.map(c => ({ start: c.start })) }),
        });
        if (!res.ok) {
            pending.forEach(c => { c.thumbnail = null; });
            return;
        }
        const data = await res.json();
        pending.forEach((c, idx) => { c.thumbnail = data.thumbnails[idx] || null; });
    } catch (e) {
        pending.forEach(c => { c.thumbnail = null; });
    }
    if (onUpdate) onUpdate();
}
