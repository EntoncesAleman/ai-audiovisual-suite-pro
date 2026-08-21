import { state } from '../state.js';
import { getSessions, setSessions } from '../utils/storage.js';
import { generateIAPrompt } from './prompts.js';
import { normalizeToSrt, addSeconds } from '../utils/helpers.js';
import { renderInteractiveTranscript } from './transcriptPanel.js';

/**
 * La transcripción tiene dos vistas del mismo texto: la interactiva (speech
 * map + tabs + lista clickeable, la que se ve por default) y la caja cruda
 * (#resTimeline, contenteditable) que solo se muestra mientras se busca
 * texto (para ver los <mark> resaltados) o se está editando.
 */
function setRawTranscriptVisible(visible) {
    const rawWrap = document.getElementById('rawTranscriptWrap');
    const interactiveWrap = document.getElementById('interactiveTranscriptWrap');
    if (rawWrap) rawWrap.style.display = visible ? 'block' : 'none';
    if (interactiveWrap) interactiveWrap.style.display = visible ? 'none' : 'block';
}

export function searchTimeline() {
    const q = document.getElementById('timelineSearch').value.trim();
    const box = document.getElementById('resTimeline');
    if (state.editing) return; // no interferir con edición
    if (!q) {
        box.innerText = state.originalTimeline;
        document.getElementById('searchInfo').textContent = "";
        setRawTranscriptVisible(false);
        return;
    }
    setRawTranscriptVisible(true);
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, 'gi');
    const matches = state.originalTimeline.match(regex) || [];
    const safeText = state.originalTimeline.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
    const highlighted = safeText.replace(regex, m => `<mark>${m}</mark>`);
    box.innerHTML = highlighted;
    document.getElementById('searchInfo').textContent = `${matches.length} coincidencia${matches.length === 1 ? '' : 's'}`;
}

// Iconos del botón editar/guardar (no se puede usar textContent para
// cambiar la etiqueta porque borraría el ícono SVG - ver abajo).
const ICON_PENCIL = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';
const ICON_SAVE = '<svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg>';

export function toggleEdit() {
    const box = document.getElementById('resTimeline');
    const btn = document.getElementById('editToggle');
    state.editing = !state.editing;
    if (state.editing) {
        box.innerText = state.originalTimeline; // limpiar highlights
        box.setAttribute('contenteditable', 'true');
        box.focus();
        btn.innerHTML = `${ICON_SAVE} Guardar cambios`;
        btn.classList.add('editing');
        setRawTranscriptVisible(true);
    } else {
        const newText = box.innerText;
        state.originalTimeline = newText;
        box.removeAttribute('contenteditable');
        btn.innerHTML = `${ICON_PENCIL} Editar transcripción`;
        btn.classList.remove('editing');
        // Persistir cambios en la sesión actual
        if (state.currentSessionId) {
            let sessions = getSessions();
            const idx = sessions.findIndex(s => s.id === state.currentSessionId);
            if (idx !== -1) {
                sessions[idx].data.raw_timeline = newText;
                setSessions(sessions);
                state.currentData = sessions[idx].data;
            }
        }
        generateIAPrompt(); // regenerar prompt con texto editado
        renderInteractiveTranscript(); // reflejar los cambios en el speech map / lista
        setRawTranscriptVisible(false);
    }
}

export function downloadTimeline(format) {
    if (!state.originalTimeline) { alert("No hay transcripción para descargar."); return; }
    let content = state.originalTimeline;
    let ext = "txt";
    let mime = "text/plain";

    if (format === "srt") {
        // Conversor básico: detecta bloques TIMESTAMP / SPEAKER / DIALOGUE y arma SRT.
        const blocks = state.originalTimeline.split(/^---\s*$/m).map(b => b.trim()).filter(Boolean);
        const srtLines = [];
        blocks.forEach((block, i) => {
            const tsMatch = block.match(/TIMESTAMP:\s*(\d+:\d+(?::\d+)?)/i);
            const spMatch = block.match(/SPEAKER:\s*(.+)/i);
            const dlMatch = block.match(/DIALOGUE:\s*([\s\S]+?)(?=\n[A-Z]+:|$)/i);
            if (!tsMatch) return;
            const start = normalizeToSrt(tsMatch[1]);
            const end = addSeconds(start, 4); // duración estimada 4s; el usuario afina luego
            const speaker = spMatch ? spMatch[1].trim() : "";
            const dialogue = dlMatch ? dlMatch[1].trim() : "";
            srtLines.push(`${i+1}\n${start} --> ${end}\n${speaker ? speaker + ": " : ""}${dialogue}\n`);
        });
        content = srtLines.join("\n");
        ext = "srt";
    }

    const blob = new Blob([content], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const safeTitle = (state.currentData?.title || "transcripcion").replace(/[^\w\-]+/g, "_");
    a.download = `${safeTitle}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
}
