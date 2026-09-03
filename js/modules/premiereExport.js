import { state } from '../state.js';
import { BACKEND_URL, STREAM_STALL_MS } from '../config.js';
import { setExportProgress, resetExportProgress, telemetryLog } from '../utils/dom.js';
import { tsToSeconds, buildSubtitleCuesForClip } from '../utils/helpers.js';
import { resolveExportSource } from '../api/api.js';
import { authHeaders } from '../utils/storage.js';

/**
 * Modal de opciones compartido entre las dos pestañas que exportan a
 * Premiere (Clip Editor y Editor de Video para Redes) - antes cada una
 * tenía su propia función que exportaba directo con lo que ya estuviera
 * tildado en el panel de subtítulos compartido; ahora el usuario elige
 * acá mismo, en el momento del export, sin tocar nada de otro lado.
 */
const CONTEXTS = {
    clips: {
        listKey: 'clipsList',
        urlInputId: 'clipSourceUrl', fileInputId: 'clipSourceFile',
        statusElId: 'clipExportStatus', downloadBtnId: 'clipDownloadBtn',
        progressPrefix: 'clipExport', downloadBtnClass: 'btn-clip-download',
    },
    reel: {
        listKey: 'reelClipsList',
        urlInputId: 'reelSourceUrl', fileInputId: 'reelSourceFile',
        statusElId: 'reelExportStatus', downloadBtnId: 'reelDownloadBtn',
        progressPrefix: 'reelExport', downloadBtnClass: 'btn-reel-download',
    },
};

let _pendingSource = null;

export function openPremiereOptions(source) {
    const ctx = CONTEXTS[source];
    if (!ctx) return;
    const selected = state[ctx.listKey].filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip para exportar."); return; }

    _pendingSource = source;
    document.getElementById('premiereSeqName').value = (state.currentData?.title || "AVSuite Export").slice(0, 60);
    document.getElementById('premiereIncludeSubtitles').checked = true;
    document.getElementById('premiereTrackMode').value = "same";
    document.getElementById('premiereOptionsClipCount').textContent =
        `${selected.length} clip${selected.length > 1 ? 's' : ''} seleccionado${selected.length > 1 ? 's' : ''}`;
    document.getElementById('premiereOptionsOverlay').classList.add('active');
}

export function closePremiereOptions() {
    document.getElementById('premiereOptionsOverlay').classList.remove('active');
    _pendingSource = null;
}

export async function confirmPremiereExport() {
    const source = _pendingSource;
    const ctx = CONTEXTS[source];
    if (!ctx) return;

    const sequenceName = document.getElementById('premiereSeqName').value.trim() || "AVSuite Export";
    const includeSubtitles = document.getElementById('premiereIncludeSubtitles').checked;
    const separateTracks = document.getElementById('premiereTrackMode').value === "separate";
    closePremiereOptions();
    await runPremiereExport(ctx, sequenceName, includeSubtitles, separateTracks);
}

async function runPremiereExport(ctx, sequenceName, includeSubtitles, separateTracks) {
    const selected = state[ctx.listKey].filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip para exportar."); return; }

    const statusEl = document.getElementById(ctx.statusElId);
    const downloadBtn = document.getElementById(ctx.downloadBtnId);

    let source;
    try {
        source = await resolveExportSource(ctx.urlInputId, ctx.fileInputId, statusEl);
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        statusEl.textContent = "❌ Error subiendo el archivo: " + e.message;
        return;
    }
    if (!source) return;

    statusEl.className = "clip-export-status active";
    statusEl.textContent = "⏳ Armando proyecto de Premiere...";
    downloadBtn.className = ctx.downloadBtnClass;
    resetExportProgress(ctx.progressPrefix);
    setExportProgress(ctx.progressPrefix, 2);
    telemetryLog('telemetry', `Iniciando export a Premiere (XML) - ${separateTracks ? 'canales separados' : 'mismo canal'}, subtítulos ${includeSubtitles ? 'sí' : 'no'}...`, 'uploading');

    const clips = selected.map(c => ({
        start: c.start, end: c.end, label: c.label,
        subtitles: includeSubtitles
            ? buildSubtitleCuesForClip(tsToSeconds(c.start), tsToSeconds(c.end), state.originalTimeline)
            : [],
    }));

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
        const res = await fetch(`${BACKEND_URL}/export-premiere-xml`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...source, clips, sequence_name: sequenceName, separate_tracks: separateTracks }),
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
                    if (typeof payload.pct === "number") setExportProgress(ctx.progressPrefix, payload.pct);
                    telemetryLog('telemetry', payload.message, payload.stage);
                    if (payload.stage === "error") {
                        statusEl.className = "clip-export-status active error";
                        statusEl.textContent = "❌ " + payload.message;
                        return;
                    }
                    if (payload.stage === "done") {
                        setExportProgress(ctx.progressPrefix, 100);
                        statusEl.textContent = "✅ " + payload.message;
                        downloadBtn.href = BACKEND_URL + payload.download_url;
                        downloadBtn.download = payload.filename;
                        downloadBtn.className = ctx.downloadBtnClass + " active";
                    } else {
                        statusEl.textContent = "⏳ " + payload.message;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        if (stalled) {
            statusEl.textContent = "❌ Se perdió la conexión con el servidor (sin respuesta por " + Math.round(STREAM_STALL_MS / 1000) + "s). Probá de nuevo en un rato.";
            telemetryLog('telemetry', statusEl.textContent, 'error');
        } else {
            statusEl.textContent = "❌ Error: " + e.message;
            telemetryLog('telemetry', statusEl.textContent, 'error');
        }
    } finally {
        clearTimeout(watchdog);
    }
}
