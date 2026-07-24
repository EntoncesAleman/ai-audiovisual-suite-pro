import { state } from '../state.js';
import { getSessions, setSessions } from '../utils/storage.js';
import { generateIAPrompt } from './prompts.js';
import { normalizeToSrt, addSeconds } from '../utils/helpers.js';

export function searchTimeline() {
    const q = document.getElementById('timelineSearch').value.trim();
    const box = document.getElementById('resTimeline');
    if (state.editing) return; // no interferir con edición
    if (!q) {
        box.innerText = state.originalTimeline;
        document.getElementById('searchInfo').textContent = "";
        return;
    }
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escaped, 'gi');
    const matches = state.originalTimeline.match(regex) || [];
    const safeText = state.originalTimeline.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
    const highlighted = safeText.replace(regex, m => `<mark>${m}</mark>`);
    box.innerHTML = highlighted;
    document.getElementById('searchInfo').textContent = `${matches.length} coincidencia${matches.length === 1 ? '' : 's'}`;
}

export function toggleEdit() {
    const box = document.getElementById('resTimeline');
    const btn = document.getElementById('editToggle');
    state.editing = !state.editing;
    if (state.editing) {
        box.innerText = state.originalTimeline; // limpiar highlights
        box.setAttribute('contenteditable', 'true');
        box.focus();
        btn.textContent = "💾 Guardar cambios";
        btn.classList.add('editing');
    } else {
        const newText = box.innerText;
        state.originalTimeline = newText;
        box.removeAttribute('contenteditable');
        btn.textContent = "✏ Editar transcripción";
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
