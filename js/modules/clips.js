import { state } from '../state.js';
import { BACKEND_URL, STREAM_STALL_MS } from '../config.js';
import { escapeHtml, setExportProgress, resetExportProgress, telemetryLog, showExportPreview, resetExportPreview } from '../utils/dom.js';
import { tsToSeconds, secondsToTs, parseAiTimestampsText, buildSubtitleCuesForClip } from '../utils/helpers.js';
import { resolveExportSource } from '../api/api.js';
import { authHeaders } from '../utils/storage.js';
import { seekAndPlay } from './player.js';
import { subtitlesEnabled, getSubtitleStyle } from './subtitleStyle.js';

// ============================================================
// EXPORTACIÓN DE CLIPS
// ============================================================
// Todo vive siempre en pantalla (no hay pasos): parseClipsFromTimeline()
// se llama tanto a mano (botón "Extraer timestamps") como automáticamente
// cada vez que termina un análisis (ver sessions.js) - en el segundo caso
// silent=true para no interrumpir con un alert si por algún motivo el
// texto no tiene bloques TIMESTAMP todavía.

export function parseClipsFromTimeline(silent = false) {
    if (!state.originalTimeline) {
        if (!silent) alert("Primero procesá un video.");
        return;
    }
    const dur = parseInt(document.getElementById('clipDefaultDuration').value) || 30;
    const blocks = state.originalTimeline.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean);
    const parsed = [];

    for (const block of blocks) {
        const tsMatch = block.match(/TIMESTAMP:\s*(\d{1,2}:\d{2}(?::\d{2})?)/i);
        const spMatch = block.match(/SPEAKER:\s*([^\n]+)/i);
        const dlMatch = block.match(/DIALOGUE:\s*([\s\S]+?)(?=\n[A-Z]+:|$)/i);
        if (!tsMatch) continue;
        const startTs = tsMatch[1].trim();
        const startSec = tsToSeconds(startTs);
        const endTs = secondsToTs(startSec + dur);
        const speaker = spMatch ? spMatch[1].trim().substring(0, 25) : "";
        const dialogue = dlMatch ? dlMatch[1].trim().substring(0, 60) : "";
        const label = speaker ? `${speaker}: ${dialogue}` : dialogue;
        parsed.push({ start: startTs, end: endTs, label: label, selected: true });
    }

    if (parsed.length === 0) {
        if (!silent) alert("No se encontraron timestamps en el análisis. Asegurate de haber procesado el video primero.");
        return;
    }
    state.clipsList = parsed;
    renderClipsList();
}

export function renderClipsList() {
    const grid = document.getElementById('clipsCardGrid');
    const badge = document.getElementById('clipCountBadge');
    const selected = state.clipsList.filter(c => c.selected).length;
    badge.textContent = `${selected}/${state.clipsList.length} clips`;

    if (state.clipsList.length === 0) {
        grid.innerHTML = '<div class="clip-empty">Usá "⚡ Generar Clips con IA" (arriba) o "Extraer timestamps del análisis".</div>';
        return;
    }

    grid.innerHTML = state.clipsList.map((clip, i) => `
        <div class="clip-card">
            <div class="clip-card-thumb">
                <button class="clip-card-play" onclick="playClip(${i})" title="Reproducir desde acá"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7Z"/></svg></button>
            </div>
            <div class="clip-card-body">
                <div class="clip-card-top">
                    <input type="checkbox" ${clip.selected ? "checked" : ""} onchange="toggleClipSelection(${i}, this.checked)" title="Incluir en la exportación">
                    <input type="text" class="clip-card-title" value="${escapeHtml(clip.label)}" onchange="updateClip(${i}, 'label', this.value)" placeholder="Descripción del clip">
                    <button class="clip-card-star ${clip.favorite ? 'active' : ''}" onclick="toggleClipFavorite(${i})" title="Marcar como favorito">★</button>
                    <button class="btn-clip-remove" onclick="removeClip(${i})" title="Quitar">×</button>
                </div>
                <div class="clip-card-times">
                    <input type="text" value="${escapeHtml(clip.start)}" onchange="updateClip(${i}, 'start', this.value)" title="Inicio (In)">
                    <span>→</span>
                    <input type="text" value="${escapeHtml(clip.end)}" onchange="updateClip(${i}, 'end', this.value)" title="Fin (Out)">
                </div>
            </div>
        </div>
    `).join('');
}

export function toggleClipFavorite(i) {
    state.clipsList[i].favorite = !state.clipsList[i].favorite;
    renderClipsList();
}

export function playClip(i) {
    seekAndPlay(state.clipsList[i].start);
}

export function toggleClipSelection(i, checked) {
    state.clipsList[i].selected = checked;
    const selected = state.clipsList.filter(c => c.selected).length;
    document.getElementById('clipCountBadge').textContent = `${selected}/${state.clipsList.length} clips`;
}

export function updateClip(i, field, value) {
    state.clipsList[i][field] = value.trim();
}

export function removeClip(i) {
    state.clipsList.splice(i, 1);
    renderClipsList();
}

export function selectAllClips(val) {
    state.clipsList.forEach(c => c.selected = val);
    renderClipsList();
}

export function addClipManual() {
    const start = document.getElementById('newClipStart').value.trim();
    const end = document.getElementById('newClipEnd').value.trim();
    const label = document.getElementById('newClipLabel').value.trim();
    if (!start) { alert("Ingresá al menos el tiempo de inicio (MM:SS)."); return; }
    const startSec = tsToSeconds(start);
    const endFinal = end || secondsToTs(startSec + (parseInt(document.getElementById('clipDefaultDuration').value) || 30));
    state.clipsList.push({ start, end: endFinal, label, selected: true });
    document.getElementById('newClipStart').value = "";
    document.getElementById('newClipEnd').value = "";
    document.getElementById('newClipLabel').value = "";
    renderClipsList();
}

export function toggleClipAiImport() {
    const body = document.getElementById("clipAiImportBody");
    const btn = document.getElementById("btnClipAiImport");
    const isOpen = body.classList.toggle("open");
    btn.classList.toggle("open", isOpen);
    btn.textContent = isOpen ? "✕ Cerrar" : "Ver / pegar respuesta de Gemini manualmente";
}

export function importClipAiTimestamps() {
    const text = document.getElementById("clipAiResponseInput").value;
    const feedback = document.getElementById("clipAiImportFeedback");
    if (!text.trim()) { feedback.textContent = "⚠ Pegá la respuesta de la IA primero."; return; }

    const dur = parseInt(document.getElementById('clipDefaultDuration').value) || 30;
    const imported = parseAiTimestampsText(text, dur);

    if (imported.length === 0) {
        feedback.textContent = "❌ No se encontraron timestamps. La IA debe usar el formato ⏱ Inicio: MM:SS / ⏱ Fin: MM:SS";
        return;
    }

    state.clipsList = imported;
    renderClipsList();
    feedback.textContent = `✅ ${imported.length} clip${imported.length > 1 ? 's' : ''} importado${imported.length > 1 ? 's' : ''} correctamente.`;
    document.getElementById("clipAiResponseInput").value = "";
}

/**
 * Reemplaza el paso de copiar el prompt a otra IA (ChatGPT/Claude/Gemini) y
 * pegar la respuesta acá a mano: le pide directamente a Gemini (el mismo
 * motor que ya usa la app) que resuelva el prompt actual del generador —
 * predefinido o libre — y carga los clips resultantes en esta tabla, ya con
 * los timestamps listos. Sigue estando disponible el camino manual
 * ("Importar respuesta de IA") por si se prefiere usar otra IA.
 */
export async function generateClipsWithAI() {
    const promptText = document.getElementById('promptOutput')?.innerText || "";
    const feedback = document.getElementById('clipAiImportFeedback');
    if (!state.currentData || promptText.includes("Carga un análisis")) {
        alert("Primero procesá un video (arriba) para poder generar clips.");
        return;
    }
    const btn = document.getElementById('btnGenerateActiveClips');
    if (btn) { btn.disabled = true; btn.dataset.origHtml = btn.innerHTML; btn.textContent = "⏳ Generando con Gemini..."; }
    if (feedback) feedback.textContent = "⏳ Generando con Gemini (puede tardar unos segundos)...";

    try {
        const res = await fetch(`${BACKEND_URL}/generate-clip-suggestions`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

        const dur = parseInt(document.getElementById('clipDefaultDuration').value) || 30;
        const imported = parseAiTimestampsText(data.text, dur);

        if (imported.length === 0) {
            if (feedback) feedback.textContent = "⚠ Gemini respondió pero no encontré timestamps en el formato esperado. Revisá la respuesta completa abajo (se pegó en el importador manual).";
            document.getElementById('clipAiResponseInput').value = data.text;
            const body = document.getElementById('clipAiImportBody');
            if (body && !body.classList.contains('open')) toggleClipAiImport();
            return;
        }

        state.clipsList = imported;
        renderClipsList();
        const engineLabel = data.engine === "groq" ? "Groq (respaldo, Gemini no estaba disponible)" : "Gemini";
        if (feedback) feedback.textContent = `✅ ${imported.length} clip${imported.length > 1 ? 's' : ''} generado${imported.length > 1 ? 's' : ''} e importado${imported.length > 1 ? 's' : ''} directo con ${engineLabel}, sin pasar por otra IA.`;
    } catch (e) {
        if (feedback) feedback.textContent = "❌ Error generando con Gemini: " + e.message;
    } finally {
        if (btn) { btn.disabled = false; if (btn.dataset.origHtml) btn.innerHTML = btn.dataset.origHtml; }
    }
}

/** Botón "📥 Descargar ZIP (Todos)": selecciona todos los clips y exporta de una. */
export async function exportAllClips() {
    selectAllClips(true);
    await startClipExport();
}

export async function startClipExport() {
    const selected = state.clipsList.filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip para exportar."); return; }

    const statusEl = document.getElementById('clipExportStatus');
    const downloadBtn = document.getElementById('clipDownloadBtn');

    let source;
    try {
        source = await resolveExportSource('clipSourceUrl', 'clipSourceFile', statusEl);
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        statusEl.textContent = "❌ Error subiendo el archivo: " + e.message;
        return;
    }
    if (!source) return;

    statusEl.className = "clip-export-status active";
    statusEl.textContent = "⏳ Iniciando exportación...";
    downloadBtn.className = "btn-clip-download";
    resetExportProgress('clipExport');
    setExportProgress('clipExport', 2);
    resetExportPreview('previewVideo');
    telemetryLog('telemetry', 'Iniciando exportación de clips...', 'uploading');

    const wantsSubtitles = subtitlesEnabled();
    const clips = selected.map(c => ({
        start: c.start, end: c.end, label: c.label,
        subtitles: wantsSubtitles
            ? buildSubtitleCuesForClip(tsToSeconds(c.start), tsToSeconds(c.end), state.originalTimeline)
            : [],
    }));
    const subtitleStyle = wantsSubtitles ? getSubtitleStyle() : null;

    // Watchdog: si no llega ningún byte en STREAM_STALL_MS, algo se colgó
    // (conexión cortada sin que el navegador se entere) - abortamos y avisamos
    // en vez de dejar la barra de progreso congelada para siempre.
    const controller = new AbortController();
    let stalled = false;
    let watchdog = setTimeout(() => { stalled = true; controller.abort(); }, STREAM_STALL_MS);
    const resetWatchdog = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => { stalled = true; controller.abort(); }, STREAM_STALL_MS);
    };

    try {
        const res = await fetch(`${BACKEND_URL}/export-clips`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...source, clips, subtitle_style: subtitleStyle }),
            signal: controller.signal
        });
        if (!res.ok || !res.body) throw new Error("Sin respuesta del servidor.");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            resetWatchdog();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith("data:")) continue;
                try {
                    const payload = JSON.parse(line.slice(5).trim());
                    if (typeof payload.pct === "number") {
                        setExportProgress('clipExport', payload.pct);
                    }
                    telemetryLog('telemetry', payload.message, payload.stage);
                    if (payload.stage === "error") {
                        statusEl.className = "clip-export-status active error";
                        statusEl.textContent = "❌ " + payload.message;
                        return;
                    }
                    if (payload.stage === "done") {
                        setExportProgress('clipExport', 100);
                        statusEl.textContent = "✅ " + payload.message;
                        downloadBtn.href = BACKEND_URL + payload.download_url;
                        downloadBtn.download = payload.filename;
                        downloadBtn.className = "btn-clip-download active";
                        showExportPreview('previewVideo', payload, downloadBtn.href);
                    } else {
                        statusEl.textContent = "⏳ " + payload.message;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        if (stalled) {
            statusEl.textContent = "❌ Se perdió la conexión con el servidor (sin respuesta por " + Math.round(STREAM_STALL_MS / 1000) + "s). Puede que el servidor haya seguido cortando clips igual: probá 'Generar' de nuevo, retoma desde donde quedó.";
            telemetryLog('telemetry', statusEl.textContent, 'error');
        } else {
            statusEl.textContent = "❌ Error: " + e.message;
            telemetryLog('telemetry', statusEl.textContent, 'error');
        }
    } finally {
        clearTimeout(watchdog);
    }
}

/**
 * El panel "Generar y Exportar Clips" tiene dos pestañas del lado del
 * resultado: clips simples (tamaño original) y video para redes (recorte
 * a formato de plataforma). Solo una está visible a la vez - "Generar
 * Clips con IA" (generateActiveClipsWithAI en app.js) llena la que esté activa.
 */
export function switchClipEditorTab(tab) {
    document.querySelectorAll('.clip-editor-tab-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    document.getElementById('clipEditorTabSimple').classList.toggle('active', tab === 'simple');
    document.getElementById('clipEditorTabSocial').classList.toggle('active', tab === 'social');
}

// Las filas de la tabla de clips se generan dinámicamente vía innerHTML (arriba),
// así que sus onclick/onchange necesitan encontrar estas funciones en window.
window.toggleClipSelection = toggleClipSelection;
window.updateClip = updateClip;
window.removeClip = removeClip;
window.toggleClipFavorite = toggleClipFavorite;
window.playClip = playClip;
