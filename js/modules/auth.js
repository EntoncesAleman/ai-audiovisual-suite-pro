import { BACKEND_URL } from '../config.js';
import { getApiKey, setApiKey, clearApiKey, authHeaders } from '../utils/storage.js';
import { fetchWithTimeout } from '../utils/helpers.js';

// ============================================================
// SISTEMA DE USUARIOS: Auth Guard (modal de login + solicitar
// acceso) + panel de administración para el SUPERADMIN. Todo el
// HTML de acá se inyecta por JS al cargar la página (mismo módulo
// para index.html e historial.html, sin duplicar el markup).
// ============================================================

let currentUser = null; // { username, role } | null

export function getCurrentUser() { return currentUser; }
export function isSuperAdmin() { return currentUser?.role === 'SUPERADMIN'; }

function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** AbortError (timeout de fetchWithTimeout) da un mensaje de browser poco claro - lo traducimos. */
function friendlyErrorMessage(err) {
    if (err.name === 'AbortError') return 'El servidor tardó demasiado en responder. Probá de nuevo en unos segundos.';
    if (err instanceof TypeError) return 'No se pudo contactar al servidor. Revisá tu conexión e intentá de nuevo.';
    return err.message;
}

// ------------------------------------------------------------
// INYECCIÓN DE MARKUP
// ------------------------------------------------------------
function injectAuthUI() {
    if (document.getElementById('authGuardOverlay')) return;

    const wrap = document.createElement('div');
    wrap.innerHTML = `
        <div class="auth-guard-overlay" id="authGuardOverlay">
            <div class="auth-modal">

                <div class="auth-view active" id="authViewLogin">
                    <div class="auth-modal-logo">
                        <span class="app-logo-icon" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="4" y1="19" x2="4" y2="11"/><line x1="10" y1="19" x2="10" y2="5"/><line x1="16" y1="19" x2="16" y2="9"/><line x1="21" y1="19" x2="21" y2="14"/></svg></span>
                        <span class="app-brand-name">AV SUITE PRO</span>
                    </div>
                    <h2 class="auth-modal-title">Iniciar sesión</h2>
                    <form id="authLoginForm">
                        <label>Usuario</label>
                        <input type="text" id="authLoginUsername" autocomplete="username" required>
                        <label>Contraseña</label>
                        <input type="password" id="authLoginPassword" autocomplete="current-password" required>
                        <p class="auth-error" id="authLoginError" hidden></p>
                        <button type="submit" class="btn-auth-primary" id="authLoginSubmit">Iniciar Sesión</button>
                    </form>
                    <div class="auth-modal-footer" style="flex-direction:column; gap:8px;">
                        <button type="button" class="btn-auth-link" id="btnForgotPassword" style="color:var(--text-sub); font-weight:600;">¿Olvidaste tu contraseña?</button>
                        <div>
                            <span>¿No tenés cuenta?</span>
                            <button type="button" class="btn-auth-link" id="btnShowRequestAccess">📩 Solicitar Acceso</button>
                        </div>
                    </div>
                </div>

                <div class="auth-view" id="authViewRequest">
                    <h2 class="auth-modal-title" id="authRequestTitle">Solicitar Acceso</h2>
                    <p class="request-hint" id="authRequestHint" hidden style="font-size:12.5px; color:var(--text-sub); text-align:center; margin:-8px 0 16px;">Le llega al administrador, que te va a resetear la contraseña y avisarte.</p>
                    <form id="authRequestForm">
                        <label>Nombre / Apodo</label>
                        <input type="text" id="authReqName" required>
                        <label>Organización / Proyecto</label>
                        <input type="text" id="authReqProject">
                        <label>Motivo / Uso (opcional)</label>
                        <textarea id="authReqReason" rows="3"></textarea>
                        <p class="auth-error" id="authRequestError" hidden></p>
                        <button type="submit" class="btn-auth-primary" id="authRequestSubmit">Enviar Solicitud</button>
                    </form>
                    <p class="auth-success" id="authRequestSuccess" hidden>✅ Solicitud enviada. El administrador te asignará credenciales a la brevedad.</p>
                    <div class="auth-modal-footer">
                        <button type="button" class="btn-auth-link" id="btnBackToLogin">← Volver a iniciar sesión</button>
                    </div>
                </div>

            </div>
        </div>

        <div class="admin-drawer-overlay" id="adminDrawerOverlay">
            <div class="admin-drawer">
                <div class="admin-drawer-header">
                    <h2 class="icon-heading">👑 Panel de Control</h2>
                    <button class="btn-close-drawer" id="btnCloseAdminDrawer" title="Cerrar">✕</button>
                </div>
                <div class="admin-drawer-tabs">
                    <button class="admin-tab-btn active" data-tab="pending" id="adminTabPending">Solicitudes Pendientes <span class="admin-tab-count" id="adminPendingCount">0</span></button>
                    <button class="admin-tab-btn" data-tab="users" id="adminTabUsers">Usuarios Activos</button>
                </div>
                <div class="admin-tab-panel active" id="adminPanelPending">
                    <div class="admin-request-list" id="adminRequestList"><div class="admin-empty">Cargando...</div></div>
                </div>
                <div class="admin-tab-panel" id="adminPanelUsers">
                    <table class="admin-users-table">
                        <thead><tr><th>Usuario</th><th>Rol</th><th>Estado</th><th></th></tr></thead>
                        <tbody id="adminUsersTableBody"><tr><td colspan="4" class="admin-empty">Cargando...</td></tr></tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    document.body.append(...wrap.children);

    document.getElementById('authLoginForm').addEventListener('submit', onLoginSubmit);
    document.getElementById('authRequestForm').addEventListener('submit', onRequestSubmit);
    document.getElementById('btnShowRequestAccess').addEventListener('click', () => switchAuthView('request'));
    document.getElementById('btnForgotPassword').addEventListener('click', showForgotPasswordView);
    document.getElementById('btnBackToLogin').addEventListener('click', () => switchAuthView('login'));
    document.getElementById('btnCloseAdminDrawer').addEventListener('click', closeAdminDrawer);
    document.getElementById('adminTabPending').addEventListener('click', () => switchAdminTab('pending'));
    document.getElementById('adminTabUsers').addEventListener('click', () => switchAdminTab('users'));
    document.getElementById('adminDrawerOverlay').addEventListener('click', (e) => {
        if (e.target.id === 'adminDrawerOverlay') closeAdminDrawer();
    });
}

function switchAuthView(view) {
    document.getElementById('authViewLogin').classList.toggle('active', view === 'login');
    document.getElementById('authViewRequest').classList.toggle('active', view === 'request');
    document.getElementById('authRequestSuccess').hidden = true;
    document.getElementById('authRequestForm').hidden = false;
    // Volver siempre al modo "Solicitar Acceso" normal salvo que se pida explícitamente el de recuperar contraseña (ver showForgotPasswordView).
    document.getElementById('authRequestTitle').textContent = 'Solicitar Acceso';
    document.getElementById('authRequestHint').hidden = true;
    document.getElementById('authReqReason').value = '';
}

/**
 * "¿Olvidaste tu contraseña?": no hay backend de reseteo por mail (no hace
 * falta para un equipo chico) - reusa el mismo formulario de Solicitar
 * Acceso, con el motivo pre-cargado, para que le llegue al SUPERADMIN en el
 * Panel de Control y pueda resetear la contraseña desde ahí.
 */
function showForgotPasswordView() {
    switchAuthView('request');
    document.getElementById('authRequestTitle').textContent = 'Recuperar Contraseña';
    document.getElementById('authRequestHint').hidden = false;
    document.getElementById('authReqReason').value = 'Olvidé mi contraseña, necesito que me la resetee un administrador.';
}

function showLoginModal() {
    injectAuthUI();
    switchAuthView('login');
    document.getElementById('authGuardOverlay').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function hideLoginModal() {
    const overlay = document.getElementById('authGuardOverlay');
    if (overlay) overlay.classList.remove('active');
    document.body.style.overflow = '';
}

// ------------------------------------------------------------
// LOGIN / LOGOUT / CHEQUEO DE SESIÓN
// ------------------------------------------------------------
async function onLoginSubmit(e) {
    e.preventDefault();
    const username = document.getElementById('authLoginUsername').value.trim();
    const password = document.getElementById('authLoginPassword').value;
    const errorEl = document.getElementById('authLoginError');
    const btn = document.getElementById('authLoginSubmit');
    errorEl.hidden = true;
    btn.disabled = true;
    btn.textContent = 'Ingresando...';
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Usuario o contraseña incorrectos.');
        setApiKey(data.token);
        currentUser = { username: data.username, role: data.role };
        hideLoginModal();
        renderUserUI();
    } catch (err) {
        errorEl.textContent = friendlyErrorMessage(err);
        errorEl.hidden = false;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Iniciar Sesión';
    }
}

async function onRequestSubmit(e) {
    e.preventDefault();
    const name = document.getElementById('authReqName').value.trim();
    const project = document.getElementById('authReqProject').value.trim();
    const reason = document.getElementById('authReqReason').value.trim();
    const errorEl = document.getElementById('authRequestError');
    const btn = document.getElementById('authRequestSubmit');
    errorEl.hidden = true;
    btn.disabled = true;
    btn.textContent = 'Enviando...';
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/access-requests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, project, reason })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo enviar la solicitud.');
        document.getElementById('authRequestForm').hidden = true;
        document.getElementById('authRequestSuccess').hidden = false;
    } catch (err) {
        errorEl.textContent = friendlyErrorMessage(err);
        errorEl.hidden = false;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Enviar Solicitud';
    }
}

export async function logout() {
    try {
        await fetchWithTimeout(`${BACKEND_URL}/auth/logout`, { method: 'POST', headers: authHeaders() });
    } catch (e) { /* best-effort */ }
    clearApiKey();
    currentUser = null;
    window.location.reload();
}

/**
 * Auth Guard: se llama al cargar cualquier página protegida (index.html,
 * historial.html). Si no hay sesión válida, bloquea todo detrás de un
 * modal de login. Si falla por red (server dormido en el free tier), NO
 * fuerza logout - deja pasar de forma optimista si ya había un token
 * guardado, igual que el chequeo viejo (ensureAuthenticated en app.js).
 */
export async function initAuthGuard() {
    injectAuthUI();
    const token = getApiKey();
    if (!token) { showLoginModal(); return; }
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/auth/check`, { headers: authHeaders() });
        if (res.status === 401) {
            clearApiKey();
            showLoginModal();
            return;
        }
        if (!res.ok) { hideLoginModal(); return; }
        const data = await res.json();
        if (data.username) {
            currentUser = { username: data.username, role: data.role };
        }
        hideLoginModal();
        renderUserUI();
    } catch (err) {
        console.warn('No se pudo verificar la sesión (¿servidor dormido?):', err);
        hideLoginModal();
    }
}

// ------------------------------------------------------------
// HEADER: nombre de usuario + badge SUPERUSER + botón Panel de Control
// ------------------------------------------------------------
function renderUserUI() {
    const accountLabel = document.getElementById('navAccountLabel');
    const accountLink = document.getElementById('navAccountLink');
    if (accountLabel && currentUser) accountLabel.textContent = currentUser.username;
    if (accountLink && !accountLink.dataset.wired) {
        accountLink.dataset.wired = '1';
        accountLink.style.position = 'relative';
        accountLink.insertAdjacentHTML('beforeend', `
            <div class="account-dropdown" id="accountDropdown">
                <button type="button" id="btnOpenProjects">📁 Proyectos</button>
                <button type="button" id="btnLogout">Cerrar sesión</button>
            </div>
        `);
        accountLink.addEventListener('click', (e) => {
            e.stopPropagation();
            document.getElementById('accountDropdown').classList.toggle('open');
        });
        document.getElementById('btnOpenProjects').addEventListener('click', async (e) => {
            e.stopPropagation();
            document.getElementById('accountDropdown').classList.remove('open');
            const { openProjectsManager } = await import('./projects.js');
            openProjectsManager();
        });
        document.getElementById('btnLogout').addEventListener('click', (e) => {
            e.stopPropagation();
            logout();
        });
        document.addEventListener('click', () => {
            document.getElementById('accountDropdown')?.classList.remove('open');
        });
    }

    const nav = document.getElementById('headerNav');
    if (!nav || !currentUser) return;

    if (isSuperAdmin() && !document.getElementById('adminBadge')) {
        const badge = document.createElement('span');
        badge.className = 'admin-badge';
        badge.id = 'adminBadge';
        badge.textContent = 'SUPERUSER';

        const btn = document.createElement('button');
        btn.className = 'btn-admin-panel';
        btn.id = 'btnOpenAdminPanel';
        btn.innerHTML = '👑 Panel de Control <span class="admin-pending-badge" id="adminPendingBadge" style="display:none">0</span>';
        btn.addEventListener('click', openAdminDrawer);

        nav.prepend(btn);
        nav.prepend(badge);
        refreshPendingCount();
    }
}

async function refreshPendingCount() {
    if (!isSuperAdmin()) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/access-requests`, { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const count = data.requests.length;
        const badge = document.getElementById('adminPendingBadge');
        if (badge) {
            badge.textContent = String(count);
            badge.style.display = count > 0 ? 'inline-flex' : 'none';
        }
    } catch (e) { /* silencioso */ }
}

// ------------------------------------------------------------
// PANEL DE ADMINISTRACIÓN
// ------------------------------------------------------------
function openAdminDrawer() {
    document.getElementById('adminDrawerOverlay').classList.add('active');
    loadPendingRequests();
    loadActiveUsers();
}

function closeAdminDrawer() {
    document.getElementById('adminDrawerOverlay').classList.remove('active');
}

function switchAdminTab(tab) {
    document.getElementById('adminTabPending').classList.toggle('active', tab === 'pending');
    document.getElementById('adminTabUsers').classList.toggle('active', tab === 'users');
    document.getElementById('adminPanelPending').classList.toggle('active', tab === 'pending');
    document.getElementById('adminPanelUsers').classList.toggle('active', tab === 'users');
}

function suggestUsername(name) {
    return name.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
        .replace(/[^a-z0-9]+/g, '.').replace(/^\.+|\.+$/g, '') || 'usuario';
}

function generatePassword() {
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
    let pw = '';
    for (let i = 0; i < 12; i++) pw += chars[Math.floor(Math.random() * chars.length)];
    return pw;
}

async function loadPendingRequests() {
    const list = document.getElementById('adminRequestList');
    list.innerHTML = '<div class="admin-empty">Cargando...</div>';
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/access-requests`, { headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudieron cargar las solicitudes.');
        const { requests } = await res.json();
        document.getElementById('adminPendingCount').textContent = String(requests.length);
        refreshPendingCount();
        if (requests.length === 0) {
            list.innerHTML = '<div class="admin-empty">No hay solicitudes pendientes.</div>';
            return;
        }
        list.innerHTML = requests.map((r) => `
            <div class="admin-request-card" data-id="${r.id}">
                <div class="admin-request-info">
                    <div class="admin-request-name">${escapeHtml(r.name)}</div>
                    <div class="admin-request-meta">${escapeHtml(r.project) || 'Sin proyecto'} · ${new Date(r.created_at).toLocaleDateString('es-AR')}</div>
                    ${r.reason ? `<div class="admin-request-reason">${escapeHtml(r.reason)}</div>` : ''}
                </div>
                <div class="admin-request-creds">
                    <input type="text" class="admin-req-username" value="${escapeHtml(suggestUsername(r.name))}" placeholder="usuario">
                    <input type="text" class="admin-req-password" value="${escapeHtml(generatePassword())}" placeholder="contraseña">
                </div>
                <div class="admin-request-actions">
                    <button class="btn-admin-approve">✅ Aprobar y Generar Acceso</button>
                    <button class="btn-admin-reject">❌ Rechazar</button>
                </div>
            </div>
        `).join('');
        list.querySelectorAll('.btn-admin-approve').forEach((btn) => {
            btn.addEventListener('click', () => approveRequestFromCard(btn.closest('.admin-request-card')));
        });
        list.querySelectorAll('.btn-admin-reject').forEach((btn) => {
            btn.addEventListener('click', () => rejectRequestFromCard(btn.closest('.admin-request-card')));
        });
    } catch (err) {
        list.innerHTML = `<div class="admin-empty">❌ ${escapeHtml(friendlyErrorMessage(err))}</div>`;
    }
}

async function approveRequestFromCard(card) {
    const id = card.dataset.id;
    const username = card.querySelector('.admin-req-username').value.trim();
    const password = card.querySelector('.admin-req-password').value;
    if (!username || !password) { alert('Usuario y contraseña son obligatorios.'); return; }
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/access-requests/${id}/approve`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo aprobar la solicitud.');
        alert(`Acceso creado.\n\nUsuario: ${username}\nContraseña: ${password}\n\nComunicáselas a la persona - no se van a volver a mostrar acá.`);
        loadPendingRequests();
        loadActiveUsers();
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}

async function rejectRequestFromCard(card) {
    if (!confirm('¿Rechazar esta solicitud?')) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/access-requests/${card.dataset.id}/reject`, { method: 'POST', headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudo rechazar la solicitud.');
        loadPendingRequests();
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}

async function loadActiveUsers() {
    const tbody = document.getElementById('adminUsersTableBody');
    tbody.innerHTML = '<tr><td colspan="4" class="admin-empty">Cargando...</td></tr>';
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users`, { headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudieron cargar los usuarios.');
        const { users } = await res.json();
        if (users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="admin-empty">Todavía no hay usuarios.</td></tr>';
            return;
        }
        tbody.innerHTML = users.map((u) => `
            <tr data-username="${escapeHtml(u.username)}">
                <td>${escapeHtml(u.username)}</td>
                <td>${u.role === 'SUPERADMIN' ? '<span class="admin-role-badge">SUPERADMIN</span>' : 'USER'}</td>
                <td>${u.active ? '<span class="admin-status-active">Activo</span>' : '<span class="admin-status-inactive">Desactivado</span>'}</td>
                <td class="admin-users-actions">
                    <button class="btn-admin-mini btn-admin-reset" title="Resetear contraseña">🔑</button>
                    <button class="btn-admin-mini btn-admin-revoke" title="Revocar sesión">🚫</button>
                    <button class="btn-admin-mini btn-admin-deactivate" title="Desactivar acceso" ${u.role === 'SUPERADMIN' ? 'disabled' : ''}>🗑</button>
                </td>
            </tr>
        `).join('');
        tbody.querySelectorAll('.btn-admin-reset').forEach((btn) => {
            btn.addEventListener('click', () => resetPasswordFor(btn.closest('tr').dataset.username));
        });
        tbody.querySelectorAll('.btn-admin-revoke').forEach((btn) => {
            btn.addEventListener('click', () => revokeSessionFor(btn.closest('tr').dataset.username));
        });
        tbody.querySelectorAll('.btn-admin-deactivate').forEach((btn) => {
            btn.addEventListener('click', () => deactivateUserFor(btn.closest('tr').dataset.username));
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" class="admin-empty">❌ ${escapeHtml(friendlyErrorMessage(err))}</td></tr>`;
    }
}

async function resetPasswordFor(username) {
    if (!confirm(`¿Resetear la contraseña de "${username}"? Se va a cerrar su sesión actual.`)) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users/${username}/reset-password`, { method: 'POST', headers: authHeaders() });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo resetear la contraseña.');
        alert(`Nueva contraseña para ${username}:\n\n${data.password}\n\nComunicásela - no se va a volver a mostrar.`);
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}

async function revokeSessionFor(username) {
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users/${username}/revoke-session`, { method: 'POST', headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudo revocar la sesión.');
        alert(`Sesión de ${username} revocada.`);
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}

async function deactivateUserFor(username) {
    if (!confirm(`¿Desactivar el acceso de "${username}"? Va a dejar de poder iniciar sesión.`)) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users/${username}/deactivate`, { method: 'POST', headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudo desactivar el usuario.');
        loadActiveUsers();
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}
