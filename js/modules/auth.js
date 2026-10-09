import { BACKEND_URL } from '../config.js';
import { getApiKey, setApiKey, clearApiKey, authHeaders, setStorageAccount, readAccountValue, writeAccountValue } from '../utils/storage.js';
import { fetchWithTimeout } from '../utils/helpers.js';
import { flushWorkspace } from './workspaceSync.js';

// ============================================================
// SISTEMA DE USUARIOS: Auth Guard (modal de login + solicitar
// acceso) + panel de administración para el SUPERADMIN. Todo el
// HTML de acá se inyecta por JS al cargar la página (mismo módulo
// para index.html e historial.html, sin duplicar el markup).
// ============================================================

let currentUser = null; // { username, role, plan, unrestricted, daily_usage_seconds, limits } | null

export function getCurrentUser() { return currentUser; }
export function isSuperAdmin() { return currentUser?.role === 'SUPERADMIN'; }
/** true si la cuenta puede usar funciones PRO (Voiceover, Premiere/XML, batch) - SUPERADMIN cuenta como PRO. */
export function isPro() { return !!currentUser && (isSuperAdmin() || currentUser.unrestricted || currentUser.plan === 'PRO'); }
export function planLimits() { return currentUser?.limits || {}; }

/**
 * Chequeo previo (UX) del tope de clips por exportación en lote para FREE
 * (el backend es quien realmente lo hace cumplir, ver _check_batch_allowed
 * en main.py - esto solo evita mandar el request para nada y mostrar un
 * mensaje más claro que el error genérico del stream).
 */
export function checkBatchAllowed(clipCount) {
    if (isPro()) return true;
    const max = currentUser?.limits?.max_batch_clips || 3;
    if (clipCount > max) {
        alert(`El plan FREE permite exportar hasta ${max} clips por vez (pediste ${clipCount}). Pasate a PRO para exportar en lote sin este límite.`);
        return false;
    }
    return true;
}

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
                    <h2 class="auth-modal-title">Elegí cómo trabajar</h2>    <section class="access-plans" aria-label="Tres formas de usar AV Suite">
        <article><strong>Sin registro · Gratis</strong><span>30 min · 1 export / día</span><small>Probá con tu material, sin historial.</small></article>
        <article><strong>Con cuenta · Gratis</strong><span>60 min · 3 exports / día</span><small>Historial y proyectos guardados.</small></article>
        <article><strong>PRO · Studio completo</strong><span>Todas las herramientas de edición</span><small>Hoy con modelos gratuitos. APIs pagas a futuro.</small></article>
        <p>Los accesos gratuitos usan modelos con cuotas, posibles demoras y disponibilidad limitada. Cupos diarios con reinicio UTC.</p>
    </section>
<h3 class="auth-modal-title">Iniciar sesión</h3>
                    <form id="authLoginForm">
                        <label>Usuario</label>
                        <input type="text" id="authLoginUsername" autocomplete="username" required>
                        <label>Contraseña</label>
                        <input type="password" id="authLoginPassword" autocomplete="current-password" required>
                        <p class="auth-error" id="authLoginError" hidden></p>
                        <button type="submit" class="btn-auth-primary" id="authLoginSubmit">Iniciar Sesión</button>
                    </form>
                    <button type="button" class="btn-auth-primary" id="btnEnterGuest" style="margin-top:12px;background:var(--bg-input);color:var(--text-main);border:1px solid var(--border)">Entrar sin cuenta · FREE</button>
                    <p style="font-size:12px;color:var(--text-sub);text-align:center;margin:10px 0">Sin cuenta: 30 min y 1 export por día. Con cuenta gratis: 60 min y 3 exports por día, historial y proyectos. PRO: Studio completo. Hoy todos usan modelos gratuitos, sujetos a cuotas, demoras y disponibilidad; imágenes pueden no tener cuota gratuita.</p>
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
                        <thead><tr><th>Usuario</th><th>Rol</th><th>Plan</th><th>Consumo hoy</th><th>Estado</th><th></th></tr></thead>
                        <tbody id="adminUsersTableBody"><tr><td colspan="6" class="admin-empty">Cargando...</td></tr></tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
    document.body.append(...wrap.children);
    document.addEventListener('jobs-changed', () => refreshUsageBadge());

    document.getElementById('authLoginForm').addEventListener('submit', onLoginSubmit);
    document.getElementById('btnEnterGuest').addEventListener('click', onGuestSubmit);
    document.getElementById('authRequestForm').addEventListener('submit', onRequestSubmit);
    document.getElementById('btnShowRequestAccess').addEventListener('click', () => switchAuthView('request'));
    document.getElementById('btnForgotPassword').addEventListener('click', showForgotPasswordView);
    document.getElementById('btnBackToLogin').addEventListener('click', () => switchAuthView('login'));
    document.getElementById('btnCloseAdminDrawer').addEventListener('click', closeAdminDrawer);
    document.getElementById('adminDrawerOverlay').addEventListener('click', event => { if (event.target.id === 'adminDrawerOverlay') closeAdminDrawer(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeAdminDrawer(); });
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
async function onGuestSubmit() {
    const button = document.getElementById('btnEnterGuest');
    const error = document.getElementById('authLoginError');
    button.disabled = true; error.hidden = true;
    try {
        const response = await fetchWithTimeout(`${BACKEND_URL}/auth/guest`, { method: 'POST' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'No se pudo iniciar el acceso FREE.');
        setApiKey(data.token, true);
        currentUser = data;
        hideLoginModal(); renderUserUI();
    } catch (err) { error.textContent = friendlyErrorMessage(err); error.hidden = false; }
    finally { button.disabled = false; }
}

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
        currentUser = data;
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
    document.dispatchEvent(new CustomEvent('editor-flush'));
    await flushWorkspace();
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
 * modal de login. Si falla la verificación, conserva el token y muestra el ingreso con
 * un mensaje de reintento. La interfaz de trabajo se muestra después de
 * validar el acceso para no presentar el dashboard FREE a una cuenta PRO.
 */
export async function initAuthGuard() {
    injectAuthUI();
    const token = getApiKey();
    // Sin token igual se consulta: en modo local PRO (LOCAL_PRO_MODE en el
    // backend) localhost entra directo, sin login. Si no, responde 401.
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/auth/check`, { headers: authHeaders() });
        if (res.status === 401) {
            clearApiKey();
            showLoginModal();
            return;
        }
        if (!res.ok) { showLoginModal(); return; }
        const data = await res.json();
        if (data.username) {
            currentUser = data;
        }
        hideLoginModal();
        renderUserUI();
    } catch (err) {
        console.warn('No se pudo verificar la sesión (¿servidor dormido?):', err);
        showLoginModal();
        if (!token) return;
        const message = document.getElementById('authLoginError');
        message.textContent = 'No se pudo verificar tu sesión. Esperá unos segundos y reintentá.'; message.hidden = false;
    }
}

// ------------------------------------------------------------
// HEADER: nombre de usuario + badge SUPERUSER + botón Panel de Control
// ------------------------------------------------------------
function initHeaderActions() {
    const nav = document.getElementById('headerNav');
    if (!nav || document.getElementById('navProjects')) return;
    const button = document.createElement('button');
    button.type = 'button'; button.id = 'navProjects'; button.className = 'nav-link'; button.textContent = 'Proyectos';
    button.addEventListener('click', async () => {
        const { closeStudio } = await import('./onlineStudio.js'); closeStudio();
        const { openProjectsManager } = await import('./projects.js'); openProjectsManager();
    });
    nav.prepend(button);
    document.getElementById('navSettings')?.addEventListener('click', openSettings);
    nav.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            document.getElementById('accountDropdown')?.classList.remove('open');
            document.getElementById('navAccountLink')?.setAttribute('aria-expanded', 'false');
        }
    });
}

function openSettings() {
    let dialog = document.getElementById('accountSettings');
    if (!dialog) {
        dialog = document.createElement('dialog'); dialog.id = 'accountSettings'; dialog.className = 'account-settings';
        dialog.innerHTML = `<form method="dialog"><header><h2>Ajustes de tu espacio</h2><button aria-label="Cerrar ajustes">✕</button></header></form>
        <p id="settingsAccount"></p><p>Todos los modelos siguen sujetos a la disponibilidad del proveedor. Las APIs pagas se habilitarán en una etapa futura.</p>
        <label><input type="checkbox" id="settingsCompact"> Usar controles compactos en el Studio</label>

        <button type="button" class="studio-nav-btn" id="settingsRefresh">Actualizar sesión y permisos</button><p id="settingsStatus" role="status"></p>`;
        document.body.append(dialog);
        document.getElementById('settingsCompact').addEventListener('change', event => {
            writeAccountValue('compact_studio', event.target.checked); document.body.classList.toggle('studio-compact', event.target.checked);
        });
        document.getElementById('settingsRefresh').addEventListener('click', async () => {
            const button = document.getElementById('settingsRefresh'); button.disabled = true;
            try {
                const response = await fetchWithTimeout(`${BACKEND_URL}/auth/check`, { headers: authHeaders() });
                const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'No se pudo actualizar la sesión.');
                currentUser = data; renderUserUI();
                document.getElementById('settingsAccount').textContent = `${currentUser.username} · ${isSuperAdmin() ? 'Administrador · Studio completo' : currentUser.plan}`;
                document.getElementById('settingsStatus').textContent = 'Sesión y permisos actualizados.';
            } catch (error) { document.getElementById('settingsStatus').textContent = friendlyErrorMessage(error); }
            finally { button.disabled = false; }
        });
    }
    document.getElementById('settingsAccount').textContent = `${currentUser?.username || 'Invitado'} · ${isSuperAdmin() ? 'Administrador · Studio completo' : currentUser?.plan || 'FREE'}`;
    document.getElementById('settingsCompact').checked = !!readAccountValue('compact_studio', false);
    document.getElementById('settingsStatus').textContent = '';
    dialog.showModal();
}

function renderUserUI() {
    initHeaderActions();
    if (currentUser?.username) {
        setStorageAccount(currentUser.username, currentUser.role === 'GUEST');
        const access = `${currentUser.role}:${currentUser.plan}:${!!currentUser.unrestricted}`;
        const changedAccess = document.body.dataset.studioAccess !== access;
        document.body.dataset.studioAccess = access;
        if (document.body.dataset.studioAccount !== currentUser.username) {
            document.body.dataset.studioAccount = currentUser.username;
            document.dispatchEvent(new CustomEvent('auth-ready', { detail: currentUser }));
        } else if (changedAccess) {
            document.dispatchEvent(new CustomEvent('auth-updated', { detail: currentUser }));
        }
    }
    document.body.classList.toggle('studio-compact', !!readAccountValue('compact_studio', false));
    const accountLabel = document.getElementById('navAccountLabel');
    const accountLink = document.getElementById('navAccountLink');
    if (accountLabel && currentUser) accountLabel.textContent = currentUser.role === 'GUEST' ? 'Invitado · FREE' : currentUser.username;
    document.querySelectorAll('a[href="/historial"]').forEach(link => link.style.display = currentUser?.role === 'GUEST' ? 'none' : '');
    document.querySelectorAll('a[href="/historial"], a[data-studio-history]').forEach(link => { link.dataset.studioHistory = '1'; link.href = isPro() ? '/?studio=projects' : '/historial'; });
    if (isPro() && location.pathname === '/historial') { location.replace('/?studio=projects'); return; }
    if (currentUser?.role === 'GUEST' && location.pathname === '/historial') { location.replace('/'); return; }
    if (accountLink && !accountLink.dataset.wired) {
        accountLink.dataset.wired = '1';
        accountLink.parentElement.style.position = 'relative';
        accountLink.parentElement.insertAdjacentHTML('beforeend', `
            <div class="account-dropdown" id="accountDropdown">
                <button type="button" id="btnOpenProjects">📁 Proyectos</button>
                <button type="button" id="btnLogout">Cerrar sesión</button>
            </div>
        `);
        accountLink.addEventListener('click', (e) => {
            e.stopPropagation();
            const open = document.getElementById('accountDropdown').classList.toggle('open');
            accountLink.setAttribute('aria-expanded', String(open));
        });
        document.getElementById('btnOpenProjects').addEventListener('click', async (e) => {
            e.stopPropagation();
            document.getElementById('accountDropdown').classList.remove('open');
            const { closeStudio } = await import('./onlineStudio.js'); closeStudio();
            const { openProjectsManager } = await import('./projects.js');
            openProjectsManager();
        });
        document.getElementById('btnLogout').addEventListener('click', (e) => {
            e.stopPropagation();
            logout();
        });
        document.addEventListener('click', () => {
            document.getElementById('accountDropdown')?.classList.remove('open');
            accountLink.setAttribute('aria-expanded', 'false');
        });
    }

    const nav = document.getElementById('headerNav');
    const projectsButton = document.getElementById('btnOpenProjects');
    if (document.getElementById('navProjects')) document.getElementById('navProjects').hidden = currentUser?.role === 'GUEST';
    if (projectsButton) projectsButton.style.display = currentUser?.role === 'GUEST' ? 'none' : '';
    const logoutButton = document.getElementById('btnLogout');
    if (logoutButton && currentUser?.role === 'GUEST') logoutButton.textContent = 'Salir / Ingresar con cuenta';
    if (!nav || !currentUser) return;
    document.body.classList.remove('access-pending');
    const adminButton = document.getElementById('btnOpenAdminPanel');
    const adminBadge = document.getElementById('adminBadge');
    if (adminButton) adminButton.hidden = !isSuperAdmin();
    if (adminBadge) adminBadge.hidden = !isSuperAdmin();

    renderPlanBadge(nav);

    if (isSuperAdmin() && !document.getElementById('adminBadge')) {
        const badge = document.createElement('span');
        badge.className = 'admin-badge';
        badge.id = 'adminBadge';
        badge.textContent = 'ADMINISTRADOR';

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

/**
 * Badge de plan/consumo en el header ("PRO" o "FREE · 12/60 min hoy").
 * Puramente informativo - el enforcement real es del backend (ver main.py),
 * esto solo evita que la persona se entere del límite recién cuando un
 * análisis le rebota con un error.
 */
function renderPlanBadge(nav) {
    if (!currentUser || currentUser.plan == null) return;
    let badge = document.getElementById('planBadge');
    if (!badge) {
        badge = document.createElement('span');
        badge.id = 'planBadge';
        badge.className = 'plan-badge';
        nav.prepend(badge);
    }
    if (isPro()) {
        badge.textContent = 'PRO';
        badge.className = 'plan-badge plan-badge-pro';
        badge.title = 'Plan PRO: sin límite diario, Voiceover/Premiere/lote habilitados.';
    } else {
        const used = Math.round((currentUser.daily_usage_seconds || 0) / 60);
        const limitMin = Math.round((currentUser.limits?.daily_seconds || 3600) / 60);
        const maxExports = currentUser.limits?.daily_exports || (currentUser.role === 'GUEST' ? 1 : 3);
        badge.textContent = `${currentUser.role === 'GUEST' ? 'INVITADO' : 'CUENTA GRATIS'} · ${used}/${limitMin} min · ${currentUser.daily_exports_used || 0}/${maxExports} exports hoy`;
        badge.className = 'plan-badge plan-badge-free';
        badge.title = 'Cupos diarios con reinicio UTC. Modelos gratuitos: cuotas, demoras, calidad variable y disponibilidad limitada.';
    }
}

/** Re-consulta /auth/check para refrescar el consumo mostrado en el badge (ej. después de un análisis exitoso). */
export async function refreshUsageBadge() {
    if (!currentUser) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/auth/check`, { headers: authHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        if (data.username) {
            currentUser = { ...currentUser, ...data };
            renderUserUI();
        }
    } catch (e) { /* silencioso */ }
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
                    <select class="admin-req-plan" title="Plan con el que arranca esta cuenta">
                        <option value="FREE" selected>Plan FREE</option>
                        <option value="PRO">Plan PRO</option>
                    </select>
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
    const plan = card.querySelector('.admin-req-plan').value;
    if (!username || !password) { alert('Usuario y contraseña son obligatorios.'); return; }
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/access-requests/${id}/approve`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, plan })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo aprobar la solicitud.');
        alert(`Acceso creado (plan ${plan}).\n\nUsuario: ${username}\nContraseña: ${password}\n\nComunicáselas a la persona - no se van a volver a mostrar acá.`);
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
                <td>${u.role === 'SUPERADMIN' ? '<span class="admin-role-badge">Administrador</span>' : 'Usuario'}</td>
                <td>
                    ${u.role === 'SUPERADMIN'
                        ? '<span class="plan-badge plan-badge-pro" style="position:static;">PRO</span>'
                        : `<button class="btn-admin-mini btn-admin-toggle-plan" data-plan="${escapeHtml(u.plan || 'FREE')}" title="Click para cambiar de plan">
                            <span class="plan-badge ${u.plan === 'PRO' ? 'plan-badge-pro' : 'plan-badge-free'}" style="position:static;">${escapeHtml(u.plan || 'FREE')}</span>
                           </button>`}
                </td>
                <td>${Math.round((u.daily_usage_seconds || 0) / 60)} min</td>
                <td>${u.active ? '<span class="admin-status-active">Activo</span>' : '<span class="admin-status-inactive">Desactivado</span>'}</td>
                <td class="admin-users-actions">
                    <button class="btn-admin-mini btn-admin-reset" title="Resetear contraseña">🔑</button>
                    <button class="btn-admin-mini btn-admin-revoke" title="Revocar sesión">🚫</button>
                    ${u.active
                        ? `<button class="btn-admin-mini btn-admin-deactivate" title="Desactivar acceso" ${u.role === 'SUPERADMIN' ? 'disabled' : ''}>🗑</button>`
                        : `<button class="btn-admin-mini btn-admin-activate" title="Reactivar acceso">♻️</button>`}
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
        tbody.querySelectorAll('.btn-admin-activate').forEach((btn) => {
            btn.addEventListener('click', () => activateUserFor(btn.closest('tr').dataset.username));
        });
        tbody.querySelectorAll('.btn-admin-toggle-plan').forEach((btn) => {
            btn.addEventListener('click', () => togglePlanFor(btn.closest('tr').dataset.username, btn.dataset.plan));
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

async function activateUserFor(username) {
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users/${username}/activate`, { method: 'POST', headers: authHeaders() });
        if (!res.ok) throw new Error('No se pudo reactivar el usuario.');
        loadActiveUsers();
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}

async function togglePlanFor(username, currentPlan) {
    const newPlan = currentPlan === 'PRO' ? 'FREE' : 'PRO';
    if (!confirm(`¿Cambiar a "${username}" de ${currentPlan} a ${newPlan}?`)) return;
    try {
        const res = await fetchWithTimeout(`${BACKEND_URL}/admin/users/${username}/set-plan`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ plan: newPlan })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'No se pudo cambiar el plan.');
        loadActiveUsers();
    } catch (err) {
        alert('❌ ' + friendlyErrorMessage(err));
    }
}
