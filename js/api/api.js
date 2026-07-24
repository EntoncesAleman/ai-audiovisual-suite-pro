import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';

/**
 * Resuelve de dónde sale el video fuente para exportar. Orden de prioridad:
 * 1. cache_key del análisis actual (el server guardó el video, cero re-subida/descarga).
 * 2. URL pegada.
 * 3. Archivo local subido de nuevo (fallback si el cache ya no está).
 * Devuelve {cache_key}, {url} o {video_path}, o null si no hay ninguna
 * (y ya mostró el alert correspondiente).
 */
export async function resolveExportSource(urlInputId, fileInputId, statusEl) {
    if (state.currentData && state.currentData.cache_key) {
        return { cache_key: state.currentData.cache_key };
    }

    const url = document.getElementById(urlInputId).value.trim();
    const fileInput = document.getElementById(fileInputId);
    const file = fileInput && fileInput.files.length > 0 ? fileInput.files[0] : null;

    if (!url && !file) {
        alert("Pegá la URL del video fuente o seleccioná el archivo local antes de exportar.");
        return null;
    }
    if (file) {
        if (statusEl) {
            statusEl.className = "clip-export-status active";
            statusEl.textContent = "⏳ Subiendo archivo local...";
        }
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(`${BACKEND_URL}/inspect-file`, { method: "POST", body: formData });
        if (!res.ok) throw new Error("No se pudo subir el archivo (HTTP " + res.status + ")");
        const info = await res.json();
        return { video_path: info.temp_path };
    }
    return { url };
}
