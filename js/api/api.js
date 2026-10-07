import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { authHeaders } from '../utils/storage.js';
import { telemetryLog } from '../utils/dom.js';
import { hasPreviewSource, loadRemoteSourcePreview, seekAndPlay } from '../modules/player.js';

/**
 * Descarga un archivo protegido de /exports/{filename} (o cualquier ruta que
 * exija X-API-Key) disparando un fetch con el header de auth, en vez de
 * dejar que el navegador navegue directo a un <a href>: un link plano NO
 * manda headers custom, así que desde que /exports/{filename} exige dueño
 * (ver ownership de exports en main.py) un click nativo siempre devolvía
 * 401/403 y el navegador lo mostraba como "El archivo no se encontraba
 * disponible en el sitio", sin ningún detalle del error real. Usado por los
 * botones "Descargar" de clips/reel/Premiere/voiceover.
 */
export async function downloadAuthenticated(url, filename) {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (e) { /* respuesta no-JSON, nos quedamos con el status */ }
        throw new Error(detail);
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename || '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
}

/**
 * Deja un botón/link de descarga (<a id=...>) listo: guarda la URL real
 * (BACKEND_URL + download_url) para mostrarla/usarla como fallback visual,
 * pero el click dispara downloadAuthenticated en vez de la navegación
 * nativa del <a href>. Centraliza el wiring que antes se repetía suelto en
 * cada módulo de export (clips/reel/Premiere/voiceover).
 */
export function wireDownloadButton(downloadBtn, url, filename) {
    downloadBtn.href = url;
    downloadBtn.download = filename || '';
    downloadBtn.onclick = (e) => {
        e.preventDefault();
        downloadAuthenticated(url, filename).catch((err) => {
            alert('No se pudo descargar el archivo: ' + err.message);
        });
    };
}

/**
 * Resuelve de dónde sale el video fuente para exportar. Orden de prioridad:
 * 1. cache_key del análisis actual (el server guardó el video, cero re-subida/descarga).
 * 2. URL pegada.
 * 3. Archivo local subido de nuevo (fallback si el cache ya no está).
 * Devuelve {cache_key}, {url} o {video_path}, o null si no hay ninguna
 * (y ya mostró el alert correspondiente).
 */
export async function resolveExportSource(urlInputId, fileInputId, statusEl) {
    const url = document.getElementById(urlInputId)?.value.trim() || state.currentData?.source_url || document.getElementById('streamUrl')?.value.trim() || '';
    const fileInput = document.getElementById(fileInputId);
    let file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;
    if (!file && !state.currentData?.cache_key) file = document.getElementById('localFile')?.files?.[0] || null;

    if (state.currentData && state.currentData.cache_key && !file) {
        // Mandamos la URL igual aunque haya cache_key: el disco de Render es
        // efímero, así que si el server se reinició desde que se analizó el
        // video, el cache del video ya no existe ahí aunque el frontend
        // todavía lo recuerde. El backend prueba cache primero y si no está
        // cae en descargar de la URL en vez de fallar con "falta URL".
        return { cache_key: state.currentData.cache_key, url };
    }

    if (!url && !file) {
        alert("Primero cargá el video en Fuente de video. Si abriste un proyecto guardado y el video ya no está disponible, volvé a subirlo allí.");
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
        return { asset_id: info.asset_id };
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
    const cacheKey = state.currentData?.cache_key || "";
    const urlInput = document.getElementById(sourceUrlInputId);
    const url = (urlInput?.value || "").trim() || state.currentData?.source_url || "";

    if (pending.length === 0) {
        // Igual intentamos cargar el mini-player si todavía no tiene fuente
        // (por ej. clips que ya tenían thumbnail de una sesión guardada).
        loadPreviewFromSourceIfNeeded(cacheKey, url);
        return;
    }

    if (!cacheKey && !url) {
        pending.forEach(c => { c.thumbnail = null; });
        return;
    }

    // Fuerza la descarga/cache del video (a diferencia de /generate-thumbnails,
    // que a propósito no lo hace) para que tanto las miniaturas como el
    // mini-player funcionen con fuentes de YouTube/Drive, no solo con
    // archivo local. Best-effort: si falla, seguimos igual con
    // /generate-thumbnails por si el video ya estaba cacheado de otra forma.
    const effectiveCacheKey = await loadPreviewFromSourceIfNeeded(cacheKey, url);

    try {
        const res = await fetch(`${BACKEND_URL}/generate-thumbnails`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cache_key: effectiveCacheKey || cacheKey, url, clips: pending.map(c => ({ start: c.start })) }),
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

/**
 * Si el mini-player todavía no tiene ningún video cargado, fuerza el cacheo
 * del video fuente (por cache_key o url) en el backend y lo trae como blob
 * para poder reproducirlo/saltar a cualquier punto ANTES de exportar -
 * mismo resultado que ya existía para archivos locales. Devuelve el
 * cache_key efectivo (útil para /generate-thumbnails) o "" si no se pudo.
 * Silencioso ante cualquier error: el flujo de siempre (recién ver el
 * preview al exportar) sigue funcionando igual como fallback.
 */
async function loadPreviewFromSourceIfNeeded(cacheKey, url) {
    if (hasPreviewSource() || (!cacheKey && !url)) return cacheKey;
    try {
        const ensureRes = await fetch(`${BACKEND_URL}/ensure-cached-video`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ cache_key: cacheKey, url }),
        });
        if (!ensureRes.ok) return cacheKey;
        const { cache_key: effectiveCacheKey } = await ensureRes.json();
        if (!effectiveCacheKey) return cacheKey;
        const videoRes = await fetch(`${BACKEND_URL}/cached-video/${effectiveCacheKey}`, { headers: authHeaders() });
        if (!videoRes.ok) return effectiveCacheKey;
        loadRemoteSourcePreview(await videoRes.blob());
        return effectiveCacheKey;
    } catch (e) {
        return cacheKey;
    }
}

/**
 * Como seekAndPlay (player.js), pero si el mini-player todavía no tiene
 * fuente y el análisis vino de una URL (YouTube/Drive, no archivo local),
 * primero intenta cachear/traer el video real antes de saltar - a
 * diferencia de un archivo local (que se carga solo con seleccionarlo, ver
 * loadLocalSourcePreview en app.js), un video por link recién se cacheaba
 * como side-effect de pedir miniaturas de clips - si todavía no había
 * clips generados, el mini-player quedaba sin fuente y clickear "play" en
 * la transcripción solo mostraba "subí un archivo local", aunque el video
 * SÍ viniera de una URL válida. A propósito sigue siendo perezoso (no
 * fuerza la descarga en cuanto termina el análisis) para no bajar el video
 * completo si la persona nunca llega a usar el mini-player.
 */
export async function playFromSource(startTs) {
    if (!hasPreviewSource()) {
        const cacheKey = state.currentData?.cache_key || "";
        const url = state.currentData?.source_url || "";
        if (cacheKey || url) {
            await loadPreviewFromSourceIfNeeded(cacheKey, url);
        }
    }
    seekAndPlay(startTs);
}
