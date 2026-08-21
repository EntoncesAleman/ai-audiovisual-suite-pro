import { state } from '../state.js';
import { escapeHtml, highlightSearch } from '../utils/dom.js';
import { parseTimelineToSegments } from '../utils/helpers.js';

export function openReader() {
    if (!state.currentData || !state.originalTimeline) {
        alert("Primero cargá o procesá una sesión.");
        return;
    }
    document.getElementById('readerTitleText').textContent =
        state.currentData.title || 'Desgrabación';
    document.getElementById('readerOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
    renderReader();
}

export function closeReader() {
    document.getElementById('readerOverlay').classList.remove('active');
    document.body.style.overflow = '';
}

// Cerrar con ESC
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('readerOverlay').classList.contains('active')) {
        closeReader();
    }
});

export function changeReaderFontSize() {
    const size = document.getElementById('readerFontSize').value;
    const content = document.getElementById('readerContent');
    content.classList.remove('font-size-sm', 'font-size-lg', 'font-size-xl');
    if (size) content.classList.add(size);
}

export function renderReader() {
    const view = document.getElementById('readerView').value;
    const search = document.getElementById('readerSearch').value.trim().toLowerCase();
    const content = document.getElementById('readerContent');

    // Limpiar clases de vista y aplicar la nueva
    content.className = 'reader-content view-' + view;
    // Reaplicar tamaño de fuente
    const size = document.getElementById('readerFontSize').value;
    if (size) content.classList.add(size);

    const segments = parseTimelineToSegments(state.originalTimeline);
    if (segments.length === 0) {
        content.innerHTML = '<p style="color:#94a3b8;text-align:center;">No se pudo parsear la transcripción. Probá la vista normal.</p>';
        return;
    }

    // Filtrado por búsqueda
    const filtered = search
        ? segments.filter(s =>
            (s.text || "").toLowerCase().includes(search) ||
            (s.speaker || "").toLowerCase().includes(search))
        : segments;

    let html = "";

    if (view === 'dialogue' || view === 'subtitle') {
        html = filtered.map(s => `
            <div class="segment">
                ${s.timestamp ? `<div class="segment-time">${escapeHtml(s.timestamp)}</div>` : ''}
                <div>
                    ${s.speaker ? `<div class="segment-speaker">${escapeHtml(s.speaker)}</div>` : ''}
                    <div class="segment-text">${highlightSearch(escapeHtml(s.text), search)}</div>
                </div>
            </div>
        `).join("");
    } else if (view === 'grouped') {
        // Agrupar por hablante (preservando orden de primera aparición)
        const groups = {};
        const order = [];
        for (const s of filtered) {
            const sp = s.speaker || "Sin identificar";
            if (!(sp in groups)) { groups[sp] = []; order.push(sp); }
            groups[sp].push(s);
        }
        html = order.map(speaker => `
            <div class="speaker-block">
                <div class="speaker-name">👤 ${escapeHtml(speaker)} <span style="color:#64748b;font-weight:normal;">(${groups[speaker].length} intervenciones)</span></div>
                ${groups[speaker].map(s => `
                    <div class="speaker-line">
                        ${s.timestamp ? `<span class="speaker-line-time">[${escapeHtml(s.timestamp)}]</span>` : ''}
                        ${highlightSearch(escapeHtml(s.text), search)}
                    </div>
                `).join("")}
            </div>
        `).join("");
    }

    content.innerHTML = html || '<p style="color:#94a3b8;">Sin resultados para esta búsqueda.</p>';

    // Estadísticas al pie
    renderReaderStats(segments, filtered);
}

function renderReaderStats(allSegments, filteredSegments) {
    const speakers = new Set(allSegments.map(s => s.speaker).filter(Boolean));
    const totalWords = allSegments.reduce((acc, s) => acc + (s.text || "").split(/\s+/).filter(Boolean).length, 0);
    const estimatedMinutes = Math.round(totalWords / 130); // ~130 palabras por minuto de habla

    document.getElementById('readerStats').innerHTML = `
        <span>📊 ${allSegments.length} segmentos</span>
        <span>👥 ${speakers.size} hablantes</span>
        <span>📝 ~${totalWords.toLocaleString()} palabras</span>
        <span>⏱ ~${estimatedMinutes} min de audio estimado</span>
        ${filteredSegments.length !== allSegments.length ? `<span style="color:#fbbf24;">🔍 ${filteredSegments.length} coincidencias</span>` : ''}
    `;
}
