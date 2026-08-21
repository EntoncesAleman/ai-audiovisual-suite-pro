// Página aparte del historial de sesiones (antes vivía como una tarjeta
// compacta dentro de index.html). Todo local: las sesiones están en
// localStorage (ver utils/storage.js), no hace falta backend para listarlas
// - solo "Borrar caché de análisis" le pega al servidor.
import { BACKEND_URL } from './config.js';
import { getSessions, setSessions, authHeaders, getProjects } from './utils/storage.js';
import { escapeHtml } from './utils/dom.js';
import { initAuthGuard } from './modules/auth.js';
import { getProjectName, assignSessionToProject } from './modules/projects.js';

let activeProjectFilter = ""; // "" = todos, "none" = sin proyecto, o un project_id

function populateProjectFilter() {
    const sel = document.getElementById('projectFilter');
    if (!sel) return;
    const projects = getProjects();
    const current = sel.value;
    sel.innerHTML = '<option value="">📁 Todos los proyectos</option>'
        + '<option value="none">Sin proyecto</option>'
        + projects.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
    // Mantener la selección si el proyecto sigue existiendo
    if ([...sel.options].some(o => o.value === current)) sel.value = current;
}

function projectOptionsHtml(selectedId) {
    const projects = getProjects();
    return '<option value=""' + (!selectedId ? ' selected' : '') + '>Sin proyecto</option>'
        + projects.map(p => `<option value="${p.id}"${p.id === selectedId ? ' selected' : ''}>${escapeHtml(p.name)}</option>`).join('');
}

function renderSessions() {
    const list = document.getElementById('sessionListFull');
    let sessions = getSessions();

    if (activeProjectFilter === "none") {
        sessions = sessions.filter(s => !s.project_id);
    } else if (activeProjectFilter) {
        sessions = sessions.filter(s => s.project_id === activeProjectFilter);
    }

    if (sessions.length === 0) {
        list.innerHTML = '<li class="session-empty">'
            + (activeProjectFilter ? 'No hay sesiones en este proyecto.' : 'Todavía no hay ninguna sesión analizada.')
            + '</li>';
        return;
    }

    list.innerHTML = sessions.map((s) => `
        <li class="session-item-full" data-id="${s.id}">
            <div class="session-item-full-main" onclick="openSession(${s.id})">
                <div class="session-item-full-info">
                    <span class="session-item-full-title">${escapeHtml(s.data.title || 'Video Analizado')}</span>
                    <span class="session-item-full-date">${escapeHtml(s.timestamp || '')} · ${escapeHtml(getProjectName(s.project_id))}</span>
                </div>
            </div>
            <select class="session-project-select" onclick="event.stopPropagation()" onchange="event.stopPropagation(); moveSessionToProject(${s.id}, this.value)">
                ${projectOptionsHtml(s.project_id)}
            </select>
            <button class="btn-del" onclick="event.stopPropagation(); deleteSessionFull(${s.id})" title="Borrar">×</button>
        </li>
    `).join('');
}

function filterByProject(value) {
    activeProjectFilter = value;
    renderSessions();
}

function moveSessionToProject(id, projectId) {
    assignSessionToProject(id, projectId || null);
    renderSessions();
}

function openSession(id) {
    window.location.href = `/?session=${id}`;
}

function deleteSessionFull(id) {
    const sessions = getSessions().filter((s) => s.id !== id);
    setSessions(sessions);
    renderSessions();
}

function clearAllSessions() {
    if (confirm("¿Seguro querés vaciar todo el historial de análisis?")) {
        setSessions([]);
        renderSessions();
    }
}

function exportAllSessions() {
    const sessions = getSessions();
    if (sessions.length === 0) { alert("No hay sesiones para exportar."); return; }
    const blob = new Blob([JSON.stringify(sessions, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `audiovisual_suite_sessions_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
}

function importSessions(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const imported = JSON.parse(e.target.result);
            if (!Array.isArray(imported)) throw new Error("Formato inválido");
            const existing = getSessions();
            const merged = [...imported, ...existing];
            const seen = new Set();
            const unique = merged.filter((s) => { if (seen.has(s.id)) return false; seen.add(s.id); return true; });
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

async function clearServerCache() {
    const btn = document.getElementById('btnClearCache');
    const original = btn.innerHTML;
    btn.textContent = '⏳ Borrando...';
    btn.disabled = true;
    try {
        const res = await fetch(`${BACKEND_URL}/cache-clear`, { method: 'POST', headers: authHeaders() });
        const data = await res.json();
        btn.textContent = `✅ ${data.deleted} análisis borrados`;
        setTimeout(() => { btn.innerHTML = original; btn.disabled = false; }, 3000);
    } catch (e) {
        btn.textContent = '❌ Error al borrar';
        setTimeout(() => { btn.innerHTML = original; btn.disabled = false; }, 3000);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initAuthGuard();
    populateProjectFilter();
    renderSessions();
});
document.addEventListener('projects-changed', () => {
    populateProjectFilter();
    renderSessions();
});

window.openSession = openSession;
window.deleteSessionFull = deleteSessionFull;
window.clearAllSessions = clearAllSessions;
window.exportAllSessions = exportAllSessions;
window.importSessions = importSessions;
window.clearServerCache = clearServerCache;
window.filterByProject = filterByProject;
window.moveSessionToProject = moveSessionToProject;
