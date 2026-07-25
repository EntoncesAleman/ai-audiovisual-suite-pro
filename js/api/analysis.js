import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { showLoader, updateProgress } from '../modules/loader.js';
import { saveSession } from '../modules/sessions.js';
import { showInspectionModal } from '../modules/modal.js';

// ============================================================
// ANÁLISIS (con streaming de progreso)
// ============================================================

// "auto" (Gemini + Groq de respaldo) | "gemini" | "groq" — elegido en el selector del panel de ingreso.
export function getSelectedEngine() {
    const el = document.getElementById('transcriptEngine');
    return el ? el.value : "auto";
}

export async function analyzeUrlStream() {
    const urlInput = document.getElementById('streamUrl').value.trim();
    if (!urlInput) return alert("Pega un link primero.");
    state._pendingSourceUrl = urlInput;  // se adjunta al resultado al guardar la sesión
    showLoader(true);
    try {
        await streamingFetch(`${BACKEND_URL}/analyze-url-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: urlInput, engine: getSelectedEngine() })
        });
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log("Análisis detenido por el usuario.");
            return;
        }
        // Antes acá se reintentaba todo de cero contra el endpoint clásico
        // sin avisar nada: si la conexión se cortaba a mitad de un análisis
        // largo (proxy matando la conexión, server reiniciando, etc.) el
        // usuario perdía todo el progreso sin enterarse de qué pasó y
        // arrancaba una descarga+transcripción entera de nuevo. Mejor
        // avisar claro y dejar que decida si reintenta.
        console.error("Streaming falló:", e);
        alert("Se perdió la conexión con el servidor durante el análisis. No se perdió el link, pero hay que reintentar 'Procesar Enlace'.");
    } finally {
        showLoader(false);
    }
}

export async function analyzeLocalFile() {
    const fileInput = document.getElementById('localFile');
    if (fileInput.files.length === 0) return alert("Selecciona un archivo de audio o video local.");
    const file = fileInput.files[0];

    // PASO 1: Inspeccionar el archivo antes de procesar
    showLoader(true);
    updateProgress("uploading", "Inspeccionando archivo antes de procesar...");

    const formData = new FormData();
    formData.append("file", file);
    let inspection;
    try {
        const res = await fetch(`${BACKEND_URL}/inspect-file`, { method: 'POST', body: formData });
        if (!res.ok) throw new Error("Inspección falló (HTTP " + res.status + ")");
        inspection = await res.json();
    } catch (e) {
        showLoader(false);
        // Si la inspección falla (por ejemplo ffmpeg no instalado),
        // hacemos fallback al flujo clásico
        console.warn("Inspección no disponible, procesando directo:", e);
        return analyzeLocalFileDirect();
    }
    showLoader(false);

    // PASO 2: Mostrar el modal con la info y dejar que el usuario decida
    showInspectionModal(inspection);
}

/**
 * Flujo clásico (sin inspección): se ejecuta como fallback si la
 * inspección no está disponible (típicamente porque ffprobe no está instalado).
 */
export async function analyzeLocalFileDirect() {
    const fileInput = document.getElementById('localFile');
    if (fileInput.files.length === 0) return;
    showLoader(true);
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("engine", getSelectedEngine());
    try {
        await streamingFetch(`${BACKEND_URL}/analyze-video-stream`, {
            method: 'POST',
            body: formData
        });
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log("Análisis detenido por el usuario.");
            return;
        }
        console.error("Streaming falló:", e);
        alert("Se perdió la conexión con el servidor durante el análisis. Volvé a subir el archivo para reintentar.");
    } finally {
        showLoader(false);
    }
}

export function stopCurrentAnalysis() {
    if (state.currentAbortController) {
        state.currentAbortController.abort();
    }
}

// Cliente SSE básico sobre fetch (lee chunks line by line)
export async function streamingFetch(url, opts) {
    state.currentAbortController = new AbortController();
    try {
        const res = await fetch(url, { ...opts, signal: state.currentAbortController.signal });
        if (!res.ok || !res.body) throw new Error("Servidor sin respuesta streaming.");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalResult = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data:")) continue;
                const json = line.slice(5).trim();
                if (!json) continue;
                try {
                    const payload = JSON.parse(json);
                    if (payload.stage === "error") {
                        alert("Error: " + payload.message);
                        return;
                    }
                    updateProgress(payload.stage, payload.message);
                    if (payload.result) finalResult = payload.result;
                } catch (err) {
                    console.warn("Línea SSE inválida:", json);
                }
            }
        }

        if (finalResult) saveSession(finalResult);
    } finally {
        state.currentAbortController = null;
    }
}
