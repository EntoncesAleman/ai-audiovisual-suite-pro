import { state } from '../state.js';
import { BACKEND_URL } from '../config.js';
import { escapeHtml, setExportProgress, resetExportProgress } from '../utils/dom.js';
import { tsToSeconds, secondsToTs } from '../utils/helpers.js';
import { resolveExportSource } from '../api/api.js';

// ============================================================
// EXPORTACIÓN DE CLIPS
// ============================================================

export function toggleClipExporter() {
    const panel = document.getElementById('clipExporter');
    panel.classList.toggle('active');
    if (panel.classList.contains('active') && state.clipsList.length === 0) {
        // Auto-parsear al abrir si no hay clips cargados
        parseClipsFromTimeline();
    }
}

export function parseClipsFromTimeline() {
    if (!state.originalTimeline) { alert("Primero procesá un video."); return; }
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
        alert("No se encontraron timestamps en el análisis. Asegurate de haber procesado el video primero.");
        return;
    }
    state.clipsList = parsed;
    renderClipsList();
}

export function renderClipsList() {
    const tbody = document.getElementById('clipsTableBody');
    const badge = document.getElementById('clipCountBadge');
    const selected = state.clipsList.filter(c => c.selected).length;
    badge.textContent = `${selected}/${state.clipsList.length} clips`;

    if (state.clipsList.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="clip-empty">Usá "Extraer timestamps" o añadí clips manualmente.</td></tr>';
        return;
    }

    tbody.innerHTML = state.clipsList.map((clip, i) => `
        <tr>
            <td><input type="checkbox" ${clip.selected ? "checked" : ""} onchange="toggleClipSelection(${i}, this.checked)"></td>
            <td><input type="text" value="${escapeHtml(clip.start)}" onchange="updateClip(${i}, 'start', this.value)" style="width:68px;"></td>
            <td><input type="text" value="${escapeHtml(clip.end)}" onchange="updateClip(${i}, 'end', this.value)" style="width:68px;"></td>
            <td class="clip-label-cell"><span class="clip-label-text" title="${escapeHtml(clip.label)}">${escapeHtml(clip.label)}</span></td>
            <td><button class="btn-clip-remove" onclick="removeClip(${i})" title="Quitar">×</button></td>
        </tr>
    `).join('');
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

    const clips = selected.map(c => ({ start: c.start, end: c.end, label: c.label }));

    try {
        const res = await fetch(`${BACKEND_URL}/export-clips`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...source, clips })
        });
        if (!res.ok || !res.body) throw new Error("Sin respuesta del servidor.");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
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
                    } else {
                        statusEl.textContent = "⏳ " + payload.message;
                    }
                } catch (e) {}
            }
        }
    } catch (e) {
        statusEl.className = "clip-export-status active error";
        statusEl.textContent = "❌ Error: " + e.message;
    }
}

// Las filas de la tabla de clips se generan dinámicamente vía innerHTML (arriba),
// así que sus onclick/onchange necesitan encontrar estas funciones en window.
window.toggleClipSelection = toggleClipSelection;
window.updateClip = updateClip;
window.removeClip = removeClip;
