import { getProjects, setProjects, getSessions, setSessions } from '../utils/storage.js';

// ============================================================
// PROYECTOS: agrupan las sesiones del historial (todo en
// localStorage por ahora, mismo lugar donde ya viven las
// sesiones). Un proyecto es simplemente {id, name, created_at};
// cada sesión guarda project_id apuntando acá (o null/ausente =
// "Sin proyecto").
// ============================================================

function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function getProjectName(projectId) {
    if (!projectId) return "Sin proyecto";
    const p = getProjects().find(p => p.id === projectId);
    return p ? p.name : "Sin proyecto";
}

export function createProject(name) {
    const trimmed = name.trim();
    if (!trimmed) return null;
    const projects = getProjects();
    const project = { id: `proj_${Date.now()}`, name: trimmed, created_at: new Date().toISOString() };
    projects.unshift(project);
    setProjects(projects);
    return project;
}

export function renameProject(id, name) {
    const trimmed = name.trim();
    if (!trimmed) return;
    const projects = getProjects();
    const p = projects.find(p => p.id === id);
    if (p) { p.name = trimmed; setProjects(projects); }
}

/** Borra el proyecto y deja "Sin proyecto" a todas las sesiones que lo tenían asignado. */
export function deleteProject(id) {
    setProjects(getProjects().filter(p => p.id !== id));
    const sessions = getSessions();
    let changed = false;
    sessions.forEach(s => { if (s.project_id === id) { s.project_id = null; changed = true; } });
    if (changed) setSessions(sessions);
}

export function assignSessionToProject(sessionId, projectId) {
    const sessions = getSessions();
    const s = sessions.find(s => s.id === sessionId);
    if (!s) return;
    s.project_id = projectId || null;
    setSessions(sessions);
}

// ------------------------------------------------------------
// UI: drawer flotante (mismo lenguaje visual que el Panel de
// Control del admin, ver auth.js/auth.css) para crear/renombrar/
// borrar proyectos. Se inyecta una sola vez, se abre desde el
// dropdown de Account en el header.
// ------------------------------------------------------------
function injectProjectsUI() {
    if (document.getElementById('projectsDrawerOverlay')) return;

    const wrap = document.createElement('div');
    wrap.innerHTML = `
        <div class="admin-drawer-overlay" id="projectsDrawerOverlay">
            <div class="admin-drawer">
                <div class="admin-drawer-header">
                    <h2 class="icon-heading">📁 Proyectos</h2>
                    <button class="btn-close-drawer" id="btnCloseProjectsDrawer" title="Cerrar">✕</button>
                </div>
                <div class="admin-tab-panel active" style="padding:18px 22px;">
                    <form id="newProjectForm" style="display:flex; gap:8px; margin-bottom:16px;">
                        <input type="text" id="newProjectName" placeholder="Nombre del proyecto (ej: Podcast Data)" style="margin:0;" required>
                        <button type="submit" class="btn-admin-approve" style="flex:0 0 auto; padding:0 16px;">+ Crear</button>
                    </form>
                    <div id="projectsList"></div>
                </div>
            </div>
        </div>
    `;
    document.body.append(...wrap.children);

    document.getElementById('btnCloseProjectsDrawer').addEventListener('click', closeProjectsManager);
    document.getElementById('projectsDrawerOverlay').addEventListener('click', (e) => {
        if (e.target.id === 'projectsDrawerOverlay') closeProjectsManager();
    });
    document.getElementById('newProjectForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const input = document.getElementById('newProjectName');
        if (createProject(input.value)) {
            input.value = '';
            renderProjectsList();
        }
    });
}

function renderProjectsList() {
    const list = document.getElementById('projectsList');
    if (!list) return;
    const projects = getProjects();
    const sessions = getSessions();

    if (projects.length === 0) {
        list.innerHTML = '<div class="admin-empty">Todavía no creaste ningún proyecto.</div>';
        return;
    }

    list.innerHTML = projects.map((p) => {
        const count = sessions.filter(s => s.project_id === p.id).length;
        return `
        <div class="admin-request-card" data-id="${escapeHtml(p.id)}" style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
            <input type="text" class="project-rename-input" value="${escapeHtml(p.name)}" style="flex:1; margin:0; background:var(--bg-input); border:var(--border); border-radius:var(--radius); color:var(--text-main); padding:8px 10px; font-size:13px;">
            <span style="color:var(--text-muted); font-size:12px; white-space:nowrap;">${count} sesión${count === 1 ? '' : 'es'}</span>
            <button class="btn-admin-mini btn-project-delete" title="Borrar proyecto">🗑</button>
        </div>`;
    }).join('');

    list.querySelectorAll('.project-rename-input').forEach((input) => {
        input.addEventListener('change', () => {
            renameProject(input.closest('[data-id]').dataset.id, input.value);
            document.dispatchEvent(new CustomEvent('projects-changed'));
        });
    });
    list.querySelectorAll('.btn-project-delete').forEach((btn) => {
        btn.addEventListener('click', () => {
            const card = btn.closest('[data-id]');
            const p = projects.find(p => p.id === card.dataset.id);
            if (!confirm(`¿Borrar el proyecto "${p.name}"? Las sesiones que tenía quedan como "Sin proyecto" (no se borran).`)) return;
            deleteProject(card.dataset.id);
            renderProjectsList();
            document.dispatchEvent(new CustomEvent('projects-changed'));
        });
    });
}

export function openProjectsManager() {
    injectProjectsUI();
    renderProjectsList();
    document.getElementById('projectsDrawerOverlay').classList.add('active');
}

export function closeProjectsManager() {
    document.getElementById('projectsDrawerOverlay')?.classList.remove('active');
}
