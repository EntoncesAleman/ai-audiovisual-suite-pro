import { state } from '../state.js';
import { BACKEND_URL, PLATFORM_DATA, MAX_CLIPS_PER_EXPORT, STREAM_STALL_MS } from '../config.js';
import { escapeHtml, setExportProgress, resetExportProgress } from '../utils/dom.js';
import { tsToSeconds, secondsToTs } from '../utils/helpers.js';
import { resolveExportSource } from '../api/api.js';
import { authHeaders } from '../utils/storage.js';

function isVideoEnfoque(key) {
    if (!state.PROMPTS_LIBRARY) return false;
    return state.PROMPTS_LIBRARY.enfoques?.[key]?.categoria === "video";
}

// Iconos usados en botones cuya etiqueta cambia por JS (no se puede usar
// textContent ahí sin borrar el ícono - ver updateVideoPanel/toggleAiImport).
const ICON_FILM = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="18" rx="2"/><path d="M7 3v18M17 3v18M2 8h5M2 16h5M17 8h5M17 16h5"/></svg>';
const ICON_IMAGE = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>';
const ICON_INBOX = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/></svg>';
const ICON_CLOSE = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

export function updateVideoPanel() {
    const type = document.getElementById("promptType").value;
    const isVideo = isVideoEnfoque(type);
    const resultVisible = document.getElementById("resultBlock").style.display !== "none";
    const panel = document.getElementById("videoEditorPanel");
    if (!panel) return;

    const shouldShow = isVideo && resultVisible && !!state.currentData;
    panel.classList.toggle("active", shouldShow);

    if (shouldShow) {
        state.currentPlatformKey = type;
        const pdata = PLATFORM_DATA[type];
        if (pdata) {
            document.getElementById("platformBadge").textContent = pdata.label;
            document.getElementById("platformRatio").textContent = pdata.ratio;
            document.getElementById("platformRes").textContent = pdata.res;
            document.getElementById("platformDur").textContent = pdata.dur;

            const btn = document.getElementById("btnExportReel");
            if (pdata.isPlatesCarousel) {
                btn.innerHTML = `${ICON_IMAGE} Generar placas de texto (ZIP)`;
            } else if (pdata.isClipsCarousel) {
                btn.innerHTML = `${ICON_FILM} Generar clips 1:1 (ZIP)`;
            } else {
                btn.innerHTML = `${ICON_FILM} Generar ${escapeHtml(pdata.label)}`;
            }
        }
        const srcUrl = document.getElementById("clipSourceUrl").value || (state.currentData && state.currentData.source_url) || "";
        if (srcUrl) document.getElementById("reelSourceUrl").value = srcUrl;
    }
}

export function parseClipsForReel() {
    if (!state.originalTimeline) { alert("Primero procesá un video."); return; }
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;

    const blocks = state.originalTimeline.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean);
    const parsed = [];
    for (const block of blocks) {
        const tsMatch = block.match(/TIMESTAMP:\s*(\d{1,2}:\d{2}(?::\d{2})?)/i);
        const spMatch = block.match(/SPEAKER:\s*([^\n]+)/i);
        const dlMatch = block.match(/DIALOGUE:\s*([\s\S]+?)(?=\n[A-Z]+:|$)/i);
        if (!tsMatch) continue;
        const startTs = tsMatch[1].trim();
        const startSec = tsToSeconds(startTs);
        const endTs = secondsToTs(startSec + defDur);
        const speaker = spMatch ? spMatch[1].trim().substring(0, 30) : "";
        const dialogue = dlMatch ? dlMatch[1].trim().substring(0, 80) : "";
        const label = speaker ? `${speaker}: ${dialogue}` : dialogue;
        parsed.push({ start: startTs, end: endTs, label, selected: true });
    }
    if (parsed.length === 0) { alert("No se encontraron timestamps en el análisis."); return; }
    state.reelClipsList = parsed;
    renderReelClipsList();
}

export function renderReelClipsList() {
    const tbody = document.getElementById("reelClipsTableBody");
    const badge = document.getElementById("reelCountBadge");
    if (!tbody) return;
    const selected = state.reelClipsList.filter(c => c.selected).length;
    if (badge) badge.textContent = `${selected}/${state.reelClipsList.length} clips`;

    if (state.reelClipsList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="clip-empty">Extraé timestamps del análisis o agregá clips manualmente.</td></tr>';
        return;
    }
    tbody.innerHTML = state.reelClipsList.map((clip, i) => `
        <tr>
            <td><input type="checkbox" ${clip.selected ? "checked" : ""} onchange="toggleReelClip(${i}, this.checked)"></td>
            <td><input type="text" value="${escapeHtml(clip.start)}" onchange="updateReelClip(${i}, 'start', this.value)" style="width:68px;"></td>
            <td><input type="text" value="${escapeHtml(clip.end)}" onchange="updateReelClip(${i}, 'end', this.value)" style="width:68px;"></td>
            <td class="clip-label-cell"><span class="clip-label-text" title="${escapeHtml(clip.label)}">${escapeHtml(clip.label)}</span></td>
            <td><button class="btn-clip-remove" onclick="removeReelClip(${i})" title="Quitar">×</button></td>
        </tr>
    `).join("");
}

export function toggleReelClip(i, checked) {
    state.reelClipsList[i].selected = checked;
    const selected = state.reelClipsList.filter(c => c.selected).length;
    const badge = document.getElementById("reelCountBadge");
    if (badge) badge.textContent = `${selected}/${state.reelClipsList.length} clips`;
}

export function updateReelClip(i, field, value) { state.reelClipsList[i][field] = value.trim(); }
export function removeReelClip(i) { state.reelClipsList.splice(i, 1); renderReelClipsList(); }
export function selectAllReelClips(val) { state.reelClipsList.forEach(c => c.selected = val); renderReelClipsList(); }

export function toggleAiImport() {
    const body = document.getElementById("aiImportBody");
    const btn = document.getElementById("btnAiImport");
    const isOpen = body.classList.toggle("open");
    btn.classList.toggle("open", isOpen);
    btn.innerHTML = isOpen ? `${ICON_CLOSE} Cerrar importador` : `${ICON_INBOX} Importar respuesta de IA`;
}

export function importAiTimestamps() {
    const text = document.getElementById("aiResponseInput").value;
    const feedback = document.getElementById("aiImportFeedback");
    if (!text.trim()) { feedback.textContent = "⚠ Pegá la respuesta de la IA primero."; return; }

    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;

    const imported = [];

    const inicioPattern = /(?:⏱\s*)?Inicio:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;
    const finPattern    = /(?:⏱\s*)?Fin:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;

    const inicios = [...text.matchAll(inicioPattern)].map(m => m[1]);
    const fines   = [...text.matchAll(finPattern)].map(m => m[1]);

    const labelPattern = /(?:🎯|⭕|▶|🖼|🎵|🐦)\s*(?:Opción|Clip|Slide|Story|Short)\s*#?\d+[^\n]*/gi;
    const labels = [...text.matchAll(labelPattern)].map(m =>
        m[0].replace(/^[🎯⭕▶🖼🎵🐦]\s*/u, '').replace(/\s*—.*$/, '').trim()
    );

    if (inicios.length > 0) {
        for (let i = 0; i < inicios.length; i++) {
            const start = inicios[i];
            const end   = fines[i] || secondsToTs(tsToSeconds(start) + defDur);
            const label = labels[i] || `Clip importado ${i + 1}`;
            imported.push({ start, end, label, selected: true });
        }
    } else {
        const inlinePattern = /Inicio:\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[—–-]+\s*Fin:\s*(\d{1,2}:\d{2}(?::\d{2})?)/gi;
        const inlineMatches = [...text.matchAll(inlinePattern)];
        for (let i = 0; i < inlineMatches.length; i++) {
            imported.push({
                start: inlineMatches[i][1],
                end:   inlineMatches[i][2],
                label: labels[i] || `Clip importado ${i + 1}`,
                selected: true
            });
        }
    }

    if (imported.length === 0) {
        feedback.textContent = "❌ No se encontraron timestamps. La IA debe usar el formato ⏱ Inicio: MM:SS / ⏱ Fin: MM:SS";
        return;
    }

    state.reelClipsList = imported;
    renderReelClipsList();
    feedback.textContent = `✅ ${imported.length} clip${imported.length > 1 ? 's' : ''} importado${imported.length > 1 ? 's' : ''} correctamente.`;
    document.getElementById("aiResponseInput").value = "";
}

export function addReelClipManual() {
    const start = document.getElementById("newReelStart").value.trim();
    const end = document.getElementById("newReelEnd").value.trim();
    const label = document.getElementById("newReelLabel").value.trim();
    if (!start) { alert("Ingresá al menos el tiempo de inicio (MM:SS)."); return; }
    const pdata = state.currentPlatformKey ? PLATFORM_DATA[state.currentPlatformKey] : null;
    const defDur = pdata ? (parseInt(pdata.dur) || 30) : 30;
    const endFinal = end || secondsToTs(tsToSeconds(start) + defDur);
    state.reelClipsList.push({ start, end: endFinal, label, selected: true });
    document.getElementById("newReelStart").value = "";
    document.getElementById("newReelEnd").value = "";
    document.getElementById("newReelLabel").value = "";
    renderReelClipsList();
}

export async function startReelExport() {
    if (!state.currentPlatformKey) { alert("Seleccioná un enfoque de video primero."); return; }
    const selected = state.reelClipsList.filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip."); return; }

    const pdata = PLATFORM_DATA[state.currentPlatformKey];
    // Las placas de texto son solo imágenes (liviano); todo lo demás corta +
    // reencodea con ffmpeg, y muchos clips juntos se quedan sin memoria en
    // el free tier de Render (512MB) - ver MAX_CLIPS_PER_EXPORT.
    if (!pdata?.isPlatesCarousel && selected.length > MAX_CLIPS_PER_EXPORT) {
        alert(`Máximo ${MAX_CLIPS_PER_EXPORT} clips por exportación (seleccionaste ${selected.length}). Exportá en tandas de a ${MAX_CLIPS_PER_EXPORT} para no sobrecargar el servidor.`);
        return;
    }

    const statusEl = document.getElementById("reelExportStatus");
    const downloadBtn = document.getElementById("reelDownloadBtn");

    let source;
    try {
        source = await resolveExportSource("reelSourceUrl", "reelSourceFile", statusEl);
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        statusEl.textContent = "❌ Error subiendo el archivo: " + e.message;
        return;
    }
    if (!source) return;

    const isCarousel = pdata?.isCarousel;
    const endpoint = isCarousel ? `${BACKEND_URL}/export-carousel` : `${BACKEND_URL}/export-reel`;

    statusEl.className = "clip-export-status active";
    statusEl.textContent = "⏳ Iniciando exportación...";
    downloadBtn.className = "btn-reel-download";
    resetExportProgress('reelExport');
    setExportProgress('reelExport', 2);

    const clips = selected.map(c => ({ start: c.start, end: c.end, label: c.label }));

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
        const res = await fetch(endpoint, {
            method: "POST",
            headers: { ...authHeaders(), "Content-Type": "application/json" },
            body: JSON.stringify({ ...source, clips, platform: state.currentPlatformKey }),
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
                        setExportProgress('reelExport', payload.pct);
                    }
                    if (payload.stage === "error") {
                        statusEl.className = "clip-export-status active error";
                        statusEl.textContent = "❌ " + payload.message;
                        return;
                    }
                    if (payload.stage === "done") {
                        setExportProgress('reelExport', 100);
                        statusEl.textContent = "✅ " + payload.message;
                        downloadBtn.href = BACKEND_URL + payload.download_url;
                        downloadBtn.download = payload.filename;
                        downloadBtn.className = "btn-reel-download active";
                    } else {
                        statusEl.textContent = "⏳ " + payload.message;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        if (stalled) {
            statusEl.textContent = "❌ Se perdió la conexión con el servidor (sin respuesta por " + Math.round(STREAM_STALL_MS / 1000) + "s). Puede que el servidor haya seguido procesando igual: probá 'Generar' de nuevo, retoma desde donde quedó.";
        } else {
            statusEl.textContent = "❌ Error: " + e.message;
        }
    } finally {
        clearTimeout(watchdog);
    }
}

// Las filas de la tabla se generan dinámicamente vía innerHTML (arriba), así que
// sus onclick/onchange necesitan encontrar estas funciones en window.
window.toggleReelClip = toggleReelClip;
window.updateReelClip = updateReelClip;
window.removeReelClip = removeReelClip;
