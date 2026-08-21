import { BACKEND_URL, STREAM_STALL_MS } from '../config.js';
import { state } from '../state.js';
import { showLoader, updateProgress } from '../modules/loader.js';
import { saveSession } from '../modules/sessions.js';
import { authHeaders } from '../utils/storage.js';
import { setTelemetryMetrics } from '../utils/dom.js';

// ============================================================
// ANÁLISIS (con streaming de progreso)
// ============================================================

// "auto" (Gemini + Groq de respaldo) | "gemini" | "groq" — elegido en el selector del panel de ingreso.
export function getSelectedEngine() {
    const el = document.getElementById('transcriptEngine');
    return el ? el.value : "auto";
}

const ENGINE_META = {
    auto:   { label: "Auto (Gemini + Groq)", diarization: "Real (Gemini)" },
    gemini: { label: "Only Gemini",          diarization: "Real (Gemini)" },
    groq:   { label: "Only Groq",            diarization: "Estimada (sin diarización real)" },
};

/**
 * Manejador único del botón "START ANALYSIS": decide solo si hay que
 * procesar el archivo local elegido o el link pegado, según lo que haya
 * cargado la persona (antes eran dos botones separados).
 */
export function startAnalysis() {
    const fileInput = document.getElementById('localFile');
    if (fileInput && fileInput.files.length > 0) {
        analyzeLocalFile();
    } else if (document.getElementById('streamUrl').value.trim()) {
        analyzeUrlStream();
    } else {
        alert("Pegá un link o subí un archivo local primero.");
    }
}

function updateEngineMetrics(inputLabel) {
    const meta = ENGINE_META[getSelectedEngine()] || ENGINE_META.auto;
    state.lastEngineLabel = meta.label;
    state.lastInputLabel = inputLabel;
    state.lastDiarizationLabel = meta.diarization;
    setTelemetryMetrics({ engine: meta.label, input: inputLabel, duration: "—", diarization: meta.diarization });
}

export async function analyzeUrlStream() {
    const urlInput = document.getElementById('streamUrl').value.trim();
    if (!urlInput) return alert("Pega un link primero.");
    state._pendingSourceUrl = urlInput;  // se adjunta al resultado al guardar la sesión
    updateEngineMetrics(urlInput.length > 40 ? urlInput.slice(0, 40) + "…" : urlInput);
    showLoader(true);
    try {
        await streamingFetch(`${BACKEND_URL}/analyze-url-stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: urlInput, engine: getSelectedEngine() })
        });
    } catch (e) {
        if (e.name === 'AbortError' && !state._lastStreamStalled) {
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
        if (state._lastStreamStalled) {
            alert(`Se perdió la conexión con el servidor (sin respuesta por ${Math.round(STREAM_STALL_MS / 1000)}s). El servidor puede haber seguido trabajando igual: reintentá 'Procesar Enlace' en un rato.`);
        } else {
            alert("Se perdió la conexión con el servidor durante el análisis. No se perdió el link, pero hay que reintentar 'Procesar Enlace'.");
        }
    } finally {
        showLoader(false);
    }
}

/**
 * Sube el archivo local y lo procesa directo: el backend siempre extrae
 * solo el audio antes de transcribir (menos tokens/tiempo, nunca sube el
 * video entero a Gemini/Groq), así que no hace falta preguntarle nada al
 * usuario antes de arrancar.
 */
export async function analyzeLocalFile() {
    const fileInput = document.getElementById('localFile');
    if (fileInput.files.length === 0) return alert("Selecciona un archivo de audio o video local.");
    updateEngineMetrics(fileInput.files[0].name);
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
        if (e.name === 'AbortError' && !state._lastStreamStalled) {
            console.log("Análisis detenido por el usuario.");
            return;
        }
        console.error("Streaming falló:", e);
        if (state._lastStreamStalled) {
            alert(`Se perdió la conexión con el servidor (sin respuesta por ${Math.round(STREAM_STALL_MS / 1000)}s). El servidor puede haber seguido trabajando igual: reintentá en un rato.`);
        } else {
            alert("Se perdió la conexión con el servidor durante el análisis. Volvé a subir el archivo para reintentar.");
        }
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
    state._lastStreamStalled = false;
    // Watchdog: si no llega ningún byte en STREAM_STALL_MS, la conexión se
    // colgó (el backend manda un keep-alive cada 20s en los pasos largos) -
    // abortamos y marcamos el motivo para que el caller avise en vez de
    // dejar la barra de progreso congelada para siempre.
    let watchdog = setTimeout(() => {
        state._lastStreamStalled = true;
        state.currentAbortController.abort();
    }, STREAM_STALL_MS);
    const resetWatchdog = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => {
            state._lastStreamStalled = true;
            state.currentAbortController.abort();
        }, STREAM_STALL_MS);
    };
    try {
        const res = await fetch(url, {
            ...opts,
            headers: { ...authHeaders(), ...(opts.headers || {}) },
            signal: state.currentAbortController.signal
        });
        if (!res.ok || !res.body) throw new Error("Servidor sin respuesta streaming.");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalResult = null;

        while (true) {
            const { done, value } = await reader.read();
            resetWatchdog();
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
        clearTimeout(watchdog);
        state.currentAbortController = null;
    }
}
