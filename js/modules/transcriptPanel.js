import { state } from '../state.js';
import { escapeHtml } from '../utils/dom.js';
import { parseTimelineToSegments, tsToSeconds, estimateDurationSeconds } from '../utils/helpers.js';
import { playFromSource } from '../api/api.js';
import { generateIAPrompt } from './prompts.js';
import { getSessions, setSessions } from '../utils/storage.js';

// Paleta fija por orden de primera aparición del hablante - se recicla si
// hay más de 4 (poco común, pero no debe romperse).
const SPEAKER_PALETTE = ['var(--accent-cyan)', 'var(--accent-green)', 'var(--accent-coral)', 'var(--accent-purple)'];
let speakerColorMap = {};

function colorForSpeaker(speaker) {
    const key = speaker || "—";
    if (!(key in speakerColorMap)) {
        speakerColorMap[key] = SPEAKER_PALETTE[Object.keys(speakerColorMap).length % SPEAKER_PALETTE.length];
    }
    return speakerColorMap[key];
}

let activeView = 'dialogue';
let lastTotalSeconds = 0;

/** Sincroniza la aguja del speech map con el tiempo del mini-player, si tiene fuente cargada. */
export function initSpeechMapSync() {
    const video = document.getElementById('previewVideo');
    if (!video) return;
    video.addEventListener('timeupdate', () => {
        if (lastTotalSeconds > 0) updateSpeechMapNeedle(video.currentTime, lastTotalSeconds);
    });
}

export function renderInteractiveTranscript() {
    speakerColorMap = {};
    const segments = parseTimelineToSegments(state.originalTimeline).filter(s => s.timestamp);
    renderSpeechMap(segments);
    renderTranscriptList(segments);
}

function renderSpeechMap(segments) {
    const track = document.getElementById('speechMapTrack');
    const legend = document.getElementById('speechMapLegend');
    if (!track) return;

    if (segments.length === 0) {
        track.innerHTML = '<div class="speech-map-empty">Procesá un video para ver el mapa de hablantes.</div>';
        if (legend) legend.innerHTML = '';
        return;
    }

    const total = estimateDurationSeconds(state.originalTimeline);
    lastTotalSeconds = total;
    const bars = segments.map((s, i) => {
        const startSec = tsToSeconds(s.timestamp);
        const nextSec = i < segments.length - 1 ? tsToSeconds(segments[i + 1].timestamp) : total;
        const startPct = total > 0 ? (startSec / total) * 100 : 0;
        const widthPct = total > 0 ? Math.max(((nextSec - startSec) / total) * 100, 0.6) : 0;
        return `<div class="speech-map-bar" style="left:${startPct}%;width:${widthPct}%;background:${colorForSpeaker(s.speaker)};" title="${escapeHtml(s.speaker || 'Sin identificar')} · ${escapeHtml(s.timestamp)}" data-seek="${escapeHtml(s.timestamp)}"></div>`;
    }).join('');

    track.innerHTML = bars + '<div class="speech-map-needle" id="speechMapNeedle"></div>';

    if (legend) {
        legend.innerHTML = Object.entries(speakerColorMap).map(([sp, color]) => `
            <span class="speech-map-legend-item" data-speaker="${escapeHtml(sp)}" title="Click para renombrar"><span class="speech-map-legend-dot" style="background:${color}"></span>${escapeHtml(sp)} ✏️</span>
        `).join('');
    }
}

/** Reposiciona la aguja blanca según el tiempo actual del mini-player (si tiene fuente cargada). */
export function updateSpeechMapNeedle(currentSeconds, totalSeconds) {
    const needle = document.getElementById('speechMapNeedle');
    if (!needle || !totalSeconds) return;
    const pct = Math.max(0, Math.min(100, (currentSeconds / totalSeconds) * 100));
    needle.style.left = pct + '%';
}

export function switchTranscriptView(view) {
    activeView = view;
    document.querySelectorAll('.transcript-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === view);
    });
    const segments = parseTimelineToSegments(state.originalTimeline).filter(s => s.timestamp || s.text);
    renderTranscriptList(segments);
}

function renderTranscriptList(segments) {
    const list = document.getElementById('transcriptList');
    if (!list) return;

    if (segments.length === 0) {
        list.innerHTML = '<div class="transcript-list-empty">Procesá un audio/video para ver acá la transcripción interactiva.</div>';
        return;
    }

    if (activeView === 'speakers') {
        const groups = {};
        const order = [];
        for (const s of segments) {
            const sp = s.speaker || "Sin identificar";
            if (!(sp in groups)) { groups[sp] = []; order.push(sp); }
            groups[sp].push(s);
        }
        list.innerHTML = order.map(sp => `
            <div class="transcript-speaker-group">
                <div class="transcript-speaker-group-title" data-speaker="${escapeHtml(sp)}" title="Click para renombrar"><span class="transcript-badge-dot" style="background:${colorForSpeaker(sp)}"></span>${escapeHtml(sp)} ✏️ <span class="transcript-speaker-count">(${groups[sp].length})</span></div>
                ${groups[sp].map(s => transcriptLine(s)).join('')}
            </div>
        `).join('');
        return;
    }

    // 'dialogue' y 'timestamps' comparten la misma lista secuencial; la
    // vista timestamps solo hace más prominente el badge de tiempo (CSS).
    list.className = `transcript-list view-${activeView}`;
    list.innerHTML = segments.map(s => transcriptLine(s)).join('');
}

function transcriptLine(s) {
    const speaker = s.speaker || 'Sin identificar';
    return `
        <div class="transcript-line" data-seek="${escapeHtml(s.timestamp)}">
            <span class="transcript-line-badge" style="border-color:${colorForSpeaker(s.speaker)};" data-speaker="${escapeHtml(speaker)}" title="Click para renombrar este speaker">
                <span class="transcript-badge-dot" style="background:${colorForSpeaker(s.speaker)};"></span>
                ${escapeHtml(speaker)} <span class="transcript-line-time">${escapeHtml(s.timestamp)}</span>
            </span>
            <span class="transcript-line-text">${escapeHtml(s.text)}</span>
        </div>
    `;
}

export function seekTranscriptTo(timestamp) {
    playFromSource(timestamp);
}

/**
 * La IA nunca inventa nombres reales (ver PROMPT_ESCANEO en main.py) - solo
 * pone "Speaker 1", "Speaker 2", etc. Esto deja renombrarlos a mano, una vez
 * identificados de oído, desde cualquiera de los 3 lugares donde aparecen
 * (línea de diálogo, vista "Speakers", leyenda del Speech Map). Reemplaza
 * TODAS las apariciones de esa etiqueta en el transcript crudo (no solo la
 * que se clickeó), así el cambio se refleja en todos lados a la vez -
 * incluido el prompt que se le manda a la IA para generar clips.
 */
export function renameSpeaker(oldLabel, event) {
    if (event) event.stopPropagation();
    if (!state.originalTimeline) return;
    const newLabel = prompt(`Renombrar "${oldLabel}" a:`, oldLabel);
    if (!newLabel || !newLabel.trim() || newLabel.trim() === oldLabel) return;

    const escaped = oldLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`(SPEAKER:\\s*)${escaped}(\\s*)$`, 'gm');
    state.originalTimeline = state.originalTimeline.replace(pattern, `$1${newLabel.trim()}$2`);

    // Mismo patrón de persistencia que toggleEdit (ver timeline.js): si la
    // sesión ya se guardó, el cambio sobrevive a recargar/reabrir del historial.
    if (state.currentSessionId) {
        let sessions = getSessions();
        const idx = sessions.findIndex(s => s.id === state.currentSessionId);
        if (idx !== -1) {
            sessions[idx].data.raw_timeline = state.originalTimeline;
            setSessions(sessions);
            state.currentData = sessions[idx].data;
        }
    }
    generateIAPrompt();
    renderInteractiveTranscript();
}

window.seekTranscriptTo = seekTranscriptTo;
window.switchTranscriptView = switchTranscriptView;
window.renameSpeaker = renameSpeaker;

// User speaker labels are data, never inline JavaScript.
document.addEventListener('click', event => {
    const speaker = event.target.closest('[data-speaker]');
    if (speaker) { renameSpeaker(speaker.dataset.speaker, event); return; }
    const seek = event.target.closest('[data-seek]');
    if (seek) seekTranscriptTo(seek.dataset.seek);
});
