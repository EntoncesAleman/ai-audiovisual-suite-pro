import { durableJobFetch } from '../api/jobs.js';
import { state } from '../state.js';
import { BACKEND_URL, STREAM_STALL_MS } from '../config.js';
import { setExportProgress, resetExportProgress, telemetryLog } from '../utils/dom.js';
import { tsToSeconds, buildSubtitleCuesForClip } from '../utils/helpers.js';
import { resolveExportSource, wireDownloadButton } from '../api/api.js';
import { authHeaders } from '../utils/storage.js';
import { isPro } from './auth.js';

/**
 * Card standalone de "Exportar a Premiere" (debajo de "Metraje Escaneado
 * con Éxito"), separada de Clips Inteligentes - la fuente de clips (Clip
 * Editor o Editor de Video para Redes) se elige acá mismo con un selector,
 * en vez de tener un botón de export por pestaña.
 */
const CLIP_SOURCES = {
    clips: { listKey: 'clipsList', urlInputId: 'clipSourceUrl', fileInputId: 'clipSourceFile' },
    reel: { listKey: 'reelClipsList', urlInputId: 'reelSourceUrl', fileInputId: 'reelSourceFile' },
};

export function updatePremiereClipCount() {
    const source = document.getElementById('premiereClipSource').value;
    const ctx = CLIP_SOURCES[source];
    const countEl = document.getElementById('premiereOptionsClipCount');
    if (!ctx || !countEl) return;
    const selected = state[ctx.listKey].filter(c => c.selected).length;
    countEl.textContent = `${selected} clip${selected !== 1 ? 's' : ''} seleccionado${selected !== 1 ? 's' : ''}`;
}

export async function startPremiereExport() {
    if (!isPro()) { alert('Exportar a Premiere (XML) es una función exclusiva del plan PRO. Pedile a un administrador que active tu cuenta en PRO.'); return; }
    const source = document.getElementById('premiereClipSource').value;
    const ctx = CLIP_SOURCES[source];
    if (!ctx) return;

    const [targetWidth, targetHeight] = document.getElementById('premiereAspectRatio').value.split('x');
    const options = {
        sequenceName: document.getElementById('premiereSeqName').value.trim() || "AVSuite Export",
        includeSubtitles: document.getElementById('premiereIncludeSubtitles').checked,
        separateTracks: document.getElementById('premiereTrackMode').value === "separate",
        videoTrackName: document.getElementById('premiereVideoTrackName').value.trim(),
        audioTrackName: document.getElementById('premiereAudioTrackName').value.trim(),
        organizeInBin: document.getElementById('premiereOrganizeInBin').checked,
        handleSeconds: parseFloat(document.getElementById('premiereHandleSeconds').value) || 0,
        clipOrder: document.getElementById('premiereClipOrder').value,
        targetWidth: targetWidth ? parseInt(targetWidth) : 0,
        targetHeight: targetHeight ? parseInt(targetHeight) : 0,
        includeCompanion: document.getElementById('premiereIncludeCompanion').checked,
        includeSrt: document.getElementById('premiereIncludeSrt').checked,
        multipleSequences: document.getElementById('premiereMultipleSequences').checked,
    };
    await runPremiereExport(ctx, options);
}

async function runPremiereExport(ctx, options) {
    let selected = state[ctx.listKey].filter(c => c.selected);
    if (selected.length === 0) { alert("Seleccioná al menos un clip para exportar (en Clip Editor o Editor de Video para Redes, según lo que hayas elegido arriba)."); return; }
    if (options.clipOrder === "timestamp") {
        selected = [...selected].sort((a, b) => tsToSeconds(a.start) - tsToSeconds(b.start));
    }

    const statusEl = document.getElementById('premiereExportStatus');
    const downloadBtn = document.getElementById('premiereDownloadBtn');

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
    downloadBtn.className = "btn-clip-download";
    resetExportProgress('premiereExport');
    setExportProgress('premiereExport', 2);
    telemetryLog('telemetry', `Iniciando export a Premiere (XML) - ${options.separateTracks ? 'canales separados' : 'mismo canal'}, subtítulos ${options.includeSubtitles ? 'sí' : 'no'}...`, 'uploading');

    const clips = selected.map(c => ({
        start: c.start, end: c.end, label: c.label,
        subtitles: options.includeSubtitles
            ? (c.subtitles || buildSubtitleCuesForClip(tsToSeconds(c.start), tsToSeconds(c.end), state.originalTimeline))
            : [],
        transition_out: c.transitionOut || "none",
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
        const res = await durableJobFetch(`${BACKEND_URL}/export-premiere-xml`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...source, clips,
                sequence_name: options.sequenceName,
                separate_tracks: options.separateTracks,
                video_track_name: options.videoTrackName,
                audio_track_name: options.audioTrackName,
                organize_in_bin: options.organizeInBin,
                handle_seconds: options.handleSeconds,
                target_width: options.targetWidth,
                target_height: options.targetHeight,
                include_companion: options.includeCompanion,
                include_srt: options.includeSrt,
                multiple_sequences: options.multipleSequences,
            }),
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
                    if (typeof payload.pct === "number") setExportProgress('premiereExport', payload.pct);
                    telemetryLog('telemetry', payload.message, payload.stage);
                    if (payload.stage === "error") {
                        statusEl.className = "clip-export-status active error";
                        statusEl.textContent = "❌ " + payload.message;
                        return;
                    }
                    if (payload.stage === "done") {
                        setExportProgress('premiereExport', 100);
                        statusEl.textContent = "✅ " + payload.message;
                        wireDownloadButton(downloadBtn, BACKEND_URL + payload.download_url, payload.filename);
                        downloadBtn.className = "btn-clip-download active";
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
