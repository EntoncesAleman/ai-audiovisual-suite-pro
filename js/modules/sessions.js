import { BACKEND_URL } from '../config.js';
import { state } from '../state.js';
import { getSessions, setSessions } from '../utils/storage.js';
import { renderClipsList } from './clips.js';
import { renderReelClipsList, updateVideoPanel } from './reelEditor.js';
import { generateIAPrompt } from './prompts.js';
import { toggleEdit } from './timeline.js';

export function saveSession(data) {
    if (state._pendingSourceUrl) { data.source_url = state._pendingSourceUrl; state._pendingSourceUrl = ""; }
    let sessions = getSessions();
    const newSession = { id: Date.now(), timestamp: new Date().toLocaleDateString(), data: data };
    sessions.unshift(newSession);
    try {
        setSessions(sessions);
    } catch (e) {
        alert("⚠ El historial está casi lleno. Exportá las sesiones y vaciá algunas antes de seguir.");
    }
    state.currentSessionId = newSession.id;
    renderSessions();
    loadSessionData(data);
}

export function renderSessions() {
    const list = document.getElementById("sessionList");
    list.innerHTML = "";
    let sessions = getSessions();
    sessions.forEach(s => {
        const activeClass = s.id === state.currentSessionId ? "active" : "";
        list.innerHTML += `
            <li class="session-item ${activeClass}" onclick="loadSessionById(${s.id})">
                <span class="session-title">${(s.data.title || 'Video Analizado').replace(/</g, '&lt;')}</span>
                <button class="btn-del" onclick="deleteSession(event, ${s.id})">×</button>
            </li>
        `;
    });
}

export function loadSessionById(id) {
    let sessions = getSessions();
    let item = sessions.find(s => s.id === id);
    if (item) {
        state.currentSessionId = id;
        loadSessionData(item.data);
        renderSessions();
    }
}

export function loadSessionData(data) {
    state.currentData = data;
    state.originalTimeline = data.raw_timeline || "No hay líneas de tiempo registradas.";
    document.getElementById('resTimeline').innerText = state.originalTimeline;
    document.getElementById('resultBlock').style.display = 'block';
    document.getElementById('cacheBadge').innerHTML = data.from_cache ? '<span class="cache-badge">⚡ DESDE CACHE</span>' : '';
    document.getElementById('timelineSearch').value = "";
    document.getElementById('searchInfo').textContent = "";
    if (state.editing) toggleEdit();
    // Restaurar URL fuente en el panel de clips
    document.getElementById('clipSourceUrl').value = data.source_url || "";
    // Cerrar panel de clips al cambiar sesión
    document.getElementById('clipExporter').classList.remove('active');
    state.clipsList = [];
    renderClipsList();
    // Actualizar panel de video para redes
    state.reelClipsList = [];
    renderReelClipsList();
    updateVideoPanel();
    generateIAPrompt();
}

export function startNewSession() {
    state.currentData = null;
    state.currentSessionId = null;
    document.getElementById('streamUrl').value = "";
    document.getElementById('localFile').value = "";
    document.getElementById('resultBlock').style.display = 'none';
    document.getElementById('promptOutput').innerText = "Carga un análisis para generar el prompt dinámico...";
    renderSessions();
}

export function deleteSession(event, id) {
    event.stopPropagation();
    let sessions = getSessions();
    sessions = sessions.filter(s => s.id !== id);
    setSessions(sessions);
    if (state.currentSessionId === id) startNewSession();
    else renderSessions();
}

export async function clearServerCache() {
    const btn = document.getElementById('btnClearCache');
    const original = btn.textContent;
    btn.textContent = '⏳ Borrando...';
    btn.disabled = true;
    try {
        const res = await fetch(`${BACKEND_URL}/cache-clear`, { method: 'POST' });
        const data = await res.json();
        btn.textContent = `✅ ${data.deleted} análisis borrados`;
        setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 3000);
    } catch (e) {
        btn.textContent = '❌ Error al borrar';
        setTimeout(() => { btn.textContent = original; btn.disabled = false; }, 3000);
    }
}

export function clearAllSessions() {
    if (confirm("¿Seguro querés vaciar todo el historial de análisis?")) {
        localStorage.removeItem("video_sessions_v5");
        startNewSession();
    }
}

export function exportAllSessions() {
    const sessions = getSessions();
    if (sessions.length === 0) { alert("No hay sesiones para exportar."); return; }
    const blob = new Blob([JSON.stringify(sessions, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `audiovisual_suite_sessions_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
}

export function importSessions(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const imported = JSON.parse(e.target.result);
            if (!Array.isArray(imported)) throw new Error("Formato inválido");
            const existing = getSessions();
            const merged = [...imported, ...existing];
            // Deduplicar por id
            const seen = new Set();
            const unique = merged.filter(s => { if (seen.has(s.id)) return false; seen.add(s.id); return true; });
            setSessions(unique);
            renderSessions();
            alert(`✓ Importadas ${imported.length} sesiones.`);
        } catch (err) {
            alert("Error al importar: " + err.message);
        }
    };
    reader.readAsText(file);
    event.target.value = "";
}

// Las filas de sesiones se generan dinámicamente vía innerHTML (arriba), así que
// sus onclick necesitan encontrar estas funciones en window.
window.loadSessionById = loadSessionById;
window.deleteSession = deleteSession;
